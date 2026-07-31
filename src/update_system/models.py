"""Typed contracts shared by update discovery, WebUI, and the Runner."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
STABLE_TAG_RE = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\+([0-9A-Za-z.-]+))?$")


class UpdateChannel(str, Enum):
    STABLE = "stable"
    DEV = "dev"


class InstallationMode(str, Enum):
    SOURCE = "source"
    DOCKER = "docker"
    ARCHIVE = "archive"


@dataclass(frozen=True)
class BuildIdentity:
    version: str
    revision: str | None
    ref: str | None
    installation_mode: InstallationMode
    dirty: bool

    def __post_init__(self) -> None:
        if self.revision is not None and not FULL_SHA_RE.fullmatch(self.revision):
            raise ValueError("revision must be a lowercase 40-character SHA")


@dataclass(frozen=True)
class RemoteBranch:
    name: str
    revision: str
    summary: str = ""

    def __post_init__(self) -> None:
        _validate_sha(self.revision, "branch revision")


@dataclass(frozen=True)
class RemoteTag:
    name: str
    revision: str
    summary: str = ""

    def __post_init__(self) -> None:
        _validate_sha(self.revision, "tag revision")


@dataclass(frozen=True)
class UpdateTarget:
    ref: str
    revision: str
    summary: str = ""

    def __post_init__(self) -> None:
        _validate_sha(self.revision, "target revision")


@dataclass(frozen=True)
class UpdateStatus:
    channel: UpdateChannel
    current: BuildIdentity
    target: UpdateTarget | None
    update_available: bool
    can_apply: bool
    block_code: str | None
    block_message: str | None
    checked_at: str

    def to_dict(self) -> dict[str, Any]:
        return _enum_values(asdict(self))


@dataclass(frozen=True)
class PendingUpdate:
    channel: UpdateChannel
    current_revision: str
    target_revision: str
    target_ref: str
    requested_at: str

    def __post_init__(self) -> None:
        _validate_sha(self.current_revision, "current revision")
        _validate_sha(self.target_revision, "target revision")
        if self.channel is UpdateChannel.DEV and self.target_ref != "dev":
            raise ValueError("dev updates must target the dev branch")
        if self.channel is UpdateChannel.STABLE and stable_version(self.target_ref) is None:
            raise ValueError("stable updates must target a stable semantic-version tag")

    def to_dict(self) -> dict[str, str]:
        return {
            "channel": self.channel.value,
            "current_revision": self.current_revision,
            "target_revision": self.target_revision,
            "target_ref": self.target_ref,
            "requested_at": self.requested_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PendingUpdate":
        expected_keys = {
            "channel",
            "current_revision",
            "target_revision",
            "target_ref",
            "requested_at",
        }
        if set(payload) != expected_keys or not all(isinstance(payload[key], str) for key in expected_keys):
            raise ValueError("pending update payload is invalid")
        return cls(
            channel=UpdateChannel(payload["channel"]),
            current_revision=payload["current_revision"],
            target_revision=payload["target_revision"],
            target_ref=payload["target_ref"],
            requested_at=payload["requested_at"],
        )


@dataclass(frozen=True)
class UpdateResult:
    success: bool
    code: str
    message: str
    completed_at: str
    target_revision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_sha(value: str, label: str) -> None:
    if not FULL_SHA_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase 40-character SHA")


def stable_version(tag_name: str) -> tuple[int, int, int] | None:
    match = STABLE_TAG_RE.fullmatch(tag_name)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def select_latest_stable_tag(tags: Iterable[RemoteTag]) -> RemoteTag | None:
    candidates = [(version, tag) for tag in tags if (version := stable_version(tag.name)) is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _enum_values(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _enum_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_enum_values(item) for item in value]
    return value
