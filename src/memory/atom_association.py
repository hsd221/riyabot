"""
原子到原子关联网络 — 记忆原子之间的显式关联边。

创建和管理记忆原子之间的直接关联边，用于：
- CO_OCCURRENCE：在时间上接近且共享 >= 2 个实体的原子
- CAUSAL：atom_a 的实体被包含在 atom_b 的实体中的原子对
- SEQUENTIAL：60 秒内来自同一 stream_id 的原子
- DREAM_DISCOVERED：由 Dream Weaver 代理发现的关联
"""

import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from src.common.logger import get_logger
from src.memory.schema import AtomAssociationModel, memory_db

logger = get_logger("memory.association")

# 关联权重增量强化系数（每次 evidence 累加时的增长速率）
_WEIGHT_GROWTH_RATE: float = 0.1


class AssociationType(str, Enum):
    """原子到原子关联的类型。"""

    CO_OCCURRENCE = "co_occurrence"
    CAUSAL = "causal"
    SEQUENTIAL = "sequential"
    DREAM_DISCOVERED = "dream_discovered"


@dataclass
class AtomAssociation:
    """两个记忆原子之间的关联。

    属性：
        atom_a_id：第一个原子 ID（字典序较小）
        atom_b_id：第二个原子 ID（字典序较大）
        association_type：关联类型
        weight：关联强度 0-1
        evidence_count：该关联被强化的次数
        created_at：关联首次创建的时间
    """

    atom_a_id: str
    atom_b_id: str
    association_type: AssociationType
    weight: float = 0.5
    evidence_count: int = 1
    created_at: Optional[datetime.datetime] = None


class AtomAssociationStore:
    """原子到原子关联边的存储。

    提供 CRUD、基于规则的批量构建、链遍历（BFS）、
    以及弱边清理功能。所有操作使用共享的 memory.db。
    """

    def __init__(self) -> None:
        self.db = memory_db
        # 自动创建表（幂等）
        with self.db:
            self.db.create_tables([AtomAssociationModel], safe=True)

    # ------------------------------------------------------------------
    # CRUD 操作
    # ------------------------------------------------------------------

    def add_association(
        self,
        atom_a_id: str,
        atom_b_id: str,
        assoc_type: AssociationType,
        weight: float,
    ) -> None:
        """Upsert：创建或增加 evidence_count 并提升权重。

        原子 ID 通过字典序归一化，确保 (a, b) 和 (b, a) 映射到同一行。
        """
        if atom_a_id > atom_b_id:
            atom_a_id, atom_b_id = atom_b_id, atom_a_id

        try:
            with self.db.atomic():
                existing = AtomAssociationModel.get_or_none(
                    (AtomAssociationModel.atom_a_id == atom_a_id)
                    & (AtomAssociationModel.atom_b_id == atom_b_id)
                    & (AtomAssociationModel.association_type == assoc_type.value)
                )
                if existing:
                    existing.evidence_count += 1
                    existing.weight = existing.weight + (1.0 - existing.weight) * _WEIGHT_GROWTH_RATE
                    existing.save()
                else:
                    AtomAssociationModel.create(
                        atom_a_id=atom_a_id,
                        atom_b_id=atom_b_id,
                        association_type=assoc_type.value,
                        weight=min(1.0, weight),
                        evidence_count=1,
                    )
        except Exception as e:
            logger.error("添加关联失败: %s <-> %s: %s", atom_a_id, atom_b_id, e)

    def get_associations(self, atom_id: str) -> list[dict[str, Any]]:
        """返回指定原子的所有关联（双向）。"""
        try:
            with self.db:
                query = AtomAssociationModel.select().where(
                    (AtomAssociationModel.atom_a_id == atom_id) | (AtomAssociationModel.atom_b_id == atom_id)
                )
                return [self._model_to_dict(a) for a in query]
        except Exception as e:
            logger.error("获取关联失败 (atom_id=%s): %s", atom_id, e)
            return []

    def delete_association(
        self,
        atom_a_id: str,
        atom_b_id: str,
        assoc_type: AssociationType,
    ) -> bool:
        """删除指定的关联。"""
        if atom_a_id > atom_b_id:
            atom_a_id, atom_b_id = atom_b_id, atom_a_id
        try:
            with self.db:
                rows = (
                    AtomAssociationModel.delete()
                    .where(
                        AtomAssociationModel.atom_a_id == atom_a_id,
                        AtomAssociationModel.atom_b_id == atom_b_id,
                        AtomAssociationModel.association_type == assoc_type.value,
                    )
                    .execute()
                )
            return rows > 0
        except Exception as e:
            logger.error("删除关联失败: %s", e)
            return False

    # ------------------------------------------------------------------
    # 链遍历（BFS）
    # ------------------------------------------------------------------

    def get_chain(
        self,
        atom_id: str,
        max_depth: int = 2,
    ) -> list[dict[str, Any]]:
        """沿关联进行 BFS 遍历，返回排序后的相关原子。

        返回：
            list[dict] — 每个字典包含键：atom_id、association_type、weight、depth
        """
        try:
            visited: set[str] = {atom_id}
            results: list[dict[str, Any]] = []
            queue: list[tuple[str, int]] = [(atom_id, 0)]

            while queue:
                current_id, depth = queue.pop(0)

                if depth >= max_depth:
                    continue

                with self.db:
                    edges = AtomAssociationModel.select().where(
                        (AtomAssociationModel.atom_a_id == current_id) | (AtomAssociationModel.atom_b_id == current_id)
                    )

                    for edge in edges:
                        neighbor = edge.atom_b_id if edge.atom_a_id == current_id else edge.atom_a_id
                        if neighbor not in visited:
                            visited.add(neighbor)
                            results.append(
                                {
                                    "atom_id": neighbor,
                                    "association_type": edge.association_type,
                                    "weight": edge.weight,
                                    "depth": depth + 1,
                                }
                            )
                            queue.append((neighbor, depth + 1))

            return results
        except Exception as e:
            logger.error("关联链查询失败 (atom_id=%s): %s", atom_id, e)
            return []

    # ------------------------------------------------------------------
    # 基于规则的批量构建
    # ------------------------------------------------------------------

    def build_from_batch(
        self,
        atoms: list[Any],
        stream_map: Optional[dict[str, str]] = None,
    ) -> int:
        """基于规则的关联构建器，用于新写入的原子。

        应用的规则（对每个无序对按顺序检查）：
        1. CO_OCCURRENCE — 共享 >= 2 个实体的原子：
           权重 = entity_jaccard * 0.7
        2. CAUSAL — 实体包含关系（一个原子的所有实体都出现在
           另一个中，且集合不同）：
           权重 = 0.6
        3. SEQUENTIAL — 60 秒内同一 stream_id：
           权重 = 1.0 - (time_gap / 60)

        参数：
            atoms: MemoryAtom 数据类对象列表（或任何具有 .atom_id、
                   .entities、.created_at 属性的鸭子类型对象）
            stream_map: 可选的 dict，将 atom_id 映射到 stream_id，
                        用于顺序检测

        返回：
            创建的关联数量
        """
        count = 0
        n = len(atoms)

        for i in range(n):
            for j in range(i + 1, n):
                a, b = atoms[i], atoms[j]

                set_a = set(a.entities) if a.entities else set()
                set_b = set(b.entities) if b.entities else set()

                # -- 共现（CO_OCCURRENCE）--
                if len(set_a) >= 2 and len(set_b) >= 2:
                    common = set_a & set_b
                    if len(common) >= 2:
                        union = set_a | set_b
                        jaccard = len(common) / len(union) if union else 0
                        self.add_association(
                            a.atom_id,
                            b.atom_id,
                            AssociationType.CO_OCCURRENCE,
                            jaccard * 0.7,
                        )
                        count += 1

                # -- 因果（CAUSAL）：实体包含 --
                if set_a and set_b and set_a != set_b:
                    if set_a.issubset(set_b):
                        self.add_association(
                            a.atom_id,
                            b.atom_id,
                            AssociationType.CAUSAL,
                            0.6,
                        )
                        count += 1
                    elif set_b.issubset(set_a):
                        self.add_association(
                            b.atom_id,
                            a.atom_id,
                            AssociationType.CAUSAL,
                            0.6,
                        )
                        count += 1

                # -- 顺序（SEQUENTIAL）：60s 内同一流 --
                if stream_map:
                    a_stream = stream_map.get(a.atom_id)
                    b_stream = stream_map.get(b.atom_id)
                    if a_stream and b_stream and a_stream == b_stream:
                        a_ts = self._resolve_ts(a.created_at)
                        b_ts = self._resolve_ts(b.created_at)
                        if a_ts is not None and b_ts is not None:
                            time_gap = abs(a_ts - b_ts)
                            if time_gap <= 60:
                                weight = 1.0 - (time_gap / 60.0)
                                self.add_association(
                                    a.atom_id,
                                    b.atom_id,
                                    AssociationType.SEQUENTIAL,
                                    weight,
                                )
                                count += 1

        if count > 0:
            logger.info("批量关联构建完成: 新增 %d 条关联 (atoms=%d)", count, n)

        return count

    # ------------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------------

    def prune_weak(self, threshold: float = 0.1) -> int:
        """移除权重低于阈值的所有关联。

        参数：
            threshold：保留的最低权重（默认 0.1）。

        返回：
            删除的行数。
        """
        try:
            with self.db:
                rows = AtomAssociationModel.delete().where(AtomAssociationModel.weight < threshold).execute()
            if rows > 0:
                logger.info("清理弱关联: 移除 %d 条 (阈值=%.2f)", rows, threshold)
            return rows
        except Exception as e:
            logger.error("清理弱关联失败: %s", e)
            return 0

    def count(self) -> int:
        """返回存储中的关联总数。"""
        try:
            with self.db:
                return AtomAssociationModel.select().count()
        except Exception as e:
            logger.error("统计关联数失败: %s", e)
            return 0

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _model_to_dict(model: AtomAssociationModel) -> dict[str, Any]:
        return {
            "id": model.id,
            "atom_a_id": model.atom_a_id,
            "atom_b_id": model.atom_b_id,
            "association_type": model.association_type,
            "weight": model.weight,
            "evidence_count": model.evidence_count,
            "created_at": model.created_at.isoformat() if model.created_at else None,
        }

    @staticmethod
    def _resolve_ts(ts: Any) -> Optional[float]:
        """将时间戳归一化为 float（自 epoch 以来的秒数）。

        接受 float、int 或 datetime 类型。
        """
        if ts is None:
            return None
        if isinstance(ts, (int, float)):
            return float(ts)
        if isinstance(ts, datetime.datetime):
            return ts.timestamp()
        return None
