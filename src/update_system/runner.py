"""Runner-owned update plan persistence and source checkout executor."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.logger import get_logger

from .models import PendingUpdate, UpdateChannel, UpdateResult


REPOSITORY_URL = "https://github.com/hsd221/riyabot.git"
UPDATE_EXIT_CODE = 43
CommandRunner = Callable[[list[str], Path, int], subprocess.CompletedProcess[str]]
logger = get_logger("update_runner")


class PendingUpdateStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.pending_path = directory / "pending.json"
        self.result_path = directory / "result.json"

    def write_pending(self, plan: PendingUpdate) -> None:
        self._atomic_write(self.pending_path, plan.to_dict())

    def read_pending(self) -> PendingUpdate | None:
        payload = self._read_json(self.pending_path)
        return PendingUpdate.from_dict(payload) if payload is not None else None

    def clear_pending(self) -> None:
        try:
            self.pending_path.unlink()
        except FileNotFoundError:
            pass

    def clear_result(self) -> None:
        try:
            self.result_path.unlink()
        except FileNotFoundError:
            pass

    def write_result(self, result: UpdateResult) -> None:
        self._atomic_write(self.result_path, result.to_dict())

    def read_result(self) -> dict[str, Any] | None:
        return self._read_json(self.result_path)

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            if path.is_symlink():
                raise ValueError("update state file must not be a symbolic link")
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        if len(raw) > 64 * 1024:
            raise ValueError("update state file is too large")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("update state payload must be an object")
        return payload

    def _atomic_write(self, path: Path, payload: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise ValueError("update state directory must not be a symbolic link")
        encoded = (json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=self.directory)
        temporary_path = Path(temporary_name)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
            os.chmod(path, 0o600)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def apply_pending_update(
    *,
    project_root: Path,
    store: PendingUpdateStore,
    command_runner: CommandRunner | None = None,
    executable_finder: Callable[[str], str | None] = shutil.which,
) -> UpdateResult:
    runner = command_runner or _run_command
    try:
        plan = store.read_pending()
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return _finish(store, False, "invalid_plan", f"更新计划无效：{type(exc).__name__}")
    if plan is None:
        return _finish(store, False, "no_pending_update", "没有待执行的更新计划")

    if not (project_root / ".git").exists():
        return _finish(store, False, "not_source_install", "当前安装不是 Git 源码检出", plan.target_revision)

    executables = {name: executable_finder(name) for name in ("git", "uv", "bun")}
    missing = [name for name, path in executables.items() if path is None]
    if missing:
        return _finish(store, False, "missing_tool", f"缺少更新工具：{', '.join(missing)}", plan.target_revision)

    git = str(executables["git"])
    uv = str(executables["uv"])
    bun = str(executables["bun"])

    try:
        current = _checked_output(runner, [git, "rev-parse", "HEAD"], project_root, 10)
        dirty = _checked_output(runner, [git, "status", "--porcelain", "--untracked-files=no"], project_root, 10)
    except subprocess.TimeoutExpired as exc:
        _log_command_failure("runner.update.preflight_timeout", exc)
        return _finish(store, False, "command_timeout", "更新前检查超时，请查看日志", plan.target_revision)
    except (OSError, subprocess.SubprocessError) as exc:
        _log_command_failure("runner.update.preflight_failed", exc)
        return _finish(store, False, "command_failed", "更新前检查失败，请查看日志", plan.target_revision)

    if current != plan.current_revision:
        return _finish(
            store,
            False,
            "current_revision_changed",
            "当前提交在计划创建后发生变化，已取消更新",
            plan.target_revision,
        )
    if dirty:
        return _finish(store, False, "dirty_worktree", "工作区存在未提交修改，已取消更新", plan.target_revision)

    remote_ref = "refs/heads/dev" if plan.channel is UpdateChannel.DEV else f"refs/tags/{plan.target_ref}"
    commands: list[tuple[list[str], Path, int]] = [
        ([git, "fetch", "--no-tags", REPOSITORY_URL, remote_ref], project_root, 120),
    ]
    checkout_advanced = False
    try:
        for args, cwd, timeout in commands:
            _checked_run(runner, args, cwd, timeout)
        fetched = _checked_output(runner, [git, "rev-parse", "FETCH_HEAD^{commit}"], project_root, 10)
        if fetched != plan.target_revision:
            return _finish(
                store, False, "target_revision_changed", "远端目标已变化，请重新检查更新", plan.target_revision
            )
        _checked_run(runner, [git, "merge-base", "--is-ancestor", current, fetched], project_root, 10)
        _checked_run(runner, [git, "merge", "--ff-only", fetched], project_root, 60)
        checkout_advanced = True
        _checked_run(runner, [uv, "sync", "--locked"], project_root, 600)
        webui_root = project_root / "webui"
        _checked_run(runner, [bun, "install", "--frozen-lockfile"], webui_root, 600)
        _checked_run(runner, [bun, "run", "build"], webui_root, 600)
    except subprocess.TimeoutExpired as exc:
        _log_command_failure("runner.update.command_timeout", exc)
        if checkout_advanced:
            return _finish(
                store,
                False,
                "post_update_timeout",
                "代码已快进到目标提交，但依赖同步或 WebUI 构建超时，请查看日志",
                plan.target_revision,
            )
        return _finish(store, False, "command_timeout", "更新命令执行超时，请查看日志", plan.target_revision)
    except (OSError, subprocess.SubprocessError) as exc:
        _log_command_failure("runner.update.command_failed", exc)
        if checkout_advanced:
            return _finish(
                store,
                False,
                "post_update_failed",
                "代码已快进到目标提交，但依赖同步或 WebUI 构建失败，请查看日志",
                plan.target_revision,
            )
        return _finish(store, False, "command_failed", "更新命令执行失败，请查看日志", plan.target_revision)

    return _finish(store, True, "updated", "更新完成，正在启动新版本", plan.target_revision)


def _checked_run(runner: CommandRunner, args: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    completed = runner(args, cwd, timeout)
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, args, completed.stdout, completed.stderr)
    return completed


def _checked_output(runner: CommandRunner, args: list[str], cwd: Path, timeout: int) -> str:
    return _checked_run(runner, args, cwd, timeout).stdout.strip().lower()


def _run_command(args: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout)


def _log_command_failure(event_code: str, exc: BaseException) -> None:
    command = getattr(exc, "cmd", None)
    if isinstance(command, (list, tuple)) and command:
        executable = Path(str(command[0])).name
        action = str(command[1])[:32] if len(command) > 1 else "unknown"
    else:
        executable = "unknown"
        action = "unknown"
    logger.error(
        "更新命令执行失败",
        event_code=event_code,
        error_type=type(exc).__name__,
        executable=executable,
        action=action,
        return_code=getattr(exc, "returncode", None),
    )


def _finish(
    store: PendingUpdateStore,
    success: bool,
    code: str,
    message: str,
    target_revision: str | None = None,
) -> UpdateResult:
    result = UpdateResult(
        success=success,
        code=code,
        message=message,
        completed_at=datetime.now(timezone.utc).isoformat(),
        target_revision=target_revision,
    )
    try:
        store.write_result(result)
    finally:
        store.clear_pending()
    return result
