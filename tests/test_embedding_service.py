import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.llm_models import embedding


class EmbeddingServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_embed_text_uses_stable_task_and_returns_profile(self) -> None:
        llm = SimpleNamespace(get_embedding=AsyncMock(return_value=([0.1, 0.2], "runtime-model")))
        profile = SimpleNamespace(signature="profile-signature", dimension=2)
        stable_task = object()

        with (
            patch.object(embedding, "get_stable_embedding_task_config", return_value=stable_task),
            patch.object(embedding, "get_embedding_profile", return_value=profile) as get_profile,
            patch.object(embedding, "LLMRequest", Mock(return_value=llm)) as request_cls,
        ):
            result = await embedding.embed_text("hello", request_type="vector.test", expected_dimension=2)

        self.assertEqual(result.vector, [0.1, 0.2])
        self.assertIs(result.profile, profile)
        request_cls.assert_called_once_with(model_set=stable_task, request_type="vector.test")
        llm.get_embedding.assert_awaited_once_with("hello")
        get_profile.assert_called_once_with(2)

    async def test_embed_text_rejects_unexpected_dimension(self) -> None:
        llm = SimpleNamespace(get_embedding=AsyncMock(return_value=([0.1, 0.2], "runtime-model")))

        with patch.object(embedding, "LLMRequest", Mock(return_value=llm)):
            with self.assertRaisesRegex(ValueError, "dimension"):
                await embedding.embed_text("hello", expected_dimension=3)

    async def test_embed_text_rejects_non_finite_values(self) -> None:
        llm = SimpleNamespace(get_embedding=AsyncMock(return_value=([float("nan"), 0.2], "runtime-model")))

        with patch.object(embedding, "LLMRequest", Mock(return_value=llm)):
            with self.assertRaisesRegex(ValueError, "finite"):
                await embedding.embed_text("hello")

    async def test_embed_text_passes_runtime_snapshot_to_request_and_marks_vector(self) -> None:
        llm = SimpleNamespace(get_embedding=AsyncMock(return_value=([0.1, 0.2], "runtime-model")))
        profile = SimpleNamespace(signature="profile-signature", dimension=2)
        runtime = SimpleNamespace(model_config=object(), task_config=object(), profile=profile)

        with patch.object(embedding, "LLMRequest", Mock(return_value=llm)) as request_cls:
            result = await embedding.embed_text("hello", runtime=runtime)

        self.assertEqual(result.vector, [0.1, 0.2])
        self.assertEqual(result.vector.embedding_signature, "profile-signature")
        self.assertEqual(result.vector.embedding_dimension, 2)
        self.assertIs(request_cls.call_args.kwargs["model_config_override"], runtime.model_config)


if __name__ == "__main__":
    unittest.main()
