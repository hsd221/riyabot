"""Authenticated WebUI endpoints for update discovery and task creation."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from src.common.background_tasks import spawn_background_task
from src.common.logger import get_logger
from src.config.config import PROJECT_ROOT
from src.update_system.models import FULL_SHA_RE, PendingUpdate, UpdateChannel
from src.update_system.runner import UPDATE_EXIT_CODE, PendingUpdateStore
from src.update_system.service import get_update_service
from src.webui.auth import require_same_site_request, verify_auth_token_from_cookie_or_header
from src.webui.config_routes import read_bot_config_section, save_bot_config_section
from src.webui.error_utils import internal_server_error


router = APIRouter(tags=["updates"])
logger = get_logger("webui_updates")
_task_lock = asyncio.Lock()
_pending_update_store: PendingUpdateStore | None = None


def require_auth(
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> bool:
    return verify_auth_token_from_cookie_or_header(maibot_session, authorization)


class UpdatePreferencesRequest(BaseModel):
    channel: UpdateChannel


class UpdatePreferencesResponse(BaseModel):
    channel: UpdateChannel


class CreateUpdateTaskRequest(BaseModel):
    expected_target_revision: str = Field(pattern=FULL_SHA_RE.pattern)


class CreateUpdateTaskResponse(BaseModel):
    accepted: bool
    target_revision: str
    message: str


class UpdateResultPayload(BaseModel):
    success: bool
    code: str
    message: str
    completed_at: str
    target_revision: Optional[str] = None


class UpdateResultResponse(BaseModel):
    last_result: Optional[UpdateResultPayload] = None


def get_pending_update_store() -> PendingUpdateStore:
    global _pending_update_store
    if _pending_update_store is None:
        _pending_update_store = PendingUpdateStore(Path(PROJECT_ROOT) / "data" / "update")
    return _pending_update_store


def _configured_channel() -> UpdateChannel:
    section = read_bot_config_section("update")
    if not isinstance(section, dict):
        raise RuntimeError("update config section is invalid")
    return UpdateChannel(section.get("channel", UpdateChannel.STABLE.value))


@router.get("/updates/status")
async def get_update_status(force: bool = False, _auth: bool = Depends(require_auth)) -> dict:
    try:
        channel = _configured_channel()
        status = await get_update_service().check(channel, force=force)
        store = get_pending_update_store()
        payload = status.to_dict()
        payload["update_pending"] = store.read_pending() is not None
        payload["last_result"] = store.read_result()
        return payload
    except HTTPException:
        raise
    except Exception as exc:
        raise internal_server_error(logger, "更新状态读取失败", exc, detail="检查更新失败") from None


@router.patch("/updates/preferences", response_model=UpdatePreferencesResponse)
async def update_preferences(
    request: UpdatePreferencesRequest,
    _same_site: None = Depends(require_same_site_request),
    _auth: bool = Depends(require_auth),
) -> UpdatePreferencesResponse:
    try:
        save_bot_config_section("update", {"channel": request.channel.value})
        logger.info("更新频道偏好已保存", event_code="update.preference.saved", channel=request.channel.value)
        return UpdatePreferencesResponse(channel=request.channel)
    except HTTPException:
        raise
    except Exception as exc:
        raise internal_server_error(logger, "更新频道保存失败", exc, detail="保存更新频道失败") from None


@router.get("/update-tasks/result", response_model=UpdateResultResponse)
async def get_update_result(_auth: bool = Depends(require_auth)) -> UpdateResultResponse:
    try:
        payload = get_pending_update_store().read_result()
        result = UpdateResultPayload.model_validate(payload) if payload is not None else None
        return UpdateResultResponse(last_result=result)
    except HTTPException:
        raise
    except Exception as exc:
        raise internal_server_error(logger, "更新结果读取失败", exc, detail="读取更新结果失败") from None


@router.post("/update-tasks", response_model=CreateUpdateTaskResponse, status_code=202)
async def create_update_task(
    request: CreateUpdateTaskRequest,
    _same_site: None = Depends(require_same_site_request),
    _auth: bool = Depends(require_auth),
) -> CreateUpdateTaskResponse:
    async with _task_lock:
        try:
            channel = _configured_channel()
            status = await get_update_service().check(channel, force=True)
            if not status.update_available or status.target is None:
                raise HTTPException(status_code=409, detail="当前已经是所选频道的最新版本")
            if status.target.revision != request.expected_target_revision:
                raise HTTPException(status_code=409, detail="远端目标已变化，请重新检查并确认更新")
            if not status.can_apply or status.current.revision is None:
                raise HTTPException(status_code=409, detail=status.block_message or "当前安装无法自动更新")

            store = get_pending_update_store()
            if store.read_pending() is not None:
                raise HTTPException(status_code=409, detail="已有更新任务等待执行")
            plan = PendingUpdate(
                channel=channel,
                current_revision=status.current.revision,
                target_revision=status.target.revision,
                target_ref=status.target.ref,
                requested_at=datetime.now(timezone.utc).isoformat(),
            )
            store.clear_result()
            store.write_pending(plan)

            async def delayed_update_exit() -> None:
                await asyncio.sleep(0.5)
                logger.info(
                    "WebUI 请求执行更新",
                    event_code="update.task.runner_requested",
                    channel=channel.value,
                    target_revision=status.target.revision,
                )
                os._exit(UPDATE_EXIT_CODE)

            try:
                spawn_background_task(delayed_update_exit(), name="webui-delayed-update-exit")
            except Exception:
                store.clear_pending()
                raise
            return CreateUpdateTaskResponse(
                accepted=True,
                target_revision=status.target.revision,
                message="更新任务已创建，主程序即将重启",
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise internal_server_error(logger, "更新任务创建失败", exc, detail="创建更新任务失败") from None
