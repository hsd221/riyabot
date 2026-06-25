"""
Atom-to-atom association network — explicit association edges between memory atoms.

Creates and manages direct edges between memory atoms for:
- CO_OCCURRENCE: atoms sharing >= 2 entities in temporal proximity
- CAUSAL: atom where atom_a entities are contained in atom_b entities
- SEQUENTIAL: atoms from same stream_id within 60 seconds
- DREAM_DISCOVERED: discovered by the Dream Weaver agent
"""

import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from src.common.logger import get_logger
from src.memory.schema import AtomAssociationModel, memory_db

logger = get_logger("memory.association")


class AssociationType(str, Enum):
    """Types of atom-to-atom associations."""

    CO_OCCURRENCE = "co_occurrence"
    CAUSAL = "causal"
    SEQUENTIAL = "sequential"
    DREAM_DISCOVERED = "dream_discovered"


@dataclass
class AtomAssociation:
    """Association between two memory atoms.

    Attributes:
        atom_a_id: First atom ID (lexicographically smaller)
        atom_b_id: Second atom ID (lexicographically larger)
        association_type: Type of association
        weight: Association strength 0-1
        evidence_count: How many times this association has been reinforced
        created_at: When the association was first created
    """

    atom_a_id: str
    atom_b_id: str
    association_type: AssociationType
    weight: float = 0.5
    evidence_count: int = 1
    created_at: Optional[datetime.datetime] = None


class AtomAssociationStore:
    """Store for atom-to-atom association edges.

    Provides CRUD, rules-based batch building, chain traversal (BFS),
    and weak-edge pruning. All operations use the shared memory.db.
    """

    def __init__(self) -> None:
        self.db = memory_db
        # Auto-create table (idempotent)
        with self.db:
            self.db.create_tables([AtomAssociationModel], safe=True)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_association(
        self,
        atom_a_id: str,
        atom_b_id: str,
        assoc_type: AssociationType,
        weight: float,
    ) -> None:
        """Upsert: create or increment evidence_count + boost weight.

        Atom IDs are normalized by lexicographic order so that
        (a, b) and (b, a) map to the same row.
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
                    existing.weight = existing.weight + (1.0 - existing.weight) * 0.1
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
        """Return all associations for a given atom (both directions)."""
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
        """Delete a specific association."""
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
    # Chain traversal (BFS)
    # ------------------------------------------------------------------

    def get_chain(
        self,
        atom_id: str,
        max_depth: int = 2,
    ) -> list[dict[str, Any]]:
        """BFS walk along associations, return ordered related atoms.

        Returns:
            list[dict] — each with keys: atom_id, association_type, weight, depth
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
    # Rules-based batch builder
    # ------------------------------------------------------------------

    def build_from_batch(
        self,
        atoms: list[Any],
        stream_map: Optional[dict[str, str]] = None,
    ) -> int:
        """Rules-based association builder for newly written atoms.

        Rules applied (in order for each unordered pair):
        1. CO_OCCURRENCE — atoms sharing >= 2 entities:
           weight = entity_jaccard * 0.7
        2. CAUSAL — entity containment (one atom's entities all
           appear in the other's, and sets differ):
           weight = 0.6
        3. SEQUENTIAL — same stream_id within 60 seconds:
           weight = 1.0 - (time_gap / 60)

        Args:
            atoms: list of MemoryAtom dataclass objects (or any duck-typed
                   objects with .atom_id, .entities, .created_at attrs).
            stream_map: optional dict mapping atom_id -> stream_id for
                        sequential detection.

        Returns:
            Number of associations created.
        """
        count = 0
        n = len(atoms)

        for i in range(n):
            for j in range(i + 1, n):
                a, b = atoms[i], atoms[j]

                set_a = set(a.entities) if a.entities else set()
                set_b = set(b.entities) if b.entities else set()

                # -- CO_OCCURRENCE --
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

                # -- CAUSAL: entity containment --
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

                # -- SEQUENTIAL: same stream within 60s --
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
    # Maintenance
    # ------------------------------------------------------------------

    def prune_weak(self, threshold: float = 0.1) -> int:
        """Remove all associations below a weight threshold.

        Args:
            threshold: minimum weight to keep (default 0.1).

        Returns:
            Number of deleted rows.
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
        """Return total number of associations in the store."""
        try:
            with self.db:
                return AtomAssociationModel.select().count()
        except Exception as e:
            logger.error("统计关联数失败: %s", e)
            return 0

    # ------------------------------------------------------------------
    # Internal helpers
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
        """Normalise a timestamp to float (seconds since epoch).

        Accepts float, int, or datetime.
        """
        if ts is None:
            return None
        if isinstance(ts, (int, float)):
            return float(ts)
        if isinstance(ts, datetime.datetime):
            return ts.timestamp()
        return None
