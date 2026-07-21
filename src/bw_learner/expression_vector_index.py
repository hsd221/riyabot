import asyncio
import json
import math
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.common.logger import get_logger
from src.config.config import model_config
from src.llm_models.embedding import embed_text
from src.llm_models.embedding_profile import (
    EmbeddingProfile,
    get_active_embedding_runtime,
    is_active_embedding_profile,
    is_active_embedding_signature,
)

logger = get_logger("expression_vector_index")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX_PATH = PROJECT_ROOT / "data" / "expression_selection" / "expression_vector_index.json"
INDEX_VERSION = 1
MIN_VECTOR_CANDIDATES = 10
VECTOR_CANDIDATE_LIMIT = 50
MAX_SYNC_EMBEDDING_UPDATES = 30
MAX_EMBEDDING_CONCURRENCY = 3
VECTOR_WEIGHT = 0.85
LEXICAL_WEIGHT = 0.15


@dataclass(frozen=True)
class IndexedExpression:
    id: int
    source_id: str
    situation: str
    style: str
    count: int
    fingerprint: str
    embedding_model: str
    embedding_dimension: int
    embedding: List[float]


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def expression_fingerprint(candidate: Dict[str, Any]) -> str:
    raw_text = "\n".join(
        [
            str(candidate.get("id") or ""),
            normalize_text(candidate.get("source_id")),
            normalize_text(candidate.get("situation")),
            normalize_text(candidate.get("style")),
        ]
    )
    return sha256(raw_text.encode("utf-8")).hexdigest()


def expression_embedding_text(candidate: Dict[str, Any]) -> str:
    return f"情景：{normalize_text(candidate.get('situation'))}\n风格：{normalize_text(candidate.get('style'))}"


def lexical_tokens(text: str) -> set[str]:
    normalized = normalize_text(text).lower()
    tokens: set[str] = set()
    current_ascii = []
    current_cjk = []

    def flush_ascii() -> None:
        if len(current_ascii) >= 2:
            tokens.add("".join(current_ascii))
        current_ascii.clear()

    def flush_cjk() -> None:
        if current_cjk:
            tokens.update(current_cjk)
            for index in range(len(current_cjk) - 1):
                tokens.add("".join(current_cjk[index : index + 2]))
        current_cjk.clear()

    for char in normalized:
        if "\u4e00" <= char <= "\u9fff":
            flush_ascii()
            current_cjk.append(char)
        elif char.isalnum() or char in {"_", "#", "+", "-", "."}:
            flush_cjk()
            current_ascii.append(char)
        else:
            flush_ascii()
            flush_cjk()
    flush_ascii()
    flush_cjk()
    return tokens


def lexical_overlap_score(query_tokens: set[str], candidate: Dict[str, Any]) -> float:
    if not query_tokens:
        return 0.0
    candidate_tokens = lexical_tokens(f"{candidate.get('situation', '')}\n{candidate.get('style', '')}")
    if not candidate_tokens:
        return 0.0
    overlap_count = len(query_tokens & candidate_tokens)
    if overlap_count <= 0:
        return 0.0
    return overlap_count / math.sqrt(len(query_tokens) * len(candidate_tokens))


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for left_value, right_value in zip(left, right, strict=True):
        left_float = float(left_value)
        right_float = float(right_value)
        dot += left_float * right_float
        left_norm += left_float * left_float
        right_norm += right_float * right_float
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)


def _has_embedding_model_configured() -> bool:
    runtime = get_active_embedding_runtime()
    config = runtime.model_config if runtime is not None else model_config
    model_list = getattr(config.model_task_config.embedding, "model_list", []) or []
    return any(str(model_name or "").strip() for model_name in model_list)


async def _get_embedding_with_model(text: str, request_type: str) -> Tuple[List[float], str]:
    result = await embed_text(text, request_type=request_type)
    return result.vector, result.profile.signature


class ExpressionVectorIndex:
    def __init__(self, index_path: Path = DEFAULT_INDEX_PATH) -> None:
        self.index_path = index_path
        self._lock = asyncio.Lock()

    @staticmethod
    def _candidate_sort_key(candidate: Dict[str, Any]) -> Tuple[int, int]:
        try:
            count = int(candidate.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        try:
            candidate_id = int(candidate.get("id") or 0)
        except (TypeError, ValueError):
            candidate_id = 0
        return count, candidate_id

    def _load_entries(self) -> Dict[str, IndexedExpression]:
        if not self.index_path.exists():
            return {}
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"表达向量索引读取失败，已忽略旧索引: {exc}")
            return {}
        if int(payload.get("version") or 0) != INDEX_VERSION:
            return {}

        entries: Dict[str, IndexedExpression] = {}
        for raw_entry in payload.get("expressions") or []:
            if not isinstance(raw_entry, dict):
                continue
            fingerprint = normalize_text(raw_entry.get("fingerprint"))
            embedding = raw_entry.get("embedding")
            if not fingerprint or not isinstance(embedding, list):
                continue
            try:
                entry = IndexedExpression(
                    id=int(raw_entry.get("id") or 0),
                    source_id=normalize_text(raw_entry.get("source_id")),
                    situation=normalize_text(raw_entry.get("situation")),
                    style=normalize_text(raw_entry.get("style")),
                    count=int(raw_entry.get("count") or 0),
                    fingerprint=fingerprint,
                    embedding_model=normalize_text(raw_entry.get("embedding_model")),
                    embedding_dimension=int(raw_entry.get("embedding_dimension") or len(embedding)),
                    embedding=[float(value) for value in embedding],
                )
            except (TypeError, ValueError):
                continue
            if entry.id > 0 and entry.embedding and entry.embedding_dimension == len(entry.embedding):
                entries[fingerprint] = entry
        return entries

    @staticmethod
    def _profile_metadata(
        entries: Dict[str, IndexedExpression],
        profile: EmbeddingProfile | None,
    ) -> tuple[str | None, int | None]:
        if profile is not None:
            return profile.signature, profile.dimension
        entry_profiles = {(entry.embedding_model, entry.embedding_dimension) for entry in entries.values()}
        if len(entry_profiles) == 1:
            return next(iter(entry_profiles))
        if not entries and (runtime := get_active_embedding_runtime()) is not None:
            return runtime.profile.signature, runtime.profile.dimension
        return None, None

    def profile_matches(self, profile: EmbeddingProfile) -> bool:
        """Return whether the file was completely written for this profile."""
        if not self.index_path.exists():
            return False
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            return (
                isinstance(payload, dict)
                and int(payload.get("version") or 0) == INDEX_VERSION
                and payload.get("embedding_signature") == profile.signature
                and int(payload.get("embedding_dimension") or 0) == profile.dimension
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False

    def _write_entries(
        self,
        entries: Dict[str, IndexedExpression],
        profile: EmbeddingProfile | None = None,
    ) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        embedding_signature, embedding_dimension = self._profile_metadata(entries, profile)
        payload = {
            "version": INDEX_VERSION,
            "generated_at": time.time(),
            "embedding_signature": embedding_signature,
            "embedding_dimension": embedding_dimension,
            "expressions": [
                {
                    "id": entry.id,
                    "source_id": entry.source_id,
                    "situation": entry.situation,
                    "style": entry.style,
                    "count": entry.count,
                    "fingerprint": entry.fingerprint,
                    "embedding_model": entry.embedding_model,
                    "embedding_dimension": entry.embedding_dimension,
                    "embedding": [round(float(value), 7) for value in entry.embedding],
                }
                for entry in entries.values()
            ],
        }
        temporary_path = self.index_path.with_name(f"{self.index_path.stem}.tmp{self.index_path.suffix}")
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary_path.replace(self.index_path)

    async def _embed_candidate(self, candidate: Dict[str, Any]) -> Optional[IndexedExpression]:
        try:
            embedding, model_name = await _get_embedding_with_model(
                expression_embedding_text(candidate),
                request_type="expression.vector.index",
            )
        except Exception as exc:
            logger.warning(f"表达向量索引生成失败，跳过表达 ID={candidate.get('id')}: {exc}")
            return None
        if not embedding:
            return None
        return IndexedExpression(
            id=int(candidate["id"]),
            source_id=normalize_text(candidate.get("source_id")),
            situation=normalize_text(candidate.get("situation")),
            style=normalize_text(candidate.get("style")),
            count=int(candidate.get("count") or 0),
            fingerprint=expression_fingerprint(candidate),
            embedding_model=normalize_text(model_name),
            embedding_dimension=len(embedding),
            embedding=[float(value) for value in embedding],
        )

    async def _embed_missing_candidates(self, candidates: List[Dict[str, Any]]) -> List[IndexedExpression]:
        semaphore = asyncio.Semaphore(MAX_EMBEDDING_CONCURRENCY)

        async def embed_with_limit(candidate: Dict[str, Any]) -> Optional[IndexedExpression]:
            async with semaphore:
                return await self._embed_candidate(candidate)

        embedded = await asyncio.gather(*(embed_with_limit(candidate) for candidate in candidates))
        return [entry for entry in embedded if entry is not None]

    async def rebuild(
        self,
        candidates: Sequence[Dict[str, Any]],
        *,
        expected_profile: EmbeddingProfile | None = None,
    ) -> bool:
        """Rebuild the complete cache atomically for one embedding profile."""
        normalized_candidates = [
            candidate.copy()
            for candidate in candidates
            if candidate.get("id") is not None
            and normalize_text(candidate.get("situation"))
            and normalize_text(candidate.get("style"))
        ]
        async with self._lock:
            if normalized_candidates and not _has_embedding_model_configured():
                return False
            embedded_entries = await self._embed_missing_candidates(normalized_candidates)
            if len(embedded_entries) != len(normalized_candidates):
                logger.warning(
                    "表达向量全量重建未完成，保留旧缓存",
                    event_code="embedding.index.expression.rebuild_incomplete",
                    expected=len(normalized_candidates),
                    actual=len(embedded_entries),
                )
                return False
            if expected_profile is not None and (
                not is_active_embedding_profile(expected_profile)
                or any(
                    entry.embedding_model != expected_profile.signature
                    or entry.embedding_dimension != expected_profile.dimension
                    for entry in embedded_entries
                )
            ):
                logger.warning("表达向量全量重建期间 profile 发生变化，丢弃本轮结果")
                return False
            entries = {entry.fingerprint: entry for entry in embedded_entries}
            try:
                self._write_entries(entries, expected_profile)
            except Exception:
                logger.exception("表达向量全量重建写入失败", event_code="embedding.index.expression.rebuild_failed")
                return False
            logger.info(
                "表达向量索引全量重建完成",
                event_code="embedding.index.expression.rebuilt",
                count=len(entries),
                embedding_signature=expected_profile.signature if expected_profile else None,
            )
            return True

    @staticmethod
    def _entry_matches_query(entry: IndexedExpression, query_model: str, query_dimension: int) -> bool:
        return entry.embedding_model == query_model and entry.embedding_dimension == query_dimension

    def _rank_candidates(
        self,
        candidates: List[Dict[str, Any]],
        entries: Dict[str, IndexedExpression],
        query_embedding: List[float],
        query_model: str,
        query_text: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        query_tokens = lexical_tokens(query_text)
        scored_candidates: List[Tuple[float, Dict[str, Any]]] = []
        query_dimension = len(query_embedding)

        for candidate in candidates:
            entry = entries.get(expression_fingerprint(candidate))
            if entry is None or not self._entry_matches_query(entry, query_model, query_dimension):
                continue
            vector_score = cosine_similarity(query_embedding, entry.embedding)
            lexical_score = lexical_overlap_score(query_tokens, candidate)
            score = vector_score * VECTOR_WEIGHT + lexical_score * LEXICAL_WEIGHT
            ranked_candidate = candidate.copy()
            ranked_candidate["selector_score"] = round(score, 4)
            ranked_candidate["vector_score"] = round(vector_score, 4)
            ranked_candidate["lexical_score"] = round(lexical_score, 4)
            scored_candidates.append((score, ranked_candidate))

        scored_candidates.sort(key=lambda item: item[0], reverse=True)
        return [candidate for _, candidate in scored_candidates[:limit]]

    async def select_candidates(
        self,
        *,
        candidates: List[Dict[str, Any]],
        query_text: str,
        limit: int = VECTOR_CANDIDATE_LIMIT,
    ) -> Optional[List[Dict[str, Any]]]:
        normalized_query = normalize_text(query_text)
        if not normalized_query:
            logger.info("表达向量选择不可用：query 为空")
            return None
        if len(candidates) < MIN_VECTOR_CANDIDATES:
            logger.info(f"表达向量选择不可用：候选不足 {len(candidates)}/{MIN_VECTOR_CANDIDATES}")
            return None
        if not _has_embedding_model_configured():
            logger.info("表达向量选择不可用：未配置 embedding 模型")
            return None

        try:
            query_embedding, query_model = await _get_embedding_with_model(
                normalized_query,
                request_type="expression.vector.query",
            )
        except Exception as exc:
            logger.warning(f"表达向量 query 生成失败，回退传统表达选择: {exc}")
            return None
        if not query_embedding:
            return None

        query_model = normalize_text(query_model)
        query_dimension = len(query_embedding)
        if not is_active_embedding_signature(query_model, query_dimension):
            logger.info("表达向量 query profile 已切换，本轮放弃旧结果")
            return None
        effective_limit = max(1, min(int(limit), VECTOR_CANDIDATE_LIMIT))
        normalized_candidates = [
            candidate.copy()
            for candidate in candidates
            if candidate.get("id") is not None
            and normalize_text(candidate.get("situation"))
            and normalize_text(candidate.get("style"))
        ]
        for candidate in normalized_candidates:
            candidate["_query_text"] = normalized_query

        async with self._lock:
            if not is_active_embedding_signature(query_model, query_dimension):
                logger.info("表达向量 query profile 在索引锁等待期间发生变化")
                return None
            entries = self._load_entries()
            missing_candidates: List[Dict[str, Any]] = []
            usable_count = 0
            for candidate in sorted(normalized_candidates, key=self._candidate_sort_key, reverse=True):
                fingerprint = expression_fingerprint(candidate)
                entry = entries.get(fingerprint)
                if entry is not None and self._entry_matches_query(entry, query_model, query_dimension):
                    usable_count += 1
                    continue
                if len(missing_candidates) < MAX_SYNC_EMBEDDING_UPDATES:
                    missing_candidates.append(candidate)

            if missing_candidates:
                embedded_entries = await self._embed_missing_candidates(missing_candidates)
                if not is_active_embedding_signature(query_model, query_dimension):
                    logger.info("表达向量刷新期间 profile 发生变化，丢弃旧结果")
                    return None
                for entry in embedded_entries:
                    entries[entry.fingerprint] = entry
                    if self._entry_matches_query(entry, query_model, query_dimension):
                        usable_count += 1
                if embedded_entries:
                    self._write_entries(entries)

            if usable_count < MIN_VECTOR_CANDIDATES:
                logger.info(f"表达向量选择不可用：可用索引不足 {usable_count}/{MIN_VECTOR_CANDIDATES}")
                return None

            ranked_candidates = self._rank_candidates(
                normalized_candidates,
                entries,
                query_embedding,
                normalize_text(query_model),
                normalized_query,
                effective_limit,
            )

        for candidate in ranked_candidates:
            candidate.pop("_query_text", None)
        logger.debug(f"表达向量候选池完成：候选数={len(ranked_candidates)}")
        return ranked_candidates


expression_vector_index = ExpressionVectorIndex()
