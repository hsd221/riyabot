from typing import List, Tuple
from src.common.logger import get_module_logger
from src.chat.message_receive.message import Message

logger = get_module_logger("knowledge_fetcher")


class KnowledgeFetcher:
    """知识调取器（LPMM 知识库已移除，暂返回空结果）"""

    def __init__(self, private_name: str):
        self.private_name = private_name

    async def fetch(self, query: str, chat_history: List[Message]) -> Tuple[str, str]:
        """获取相关知识（LPMM 已移除，返回空占位）

        Args:
            query: 查询内容
            chat_history: 聊天历史

        Returns:
            Tuple[str, str]: (获取的知识, 知识来源)
        """
        logger.debug(f"[私聊][{self.private_name}]LPMM知识库已移除，跳过知识获取")
        return "（LPMM 知识库已移除，等待新记忆系统）", ""
