import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.bw_learner.expression_vector_index import ExpressionVectorIndex


class ExpressionVectorIndexTest(unittest.IsolatedAsyncioTestCase):
    async def test_rebuild_discards_results_if_active_profile_changes_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "expression_vector_index.json"
            index_path.write_text(
                '{"version": 1, "expressions": [{"id": 99}]}',
                encoding="utf-8",
            )
            index = ExpressionVectorIndex(index_path)
            candidates = [{"id": 1, "situation": "场景", "style": "风格"}]
            expected_profile = SimpleNamespace(signature="profile-current", dimension=2)

            with (
                patch("src.bw_learner.expression_vector_index._has_embedding_model_configured", return_value=True),
                patch(
                    "src.bw_learner.expression_vector_index._get_embedding_with_model",
                    new=AsyncMock(return_value=([1.0, 0.0], "profile-current")),
                ),
                patch(
                    "src.bw_learner.expression_vector_index.is_active_embedding_profile",
                    return_value=False,
                ),
            ):
                rebuilt = await index.rebuild(candidates, expected_profile=expected_profile)

            self.assertFalse(rebuilt)
            self.assertEqual(index_path.read_text(encoding="utf-8"), '{"version": 1, "expressions": [{"id": 99}]}')

    async def test_rebuild_writes_the_complete_current_profile_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "expression_vector_index.json"
            index_path.write_text('{"version": 1, "expressions": []}', encoding="utf-8")
            index = ExpressionVectorIndex(index_path)
            candidates = [
                {"id": 1, "source_id": "a", "situation": "场景一", "style": "风格一", "count": 1},
                {"id": 2, "source_id": "b", "situation": "场景二", "style": "风格二", "count": 2},
            ]
            profile = SimpleNamespace(signature="profile-current", dimension=2)

            with (
                patch("src.bw_learner.expression_vector_index._has_embedding_model_configured", return_value=True),
                patch(
                    "src.bw_learner.expression_vector_index._get_embedding_with_model",
                    new=AsyncMock(return_value=([1.0, 0.0], "profile-current")),
                ),
            ):
                rebuilt = await index.rebuild(candidates, expected_profile=profile)

            self.assertTrue(rebuilt)
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["embedding_signature"], "profile-current")
            self.assertEqual(payload["embedding_dimension"], 2)
            self.assertEqual(len(payload["expressions"]), 2)
            self.assertEqual({entry["embedding_model"] for entry in payload["expressions"]}, {"profile-current"})

    async def test_select_candidates_prefers_closest_embedding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index = ExpressionVectorIndex(Path(temp_dir) / "expression_vector_index.json")
            candidates = [
                {
                    "id": 1,
                    "source_id": "chat-a",
                    "situation": "技术问题排查",
                    "style": "先确认关键配置",
                    "count": 3,
                },
                *[
                    {
                        "id": item_id,
                        "source_id": "chat-a",
                        "situation": f"日常闲聊 {item_id}",
                        "style": f"轻松接话 {item_id}",
                        "count": 1,
                    }
                    for item_id in range(2, 12)
                ],
            ]

            async def fake_embedding(text: str, request_type: str):
                if request_type == "expression.vector.query":
                    return [1.0, 0.0], "fake-embedding"
                if "技术问题排查" in text:
                    return [1.0, 0.0], "fake-embedding"
                return [0.0, 1.0], "fake-embedding"

            with (
                patch("src.bw_learner.expression_vector_index._has_embedding_model_configured", return_value=True),
                patch(
                    "src.bw_learner.expression_vector_index._get_embedding_with_model",
                    new=AsyncMock(side_effect=fake_embedding),
                ),
            ):
                results = await index.select_candidates(
                    candidates=candidates,
                    query_text="需要排查技术配置问题",
                    limit=5,
                )

            self.assertIsNotNone(results)
            self.assertEqual(results[0]["id"], 1)
            self.assertTrue((Path(temp_dir) / "expression_vector_index.json").exists())

    async def test_rebuilds_cached_vectors_after_profile_and_dimension_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "expression_vector_index.json"
            index = ExpressionVectorIndex(index_path)
            candidates = [
                {
                    "id": item_id,
                    "source_id": "chat-a",
                    "situation": f"情景 {item_id}",
                    "style": f"风格 {item_id}",
                    "count": 1,
                }
                for item_id in range(1, 11)
            ]
            current_profile = {"signature": "profile-v1", "dimension": 2}
            request_types: list[str] = []

            async def fake_embedding(_text: str, request_type: str):
                request_types.append(request_type)
                dimension = current_profile["dimension"]
                return [1.0, *([0.0] * (dimension - 1))], current_profile["signature"]

            with (
                patch("src.bw_learner.expression_vector_index._has_embedding_model_configured", return_value=True),
                patch(
                    "src.bw_learner.expression_vector_index._get_embedding_with_model",
                    new=AsyncMock(side_effect=fake_embedding),
                ),
            ):
                await index.select_candidates(candidates=candidates, query_text="测试", limit=5)

                request_types.clear()
                current_profile["signature"] = "profile-v2"
                await index.select_candidates(candidates=candidates, query_text="测试", limit=5)
                self.assertEqual(request_types.count("expression.vector.index"), len(candidates))
                same_dimension_payload = json.loads(index_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    {entry["embedding_model"] for entry in same_dimension_payload["expressions"]},
                    {"profile-v2"},
                )
                self.assertEqual(
                    {entry["embedding_dimension"] for entry in same_dimension_payload["expressions"]},
                    {2},
                )

                request_types.clear()
                current_profile.update(signature="profile-v3", dimension=3)
                await index.select_candidates(candidates=candidates, query_text="测试", limit=5)
                self.assertEqual(request_types.count("expression.vector.index"), len(candidates))
                changed_dimension_payload = json.loads(index_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    {entry["embedding_model"] for entry in changed_dimension_payload["expressions"]},
                    {"profile-v3"},
                )
                self.assertEqual(
                    {entry["embedding_dimension"] for entry in changed_dimension_payload["expressions"]},
                    {3},
                )


if __name__ == "__main__":
    unittest.main()
