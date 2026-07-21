import asyncio
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from src.common.logger import get_logger
from src.config.config import model_config
from src.llm_models.embedding import embed_text
from src.llm_models.embedding_profile import (
    EmbeddingProfile,
    get_active_embedding_runtime,
    is_active_embedding_profile,
    is_active_embedding_signature,
)


logger = get_logger("emoji_vector_index")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INDEX_PATH = PROJECT_ROOT / "data" / "emoji_selection" / "emoji_vector_index.json"
DEFAULT_USAGE_SCENE_INDEX_PATH = PROJECT_ROOT / "data" / "emoji_selection" / "emoji_usage_scene_vector_index.json"
INDEX_VERSION = 1
DEFAULT_SIMILARITY_THRESHOLD = 0.4
DEFAULT_CANDIDATE_LIMIT = 30
MAX_SYNC_EMBEDDING_UPDATES = 30
MAX_EMBEDDING_CONCURRENCY = 3
MAX_EMBEDDING_DIMENSION = 32768
MAX_EMOTION_COUNT = 8
MAX_EMOTION_LENGTH = 64
MAX_QUERY_LENGTH = 64
MAX_USAGE_SCENE_LENGTH = 240
MAX_USAGE_SCENE_QUERY_LENGTH = 1000


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


@dataclass(frozen=True)
class EmojiUsageSceneVectorCandidate:
    scene_id: int
    emoji_hash: str
    scene: str


@dataclass(frozen=True)
class EmojiUsageSceneVectorMatch:
    scene_id: int
    emoji_hash: str
    scene: str
    similarity: float


@dataclass(frozen=True)
class IndexedEmojiUsageScene:
    scene_id: int
    emoji_hash: str
    scene: str
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


def usage_scene_embedding_text(scene: str) -> str:
    return f"表情使用场景：{normalize_text(scene)[:MAX_USAGE_SCENE_LENGTH]}"


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
    runtime = get_active_embedding_runtime()
    config = runtime.model_config if runtime is not None else model_config
    model_list = getattr(config.model_task_config.embedding, "model_list", []) or []
    return any(normalize_text(model_name) for model_name in model_list)


async def _get_embedding_with_model(text: str, request_type: str) -> tuple[list[float], str]:
    result = await embed_text(text, request_type=request_type)
    return result.vector, result.profile.signature


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

    @staticmethod
    def _profile_metadata(
        entries: dict[str, IndexedEmoji],
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
        entries: dict[str, IndexedEmoji],
        profile: EmbeddingProfile | None = None,
    ) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        embedding_signature, embedding_dimension = self._profile_metadata(entries, profile)
        payload = {
            "version": INDEX_VERSION,
            "embedding_signature": embedding_signature,
            "embedding_dimension": embedding_dimension,
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

    async def rebuild(
        self,
        candidates: Sequence[EmojiVectorCandidate],
        *,
        expected_profile: EmbeddingProfile | None = None,
    ) -> bool:
        """Rebuild the complete emotion cache atomically."""
        normalized_candidates = [
            EmojiVectorCandidate(
                normalize_text(candidate.emoji_hash)[:128],
                normalize_emotions(candidate.emotions),
            )
            for candidate in candidates
            if normalize_text(candidate.emoji_hash)[:128] and normalize_emotions(candidate.emotions)
        ]
        async with self._lock:
            if normalized_candidates and not _has_embedding_model_configured():
                return False
            embedded_entries = await self._embed_candidates(normalized_candidates)
            if len(embedded_entries) != len(normalized_candidates):
                logger.warning("表情情感向量全量重建未完成，保留旧缓存")
                return False
            if expected_profile is not None and (
                not is_active_embedding_profile(expected_profile)
                or any(
                    entry.embedding_model != expected_profile.signature
                    or entry.embedding_dimension != expected_profile.dimension
                    for entry in embedded_entries
                )
            ):
                logger.warning("表情情感向量全量重建期间 profile 发生变化，丢弃本轮结果")
                return False
            try:
                self._write_entries(
                    {entry.emoji_hash: entry for entry in embedded_entries},
                    expected_profile,
                )
            except Exception:
                logger.exception("表情情感向量全量重建写入失败")
                return False
            logger.info(
                "表情情感向量索引全量重建完成",
                event_code="embedding.index.emoji.rebuilt",
                count=len(embedded_entries),
            )
            return True

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
                if not is_active_embedding_signature(entry.embedding_model, entry.embedding_dimension):
                    logger.info("表情向量 upsert profile 已切换，丢弃旧结果")
                    return False
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
        if not is_active_embedding_signature(query_model, query_dimension):
            logger.info("表情向量 query profile 已切换，本轮放弃旧结果")
            return None
        effective_limit = max(1, min(int(limit), DEFAULT_CANDIDATE_LIMIT))
        threshold = max(-1.0, min(float(similarity_threshold), 1.0))

        async with self._lock:
            if not is_active_embedding_signature(query_model, query_dimension):
                logger.info("表情向量 query profile 在索引锁等待期间发生变化")
                return None
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
                refreshed_entries = await self._embed_candidates(missing_candidates)
                if not is_active_embedding_signature(query_model, query_dimension):
                    logger.info("表情向量刷新期间 profile 发生变化，丢弃旧结果")
                    return None
                for entry in refreshed_entries:
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
        if unresolved_candidates:
            logger.info("表情向量索引仍在补齐，本轮回退随机候选")
            return None
        scored_matches.sort(key=lambda match: match.similarity, reverse=True)
        return scored_matches[:effective_limit]


emoji_vector_index = EmojiVectorIndex()


class EmojiUsageSceneVectorIndex:
    """发送阶段使用的真人场景向量索引；每个场景保持独立条目。"""

    def __init__(self, index_path: Path = DEFAULT_USAGE_SCENE_INDEX_PATH) -> None:
        self.index_path = index_path
        self._lock = asyncio.Lock()

    def _load_entries(self) -> dict[int, IndexedEmojiUsageScene]:
        if not self.index_path.exists():
            return {}
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"真人表情场景向量索引读取失败，已忽略旧索引: {exc}")
            return {}
        if not isinstance(payload, dict) or payload.get("version") != INDEX_VERSION:
            return {}

        entries: dict[int, IndexedEmojiUsageScene] = {}
        raw_entries = payload.get("scenes")
        if not isinstance(raw_entries, list):
            return {}
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                continue
            try:
                scene_id = int(raw_entry.get("scene_id"))
                embedding_dimension = int(raw_entry.get("embedding_dimension"))
            except (TypeError, ValueError):
                continue
            emoji_hash = normalize_text(raw_entry.get("emoji_hash"))[:128]
            scene = normalize_text(raw_entry.get("scene"))[:MAX_USAGE_SCENE_LENGTH]
            embedding = normalize_embedding(raw_entry.get("embedding"))
            if scene_id <= 0 or not emoji_hash or not scene or embedding is None:
                continue
            entry = IndexedEmojiUsageScene(
                scene_id=scene_id,
                emoji_hash=emoji_hash,
                scene=scene,
                embedding_model=normalize_text(raw_entry.get("embedding_model"))[:256],
                embedding_dimension=embedding_dimension,
                embedding=embedding,
            )
            if entry.embedding_dimension == len(entry.embedding):
                entries[entry.scene_id] = entry
        return entries

    @staticmethod
    def _profile_metadata(
        entries: dict[int, IndexedEmojiUsageScene],
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
        entries: dict[int, IndexedEmojiUsageScene],
        profile: EmbeddingProfile | None = None,
    ) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        embedding_signature, embedding_dimension = self._profile_metadata(entries, profile)
        payload = {
            "version": INDEX_VERSION,
            "embedding_signature": embedding_signature,
            "embedding_dimension": embedding_dimension,
            "scenes": [
                {
                    "scene_id": entry.scene_id,
                    "emoji_hash": entry.emoji_hash,
                    "scene": entry.scene,
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
        entry: IndexedEmojiUsageScene,
        candidate: EmojiUsageSceneVectorCandidate,
        query_model: str,
        query_dimension: int,
    ) -> bool:
        return (
            entry.emoji_hash == candidate.emoji_hash
            and entry.scene == candidate.scene
            and entry.embedding_model == query_model
            and entry.embedding_dimension == query_dimension
        )

    async def _embed_candidate(
        self,
        candidate: EmojiUsageSceneVectorCandidate,
    ) -> IndexedEmojiUsageScene | None:
        try:
            raw_embedding, model_name = await _get_embedding_with_model(
                usage_scene_embedding_text(candidate.scene),
                request_type="emoji.usage_scene.vector.index",
            )
        except Exception as exc:
            logger.warning(f"真人表情场景向量生成失败，跳过 scene_id={candidate.scene_id}: {exc}")
            return None
        embedding = normalize_embedding(raw_embedding)
        if embedding is None:
            logger.warning(f"真人表情场景向量响应无效，跳过 scene_id={candidate.scene_id}")
            return None
        return IndexedEmojiUsageScene(
            scene_id=candidate.scene_id,
            emoji_hash=candidate.emoji_hash,
            scene=candidate.scene,
            embedding_model=normalize_text(model_name)[:256],
            embedding_dimension=len(embedding),
            embedding=embedding,
        )

    async def _embed_candidates(
        self,
        candidates: Sequence[EmojiUsageSceneVectorCandidate],
    ) -> list[IndexedEmojiUsageScene]:
        semaphore = asyncio.Semaphore(MAX_EMBEDDING_CONCURRENCY)

        async def embed_with_limit(candidate: EmojiUsageSceneVectorCandidate) -> IndexedEmojiUsageScene | None:
            async with semaphore:
                return await self._embed_candidate(candidate)

        embedded = await asyncio.gather(*(embed_with_limit(candidate) for candidate in candidates))
        return [entry for entry in embedded if entry is not None]

    async def rebuild(
        self,
        candidates: Sequence[EmojiUsageSceneVectorCandidate],
        *,
        expected_profile: EmbeddingProfile | None = None,
    ) -> bool:
        """Rebuild the complete usage-scene cache atomically."""
        normalized_candidates: list[EmojiUsageSceneVectorCandidate] = []
        seen_scene_ids: set[int] = set()
        for candidate in candidates:
            if (
                isinstance(candidate.scene_id, bool)
                or not isinstance(candidate.scene_id, int)
                or candidate.scene_id <= 0
                or candidate.scene_id in seen_scene_ids
            ):
                continue
            emoji_hash = normalize_text(candidate.emoji_hash)[:128]
            scene = normalize_text(candidate.scene)[:MAX_USAGE_SCENE_LENGTH]
            if not emoji_hash or not scene:
                continue
            seen_scene_ids.add(candidate.scene_id)
            normalized_candidates.append(EmojiUsageSceneVectorCandidate(candidate.scene_id, emoji_hash, scene))

        async with self._lock:
            if normalized_candidates and not _has_embedding_model_configured():
                return False
            embedded_entries = await self._embed_candidates(normalized_candidates)
            if len(embedded_entries) != len(normalized_candidates):
                logger.warning("真人表情场景向量全量重建未完成，保留旧缓存")
                return False
            if expected_profile is not None and (
                not is_active_embedding_profile(expected_profile)
                or any(
                    entry.embedding_model != expected_profile.signature
                    or entry.embedding_dimension != expected_profile.dimension
                    for entry in embedded_entries
                )
            ):
                logger.warning("真人表情场景向量全量重建期间 profile 发生变化，丢弃本轮结果")
                return False
            try:
                self._write_entries(
                    {entry.scene_id: entry for entry in embedded_entries},
                    expected_profile,
                )
            except Exception:
                logger.exception("真人表情场景向量全量重建写入失败")
                return False
            logger.info(
                "真人表情场景向量索引全量重建完成",
                event_code="embedding.index.emoji_scene.rebuilt",
                count=len(embedded_entries),
            )
            return True

    async def search(
        self,
        *,
        query_text: str,
        candidates: Sequence[EmojiUsageSceneVectorCandidate],
        limit: int = DEFAULT_CANDIDATE_LIMIT,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> list[EmojiUsageSceneVectorMatch] | None:
        normalized_query = normalize_text(query_text)[:MAX_USAGE_SCENE_QUERY_LENGTH]
        normalized_candidates: list[EmojiUsageSceneVectorCandidate] = []
        seen_scene_ids: set[int] = set()
        for candidate in candidates:
            scene_id = candidate.scene_id
            emoji_hash = normalize_text(candidate.emoji_hash)[:128]
            scene = normalize_text(candidate.scene)[:MAX_USAGE_SCENE_LENGTH]
            if (
                isinstance(scene_id, bool)
                or not isinstance(scene_id, int)
                or scene_id <= 0
                or scene_id in seen_scene_ids
                or not emoji_hash
                or not scene
            ):
                continue
            seen_scene_ids.add(scene_id)
            normalized_candidates.append(EmojiUsageSceneVectorCandidate(scene_id, emoji_hash, scene))
        if not normalized_query:
            return None
        if not normalized_candidates:
            return []
        if not _has_embedding_model_configured():
            logger.info("真人表情场景向量检索不可用：未配置 embedding 模型")
            return None

        try:
            raw_query_embedding, query_model = await _get_embedding_with_model(
                usage_scene_embedding_text(normalized_query),
                request_type="emoji.usage_scene.vector.query",
            )
        except Exception as exc:
            logger.warning(f"真人表情场景向量 query 生成失败: {exc}")
            return None
        query_embedding = normalize_embedding(raw_query_embedding)
        if query_embedding is None:
            logger.warning("真人表情场景向量 query 响应无效")
            return None

        query_model = normalize_text(query_model)[:256]
        query_dimension = len(query_embedding)
        if not is_active_embedding_signature(query_model, query_dimension):
            logger.info("真人表情场景 query profile 已切换，本轮放弃旧结果")
            return None
        effective_limit = max(1, min(int(limit), len(normalized_candidates)))
        threshold = max(-1.0, min(float(similarity_threshold), 1.0))

        async with self._lock:
            if not is_active_embedding_signature(query_model, query_dimension):
                logger.info("真人表情场景 query profile 在索引锁等待期间发生变化")
                return None
            entries = self._load_entries()
            active_scene_ids = {candidate.scene_id for candidate in normalized_candidates}
            changed = False
            for scene_id in list(entries):
                if scene_id not in active_scene_ids:
                    entries.pop(scene_id, None)
                    changed = True

            missing_candidates = [
                candidate
                for candidate in normalized_candidates
                if (entry := entries.get(candidate.scene_id)) is None
                or not self._entry_matches(entry, candidate, query_model, query_dimension)
            ][:MAX_SYNC_EMBEDDING_UPDATES]
            refreshed_entries = await self._embed_candidates(missing_candidates)
            if not is_active_embedding_signature(query_model, query_dimension):
                logger.info("真人表情场景刷新期间 profile 发生变化，丢弃旧结果")
                return None
            for entry in refreshed_entries:
                entries[entry.scene_id] = entry
                changed = True

            if changed:
                try:
                    self._write_entries(entries)
                except Exception as exc:
                    logger.warning(f"真人表情场景向量索引刷新失败，将使用内存结果: {exc}")

            scored_matches: list[EmojiUsageSceneVectorMatch] = []
            usable_entries = 0
            unresolved_candidates = 0
            for candidate in normalized_candidates:
                entry = entries.get(candidate.scene_id)
                if entry is None or not self._entry_matches(entry, candidate, query_model, query_dimension):
                    unresolved_candidates += 1
                    continue
                usable_entries += 1
                similarity = cosine_similarity(query_embedding, entry.embedding)
                if similarity >= threshold:
                    scored_matches.append(
                        EmojiUsageSceneVectorMatch(
                            scene_id=candidate.scene_id,
                            emoji_hash=candidate.emoji_hash,
                            scene=candidate.scene,
                            similarity=similarity,
                        )
                    )

        if usable_entries == 0:
            return None
        if unresolved_candidates:
            logger.info("真人表情场景向量索引仍在补齐，本轮保留其他候选路径")
            return None
        scored_matches.sort(key=lambda match: match.similarity, reverse=True)
        return scored_matches[:effective_limit]


emoji_usage_scene_vector_index = EmojiUsageSceneVectorIndex()
