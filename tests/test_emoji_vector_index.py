import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.chat.emoji_system.emoji_vector_index import EmojiVectorCandidate, EmojiVectorIndex


class EmojiVectorIndexTest(unittest.IsolatedAsyncioTestCase):
    async def test_upserted_emotion_vectors_are_ranked_and_filtered_by_similarity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "emoji_vector_index.json"
            index = EmojiVectorIndex(index_path)

            async def fake_embedding(text: str, request_type: str):
                if request_type == "emoji.vector.query":
                    return [1.0, 0.0], "fake-embedding"
                if "轻松调侃" in text:
                    return [1.0, 0.0], "fake-embedding"
                return [0.0, 1.0], "fake-embedding"

            with (
                patch("src.chat.emoji_system.emoji_vector_index._has_embedding_model_configured", return_value=True),
                patch(
                    "src.chat.emoji_system.emoji_vector_index._get_embedding_with_model",
                    new=AsyncMock(side_effect=fake_embedding),
                ),
            ):
                self.assertTrue(await index.upsert("emoji-happy", ["轻松调侃", "开心"]))
                self.assertTrue(await index.upsert("emoji-sad", ["难过", "委屈"]))

                matches = await index.search(
                    query_text="轻松调侃",
                    candidates=[
                        EmojiVectorCandidate("emoji-happy", ("轻松调侃", "开心")),
                        EmojiVectorCandidate("emoji-sad", ("难过", "委屈")),
                    ],
                    limit=10,
                    similarity_threshold=0.8,
                )

            self.assertIsNotNone(matches)
            self.assertEqual([match.emoji_hash for match in matches or []], ["emoji-happy"])
            self.assertEqual((matches or [])[0].emotions, ("轻松调侃", "开心"))
            self.assertAlmostEqual((matches or [])[0].similarity, 1.0)
            self.assertTrue(index_path.exists())

    async def test_search_returns_none_when_embedding_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index = EmojiVectorIndex(Path(temp_dir) / "emoji_vector_index.json")

            with patch(
                "src.chat.emoji_system.emoji_vector_index._has_embedding_model_configured",
                return_value=False,
            ):
                result = await index.search(
                    query_text="开心",
                    candidates=[EmojiVectorCandidate("emoji-happy", ("开心",))],
                )

            self.assertIsNone(result)

    async def test_invalid_embedding_response_is_treated_as_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "emoji_vector_index.json"
            index = EmojiVectorIndex(index_path)

            with (
                patch("src.chat.emoji_system.emoji_vector_index._has_embedding_model_configured", return_value=True),
                patch(
                    "src.chat.emoji_system.emoji_vector_index._get_embedding_with_model",
                    new=AsyncMock(return_value=([float("nan"), 0.0], "fake-embedding")),
                ),
            ):
                result = await index.search(
                    query_text="开心",
                    candidates=[EmojiVectorCandidate("emoji-happy", ("开心",))],
                )

            self.assertIsNone(result)
            self.assertFalse(index_path.exists())

    async def test_malformed_index_metadata_is_rebuilt_from_current_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "emoji_vector_index.json"
            index_path.write_text('{"version": "broken", "emojis": "invalid"}', encoding="utf-8")
            index = EmojiVectorIndex(index_path)

            with (
                patch("src.chat.emoji_system.emoji_vector_index._has_embedding_model_configured", return_value=True),
                patch(
                    "src.chat.emoji_system.emoji_vector_index._get_embedding_with_model",
                    new=AsyncMock(return_value=([1.0, 0.0], "fake-embedding")),
                ),
            ):
                result = await index.search(
                    query_text="开心",
                    candidates=[EmojiVectorCandidate("emoji-happy", ("开心",))],
                    similarity_threshold=0.8,
                )

            self.assertEqual([match.emoji_hash for match in result or []], ["emoji-happy"])

    async def test_search_returns_empty_when_vectors_work_but_no_item_reaches_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index = EmojiVectorIndex(Path(temp_dir) / "emoji_vector_index.json")

            async def fake_embedding(text: str, request_type: str):
                if request_type == "emoji.vector.query":
                    return [1.0, 0.0], "fake-embedding"
                return [0.0, 1.0], "fake-embedding"

            with (
                patch("src.chat.emoji_system.emoji_vector_index._has_embedding_model_configured", return_value=True),
                patch(
                    "src.chat.emoji_system.emoji_vector_index._get_embedding_with_model",
                    new=AsyncMock(side_effect=fake_embedding),
                ),
            ):
                result = await index.search(
                    query_text="开心",
                    candidates=[EmojiVectorCandidate("emoji-sad", ("难过",))],
                    similarity_threshold=0.8,
                )

            self.assertEqual(result, [])

    async def test_incomplete_legacy_backfill_is_unavailable_until_remaining_candidates_are_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index = EmojiVectorIndex(Path(temp_dir) / "emoji_vector_index.json")
            candidates = [
                EmojiVectorCandidate(f"emoji-{index_number:02d}", (f"普通情绪{index_number:02d}",))
                for index_number in range(30)
            ]
            candidates.append(EmojiVectorCandidate("emoji-target", ("目标情绪",)))

            async def fake_embedding(text: str, request_type: str):
                if request_type == "emoji.vector.query" or "目标情绪" in text:
                    return [1.0, 0.0], "fake-embedding"
                return [0.0, 1.0], "fake-embedding"

            with (
                patch("src.chat.emoji_system.emoji_vector_index._has_embedding_model_configured", return_value=True),
                patch(
                    "src.chat.emoji_system.emoji_vector_index._get_embedding_with_model",
                    new=AsyncMock(side_effect=fake_embedding),
                ),
            ):
                first_result = await index.search(
                    query_text="目标情绪",
                    candidates=candidates,
                    similarity_threshold=0.8,
                )
                second_result = await index.search(
                    query_text="目标情绪",
                    candidates=candidates,
                    similarity_threshold=0.8,
                )

            self.assertIsNone(first_result)
            self.assertEqual([match.emoji_hash for match in second_result or []], ["emoji-target"])


if __name__ == "__main__":
    unittest.main()
