"""
遗忘管理器 — 时间衰减与归档清理

管理记忆原子的生命周期，通过定期衰减扫描降低长尾记忆的权重，
当权重低于归档阈值时保存到 RawMessageArchive 并标记为归档状态，
低于删除阈值时从 SQLite 和 Qdrant 彻底删除。

Classes:
    ForgettingManager: 遗忘管理器，负责衰减/归档/清理全流程
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import datetime, timezone
from typing import Any

from src.common.logger import get_logger
from src.memory.atom import (
    MemoryAtom as MemoryAtomDC,
    AtomType,
    DecayType,
    compute_decay_factor,
    get_fade_level,
)
from src.memory.schema import (
    MemoryAtom as MemoryAtomModel,
    RawMessageArchive,
    memory_db,
)
from src.memory.store import MemoryStore
from src.manager.async_task_manager import AsyncTask

logger = get_logger("memory.forgetting")


def _safe_timestamp(value: Any, default: float | None = None) -> float:
    """安全地将 datetime / float / None 转换为 Unix 时间戳（秒）

    Peewee 的 DateTimeField 在某些场景下可能从 SQLite 返回 float 值，
    此函数防御性地处理 datetime 和 float 两种类型。

    Args:
        value: 可能为 datetime、float、int 或 None
        default: 当 value 为 None 时的默认值；为 None 时使用当前 UTC 时间

    Returns:
        float: Unix 时间戳（秒）
    """
    if value is None:
        return default if default is not None else datetime.now(timezone.utc).timestamp()
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value)


# ── 分页大小 ──────────────────────────────────────────────────────────────────

PAGE_SIZE = 500  # _decay_atoms 每批处理的行数，防止 OOM

# ── 默认阈值 ──────────────────────────────────────────────────────────────────

_DEFAULT_ARCHIVE_THRESHOLD: float = 0.1  # 归档阈值：权重低于此值时归档
_DEFAULT_DELETE_THRESHOLD: float = 0.01  # 删除阈值：权重低于此值时硬删除
_DEFAULT_SWEEP_INTERVAL: int = 3600  # 自动扫描间隔（秒）


# ======================================================================
# ForgettingManager
# ======================================================================


class ForgettingManager:
    """遗忘管理器 — 时间衰减与归档清理

    职责：
    1. 周期性衰减扫描：对所有活跃原子按 decay_type 计算衰减因子并更新权重
    2. 归档褪色记忆：权重 < archive_threshold 的原子保存到 RawMessageArchive 并标记为 archived
    3. 清理过期数据：权重 < delete_threshold 的原子从 SQLite + Qdrant 彻底删除

    Attributes:
        store: MemoryStore 实例
        archive_threshold: 归档阈值（默认 0.1）
        delete_threshold: 删除阈值（默认 0.01）
        sweep_interval: 自动扫描间隔秒数（默认 3600）
    """

    def __init__(
        self,
        store: MemoryStore,
        archive_threshold: float = _DEFAULT_ARCHIVE_THRESHOLD,
        delete_threshold: float = _DEFAULT_DELETE_THRESHOLD,
        sweep_interval: int = _DEFAULT_SWEEP_INTERVAL,
    ) -> None:
        self._store = store
        self.archive_threshold = archive_threshold
        self.delete_threshold = delete_threshold
        self.sweep_interval = sweep_interval
        self._sweep_lock = asyncio.Lock()

    # ── 主扫描入口 ──────────────────────────────────────────────────────

    async def run_sweep(self) -> dict[str, int]:
        """执行一次完整的遗忘扫描

        依次执行衰减 → 归档 → 硬删除三步，返回各步处理计数。

        Returns:
            dict: {"decayed": N, "archived": M, "deleted": K}
        """
        if self._sweep_lock.locked():
            logger.debug("遗忘扫描已在执行中，跳过本轮扫描")
            return {"decayed": 0, "archived": 0, "deleted": 0}

        async with self._sweep_lock:
            _sweep_start = time.monotonic()
            logger.info("遗忘扫描开始")

            decayed = await self._decay_atoms()
            archived = await self._archive_faded()
            deleted = await self._purge_expired()

            result: dict[str, int] = {
                "decayed": decayed,
                "archived": archived,
                "deleted": deleted,
            }
            duration = time.monotonic() - _sweep_start
            logger.info(f"遗忘扫描完成: {decayed} 个衰减, {archived} 个归档, {deleted} 个删除")
            logger.info("遗忘扫除完成", total_duration_ms=round(duration * 1000))
            return result

    # ── 衰减 ─────────────────────────────────────────────────────────────

    async def _decay_atoms(self) -> int:
        """对所有活跃记忆原子应用时间衰减，更新权重

        对每个 status = "active" 的原子：
        new_weight = current_weight × compute_decay_factor(atom)

        Returns:
            int: 权重发生变化的原子数量
        """
        count = 0
        now_ts = datetime.now(timezone.utc).timestamp()

        with memory_db:
            query = MemoryAtomModel.select().where(MemoryAtomModel.status == "active")
            total = query.count()
            if total == 0:
                return 0

            num_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
            idx = 0

            for page in range(1, num_pages + 1):
                batch = query.paginate(page, PAGE_SIZE)
                logger.debug("衰减批次处理", page=page, total_pages=num_pages, batch_size=len(batch))

                for atom_model in batch:
                    try:
                        atom_type = AtomType(atom_model.atom_type)
                        decay_type = DecayType(atom_model.decay_type)
                    except ValueError:
                        idx += 1
                        continue

                    last_accessed = _safe_timestamp(atom_model.last_accessed_at, now_ts)

                    old_weight = atom_model.weight

                    atom_dc = MemoryAtomDC(
                        atom_id=atom_model.atom_id,
                        atom_type=atom_type,
                        content=atom_model.content or "",
                        importance=atom_model.importance,
                        confidence=atom_model.confidence,
                        weight=old_weight,
                        created_at=_safe_timestamp(atom_model.created_at, now_ts),
                        last_accessed_at=last_accessed,
                        ttl_days=float(atom_model.ttl_days or 7),
                        decay_type=decay_type,
                        reinforcement_count=atom_model.reinforcement_count or 0,
                        source_scene=atom_model.source_scene or "unknown",
                        privacy_level=atom_model.privacy_level or "context_sensitive",
                        status=atom_model.status,
                    )

                    decay_factor = compute_decay_factor(atom_dc, current_time=now_ts)
                    new_weight = max(0.0, old_weight * decay_factor)

                    if not math.isclose(new_weight, old_weight, rel_tol=1e-6):
                        MemoryAtomModel.update(weight=new_weight).where(
                            MemoryAtomModel.atom_id == atom_model.atom_id
                        ).execute()
                        count += 1

                    if idx % 10 == 0:
                        logger.debug(
                            "衰减进度",
                            processed=idx,
                            total=total,
                            sample_decay=f"{atom_model.atom_id}: {old_weight:.4f}→{new_weight:.4f}",
                        )

                    idx += 1

                logger.info(
                    "衰减批次完成",
                    page=page,
                    total_pages=num_pages,
                    page_processed=idx,
                    total=total,
                )

        logger.debug(f"衰减: {count} 个原子权重已更新")
        return count

    # ── 归档 ─────────────────────────────────────────────────────────────

    async def _archive_faded(self) -> int:
        """归档权重低于阈值的记忆原子

        将 status = "active" 且 weight < archive_threshold 的原子：
        1. 保存完整内容到 RawMessageArchive
        2. 标记 status = "archived"

        Returns:
            int: 归档的原子数量
        """
        count = 0

        with memory_db:
            query = MemoryAtomModel.select().where(
                MemoryAtomModel.status == "active",
                MemoryAtomModel.weight < self.archive_threshold,
            )
            for atom_model in query:
                try:
                    self._archive_one(atom_model)
                    atom_model.status = "archived"
                    atom_model.save()
                    count += 1
                except Exception as e:
                    logger.error(f"归档原子失败 ({atom_model.atom_id}): {e}")

        if count > 0:
            logger.info(f"归档: {count} 个原子已归档 (weight < {self.archive_threshold})")
        return count

    async def archive_atom(self, atom: MemoryAtomModel) -> None:
        """将单个记忆原子保存到归档表

        在硬删除前调用此方法保存原子内容，确保数据可追溯。
        供 force_forget 或外部调用使用。

        Args:
            atom: Peewee MemoryAtom 模型实例
        """
        self._archive_one(atom)

    def _archive_one(self, atom: MemoryAtomModel) -> None:
        """内部：将单个原子内容 + 元数据写入 RawMessageArchive

        Args:
            atom: Peewee MemoryAtom 模型实例
        """
        metadata: dict[str, Any] = {
            "atom_id": atom.atom_id,
            "atom_type": atom.atom_type,
            "importance": atom.importance,
            "confidence": atom.confidence,
            "weight": atom.weight,
            "source_scene": atom.source_scene,
            "privacy_level": atom.privacy_level,
            "reinforcement_count": atom.reinforcement_count,
            "ttl_days": atom.ttl_days,
            "decay_type": atom.decay_type,
            "trace_chain_id": atom.trace_chain_id,
            "embedding_id": atom.embedding_id,
        }
        RawMessageArchive.create(
            stream_id=f"memory_archive_{atom.source_scene or 'unknown'}",
            message_id=atom.atom_id,
            user_id="system",
            content=json.dumps(
                {"content": atom.content, "metadata": metadata},
                ensure_ascii=False,
            ),
            timestamp=_safe_timestamp(atom.created_at),
            chat_type=f"memory_archive_{atom.atom_type or 'unknown'}",
        )
        logger.debug("原子归档成功", atom_id=atom.atom_id, archive_table="RawMessageArchive")

    # ── 硬删除 ───────────────────────────────────────────────────────────

    async def _purge_expired(self) -> int:
        """硬删除权重低于删除阈值的记忆原子

        将 weight < delete_threshold 的原子：
        1. 从 Qdrant 删除向量索引
        2. 从 SQLite 删除记录

        Returns:
            int: 删除的原子数量
        """
        count = 0

        with memory_db:
            query = MemoryAtomModel.select().where(
                MemoryAtomModel.weight < self.delete_threshold,
            )
            for atom_model in query:
                try:
                    atom_id = atom_model.atom_id
                    await self._store.qdrant.delete_atom_vector(atom_id)
                    atom_model.delete_instance()
                    count += 1
                except Exception as e:
                    logger.error(f"硬删除原子失败 ({atom_model.atom_id}): {e}")

        if count > 0:
            logger.info(f"清理: {count} 个原子已硬删除 (weight < {self.delete_threshold})")
        return count

    # ── 强制遗忘 ─────────────────────────────────────────────────────────

    async def force_forget(self, atom_ids: list[str]) -> int:
        """强制遗忘指定记忆原子

        对指定的原子执行：归档（保存到 RawMessageArchive）→ 硬删除（Qdrant + SQLite）。
        无论原子当前权重如何，都直接归档并删除。

        Args:
            atom_ids: 要遗忘的原子 ID 列表

        Returns:
            int: 成功遗忘的原子数量
        """
        count = 0

        logger.info("强制遗忘", atom_id_count=len(atom_ids), atom_ids=atom_ids)

        for atom_id in atom_ids:
            try:
                atom_model = MemoryAtomModel.get_or_none(MemoryAtomModel.atom_id == atom_id)
                if atom_model is None:
                    logger.warning(f"强制遗忘: 原子不存在 {atom_id}")
                    continue

                self._archive_one(atom_model)
                await self._store.qdrant.delete_atom_vector(atom_id)
                atom_model.delete_instance()
                count += 1
                logger.debug(f"强制遗忘: {atom_id}")

            except Exception as e:
                logger.error(f"强制遗忘失败 ({atom_id}): {e}")

        if count > 0:
            logger.info(f"强制遗忘完成: {count} 个原子")
        return count

    # ── 统计信息 ─────────────────────────────────────────────────────────

    async def get_decay_stats(self) -> dict[str, Any]:
        """获取衰减统计信息

        Returns:
            dict: 包含以下字段：
                - total_active_atoms: 活跃原子总数
                - avg_weight: 平均权重
                - max_weight: 最大权重
                - min_weight: 最小权重
                - fade_level_counts: 按褪色等级的原子分布
                - needs_archive: 需要归档的原子数
                - archive_threshold: 归档阈值
                - delete_threshold: 删除阈值
        """
        total = 0
        weights: list[float] = []
        fade_levels: dict[str, int] = {
            "完整": 0,
            "摘要": 0,
            "模糊": 0,
            "残影": 0,
        }
        needs_archive = 0

        with memory_db:
            query = MemoryAtomModel.select().where(MemoryAtomModel.status == "active")
            for atom_model in query:
                total += 1
                w = atom_model.weight
                weights.append(w)

                level = get_fade_level(w)
                fade_levels[level] = fade_levels.get(level, 0) + 1

                if w < self.archive_threshold:
                    needs_archive += 1

        avg_weight = sum(weights) / len(weights) if weights else 0.0
        max_weight = max(weights) if weights else 0.0
        min_weight = min(weights) if weights else 0.0

        stats = {
            "total_active_atoms": total,
            "avg_weight": round(avg_weight, 4),
            "max_weight": round(max_weight, 4),
            "min_weight": round(min_weight, 4),
            "fade_level_counts": fade_levels,
            "needs_archive": needs_archive,
            "archive_threshold": self.archive_threshold,
            "delete_threshold": self.delete_threshold,
            "sweep_interval_seconds": self.sweep_interval,
        }
        logger.debug(
            "遗忘统计",
            total_atoms=stats["total_active_atoms"],
            archived=stats["needs_archive"],
            deleted=0,
            active=stats["total_active_atoms"] - stats["needs_archive"],
        )
        return stats


# ======================================================================
# ForgettingSweepTask — AsyncTask 包装
# ======================================================================


class ForgettingSweepTask(AsyncTask):
    """记忆遗忘定期扫描任务

    包装 ForgettingManager.run_sweep() 为 AsyncTask，
    每 3600 秒执行一次：衰减 → 归档 → 硬删除。
    """

    def __init__(self, forgetting_manager: ForgettingManager):
        super().__init__(task_name="记忆遗忘扫描", run_interval=3600)
        self._manager = forgetting_manager

    async def run(self):
        await self._manager.run_sweep()
