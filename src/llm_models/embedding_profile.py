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


def _json_safe(value: Any) -> Any:
    """Convert TOML/config values into deterministic JSON-compatible data."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _model_descriptor(model_name: str) -> dict[str, Any]:
    """Return the non-secret parts of a configured model contract."""
    model_info = model_config.get_model_info(model_name)
    provider = model_config.get_provider(model_info.api_provider)
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


def get_embedding_profile(dimension: int) -> EmbeddingProfile:
    """Build a deterministic profile for the model used by vector writes.

    The embedding task historically allowed multiple models with a random
    selection strategy.  A single persisted vector collection cannot safely
    contain vectors from those different spaces, so all vector callers pin the
    first configured model.  The selected model is therefore the only model
    included in the signature.
    """
    task_config = model_config.model_task_config.embedding
    model_names = tuple(str(name).strip() for name in task_config.model_list if str(name).strip())
    primary_name = model_names[0] if model_names else ""

    if len(model_names) > 1:
        _warn_multiple_models(model_names)

    if primary_name:
        descriptor = _model_descriptor(primary_name)
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


def get_stable_embedding_task_config():
    """Return a task config pinned to the model used by vector indexes."""
    task_config = model_config.model_task_config.embedding
    model_names = [str(name).strip() for name in task_config.model_list if str(name).strip()]
    if not model_names or len(model_names) == 1:
        return task_config
    if hasattr(task_config, "__dataclass_fields__"):
        return replace(task_config, model_list=[model_names[0]], selection_strategy="balance")
    pinned = copy.copy(task_config)
    pinned.model_list = [model_names[0]]
    pinned.selection_strategy = "balance"
    return pinned
