from typing import Dict, Any, Optional

from src.common.logger import get_logger
from src.plugin_system import BaseTool, ToolParamType

logger = get_logger("lpmm_get_knowledge_tool")


class SearchKnowledgeFromLPMMTool(BaseTool):
    """兼容旧 LPMM 工具名的记忆检索工具。"""

    name = "lpmm_search_knowledge"
    description = "从过去聊天记忆中搜索与当前回复直接相关的候选证据"
    parameters = [
        ("query", ToolParamType.STRING, "一个具体、可检索的过去聊天记忆问题", True, None),
        ("limit", ToolParamType.INTEGER, "希望返回的候选证据条数，默认5", False, None),
    ]
    available_for_llm = False

    def __init__(
        self,
        plugin_config: Optional[dict] = None,
        chat_stream: Optional[Any] = None,
        chat_history: str = "",
        sender: str = "",
        target: str = "",
    ):
        super().__init__(plugin_config=plugin_config, chat_stream=chat_stream)
        self.chat_history = chat_history
        self.sender = sender
        self.target = target

    async def execute(self, function_args: Dict[str, Any]) -> Dict[str, Any]:
        """执行记忆检索。

        Args:
            function_args: 工具参数

        Returns:
            Dict: 工具执行结果
        """
        query = str(function_args.get("query", "") or "").strip()
        if not query:
            return {"type": "info", "id": "", "content": ""}
        if self.chat_stream is None:
            logger.debug("旧知识工具未获得 ChatStream，跳过记忆检索: %s", query)
            return {"type": "info", "id": query, "content": ""}

        try:
            limit = int(function_args.get("limit") or 5)
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(limit, 6))

        try:
            from src.memory.prompt_integration import build_memory_retrieval_prompt

            user_id = getattr(getattr(self.chat_stream, "user_info", None), "user_id", None)
            evidence, atom_ids = await build_memory_retrieval_prompt(
                chat_talking_prompt_short=self.chat_history,
                sender=self.sender,
                target=self.target,
                chat_stream=self.chat_stream,
                think_level=2,
                question=query,
                user_id=user_id,
                max_atoms=limit,
                max_chars=900,
                include_cross_scene=True,
                question_from_planner=False,
            )
        except Exception as e:
            logger.debug("旧知识工具桥接记忆检索失败: %s", e)
            return {"type": "info", "id": query, "content": ""}

        return {
            "type": "info",
            "id": query,
            "content": evidence,
            "source": "memory",
            "atom_ids": atom_ids,
        }
