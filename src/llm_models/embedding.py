"""Canonical entry point for generating comparable text embeddings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from hashlib import sha256

from src.llm_models.embedding_profile import (
    EmbeddingProfile,
    get_embedding_profile,
    get_stable_embedding_task_config,
)
from src.llm_models.utils_model import LLMRequest


@dataclass(frozen=True)
class EmbeddingResult:
    """A vector bundled with the persistent identity of its embedding space."""

    vector: list[float]
    profile: EmbeddingProfile


def embedding_source_hash(text: str) -> str:
    """Return a stable fingerprint for the exact text represented by a vector."""
    if not isinstance(text, str):
        raise TypeError("embedding source must be a string")
    return sha256(text.encode("utf-8")).hexdigest()


async def embed_text(
    text: str,
    *,
    request_type: str = "embedding",
    expected_dimension: int | None = None,
) -> EmbeddingResult:
    """Generate a validated vector using the project's pinned embedding model.

    Persistent indexes should store ``result.profile.signature`` alongside the
    vector-space dimension.  This distinguishes model/provider changes even
    when the returned vector length stays the same.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("embedding input must be a non-empty string")

    llm = LLMRequest(
        model_set=get_stable_embedding_task_config(),
        request_type=request_type,
    )
    raw_vector, _runtime_model_name = await llm.get_embedding(text)
    try:
        vector = [float(value) for value in raw_vector]
    except (TypeError, ValueError) as exc:
        raise ValueError("embedding vector must contain numeric values") from exc

    if not vector:
        raise ValueError("embedding vector must not be empty")
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("embedding vector values must be finite")
    if expected_dimension is not None and len(vector) != int(expected_dimension):
        raise ValueError(f"embedding dimension {len(vector)} != expected dimension {int(expected_dimension)}")

    return EmbeddingResult(
        vector=vector,
        profile=get_embedding_profile(len(vector)),
    )
