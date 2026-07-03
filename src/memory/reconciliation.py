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

from typing import Any, Optional

from src.common.logger import get_logger
from src.manager.async_task_manager import AsyncTask
from src.memory.embedding_utils import generate_embedding
from src.memory.store import MemoryStore
from src.memory.write_ops import WriteOp, WriteOpLogger

logger = get_logger("recon")

# 每侧补偿的最大重试次数（累计，超过后不再处理）
_MAX_RETRIES = 5


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

    async def run(self) -> None:
        if self._op_logger is None:
            return

        try:
            inconsistent_pairs = self._op_logger.get_inconsistent_ops()
        except Exception as e:
            logger.error("获取不一致操作记录失败: %s", e, exc_info=True)
            return

        if not inconsistent_pairs:
            return

        logger.info("发现 %d 组不一致写操作，开始协调", len(inconsistent_pairs))

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

        if reconciled > 0 or skipped > 0:
            logger.info(
                "协调完成: %d 已修复, %d 跳过/黑名单",
                reconciled,
                skipped,
            )

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

    async def _sync_sqlite_to_qdrant(self, atom_id: str, completed_op: WriteOp) -> bool:
        """将 SQLite 中的原子同步到 Qdrant（补偿 Qdrant 丢失）

        直接调用 store.qdrant.upsert_atom_vector 而非 WriteOperation，
        避免协调操作本身又记录为写操作导致无限循环。

        Args:
            atom_id: 要同步的原子 ID
            completed_op: 成功的 SQLite 写操作（用于日志）

        Returns:
            True 表示同步成功
        """
        # 查找最新的不成功操作的 payload 中的原子数据
        # （优先使用 payload，避免额外的 SQLite 查询）
        atom_data: Optional[dict[str, Any]] = None
        if completed_op.payload and "atom" in completed_op.payload:
            atom_data = completed_op.payload.get("atom")
        elif completed_op.payload and "updates" in completed_op.payload:
            # UPDATE_ATOM 类型：payload 只有 updates 字段
            # 需要从 SQLite 读取完整数据
            pass  # 走下面的 SQLite 读取兜底

        # 兜底：从 SQLite 读取
        if atom_data is None:
            try:
                atom_data = await self._store.get_atom(atom_id)
            except Exception as e:
                logger.error(
                    "从 SQLite 读取原子失败",
                    extra={"atom_id": atom_id, "error": str(e)},
                )
                return False

        if not atom_data:
            logger.warning(
                "SQLite 中未找到原子，无法同步到 Qdrant",
                extra={"atom_id": atom_id},
            )
            return False

        content = atom_data.get("content", "")
        if not content:
            logger.warning(
                "原子内容为空，无法生成 embedding",
                extra={"atom_id": atom_id},
            )
            return False

        # 生成 embedding
        try:
            embedding = await generate_embedding(content)
        except Exception as e:
            logger.error(
                "生成 embedding 失败",
                extra={"atom_id": atom_id, "error": str(e)},
            )
            return False

        if not embedding:
            logger.warning(
                "生成 embedding 返回空",
                extra={"atom_id": atom_id},
            )
            return False

        # 直接 upsert 到 Qdrant（不走 WriteOperation，避免无限循环）
        try:
            ok = await self._store.qdrant.upsert_atom_vector(
                point_id=atom_id,
                vector=embedding,
                payload={
                    "atom_id": atom_id,
                    "atom_type": atom_data.get("atom_type", "factual"),
                    "weight": atom_data.get("weight", 0.5),
                    "importance": atom_data.get("importance", 0.5),
                    "confidence": atom_data.get("confidence", 0.5),
                    "status": atom_data.get("status", "active"),
                    "source_scene": atom_data.get("source_scene", "chat"),
                    "source_id": atom_data.get("source_id"),
                    "privacy_level": atom_data.get("privacy_level", "context_sensitive"),
                },
            )
            if ok:
                logger.info(
                    "协调: 原子已同步到 Qdrant",
                    extra={"atom_id": atom_id},
                )
                return True
            logger.warning(
                "协调: Qdrant upsert 返回 False",
                extra={"atom_id": atom_id},
            )
            return False
        except Exception as e:
            logger.error(
                "协调: Qdrant upsert 异常",
                extra={"atom_id": atom_id, "error": str(e)},
            )
            return False

    async def _remove_orphan_vector(self, atom_id: str, failed_op: WriteOp) -> bool:
        """从 Qdrant 删除孤立向量（SQLite 已无记录）

        Args:
            atom_id: 要删除的向量 ID
            failed_op: 失败的 SQLite 操作（用于日志）

        Returns:
            True 表示删除成功
        """
        try:
            ok = await self._store.qdrant.delete_atom_vector(atom_id)
            if ok:
                logger.info(
                    "协调: 孤立向量已从 Qdrant 删除",
                    extra={"atom_id": atom_id},
                )
                return True
            # delete_atom_vector 返回 False 可能意味着 Qdrant 也不存在该向量
            # 这实际上不是问题 — 目标状态已经达成
            logger.debug(
                "协调: Qdrant 删除返回 False（向量可能已不存在）",
                extra={"atom_id": atom_id},
            )
            return True
        except Exception as e:
            logger.error(
                "协调: 删除 Qdrant 孤立向量异常",
                extra={"atom_id": atom_id, "error": str(e)},
            )
            return False
