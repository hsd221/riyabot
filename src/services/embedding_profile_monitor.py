"""Runtime detection and coordinated rebuilds for embedding profile changes."""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path
from typing import Any

from src.bw_learner.expression_vector_index import expression_vector_index
from src.chat.emoji_system.emoji_vector_index import (
    EmojiUsageSceneVectorCandidate,
    EmojiVectorCandidate,
    emoji_usage_scene_vector_index,
    emoji_vector_index,
    normalize_emotions,
    normalize_text,
)
from src.common.database.database_model import Emoji, EmojiUsageScene, Expression
from src.common.logger import get_logger
from src.config.config import CONFIG_DIR, api_ada_load_config, global_config, load_config
from src.llm_models.embedding import embed_text
from src.llm_models.embedding_profile import (
    EmbeddingProfile,
    EmbeddingRuntime,
    activate_embedding_runtime,
    build_embedding_runtime,
    get_active_embedding_runtime,
)
from src.manager.async_task_manager import AsyncTask, AsyncTaskManager, async_task_manager
from src.memory.vector_migration import GraphVectorIndexMigrationTask, VectorIndexMigrationTask

logger = get_logger("embedding.profile_monitor")

EMBEDDING_CONFIG_CHECK_INTERVAL_SECONDS = 15
MAX_EMBEDDING_DIMENSION = 32768
_PROFILE_PROBE_TEXT = "RiyaBot embedding profile readiness probe"

ConfigFingerprint = tuple[tuple[int, int, int, int, int], tuple[int, int, int, int, int]]


def _file_fingerprint(path: Path) -> tuple[int, int, int, int, int]:
    """Return a no-follow identity for a trusted regular configuration file."""
    file_stat = os.lstat(path)
    if not stat.S_ISREG(file_stat.st_mode):
        raise RuntimeError(f"配置文件路径无效: {path}")
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )


def _config_fingerprint(config_dir: Path) -> ConfigFingerprint:
    return (
        _file_fingerprint(config_dir / "model_config.toml"),
        _file_fingerprint(config_dir / "bot_config.toml"),
    )


def _load_candidate_runtime(config_dir: Path) -> EmbeddingRuntime:
    candidate_model_config = api_ada_load_config(str(config_dir / "model_config.toml"))
    candidate_model_config.validate_integrity(require_complete=True)
    candidate_bot_config = load_config(str(config_dir / "bot_config.toml"))

    dimension = int(candidate_bot_config.memory.embedding_dimension)
    if not 0 < dimension <= MAX_EMBEDDING_DIMENSION:
        raise ValueError(f"memory.embedding_dimension 必须在 1 到 {MAX_EMBEDDING_DIMENSION} 之间")
    model_names = [
        str(model_name).strip()
        for model_name in candidate_model_config.model_task_config.embedding.model_list
        if str(model_name).strip()
    ]
    if not model_names:
        raise ValueError("embedding 任务必须配置至少一个模型")
    return build_embedding_runtime(candidate_model_config, dimension)


def _load_expression_candidates() -> list[dict[str, Any]]:
    conditions = ~Expression.rejected
    if global_config.expression.expression_checked_only:
        conditions = conditions & Expression.checked
    return [
        {
            "id": expression.id,
            "situation": expression.situation,
            "style": expression.style,
            "source_id": expression.chat_id,
            "count": expression.count if expression.count is not None else 1,
        }
        for expression in Expression.select().where(conditions)
    ]


def _load_emoji_candidates() -> tuple[list[EmojiVectorCandidate], list[EmojiUsageSceneVectorCandidate]]:
    candidates_by_hash: dict[str, EmojiVectorCandidate] = {}
    for emoji in Emoji.select(Emoji.emoji_hash, Emoji.emotion):
        emoji_hash = normalize_text(emoji.emoji_hash)[:128]
        raw_emotions = str(emoji.emotion or "").replace("，", ",").split(",")
        emotions = normalize_emotions(raw_emotions)
        if emoji_hash and emotions:
            candidates_by_hash[emoji_hash] = EmojiVectorCandidate(emoji_hash, emotions)

    active_hashes = set(candidates_by_hash)
    scene_candidates = [
        EmojiUsageSceneVectorCandidate(int(scene.id), str(scene.emoji_hash), str(scene.scene))
        for scene in EmojiUsageScene.select(EmojiUsageScene.id, EmojiUsageScene.emoji_hash, EmojiUsageScene.scene)
        if str(scene.emoji_hash) in active_hashes
    ]
    return list(candidates_by_hash.values()), scene_candidates


async def rebuild_json_vector_indexes(profile: EmbeddingProfile) -> bool:
    """Rebuild all file-backed vector caches under their existing concurrency limits."""
    try:
        expression_candidates = _load_expression_candidates()
        emoji_candidates, scene_candidates = _load_emoji_candidates()
    except Exception:
        logger.exception(
            "向量 JSON 索引源数据读取失败",
            event_code="embedding.index.json_sources_failed",
        )
        return False

    rebuilds = (
        ("expressions", expression_vector_index, expression_candidates),
        ("emoji_emotions", emoji_vector_index, emoji_candidates),
        ("emoji_usage_scenes", emoji_usage_scene_vector_index, scene_candidates),
    )
    completed = True
    for index_name, index, candidates in rebuilds:
        if index.profile_matches(profile):
            continue
        try:
            completed = bool(await index.rebuild(candidates, expected_profile=profile)) and completed
        except Exception:
            completed = False
            logger.exception(
                "向量 JSON 索引全量重建失败",
                event_code="embedding.index.json_rebuild_failed",
                index_name=index_name,
            )
    return completed


def json_vector_indexes_match_profile(profile: EmbeddingProfile) -> bool:
    """Return whether every file-backed index completed this profile."""
    return all(
        index.profile_matches(profile)
        for index in (expression_vector_index, emoji_vector_index, emoji_usage_scene_vector_index)
    )


async def register_pending_vector_migrations(
    store: Any,
    profile: EmbeddingProfile,
    *,
    task_manager: AsyncTaskManager = async_task_manager,
) -> int:
    """Start missing Qdrant rebuild workers without replacing active workers."""
    migration_specs = (
        ("memory_atoms", store.qdrant.atom_migration_pending, VectorIndexMigrationTask),
        ("graph_entries", store.qdrant.graph_migration_pending, GraphVectorIndexMigrationTask),
    )
    registered = 0
    for index_name, pending, task_type in migration_specs:
        if not pending:
            continue
        migration_task = task_type(store)
        if migration_task.task_name in task_manager.tasks:
            logger.debug(
                "向量索引迁移任务已在运行",
                event_code="memory.vector_migration.task_already_running",
                index_name=index_name,
            )
            continue
        try:
            await task_manager.add_task(migration_task)
            registered += 1
            logger.warning(
                "检测到 embedding 配置变化，向量索引后台迁移任务已注册",
                event_code="memory.vector_migration.task_registered",
                index_name=index_name,
                embedding_model=profile.model_name,
                embedding_dimension=profile.dimension,
                interval_seconds=migration_task.run_interval,
            )
        except Exception:
            logger.warning(
                "向量索引后台迁移任务注册失败，对应旧索引保持停用",
                event_code="memory.vector_migration.task_register_failed",
                index_name=index_name,
                exc_info=True,
            )
    return registered


class EmbeddingProfileMonitorTask(AsyncTask):
    """Poll configuration files and coordinate safe runtime profile switches."""

    def __init__(
        self,
        store: Any,
        *,
        config_dir: str | Path = CONFIG_DIR,
        interval: int = EMBEDDING_CONFIG_CHECK_INTERVAL_SECONDS,
        task_manager: AsyncTaskManager = async_task_manager,
    ) -> None:
        super().__init__(task_name="embedding profile monitor", run_interval=max(1, int(interval)))
        self._store = store
        self._config_dir = Path(config_dir)
        self._task_manager = task_manager
        self._last_processed_fingerprint: ConfigFingerprint | None = None
        self._last_rejected_fingerprint: ConfigFingerprint | None = None
        self._pending_json_signature: str | None = None
        self._first_run = True
        self._run_lock = asyncio.Lock()

    async def _probe(self, runtime: EmbeddingRuntime) -> None:
        result = await embed_text(
            _PROFILE_PROBE_TEXT,
            request_type="embedding.profile.probe",
            expected_dimension=runtime.profile.dimension,
            runtime=runtime,
        )
        if result.profile.signature != runtime.profile.signature:
            raise RuntimeError("embedding profile probe returned a different signature")

    async def _candidate_is_ready(self, candidate: EmbeddingRuntime) -> bool:
        try:
            await self._probe(candidate)
        except Exception:
            logger.exception(
                "候选 embedding 配置探测失败，继续使用旧 profile",
                event_code="embedding.profile.probe_failed",
                candidate_signature=candidate.profile.signature,
                candidate_dimension=candidate.profile.dimension,
            )
            return False
        return True

    async def _switch_runtime(self, candidate: EmbeddingRuntime) -> bool:
        if not await self._candidate_is_ready(candidate):
            return False

        if not await self._store.qdrant.reconfigure_embedding(candidate.profile):
            return False

        activate_embedding_runtime(candidate.model_config, candidate.profile.dimension)
        self._pending_json_signature = candidate.profile.signature
        logger.warning(
            "检测到 embedding profile 变化，运行时配置已切换",
            event_code="embedding.profile.runtime_switched",
            embedding_model=candidate.profile.model_name,
            embedding_dimension=candidate.profile.dimension,
            embedding_signature=candidate.profile.signature,
        )
        return True

    async def _run_once(self) -> None:
        fingerprint = _config_fingerprint(self._config_dir)
        active_runtime = get_active_embedding_runtime()
        profile_changed = False

        if fingerprint != self._last_processed_fingerprint and fingerprint != self._last_rejected_fingerprint:
            try:
                candidate = _load_candidate_runtime(self._config_dir)
            except Exception:
                self._last_rejected_fingerprint = fingerprint
                logger.exception(
                    "embedding 配置变更无效，继续使用旧 profile",
                    event_code="embedding.profile.config_rejected",
                )
            else:
                candidate_accepted = False
                if active_runtime is None or candidate.profile.signature != active_runtime.profile.signature:
                    if await self._switch_runtime(candidate):
                        active_runtime = get_active_embedding_runtime()
                        profile_changed = True
                        candidate_accepted = True
                elif await self._candidate_is_ready(candidate):
                    # Refresh credentials and retry settings even when they do not
                    # affect the persistent vector-space signature.
                    active_runtime = activate_embedding_runtime(candidate.model_config, candidate.profile.dimension)
                    candidate_accepted = True

                if candidate_accepted:
                    self._last_processed_fingerprint = fingerprint
                    self._last_rejected_fingerprint = None

        if active_runtime is None:
            return

        migration_pending = bool(
            self._store.qdrant.atom_migration_pending or self._store.qdrant.graph_migration_pending
        )
        if self._first_run:
            if migration_pending or not json_vector_indexes_match_profile(active_runtime.profile):
                self._pending_json_signature = active_runtime.profile.signature
            self._first_run = False

        await register_pending_vector_migrations(
            self._store,
            active_runtime.profile,
            task_manager=self._task_manager,
        )

        if profile_changed:
            self._pending_json_signature = active_runtime.profile.signature
        if self._pending_json_signature == active_runtime.profile.signature:
            if await rebuild_json_vector_indexes(active_runtime.profile):
                self._pending_json_signature = None

    async def run(self) -> None:
        async with self._run_lock:
            try:
                await self._run_once()
            except Exception:
                logger.exception(
                    "embedding profile 检测失败，将在下个周期重试",
                    event_code="embedding.profile.monitor_failed",
                )
