"""Resume-state orchestration for chat-history import tasks."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from src.bw_learner.history_import import ImportedMessage
from src.bw_learner.history_learning import HistoryCandidates, HistoryStoreResult, HistoryWindowCheckpoint
from src.common.database.database_model import ChatHistoryImportTask
from src.webui.chat_history_candidate_catalog import page_candidate_catalog
from src.webui.chat_history_checkpoint import (
    append_extraction_checkpoint,
    load_extraction_checkpoints,
    load_pending_learning_result,
)


CoreCandidateStore = Callable[[str, HistoryCandidates, Mapping[str, ImportedMessage]], HistoryStoreResult]


def _load_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def learning_checkpoint_key(task: ChatHistoryImportTask, options: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"source_hash": task.source_hash, "options": options},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def can_resume_task(task: ChatHistoryImportTask, task_dir: Path, options: dict[str, Any]) -> bool:
    return task.status == "failed" and bool(options.get("depth")) and (task_dir / "normalized.jsonl").is_file()


def has_submitted_profile_decisions(task: ChatHistoryImportTask) -> bool:
    review = _load_json_object(task.result_json).get("profile_review")
    return isinstance(review, dict) and isinstance(review.get("decisions"), dict)


def mark_task_failed(task: ChatHistoryImportTask, message: str, *, resume_stage: str | None = None) -> None:
    now = time.time()
    task.status = "failed"
    task.progress_stage = "failed"
    task.resume_stage = (resume_stage or task.resume_stage or "extracting")[:32]
    task.error_message = message
    task.updated_at = now
    task.completed_at = now
    task.save()


def validate_learning_resume_artifacts(
    task: ChatHistoryImportTask,
    task_dir: Path,
    options: dict[str, Any],
) -> None:
    pending_result = load_pending_learning_result(task_dir)
    if pending_result is None:
        load_extraction_checkpoints(task_dir, learning_checkpoint_key(task, options))
        return
    page_candidate_catalog(
        task_dir,
        pending_result,
        kind="expressions",
        query="",
        page=1,
        page_size=1,
    )


@dataclass
class ExtractionCheckpointSession:
    import_id: str
    task_dir: Path
    checkpoint_key: str
    checkpoints: dict[str, HistoryWindowCheckpoint]
    window_ids: set[str] = field(init=False)

    def __post_init__(self) -> None:
        self.window_ids = set(self.checkpoints)

    @classmethod
    async def load(
        cls,
        task: ChatHistoryImportTask,
        task_dir: Path,
        options: dict[str, Any],
    ) -> ExtractionCheckpointSession:
        checkpoint_key = learning_checkpoint_key(task, options)
        checkpoints = await asyncio.to_thread(load_extraction_checkpoints, task_dir, checkpoint_key)
        ChatHistoryImportTask.update(checkpoint_window_count=len(checkpoints)).where(
            ChatHistoryImportTask.import_id == task.import_id
        ).execute()
        return cls(
            import_id=task.import_id,
            task_dir=task_dir,
            checkpoint_key=checkpoint_key,
            checkpoints=checkpoints,
        )

    async def persist(self, checkpoint: HistoryWindowCheckpoint) -> None:
        await asyncio.to_thread(
            append_extraction_checkpoint,
            self.task_dir,
            self.checkpoint_key,
            checkpoint,
        )
        self.window_ids.add(checkpoint.window_id)
        ChatHistoryImportTask.update(
            checkpoint_window_count=len(self.window_ids),
            updated_at=time.time(),
        ).where(ChatHistoryImportTask.import_id == self.import_id).execute()


def store_core_candidates_once(
    *,
    task: ChatHistoryImportTask,
    result_payload: dict[str, Any],
    candidates: HistoryCandidates,
    evidence: Mapping[str, ImportedMessage],
    store_candidates: CoreCandidateStore,
) -> None:
    """Commit candidate counters and the task marker in one SQLite transaction."""

    database = ChatHistoryImportTask._meta.database
    with database.atomic():
        current_task = ChatHistoryImportTask.get_by_id(task.id)
        persisted_payload = _load_json_object(current_task.result_json)
        if current_task.core_store_completed:
            persisted_store_result = persisted_payload.get("store_result")
            if not isinstance(persisted_store_result, dict):
                raise RuntimeError("核心候选写入断点缺少结果")
            result_payload["store_result"] = persisted_store_result
            return

        store_result = store_candidates(task.chat_id or "", candidates, evidence)
        result_payload["store_result"] = {
            "created": store_result.created,
            "updated": store_result.updated,
        }
        current_task.core_store_completed = True
        current_task.result_json = json.dumps(result_payload, ensure_ascii=False, separators=(",", ":"))
        current_task.updated_at = time.time()
        current_task.save()
