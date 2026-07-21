import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import src.main as main_module
from src.memory.vector_migration import GraphVectorIndexMigrationTask, VectorIndexMigrationTask


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

        with patch.object(main_module.async_task_manager, "add_task", new=AsyncMock()) as add_task:
            await main_module._register_vector_migration_tasks(store, embedding_profile)

        registered_tasks = [call.args[0] for call in add_task.await_args_list]
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

        with patch.object(
            main_module.async_task_manager,
            "add_task",
            new=AsyncMock(side_effect=[RuntimeError("atom task failed"), None]),
        ) as add_task:
            await main_module._register_vector_migration_tasks(store, embedding_profile)

        self.assertEqual(add_task.await_count, 2)
        self.assertIsInstance(add_task.await_args_list[0].args[0], VectorIndexMigrationTask)
        self.assertIsInstance(add_task.await_args_list[1].args[0], GraphVectorIndexMigrationTask)


if __name__ == "__main__":
    unittest.main()
