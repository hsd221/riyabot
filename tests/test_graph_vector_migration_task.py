import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.memory.schema import GraphEntry, configure_memory_database, initialize_database, memory_db
from src.memory.vector_migration import GraphVectorIndexMigrationTask


class FakeGraphMigrationQdrant:
    def __init__(self) -> None:
        self.graph_migration_pending = True
        self.graph_migration_target = "graph_entries__target"
        self.points: dict[str, tuple[list[float], dict[str, object]]] = {}
        self.state = SimpleNamespace(last_processed_id=None, migrated_count=0, total_count=0, status="migrating")
        self.activated = False
        self.failures: list[str] = []

    def get_graph_migration_state(self):
        return self.state

    async def upsert_graph_vector_to_collection(
        self,
        collection_name: str,
        point_id: str,
        vector: list[float],
        payload: dict[str, object],
    ) -> bool:
        self.points[str(point_id)] = (list(vector), dict(payload))
        return collection_name == self.graph_migration_target

    async def delete_graph_vector_from_collection(self, collection_name: str, point_id: str) -> bool:
        self.points.pop(str(point_id), None)
        return collection_name == self.graph_migration_target

    async def list_graph_points(self, page_size: int = 256, collection_name: str | None = None):
        del page_size
        if collection_name != self.graph_migration_target:
            return None
        return [
            {
                "physical_id": entry_id,
                "business_id": entry_id,
                "embedding_source_hash": payload.get("embedding_source_hash"),
                "embedding_signature": payload.get("embedding_signature"),
                "embedding_dimension": payload.get("embedding_dimension"),
            }
            for entry_id, (_vector, payload) in sorted(self.points.items())
        ]

    async def mark_graph_migration_progress(self, **updates) -> None:
        for key, value in updates.items():
            setattr(self.state, key, value)
        self.state.status = "migrating"

    async def mark_graph_migration_failure(self, error: str) -> None:
        self.failures.append(error)
        self.state.status = "failed"

    async def activate_graph_migration(self) -> bool:
        self.activated = True
        self.graph_migration_pending = False
        return True


class GraphVectorIndexMigrationTaskTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.original_path = memory_db.database
        self.addCleanup(lambda: configure_memory_database(str(self.original_path)))
        configure_memory_database(str(Path(self.temp_dir.name) / "memory.db"))
        initialize_database()

    async def test_rebuilds_graph_entries_and_activates_only_after_validation(self) -> None:
        entry = GraphEntry.create(
            subject="璃夜",
            predicate="喜欢",
            object="爵士乐",
            evidence="她在聊天中主动提到爵士乐",
            confidence=0.9,
        )
        qdrant = FakeGraphMigrationQdrant()
        store = SimpleNamespace(
            config=SimpleNamespace(
                embedding_dimension=2,
                embedding_signature="profile-signature",
                vector_batch_size=1,
            ),
            qdrant=qdrant,
        )
        embedding_result = SimpleNamespace(
            vector=[0.25, 0.75],
            profile=SimpleNamespace(signature="profile-signature"),
        )
        task = GraphVectorIndexMigrationTask(store, batch_size=1, interval=1)

        with patch(
            "src.memory.vector_migration.embed_text",
            new=AsyncMock(return_value=embedding_result),
        ):
            self.assertEqual(await task.run(), 1)
            self.assertFalse(qdrant.activated)
            self.assertEqual(await task.run(), 0)

        entry_id = str(entry.id)
        self.assertTrue(qdrant.activated)
        self.assertEqual(task.run_interval, 0)
        self.assertEqual(qdrant.points[entry_id][0], [0.25, 0.75])
        payload = qdrant.points[entry_id][1]
        self.assertEqual(payload["entry_id"], entry_id)
        self.assertEqual(payload["embedding_signature"], "profile-signature")
        self.assertEqual(payload["embedding_dimension"], 2)
        self.assertTrue(payload["embedding_source_hash"])


if __name__ == "__main__":
    unittest.main()
