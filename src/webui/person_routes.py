"""人物信息管理 API 路由

# 用户画像功能已迁移 — 路由保留占位
未来的用户画像系统会替代此模块。
"""

from fastapi import APIRouter, HTTPException, Header, Query, Cookie
from pydantic import BaseModel
from typing import Optional, List, Dict
from src.common.logger import get_logger
from .auth import verify_auth_token_from_cookie_or_header
import json

logger = get_logger("webui.person")

# 创建路由器
router = APIRouter(prefix="/person", tags=["Person"])


class PersonInfoResponse(BaseModel):
    """人物信息响应"""

    id: int
    is_known: bool
    person_id: str
    person_name: Optional[str]
    name_reason: Optional[str]
    platform: str
    user_id: str
    nickname: Optional[str]
    group_nick_name: Optional[List[Dict[str, str]]]  # 解析后的 JSON
    memory_points: Optional[str]
    know_times: Optional[float]
    know_since: Optional[float]
    last_know: Optional[float]


class PersonListResponse(BaseModel):
    """人物列表响应"""

    success: bool
    total: int
    page: int
    page_size: int
    data: List[PersonInfoResponse]


class PersonDetailResponse(BaseModel):
    """人物详情响应"""

    success: bool
    data: PersonInfoResponse


class PersonUpdateRequest(BaseModel):
    """人物信息更新请求"""

    person_name: Optional[str] = None
    name_reason: Optional[str] = None
    nickname: Optional[str] = None
    memory_points: Optional[str] = None
    is_known: Optional[bool] = None


class PersonUpdateResponse(BaseModel):
    """人物信息更新响应"""

    success: bool
    message: str
    data: Optional[PersonInfoResponse] = None


class PersonDeleteResponse(BaseModel):
    """人物删除响应"""

    success: bool
    message: str


class BatchDeleteRequest(BaseModel):
    """批量删除请求"""

    person_ids: List[str]


class BatchDeleteResponse(BaseModel):
    """批量删除响应"""

    success: bool
    message: str
    deleted_count: int
    failed_count: int
    failed_ids: List[str] = []


def verify_auth_token(
    maibot_session: Optional[str] = None,
    authorization: Optional[str] = None,
) -> bool:
    """验证认证 Token，支持 Cookie 和 Header"""
    return verify_auth_token_from_cookie_or_header(maibot_session, authorization)


def parse_group_nick_name(group_nick_name_str: Optional[str]) -> Optional[List[Dict[str, str]]]:
    """解析群昵称 JSON 字符串"""
    if not group_nick_name_str:
        return None
    try:
        return json.loads(group_nick_name_str)
    except (json.JSONDecodeError, TypeError):
        return None


@router.get("/list", response_model=PersonListResponse)
async def get_person_list(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    is_known: Optional[bool] = Query(None, description="是否已认识筛选"),
    platform: Optional[str] = Query(None, description="平台筛选"),
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """获取人物信息列表（用户画像功能已迁移，返回空列表）"""
    try:
        verify_auth_token(maibot_session, authorization)
        logger.info("人物列表查询：用户画像功能已迁移，返回空列表")
        return PersonListResponse(success=True, total=0, page=page, page_size=page_size, data=[])
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取人物列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取人物列表失败: {str(e)}") from e


@router.get("/{person_id}", response_model=PersonDetailResponse)
async def get_person_detail(
    person_id: str, maibot_session: Optional[str] = Cookie(None), authorization: Optional[str] = Header(None)
):
    """获取人物详细信息（用户画像功能已迁移）"""
    try:
        verify_auth_token(maibot_session, authorization)
        raise HTTPException(status_code=404, detail="用户画像功能已迁移")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取人物详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取人物详情失败: {str(e)}") from e


@router.patch("/{person_id}", response_model=PersonUpdateResponse)
async def update_person(
    person_id: str,
    request: PersonUpdateRequest,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """更新人物信息（用户画像功能已迁移，操作不可用）"""
    try:
        verify_auth_token(maibot_session, authorization)
        raise HTTPException(status_code=400, detail="操作不可用：用户画像功能已迁移")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"更新人物信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新人物信息失败: {str(e)}") from e


@router.delete("/{person_id}", response_model=PersonDeleteResponse)
async def delete_person(
    person_id: str, maibot_session: Optional[str] = Cookie(None), authorization: Optional[str] = Header(None)
):
    """删除人物信息（用户画像功能已迁移，操作不可用）"""
    try:
        verify_auth_token(maibot_session, authorization)
        raise HTTPException(status_code=400, detail="操作不可用：用户画像功能已迁移")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"删除人物信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除人物信息失败: {str(e)}") from e


@router.get("/stats/summary")
async def get_person_stats(maibot_session: Optional[str] = Cookie(None), authorization: Optional[str] = Header(None)):
    """获取人物信息统计数据（用户画像功能已迁移，返回空数据）"""
    try:
        verify_auth_token(maibot_session, authorization)
        return {"success": True, "data": {"total": 0, "known": 0, "unknown": 0, "platforms": {}}}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取统计数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计数据失败: {str(e)}") from e


@router.post("/batch/delete", response_model=BatchDeleteResponse)
async def batch_delete_persons(
    request: BatchDeleteRequest,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """批量删除人物信息（用户画像功能已迁移，操作不可用）"""
    try:
        verify_auth_token(maibot_session, authorization)
        return BatchDeleteResponse(
            success=True,
            message="操作不可用：用户画像功能已迁移",
            deleted_count=0,
            failed_count=0,
            failed_ids=[],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"批量删除人物信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量删除失败: {str(e)}") from e
