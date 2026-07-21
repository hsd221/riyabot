"""Stable embedding configuration identity shared by vector indexes.

Embedding vectors are only comparable when they were produced by the same
model contract.  This module keeps that contract in one place so persistent
indexes do not silently mix models that happen to have the same dimension.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, replace
from functools import lru_cache
from hashlib import sha256
from typing import Any

from src.common.logger import get_logger
from src.config.config import model_config

logger = get_logger("embedding.profile")

EMBEDDING_PROFILE_VERSION = 1


@dataclass(frozen=True)
class EmbeddingProfile:
    """The immutable identity used for one persisted embedding space."""

    signature: str
    model_name: str
    model_identifier: str
    provider_name: str
    dimension: int
    model_names: tuple[str, ...]


@dataclass(frozen=True)
class EmbeddingRuntime:
    """Immutable configuration snapshot used by one embedding generation."""

    model_config: Any
    task_config: Any
    profile: EmbeddingProfile


class ProfiledEmbedding(list[float]):
    """A list-compatible vector carrying the profile that generated it.

    Existing callers can keep treating vectors as ordinary lists, while storage
    layers can reject a result that was generated before a runtime profile
    switch.
    """

    def __init__(self, values: list[float], profile: EmbeddingProfile) -> None:
        super().__init__(values)
        self.embedding_signature = profile.signature
        self.embedding_dimension = profile.dimension


_active_embedding_runtime: EmbeddingRuntime | None = None


def _json_safe(value: Any) -> Any:
    """Convert TOML/config values into deterministic JSON-compatible data."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _model_descriptor(model_name: str, config: Any | None = None) -> dict[str, Any]:
    """Return the non-secret parts of a configured model contract."""
    config = config or model_config
    model_info = config.get_model_info(model_name)
    provider = config.get_provider(model_info.api_provider)
    return {
        "name": model_info.name,
        "model_identifier": model_info.model_identifier,
        "api_provider": model_info.api_provider,
        "provider_client_type": provider.client_type,
        "provider_base_url": provider.base_url,
        "extra_params": _json_safe(model_info.extra_params),
    }


@lru_cache(maxsize=32)
def _warn_multiple_models(model_names: tuple[str, ...]) -> None:
    """Warn once for each multi-model embedding configuration seen by this process."""
    logger.warning(
        "embedding 任务配置了多个模型，向量索引将固定使用列表中的第一个模型",
        event_code="embedding.profile.multiple_models_pinned",
        selected_model=model_names[0],
        configured_models=list(model_names),
    )


def get_embedding_profile(dimension: int, *, config: Any | None = None) -> EmbeddingProfile:
    """Build a deterministic profile for the model used by vector writes.

    The embedding task historically allowed multiple models with a random
    selection strategy.  A single persisted vector collection cannot safely
    contain vectors from those different spaces, so all vector callers pin the
    first configured model.  The selected model is therefore the only model
    included in the signature.
    """
    config = config or model_config
    task_config = config.model_task_config.embedding
    model_names = tuple(str(name).strip() for name in task_config.model_list if str(name).strip())
    primary_name = model_names[0] if model_names else ""

    if len(model_names) > 1:
        _warn_multiple_models(model_names)

    if primary_name:
        descriptor = _model_descriptor(primary_name, config)
    else:
        descriptor = {
            "name": "",
            "model_identifier": "",
            "api_provider": "",
            "provider_client_type": "",
            "provider_base_url": "",
            "extra_params": {},
        }

    signature_payload = {
        "profile_version": EMBEDDING_PROFILE_VERSION,
        "dimension": int(dimension),
        "model": descriptor,
        "selection": "fixed-primary",
    }
    signature = sha256(
        json.dumps(signature_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return EmbeddingProfile(
        signature=signature,
        model_name=descriptor["name"],
        model_identifier=descriptor["model_identifier"],
        provider_name=descriptor["api_provider"],
        dimension=int(dimension),
        model_names=model_names,
    )


def get_stable_embedding_task_config(config: Any | None = None):
    """Return a task config pinned to the model used by vector indexes."""
    config = config or model_config
    task_config = config.model_task_config.embedding
    model_names = [str(name).strip() for name in task_config.model_list if str(name).strip()]
    if not model_names or len(model_names) == 1:
        return task_config
    if hasattr(task_config, "__dataclass_fields__"):
        return replace(task_config, model_list=[model_names[0]], selection_strategy="balance")
    pinned = copy.copy(task_config)
    pinned.model_list = [model_names[0]]
    pinned.selection_strategy = "balance"
    return pinned


def build_embedding_runtime(config: Any, dimension: int) -> EmbeddingRuntime:
    """Build a candidate runtime without changing the active process state."""
    profile = get_embedding_profile(int(dimension), config=config)
    task_config = get_stable_embedding_task_config(config)
    return EmbeddingRuntime(model_config=config, task_config=task_config, profile=profile)


def activate_embedding_runtime(config: Any, dimension: int) -> EmbeddingRuntime:
    """Atomically make a validated embedding configuration the active one."""
    global _active_embedding_runtime
    runtime = build_embedding_runtime(config, dimension)
    _active_embedding_runtime = runtime
    return runtime


def get_active_embedding_runtime() -> EmbeddingRuntime | None:
    """Return the current runtime snapshot, if startup has activated one."""
    return _active_embedding_runtime


def is_active_embedding_profile(profile: EmbeddingProfile) -> bool:
    """Return whether a profile still matches the process-wide embedding runtime."""
    return is_active_embedding_signature(profile.signature, profile.dimension)


def is_active_embedding_signature(signature: str | None, dimension: int | None = None) -> bool:
    """Return whether a stored signature and optional dimension are still current."""
    runtime = get_active_embedding_runtime()
    if runtime is None:
        return True
    if not signature or str(signature) != runtime.profile.signature:
        return False
    if dimension is not None:
        try:
            if int(dimension) != runtime.profile.dimension:
                return False
        except (TypeError, ValueError):
            return False
    return True


def reset_embedding_runtime() -> None:
    """Reset the process-local runtime override for tests and controlled shutdown."""
    global _active_embedding_runtime
    _active_embedding_runtime = None
