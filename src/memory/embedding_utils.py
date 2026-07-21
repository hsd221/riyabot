"""嵌入向量生成工具

提供 generate_embedding / generate_query_embedding 两个记忆层兼容函数，
底层统一调用 ``src.llm_models.embedding.embed_text``。

Usage:
    from src.memory.embedding_utils import generate_embedding

    vec = await generate_embedding("要编码的记忆内容")
    if vec:
        qdrant_client.upsert(..., vector=vec)
"""

from typing import Optional

from src.common.logger import get_logger
from src.config.config import global_config
from src.llm_models.embedding import embed_text
from src.llm_models.embedding_profile import get_active_embedding_runtime

logger = get_logger("memory.embedding")


async def generate_embedding(text: str) -> Optional[list[float]]:
    """为记忆内容生成嵌入向量

    Args:
        text: 要编码的文本内容

    Returns:
        嵌入向量列表（维度由 bot 配置的 embedding 模型决定），失败时返回 None
    """
    if not text or not text.strip():
        return None

    try:
        runtime = get_active_embedding_runtime()
        result = await embed_text(
            text,
            request_type="memory.embedding",
            expected_dimension=(
                runtime.profile.dimension if runtime is not None else global_config.memory.embedding_dimension
            ),
            runtime=runtime,
        )
        return result.vector
    except Exception as e:
        logger.error(f"生成 embedding 失败: {e}")
        return None


async def generate_query_embedding(query: str) -> Optional[list[float]]:
    """为查询文本生成嵌入向量（用于向量检索）

    与 generate_embedding 共享底层实现，但在角色语义上区分记忆写入 vs 查询，
    便于后续针对查询场景作 prompt 优化或降维等预处理。

    Args:
        query: 查询文本

    Returns:
        嵌入向量列表，失败时返回 None
    """
    if not query or not query.strip():
        return None
    try:
        runtime = get_active_embedding_runtime()
        result = await embed_text(
            query,
            request_type="memory.embedding.query",
            expected_dimension=(
                runtime.profile.dimension if runtime is not None else global_config.memory.embedding_dimension
            ),
            runtime=runtime,
        )
        return result.vector
    except Exception as e:
        logger.error(f"生成 query embedding 失败: {e}")
        return None
