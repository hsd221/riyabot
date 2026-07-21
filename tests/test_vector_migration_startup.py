import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.memory.vector_migration import GraphVectorIndexMigrationTask, VectorIndexMigrationTask
from src.services.embedding_profile_monitor import register_pending_vector_migrations


class VectorMigrationStartupTest(unittest.IsolatedAsyncioTestCase):
    async def test_registers_all_pending_vector_index_migrations(self) -> None:
        store = SimpleNamespace(
            config=SimpleNamespace(vector_batch_size=16),
            qdrant=SimpleNamespace(
                atom_migration_pending=True,
                atom_migration_target="memory_atoms__target",
                graph_migration_pending=True,
                graph_migration_target="graph_entries__target",
            ),
        )
        embedding_profile = SimpleNamespace(model_name="embedding-v2", dimension=1536)
        task_manager = SimpleNamespace(tasks={}, add_task=AsyncMock())

        await register_pending_vector_migrations(store, embedding_profile, task_manager=task_manager)

        registered_tasks = [call.args[0] for call in task_manager.add_task.await_args_list]
        self.assertEqual(len(registered_tasks), 2)
        self.assertIsInstance(registered_tasks[0], VectorIndexMigrationTask)
        self.assertIsInstance(registered_tasks[1], GraphVectorIndexMigrationTask)

    async def test_registration_failure_for_one_index_does_not_block_the_other(self) -> None:
        store = SimpleNamespace(
            config=SimpleNamespace(vector_batch_size=16),
            qdrant=SimpleNamespace(
                atom_migration_pending=True,
                atom_migration_target="memory_atoms__target",
                graph_migration_pending=True,
                graph_migration_target="graph_entries__target",
            ),
        )
        embedding_profile = SimpleNamespace(model_name="embedding-v2", dimension=1536)
        task_manager = SimpleNamespace(
            tasks={},
            add_task=AsyncMock(side_effect=[RuntimeError("atom task failed"), None]),
        )

        await register_pending_vector_migrations(store, embedding_profile, task_manager=task_manager)

        self.assertEqual(task_manager.add_task.await_count, 2)
        self.assertIsInstance(task_manager.add_task.await_args_list[0].args[0], VectorIndexMigrationTask)
        self.assertIsInstance(task_manager.add_task.await_args_list[1].args[0], GraphVectorIndexMigrationTask)


if __name__ == "__main__":
    unittest.main()
