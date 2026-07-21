import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.memory.schema import (
    GraphEntry,
    MemoryAtom,
    VectorIndexState,
    configure_memory_database,
    initialize_database,
    memory_db,
)
from src.memory.store import QDRANT_AVAILABLE, MemoryStoreConfig, QdrantManager
from src.memory.vector_migration import GraphVectorIndexMigrationTask, VectorIndexMigrationTask

if QDRANT_AVAILABLE:
    from qdrant_client import QdrantClient, models


@unittest.skipUnless(QDRANT_AVAILABLE, "qdrant-client is not installed")
class VectorMigrationIntegrationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.original_path = memory_db.database
        self.addCleanup(lambda: configure_memory_database(str(self.original_path)))
        configure_memory_database(str(Path(self.temp_dir.name) / "memory.db"))
        initialize_database()

    async def test_rebuilds_legacy_collection_switches_alias_and_keeps_old_collection(self) -> None:
        qdrant_path = str(Path(self.temp_dir.name) / "qdrant")
        legacy_client = QdrantClient(path=qdrant_path)
        for collection_name in ("memory_atoms", "graph_entries"):
            legacy_client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE),
            )
        legacy_client.upsert(
            collection_name="memory_atoms",
            points=[
                models.PointStruct(
                    id=QdrantManager._normalize_point_id("atom-a"),
                    vector=[1.0, 0.0],
                    payload={"atom_id": "atom-a"},
                )
            ],
        )
        legacy_client.close()

        MemoryAtom.create(atom_id="atom-a", atom_type="factual", content="new content", status="active")
        config = MemoryStoreConfig(
            embedding_dimension=2,
            embedding_signature="new-profile",
            embedding_model_name="embedding-primary",
            qdrant_local_path=qdrant_path,
            vector_batch_size=1,
        )
        manager = QdrantManager(config)
        await manager.initialize()
        self.addAsyncCleanup(manager.close)

        self.assertTrue(manager.atom_migration_pending)
        target = manager.atom_migration_target
        self.assertIsNotNone(target)
        store = SimpleNamespace(config=config, qdrant=manager)
        embedding_result = SimpleNamespace(
            vector=[0.0, 1.0],
            profile=SimpleNamespace(signature="new-profile"),
        )
        task = VectorIndexMigrationTask(store, batch_size=1, interval=1)

        with patch("src.memory.vector_migration.embed_text", new=AsyncMock(return_value=embedding_result)):
            for _ in range(4):
                await task.run()
                if not manager.atom_migration_pending:
                    break

        self.assertFalse(manager.atom_migration_pending)
        self.assertTrue(manager.vector_search_enabled)
        self.assertEqual(manager._get_aliases()["memory_atoms__active"], target)
        self.assertIn("memory_atoms", manager._get_collection_names())
        self.assertIn(target, manager._get_collection_names())

        target_points = await manager.list_atom_points(collection_name=target)
        self.assertIsNotNone(target_points)
        self.assertEqual([point["business_id"] for point in target_points], ["atom-a"])
        self.assertEqual(target_points[0]["embedding_signature"], "new-profile")
        self.assertTrue(target_points[0]["embedding_source_hash"])

        state = VectorIndexState.get_by_id("memory_atoms")
        self.assertEqual(state.status, "ready")
        self.assertEqual(state.active_collection, target)

    async def test_rebuilds_legacy_graph_collection_switches_alias_and_keeps_old_collection(self) -> None:
        entry = GraphEntry.create(
            subject="璃夜",
            predicate="喜欢",
            object="爵士乐",
            evidence="聊天中主动提到",
            confidence=0.9,
        )
        qdrant_path = str(Path(self.temp_dir.name) / "qdrant")
        legacy_client = QdrantClient(path=qdrant_path)
        for collection_name in ("memory_atoms", "graph_entries"):
            legacy_client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE),
            )
        legacy_client.upsert(
            collection_name="graph_entries",
            points=[
                models.PointStruct(
                    id=entry.id,
                    vector=[1.0, 0.0],
                    payload={"entry_id": str(entry.id)},
                )
            ],
        )
        legacy_client.close()

        config = MemoryStoreConfig(
            embedding_dimension=2,
            embedding_signature="new-profile",
            embedding_model_name="embedding-primary",
            qdrant_local_path=qdrant_path,
            vector_batch_size=1,
        )
        manager = QdrantManager(config)
        await manager.initialize()
        self.addAsyncCleanup(manager.close)

        self.assertTrue(manager.graph_migration_pending)
        self.assertFalse(manager.graph_search_enabled)
        target = manager.graph_migration_target
        self.assertIsNotNone(target)
        store = SimpleNamespace(config=config, qdrant=manager)
        embedding_result = SimpleNamespace(
            vector=[0.0, 1.0],
            profile=SimpleNamespace(signature="new-profile"),
        )
        task = GraphVectorIndexMigrationTask(store, batch_size=1, interval=1)

        with patch("src.memory.vector_migration.embed_text", new=AsyncMock(return_value=embedding_result)):
            for _ in range(4):
                await task.run()
                if not manager.graph_migration_pending:
                    break

        self.assertFalse(manager.graph_migration_pending)
        self.assertTrue(manager.graph_search_enabled)
        self.assertEqual(manager._get_aliases()["graph_entries__active"], target)
        self.assertIn("graph_entries", manager._get_collection_names())
        self.assertIn(target, manager._get_collection_names())

        target_points = await manager.list_graph_points(collection_name=target)
        self.assertIsNotNone(target_points)
        self.assertEqual([point["business_id"] for point in target_points], [str(entry.id)])
        self.assertEqual(target_points[0]["embedding_signature"], "new-profile")
        self.assertTrue(target_points[0]["embedding_source_hash"])

        state = VectorIndexState.get_by_id("graph_entries")
        self.assertEqual(state.status, "ready")
        self.assertEqual(state.active_collection, target)


if __name__ == "__main__":
    unittest.main()
