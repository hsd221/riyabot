import tempfile
import unittest
from pathlib import Path

from src.memory.schema import VectorIndexState, configure_memory_database, initialize_database, memory_db


class VectorIndexStateTest(unittest.TestCase):
    def test_state_table_is_created_and_persists_migration_cursor(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        original_path = memory_db.database
        self.addCleanup(lambda: configure_memory_database(str(original_path)))
        configure_memory_database(str(Path(temp_dir.name) / "memory.db"))
        initialize_database()

        state = VectorIndexState.create(
            index_name="memory_atoms",
            active_signature="old",
            active_dimension=1024,
            active_collection="memory_atoms__v-old",
            status="migrating",
            target_signature="new",
            target_dimension=1536,
            target_collection="memory_atoms__v-new",
            last_processed_id="atom-1",
            migrated_count=1,
            total_count=2,
        )

        persisted = VectorIndexState.get_by_id("memory_atoms")
        self.assertEqual(persisted.target_dimension, 1536)
        self.assertEqual(persisted.last_processed_id, "atom-1")
        self.assertEqual(state.status, "migrating")


if __name__ == "__main__":
    unittest.main()
