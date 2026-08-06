"""Remote update discovery and local installation capability checks."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import shutil
import subprocess
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import aiohttp

from src.common.logger import get_logger
from src.config.config import MMC_VERSION, PROJECT_ROOT

from .models import (
    FULL_SHA_RE,
    BuildIdentity,
    InstallationMode,
    RemoteBranch,
    RemoteTag,
    UpdateChannel,
    UpdateStatus,
    UpdateTarget,
    stable_version,
)


logger = get_logger("update_service")
GITHUB_API_ROOT = "https://api.github.com/repos/hsd221/riyabot"
_CACHE_SECONDS = 60.0
_MAX_GITHUB_RESPONSE_BYTES = 2 * 1024 * 1024


class RepositoryClient(Protocol):
    async def get_branch(self, name: str) -> RemoteBranch: ...

    async def list_tags(self) -> list[RemoteTag]: ...

    async def is_ancestor(self, base_revision: str, head_revision: str) -> bool: ...


class GitHubAPIError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"GitHub API returned HTTP {status_code}")
        self.status_code = status_code


class GitHubRepositoryClient:
    """Small, fixed-repository GitHub API client."""

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds, connect=min(timeout_seconds, 5.0))
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"RiyaBot/{MMC_VERSION}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _get_json(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        async with aiohttp.ClientSession(timeout=self._timeout, headers=self._headers) as session:
            async with session.get(f"{GITHUB_API_ROOT}{path}", params=params, allow_redirects=False) as response:
                if response.status != 200:
                    raise GitHubAPIError(response.status)
                raw = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    raw.extend(chunk)
                    if len(raw) > _MAX_GITHUB_RESPONSE_BYTES:
                        raise RuntimeError("GitHub API response was too large")
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError("GitHub API returned invalid JSON") from exc

    async def get_branch(self, name: str) -> RemoteBranch:
        if name not in {"main", "dev"}:
            raise ValueError("unsupported branch")
        payload = await self._get_json(f"/branches/{name}")
        commit = payload.get("commit") if isinstance(payload, dict) else None
        revision = commit.get("sha") if isinstance(commit, dict) else None
        message = commit.get("commit", {}).get("message", "") if isinstance(commit, dict) else ""
        if not isinstance(revision, str) or not FULL_SHA_RE.fullmatch(revision):
            raise RuntimeError("GitHub branch response did not contain a valid revision")
        summary = _clean_summary(message)
        return RemoteBranch(name=name, revision=revision, summary=summary)

    async def list_tags(self) -> list[RemoteTag]:
        tags: list[RemoteTag] = []
        for page in range(1, 11):
            payload = await self._get_json("/tags", params={"per_page": "100", "page": str(page)})
            if not isinstance(payload, list):
                raise RuntimeError("GitHub tags response was invalid")
            for item in payload:
                if not isinstance(item, dict) or not isinstance(item.get("commit"), dict):
                    continue
                name = item.get("name")
                revision = item["commit"].get("sha")
                if isinstance(name, str) and isinstance(revision, str) and FULL_SHA_RE.fullmatch(revision):
                    tags.append(RemoteTag(name=name, revision=revision))
            if len(payload) < 100:
                break
        return tags

    async def is_ancestor(self, base_revision: str, head_revision: str) -> bool:
        if not FULL_SHA_RE.fullmatch(base_revision) or not FULL_SHA_RE.fullmatch(head_revision):
            raise ValueError("invalid revision")
        base = quote(base_revision, safe="")
        head = quote(head_revision, safe="")
        try:
            payload = await self._get_json(
                f"/compare/{base}...{head}",
                params={"per_page": "1", "page": "1"},
            )
        except GitHubAPIError as exc:
            if exc.status_code == 404:
                return False
            raise
        status = payload.get("status") if isinstance(payload, dict) else None
        return status in {"ahead", "identical"}


FastForwardChecker = Callable[[str, str], bool | Awaitable[bool]]


class UpdateService:
    def __init__(
        self,
        *,
        repository_client: RepositoryClient | None = None,
        identity_provider: Callable[[], BuildIdentity] | None = None,
        fast_forward_checker: FastForwardChecker | None = None,
        tool_checker: Callable[[], str | None] | None = None,
        cache_seconds: float = _CACHE_SECONDS,
    ) -> None:
        self.repository_client = repository_client or GitHubRepositoryClient()
        self.identity_provider = identity_provider or detect_build_identity
        self.fast_forward_checker = fast_forward_checker
        self.tool_checker = tool_checker or check_update_tools
        self.cache_seconds = max(0.0, cache_seconds)
        self._cache: dict[UpdateChannel, tuple[float, UpdateStatus]] = {}
        self._lock = asyncio.Lock()

    async def check(self, channel: UpdateChannel, *, force: bool = False) -> UpdateStatus:
        cached = self._cache.get(channel)
        now = time.monotonic()
        if not force and cached is not None and now - cached[0] < self.cache_seconds:
            return cached[1]

        async with self._lock:
            cached = self._cache.get(channel)
            now = time.monotonic()
            if not force and cached is not None and now - cached[0] < self.cache_seconds:
                return cached[1]
            status = await self._check_uncached(channel)
            self._cache[channel] = (now, status)
            return status

    async def _check_uncached(self, channel: UpdateChannel) -> UpdateStatus:
        identity = await asyncio.to_thread(self.identity_provider)
        target = await self._resolve_target(channel)
        checked_at = _utc_now()
        if target is None:
            return UpdateStatus(
                channel, identity, None, False, False, "no_stable_release", "未找到正式版本", checked_at
            )

        update_available = identity.revision != target.revision
        if not update_available:
            return UpdateStatus(channel, identity, target, False, False, None, None, checked_at)

        is_fast_forward: bool | None = None
        if identity.revision is not None:
            is_fast_forward = await self._is_fast_forward(identity.revision, target.revision)
            if not is_fast_forward and await self.repository_client.is_ancestor(target.revision, identity.revision):
                return UpdateStatus(
                    channel,
                    identity,
                    target,
                    False,
                    False,
                    "target_behind",
                    "当前提交比所选频道目标更新，不会执行降级",
                    checked_at,
                )

        blocker = self._find_blocker(identity, is_fast_forward)
        return UpdateStatus(
            channel=channel,
            current=identity,
            target=target,
            update_available=True,
            can_apply=blocker is None,
            block_code=blocker[0] if blocker else None,
            block_message=blocker[1] if blocker else None,
            checked_at=checked_at,
        )

    async def _resolve_target(self, channel: UpdateChannel) -> UpdateTarget | None:
        if channel is UpdateChannel.DEV:
            branch = await self.repository_client.get_branch("dev")
            return UpdateTarget(ref="dev", revision=branch.revision, summary=branch.summary)

        main, tags = await asyncio.gather(self.repository_client.get_branch("main"), self.repository_client.list_tags())
        stable_tags = sorted(
            (tag for tag in tags if stable_version(tag.name) is not None),
            key=lambda tag: _stable_sort_key(tag.name),
            reverse=True,
        )
        for tag in stable_tags:
            if await self.repository_client.is_ancestor(tag.revision, main.revision):
                return UpdateTarget(ref=tag.name, revision=tag.revision, summary=tag.summary)
        return None

    def _find_blocker(self, identity: BuildIdentity, is_fast_forward: bool | None) -> tuple[str, str] | None:
        if identity.installation_mode is InstallationMode.DOCKER:
            return "docker_managed", "Docker 部署请拉取新镜像后重新创建容器"
        if identity.installation_mode is InstallationMode.ARCHIVE:
            return "archive_managed", "压缩包安装只能检测更新，请手动替换程序文件"
        if identity.revision is None:
            return "unknown_revision", "无法识别当前提交，不能执行自动更新"
        if identity.dirty:
            return "dirty_worktree", "工作区存在未提交修改，不能执行自动更新"
        tool_error = self.tool_checker()
        if tool_error:
            return "missing_tool", tool_error
        if not is_fast_forward:
            return "not_fast_forward", "目标版本不是当前提交的快进更新"
        return None

    async def _is_fast_forward(self, current_revision: str, target_revision: str) -> bool:
        check = self.fast_forward_checker
        result = (
            self.repository_client.is_ancestor(current_revision, target_revision)
            if check is None
            else check(current_revision, target_revision)
        )
        if inspect.isawaitable(result):
            return bool(await result)
        return bool(result)


def _stable_sort_key(tag_name: str) -> tuple[int, int, int]:
    return stable_version(tag_name) or (-1, -1, -1)


def _clean_summary(message: Any) -> str:
    if not isinstance(message, str):
        return ""
    lines = message.splitlines()
    first_line = lines[0] if lines else ""
    return "".join(character for character in first_line if character >= " " and character != "\x7f")[:240]


def detect_build_identity(project_root: Path | None = None) -> BuildIdentity:
    root = (project_root or Path(PROJECT_ROOT)).resolve()
    env_mode = os.environ.get("RIYABOT_INSTALLATION_MODE", "").strip().lower()
    env_revision = os.environ.get("RIYABOT_BUILD_REVISION", "").strip().lower()
    env_ref = os.environ.get("RIYABOT_BUILD_REF", "").strip() or None

    if env_mode == InstallationMode.DOCKER.value or (not (root / ".git").exists() and Path("/.dockerenv").exists()):
        revision = env_revision if FULL_SHA_RE.fullmatch(env_revision) else None
        return BuildIdentity(MMC_VERSION, revision, env_ref, InstallationMode.DOCKER, False)

    if (root / ".git").exists():
        if shutil.which("git") is None:
            return BuildIdentity(MMC_VERSION, None, env_ref, InstallationMode.SOURCE, True)
        revision = _git_output(root, ["rev-parse", "HEAD"])
        ref = _git_output(root, ["symbolic-ref", "--quiet", "--short", "HEAD"]) or env_ref
        status = _git_output(root, ["status", "--porcelain", "--untracked-files=no"])
        dirty = status is None or bool(status)
        valid_revision = revision if revision is not None and FULL_SHA_RE.fullmatch(revision) else None
        return BuildIdentity(MMC_VERSION, valid_revision, ref, InstallationMode.SOURCE, dirty)

    revision = env_revision if FULL_SHA_RE.fullmatch(env_revision) else None
    return BuildIdentity(MMC_VERSION, revision, env_ref, InstallationMode.ARCHIVE, False)


def _git_output(root: Path, args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def check_update_tools() -> str | None:
    missing = [name for name in ("git", "uv", "bun") if shutil.which(name) is None]
    if not missing:
        return None
    return f"缺少自动更新所需工具：{', '.join(missing)}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_update_service: UpdateService | None = None


def get_update_service() -> UpdateService:
    global _update_service
    if _update_service is None:
        _update_service = UpdateService()
    return _update_service
