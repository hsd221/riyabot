import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.chat.emoji_system.emoji_vector_index import (
    EmojiUsageSceneVectorCandidate,
    EmojiUsageSceneVectorIndex,
    EmojiVectorCandidate,
    EmojiVectorIndex,
)


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

    async def test_incomplete_backfill_does_not_return_partial_emotion_matches(self) -> None:
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
                if "普通情绪00" in text:
                    return [0.9, 0.435889894], "fake-embedding"
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
            self.assertEqual(
                [match.emoji_hash for match in second_result or []],
                ["emoji-target", "emoji-00"],
            )

    async def test_rebuilds_emotion_cache_after_profile_and_dimension_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "emoji_vector_index.json"
            index = EmojiVectorIndex(index_path)
            candidate = EmojiVectorCandidate("emoji-happy", ("开心",))
            current_profile = {"signature": "profile-v1", "dimension": 2}
            request_types: list[str] = []

            async def fake_embedding(_text: str, request_type: str):
                request_types.append(request_type)
                dimension = current_profile["dimension"]
                return [1.0, *([0.0] * (dimension - 1))], current_profile["signature"]

            with (
                patch("src.chat.emoji_system.emoji_vector_index._has_embedding_model_configured", return_value=True),
                patch(
                    "src.chat.emoji_system.emoji_vector_index._get_embedding_with_model",
                    new=AsyncMock(side_effect=fake_embedding),
                ),
            ):
                self.assertTrue(await index.upsert(candidate.emoji_hash, candidate.emotions))

                request_types.clear()
                current_profile["signature"] = "profile-v2"
                await index.search(query_text="开心", candidates=[candidate], similarity_threshold=0.8)
                self.assertEqual(request_types.count("emoji.vector.index"), 1)
                same_dimension_payload = json.loads(index_path.read_text(encoding="utf-8"))
                self.assertEqual(same_dimension_payload["emojis"][0]["embedding_model"], "profile-v2")
                self.assertEqual(same_dimension_payload["emojis"][0]["embedding_dimension"], 2)

                request_types.clear()
                current_profile.update(signature="profile-v3", dimension=3)
                await index.search(query_text="开心", candidates=[candidate], similarity_threshold=0.8)
                self.assertEqual(request_types.count("emoji.vector.index"), 1)
                changed_dimension_payload = json.loads(index_path.read_text(encoding="utf-8"))
                self.assertEqual(changed_dimension_payload["emojis"][0]["embedding_model"], "profile-v3")
                self.assertEqual(changed_dimension_payload["emojis"][0]["embedding_dimension"], 3)


class EmojiUsageSceneVectorIndexTest(unittest.IsolatedAsyncioTestCase):
    async def test_each_human_usage_scene_is_indexed_and_ranked_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "emoji_usage_scene_vector_index.json"
            index = EmojiUsageSceneVectorIndex(index_path)

            async def fake_embedding(text: str, request_type: str):
                if request_type == "emoji.usage_scene.vector.query" or "自嘲失败" in text:
                    return [1.0, 0.0], "fake-embedding"
                return [0.0, 1.0], "fake-embedding"

            candidates = [
                EmojiUsageSceneVectorCandidate(1, "emoji-a", "对方严肃批评时表示歉意"),
                EmojiUsageSceneVectorCandidate(2, "emoji-a", "对方自嘲失败时轻松接梗"),
                EmojiUsageSceneVectorCandidate(3, "emoji-b", "对方难过时安慰"),
            ]
            with (
                patch("src.chat.emoji_system.emoji_vector_index._has_embedding_model_configured", return_value=True),
                patch(
                    "src.chat.emoji_system.emoji_vector_index._get_embedding_with_model",
                    new=AsyncMock(side_effect=fake_embedding),
                ),
            ):
                matches = await index.search(
                    query_text="接住自嘲",
                    candidates=candidates,
                    limit=5,
                    similarity_threshold=0.8,
                )

            self.assertIsNotNone(matches)
            self.assertEqual([match.scene_id for match in matches or []], [2])
            self.assertEqual((matches or [])[0].emoji_hash, "emoji-a")
            self.assertEqual((matches or [])[0].scene, "对方自嘲失败时轻松接梗")
            self.assertTrue(index_path.exists())

    async def test_incomplete_scene_backfill_is_unavailable_until_all_candidates_are_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index = EmojiUsageSceneVectorIndex(Path(temp_dir) / "emoji_usage_scene_vector_index.json")
            candidates = [
                EmojiUsageSceneVectorCandidate(
                    index_number + 1,
                    f"emoji-{index_number:02d}",
                    f"普通场景{index_number:02d}",
                )
                for index_number in range(30)
            ]
            candidates.append(EmojiUsageSceneVectorCandidate(31, "emoji-target", "目标场景"))

            async def fake_embedding(text: str, request_type: str):
                if request_type == "emoji.usage_scene.vector.query" or "目标场景" in text:
                    return [1.0, 0.0], "fake-embedding"
                if "普通场景00" in text:
                    return [0.8, 0.6], "fake-embedding"
                return [0.0, 1.0], "fake-embedding"

            with (
                patch("src.chat.emoji_system.emoji_vector_index._has_embedding_model_configured", return_value=True),
                patch(
                    "src.chat.emoji_system.emoji_vector_index._get_embedding_with_model",
                    new=AsyncMock(side_effect=fake_embedding),
                ),
            ):
                first_result = await index.search(
                    query_text="目标场景",
                    candidates=candidates,
                    limit=5,
                    similarity_threshold=0.8,
                )
                second_result = await index.search(
                    query_text="目标场景",
                    candidates=candidates,
                    limit=5,
                    similarity_threshold=0.8,
                )

            self.assertIsNone(first_result)
            self.assertEqual([match.scene_id for match in second_result or []], [31, 1])

    async def test_rebuilds_scene_cache_after_profile_and_dimension_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "emoji_usage_scene_vector_index.json"
            index = EmojiUsageSceneVectorIndex(index_path)
            candidate = EmojiUsageSceneVectorCandidate(1, "emoji-happy", "对方开心时一起庆祝")
            current_profile = {"signature": "profile-v1", "dimension": 2}
            request_types: list[str] = []

            async def fake_embedding(_text: str, request_type: str):
                request_types.append(request_type)
                dimension = current_profile["dimension"]
                return [1.0, *([0.0] * (dimension - 1))], current_profile["signature"]

            with (
                patch("src.chat.emoji_system.emoji_vector_index._has_embedding_model_configured", return_value=True),
                patch(
                    "src.chat.emoji_system.emoji_vector_index._get_embedding_with_model",
                    new=AsyncMock(side_effect=fake_embedding),
                ),
            ):
                await index.search(query_text="一起庆祝", candidates=[candidate], similarity_threshold=0.8)

                request_types.clear()
                current_profile["signature"] = "profile-v2"
                await index.search(query_text="一起庆祝", candidates=[candidate], similarity_threshold=0.8)
                self.assertEqual(request_types.count("emoji.usage_scene.vector.index"), 1)
                same_dimension_payload = json.loads(index_path.read_text(encoding="utf-8"))
                self.assertEqual(same_dimension_payload["scenes"][0]["embedding_model"], "profile-v2")
                self.assertEqual(same_dimension_payload["scenes"][0]["embedding_dimension"], 2)

                request_types.clear()
                current_profile.update(signature="profile-v3", dimension=3)
                await index.search(query_text="一起庆祝", candidates=[candidate], similarity_threshold=0.8)
                self.assertEqual(request_types.count("emoji.usage_scene.vector.index"), 1)
                changed_dimension_payload = json.loads(index_path.read_text(encoding="utf-8"))
                self.assertEqual(changed_dimension_payload["scenes"][0]["embedding_model"], "profile-v3")
                self.assertEqual(changed_dimension_payload["scenes"][0]["embedding_dimension"], 3)


if __name__ == "__main__":
    unittest.main()
