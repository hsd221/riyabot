"""记忆追溯链记录器 — 记录记忆原子从编码到入库的完整加工路径

TraceChainRecorder 负责将 TraceStep 记录到 MemoryTraceChain 表，
供后续追溯和审计使用。每个记忆原子的完整加工路径为：
  提取（Layer2Encoder）→ 校验（ObjectivityChecker）→ 写入（MemoryWriter）

Classes:
    TraceStep: 追溯步骤 dataclass，对应 MemoryTraceChain 表的一条记录
    TraceChainRecorder: 追溯链记录器
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.common.logger import get_logger
from src.memory.schema import MemoryTraceChain, memory_db


@dataclass
class TraceStep:
    """追溯步骤 — 对应 MemoryTraceChain 表的一条记录

    Attributes:
        atom_id: 记忆原子 ID
        step_order: 步骤序号（从 1 开始递增）
        agent_name: Agent 名称，如 "Layer2Encoder" / "ObjectivityChecker" / "MemoryWriter"
        operation: 操作类型，如 "extract" / "verify" / "write"
        input_source: 输入来源摘要（可选）
        output_summary: 输出摘要（可选）
        confidence_decay: 置信度衰减因子，0-1 范围（1.0 表示无衰减）
    """

    atom_id: str
    step_order: int
    agent_name: str
    operation: str
    input_source: Optional[str] = None
    output_summary: Optional[str] = None
    confidence_decay: float = 1.0


class TraceChainRecorder:
    """追溯链记录器

    将记忆原子的加工步骤顺序记录到 MemoryTraceChain 表。
    每个原子可能有多步操作，按 step_order 排序形成完整加工链。

    使用方式:
        recorder = TraceChainRecorder()
        recorder.record(TraceStep(atom_id="xxx", step_order=1, ...))
    """

    def __init__(self) -> None:
        self._logger = get_logger("memory.trace")

    # ── 单步记录 ─────────────────────────────────────────────────────

    def record(self, trace: TraceStep) -> bool:
        """记录一个追溯步骤到数据库

        Args:
            trace: 追溯步骤

        Returns:
            bool: 是否成功写入
        """
        try:
            with memory_db:
                MemoryTraceChain.create(
                    atom_id=trace.atom_id,
                    step_number=trace.step_order,
                    agent_name=trace.agent_name,
                    operation_type=trace.operation,
                    input_source=trace.input_source,
                    output_summary=trace.output_summary,
                    confidence_decay=trace.confidence_decay,
                )
            self._logger.debug(
                "追溯步骤已记录",
                atom_id=trace.atom_id,
                step=trace.step_order,
                agent=trace.agent_name,
            )
            return True
        except Exception as e:
            self._logger.error(
                "记录追溯步骤失败",
                atom_id=trace.atom_id,
                step=trace.step_order,
                error=str(e),
            )
            return False

    # ── 追溯链查询 ───────────────────────────────────────────────────

    def get_chain(self, atom_id: str) -> list[TraceStep]:
        """获取指定原子的完整追溯链（按 step_number 升序）

        Args:
            atom_id: 原子 ID

        Returns:
            list[TraceStep]: 按步骤排序的追溯链，失败时返回空列表
        """
        return self.get_lineage(atom_id)

    def get_lineage(self, atom_id: str) -> list[TraceStep]:
        """获取指定原子的完整追溯链（同 get_chain，语义别名）

        Args:
            atom_id: 原子 ID

        Returns:
            list[TraceStep]: 按步骤排序的追溯链，失败时返回空列表
        """
        try:
            with memory_db:
                records = (
                    MemoryTraceChain.select()
                    .where(MemoryTraceChain.atom_id == atom_id)
                    .order_by(MemoryTraceChain.step_number)
                )
                return [
                    TraceStep(
                        atom_id=r.atom_id,
                        step_order=r.step_number,
                        agent_name=r.agent_name,
                        operation=r.operation_type,
                        input_source=r.input_source,
                        output_summary=r.output_summary,
                        confidence_decay=r.confidence_decay,
                    )
                    for r in records
                ]
        except Exception as e:
            self._logger.error("获取追溯链失败", atom_id=atom_id, error=str(e))
            return []

    # ── 批量记录 ─────────────────────────────────────────────────────

    def batch_record(self, traces: list[TraceStep]) -> int:
        """批量记录追溯步骤（单事务原子写入）

        Args:
            traces: 追溯步骤列表

        Returns:
            int: 成功记录的数量
        """
        if not traces:
            return 0
        count = 0
        try:
            with memory_db.atomic():
                for trace in traces:
                    MemoryTraceChain.create(
                        atom_id=trace.atom_id,
                        step_number=trace.step_order,
                        agent_name=trace.agent_name,
                        operation_type=trace.operation,
                        input_source=trace.input_source,
                        output_summary=trace.output_summary,
                        confidence_decay=trace.confidence_decay,
                    )
                    count += 1
            self._logger.debug("批量追溯步骤完成", count=count)
            return count
        except Exception as e:
            self._logger.error("批量记录追溯步骤失败", error=str(e))
            return count

    # ── 工具查询 ─────────────────────────────────────────────────────

    def get_atoms_with_traces(self, limit: int = 100) -> list[str]:
        """获取有追溯链的原子 ID 列表

        Args:
            limit: 返回数量上限

        Returns:
            list[str]: 原子 ID 列表（按追溯记录时间降序）
        """
        try:
            with memory_db:
                records = (
                    MemoryTraceChain.select(MemoryTraceChain.atom_id)
                    .distinct()
                    .order_by(MemoryTraceChain.timestamp.desc())
                    .limit(limit)
                )
                return [r.atom_id for r in records]
        except Exception as e:
            self._logger.error("获取原子追溯列表失败", error=str(e))
            return []

    def _get_logger(self):
        """获取当前日志记录器"""
        return self._logger
