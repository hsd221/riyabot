import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from src.update_system.models import (
    BuildIdentity,
    InstallationMode,
    UpdateResult,
    UpdateChannel,
    UpdateStatus,
    UpdateTarget,
)
from src.update_system.runner import PendingUpdateStore
from src.webui import update_routes


CURRENT_SHA = "1" * 40
TARGET_SHA = "2" * 40


def make_status(*, can_apply: bool = True, mode: InstallationMode = InstallationMode.SOURCE) -> UpdateStatus:
    return UpdateStatus(
        channel=UpdateChannel.DEV,
        current=BuildIdentity(
            version="1.0.0",
            revision=CURRENT_SHA,
            ref="dev",
            installation_mode=mode,
            dirty=False,
        ),
        target=UpdateTarget(ref="dev", revision=TARGET_SHA, summary="new commit"),
        update_available=True,
        can_apply=can_apply,
        block_code=None if can_apply else "docker_managed",
        block_message=None if can_apply else "Docker deployment is managed externally",
        checked_at="2026-07-31T12:00:00+00:00",
    )


class UpdateRoutesTest(unittest.IsolatedAsyncioTestCase):
    async def test_result_reads_runner_state_without_remote_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PendingUpdateStore(Path(tmpdir))
            store.write_result(
                UpdateResult(
                    success=True,
                    code="updated",
                    message="updated",
                    completed_at="2026-07-31T12:00:00+00:00",
                    target_revision=TARGET_SHA,
                )
            )
            with patch.object(update_routes, "get_pending_update_store", return_value=store):
                response = await update_routes.get_update_result(_auth=True)

        self.assertIsNotNone(response.last_result)
        self.assertTrue(response.last_result.success)
        self.assertEqual(response.last_result.target_revision, TARGET_SHA)

    async def test_status_uses_persisted_channel_and_includes_runner_state(self) -> None:
        service = AsyncMock()
        service.check.return_value = make_status()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PendingUpdateStore(Path(tmpdir))
            store.write_result(
                UpdateResult(
                    success=False,
                    code="old_failure",
                    message="old failure",
                    completed_at="2026-07-31T11:00:00+00:00",
                )
            )
            with (
                patch.object(update_routes, "get_update_service", return_value=service),
                patch.object(update_routes, "read_bot_config_section", return_value={"channel": "dev"}),
                patch.object(update_routes, "get_pending_update_store", return_value=store),
            ):
                response = await update_routes.get_update_status(force=True, _auth=True)

        service.check.assert_awaited_once_with(UpdateChannel.DEV, force=True)
        self.assertEqual(response["channel"], "dev")
        self.assertEqual(response["target"]["revision"], TARGET_SHA)
        self.assertFalse(response["update_pending"])

    async def test_preference_change_only_persists_channel(self) -> None:
        with (
            patch.object(update_routes, "save_bot_config_section") as save,
            patch.object(update_routes, "spawn_background_task") as schedule,
        ):
            response = await update_routes.update_preferences(
                update_routes.UpdatePreferencesRequest(channel=UpdateChannel.DEV),
                _same_site=None,
                _auth=True,
            )

        save.assert_called_once_with("update", {"channel": "dev"})
        schedule.assert_not_called()
        self.assertEqual(response.channel, UpdateChannel.DEV)

    async def test_create_task_rechecks_target_and_writes_a_bound_plan(self) -> None:
        service = AsyncMock()
        service.check.return_value = make_status()
        scheduled = []

        def fake_schedule(coro, **_kwargs):
            scheduled.append(coro)
            coro.close()
            return object()

        with tempfile.TemporaryDirectory() as tmpdir:
            store = PendingUpdateStore(Path(tmpdir))
            with (
                patch.object(update_routes, "get_update_service", return_value=service),
                patch.object(update_routes, "read_bot_config_section", return_value={"channel": "dev"}),
                patch.object(update_routes, "get_pending_update_store", return_value=store),
                patch.object(update_routes, "spawn_background_task", side_effect=fake_schedule),
            ):
                response = await update_routes.create_update_task(
                    update_routes.CreateUpdateTaskRequest(expected_target_revision=TARGET_SHA),
                    _same_site=None,
                    _auth=True,
                )
                plan = store.read_pending()
                previous_result = store.read_result()

        service.check.assert_awaited_once_with(UpdateChannel.DEV, force=True)
        self.assertTrue(response.accepted)
        self.assertEqual(plan.current_revision, CURRENT_SHA)
        self.assertEqual(plan.target_revision, TARGET_SHA)
        self.assertEqual(plan.target_ref, "dev")
        self.assertIsNone(previous_result)
        self.assertEqual(len(scheduled), 1)

    async def test_create_task_rejects_a_stale_target_without_scheduling_exit(self) -> None:
        service = AsyncMock()
        service.check.return_value = make_status()
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.object(update_routes, "get_update_service", return_value=service),
                patch.object(update_routes, "read_bot_config_section", return_value={"channel": "dev"}),
                patch.object(
                    update_routes,
                    "get_pending_update_store",
                    return_value=PendingUpdateStore(Path(tmpdir)),
                ),
                patch.object(update_routes, "spawn_background_task") as schedule,
            ):
                with self.assertRaises(HTTPException) as caught:
                    await update_routes.create_update_task(
                        update_routes.CreateUpdateTaskRequest(expected_target_revision="3" * 40),
                        _same_site=None,
                        _auth=True,
                    )

        self.assertEqual(caught.exception.status_code, 409)
        schedule.assert_not_called()

    async def test_create_task_rejects_check_only_installations(self) -> None:
        service = AsyncMock()
        service.check.return_value = make_status(can_apply=False, mode=InstallationMode.DOCKER)
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.object(update_routes, "get_update_service", return_value=service),
                patch.object(update_routes, "read_bot_config_section", return_value={"channel": "dev"}),
                patch.object(
                    update_routes,
                    "get_pending_update_store",
                    return_value=PendingUpdateStore(Path(tmpdir)),
                ),
            ):
                with self.assertRaises(HTTPException) as caught:
                    await update_routes.create_update_task(
                        update_routes.CreateUpdateTaskRequest(expected_target_revision=TARGET_SHA),
                        _same_site=None,
                        _auth=True,
                    )

        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail, "Docker deployment is managed externally")
