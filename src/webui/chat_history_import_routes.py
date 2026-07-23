"""Authenticated WebUI routes for chat-history learning imports."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Cookie, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.bw_learner.history_enrichment import load_history_enrichment_evidence, store_history_enrichment
from src.bw_learner.history_import import ChatHistoryFormatError, analyze_qq_chat_export, build_history_windows
from src.bw_learner.history_learning import (
    DEPTH_WINDOW_BUDGETS,
    ChatHistoryLearner,
    HistoryLearningCancelled,
    group_chat_id,
)
from src.common.database.database_model import ChatHistoryImportTask
from src.common.logger import get_logger
from src.webui.auth import verify_auth_token_from_cookie_or_header
from src.webui.error_utils import internal_server_error, log_exception_type


logger = get_logger("webui.chat_history_import")
router = APIRouter(prefix="/chat-history-imports", tags=["Chat history imports"])

IMPORT_ROOT = Path(__file__).resolve().parents[2] / "data" / "chat_history_imports"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_CONCURRENT_IMPORTS = 1
_IMPORT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_KNOWN_TASK_FILES = ("source.json", "normalized.jsonl", "result.json", "result.json.tmp")
_running_tasks: dict[str, asyncio.Task[None]] = {}
_analyzing_import_ids: set[str] = set()


class ImportedChatResponse(BaseModel):
    name: str
    source_id: str
    chat_type: str
    self_user_id: str


class ImportedParticipantResponse(BaseModel):
    source_id: str
    name: str
    card: str
    message_count: int
    is_bot: bool


class ChatHistoryAnalysisResponse(BaseModel):
    source_format: str
    chat: ImportedChatResponse
    total_messages: int
    retained_messages: int
    filtered_messages: int
    noise_counts: dict[str, int]
    participants: list[ImportedParticipantResponse]
    participant_count: int = 0
    start_timestamp: float | None
    end_timestamp: float | None
    total_window_count: int
    estimated_model_call_note: str = ""


class ChatHistoryImportProgress(BaseModel):
    stage: str
    current: int
    total: int


class ChatHistoryImportResponse(BaseModel):
    import_id: str
    source_name: str
    source_size: int
    status: str
    chat_id: str | None
    analysis: ChatHistoryAnalysisResponse | None
    estimated_model_calls: dict[str, int]
    progress: ChatHistoryImportProgress
    options: dict[str, Any]
    result: dict[str, Any] | None
    error_message: str | None
    created_at: float
    updated_at: float
    started_at: float | None
    completed_at: float | None


class ChatHistoryImportListResponse(BaseModel):
    success: bool = True
    data: list[ChatHistoryImportResponse]


class ChatHistoryImportStartRequest(BaseModel):
    depth: Literal["fast", "balanced", "deep", "full"] = "balanced"
    participant_ids: list[str] = Field(default_factory=list, max_length=200)
    extract_memories: bool = False
    update_profiles: bool = False


class ChatHistoryImportDeleteResponse(BaseModel):
    success: bool
    message: str


def verify_auth_token(maibot_session: Optional[str] = None, authorization: Optional[str] = None) -> bool:
    return verify_auth_token_from_cookie_or_header(maibot_session, authorization)


def _safe_source_name(filename: str | None) -> str:
    normalized = (filename or "history.json").replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    cleaned = "".join(character for character in normalized if character >= " " and character != "\x7f").strip()
    return (cleaned or "history.json")[:128]


def _task_dir(import_id: str) -> Path:
    if not _IMPORT_ID_RE.fullmatch(import_id):
        raise ValueError("invalid import id")
    root = IMPORT_ROOT.resolve()
    task_dir = (root / import_id).resolve()
    if task_dir.parent != root:
        raise ValueError("invalid import path")
    return task_dir


def _cleanup_task_files(import_id: str, *, remove_directory: bool = True) -> None:
    try:
        task_dir = _task_dir(import_id)
    except ValueError:
        return
    for filename in _KNOWN_TASK_FILES:
        try:
            (task_dir / filename).unlink(missing_ok=True)
        except OSError as error:
            log_exception_type(logger, "清理聊天记录导入文件失败", error, import_id=import_id)
    if remove_directory:
        try:
            task_dir.rmdir()
        except FileNotFoundError:
            pass
        except OSError as error:
            log_exception_type(logger, "清理聊天记录导入目录失败", error, import_id=import_id)


def _active_local_import_count() -> int:
    running_count = sum(not task.done() for task in _running_tasks.values())
    return len(_analyzing_import_ids) + running_count


def _load_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _task_to_response(task: ChatHistoryImportTask) -> ChatHistoryImportResponse:
    analysis = _load_json_object(task.analysis_json)
    estimates = analysis.pop("estimated_model_calls", {})
    result = _load_json_object(task.result_json) if task.result_json else None
    return ChatHistoryImportResponse(
        import_id=task.import_id,
        source_name=task.source_name,
        source_size=task.source_size,
        status=task.status,
        chat_id=task.chat_id,
        analysis=ChatHistoryAnalysisResponse.model_validate(analysis) if analysis else None,
        estimated_model_calls={str(key): int(value) for key, value in estimates.items()},
        progress=ChatHistoryImportProgress(
            stage=task.progress_stage,
            current=max(0, task.progress_current),
            total=max(1, task.progress_total),
        ),
        options=_load_json_object(task.options_json),
        result=result,
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )


async def _stream_upload(upload: UploadFile, destination: Path) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    try:
        with destination.open("xb") as output:
            destination.chmod(0o600)
            while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="聊天记录文件不能超过 100MB")
                digest.update(chunk)
                output.write(chunk)
    finally:
        await upload.close()
    if size == 0:
        raise HTTPException(status_code=400, detail="聊天记录文件为空")
    return size, digest.hexdigest()


def _analysis_payload(analysis: Any, total_window_count: int) -> dict[str, Any]:
    payload = analysis.to_json()
    payload.pop("normalized_path", None)
    payload["participants"] = list(payload.get("participants", ()))
    payload["participant_count"] = len(payload["participants"])
    payload["total_window_count"] = total_window_count
    payload["estimated_model_calls"] = {
        depth: (total_window_count if budget is None else min(total_window_count, budget)) + 1
        for depth, budget in DEPTH_WINDOW_BUDGETS.items()
    }
    payload["estimated_model_call_note"] = "每个自然窗口 1 次提取、最后 1 次跨窗口合并；若窗口边界未结束，可能追加 1 次续接提取。"
    return payload


def _get_task_or_404(import_id: str) -> ChatHistoryImportTask:
    task = ChatHistoryImportTask.get_or_none(ChatHistoryImportTask.import_id == import_id)
    if task is None:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    _reconcile_interrupted_task(task)
    return task


def _reconcile_interrupted_task(task: ChatHistoryImportTask) -> None:
    is_interrupted_analysis = task.status == "analyzing" and task.import_id not in _analyzing_import_ids
    is_interrupted_learning = task.status == "running" and task.import_id not in _running_tasks
    if not (is_interrupted_analysis or is_interrupted_learning):
        return
    _cleanup_task_files(task.import_id, remove_directory=False)
    task.status = "failed"
    task.progress_stage = "failed"
    task.error_message = "任务因服务重启而中断，请删除后重新导入"
    task.source_path = ""
    task.normalized_path = ""
    task.updated_at = time.time()
    task.completed_at = task.updated_at
    task.save()


@router.post("", response_model=ChatHistoryImportResponse)
async def create_chat_history_import(
    file: Annotated[UploadFile, File(description="QQChatExporter JSON 群聊记录")],
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> ChatHistoryImportResponse:
    verify_auth_token(maibot_session, authorization)
    source_name = _safe_source_name(file.filename)
    if not source_name.casefold().endswith(".json"):
        await file.close()
        raise HTTPException(status_code=400, detail="仅支持 JSON 聊天记录文件")
    content_type = file.content_type.split(";", maxsplit=1)[0].strip().casefold() if file.content_type else None
    if content_type not in {None, "application/json", "text/json", "application/octet-stream"}:
        await file.close()
        raise HTTPException(status_code=400, detail="仅支持 JSON 聊天记录文件")
    if _active_local_import_count() >= MAX_CONCURRENT_IMPORTS:
        await file.close()
        raise HTTPException(status_code=409, detail="已有聊天记录导入或学习任务正在运行")

    import_id = uuid.uuid4().hex
    IMPORT_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    task_dir = _task_dir(import_id)
    task_dir.mkdir(mode=0o700)
    source_path = task_dir / "source.json"
    normalized_path = task_dir / "normalized.jsonl"
    task: ChatHistoryImportTask | None = None
    _analyzing_import_ids.add(import_id)
    try:
        source_size, source_hash = await _stream_upload(file, source_path)
        duplicate = (
            ChatHistoryImportTask.select()
            .where(
                (ChatHistoryImportTask.source_hash == source_hash)
                & ChatHistoryImportTask.status.in_(("ready", "running", "completed"))
            )
            .first()
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="相同聊天记录已存在导入任务")

        now = time.time()
        task = ChatHistoryImportTask.create(
            import_id=import_id,
            source_hash=source_hash,
            source_name=source_name,
            source_size=source_size,
            status="analyzing",
            source_path=str(source_path),
            normalized_path=str(normalized_path),
            progress_stage="analyzing",
            progress_current=0,
            progress_total=1,
            created_at=now,
            updated_at=now,
        )
        analysis = await asyncio.to_thread(analyze_qq_chat_export, source_path, normalized_path)
        windows = await asyncio.to_thread(build_history_windows, normalized_path)
        payload = _analysis_payload(analysis, len(windows))
        now = time.time()
        task.status = "ready"
        task.chat_id = group_chat_id("qq", analysis.chat.source_id)
        task.chat_name = analysis.chat.name
        task.group_id = analysis.chat.source_id
        task.analysis_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        task.progress_stage = "ready"
        task.progress_current = 1
        task.progress_total = 1
        task.source_path = ""
        task.updated_at = now
        task.save()
        source_path.unlink(missing_ok=True)
        return _task_to_response(task)
    except HTTPException:
        if task is not None:
            task.delete_instance()
        _cleanup_task_files(import_id)
        raise
    except ChatHistoryFormatError as error:
        if task is not None:
            task.delete_instance()
        _cleanup_task_files(import_id)
        message = error.args[0] if error.args and isinstance(error.args[0], str) else ""
        detail = "仅支持 QQ 群聊导出记录" if "仅支持 QQ 群聊" in message else "聊天记录 JSON 格式无效"
        raise HTTPException(status_code=400, detail=detail) from None
    except Exception as error:
        if task is not None:
            task.delete_instance()
        _cleanup_task_files(import_id)
        raise internal_server_error(logger, "分析聊天记录失败", error) from None
    finally:
        _analyzing_import_ids.discard(import_id)


@router.get("", response_model=ChatHistoryImportListResponse)
async def list_chat_history_imports(
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> ChatHistoryImportListResponse:
    verify_auth_token(maibot_session, authorization)
    try:
        tasks = list(ChatHistoryImportTask.select().order_by(ChatHistoryImportTask.created_at.desc()).limit(100))
        for task in tasks:
            _reconcile_interrupted_task(task)
        return ChatHistoryImportListResponse(data=[_task_to_response(task) for task in tasks])
    except HTTPException:
        raise
    except Exception as error:
        raise internal_server_error(logger, "获取聊天记录导入任务失败", error) from None


@router.get("/{import_id}", response_model=ChatHistoryImportResponse)
async def get_chat_history_import(
    import_id: str,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> ChatHistoryImportResponse:
    verify_auth_token(maibot_session, authorization)
    return _task_to_response(_get_task_or_404(import_id))


async def _update_progress(import_id: str, stage: str, current: int, total: int) -> None:
    ChatHistoryImportTask.update(
        progress_stage=stage[:32],
        progress_current=max(0, current),
        progress_total=max(1, total),
        updated_at=time.time(),
    ).where(ChatHistoryImportTask.import_id == import_id).execute()


def _write_result(import_id: str, result: dict[str, Any]) -> None:
    task_dir = _task_dir(import_id)
    temporary = task_dir / "result.json.tmp"
    destination = task_dir / "result.json"
    temporary.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(destination)


def _mark_task_cancelled(import_id: str, normalized_path: Path) -> None:
    now = time.time()
    ChatHistoryImportTask.update(
        status="cancelled",
        progress_stage="cancelled",
        error_message=None,
        normalized_path="",
        updated_at=now,
        completed_at=now,
    ).where(ChatHistoryImportTask.import_id == import_id).execute()
    normalized_path.unlink(missing_ok=True)


async def _run_learning(import_id: str) -> None:
    task = _get_task_or_404(import_id)
    normalized_path = _task_dir(import_id) / "normalized.jsonl"
    options = _load_json_object(task.options_json)
    extract_memories = options.get("extract_memories") is True
    update_profiles = options.get("update_profiles") is True

    def should_cancel() -> bool:
        current = ChatHistoryImportTask.get_or_none(ChatHistoryImportTask.import_id == import_id)
        return current is None or bool(current.cancel_requested)

    try:
        result = await ChatHistoryLearner().learn(
            normalized_path,
            chat_id=task.chat_id or "",
            chat_name=task.chat_name or task.group_id or "群聊",
            depth=str(options.get("depth") or "balanced"),
            eligible_sender_ids=options.get("participant_ids") or None,
            store=True,
            progress=lambda stage, current, total: _update_progress(import_id, stage, current, total),
            should_cancel=should_cancel,
            extract_memories=extract_memories,
            update_profiles=update_profiles,
        )
        result_payload = result.to_json()
        result_payload["enrichment_store_result"] = None
        if extract_memories or update_profiles:
            evidence = await asyncio.to_thread(
                load_history_enrichment_evidence,
                normalized_path,
                result.candidates,
            )
            enrichment_result = await store_history_enrichment(
                import_id=import_id,
                chat_id=task.chat_id or "",
                group_id=task.group_id or "",
                chat_name=task.chat_name or task.group_id or "群聊",
                candidates=result.candidates,
                evidence=evidence,
                extract_memories=extract_memories,
                update_profiles=update_profiles,
                progress=lambda stage, current, total: _update_progress(import_id, stage, current, total),
                should_cancel=should_cancel,
            )
            result_payload["enrichment_store_result"] = enrichment_result.to_json()
        _write_result(import_id, result_payload)
        now = time.time()
        ChatHistoryImportTask.update(
            status="completed",
            result_json=json.dumps(result_payload, ensure_ascii=False, separators=(",", ":")),
            progress_stage="completed",
            progress_current=1,
            progress_total=1,
            normalized_path="",
            updated_at=now,
            completed_at=now,
        ).where(ChatHistoryImportTask.import_id == import_id).execute()
        normalized_path.unlink(missing_ok=True)
    except asyncio.CancelledError:
        _mark_task_cancelled(import_id, normalized_path)
        raise
    except HistoryLearningCancelled:
        _mark_task_cancelled(import_id, normalized_path)
    except Exception as error:
        log_exception_type(logger, "聊天记录后台学习失败", error, import_id=import_id)
        _cleanup_task_files(import_id, remove_directory=False)
        now = time.time()
        ChatHistoryImportTask.update(
            status="failed",
            progress_stage="failed",
            error_message="学习失败，请检查模型配置和服务日志",
            source_path="",
            normalized_path="",
            updated_at=now,
            completed_at=now,
        ).where(ChatHistoryImportTask.import_id == import_id).execute()


@router.post("/{import_id}/start", response_model=ChatHistoryImportResponse)
async def start_chat_history_import(
    import_id: str,
    request_body: ChatHistoryImportStartRequest,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> ChatHistoryImportResponse:
    verify_auth_token(maibot_session, authorization)
    task = _get_task_or_404(import_id)
    if task.status != "ready":
        raise HTTPException(status_code=409, detail="当前任务状态不能开始学习")
    if _active_local_import_count() >= MAX_CONCURRENT_IMPORTS:
        raise HTTPException(status_code=409, detail="已有聊天记录学习任务正在运行")

    analysis = _load_json_object(task.analysis_json)
    known_participants = {
        str(participant.get("source_id"))
        for participant in analysis.get("participants", [])
        if isinstance(participant, dict) and participant.get("source_id") is not None
    }
    participant_ids = list(dict.fromkeys(item.strip() for item in request_body.participant_ids if item.strip()))
    unknown = set(participant_ids) - known_participants
    if unknown:
        raise HTTPException(status_code=422, detail="选择的参与者不在聊天记录中")
    if not participant_ids:
        participant_ids = [
            str(participant["source_id"])
            for participant in analysis.get("participants", [])
            if isinstance(participant, dict) and not participant.get("is_bot") and participant.get("source_id")
        ]

    now = time.time()
    options = {
        "depth": request_body.depth,
        "participant_ids": participant_ids,
        "extract_memories": request_body.extract_memories,
        "update_profiles": request_body.update_profiles,
    }
    updated = (
        ChatHistoryImportTask.update(
            status="running",
            options_json=json.dumps(options, ensure_ascii=False, separators=(",", ":")),
            error_message=None,
            progress_stage="queued",
            progress_current=0,
            progress_total=1,
            cancel_requested=False,
            started_at=now,
            updated_at=now,
        )
        .where((ChatHistoryImportTask.import_id == import_id) & (ChatHistoryImportTask.status == "ready"))
        .execute()
    )
    if updated != 1:
        raise HTTPException(status_code=409, detail="任务已被其他请求启动")
    background = asyncio.create_task(_run_learning(import_id), name=f"chat-history-import-{import_id}")
    _running_tasks[import_id] = background
    background.add_done_callback(lambda _task: _running_tasks.pop(import_id, None))
    return _task_to_response(_get_task_or_404(import_id))


@router.delete("/{import_id}", response_model=ChatHistoryImportDeleteResponse)
async def delete_chat_history_import(
    import_id: str,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> ChatHistoryImportDeleteResponse:
    verify_auth_token(maibot_session, authorization)
    task = _get_task_or_404(import_id)
    running = _running_tasks.get(import_id)
    if task.status == "running":
        task.cancel_requested = True
        task.updated_at = time.time()
        task.save()
        if running is not None and not running.done():
            running.cancel()
        return ChatHistoryImportDeleteResponse(success=True, message="已请求取消导入任务")

    _cleanup_task_files(import_id)
    task.delete_instance()
    return ChatHistoryImportDeleteResponse(success=True, message="导入任务已删除")
