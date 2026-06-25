"""嵌入向量生成工具

提供 generate_embedding / generate_query_embedding 两个核心函数，
通过延迟导入调用 bot 已配置的 LLM embedding 模型接口，避免循环依赖。

Usage:
    from src.memory.embedding_utils import generate_embedding

    vec = await generate_embedding("要编码的记忆内容")
    if vec:
        qdrant_client.upsert(..., vector=vec)
"""

from typing import Optional

from src.common.logger import get_logger

logger = get_logger("memory.embedding")


async def generate_embedding(text: str) -> Optional[list[float]]:
    """为记忆内容生成嵌入向量

    延迟导入 src.chat.utils.utils.get_embedding 以避免模块加载时的循环依赖。

    Args:
        text: 要编码的文本内容

    Returns:
        嵌入向量列表（维度由 bot 配置的 embedding 模型决定），失败时返回 None
    """
    if not text or not text.strip():
        return None

    try:
        from src.chat.utils.utils import get_embedding

        embedding = await get_embedding(text)
        return embedding
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
    return await generate_embedding(query)
