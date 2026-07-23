"""Authenticated WebUI routes for chat-history learning imports."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Optional

from fastapi import APIRouter, Cookie, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from src.bw_learner.history_enrichment import (
    find_history_profile_conflicts,
    load_history_candidate_evidence,
    load_history_enrichment_evidence,
    store_history_enrichment,
)
from src.bw_learner.history_import import ChatHistoryFormatError, analyze_qq_chat_export, build_history_windows
from src.bw_learner.history_learning import (
    DEPTH_WINDOW_BUDGETS,
    ChatHistoryLearner,
    HistoryLearningCancelled,
    group_chat_id,
    history_candidates_from_json,
    store_history_candidates,
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
MAX_PARTICIPANT_PREVIEW = 30
MAX_PARTICIPANT_SELECTION_OVERRIDES = 200
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


class ChatHistoryParticipantScopeRequest(BaseModel):
    mode: Literal["all", "custom"] = "all"
    included_ids: list[str] = Field(default_factory=list, max_length=MAX_PARTICIPANT_SELECTION_OVERRIDES)
    excluded_ids: list[str] = Field(default_factory=list, max_length=MAX_PARTICIPANT_SELECTION_OVERRIDES)


class ChatHistoryImportStartRequest(BaseModel):
    depth: Literal["fast", "balanced", "deep", "full"] = "balanced"
    participant_ids: list[str] = Field(default_factory=list, max_length=MAX_PARTICIPANT_SELECTION_OVERRIDES)
    participant_scope: ChatHistoryParticipantScopeRequest | None = None
    extract_memories: bool = False
    update_profiles: bool = False


class ChatHistoryImportDeleteResponse(BaseModel):
    success: bool
    message: str


class ChatHistoryParticipantPagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class ChatHistoryParticipantListResponse(BaseModel):
    data: list[ImportedParticipantResponse]
    pagination: ChatHistoryParticipantPagination


class ChatHistoryProfileDecisionRequest(BaseModel):
    decisions: dict[str, Literal["keep_existing", "apply_imported"]] = Field(
        default_factory=dict,
        max_length=100,
    )


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
    participants = analysis.get("participants", [])
    if isinstance(participants, list):
        analysis["participant_count"] = int(analysis.get("participant_count") or len(participants))
        analysis["participants"] = participants[:MAX_PARTICIPANT_PREVIEW]
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
    payload["estimated_model_call_note"] = (
        "每个自然窗口 1 次提取、最后 1 次跨窗口合并；若窗口边界未结束，可能追加 1 次续接提取。"
    )
    return payload


def _resolve_participant_scope(
    request_body: ChatHistoryImportStartRequest,
    participants: list[Any],
) -> dict[str, Any]:
    human_ids = {
        str(participant.get("source_id"))
        for participant in participants
        if isinstance(participant, dict) and not participant.get("is_bot") and participant.get("source_id")
    }
    requested = request_body.participant_scope
    if requested is None:
        legacy_ids = list(dict.fromkeys(item.strip() for item in request_body.participant_ids if item.strip()))
        mode = "custom" if legacy_ids else "all"
        included_ids = legacy_ids
        excluded_ids: list[str] = []
    else:
        mode = requested.mode
        included_ids = list(dict.fromkeys(item.strip() for item in requested.included_ids if item.strip()))
        excluded_ids = list(dict.fromkeys(item.strip() for item in requested.excluded_ids if item.strip()))

    if mode == "all":
        if included_ids:
            raise HTTPException(status_code=422, detail="全部成员模式不能同时提交包含列表")
        unknown = set(excluded_ids) - human_ids
        if unknown:
            raise HTTPException(status_code=422, detail="排除的参与者不在聊天记录中")
        if human_ids and len(excluded_ids) >= len(human_ids):
            raise HTTPException(status_code=422, detail="至少保留一名参与学习的成员")
        return {"mode": "all", "excluded_ids": excluded_ids}

    if excluded_ids:
        raise HTTPException(status_code=422, detail="自定义成员模式不能同时提交排除列表")
    unknown = set(included_ids) - human_ids
    if unknown:
        raise HTTPException(status_code=422, detail="选择的参与者不在聊天记录中")
    if not included_ids:
        raise HTTPException(status_code=422, detail="自定义成员模式至少选择一名成员")
    return {"mode": "custom", "included_ids": included_ids}


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


@router.get("/{import_id}/participants", response_model=ChatHistoryParticipantListResponse)
async def list_chat_history_participants(
    import_id: str,
    query: Annotated[str, Query(max_length=100)] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> ChatHistoryParticipantListResponse:
    verify_auth_token(maibot_session, authorization)
    task = _get_task_or_404(import_id)
    analysis = _load_json_object(task.analysis_json)
    raw_participants = analysis.get("participants", [])
    participants = (
        [item for item in raw_participants if isinstance(item, dict)] if isinstance(raw_participants, list) else []
    )
    normalized_query = query.casefold().strip()
    if normalized_query:
        participants = [
            participant
            for participant in participants
            if normalized_query
            in " ".join(str(participant.get(key) or "").casefold() for key in ("source_id", "name", "card"))
        ]
    total_items = len(participants)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    if page > total_pages and total_items:
        raise HTTPException(status_code=422, detail="参与者页码超出范围")
    start = (page - 1) * page_size
    data = [ImportedParticipantResponse.model_validate(item) for item in participants[start : start + page_size]]
    return ChatHistoryParticipantListResponse(
        data=data,
        pagination=ChatHistoryParticipantPagination(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        ),
    )


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


async def _commit_learning_result(
    *,
    import_id: str,
    task: ChatHistoryImportTask,
    normalized_path: Path,
    result_payload: dict[str, Any],
    profile_decisions: dict[str, str] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Write a reviewed result and then atomically advance the task state."""

    options = _load_json_object(task.options_json)
    candidates = history_candidates_from_json(result_payload.get("candidates"))
    evidence = await asyncio.to_thread(load_history_candidate_evidence, normalized_path, candidates)
    if should_cancel and should_cancel():
        raise HistoryLearningCancelled("聊天记录学习已取消")
    store_result = store_history_candidates(task.chat_id or "", candidates, evidence)
    result_payload["store_result"] = {
        "created": store_result.created,
        "updated": store_result.updated,
    }
    result_payload["enrichment_store_result"] = None
    if options.get("extract_memories") is True or options.get("update_profiles") is True:
        enrichment_result = await store_history_enrichment(
            import_id=import_id,
            chat_id=task.chat_id or "",
            group_id=task.group_id or "",
            chat_name=task.chat_name or task.group_id or "群聊",
            candidates=candidates,
            evidence=evidence,
            extract_memories=options.get("extract_memories") is True,
            update_profiles=options.get("update_profiles") is True,
            profile_decisions=profile_decisions,
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
    return result_payload


async def _run_learning(import_id: str) -> None:
    task = _get_task_or_404(import_id)
    normalized_path = _task_dir(import_id) / "normalized.jsonl"
    options = _load_json_object(task.options_json)
    extract_memories = options.get("extract_memories") is True
    update_profiles = options.get("update_profiles") is True
    participant_scope = options.get("participant_scope")
    participant_scope = participant_scope if isinstance(participant_scope, dict) else {}
    if participant_scope.get("mode") == "custom":
        eligible_sender_ids = participant_scope.get("included_ids") or options.get("participant_ids") or None
        excluded_sender_ids = None
    else:
        eligible_sender_ids = (options.get("participant_ids") or None) if not participant_scope else None
        excluded_sender_ids = participant_scope.get("excluded_ids") or None

    def should_cancel() -> bool:
        current = ChatHistoryImportTask.get_or_none(ChatHistoryImportTask.import_id == import_id)
        return current is None or bool(current.cancel_requested)

    try:
        result = await ChatHistoryLearner().learn(
            normalized_path,
            chat_id=task.chat_id or "",
            chat_name=task.chat_name or task.group_id or "群聊",
            depth=str(options.get("depth") or "balanced"),
            eligible_sender_ids=eligible_sender_ids,
            excluded_sender_ids=excluded_sender_ids,
            store=False,
            progress=lambda stage, current, total: _update_progress(import_id, stage, current, total),
            should_cancel=should_cancel,
            extract_memories=extract_memories,
            update_profiles=update_profiles,
        )
        result_payload = result.to_json()
        result_payload["enrichment_store_result"] = None
        if update_profiles and result.candidates.profiles:
            profile_evidence = await asyncio.to_thread(
                load_history_enrichment_evidence,
                normalized_path,
                result.candidates,
            )
            conflicts = find_history_profile_conflicts(
                candidates=result.candidates,
                evidence=profile_evidence,
                group_id=task.group_id or "",
                chat_name=task.chat_name or task.group_id or "群聊",
            )
            if conflicts:
                result_payload["profile_review"] = {"conflicts": conflicts, "decisions": None}
                _write_result(import_id, result_payload)
                now = time.time()
                ChatHistoryImportTask.update(
                    status="awaiting_profile_review",
                    result_json=json.dumps(result_payload, ensure_ascii=False, separators=(",", ":")),
                    progress_stage="awaiting_profile_review",
                    progress_current=0,
                    progress_total=1,
                    normalized_path=str(normalized_path),
                    updated_at=now,
                ).where(ChatHistoryImportTask.import_id == import_id).execute()
                return
        await _commit_learning_result(
            import_id=import_id,
            task=task,
            normalized_path=normalized_path,
            result_payload=result_payload,
            should_cancel=should_cancel,
        )
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


async def _run_profile_decisions(import_id: str) -> None:
    task = _get_task_or_404(import_id)
    normalized_path = _task_dir(import_id) / "normalized.jsonl"
    result_payload = _load_json_object(task.result_json)
    review = result_payload.get("profile_review")
    decisions = review.get("decisions") if isinstance(review, dict) else None

    def should_cancel() -> bool:
        current = ChatHistoryImportTask.get_or_none(ChatHistoryImportTask.import_id == import_id)
        return current is None or bool(current.cancel_requested)

    try:
        if not isinstance(decisions, dict):
            raise ValueError("画像决策数据无效")
        await _commit_learning_result(
            import_id=import_id,
            task=task,
            normalized_path=normalized_path,
            result_payload=result_payload,
            profile_decisions={str(key): str(value) for key, value in decisions.items()},
            should_cancel=should_cancel,
        )
    except asyncio.CancelledError:
        _mark_task_cancelled(import_id, normalized_path)
        raise
    except HistoryLearningCancelled:
        _mark_task_cancelled(import_id, normalized_path)
    except Exception as error:
        log_exception_type(logger, "聊天记录画像决策写入失败", error, import_id=import_id)
        _cleanup_task_files(import_id, remove_directory=False)
        now = time.time()
        ChatHistoryImportTask.update(
            status="failed",
            progress_stage="failed",
            error_message="画像决策写入失败，请检查服务日志",
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
    participants = analysis.get("participants", [])
    participants = participants if isinstance(participants, list) else []
    participant_scope = _resolve_participant_scope(request_body, participants)
    participant_ids = participant_scope.get("included_ids", [])

    now = time.time()
    options = {
        "depth": request_body.depth,
        "participant_ids": participant_ids,
        "participant_scope": participant_scope,
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


@router.post("/{import_id}/profile-decisions", response_model=ChatHistoryImportResponse)
async def submit_chat_history_profile_decisions(
    import_id: str,
    request_body: ChatHistoryProfileDecisionRequest,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> ChatHistoryImportResponse:
    verify_auth_token(maibot_session, authorization)
    task = _get_task_or_404(import_id)
    if task.status != "awaiting_profile_review":
        raise HTTPException(status_code=409, detail="当前任务不需要画像确认")
    if _active_local_import_count() >= MAX_CONCURRENT_IMPORTS:
        raise HTTPException(status_code=409, detail="已有聊天记录学习任务正在运行")

    result_payload = _load_json_object(task.result_json)
    review = result_payload.get("profile_review")
    conflicts = review.get("conflicts") if isinstance(review, dict) else None
    if not isinstance(conflicts, list) or not conflicts:
        raise HTTPException(status_code=409, detail="任务缺少可确认的画像冲突")
    expected_ids = {
        str(conflict.get("profile_id"))
        for conflict in conflicts
        if isinstance(conflict, dict) and conflict.get("profile_id")
    }
    if not expected_ids or set(request_body.decisions) != expected_ids:
        raise HTTPException(status_code=422, detail="必须为每个画像冲突选择处理方式")

    result_payload["profile_review"] = {
        "conflicts": conflicts,
        "decisions": dict(request_body.decisions),
    }
    now = time.time()
    updated = (
        ChatHistoryImportTask.update(
            status="running",
            result_json=json.dumps(result_payload, ensure_ascii=False, separators=(",", ":")),
            progress_stage="storing",
            progress_current=0,
            progress_total=1,
            cancel_requested=False,
            updated_at=now,
        )
        .where(
            (ChatHistoryImportTask.import_id == import_id) & (ChatHistoryImportTask.status == "awaiting_profile_review")
        )
        .execute()
    )
    if updated != 1:
        raise HTTPException(status_code=409, detail="画像决策已由其他请求提交")
    background = asyncio.create_task(_run_profile_decisions(import_id), name=f"chat-history-profile-{import_id}")
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
