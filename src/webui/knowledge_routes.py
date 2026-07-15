"""知识库图谱可视化 API 路由（LPMM 知识库已移除，所有接口返回 disabled 状态）"""

from typing import List, Optional
from fastapi import APIRouter, Query, Depends, Cookie, Header
from pydantic import BaseModel
import logging
from src.common.logger import hash_id
from src.webui.auth import verify_auth_token_from_cookie_or_header

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webui/knowledge", tags=["knowledge"])


def require_auth(
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> bool:
    """认证依赖：验证用户是否已登录"""
    return verify_auth_token_from_cookie_or_header(maibot_session, authorization)


class KnowledgeNode(BaseModel):
    """知识节点"""

    id: str
    type: str  # 'entity' or 'paragraph'
    content: str
    create_time: Optional[float] = None


class KnowledgeEdge(BaseModel):
    """知识边"""

    source: str
    target: str
    weight: float
    create_time: Optional[float] = None
    update_time: Optional[float] = None


class KnowledgeGraph(BaseModel):
    """知识图谱"""

    nodes: List[KnowledgeNode]
    edges: List[KnowledgeEdge]


class KnowledgeStats(BaseModel):
    """知识库统计信息"""

    total_nodes: int
    total_edges: int
    entity_nodes: int
    paragraph_nodes: int
    avg_connections: float


@router.get("/graph", response_model=KnowledgeGraph)
async def get_knowledge_graph(
    limit: int = Query(100, ge=1, le=10000, description="返回的最大节点数"),
    node_type: str = Query("all", description="节点类型过滤: all, entity, paragraph"),
    _auth: bool = Depends(require_auth),
):
    """获取知识图谱 — LPMM 已移除，返回空"""
    logger.info("LPMM 知识库已移除，知识图谱不可用")
    return KnowledgeGraph(nodes=[], edges=[])


@router.get("/stats", response_model=KnowledgeStats)
async def get_knowledge_stats(_auth: bool = Depends(require_auth)):
    """获取知识库统计信息 — LPMM 已移除，返回零值"""
    logger.info("LPMM 知识库已移除，知识统计不可用")
    return KnowledgeStats(total_nodes=0, total_edges=0, entity_nodes=0, paragraph_nodes=0, avg_connections=0.0)


@router.get("/search", response_model=List[KnowledgeNode])
async def search_knowledge_node(query: str = Query(..., min_length=1), _auth: bool = Depends(require_auth)):
    """搜索知识节点 — LPMM 已移除，返回空列表"""
    logger.info("LPMM 知识库已移除，知识搜索不可用", extra={"query_hash": hash_id(query)})
    return []
