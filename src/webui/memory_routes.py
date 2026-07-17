"""记忆系统 API 路由"""

import datetime
import json
from typing import Any, Optional

from fastapi import APIRouter, Cookie, Header, HTTPException, Query, Depends
from pydantic import BaseModel

from src.common.logger import get_logger
from src.config.config import global_config
from src.memory.schema import (
    MemoryAtom,
    DreamRun,
    InsightPool,
    NoisePool,
    RawMessageArchive,
    configure_memory_database,
    initialize_database,
    memory_db,
)
from src.webui.error_utils import internal_server_error
from .auth import verify_auth_token_from_cookie_or_header

logger = get_logger("webui.memory")

router = APIRouter(prefix="/memory", tags=["Memory"])
_memory_db_ready_path: Optional[str] = None


def require_auth(
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> bool:
    """认证依赖：验证用户是否已登录"""
    return verify_auth_token_from_cookie_or_header(maibot_session, authorization)


def _ensure_memory_database_ready() -> None:
    """确保记忆数据库表结构已初始化，兼容 WebUI 单独访问场景。"""
    global _memory_db_ready_path

    sqlite_path = getattr(global_config.memory, "sqlite_path", None)
    if sqlite_path:
        configure_memory_database(sqlite_path)

    current_path = str(memory_db.database)
    if _memory_db_ready_path == current_path:
        return

    initialize_database()
    _memory_db_ready_path = current_path


# ==================== Response Models ====================


class MemoryStatsResponse(BaseModel):
    """记忆系统统计响应"""

    total_atoms: int
    active_atoms: int
    type_distribution: dict[str, int]
    dream_run_count: int
    insight_count: int
    noise_pool_count: int


class AtomData(BaseModel):
    """记忆原子数据"""

    atom_id: str
    atom_type: str
    content: str
    importance: float
    confidence: float
    weight: float
    status: str
    source_scene: Optional[str] = None
    created_at: Optional[str] = None
    entities: Optional[Any] = None


class AtomListResponse(BaseModel):
    """记忆原子列表响应"""

    items: list[AtomData]
    total: int


class AtomDetailResponse(BaseModel):
    """记忆原子详情响应"""

    data: AtomData


class DreamRunData(BaseModel):
    """梦境运行记录数据"""

    id: int
    run_type: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: str
    atoms_processed: Optional[int] = None
    atoms_created: Optional[int] = None
    summary: Optional[str] = None


class DreamRunListResponse(BaseModel):
    """梦境运行记录列表响应"""

    items: list[DreamRunData]
    total: int


class DreamRunMessageData(BaseModel):
    """单次梦境对一条原始消息的处理详情。"""

    archive_id: int
    message_id: str
    stream_id: str
    user_id: str
    platform: str
    sender_name: str
    conversation_name: str
    content: str
    message_timestamp: float
    chat_type: str
    route: str
    significance: Optional[float] = None
    outcome: str
    processed_at: Optional[str] = None


class DreamRunMessageListResponse(BaseModel):
    """梦境逐消息处理详情分页响应。"""

    items: list[DreamRunMessageData]
    total: int


class InsightPoolData(BaseModel):
    """洞见数据"""

    id: int
    content: str
    source_atoms: Optional[Any] = None
    agent_name: Optional[str] = None
    confidence: Optional[float] = None
    created_at: Optional[str] = None


class InsightPoolListResponse(BaseModel):
    """洞见列表响应"""

    items: list[InsightPoolData]
    total: int


class NoisePoolData(BaseModel):
    """噪声数据"""

    id: int
    content: str
    source_scene: str
    significance: Optional[float] = None
    created_at: Optional[str] = None
    ttl_days: int


class NoisePoolListResponse(BaseModel):
    """噪声列表响应"""

    items: list[NoisePoolData]
    total: int


# ==================== Helper Functions ====================


def _format_datetime(dt) -> Optional[str]:
    """格式化日期时间字段为 ISO 字符串"""
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def _atom_to_dict(atom: MemoryAtom) -> dict:
    """将 MemoryAtom 实例转换为可序列化字典"""
    entities = atom.entities
    if entities and isinstance(entities, str):
        try:
            entities = json.loads(entities)
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "atom_id": atom.atom_id,
        "atom_type": atom.atom_type,
        "content": atom.content,
        "importance": atom.importance,
        "confidence": atom.confidence,
        "weight": atom.weight,
        "status": atom.status,
        "source_scene": atom.source_scene,
        "created_at": _format_datetime(atom.created_at),
        "entities": entities,
    }


def _dream_run_to_dict(run: DreamRun) -> dict:
    """将 DreamRun 实例转换为可序列化字典"""
    return {
        "id": run.id,
        "run_type": run.run_type,
        "start_time": _format_datetime(run.start_time),
        "end_time": _format_datetime(run.end_time),
        "status": run.status,
        "atoms_processed": run.atoms_processed,
        "atoms_created": run.atoms_created,
        "summary": run.summary,
    }


def _dream_message_to_dict(message: RawMessageArchive) -> dict:
    """将原始消息的梦境处理状态转换为稳定的详情契约。"""
    sender_name = message.cardname or message.nickname or message.user_id
    if message.group_name or message.group_id:
        conversation_name = message.group_name or message.group_id
    elif message.chat_type == "private":
        conversation_name = "私聊"
    else:
        conversation_name = message.stream_id

    route = message.dream_route or "unknown"
    outcome = "skipped" if route == "skipped" or message.dream_status == "skipped" else "retained_as_candidate"
    return {
        "archive_id": message.id,
        "message_id": message.message_id,
        "stream_id": message.stream_id,
        "user_id": message.user_id,
        "platform": message.platform,
        "sender_name": sender_name,
        "conversation_name": conversation_name,
        "content": message.content,
        "message_timestamp": message.timestamp,
        "chat_type": message.chat_type,
        "route": route,
        "significance": message.dream_significance,
        "outcome": outcome,
        "processed_at": _format_datetime(message.dream_processed_at),
    }


def _insight_to_dict(insight: InsightPool) -> dict:
    """将 InsightPool 实例转换为可序列化字典"""
    source_atoms = insight.source_atoms
    if source_atoms and isinstance(source_atoms, str):
        try:
            source_atoms = json.loads(source_atoms)
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "id": insight.id,
        "content": insight.content,
        "source_atoms": source_atoms,
        "agent_name": insight.agent_name,
        "confidence": insight.confidence,
        "created_at": _format_datetime(insight.created_at),
    }


def _noise_to_dict(noise: NoisePool) -> dict:
    """将 NoisePool 实例转换为可序列化字典"""
    return {
        "id": noise.id,
        "content": noise.content,
        "source_scene": noise.source_scene,
        "significance": noise.significance,
        "created_at": _format_datetime(noise.created_at),
        "ttl_days": noise.ttl_days,
    }


# ==================== Endpoints ====================


@router.get("/stats", response_model=MemoryStatsResponse)
async def get_memory_stats(_auth: bool = Depends(require_auth)):
    """获取记忆系统统计信息"""
    try:
        _ensure_memory_database_ready()
        total_atoms = MemoryAtom.select().count()
        active_atoms = MemoryAtom.select().where(MemoryAtom.status == "active").count()

        type_distribution: dict[str, int] = {}
        for t in ["episodic", "factual", "relational", "preference", "planned"]:
            count = MemoryAtom.select().where(MemoryAtom.atom_type == t).count()
            if count > 0:
                type_distribution[t] = count

        dream_run_count = DreamRun.select().count()
        insight_count = InsightPool.select().count()
        noise_count = NoisePool.select().count()

        return MemoryStatsResponse(
            total_atoms=total_atoms,
            active_atoms=active_atoms,
            type_distribution=type_distribution,
            dream_run_count=dream_run_count,
            insight_count=insight_count,
            noise_pool_count=noise_count,
        )
    except Exception as e:
        raise internal_server_error(logger, "获取记忆统计失败", e) from None


@router.get("/atoms", response_model=AtomListResponse)
async def get_memory_atoms(
    atom_type: Optional[str] = Query(None, description="记忆类型过滤"),
    status: Optional[str] = Query("active", description="状态过滤"),
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    _auth: bool = Depends(require_auth),
):
    """获取记忆原子列表"""
    try:
        _ensure_memory_database_ready()
        conditions = []
        if atom_type:
            conditions.append(MemoryAtom.atom_type == atom_type)
        if status:
            conditions.append(MemoryAtom.status == status)

        query = MemoryAtom.select()
        if conditions:
            query = query.where(*conditions)

        total = query.count()
        items = query.order_by(MemoryAtom.created_at.desc()).limit(limit).offset(offset)

        return AtomListResponse(
            items=[AtomData(**_atom_to_dict(item)) for item in items],
            total=total,
        )
    except Exception as e:
        raise internal_server_error(logger, "获取记忆原子列表失败", e) from None


@router.get("/atoms/{atom_id}", response_model=AtomDetailResponse)
async def get_memory_atom_detail(
    atom_id: str,
    _auth: bool = Depends(require_auth),
):
    """获取记忆原子详情"""
    try:
        _ensure_memory_database_ready()
        atom = MemoryAtom.get_or_none(MemoryAtom.atom_id == atom_id)
        if not atom:
            raise HTTPException(status_code=404, detail="记忆原子不存在")
        return AtomDetailResponse(data=AtomData(**_atom_to_dict(atom)))
    except HTTPException:
        raise
    except Exception as e:
        raise internal_server_error(logger, "获取记忆原子详情失败", e) from None


@router.get("/dream-runs", response_model=DreamRunListResponse)
async def get_dream_runs(
    limit: int = Query(20, ge=1, le=200, description="返回数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    _auth: bool = Depends(require_auth),
):
    """获取梦境运行记录列表"""
    try:
        _ensure_memory_database_ready()
        total = DreamRun.select().count()
        items = DreamRun.select().order_by(DreamRun.start_time.desc()).limit(limit).offset(offset)

        return DreamRunListResponse(
            items=[DreamRunData(**_dream_run_to_dict(item)) for item in items],
            total=total,
        )
    except Exception as e:
        raise internal_server_error(logger, "获取梦境运行记录失败", e) from None


@router.get("/dream-runs/{run_id}/messages", response_model=DreamRunMessageListResponse)
async def get_dream_run_messages(
    run_id: int,
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    _auth: bool = Depends(require_auth),
):
    """获取一次梦境直接处理过的原始消息及处理结果。"""
    try:
        _ensure_memory_database_ready()
        run = DreamRun.get_or_none(DreamRun.id == run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="梦境运行记录不存在")

        message_filter = RawMessageArchive.dream_run_id == run.id
        if run.run_type == "daily":
            upper_bound = run.end_time
            if upper_bound is None:
                next_run = (
                    DreamRun.select()
                    .where(DreamRun.start_time > run.start_time)
                    .order_by(DreamRun.start_time.asc())
                    .first()
                )
                upper_bound = next_run.start_time if next_run is not None else datetime.datetime.now()

            legacy_window = (
                RawMessageArchive.dream_run_id.is_null(True)
                & RawMessageArchive.dream_processed_at.is_null(False)
                & (RawMessageArchive.dream_processed_at >= run.start_time)
                & (RawMessageArchive.dream_processed_at <= upper_bound)
            )
            message_filter = message_filter | legacy_window

        query = RawMessageArchive.select().where(message_filter)
        total = query.count()
        items = (
            query.order_by(
                RawMessageArchive.dream_processed_at.asc(),
                RawMessageArchive.timestamp.asc(),
                RawMessageArchive.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return DreamRunMessageListResponse(
            items=[DreamRunMessageData(**_dream_message_to_dict(item)) for item in items],
            total=total,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise internal_server_error(logger, "获取梦境消息处理详情失败", e) from None


@router.get("/insights", response_model=InsightPoolListResponse)
async def get_insights(
    limit: int = Query(20, ge=1, le=200, description="返回数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    _auth: bool = Depends(require_auth),
):
    """获取洞见列表"""
    try:
        _ensure_memory_database_ready()
        total = InsightPool.select().count()
        items = InsightPool.select().order_by(InsightPool.created_at.desc()).limit(limit).offset(offset)

        return InsightPoolListResponse(
            items=[InsightPoolData(**_insight_to_dict(item)) for item in items],
            total=total,
        )
    except Exception as e:
        raise internal_server_error(logger, "获取洞见列表失败", e) from None


@router.get("/noise-pool", response_model=NoisePoolListResponse)
async def get_noise_pool(
    limit: int = Query(20, ge=1, le=200, description="返回数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    _auth: bool = Depends(require_auth),
):
    """获取噪声池列表"""
    try:
        _ensure_memory_database_ready()
        total = NoisePool.select().count()
        items = NoisePool.select().order_by(NoisePool.created_at.desc()).limit(limit).offset(offset)

        return NoisePoolListResponse(
            items=[NoisePoolData(**_noise_to_dict(item)) for item in items],
            total=total,
        )
    except Exception as e:
        raise internal_server_error(logger, "获取噪声池列表失败", e) from None
