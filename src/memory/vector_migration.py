"""Resumable background rebuilds for versioned Qdrant vector indexes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from src.common.logger import get_logger
from src.llm_models.embedding import embed_text, embedding_source_hash
from src.manager.async_task_manager import AsyncTask
from src.memory.schema import GraphEntry, MemoryAtom, memory_db
from src.memory.store import MemoryStore

logger = get_logger("memory.vector_migration")

_MAX_SOURCE_REFRESH_ATTEMPTS = 3


class _VersionedVectorIndexMigrationTask(AsyncTask, ABC):
    """Common rebuild, reconciliation, and activation flow for one vector index."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        task_name: str,
        index_label: str,
        request_type: str,
        batch_size: Optional[int],
        interval: int,
    ) -> None:
        super().__init__(task_name=task_name, run_interval=max(1, int(interval)))
        self._store = store
        self._index_label = index_label
        self._request_type = request_type
        configured_batch_size = batch_size or store.config.vector_batch_size
        self._batch_size = max(1, int(configured_batch_size))

    @abstractmethod
    def _migration_pending(self) -> bool: ...

    @abstractmethod
    def _migration_target(self) -> Optional[str]: ...

    @abstractmethod
    def _migration_state(self) -> Any: ...

    @abstractmethod
    async def _mark_progress(
        self,
        *,
        last_processed_id: Optional[str],
        migrated_count: int,
        total_count: int,
    ) -> None: ...

    @abstractmethod
    async def _mark_failure(self, error: str) -> None: ...

    @abstractmethod
    async def _activate(self) -> bool: ...

    @abstractmethod
    def _load_batch(self, cursor: Optional[str]) -> list[str]: ...

    @abstractmethod
    def _source_count(self) -> int: ...

    @abstractmethod
    def _source_hashes(self) -> dict[str, str]: ...

    @abstractmethod
    def _read_source(self, source_id: str) -> Optional[dict[str, Any]]: ...

    @abstractmethod
    def _embedding_text(self, source: dict[str, Any]) -> str: ...

    @abstractmethod
    def _business_payload(self, source: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    async def _upsert_target(
        self,
        target: str,
        source_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> bool: ...

    @abstractmethod
    async def _delete_target(self, target: str, source_id: str | int) -> bool: ...

    @abstractmethod
    async def _list_target_points(self, target: str) -> Optional[list[dict[str, Any]]]: ...

    async def run(self) -> int:
        """Process one resumable batch, or reconcile and activate at EOF."""
        if not self._migration_pending():
            self.run_interval = 0
            return 0

        try:
            return await self._run_once()
        except Exception as exc:
            logger.exception(
                "向量索引迁移批次失败，旧索引保持不变",
                event_code="memory.vector_migration.batch_failed",
                index_name=self._index_label,
                error=str(exc),
            )
            try:
                await self._mark_failure(str(exc))
            except Exception:
                logger.exception(
                    "向量索引迁移失败状态保存失败，将在下个批次重试",
                    event_code="memory.vector_migration.failure_state_save_failed",
                    index_name=self._index_label,
                )
            return 0

    async def _run_once(self) -> int:
        target = self._migration_target()
        if not target:
            return 0

        state = self._migration_state()
        if state is None:
            raise RuntimeError(f"{self._index_label} vector migration state is unavailable")

        batch = self._load_batch(getattr(state, "last_processed_id", None))
        total_count = self._source_count()
        if batch:
            migrated = 0
            for source_id in batch:
                if await self._migrate_source(target, source_id):
                    migrated += 1

            await self._mark_progress(
                last_processed_id=batch[-1],
                migrated_count=int(getattr(state, "migrated_count", 0) or 0) + len(batch),
                total_count=total_count,
            )
            logger.info(
                "向量索引迁移批次完成",
                event_code="memory.vector_migration.batch_completed",
                index_name=self._index_label,
                batch_count=len(batch),
                migrated_count=migrated,
                last_processed_id=batch[-1],
                total_count=total_count,
            )
            return migrated

        return await self._reconcile_and_activate(target)

    def _migration_payload(self, source: dict[str, Any]) -> dict[str, Any]:
        embedding_text = self._embedding_text(source)
        payload = self._business_payload(source)
        payload.update(
            embedding_signature=str(self._store.config.embedding_signature or ""),
            embedding_dimension=int(self._store.config.embedding_dimension),
            embedding_source_hash=embedding_source_hash(embedding_text),
        )
        return payload

    def _point_matches_current_source(self, point: dict[str, Any], source_hash: str) -> bool:
        try:
            point_dimension = int(point.get("embedding_dimension"))
        except (TypeError, ValueError):
            return False
        return (
            str(point.get("embedding_signature") or "") == str(self._store.config.embedding_signature or "")
            and point_dimension == int(self._store.config.embedding_dimension)
            and str(point.get("embedding_source_hash") or "") == source_hash
        )

    def _source_signature(self, source: dict[str, Any]) -> tuple[str, tuple[tuple[str, Any], ...]]:
        return self._embedding_text(source), tuple(sorted(self._business_payload(source).items()))

    async def _migrate_source(self, target: str, source_id: str) -> bool:
        expected_dimension = int(self._store.config.embedding_dimension)
        expected_signature = str(self._store.config.embedding_signature or "")

        for _attempt in range(_MAX_SOURCE_REFRESH_ATTEMPTS):
            source = self._read_source(source_id)
            if source is None:
                await self._delete_target(target, source_id)
                return False

            embedding_text = self._embedding_text(source)
            if not embedding_text.strip():
                raise ValueError(f"{self._index_label} source {source_id} has empty embedding text")

            result = await embed_text(
                embedding_text,
                request_type=self._request_type,
                expected_dimension=expected_dimension,
            )
            if expected_signature and result.profile.signature != expected_signature:
                raise RuntimeError(
                    "embedding profile changed while migration was running "
                    f"({result.profile.signature} != {expected_signature})"
                )

            latest_source = self._read_source(source_id)
            if latest_source is None:
                await self._delete_target(target, source_id)
                return False
            if self._source_signature(latest_source) != self._source_signature(source):
                continue

            written = await self._upsert_target(
                target,
                source_id,
                result.vector,
                self._migration_payload(latest_source),
            )
            if not written:
                raise RuntimeError(f"failed to upsert migrated {self._index_label} source {source_id}")

            post_write_source = self._read_source(source_id)
            if post_write_source is None:
                await self._delete_target(target, source_id)
                return False
            if self._source_signature(post_write_source) == self._source_signature(latest_source):
                return True

        await self._delete_target(target, source_id)
        raise RuntimeError(f"{self._index_label} source {source_id} changed repeatedly during migration")

    async def _reconcile_and_activate(self, target: str) -> int:
        points = await self._list_target_points(target)
        if points is None:
            raise RuntimeError(f"{self._index_label} target collection points are unavailable")

        source_hashes = self._source_hashes()
        target_ids: set[str] = set()
        repair_ids: set[str] = set()
        for point in points:
            business_id = point.get("business_id")
            if not isinstance(business_id, str) or not business_id:
                if not await self._delete_target(target, point["physical_id"]):
                    raise RuntimeError(f"failed to remove an untrusted {self._index_label} target point")
                continue

            target_ids.add(business_id)
            source_hash = source_hashes.get(business_id)
            if source_hash is None:
                if not await self._delete_target(target, point["physical_id"]):
                    raise RuntimeError(f"failed to remove orphan {self._index_label} target point {business_id}")
                continue
            if not self._point_matches_current_source(point, source_hash):
                repair_ids.add(business_id)

        repair_ids.update(set(source_hashes) - target_ids)
        repaired = 0
        for source_id in sorted(repair_ids)[: self._batch_size]:
            if await self._migrate_source(target, source_id):
                repaired += 1
        if repaired:
            logger.info(
                "向量目标集合已补齐缺失来源",
                event_code="memory.vector_migration.target_repaired",
                index_name=self._index_label,
                repaired_count=repaired,
            )
            return repaired

        verified_points = await self._list_target_points(target)
        if verified_points is None:
            raise RuntimeError(f"{self._index_label} target collection verification is unavailable")
        latest_source_hashes = self._source_hashes()
        verified_target_ids: set[str] = set()
        invalid_points = 0
        for point in verified_points:
            business_id = point.get("business_id")
            if not isinstance(business_id, str) or not business_id:
                invalid_points += 1
                continue
            verified_target_ids.add(business_id)
            source_hash = latest_source_hashes.get(business_id)
            if source_hash is None or not self._point_matches_current_source(point, source_hash):
                invalid_points += 1

        latest_source_ids = set(latest_source_hashes)
        if invalid_points or verified_target_ids != latest_source_ids:
            logger.info(
                "向量目标集合仍在收敛，稍后继续校验",
                event_code="memory.vector_migration.target_not_converged",
                index_name=self._index_label,
                source_count=len(latest_source_ids),
                target_count=len(verified_target_ids),
                invalid_points=invalid_points,
            )
            return 0

        if not await self._activate():
            raise RuntimeError(f"failed to activate rebuilt {self._index_label} vector collection")
        self.run_interval = 0
        logger.info(
            "向量索引迁移完成",
            event_code="memory.vector_migration.completed",
            index_name=self._index_label,
            migrated_count=len(latest_source_ids),
            active_collection=target,
        )
        return 0


class VectorIndexMigrationTask(_VersionedVectorIndexMigrationTask):
    """Re-embed active SQLite memory atoms into a new Qdrant collection."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        batch_size: Optional[int] = None,
        interval: int = 15,
    ) -> None:
        super().__init__(
            store,
            task_name="记忆向量索引迁移",
            index_label="memory_atoms",
            request_type="memory.vector_migration",
            batch_size=batch_size,
            interval=interval,
        )

    def _migration_pending(self) -> bool:
        return bool(self._store.qdrant.atom_migration_pending)

    def _migration_target(self) -> Optional[str]:
        return self._store.qdrant.atom_migration_target

    def _migration_state(self) -> Any:
        return self._store.qdrant.get_atom_migration_state()

    async def _mark_progress(
        self,
        *,
        last_processed_id: Optional[str],
        migrated_count: int,
        total_count: int,
    ) -> None:
        await self._store.qdrant.mark_atom_migration_progress(
            last_processed_id=last_processed_id,
            migrated_count=migrated_count,
            total_count=total_count,
        )

    async def _mark_failure(self, error: str) -> None:
        await self._store.qdrant.mark_atom_migration_failure(error)

    async def _activate(self) -> bool:
        return await self._store.qdrant.activate_atom_migration()

    def _load_batch(self, cursor: Optional[str]) -> list[str]:
        with memory_db:
            query = MemoryAtom.select(MemoryAtom.atom_id).where(MemoryAtom.status == "active")
            if cursor:
                query = query.where(MemoryAtom.atom_id > cursor)
            query = query.order_by(MemoryAtom.atom_id.asc()).limit(self._batch_size)
            return [str(atom.atom_id) for atom in query]

    def _source_count(self) -> int:
        with memory_db:
            return MemoryAtom.select().where(MemoryAtom.status == "active").count()

    def _source_hashes(self) -> dict[str, str]:
        with memory_db:
            return {
                str(atom.atom_id): embedding_source_hash(str(atom.content or ""))
                for atom in MemoryAtom.select(MemoryAtom.atom_id, MemoryAtom.content).where(
                    MemoryAtom.status == "active"
                )
            }

    def _read_source(self, source_id: str) -> Optional[dict[str, Any]]:
        with memory_db:
            atom = MemoryAtom.get_or_none((MemoryAtom.atom_id == source_id) & (MemoryAtom.status == "active"))
            if atom is None:
                return None
            return {
                "atom_id": str(atom.atom_id),
                "atom_type": atom.atom_type,
                "content": atom.content,
                "weight": atom.weight,
                "importance": atom.importance,
                "confidence": atom.confidence,
                "status": atom.status,
                "source_scene": atom.source_scene,
                "source_id": atom.source_id,
                "privacy_level": atom.privacy_level,
            }

    def _embedding_text(self, source: dict[str, Any]) -> str:
        return str(source.get("content") or "")

    def _business_payload(self, source: dict[str, Any]) -> dict[str, Any]:
        return {
            "atom_id": source["atom_id"],
            "atom_type": source.get("atom_type", "factual"),
            "weight": source.get("weight", 0.5),
            "importance": source.get("importance", 0.5),
            "confidence": source.get("confidence", 0.5),
            "status": source.get("status", "active"),
            "source_scene": source.get("source_scene", "chat"),
            "source_id": source.get("source_id"),
            "privacy_level": source.get("privacy_level", "context_sensitive"),
        }

    async def _upsert_target(
        self,
        target: str,
        source_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> bool:
        return await self._store.qdrant.upsert_atom_vector_to_collection(
            collection_name=target,
            point_id=source_id,
            vector=vector,
            payload=payload,
        )

    async def _delete_target(self, target: str, source_id: str | int) -> bool:
        return await self._store.qdrant.delete_atom_vector_from_collection(target, source_id)

    async def _list_target_points(self, target: str) -> Optional[list[dict[str, Any]]]:
        return await self._store.qdrant.list_atom_points(collection_name=target)


def graph_entry_embedding_text(entry: dict[str, Any]) -> str:
    """Return the canonical text represented by one graph-entry vector."""
    parts = [
        f"主语：{str(entry.get('subject') or '').strip()}",
        f"关系：{str(entry.get('predicate') or '').strip()}",
        f"宾语：{str(entry.get('object') or '').strip()}",
    ]
    evidence = str(entry.get("evidence") or "").strip()
    if evidence:
        parts.append(f"证据：{evidence}")
    return "\n".join(parts)


class GraphVectorIndexMigrationTask(_VersionedVectorIndexMigrationTask):
    """Re-embed SQLite graph entries into a versioned Qdrant collection."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        batch_size: Optional[int] = None,
        interval: int = 15,
    ) -> None:
        super().__init__(
            store,
            task_name="图向量索引迁移",
            index_label="graph_entries",
            request_type="memory.graph.vector_migration",
            batch_size=batch_size,
            interval=interval,
        )

    def _migration_pending(self) -> bool:
        return bool(self._store.qdrant.graph_migration_pending)

    def _migration_target(self) -> Optional[str]:
        return self._store.qdrant.graph_migration_target

    def _migration_state(self) -> Any:
        return self._store.qdrant.get_graph_migration_state()

    async def _mark_progress(
        self,
        *,
        last_processed_id: Optional[str],
        migrated_count: int,
        total_count: int,
    ) -> None:
        await self._store.qdrant.mark_graph_migration_progress(
            last_processed_id=last_processed_id,
            migrated_count=migrated_count,
            total_count=total_count,
        )

    async def _mark_failure(self, error: str) -> None:
        await self._store.qdrant.mark_graph_migration_failure(error)

    async def _activate(self) -> bool:
        return await self._store.qdrant.activate_graph_migration()

    def _load_batch(self, cursor: Optional[str]) -> list[str]:
        with memory_db:
            query = GraphEntry.select(GraphEntry.id)
            if cursor:
                query = query.where(GraphEntry.id > int(cursor))
            query = query.order_by(GraphEntry.id.asc()).limit(self._batch_size)
            return [str(entry.id) for entry in query]

    def _source_count(self) -> int:
        with memory_db:
            return GraphEntry.select().count()

    def _source_hashes(self) -> dict[str, str]:
        with memory_db:
            entries = GraphEntry.select(
                GraphEntry.id,
                GraphEntry.subject,
                GraphEntry.predicate,
                GraphEntry.object,
                GraphEntry.evidence,
            )
            return {
                str(entry.id): embedding_source_hash(
                    graph_entry_embedding_text(
                        {
                            "subject": entry.subject,
                            "predicate": entry.predicate,
                            "object": entry.object,
                            "evidence": entry.evidence,
                        }
                    )
                )
                for entry in entries
            }

    def _read_source(self, source_id: str) -> Optional[dict[str, Any]]:
        try:
            entry_id = int(source_id)
        except (TypeError, ValueError):
            return None
        with memory_db:
            entry = GraphEntry.get_or_none(GraphEntry.id == entry_id)
            if entry is None:
                return None
            return {
                "entry_id": str(entry.id),
                "subject": entry.subject,
                "predicate": entry.predicate,
                "object": entry.object,
                "evidence": entry.evidence,
                "confidence": entry.confidence,
            }

    def _embedding_text(self, source: dict[str, Any]) -> str:
        return graph_entry_embedding_text(source)

    def _business_payload(self, source: dict[str, Any]) -> dict[str, Any]:
        return {
            "entry_id": source["entry_id"],
            "subject": source.get("subject", ""),
            "predicate": source.get("predicate", ""),
            "object": source.get("object", ""),
            "evidence": source.get("evidence"),
            "confidence": source.get("confidence", 0.5),
        }

    async def _upsert_target(
        self,
        target: str,
        source_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> bool:
        return await self._store.qdrant.upsert_graph_vector_to_collection(
            collection_name=target,
            point_id=source_id,
            vector=vector,
            payload=payload,
        )

    async def _delete_target(self, target: str, source_id: str | int) -> bool:
        return await self._store.qdrant.delete_graph_vector_from_collection(target, source_id)

    async def _list_target_points(self, target: str) -> Optional[list[dict[str, Any]]]:
        return await self._store.qdrant.list_graph_points(collection_name=target)
