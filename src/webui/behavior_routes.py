"""行为学习管理 API 路由"""

import json
import time
from typing import Optional

from fastapi import APIRouter, Cookie, Header, HTTPException, Query
from peewee import Case
from pydantic import BaseModel, Field

from src.bw_learner.behavior_store import (
    LEARNING_OBSERVED,
    VALID_ACTOR_TYPES,
    VALID_LEARNING_TYPES,
    normalize_source_ids,
)
from src.common.database.database_model import BehaviorPattern, ChatStreams
from src.common.logger import get_logger

from .auth import verify_auth_token_from_cookie_or_header

logger = get_logger("webui.behavior")

router = APIRouter(prefix="/behavior", tags=["Behavior"])


class BehaviorResponse(BaseModel):
    """行为模式响应"""

    id: int
    chat_id: str
    actor_type: str
    learning_type: str
    action: str
    outcome: str
    source_text: Optional[str] = None
    source_ids: list[str]
    count: int
    score: float
    enabled: bool
    selected_count: int
    last_selected_time: Optional[float] = None
    last_active_time: float
    create_date: Optional[float] = None


class BehaviorListResponse(BaseModel):
    """行为模式列表响应"""

    success: bool
    total: int
    page: int
    page_size: int
    data: list[BehaviorResponse]


class BehaviorDetailResponse(BaseModel):
    """行为模式详情响应"""

    success: bool
    data: BehaviorResponse


class BehaviorCreateRequest(BaseModel):
    """行为模式创建请求"""

    chat_id: str
    actor_type: str = "other_user"
    learning_type: str = LEARNING_OBSERVED
    action: str
    outcome: str
    source_text: Optional[str] = ""
    source_ids: list[str] = Field(default_factory=list)
    count: int = Field(1, ge=1)
    score: float = Field(1.0, ge=0.0, le=5.0)
    enabled: bool = True


class BehaviorUpdateRequest(BaseModel):
    """行为模式更新请求"""

    chat_id: Optional[str] = None
    actor_type: Optional[str] = None
    learning_type: Optional[str] = None
    action: Optional[str] = None
    outcome: Optional[str] = None
    source_text: Optional[str] = None
    source_ids: Optional[list[str]] = None
    count: Optional[int] = Field(None, ge=0)
    score: Optional[float] = Field(None, ge=0.0, le=5.0)
    enabled: Optional[bool] = None


class BehaviorUpdateResponse(BaseModel):
    """行为模式更新响应"""

    success: bool
    message: str
    data: Optional[BehaviorResponse] = None


class BehaviorCreateResponse(BaseModel):
    """行为模式创建响应"""

    success: bool
    message: str
    data: BehaviorResponse


class BehaviorDeleteResponse(BaseModel):
    """行为模式删除响应"""

    success: bool
    message: str


class BehaviorStats(BaseModel):
    """行为模式统计"""

    total: int
    enabled: int
    disabled: int
    recent_7days: int
    chat_count: int
    top_chats: dict[str, int]
    actor_type_counts: dict[str, int]
    learning_type_counts: dict[str, int]


class BehaviorStatsResponse(BaseModel):
    """行为模式统计响应"""

    success: bool
    data: BehaviorStats


class ChatInfo(BaseModel):
    """聊天信息"""

    chat_id: str
    chat_name: str
    platform: Optional[str] = None
    is_group: bool = False


class ChatListResponse(BaseModel):
    """聊天列表响应"""

    success: bool
    data: list[ChatInfo]


class BatchDeleteRequest(BaseModel):
    """批量删除请求"""

    ids: list[int]


def verify_auth_token(
    maibot_session: Optional[str] = None,
    authorization: Optional[str] = None,
) -> bool:
    """验证认证 Token，支持 Cookie 和 Header。"""
    return verify_auth_token_from_cookie_or_header(maibot_session, authorization)


def behavior_to_response(pattern: BehaviorPattern) -> BehaviorResponse:
    """将 BehaviorPattern 模型转换为响应对象。"""
    return BehaviorResponse(
        id=pattern.id,
        chat_id=pattern.chat_id,
        actor_type=pattern.actor_type,
        learning_type=pattern.learning_type,
        action=pattern.action,
        outcome=pattern.outcome,
        source_text=pattern.source_text,
        source_ids=normalize_source_ids(pattern.source_ids),
        count=pattern.count or 0,
        score=float(pattern.score or 0.0),
        enabled=bool(pattern.enabled),
        selected_count=pattern.selected_count or 0,
        last_selected_time=pattern.last_selected_time,
        last_active_time=pattern.last_active_time,
        create_date=pattern.create_date,
    )


def get_chat_names_batch(chat_ids: list[str]) -> dict[str, str]:
    """批量获取聊天名称。"""
    result = {chat_id: chat_id for chat_id in chat_ids}
    try:
        for chat_stream in ChatStreams.select().where(ChatStreams.stream_id.in_(chat_ids)):
            if chat_stream.group_name:
                result[chat_stream.stream_id] = chat_stream.group_name
            elif chat_stream.user_nickname:
                result[chat_stream.stream_id] = chat_stream.user_nickname
    except Exception as e:
        logger.warning(f"批量获取聊天名称失败: {e}")
    return result


def get_behavior_stats_data() -> dict[str, object]:
    """汇总行为模式统计，供 API 和单元测试复用。"""
    total = BehaviorPattern.select().count()
    enabled = BehaviorPattern.select().where(BehaviorPattern.enabled == True).count()  # noqa: E712
    disabled = total - enabled

    chat_stats: dict[str, int] = {}
    actor_type_counts: dict[str, int] = {}
    learning_type_counts: dict[str, int] = {}
    for pattern in BehaviorPattern.select(
        BehaviorPattern.chat_id,
        BehaviorPattern.actor_type,
        BehaviorPattern.learning_type,
    ):
        chat_stats[pattern.chat_id] = chat_stats.get(pattern.chat_id, 0) + 1
        actor_type_counts[pattern.actor_type] = actor_type_counts.get(pattern.actor_type, 0) + 1
        learning_type_counts[pattern.learning_type] = learning_type_counts.get(pattern.learning_type, 0) + 1

    seven_days_ago = time.time() - 7 * 24 * 60 * 60
    recent = (
        BehaviorPattern.select()
        .where((BehaviorPattern.create_date.is_null(False)) & (BehaviorPattern.create_date >= seven_days_ago))
        .count()
    )

    return {
        "total": total,
        "enabled": enabled,
        "disabled": disabled,
        "recent_7days": recent,
        "chat_count": len(chat_stats),
        "top_chats": dict(sorted(chat_stats.items(), key=lambda item: (-item[1], item[0]))[:10]),
        "actor_type_counts": dict(sorted(actor_type_counts.items())),
        "learning_type_counts": dict(sorted(learning_type_counts.items())),
    }


def _validate_behavior_payload(payload: dict[str, object]) -> dict[str, object]:
    """校验并清洗用户提交的行为模式字段。"""
    cleaned = dict(payload)

    for field_name in ("chat_id", "action", "outcome"):
        value = cleaned.get(field_name)
        if value is not None:
            value = str(value).strip()
            if not value:
                raise HTTPException(status_code=400, detail=f"{field_name} 不能为空")
            cleaned[field_name] = value

    actor_type = cleaned.get("actor_type")
    if actor_type is not None and actor_type not in VALID_ACTOR_TYPES:
        raise HTTPException(status_code=400, detail=f"未知的 actor_type: {actor_type}")

    learning_type = cleaned.get("learning_type")
    if learning_type is not None and learning_type not in VALID_LEARNING_TYPES:
        raise HTTPException(status_code=400, detail=f"未知的 learning_type: {learning_type}")

    if "source_text" in cleaned and cleaned["source_text"] is not None:
        cleaned["source_text"] = str(cleaned["source_text"])[-2000:]

    if "source_ids" in cleaned:
        cleaned["source_ids"] = json.dumps(normalize_source_ids(cleaned["source_ids"]), ensure_ascii=False)

    return cleaned


@router.get("/chats", response_model=ChatListResponse)
async def get_chat_list(maibot_session: Optional[str] = Cookie(None), authorization: Optional[str] = Header(None)):
    """获取所有聊天列表，用于筛选和创建行为模式。"""
    try:
        verify_auth_token(maibot_session, authorization)

        chat_list = []
        for chat_stream in ChatStreams.select():
            chat_name = chat_stream.group_name or chat_stream.user_nickname or chat_stream.stream_id
            chat_list.append(
                ChatInfo(
                    chat_id=chat_stream.stream_id,
                    chat_name=chat_name,
                    platform=chat_stream.platform,
                    is_group=bool(chat_stream.group_id),
                )
            )
        chat_list.sort(key=lambda item: item.chat_name)

        return ChatListResponse(success=True, data=chat_list)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取聊天列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取聊天列表失败: {str(e)}") from e


@router.get("/list", response_model=BehaviorListResponse)
async def get_behavior_list(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    chat_id: Optional[str] = Query(None, description="聊天ID筛选"),
    enabled: Optional[bool] = Query(None, description="启用状态筛选"),
    actor_type: Optional[str] = Query(None, description="行为主体筛选"),
    learning_type: Optional[str] = Query(None, description="学习来源筛选"),
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """获取行为模式列表。"""
    try:
        verify_auth_token(maibot_session, authorization)

        query = BehaviorPattern.select()
        if search:
            query = query.where(
                (BehaviorPattern.action.contains(search))
                | (BehaviorPattern.outcome.contains(search))
                | (BehaviorPattern.source_text.contains(search))
            )
        if chat_id:
            query = query.where(BehaviorPattern.chat_id == chat_id)
        if enabled is not None:
            query = query.where(BehaviorPattern.enabled == enabled)
        if actor_type:
            query = query.where(BehaviorPattern.actor_type == actor_type)
        if learning_type:
            query = query.where(BehaviorPattern.learning_type == learning_type)

        query = query.order_by(
            BehaviorPattern.enabled.desc(),
            Case(None, [(BehaviorPattern.last_active_time.is_null(), 1)], 0),
            BehaviorPattern.last_active_time.desc(),
        )

        total = query.count()
        behaviors = query.offset((page - 1) * page_size).limit(page_size)
        data = [behavior_to_response(pattern) for pattern in behaviors]

        return BehaviorListResponse(success=True, total=total, page=page, page_size=page_size, data=data)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取行为模式列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取行为模式列表失败: {str(e)}") from e


@router.get("/stats/summary", response_model=BehaviorStatsResponse)
async def get_behavior_stats(maibot_session: Optional[str] = Cookie(None), authorization: Optional[str] = Header(None)):
    """获取行为模式统计数据。"""
    try:
        verify_auth_token(maibot_session, authorization)
        return BehaviorStatsResponse(success=True, data=BehaviorStats(**get_behavior_stats_data()))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取行为模式统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取行为模式统计失败: {str(e)}") from e


@router.get("/{behavior_id}", response_model=BehaviorDetailResponse)
async def get_behavior_detail(
    behavior_id: int, maibot_session: Optional[str] = Cookie(None), authorization: Optional[str] = Header(None)
):
    """获取行为模式详情。"""
    try:
        verify_auth_token(maibot_session, authorization)

        pattern = BehaviorPattern.get_or_none(BehaviorPattern.id == behavior_id)
        if not pattern:
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {behavior_id} 的行为模式")

        return BehaviorDetailResponse(success=True, data=behavior_to_response(pattern))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取行为模式详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取行为模式详情失败: {str(e)}") from e


@router.post("/", response_model=BehaviorCreateResponse)
async def create_behavior(
    request: BehaviorCreateRequest,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """创建行为模式。"""
    try:
        verify_auth_token(maibot_session, authorization)

        current_time = time.time()
        create_data = _validate_behavior_payload(request.model_dump())
        create_data["last_active_time"] = current_time
        create_data["create_date"] = current_time
        create_data["selected_count"] = 0

        pattern = BehaviorPattern.create(**create_data)
        logger.info(f"行为模式已创建: ID={pattern.id}, action={pattern.action}")

        return BehaviorCreateResponse(success=True, message="行为模式创建成功", data=behavior_to_response(pattern))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"创建行为模式失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建行为模式失败: {str(e)}") from e


@router.patch("/{behavior_id}", response_model=BehaviorUpdateResponse)
async def update_behavior(
    behavior_id: int,
    request: BehaviorUpdateRequest,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """增量更新行为模式。"""
    try:
        verify_auth_token(maibot_session, authorization)

        pattern = BehaviorPattern.get_or_none(BehaviorPattern.id == behavior_id)
        if not pattern:
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {behavior_id} 的行为模式")

        update_data = _validate_behavior_payload(request.model_dump(exclude_unset=True))
        if not update_data:
            raise HTTPException(status_code=400, detail="未提供任何需要更新的字段")

        update_data["last_active_time"] = time.time()
        for field_name, value in update_data.items():
            setattr(pattern, field_name, value)
        pattern.save()

        logger.info(f"行为模式已更新: ID={behavior_id}, 字段: {list(update_data.keys())}")
        return BehaviorUpdateResponse(
            success=True,
            message=f"成功更新 {len(update_data)} 个字段",
            data=behavior_to_response(pattern),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"更新行为模式失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新行为模式失败: {str(e)}") from e


@router.delete("/{behavior_id}", response_model=BehaviorDeleteResponse)
async def delete_behavior(
    behavior_id: int, maibot_session: Optional[str] = Cookie(None), authorization: Optional[str] = Header(None)
):
    """删除行为模式。"""
    try:
        verify_auth_token(maibot_session, authorization)

        pattern = BehaviorPattern.get_or_none(BehaviorPattern.id == behavior_id)
        if not pattern:
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {behavior_id} 的行为模式")

        action = pattern.action
        pattern.delete_instance()
        logger.info(f"行为模式已删除: ID={behavior_id}, action={action}")

        return BehaviorDeleteResponse(success=True, message=f"成功删除行为模式: {action}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"删除行为模式失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除行为模式失败: {str(e)}") from e


@router.post("/batch/delete", response_model=BehaviorDeleteResponse)
async def batch_delete_behaviors(
    request: BatchDeleteRequest,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """批量删除行为模式。"""
    try:
        verify_auth_token(maibot_session, authorization)

        if not request.ids:
            raise HTTPException(status_code=400, detail="未提供要删除的行为模式ID")

        found_ids = [pattern.id for pattern in BehaviorPattern.select().where(BehaviorPattern.id.in_(request.ids))]
        deleted_count = BehaviorPattern.delete().where(BehaviorPattern.id.in_(found_ids)).execute()
        logger.info(f"批量删除了 {deleted_count} 个行为模式")

        return BehaviorDeleteResponse(success=True, message=f"成功删除 {deleted_count} 个行为模式")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"批量删除行为模式失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量删除行为模式失败: {str(e)}") from e
