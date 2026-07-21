import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.llm_models import embedding_profile


class EmbeddingProfileTest(unittest.TestCase):
    @staticmethod
    def _config(
        model_identifier: str = "model-v1",
        model_names: list[str] | None = None,
        *,
        provider_name: str = "provider-a",
        client_type: str = "openai",
        base_url: str = "https://example.invalid/v1",
        extra_params: dict[str, object] | None = None,
    ):
        names = model_names or ["embedding-primary"]
        task = SimpleNamespace(model_list=names, selection_strategy="random", slow_threshold=5.0)
        model_info = SimpleNamespace(
            name="embedding-primary",
            model_identifier=model_identifier,
            api_provider=provider_name,
            extra_params=extra_params or {"dimensions": 1024},
        )
        provider = SimpleNamespace(client_type=client_type, base_url=base_url)
        return SimpleNamespace(
            model_task_config=SimpleNamespace(embedding=task),
            get_model_info=lambda name: model_info,
            get_provider=lambda name: provider,
        )

    def test_model_identifier_change_changes_signature_even_when_dimension_is_same(self) -> None:
        with patch.object(embedding_profile, "model_config", self._config("model-v1")):
            first = embedding_profile.get_embedding_profile(1024)
        with patch.object(embedding_profile, "model_config", self._config("model-v2")):
            second = embedding_profile.get_embedding_profile(1024)

        self.assertNotEqual(first.signature, second.signature)

    def test_provider_endpoint_parameters_and_dimension_are_part_of_signature(self) -> None:
        with patch.object(embedding_profile, "model_config", self._config()):
            baseline = embedding_profile.get_embedding_profile(1024)

        changed_configs = (
            self._config(provider_name="provider-b"),
            self._config(client_type="gemini"),
            self._config(base_url="https://other.invalid/v1"),
            self._config(extra_params={"dimensions": 1024, "encoding_format": "float"}),
        )
        for changed_config in changed_configs:
            with self.subTest(changed_config=changed_config):
                with patch.object(embedding_profile, "model_config", changed_config):
                    changed = embedding_profile.get_embedding_profile(1024)
                self.assertNotEqual(baseline.signature, changed.signature)

        with patch.object(embedding_profile, "model_config", self._config()):
            changed_dimension = embedding_profile.get_embedding_profile(1536)
        self.assertNotEqual(baseline.signature, changed_dimension.signature)

    def test_multiple_models_are_pinned_to_the_first_model(self) -> None:
        config = self._config(model_names=["embedding-primary", "embedding-fallback"])
        with patch.object(embedding_profile, "model_config", config):
            pinned = embedding_profile.get_stable_embedding_task_config()

        self.assertEqual(pinned.model_list, ["embedding-primary"])
        self.assertEqual(pinned.selection_strategy, "balance")

    def test_multiple_model_warning_is_emitted_once_per_configuration(self) -> None:
        config = self._config(model_names=["embedding-primary", "embedding-fallback"])
        embedding_profile._warn_multiple_models.cache_clear()
        self.addCleanup(embedding_profile._warn_multiple_models.cache_clear)
        with (
            patch.object(embedding_profile, "model_config", config),
            patch.object(embedding_profile.logger, "warning") as warning,
        ):
            embedding_profile.get_embedding_profile(1024)
            embedding_profile.get_embedding_profile(1024)

        warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
