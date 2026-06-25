from typing import Dict, Any

from src.common.logger import get_logger
from src.plugin_system import BaseTool, ToolParamType

logger = get_logger("lpmm_get_knowledge_tool")


class SearchKnowledgeFromLPMMTool(BaseTool):
    """从LPMM知识库中搜索相关信息的工具（LPMM 已移除，返回占位消息）"""

    name = "lpmm_search_knowledge"
    description = "从知识库中搜索相关信息，如果你需要知识，就使用这个工具"
    parameters = [
        ("query", ToolParamType.STRING, "搜索查询关键词", True, None),
        ("limit", ToolParamType.INTEGER, "希望返回的相关知识条数，默认5", False, None),
    ]
    available_for_llm = False

    async def execute(self, function_args: Dict[str, Any]) -> Dict[str, Any]:
        """执行知识库搜索（LPMM 已移除，返回占位消息）

        Args:
            function_args: 工具参数

        Returns:
            Dict: 工具执行结果
        """
        query: str = function_args.get("query", "")  # type: ignore
        logger.debug(f"LPMM知识库已移除，跳过知识获取: {query}")
        return {"type": "info", "id": query, "content": "LPMM 知识库已移除，等待新记忆系统替代"}
