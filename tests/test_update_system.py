import json
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.update_system import service as update_service
from src.update_system.models import (
    BuildIdentity,
    InstallationMode,
    PendingUpdate,
    RemoteBranch,
    RemoteTag,
    UpdateChannel,
    select_latest_stable_tag,
)
from src.update_system.runner import PendingUpdateStore, apply_pending_update
from src.update_system.service import UpdateService


CURRENT_SHA = "1" * 40
TARGET_SHA = "2" * 40
MAIN_SHA = "3" * 40


class FakeRepositoryClient:
    def __init__(self) -> None:
        self.branches = {
            "main": RemoteBranch(name="main", revision=MAIN_SHA, summary="stable head"),
            "dev": RemoteBranch(name="dev", revision=TARGET_SHA, summary="new development change"),
        }
        self.tags = [
            RemoteTag(name="nightly", revision="4" * 40),
            RemoteTag(name="v1.3.0-beta.1", revision="5" * 40),
            RemoteTag(name="v1.2.0", revision=TARGET_SHA),
            RemoteTag(name="v1.10.0", revision="6" * 40),
        ]
        self.ancestors = {(TARGET_SHA, MAIN_SHA)}

    async def get_branch(self, name: str) -> RemoteBranch:
        return self.branches[name]

    async def list_tags(self) -> list[RemoteTag]:
        return self.tags

    async def is_ancestor(self, base_revision: str, head_revision: str) -> bool:
        return (base_revision, head_revision) in self.ancestors


class UpdateSelectionTest(unittest.TestCase):
    def test_latest_stable_tag_uses_semver_and_ignores_prereleases(self) -> None:
        selected = select_latest_stable_tag(
            [
                RemoteTag(name="v1.9.0", revision="1" * 40),
                RemoteTag(name="v1.10.0", revision="2" * 40),
                RemoteTag(name="v2.0.0-rc.1", revision="3" * 40),
                RemoteTag(name="latest", revision="4" * 40),
            ]
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected.name, "v1.10.0")

    def test_source_identity_treats_a_failed_status_check_as_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".git").mkdir()
            completed = [
                subprocess.CompletedProcess(["git"], 0, stdout=CURRENT_SHA + "\n", stderr=""),
                subprocess.CompletedProcess(["git"], 0, stdout="dev\n", stderr=""),
                subprocess.CompletedProcess(["git"], 128, stdout="", stderr="failed"),
            ]
            with (
                patch.object(update_service.shutil, "which", return_value="/usr/bin/git"),
                patch.object(update_service.subprocess, "run", side_effect=completed),
            ):
                identity = update_service.detect_build_identity(root)

        self.assertEqual(identity.installation_mode, InstallationMode.SOURCE)
        self.assertEqual(identity.revision, CURRENT_SHA)
        self.assertTrue(identity.dirty)


class UpdateServiceTest(unittest.IsolatedAsyncioTestCase):
    def make_identity(
        self,
        *,
        mode: InstallationMode = InstallationMode.SOURCE,
        dirty: bool = False,
        revision: str | None = CURRENT_SHA,
    ) -> BuildIdentity:
        return BuildIdentity(
            version="1.0.0",
            revision=revision,
            ref="dev",
            installation_mode=mode,
            dirty=dirty,
        )

    async def test_stable_channel_selects_latest_tag_reachable_from_main(self) -> None:
        client = FakeRepositoryClient()
        client.ancestors.add(("6" * 40, MAIN_SHA))
        service = UpdateService(
            repository_client=client,
            identity_provider=self.make_identity,
            fast_forward_checker=lambda _current, _target: True,
            tool_checker=lambda: None,
        )

        status = await service.check(UpdateChannel.STABLE, force=True)

        self.assertEqual(status.target.ref, "v1.10.0")
        self.assertEqual(status.target.revision, "6" * 40)
        self.assertTrue(status.update_available)
        self.assertTrue(status.can_apply)

    async def test_dev_channel_compares_the_full_branch_revision(self) -> None:
        service = UpdateService(
            repository_client=FakeRepositoryClient(),
            identity_provider=self.make_identity,
            fast_forward_checker=lambda current, target: (current, target) == (CURRENT_SHA, TARGET_SHA),
            tool_checker=lambda: None,
        )

        status = await service.check(UpdateChannel.DEV, force=True)

        self.assertEqual(status.target.revision, TARGET_SHA)
        self.assertEqual(status.target.summary, "new development change")
        self.assertTrue(status.update_available)
        self.assertTrue(status.can_apply)

    async def test_docker_install_reports_update_but_refuses_in_container_apply(self) -> None:
        service = UpdateService(
            repository_client=FakeRepositoryClient(),
            identity_provider=lambda: self.make_identity(mode=InstallationMode.DOCKER),
            fast_forward_checker=lambda _current, _target: True,
            tool_checker=lambda: None,
        )

        status = await service.check(UpdateChannel.DEV, force=True)

        self.assertTrue(status.update_available)
        self.assertFalse(status.can_apply)
        self.assertEqual(status.block_code, "docker_managed")

    async def test_dirty_or_diverged_source_checkout_is_blocked(self) -> None:
        dirty_service = UpdateService(
            repository_client=FakeRepositoryClient(),
            identity_provider=lambda: self.make_identity(dirty=True),
            fast_forward_checker=lambda _current, _target: True,
            tool_checker=lambda: None,
        )
        diverged_service = UpdateService(
            repository_client=FakeRepositoryClient(),
            identity_provider=self.make_identity,
            fast_forward_checker=lambda _current, _target: False,
            tool_checker=lambda: None,
        )

        dirty = await dirty_service.check(UpdateChannel.DEV, force=True)
        diverged = await diverged_service.check(UpdateChannel.DEV, force=True)

        self.assertEqual(dirty.block_code, "dirty_worktree")
        self.assertEqual(diverged.block_code, "not_fast_forward")
        self.assertFalse(dirty.can_apply)
        self.assertFalse(diverged.can_apply)

    async def test_channel_target_behind_current_revision_is_not_an_update(self) -> None:
        client = FakeRepositoryClient()
        client.ancestors.add((TARGET_SHA, CURRENT_SHA))
        service = UpdateService(
            repository_client=client,
            identity_provider=self.make_identity,
            fast_forward_checker=lambda _current, _target: False,
            tool_checker=lambda: None,
        )

        status = await service.check(UpdateChannel.DEV, force=True)

        self.assertFalse(status.update_available)
        self.assertFalse(status.can_apply)
        self.assertEqual(status.block_code, "target_behind")


class PendingUpdateStoreTest(unittest.TestCase):
    def test_pending_plan_is_atomically_persisted_with_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PendingUpdateStore(Path(tmpdir))
            plan = PendingUpdate(
                channel=UpdateChannel.DEV,
                current_revision=CURRENT_SHA,
                target_revision=TARGET_SHA,
                target_ref="dev",
                requested_at="2026-07-31T12:00:00+00:00",
            )

            store.write_pending(plan)

            self.assertEqual(store.read_pending(), plan)
            self.assertEqual(stat.S_IMODE(store.pending_path.stat().st_mode), 0o600)
            payload = json.loads(store.pending_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["target_revision"], TARGET_SHA)


class RunnerUpdateTest(unittest.TestCase):
    def test_runner_fetches_fixed_ref_verifies_sha_and_fast_forwards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / ".git").mkdir()
            (project_root / "webui").mkdir()
            store = PendingUpdateStore(project_root / "data" / "update")
            store.write_pending(
                PendingUpdate(
                    channel=UpdateChannel.DEV,
                    current_revision=CURRENT_SHA,
                    target_revision=TARGET_SHA,
                    target_ref="dev",
                    requested_at="2026-07-31T12:00:00+00:00",
                )
            )
            commands: list[tuple[str, ...]] = []

            def run_command(args: list[str], _cwd: Path, _timeout: int) -> subprocess.CompletedProcess[str]:
                commands.append(tuple(args))
                stdout = ""
                if args[1:] == ["rev-parse", "HEAD"]:
                    stdout = CURRENT_SHA + "\n"
                elif args[1:] == ["status", "--porcelain", "--untracked-files=no"]:
                    stdout = ""
                elif args[1:] == ["rev-parse", "FETCH_HEAD^{commit}"]:
                    stdout = TARGET_SHA + "\n"
                return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

            result = apply_pending_update(
                project_root=project_root,
                store=store,
                command_runner=run_command,
                executable_finder=lambda name: f"/usr/bin/{name}",
            )

            self.assertTrue(result.success)
            self.assertIn(
                (
                    "/usr/bin/git",
                    "fetch",
                    "--no-tags",
                    "https://github.com/hsd221/riyabot.git",
                    "refs/heads/dev",
                ),
                commands,
            )
            self.assertIn(("/usr/bin/git", "merge", "--ff-only", TARGET_SHA), commands)
            self.assertIn(("/usr/bin/uv", "sync", "--locked"), commands)
            self.assertIn(("/usr/bin/bun", "install", "--frozen-lockfile"), commands)
            self.assertIn(("/usr/bin/bun", "run", "build"), commands)
            self.assertFalse(store.pending_path.exists())

    def test_runner_reports_when_code_advanced_but_post_update_command_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / ".git").mkdir()
            (project_root / "webui").mkdir()
            store = PendingUpdateStore(project_root / "data" / "update")
            store.write_pending(
                PendingUpdate(
                    channel=UpdateChannel.DEV,
                    current_revision=CURRENT_SHA,
                    target_revision=TARGET_SHA,
                    target_ref="dev",
                    requested_at="2026-07-31T12:00:00+00:00",
                )
            )

            def run_command(args: list[str], _cwd: Path, _timeout: int) -> subprocess.CompletedProcess[str]:
                stdout = ""
                return_code = 0
                if args[1:] == ["rev-parse", "HEAD"]:
                    stdout = CURRENT_SHA + "\n"
                elif args[1:] == ["rev-parse", "FETCH_HEAD^{commit}"]:
                    stdout = TARGET_SHA + "\n"
                elif args[1:] == ["sync", "--locked"]:
                    return_code = 1
                return subprocess.CompletedProcess(args, return_code, stdout=stdout, stderr="sync failed")

            result = apply_pending_update(
                project_root=project_root,
                store=store,
                command_runner=run_command,
                executable_finder=lambda name: f"/usr/bin/{name}",
            )

            self.assertFalse(result.success)
            self.assertEqual(result.code, "post_update_failed")
            self.assertIn("代码已快进", result.message)
            self.assertEqual(store.read_result()["code"], "post_update_failed")

    def test_runner_rejects_a_plan_when_current_revision_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / ".git").mkdir()
            store = PendingUpdateStore(project_root / "data" / "update")
            store.write_pending(
                PendingUpdate(
                    channel=UpdateChannel.DEV,
                    current_revision=CURRENT_SHA,
                    target_revision=TARGET_SHA,
                    target_ref="dev",
                    requested_at="2026-07-31T12:00:00+00:00",
                )
            )
            commands: list[tuple[str, ...]] = []

            def run_command(args: list[str], _cwd: Path, _timeout: int) -> subprocess.CompletedProcess[str]:
                commands.append(tuple(args))
                return subprocess.CompletedProcess(args, 0, stdout="9" * 40 + "\n", stderr="")

            result = apply_pending_update(
                project_root=project_root,
                store=store,
                command_runner=run_command,
                executable_finder=lambda name: f"/usr/bin/{name}",
            )

            self.assertFalse(result.success)
            self.assertEqual(result.code, "current_revision_changed")
            self.assertFalse(any(command[1:3] == ("fetch", "--no-tags") for command in commands))

    def test_runner_turns_preflight_command_failures_into_a_persisted_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / ".git").mkdir()
            store = PendingUpdateStore(project_root / "data" / "update")
            store.write_pending(
                PendingUpdate(
                    channel=UpdateChannel.DEV,
                    current_revision=CURRENT_SHA,
                    target_revision=TARGET_SHA,
                    target_ref="dev",
                    requested_at="2026-07-31T12:00:00+00:00",
                )
            )

            def fail_command(args: list[str], _cwd: Path, _timeout: int) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args, 128, stdout="", stderr="git failed")

            result = apply_pending_update(
                project_root=project_root,
                store=store,
                command_runner=fail_command,
                executable_finder=lambda name: f"/usr/bin/{name}",
            )

            self.assertFalse(result.success)
            self.assertEqual(result.code, "command_failed")
            self.assertEqual(store.read_result()["code"], "command_failed")
