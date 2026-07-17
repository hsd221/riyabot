import asyncio
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from src.common.logger import get_logger
from src.config.config import model_config
from src.llm_models.utils_model import LLMRequest


logger = get_logger("emoji_vector_index")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INDEX_PATH = PROJECT_ROOT / "data" / "emoji_selection" / "emoji_vector_index.json"
INDEX_VERSION = 1
DEFAULT_SIMILARITY_THRESHOLD = 0.4
DEFAULT_CANDIDATE_LIMIT = 30
MAX_SYNC_EMBEDDING_UPDATES = 30
MAX_EMBEDDING_CONCURRENCY = 3
MAX_EMBEDDING_DIMENSION = 32768
MAX_EMOTION_COUNT = 8
MAX_EMOTION_LENGTH = 64
MAX_QUERY_LENGTH = 64


@dataclass(frozen=True)
class EmojiVectorCandidate:
    emoji_hash: str
    emotions: tuple[str, ...]


@dataclass(frozen=True)
class EmojiVectorMatch:
    emoji_hash: str
    emotions: tuple[str, ...]
    similarity: float


@dataclass(frozen=True)
class IndexedEmoji:
    emoji_hash: str
    emotions: tuple[str, ...]
    embedding_model: str
    embedding_dimension: int
    embedding: list[float]


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def normalize_emotions(values: Sequence[Any]) -> tuple[str, ...]:
    emotions: list[str] = []
    for value in values:
        emotion = normalize_text(value)[:MAX_EMOTION_LENGTH]
        if emotion and emotion not in emotions:
            emotions.append(emotion)
        if len(emotions) == MAX_EMOTION_COUNT:
            break
    return tuple(emotions)


def emoji_embedding_text(emotions: Sequence[str]) -> str:
    return f"表情情感：{'、'.join(normalize_emotions(emotions))}"


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


def normalize_embedding(values: Any) -> list[float] | None:
    if not isinstance(values, (list, tuple)) or not 0 < len(values) <= MAX_EMBEDDING_DIMENSION:
        return None
    try:
        embedding = [float(value) for value in values]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in embedding):
        return None
    return embedding


def _has_embedding_model_configured() -> bool:
    model_list = getattr(model_config.model_task_config.embedding, "model_list", []) or []
    return any(normalize_text(model_name) for model_name in model_list)


async def _get_embedding_with_model(text: str, request_type: str) -> tuple[list[float], str]:
    llm = LLMRequest(model_set=model_config.model_task_config.embedding, request_type=request_type)
    return await llm.get_embedding(text)


class EmojiVectorIndex:
    def __init__(self, index_path: Path = DEFAULT_INDEX_PATH) -> None:
        self.index_path = index_path
        self._lock = asyncio.Lock()

    def _load_entries(self) -> dict[str, IndexedEmoji]:
        if not self.index_path.exists():
            return {}
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"表情向量索引读取失败，已忽略旧索引: {exc}")
            return {}
        if not isinstance(payload, dict):
            return {}
        try:
            index_version = int(payload.get("version") or 0)
        except (TypeError, ValueError):
            index_version = 0
        if index_version != INDEX_VERSION:
            return {}

        entries: dict[str, IndexedEmoji] = {}
        raw_entries = payload.get("emojis")
        if not isinstance(raw_entries, list):
            return {}
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                continue
            embedding = normalize_embedding(raw_entry.get("embedding"))
            emoji_hash = normalize_text(raw_entry.get("emoji_hash"))[:128]
            raw_emotions = raw_entry.get("emotions")
            if not isinstance(raw_emotions, list):
                continue
            emotions = normalize_emotions(raw_emotions)
            if not emoji_hash or not emotions or embedding is None:
                continue
            try:
                entry = IndexedEmoji(
                    emoji_hash=emoji_hash,
                    emotions=emotions,
                    embedding_model=normalize_text(raw_entry.get("embedding_model"))[:256],
                    embedding_dimension=int(raw_entry.get("embedding_dimension") or len(embedding)),
                    embedding=embedding,
                )
            except (TypeError, ValueError):
                continue
            if entry.embedding and entry.embedding_dimension == len(entry.embedding):
                entries[entry.emoji_hash] = entry
        return entries

    def _write_entries(self, entries: dict[str, IndexedEmoji]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "emojis": [
                {
                    "emoji_hash": entry.emoji_hash,
                    "emotions": list(entry.emotions),
                    "embedding_model": entry.embedding_model,
                    "embedding_dimension": entry.embedding_dimension,
                    "embedding": [round(float(value), 7) for value in entry.embedding],
                }
                for entry in entries.values()
            ],
        }
        temporary_path = self.index_path.with_name(f"{self.index_path.stem}.tmp{self.index_path.suffix}")
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary_path.replace(self.index_path)

    @staticmethod
    def _entry_matches(
        entry: IndexedEmoji,
        candidate: EmojiVectorCandidate,
        query_model: str,
        query_dimension: int,
    ) -> bool:
        return (
            entry.emotions == candidate.emotions
            and entry.embedding_model == query_model
            and entry.embedding_dimension == query_dimension
        )

    async def _embed_candidate(self, candidate: EmojiVectorCandidate) -> IndexedEmoji | None:
        try:
            raw_embedding, model_name = await _get_embedding_with_model(
                emoji_embedding_text(candidate.emotions),
                request_type="emoji.vector.index",
            )
        except Exception as exc:
            logger.warning(f"表情向量生成失败，跳过 hash={candidate.emoji_hash[:8]}: {exc}")
            return None
        embedding = normalize_embedding(raw_embedding)
        if embedding is None:
            logger.warning(f"表情向量响应无效，跳过 hash={candidate.emoji_hash[:8]}")
            return None
        return IndexedEmoji(
            emoji_hash=candidate.emoji_hash,
            emotions=candidate.emotions,
            embedding_model=normalize_text(model_name)[:256],
            embedding_dimension=len(embedding),
            embedding=embedding,
        )

    async def _embed_candidates(self, candidates: Sequence[EmojiVectorCandidate]) -> list[IndexedEmoji]:
        semaphore = asyncio.Semaphore(MAX_EMBEDDING_CONCURRENCY)

        async def embed_with_limit(candidate: EmojiVectorCandidate) -> IndexedEmoji | None:
            async with semaphore:
                return await self._embed_candidate(candidate)

        embedded = await asyncio.gather(*(embed_with_limit(candidate) for candidate in candidates))
        return [entry for entry in embedded if entry is not None]

    async def upsert(self, emoji_hash: str, emotions: Sequence[str]) -> bool:
        normalized_hash = normalize_text(emoji_hash)[:128]
        normalized_emotions = normalize_emotions(emotions)
        if not normalized_hash or not normalized_emotions or not _has_embedding_model_configured():
            return False

        entry = await self._embed_candidate(EmojiVectorCandidate(normalized_hash, normalized_emotions))
        if entry is None:
            return False

        try:
            async with self._lock:
                entries = self._load_entries()
                entries[normalized_hash] = entry
                self._write_entries(entries)
        except Exception as exc:
            logger.warning(f"表情向量索引写入失败，hash={normalized_hash[:8]}: {exc}")
            return False
        return True

    async def delete(self, emoji_hash: str) -> bool:
        normalized_hash = normalize_text(emoji_hash)
        if not normalized_hash:
            return False
        try:
            async with self._lock:
                entries = self._load_entries()
                if entries.pop(normalized_hash, None) is not None:
                    self._write_entries(entries)
        except Exception as exc:
            logger.warning(f"删除表情向量失败，hash={normalized_hash[:8]}: {exc}")
            return False
        return True

    async def search(
        self,
        *,
        query_text: str,
        candidates: Sequence[EmojiVectorCandidate],
        limit: int = DEFAULT_CANDIDATE_LIMIT,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> list[EmojiVectorMatch] | None:
        normalized_query = normalize_text(query_text)[:MAX_QUERY_LENGTH]
        normalized_candidates: list[EmojiVectorCandidate] = []
        for candidate in candidates:
            emoji_hash = normalize_text(candidate.emoji_hash)[:128]
            emotions = normalize_emotions(candidate.emotions)
            if emoji_hash and emotions:
                normalized_candidates.append(EmojiVectorCandidate(emoji_hash, emotions))
        if not normalized_query:
            return None
        if not normalized_candidates:
            return []
        if not _has_embedding_model_configured():
            logger.info("表情向量检索不可用：未配置 embedding 模型")
            return None

        try:
            raw_query_embedding, query_model = await _get_embedding_with_model(
                f"表情情感：{normalized_query}",
                request_type="emoji.vector.query",
            )
        except Exception as exc:
            logger.warning(f"表情向量 query 生成失败，将回退随机候选: {exc}")
            return None
        query_embedding = normalize_embedding(raw_query_embedding)
        if query_embedding is None:
            logger.warning("表情向量 query 响应无效，将回退随机候选")
            return None

        query_model = normalize_text(query_model)[:256]
        query_dimension = len(query_embedding)
        effective_limit = max(1, min(int(limit), DEFAULT_CANDIDATE_LIMIT))
        threshold = max(-1.0, min(float(similarity_threshold), 1.0))

        async with self._lock:
            entries = self._load_entries()
            active_hashes = {candidate.emoji_hash for candidate in normalized_candidates}
            changed = False
            for emoji_hash in list(entries):
                if emoji_hash not in active_hashes:
                    entries.pop(emoji_hash, None)
                    changed = True

            missing_candidates = [
                candidate
                for candidate in normalized_candidates
                if (entry := entries.get(candidate.emoji_hash)) is None
                or not self._entry_matches(entry, candidate, query_model, query_dimension)
            ][:MAX_SYNC_EMBEDDING_UPDATES]
            if missing_candidates:
                for entry in await self._embed_candidates(missing_candidates):
                    entries[entry.emoji_hash] = entry
                    changed = True

            if changed:
                try:
                    self._write_entries(entries)
                except Exception as exc:
                    logger.warning(f"表情向量索引刷新失败，将使用内存结果: {exc}")

            scored_matches: list[EmojiVectorMatch] = []
            usable_entries = 0
            unresolved_candidates = 0
            for candidate in normalized_candidates:
                entry = entries.get(candidate.emoji_hash)
                if entry is None or not self._entry_matches(entry, candidate, query_model, query_dimension):
                    unresolved_candidates += 1
                    continue
                usable_entries += 1
                similarity = cosine_similarity(query_embedding, entry.embedding)
                if similarity >= threshold:
                    scored_matches.append(
                        EmojiVectorMatch(
                            emoji_hash=candidate.emoji_hash,
                            emotions=candidate.emotions,
                            similarity=similarity,
                        )
                    )

        if usable_entries == 0:
            logger.info("表情向量检索不可用：没有可用的索引条目")
            return None
        if not scored_matches and unresolved_candidates:
            logger.info("表情向量索引仍在补齐，本轮回退随机候选")
            return None
        scored_matches.sort(key=lambda match: match.similarity, reverse=True)
        return scored_matches[:effective_limit]


emoji_vector_index = EmojiVectorIndex()
