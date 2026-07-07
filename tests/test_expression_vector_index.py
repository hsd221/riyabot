import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.bw_learner.expression_vector_index import ExpressionVectorIndex


class ExpressionVectorIndexTest(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
