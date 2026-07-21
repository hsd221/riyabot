import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.memory.schema import MemoryAtom, configure_memory_database, initialize_database, memory_db
from src.memory.vector_migration import VectorIndexMigrationTask


def create_atom(atom_id: str, content: str, status: str = "active") -> None:
    MemoryAtom.create(
        atom_id=atom_id,
        atom_type="factual",
        content=content,
        status=status,
    )


class FakeMigrationQdrant:
    def __init__(self) -> None:
        self.atom_migration_pending = True
        self.atom_migration_target = "memory_atoms__target"
        self.points: dict[str, tuple[list[float], dict[str, object]]] = {}
        self.state = SimpleNamespace(last_processed_id=None, migrated_count=0, total_count=0, status="migrating")
        self.progress_updates: list[dict[str, object]] = []
        self.failures: list[str] = []
        self.activated = False

    def get_atom_migration_state(self):
        return self.state

    async def upsert_atom_vector_to_collection(
        self,
        collection_name: str,
        point_id: str,
        vector: list[float],
        payload: dict[str, object],
    ) -> bool:
        self.points[point_id] = (list(vector), dict(payload))
        return collection_name == self.atom_migration_target

    async def delete_atom_vector_from_collection(self, collection_name: str, point_id: str) -> bool:
        self.points.pop(str(point_id), None)
        return collection_name == self.atom_migration_target

    async def list_atom_points(self, page_size: int = 256, collection_name: str | None = None):
        del page_size
        if collection_name != self.atom_migration_target:
            return None
        return [
            {
                "physical_id": atom_id,
                "business_id": atom_id,
                "embedding_source_hash": payload.get("embedding_source_hash"),
                "embedding_signature": payload.get("embedding_signature"),
                "embedding_dimension": payload.get("embedding_dimension"),
            }
            for atom_id, (_vector, payload) in sorted(self.points.items())
        ]

    async def mark_atom_migration_progress(self, **updates) -> None:
        self.progress_updates.append(dict(updates))
        for key, value in updates.items():
            setattr(self.state, key, value)
        self.state.status = "migrating"

    async def mark_atom_migration_failure(self, error: str) -> None:
        self.failures.append(error)
        self.state.status = "failed"

    async def activate_atom_migration(self) -> bool:
        self.activated = True
        self.atom_migration_pending = False
        return True


class VectorIndexMigrationTaskTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.original_path = memory_db.database
        self.addCleanup(lambda: configure_memory_database(str(self.original_path)))
        configure_memory_database(str(Path(self.temp_dir.name) / "memory.db"))
        initialize_database()
        self.qdrant = FakeMigrationQdrant()
        self.store = SimpleNamespace(
            config=SimpleNamespace(
                embedding_dimension=2,
                embedding_signature="profile-signature",
                vector_batch_size=1,
            ),
            qdrant=self.qdrant,
        )

    @staticmethod
    def embedding_result(vector: list[float]):
        return SimpleNamespace(
            vector=vector,
            profile=SimpleNamespace(signature="profile-signature"),
        )

    async def test_batches_resume_by_atom_id_and_activate_only_after_exact_reconciliation(self) -> None:
        create_atom("atom-a", "alpha")
        create_atom("atom-b", "beta")
        create_atom("atom-z", "archived", status="archived")
        task = VectorIndexMigrationTask(self.store, batch_size=1, interval=1)

        with patch(
            "src.memory.vector_migration.embed_text",
            new=AsyncMock(side_effect=[self.embedding_result([1.0, 0.0]), self.embedding_result([0.0, 1.0])]),
        ):
            self.assertEqual(await task.run(), 1)
            self.assertFalse(self.qdrant.activated)
            self.assertEqual(self.qdrant.state.last_processed_id, "atom-a")

            self.assertEqual(await task.run(), 1)
            self.assertFalse(self.qdrant.activated)
            self.assertEqual(self.qdrant.state.last_processed_id, "atom-b")

            self.assertEqual(await task.run(), 0)

        self.assertTrue(self.qdrant.activated)
        self.assertEqual(set(self.qdrant.points), {"atom-a", "atom-b"})
        self.assertEqual(task.run_interval, 0)

    async def test_content_change_during_embedding_is_reembedded_before_target_write(self) -> None:
        create_atom("atom-a", "old content")
        task = VectorIndexMigrationTask(self.store, batch_size=1, interval=1)

        async def embed_with_update(text: str, **kwargs):
            del kwargs
            if text == "old content":
                MemoryAtom.update(content="new content").where(MemoryAtom.atom_id == "atom-a").execute()
                return self.embedding_result([1.0, 0.0])
            return self.embedding_result([0.0, 1.0])

        with patch("src.memory.vector_migration.embed_text", new=embed_with_update):
            self.assertEqual(await task.run(), 1)

        self.assertEqual(self.qdrant.points["atom-a"][0], [0.0, 1.0])

    async def test_content_change_after_cursor_passes_is_repaired_before_activation(self) -> None:
        create_atom("atom-a", "old content")
        task = VectorIndexMigrationTask(self.store, batch_size=1, interval=1)

        with patch(
            "src.memory.vector_migration.embed_text",
            new=AsyncMock(
                side_effect=[
                    self.embedding_result([1.0, 0.0]),
                    self.embedding_result([0.0, 1.0]),
                ]
            ),
        ):
            self.assertEqual(await task.run(), 1)
            MemoryAtom.update(content="new content").where(MemoryAtom.atom_id == "atom-a").execute()

            self.assertEqual(await task.run(), 1)
            self.assertFalse(self.qdrant.activated)
            self.assertEqual(self.qdrant.points["atom-a"][0], [0.0, 1.0])

            self.assertEqual(await task.run(), 0)

        self.assertTrue(self.qdrant.activated)

    async def test_embedding_failure_keeps_old_alias_and_records_error(self) -> None:
        create_atom("atom-a", "alpha")
        task = VectorIndexMigrationTask(self.store, batch_size=1, interval=1)

        with patch(
            "src.memory.vector_migration.embed_text",
            new=AsyncMock(side_effect=RuntimeError("provider unavailable")),
        ):
            self.assertEqual(await task.run(), 0)

        self.assertFalse(self.qdrant.activated)
        self.assertTrue(self.qdrant.atom_migration_pending)
        self.assertEqual(self.qdrant.state.status, "failed")
        self.assertIn("provider unavailable", self.qdrant.failures[0])


if __name__ == "__main__":
    unittest.main()
