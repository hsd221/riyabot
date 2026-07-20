"""模型请求追踪的只读 WebUI API。"""

import json
import math
from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.common.database.database_model import LLMRequestTrace, LLMRequestTraceMedia
from src.common.logger import get_logger
from src.llm_models.request_trace import (
    TRACE_MEDIA_ROOT,
    get_trace_media_spec,
    is_valid_trace_media_id,
    resolve_trace_media_path,
)
from src.webui.auth import verify_auth_token_from_cookie_or_header
from src.webui.error_utils import internal_server_error

logger = get_logger("webui.model_trace")


def _set_private_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(
    prefix="/model-traces",
    tags=["model-traces"],
    dependencies=[Depends(_set_private_no_store)],
)


def require_auth(
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> bool:
    return verify_auth_token_from_cookie_or_header(maibot_session, authorization)


class ModelTraceSummary(BaseModel):
    id: int
    request_type: str
    operation: Literal["response", "embedding", "audio"]
    model_name: str
    model_identifier: str
    provider_name: str
    attempt: int
    status: Literal["running", "success", "error"]
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    request_preview: str
    response_preview: str
    error_type: str | None
    error_message: str | None
    status_code: int | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ModelTracePagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class ModelTraceFilterOptions(BaseModel):
    request_types: list[str]
    models: list[str]


class ModelTraceListResponse(BaseModel):
    data: list[ModelTraceSummary]
    pagination: ModelTracePagination
    filter_options: ModelTraceFilterOptions


class ModelTraceImageMediaSummary(BaseModel):
    media_id: str = Field(max_length=64, pattern=r"^image-[1-9]\d*$")
    kind: Literal["image"]
    format: Literal["png", "jpeg", "gif", "webp"]
    mime_type: Literal["image/png", "image/jpeg", "image/gif", "image/webp"]
    size_bytes: int = Field(ge=0)


class ModelTraceAudioMediaSummary(BaseModel):
    media_id: str = Field(max_length=64, pattern=r"^audio-[1-9]\d*$")
    kind: Literal["audio"]
    format: Literal["wav", "mp3", "ogg", "flac", "mp4", "webm", "amr"]
    mime_type: Literal["audio/wav", "audio/mpeg", "audio/ogg", "audio/flac", "audio/mp4", "audio/webm", "audio/amr"]
    size_bytes: int = Field(ge=0)


ModelTraceMediaSummary = Annotated[
    ModelTraceImageMediaSummary | ModelTraceAudioMediaSummary,
    Field(discriminator="kind"),
]


class ModelTraceDetail(ModelTraceSummary):
    request_payload: Any
    response_payload: Any | None
    media: list[ModelTraceMediaSummary]


_SUMMARY_FIELDS = (
    LLMRequestTrace.id,
    LLMRequestTrace.request_type,
    LLMRequestTrace.operation,
    LLMRequestTrace.model_name,
    LLMRequestTrace.model_identifier,
    LLMRequestTrace.provider_name,
    LLMRequestTrace.attempt,
    LLMRequestTrace.status,
    LLMRequestTrace.started_at,
    LLMRequestTrace.completed_at,
    LLMRequestTrace.duration_ms,
    LLMRequestTrace.request_preview,
    LLMRequestTrace.response_preview,
    LLMRequestTrace.error_type,
    LLMRequestTrace.error_message,
    LLMRequestTrace.status_code,
    LLMRequestTrace.prompt_tokens,
    LLMRequestTrace.completion_tokens,
    LLMRequestTrace.total_tokens,
)


def _summary(trace: LLMRequestTrace) -> ModelTraceSummary:
    return ModelTraceSummary(
        id=trace.id,
        request_type=trace.request_type,
        operation=trace.operation,
        model_name=trace.model_name,
        model_identifier=trace.model_identifier,
        provider_name=trace.provider_name,
        attempt=trace.attempt,
        status=trace.status,
        started_at=trace.started_at,
        completed_at=trace.completed_at,
        duration_ms=trace.duration_ms,
        request_preview=trace.request_preview,
        response_preview=trace.response_preview,
        error_type=trace.error_type,
        error_message=trace.error_message,
        status_code=trace.status_code,
        prompt_tokens=trace.prompt_tokens,
        completion_tokens=trace.completion_tokens,
        total_tokens=trace.total_tokens,
    )


def _decode_payload(payload: str | None) -> Any | None:
    if payload is None:
        return None
    try:
        return json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return {"unparsed": True, "content": payload}


def _media_summary(media: LLMRequestTraceMedia) -> ModelTraceMediaSummary:
    mime_type, _extension = get_trace_media_spec(media.kind, media.format)
    summary = {
        "media_id": media.media_id,
        "kind": media.kind,
        "format": media.format,
        "mime_type": mime_type,
        "size_bytes": media.size_bytes,
    }
    if media.kind == "image":
        return ModelTraceImageMediaSummary(**summary)
    if media.kind == "audio":
        return ModelTraceAudioMediaSummary(**summary)
    raise ValueError("unsupported trace media kind")


def _distinct_values(field) -> list[str]:
    return [
        value for (value,) in LLMRequestTrace.select(field).where(field != "").distinct().order_by(field.asc()).tuples()
    ]


@router.get("", response_model=ModelTraceListResponse)
async def list_model_traces(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    status: Literal["running", "success", "error"] | None = Query(None),
    request_type: str | None = Query(None, max_length=120),
    model: str | None = Query(None, max_length=120),
    search: str | None = Query(None, max_length=200),
    _auth: bool = Depends(require_auth),
) -> ModelTraceListResponse:
    try:
        query = LLMRequestTrace.select(*_SUMMARY_FIELDS)
        if status:
            query = query.where(LLMRequestTrace.status == status)
        if request_type:
            query = query.where(LLMRequestTrace.request_type == request_type)
        if model:
            query = query.where(LLMRequestTrace.model_name == model)
        if search:
            query = query.where(
                LLMRequestTrace.request_preview.contains(search)
                | LLMRequestTrace.response_preview.contains(search)
                | LLMRequestTrace.request_type.contains(search)
                | LLMRequestTrace.model_name.contains(search)
                | LLMRequestTrace.provider_name.contains(search)
                | LLMRequestTrace.error_message.contains(search)
            )

        total_items = query.count()
        traces = query.order_by(LLMRequestTrace.started_at.desc(), LLMRequestTrace.id.desc()).paginate(page, page_size)
        return ModelTraceListResponse(
            data=[_summary(trace) for trace in traces],
            pagination=ModelTracePagination(
                page=page,
                page_size=page_size,
                total_items=total_items,
                total_pages=math.ceil(total_items / page_size) if total_items else 0,
            ),
            filter_options=ModelTraceFilterOptions(
                request_types=_distinct_values(LLMRequestTrace.request_type),
                models=_distinct_values(LLMRequestTrace.model_name),
            ),
        )
    except Exception as exc:
        raise internal_server_error(logger, "获取模型请求追踪列表失败", exc) from None


@router.get("/{trace_id}", response_model=ModelTraceDetail)
async def get_model_trace(
    trace_id: int,
    _auth: bool = Depends(require_auth),
) -> ModelTraceDetail:
    try:
        trace = LLMRequestTrace.get_or_none(LLMRequestTrace.id == trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="模型请求追踪不存在")
        return ModelTraceDetail(
            **_summary(trace).model_dump(),
            request_payload=_decode_payload(trace.request_payload),
            response_payload=_decode_payload(trace.response_payload),
            media=[
                _media_summary(media)
                for media in LLMRequestTraceMedia.select()
                .where(LLMRequestTraceMedia.trace_id == trace_id)
                .order_by(LLMRequestTraceMedia.id.asc())
            ],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise internal_server_error(logger, "获取模型请求追踪详情失败", exc) from None


@router.get("/{trace_id}/media/{media_id}", response_class=FileResponse)
async def get_model_trace_media(
    trace_id: int,
    media_id: str,
    _auth: bool = Depends(require_auth),
) -> FileResponse:
    if trace_id < 1 or not is_valid_trace_media_id(media_id):
        raise HTTPException(status_code=404, detail="模型请求媒体不存在")
    try:
        media = LLMRequestTraceMedia.get_or_none(
            (LLMRequestTraceMedia.trace_id == trace_id) & (LLMRequestTraceMedia.media_id == media_id)
        )
        if media is None:
            raise HTTPException(status_code=404, detail="模型请求媒体不存在")
        try:
            media_path = resolve_trace_media_path(media, media_root=TRACE_MEDIA_ROOT)
        except (TypeError, ValueError):
            raise HTTPException(status_code=404, detail="模型请求媒体不存在") from None
        if not media_path.is_file() or media_path.stat().st_size != media.size_bytes:
            raise HTTPException(status_code=404, detail="模型请求媒体不存在")
        mime_type, _extension = get_trace_media_spec(media.kind, media.format)
        return FileResponse(
            media_path,
            media_type=mime_type,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise internal_server_error(logger, "获取模型请求追踪媒体失败", exc) from None
