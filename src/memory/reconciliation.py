"""
异步协调任务 — 检测并修复 SQLite + Qdrant 双写不一致

在记忆系统的双写路径中（SQLite 写入元数据，Qdrant 写入向量索引），
可能因进程崩溃或网络抖动导致一侧写入成功而另一侧失败。
本模块的 ReconciliationTask 定期扫描写操作日志，识别不一致对并进行补偿：

- SQLite 有原子、Qdrant 缺少向量 → 重新计算 embedding 并 upsert 到 Qdrant
- Qdrant 有向量、SQLite 缺少原子 → 从 Qdrant 删除孤立向量

设计约束：
- 补偿操作直接调用 store / qdrant 方法，不走 WriteOperation，避免无限循环
- 对持续失败的补偿设置最大重试次数，避免空转
"""

from __future__ import annotations

import time
from typing import Any, Optional

from src.common.logger import get_logger
from src.manager.async_task_manager import AsyncTask
from src.memory.embedding_utils import generate_embedding
from src.memory.store import MemoryStore
from src.memory.write_ops import WriteOp, WriteOpLogger

logger = get_logger("recon")

# 每侧补偿的最大重试次数（累计，超过后不再处理）
_MAX_RETRIES = 5
_MAX_DRIFT_REPAIRS_PER_RUN = 50
_DRIFT_RETRY_BASE_SECONDS = 30.0
_DRIFT_RETRY_MAX_SECONDS = 600.0
_MAX_EMBEDDING_REFRESH_ATTEMPTS = 3


class ReconciliationTask(AsyncTask):
    """双写一致性协调任务

    每 120 秒扫描一次 WriteOpLogger 中的不一致操作记录，
    对 SQLite ↔ Qdrant 之间的数据不一致进行补偿。
    """

    def __init__(
        self,
        store: MemoryStore,
        op_logger: Optional[WriteOpLogger] = None,
        interval: int = 120,
    ):
        super().__init__(task_name="双写一致性协调", run_interval=interval)
        self._store = store
        self._op_logger = op_logger
        # 记录已经重试过的 op_id，避免每轮都重复处理同一组持续失败的操作
        self._blacklist: set[str] = set()
        # 孤立向量至少连续两轮出现才允许删除，降低并发写入期间的误删风险。
        self._orphan_candidates: dict[str, dict[str, Any]] = {}
        self._drift_failure_counts: dict[str, int] = {}
        self._drift_retry_after: dict[str, float] = {}
        self._drift_retry_base_seconds = max(_DRIFT_RETRY_BASE_SECONDS, float(interval) * 2)
        self._forced_resync_ids: set[str] = set()
        self._forced_cleanup_ids: set[str] = set()

    async def run(self) -> None:
        inconsistent_pairs: list[tuple[WriteOp, WriteOp]] = []
        if self._op_logger is not None:
            try:
                inconsistent_pairs = self._op_logger.get_inconsistent_ops()
            except Exception as e:
                logger.error("获取不一致操作记录失败", error=str(e), exc_info=True)

        if inconsistent_pairs:
            logger.info("发现不一致写操作，开始协调", count=len(inconsistent_pairs))

        reconciled = 0
        skipped = 0

        for completed_op, failed_op in inconsistent_pairs:
            if failed_op.op_id in self._blacklist:
                skipped += 1
                continue

            if failed_op.retry_count >= _MAX_RETRIES:
                logger.warning(
                    "操作已达最大重试次数，加入黑名单",
                    extra={
                        "op_id": failed_op.op_id,
                        "op_type": failed_op.op_type.value,
                        "target": failed_op.target,
                        "retries": failed_op.retry_count,
                    },
                )
                self._blacklist.add(failed_op.op_id)
                skipped += 1
                continue

            try:
                ok = await self._reconcile_one(completed_op, failed_op)
                if ok:
                    reconciled += 1
                else:
                    # 补偿失败，增加失败计数
                    if self._op_logger is not None:
                        self._op_logger._update_op(
                            failed_op.op_id,
                            retry_count=failed_op.retry_count + 1,
                        )
            except Exception as e:
                logger.error(
                    "协调操作异常",
                    extra={
                        "op_id": failed_op.op_id,
                        "op_type": failed_op.op_type.value,
                        "error": str(e),
                    },
                )

        drift_repaired, drift_removed = await self._reconcile_storage_drift()
        if reconciled > 0 or skipped > 0 or drift_repaired > 0 or drift_removed > 0:
            logger.info(
                "一致性协调完成",
                log_reconciled=reconciled,
                drift_repaired=drift_repaired,
                drift_removed=drift_removed,
                skipped=skipped,
            )

    async def _reconcile_storage_drift(self) -> tuple[int, int]:
        """比较两侧真实 ID，修复没有写操作日志可配对的数据漂移。"""
        try:
            # 先读 Qdrant，再读 SQLite。并发新写入最多会触发一次幂等 upsert，
            # 不会因为 SQLite 的旧快照把刚写入的向量当成孤儿删除。
            qdrant_points = await self._list_qdrant_points()
            sqlite_all_ids = await self._store.list_atom_ids()
            sqlite_active_ids = await self._store.list_atom_ids(status="active")
        except Exception as e:
            logger.error("读取存储一致性状态失败", error=str(e), exc_info=True)
            return 0, 0

        if qdrant_points is None or sqlite_all_ids is None or sqlite_active_ids is None:
            logger.debug("存储一致性状态不可用，跳过本轮真实差异扫描")
            return 0, 0

        qdrant_business_ids = {
            point["business_id"]
            for point in qdrant_points
            if isinstance(point.get("business_id"), str) and point["business_id"]
        }
        missing_ids = sqlite_active_ids - qdrant_business_ids

        reactivated_ids = self._forced_cleanup_ids & sqlite_active_ids
        self._forced_cleanup_ids.difference_update(reactivated_ids)
        self._forced_resync_ids.update(reactivated_ids)

        inactive_resync_ids = self._forced_resync_ids - sqlite_active_ids
        self._forced_resync_ids.difference_update(inactive_resync_ids)
        self._forced_cleanup_ids.update(inactive_resync_ids)

        normalized_sqlite_ids = self._normalized_sqlite_id_map(sqlite_all_ids)
        current_orphans: dict[str, dict[str, Any]] = {}
        for point in qdrant_points:
            business_id = point.get("business_id")
            physical_id = point["physical_id"]
            sqlite_lookup_id = (
                business_id
                if isinstance(business_id, str)
                else normalized_sqlite_ids.get(self._normalized_point_key(physical_id), str(physical_id))
            )
            if sqlite_lookup_id in self._forced_cleanup_ids:
                continue
            if sqlite_lookup_id not in sqlite_all_ids:
                current_orphans[self._point_key(physical_id)] = point

        confirmed_orphans = {key: point for key, point in current_orphans.items() if key in self._orphan_candidates}
        self._orphan_candidates = current_orphans
        sync_ids = missing_ids | self._forced_resync_ids
        current_retry_keys = {f"sync:{atom_id}" for atom_id in sync_ids}
        current_retry_keys.update(f"cleanup:{atom_id}" for atom_id in self._forced_cleanup_ids)
        current_retry_keys.update(f"orphan:{key}" for key in current_orphans)
        self._prune_drift_retry_state(current_retry_keys)

        if not missing_ids and not current_orphans and not self._forced_resync_ids and not self._forced_cleanup_ids:
            return 0, 0

        logger.info(
            "发现存储真实差异",
            extra={
                "missing_vectors": len(missing_ids),
                "orphan_vectors": len(current_orphans),
                "confirmed_orphans": len(confirmed_orphans),
                "forced_resync": len(self._forced_resync_ids),
                "forced_cleanup": len(self._forced_cleanup_ids),
            },
        )

        repaired = 0
        missing_work = [(f"sync:{atom_id}", atom_id) for atom_id in sorted(sync_ids)]
        for retry_key, atom_id in self._eligible_drift_work(missing_work):
            if await self._sync_sqlite_to_qdrant(atom_id):
                repaired += 1
                self._mark_drift_success(retry_key)
            else:
                self._mark_drift_failure(retry_key)

        removed = 0
        cleanup_work = [(f"cleanup:{atom_id}", atom_id) for atom_id in sorted(self._forced_cleanup_ids)]
        for retry_key, atom_id in self._eligible_drift_work(cleanup_work):
            if await self._resolve_forced_cleanup(atom_id):
                removed += 1
                self._mark_drift_success(retry_key)
            else:
                self._mark_drift_failure(retry_key)

        orphan_work = [(f"orphan:{key}", point) for key, point in sorted(confirmed_orphans.items())]
        for retry_key, point in self._eligible_drift_work(orphan_work):
            if await self._remove_orphan_vector(
                point["physical_id"],
                business_id=point.get("business_id"),
            ):
                removed += 1
                self._mark_drift_success(retry_key)
                self._orphan_candidates.pop(self._point_key(point["physical_id"]), None)
            else:
                self._mark_drift_failure(retry_key)

        return repaired, removed

    async def _list_qdrant_points(self) -> Optional[list[dict[str, Any]]]:
        """读取 Qdrant point；兼容尚未实现 point 枚举的存储适配器。"""
        list_points = getattr(self._store.qdrant, "list_atom_points", None)
        if callable(list_points):
            return await list_points()

        atom_ids = await self._store.qdrant.list_atom_ids()
        if atom_ids is None:
            return None
        return [{"physical_id": atom_id, "business_id": atom_id} for atom_id in atom_ids]

    @staticmethod
    def _point_key(point_id: str | int) -> str:
        return f"{type(point_id).__name__}:{point_id}"

    def _normalized_point_key(self, point_id: str | int) -> str:
        normalizer = getattr(self._store.qdrant, "_normalize_point_id", None)
        normalized = normalizer(point_id) if callable(normalizer) else point_id
        return self._point_key(normalized)

    def _normalized_sqlite_id_map(self, sqlite_ids: set[str]) -> dict[str, str]:
        return {self._normalized_point_key(atom_id): atom_id for atom_id in sqlite_ids}

    def _eligible_drift_work(self, work: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
        now = time.monotonic()
        return [item for item in work if self._drift_retry_after.get(item[0], 0.0) <= now][:_MAX_DRIFT_REPAIRS_PER_RUN]

    def _mark_drift_failure(self, key: str) -> None:
        failures = self._drift_failure_counts.get(key, 0) + 1
        self._drift_failure_counts[key] = failures
        max_delay = max(_DRIFT_RETRY_MAX_SECONDS, self._drift_retry_base_seconds)
        delay = min(max_delay, self._drift_retry_base_seconds * (2 ** min(failures - 1, 4)))
        self._drift_retry_after[key] = time.monotonic() + delay

    def _mark_drift_success(self, key: str) -> None:
        self._drift_failure_counts.pop(key, None)
        self._drift_retry_after.pop(key, None)

    def _prune_drift_retry_state(self, current_keys: set[str]) -> None:
        stale_keys = (set(self._drift_failure_counts) | set(self._drift_retry_after)) - current_keys
        for key in stale_keys:
            self._mark_drift_success(key)

    async def _reconcile_one(self, completed_op: WriteOp, failed_op: WriteOp) -> bool:
        """协调一组不一致的写操作

        Args:
            completed_op: 成功侧操作
            failed_op: 失败侧操作

        Returns:
            True 表示协调成功
        """
        # 提取共同的 atom_id（取交集，通常只有一个）
        common_ids = set(completed_op.atom_ids) & set(failed_op.atom_ids)
        if not common_ids:
            logger.warning(
                "不一致操作对无重叠 atom_ids，跳过",
                extra={
                    "completed": completed_op.op_id,
                    "failed": failed_op.op_id,
                },
            )
            return False

        atom_id = next(iter(common_ids))

        # 判断哪一侧成功、哪一侧失败
        # completed_op.target 是成功侧，failed_op.target 是失败侧
        if completed_op.target == "sqlite" and failed_op.target == "qdrant":
            # Case 1: SQLite 有记录，Qdrant 缺向量 → 补充到 Qdrant
            return await self._sync_sqlite_to_qdrant(atom_id, completed_op)
        elif completed_op.target == "qdrant" and failed_op.target == "sqlite":
            # Case 2: Qdrant 有向量，SQLite 缺记录 → 删除孤立向量
            return await self._remove_orphan_vector(atom_id, failed_op)
        else:
            # 同一侧出现 completed/failed 对，或 target 不是 sqlite/qdrant
            # 这不是跨存储不一致，跳过
            logger.debug(
                "非跨存储不一致，跳过",
                extra={
                    "completed_target": completed_op.target,
                    "failed_target": failed_op.target,
                    "op_id": failed_op.op_id,
                },
            )
            return False

    async def _sync_sqlite_to_qdrant(self, atom_id: str, completed_op: Optional[WriteOp] = None) -> bool:
        """将 SQLite 中的原子同步到 Qdrant（补偿 Qdrant 丢失）

        直接调用 store.qdrant.upsert_atom_vector 而非 WriteOperation，
        避免协调操作本身又记录为写操作导致无限循环。

        Args:
            atom_id: 要同步的原子 ID
            completed_op: 成功的 SQLite 写操作（用于日志）

        Returns:
            True 表示同步成功
        """
        atom_data = await self._read_active_atom(atom_id)
        if atom_data is None:
            if atom_id in self._forced_resync_ids:
                self._forced_resync_ids.discard(atom_id)
                self._forced_cleanup_ids.add(atom_id)
                return await self._delete_stale_vector(atom_id, queue_cleanup=True)
            return False

        self._forced_cleanup_ids.discard(atom_id)

        for _attempt in range(_MAX_EMBEDDING_REFRESH_ATTEMPTS):
            content = atom_data.get("content", "")
            if not content:
                logger.warning("原子内容为空，无法生成 embedding", extra={"atom_id": atom_id})
                return await self._abort_forced_resync(atom_id)

            try:
                embedding = await generate_embedding(content)
            except Exception as e:
                logger.error("生成 embedding 失败", extra={"atom_id": atom_id, "error": str(e)})
                return await self._abort_forced_resync(atom_id)

            if not embedding:
                logger.warning("生成 embedding 返回空", extra={"atom_id": atom_id})
                return await self._abort_forced_resync(atom_id)

            latest_atom = await self._read_active_atom(atom_id)
            if latest_atom is None:
                if atom_id in self._forced_resync_ids:
                    self._forced_resync_ids.discard(atom_id)
                    self._forced_cleanup_ids.add(atom_id)
                    return await self._delete_stale_vector(atom_id, queue_cleanup=True)
                return False
            if self._atom_sync_signature(atom_id, latest_atom) != self._atom_sync_signature(atom_id, atom_data):
                atom_data = latest_atom
                continue
            atom_data = latest_atom

            try:
                ok = await self._store.qdrant.upsert_atom_vector(
                    point_id=atom_id,
                    vector=embedding,
                    payload=self._atom_vector_payload(atom_id, atom_data),
                )
            except Exception as e:
                logger.error("协调: Qdrant upsert 异常", extra={"atom_id": atom_id, "error": str(e)})
                return await self._abort_forced_resync(atom_id)

            if not ok:
                logger.warning("协调: Qdrant upsert 返回 False", extra={"atom_id": atom_id})
                return await self._abort_forced_resync(atom_id)

            self._forced_resync_ids.add(atom_id)

            post_upsert_atom = await self._read_active_atom(atom_id, log_missing=False)
            if post_upsert_atom is None:
                self._forced_resync_ids.discard(atom_id)
                self._forced_cleanup_ids.add(atom_id)
                return await self._delete_stale_vector(atom_id, queue_cleanup=True)
            if self._atom_sync_signature(atom_id, post_upsert_atom) != self._atom_sync_signature(atom_id, atom_data):
                await self._delete_stale_vector(atom_id, queue_cleanup=False)
                atom_data = post_upsert_atom
                continue

            self._forced_resync_ids.discard(atom_id)
            self._forced_cleanup_ids.discard(atom_id)
            logger.info("协调: 原子已同步到 Qdrant", extra={"atom_id": atom_id})
            return True

        logger.warning("协调: 原子状态持续变化，删除过期向量后等待下轮重建", atom_id=atom_id)
        return await self._abort_forced_resync(atom_id)

    async def _read_active_atom(self, atom_id: str, *, log_missing: bool = True) -> Optional[dict[str, Any]]:
        try:
            atom_data = await self._store.get_atom(atom_id)
        except Exception as e:
            logger.error("从 SQLite 读取原子失败", extra={"atom_id": atom_id, "error": str(e)})
            return None

        if not atom_data:
            if log_missing:
                logger.warning("SQLite 中未找到原子，无法同步到 Qdrant", extra={"atom_id": atom_id})
            return None

        atom_data = dict(atom_data)
        if atom_data.get("status", "active") != "active":
            logger.debug(
                "原子已非 active，跳过向量补写",
                extra={"atom_id": atom_id, "status": atom_data.get("status")},
            )
            return None
        return atom_data

    @staticmethod
    def _atom_vector_payload(atom_id: str, atom_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "atom_id": atom_id,
            "atom_type": atom_data.get("atom_type", "factual"),
            "user_id": atom_data.get("user_id"),
            "group_id": atom_data.get("group_id"),
            "weight": atom_data.get("weight", 0.5),
            "importance": atom_data.get("importance", 0.5),
            "confidence": atom_data.get("confidence", 0.5),
            "status": atom_data.get("status", "active"),
            "source_scene": atom_data.get("source_scene", "chat"),
            "source_id": atom_data.get("source_id"),
            "privacy_level": atom_data.get("privacy_level", "context_sensitive"),
        }

    @classmethod
    def _atom_sync_signature(cls, atom_id: str, atom_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return str(atom_data.get("content", "")), cls._atom_vector_payload(atom_id, atom_data)

    async def _abort_forced_resync(self, atom_id: str) -> bool:
        if atom_id in self._forced_resync_ids:
            await self._delete_stale_vector(atom_id, queue_cleanup=False)
        return False

    async def _resolve_forced_cleanup(self, atom_id: str) -> bool:
        active_ids = await self._store.list_atom_ids(status="active")
        if active_ids is None:
            return False
        if atom_id in active_ids:
            self._forced_cleanup_ids.discard(atom_id)
            self._forced_resync_ids.add(atom_id)
            return await self._sync_sqlite_to_qdrant(atom_id)
        return await self._delete_stale_vector(atom_id, queue_cleanup=True)

    async def _delete_stale_vector(self, atom_id: str, *, queue_cleanup: bool) -> bool:
        try:
            deleted = await self._store.qdrant.delete_atom_vector(atom_id)
        except Exception as e:
            logger.error("协调: 过期向量删除异常", atom_id=atom_id, error=str(e))
            if queue_cleanup:
                self._forced_cleanup_ids.add(atom_id)
            return False
        if deleted:
            self._forced_cleanup_ids.discard(atom_id)
        else:
            logger.warning("协调: 过期向量删除返回 False", atom_id=atom_id)
            if queue_cleanup:
                self._forced_cleanup_ids.add(atom_id)
        return deleted

    async def _remove_orphan_vector(
        self,
        point_id: str | int,
        failed_op: Optional[WriteOp] = None,
        *,
        business_id: Optional[str] = None,
    ) -> bool:
        """从 Qdrant 删除孤立向量（SQLite 已无记录）

        Args:
            point_id: 要删除的 Qdrant 物理 point ID
            failed_op: 失败的 SQLite 操作（用于日志）
            business_id: 已验证的业务 atom_id

        Returns:
            True 表示删除成功
        """
        try:
            sqlite_ids = await self._store.list_atom_ids()
            if sqlite_ids is None:
                return False
            lookup_id = business_id or self._normalized_sqlite_id_map(sqlite_ids).get(
                self._normalized_point_key(point_id), str(point_id)
            )
            if lookup_id in sqlite_ids:
                logger.debug("协调: SQLite 原子已存在，取消删除向量", extra={"atom_id": lookup_id})
                return True

            ok = await self._store.qdrant.delete_atom_vector(point_id)
            if ok:
                logger.info(
                    "协调: 孤立向量已从 Qdrant 删除",
                    extra={"atom_id": lookup_id, "physical_id": str(point_id)},
                )

                # 删除与 SQLite 新写入发生竞态时，立即把向量补回。
                latest_sqlite_ids = await self._store.list_atom_ids()
                restored_id = None
                if latest_sqlite_ids is not None:
                    restored_id = business_id or self._normalized_sqlite_id_map(latest_sqlite_ids).get(
                        self._normalized_point_key(point_id)
                    )
                if restored_id and restored_id in latest_sqlite_ids:
                    logger.warning("协调: 删除期间检测到 SQLite 新写入，重新补写向量", atom_id=restored_id)
                    return await self._sync_sqlite_to_qdrant(restored_id)
                return True
            logger.warning(
                "协调: Qdrant 删除返回 False",
                extra={"atom_id": lookup_id, "physical_id": str(point_id)},
            )
            return False
        except Exception as e:
            logger.error(
                "协调: 删除 Qdrant 孤立向量异常",
                extra={"atom_id": business_id or str(point_id), "physical_id": str(point_id), "error": str(e)},
            )
            return False
