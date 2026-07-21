import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.llm_models.embedding_profile import EmbeddingProfile, EmbeddingRuntime, reset_embedding_runtime
from src.memory.vector_migration import GraphVectorIndexMigrationTask, VectorIndexMigrationTask
from src.services import embedding_profile_monitor as monitor_module


def _profile(signature: str, dimension: int = 2) -> EmbeddingProfile:
    return EmbeddingProfile(
        signature=signature,
        model_name=f"model-{signature}",
        model_identifier=f"id-{signature}",
        provider_name="provider",
        dimension=dimension,
        model_names=(f"model-{signature}",),
    )


def _runtime(signature: str, dimension: int = 2) -> EmbeddingRuntime:
    return EmbeddingRuntime(
        model_config=SimpleNamespace(name=f"config-{signature}"),
        task_config=SimpleNamespace(model_list=[f"model-{signature}"]),
        profile=_profile(signature, dimension),
    )


class EmbeddingProfileMonitorTaskTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        reset_embedding_runtime()

    async def test_profile_change_switches_once_and_rebuilds_all_indexes(self) -> None:
        old_runtime = _runtime("old")
        new_runtime = _runtime("new", 3)
        qdrant = SimpleNamespace(
            atom_migration_pending=False,
            graph_migration_pending=False,
            reconfigure_embedding=AsyncMock(return_value=True),
        )
        store = SimpleNamespace(qdrant=qdrant, config=SimpleNamespace(vector_batch_size=16))
        task_manager = SimpleNamespace(tasks={}, add_task=AsyncMock())
        task = monitor_module.EmbeddingProfileMonitorTask(
            store,
            config_dir=Path("/unused"),
            task_manager=task_manager,
        )

        with (
            patch.object(monitor_module, "_config_fingerprint", return_value=((1, 1, 1, 1, 1),) * 2),
            patch.object(monitor_module, "_load_candidate_runtime", return_value=new_runtime),
            patch.object(
                monitor_module,
                "get_active_embedding_runtime",
                side_effect=[old_runtime, new_runtime, new_runtime],
            ),
            patch.object(monitor_module, "activate_embedding_runtime", return_value=new_runtime) as activate,
            patch.object(task, "_probe", new=AsyncMock()),
            patch.object(monitor_module, "register_pending_vector_migrations", new=AsyncMock()) as register,
            patch.object(
                monitor_module,
                "rebuild_json_vector_indexes",
                new=AsyncMock(return_value=True),
            ) as rebuild,
        ):
            await task.run()
            await task.run()

        qdrant.reconfigure_embedding.assert_awaited_once_with(new_runtime.profile)
        activate.assert_called_once_with(new_runtime.model_config, 3)
        self.assertEqual(register.await_count, 2)
        rebuild.assert_awaited_once_with(new_runtime.profile)

    async def test_probe_failure_keeps_the_old_runtime_and_retries_later(self) -> None:
        old_runtime = _runtime("old")
        new_runtime = _runtime("new")
        qdrant = SimpleNamespace(
            atom_migration_pending=False,
            graph_migration_pending=False,
            reconfigure_embedding=AsyncMock(return_value=True),
        )
        task = monitor_module.EmbeddingProfileMonitorTask(
            SimpleNamespace(qdrant=qdrant, config=SimpleNamespace(vector_batch_size=16)),
            config_dir=Path("/unused"),
            task_manager=SimpleNamespace(tasks={}, add_task=AsyncMock()),
        )

        with (
            patch.object(monitor_module, "_config_fingerprint", return_value=((2, 2, 2, 2, 2),) * 2),
            patch.object(monitor_module, "_load_candidate_runtime", return_value=new_runtime),
            patch.object(monitor_module, "get_active_embedding_runtime", return_value=old_runtime),
            patch.object(task, "_probe", new=AsyncMock(side_effect=RuntimeError("unavailable"))) as probe,
            patch.object(monitor_module, "activate_embedding_runtime") as activate,
            patch.object(monitor_module, "register_pending_vector_migrations", new=AsyncMock()) as register,
            patch.object(monitor_module, "json_vector_indexes_match_profile", return_value=True),
            patch.object(monitor_module, "rebuild_json_vector_indexes", new=AsyncMock()) as rebuild,
        ):
            await task.run()
            await task.run()

        qdrant.reconfigure_embedding.assert_not_awaited()
        self.assertEqual(probe.await_count, 2)
        activate.assert_not_called()
        self.assertEqual(register.await_count, 2)
        rebuild.assert_not_awaited()
        self.assertIsNone(task._last_processed_fingerprint)

    async def test_same_profile_config_is_probed_before_runtime_refresh(self) -> None:
        active_runtime = _runtime("same")
        candidate_runtime = _runtime("same")
        qdrant = SimpleNamespace(
            atom_migration_pending=False,
            graph_migration_pending=False,
            reconfigure_embedding=AsyncMock(return_value=True),
        )
        task = monitor_module.EmbeddingProfileMonitorTask(
            SimpleNamespace(qdrant=qdrant, config=SimpleNamespace(vector_batch_size=16)),
            config_dir=Path("/unused"),
            task_manager=SimpleNamespace(tasks={}, add_task=AsyncMock()),
        )

        with (
            patch.object(monitor_module, "_config_fingerprint", return_value=((5, 5, 5, 5, 5),) * 2),
            patch.object(monitor_module, "_load_candidate_runtime", return_value=candidate_runtime),
            patch.object(monitor_module, "get_active_embedding_runtime", return_value=active_runtime),
            patch.object(task, "_probe", new=AsyncMock(side_effect=RuntimeError("bad credentials"))),
            patch.object(monitor_module, "activate_embedding_runtime") as activate,
            patch.object(monitor_module, "register_pending_vector_migrations", new=AsyncMock()),
            patch.object(monitor_module, "json_vector_indexes_match_profile", return_value=True),
        ):
            await task.run()

        qdrant.reconfigure_embedding.assert_not_awaited()
        activate.assert_not_called()
        self.assertIsNone(task._last_processed_fingerprint)

    async def test_invalid_candidate_does_not_block_existing_startup_migration(self) -> None:
        active_runtime = _runtime("active")
        qdrant = SimpleNamespace(
            atom_migration_pending=True,
            graph_migration_pending=False,
            reconfigure_embedding=AsyncMock(return_value=True),
        )
        task = monitor_module.EmbeddingProfileMonitorTask(
            SimpleNamespace(qdrant=qdrant, config=SimpleNamespace(vector_batch_size=16)),
            config_dir=Path("/unused"),
            task_manager=SimpleNamespace(tasks={}, add_task=AsyncMock()),
        )

        with (
            patch.object(monitor_module, "_config_fingerprint", return_value=((3, 3, 3, 3, 3),) * 2),
            patch.object(monitor_module, "_load_candidate_runtime", side_effect=ValueError("invalid")),
            patch.object(monitor_module, "get_active_embedding_runtime", return_value=active_runtime),
            patch.object(
                monitor_module,
                "register_pending_vector_migrations",
                new=AsyncMock(),
            ) as register,
            patch.object(
                monitor_module,
                "rebuild_json_vector_indexes",
                new=AsyncMock(return_value=True),
            ) as rebuild,
        ):
            await task.run()

        register.assert_awaited_once()
        rebuild.assert_awaited_once_with(active_runtime.profile)
        qdrant.reconfigure_embedding.assert_not_awaited()

    async def test_first_run_rebuilds_stale_json_indexes_without_a_qdrant_migration(self) -> None:
        active_runtime = _runtime("active")
        qdrant = SimpleNamespace(
            atom_migration_pending=False,
            graph_migration_pending=False,
            reconfigure_embedding=AsyncMock(return_value=True),
        )
        task = monitor_module.EmbeddingProfileMonitorTask(
            SimpleNamespace(qdrant=qdrant, config=SimpleNamespace(vector_batch_size=16)),
            config_dir=Path("/unused"),
            task_manager=SimpleNamespace(tasks={}, add_task=AsyncMock()),
        )

        with (
            patch.object(monitor_module, "_config_fingerprint", return_value=((4, 4, 4, 4, 4),) * 2),
            patch.object(monitor_module, "_load_candidate_runtime", return_value=active_runtime),
            patch.object(monitor_module, "get_active_embedding_runtime", return_value=active_runtime),
            patch.object(monitor_module, "activate_embedding_runtime", return_value=active_runtime),
            patch.object(task, "_probe", new=AsyncMock()),
            patch.object(monitor_module, "register_pending_vector_migrations", new=AsyncMock()),
            patch.object(
                monitor_module,
                "json_vector_indexes_match_profile",
                return_value=False,
                create=True,
            ),
            patch.object(
                monitor_module,
                "rebuild_json_vector_indexes",
                new=AsyncMock(return_value=True),
            ) as rebuild,
        ):
            await task.run()

        rebuild.assert_awaited_once_with(active_runtime.profile)


class EmbeddingRebuildRegistrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_running_migration_tasks_are_not_replaced(self) -> None:
        store = SimpleNamespace(
            config=SimpleNamespace(vector_batch_size=16),
            qdrant=SimpleNamespace(atom_migration_pending=True, graph_migration_pending=True),
        )
        atom_task_name = VectorIndexMigrationTask(store).task_name
        graph_task_name = GraphVectorIndexMigrationTask(store).task_name
        task_manager = SimpleNamespace(
            tasks={atom_task_name: object(), graph_task_name: object()},
            add_task=AsyncMock(),
        )

        registered = await monitor_module.register_pending_vector_migrations(
            store,
            _profile("current"),
            task_manager=task_manager,
        )

        self.assertEqual(registered, 0)
        task_manager.add_task.assert_not_awaited()

    async def test_json_rebuild_covers_expression_emotion_and_scene_indexes(self) -> None:
        profile = _profile("current")
        with (
            patch.object(monitor_module, "_load_expression_candidates", return_value=[{"id": 1}]),
            patch.object(monitor_module, "_load_emoji_candidates", return_value=(["emoji"], ["scene"])),
            patch.object(
                monitor_module.expression_vector_index,
                "rebuild",
                new=AsyncMock(return_value=True),
            ) as expression_rebuild,
            patch.object(
                monitor_module.emoji_vector_index,
                "rebuild",
                new=AsyncMock(return_value=True),
            ) as emoji_rebuild,
            patch.object(
                monitor_module.emoji_usage_scene_vector_index,
                "rebuild",
                new=AsyncMock(return_value=True),
            ) as scene_rebuild,
            patch.object(monitor_module.expression_vector_index, "profile_matches", return_value=False),
            patch.object(monitor_module.emoji_vector_index, "profile_matches", return_value=False),
            patch.object(monitor_module.emoji_usage_scene_vector_index, "profile_matches", return_value=False),
        ):
            rebuilt = await monitor_module.rebuild_json_vector_indexes(profile)

        self.assertTrue(rebuilt)
        expression_rebuild.assert_awaited_once_with([{"id": 1}], expected_profile=profile)
        emoji_rebuild.assert_awaited_once_with(["emoji"], expected_profile=profile)
        scene_rebuild.assert_awaited_once_with(["scene"], expected_profile=profile)

    async def test_json_rebuild_skips_indexes_that_already_match_the_profile(self) -> None:
        profile = _profile("current")
        with (
            patch.object(monitor_module, "_load_expression_candidates", return_value=[{"id": 1}]),
            patch.object(monitor_module, "_load_emoji_candidates", return_value=(["emoji"], ["scene"])),
            patch.object(
                monitor_module.expression_vector_index,
                "rebuild",
                new=AsyncMock(return_value=True),
            ) as expression_rebuild,
            patch.object(
                monitor_module.emoji_vector_index,
                "rebuild",
                new=AsyncMock(return_value=True),
            ) as emoji_rebuild,
            patch.object(
                monitor_module.emoji_usage_scene_vector_index,
                "rebuild",
                new=AsyncMock(return_value=True),
            ) as scene_rebuild,
            patch.object(monitor_module.expression_vector_index, "profile_matches", return_value=True),
            patch.object(monitor_module.emoji_vector_index, "profile_matches", return_value=False),
            patch.object(monitor_module.emoji_usage_scene_vector_index, "profile_matches", return_value=True),
        ):
            rebuilt = await monitor_module.rebuild_json_vector_indexes(profile)

        self.assertTrue(rebuilt)
        expression_rebuild.assert_not_awaited()
        emoji_rebuild.assert_awaited_once_with(["emoji"], expected_profile=profile)
        scene_rebuild.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
