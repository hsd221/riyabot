"""记忆系统与聊天回复器的集成函数。

提供 build_memory_retrieval_prompt() 供 group_generator 和 private_generator 共享调用，
避免两处重复实现相同的记忆检索 prompt 拼接逻辑。
"""

from typing import Optional, Any

from src.common.logger import get_logger

logger = get_logger("memory.prompt")


async def build_memory_retrieval_prompt(
    chat_talking_prompt_short: str = "",
    sender: str = "",
    target: str = "",
    chat_stream: Any = None,
    think_level: int = 1,
    unknown_words: Optional[list[str]] = None,
    question: Optional[str] = None,
    user_id: Optional[str] = None,
    graph_store: Optional[Any] = None,
) -> tuple[str, list[str]]:
    """从新记忆系统检索相关上下文，用于 LLM prompt 拼接

    Args:
        chat_talking_prompt_short: 短期聊天上下文文本
        sender: 发送者名称
        target: 消息内容
        chat_stream: 聊天流对象 (ChatStream)
        think_level: 思考深度
        unknown_words: 未知词汇列表
        question: 回复中带的问题
        user_id: 用户 ID（可选，用于 profile 上下文检索）
                不传则尝试从 chat_stream.user_info 提取

    Returns:
        tuple[str, list[str]]: (格式化后的记忆文本块, 检索到的 atom_id 列表)
                               检索失败或系统不可用时返回 ("", [])
    """
    try:
        from src.memory import get_memory_store
        from src.memory.layer3_retrieval import MemoryRetriever

        store = get_memory_store()
        retriever = MemoryRetriever(store, graph_store=graph_store)

        stream_id: str = chat_stream.stream_id if hasattr(chat_stream, "stream_id") else ""
        if not stream_id:
            return "", []

        # 尽量提取当前 user_id（如果未显式传入）
        resolved_user_id: Optional[str] = user_id
        if resolved_user_id is None and hasattr(chat_stream, "user_info") and chat_stream.user_info is not None:
            resolved_user_id = getattr(chat_stream.user_info, "user_id", None)

        # 使用新方法获取格式化文本 + atom_ids
        memory_context, atom_ids = await retriever.get_context_for_reply_with_ids(
            stream_id=stream_id,
            user_id=resolved_user_id,
            max_atoms=5,
            max_chars=800,
        )

        # 跨场景记忆检索（try/except 保护，不中断正常流程）
        cross_scene_text = ""
        try:
            scene_type = "group_chat" if "group" in str(stream_id) else "private_chat"
            cross_scene_text = await retriever.get_cross_scene_context(
                scene_type=scene_type,
                stream_id=stream_id,
                user_id=resolved_user_id or "",
                max_atoms=2,
                max_chars=300,
                cross_scene_atoms=3,
            )
        except Exception:
            pass

        # 尝试添加用户 profile 上下文（模块不存在时静默跳过）
        profile_text = ""
        if resolved_user_id:
            try:
                from src.memory.user_profile import ProfileRetriever, ProfileStore

                profile_store = ProfileStore()
                profile_retriever = ProfileRetriever(profile_store)
                profile_text = profile_retriever.get_profile_context(resolved_user_id)
            except Exception:
                pass

        # 拼接最终文本
        final_text = ""
        if profile_text:
            final_text += f"\n【用户画像】\n{profile_text}\n"
        if memory_context:
            final_text += f"\n【记忆检索】\n{memory_context}\n"
        if cross_scene_text:
            final_text += f"\n【跨场景记忆】\n{cross_scene_text}\n"

        if final_text:
            logger.debug(
                "记忆检索prompt构建完成（带ID）",
                context_len=len(final_text),
                atom_ids_count=len(atom_ids),
            )
            return final_text, atom_ids
        return "", []
    except ImportError:
        logger.warning("记忆系统模块不可用，跳过记忆检索")
        return "", []
    except Exception as e:
        logger.warning(f"记忆检索异常: {e}")
        return "", []
