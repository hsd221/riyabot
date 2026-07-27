"""Durable, task-scoped checkpoints for chat-history learning."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from src.bw_learner.history_learning import HistoryWindowCheckpoint


EXTRACTION_CHECKPOINT_FILENAME = "extraction_checkpoints.jsonl"
PENDING_RESULT_FILENAME = "pending_result.json"
PENDING_RESULT_TEMP_FILENAME = "pending_result.json.tmp"
MAX_CHECKPOINT_LINE_BYTES = 16 * 1024 * 1024
MAX_PENDING_RESULT_BYTES = 8 * 1024 * 1024
_CHECKPOINT_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


class HistoryCheckpointUnavailableError(RuntimeError):
    """Raised when saved work cannot be trusted for a resume attempt."""

    def __init__(self, reason: Literal["mismatch", "corrupt"]):
        super().__init__(reason)
        self.reason = reason


def _validate_checkpoint_key(checkpoint_key: str) -> None:
    if not _CHECKPOINT_KEY_RE.fullmatch(checkpoint_key):
        raise ValueError("invalid checkpoint key")


def fsync_directory(directory: Path) -> None:
    """把目录项刷盘，否则新建/改名后的文件在断电时可能整体丢失。"""

    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # 部分文件系统（如 Windows、某些网络盘）不支持目录 fsync，忽略即可。
        pass
    finally:
        os.close(descriptor)


def append_extraction_checkpoint(
    task_dir: Path,
    checkpoint_key: str,
    checkpoint: HistoryWindowCheckpoint,
) -> None:
    """Append one complete window record and make it durable before returning."""

    _validate_checkpoint_key(checkpoint_key)
    payload = json.dumps(
        {
            "version": 1,
            "checkpoint_key": checkpoint_key,
            "checkpoint": checkpoint.to_json(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > MAX_CHECKPOINT_LINE_BYTES:
        raise HistoryCheckpointUnavailableError("corrupt")

    destination = task_dir / EXTRACTION_CHECKPOINT_FILENAME
    is_new_file = not destination.exists()
    with destination.open("ab") as output:
        destination.chmod(0o600)
        output.write(payload)
        output.write(b"\n")
        output.flush()
        os.fsync(output.fileno())
    if is_new_file:
        fsync_directory(task_dir)


def load_extraction_checkpoints(
    task_dir: Path,
    checkpoint_key: str,
) -> dict[str, HistoryWindowCheckpoint]:
    """Load complete records, ignoring only a crash-truncated final line."""

    _validate_checkpoint_key(checkpoint_key)
    source_path = task_dir / EXTRACTION_CHECKPOINT_FILENAME
    if not source_path.is_file():
        return {}

    checkpoints: dict[str, HistoryWindowCheckpoint] = {}
    try:
        with source_path.open("rb") as source:
            for line in source:
                if not line.endswith(b"\n"):
                    break
                if len(line) > MAX_CHECKPOINT_LINE_BYTES + 1:
                    raise HistoryCheckpointUnavailableError("corrupt")
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, UnicodeError, TypeError) as error:
                    raise HistoryCheckpointUnavailableError("corrupt") from error
                if not isinstance(entry, dict) or entry.get("version") != 1:
                    raise HistoryCheckpointUnavailableError("corrupt")
                if entry.get("checkpoint_key") != checkpoint_key:
                    raise HistoryCheckpointUnavailableError("mismatch")
                raw_checkpoint = entry.get("checkpoint")
                if not isinstance(raw_checkpoint, dict):
                    raise HistoryCheckpointUnavailableError("corrupt")
                try:
                    checkpoint = HistoryWindowCheckpoint.from_json(raw_checkpoint)
                except (TypeError, ValueError) as error:
                    raise HistoryCheckpointUnavailableError("corrupt") from error
                checkpoints[checkpoint.window_id] = checkpoint
    except HistoryCheckpointUnavailableError:
        raise
    except (OSError, UnicodeError) as error:
        raise HistoryCheckpointUnavailableError("corrupt") from error
    return checkpoints


def write_pending_learning_result(task_dir: Path, result: dict[str, Any]) -> None:
    """Atomically persist a post-LLM result so commit failures do not rerun the model."""

    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_PENDING_RESULT_BYTES:
        raise HistoryCheckpointUnavailableError("corrupt")
    temporary = task_dir / PENDING_RESULT_TEMP_FILENAME
    destination = task_dir / PENDING_RESULT_FILENAME
    with temporary.open("wb") as output:
        temporary.chmod(0o600)
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(destination)
    fsync_directory(task_dir)


def load_pending_learning_result(task_dir: Path) -> dict[str, Any] | None:
    source_path = task_dir / PENDING_RESULT_FILENAME
    if not source_path.is_file():
        return None
    try:
        if source_path.stat().st_size > MAX_PENDING_RESULT_BYTES:
            raise HistoryCheckpointUnavailableError("corrupt")
        parsed = json.loads(source_path.read_text(encoding="utf-8"))
    except HistoryCheckpointUnavailableError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as error:
        raise HistoryCheckpointUnavailableError("corrupt") from error
    if not isinstance(parsed, dict):
        raise HistoryCheckpointUnavailableError("corrupt")
    return parsed


def remove_history_resume_artifacts(task_dir: Path) -> None:
    for filename in (
        EXTRACTION_CHECKPOINT_FILENAME,
        PENDING_RESULT_FILENAME,
        PENDING_RESULT_TEMP_FILENAME,
    ):
        (task_dir / filename).unlink(missing_ok=True)
