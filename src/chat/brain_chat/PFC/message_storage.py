from abc import ABC, abstractmethod
from typing import List, Dict, Any

from src.common.data_models.database_data_model import DatabaseMessages
from src.common.message_repository import count_messages, find_messages


class MessageStorage(ABC):
    """消息存储接口"""

    @abstractmethod
    async def get_messages_after(self, chat_id: str, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取指定消息ID之后的所有消息

        Args:
            chat_id: 聊天ID
            message: 消息

        Returns:
            List[Dict[str, Any]]: 消息列表
        """
        pass

    @abstractmethod
    async def get_messages_before(self, chat_id: str, time_point: float, limit: int = 5) -> List[Dict[str, Any]]:
        """获取指定时间点之前的消息

        Args:
            chat_id: 聊天ID
            time_point: 时间戳
            limit: 最大消息数量

        Returns:
            List[Dict[str, Any]]: 消息列表
        """
        pass

    @abstractmethod
    async def has_new_messages(self, chat_id: str, after_time: float) -> bool:
        """检查是否有新消息

        Args:
            chat_id: 聊天ID
            after_time: 时间戳

        Returns:
            bool: 是否有新消息
        """
        pass


class MongoDBMessageStorage(MessageStorage):
    """消息存储实现。

    旧版 PFC 使用 MongoDB 风格接口；当前仓库消息存储已迁移到 Peewee。
    这里保留类名兼容调用点，内部转接 message_repository。
    """

    async def get_messages_after(self, chat_id: str, message_time: float) -> List[Dict[str, Any]]:
        messages = find_messages(
            {"chat_id": chat_id, "time": {"$gt": message_time}},
            sort=[("time", 1)],
        )
        return [_message_to_pfc_dict(message) for message in messages]

    async def get_messages_before(self, chat_id: str, time_point: float, limit: int = 5) -> List[Dict[str, Any]]:
        messages = find_messages(
            {"chat_id": chat_id, "time": {"$lt": time_point}},
            limit=limit,
            limit_mode="latest",
        )
        return [_message_to_pfc_dict(message) for message in messages]

    async def has_new_messages(self, chat_id: str, after_time: float) -> bool:
        return count_messages({"chat_id": chat_id, "time": {"$gt": after_time}}) > 0


def _message_to_pfc_dict(message: DatabaseMessages) -> Dict[str, Any]:
    """转换为 PFC 旧逻辑期望的嵌套 dict 形状。"""
    flat = message.flatten()
    return {
        **flat,
        "user_info": {
            "platform": message.user_info.platform,
            "user_id": message.user_info.user_id,
            "user_nickname": message.user_info.user_nickname,
            "user_cardname": message.user_info.user_cardname,
        },
        "chat_info": {
            "stream_id": message.chat_info.stream_id,
            "platform": message.chat_info.platform,
            "create_time": message.chat_info.create_time,
            "last_active_time": message.chat_info.last_active_time,
            "user_info": {
                "platform": message.chat_info.user_info.platform,
                "user_id": message.chat_info.user_info.user_id,
                "user_nickname": message.chat_info.user_info.user_nickname,
                "user_cardname": message.chat_info.user_info.user_cardname,
            },
            "group_info": flat.get("chat_info_group_id")
            and {
                "group_id": flat.get("chat_info_group_id"),
                "group_name": flat.get("chat_info_group_name"),
                "group_platform": flat.get("chat_info_group_platform"),
            },
        },
    }


# # 创建一个内存消息存储实现，用于测试
# class InMemoryMessageStorage(MessageStorage):
#     """内存消息存储实现，主要用于测试"""

#     def __init__(self):
#         self.messages: Dict[str, List[Dict[str, Any]]] = {}

#     async def get_messages_after(self, chat_id: str, message_id: Optional[str] = None) -> List[Dict[str, Any]]:
#         if chat_id not in self.messages:
#             return []

#         messages = self.messages[chat_id]
#         if not message_id:
#             return messages

#         # 找到message_id的索引
#         try:
#             index = next(i for i, m in enumerate(messages) if m["message_id"] == message_id)
#             return messages[index + 1:]
#         except StopIteration:
#             return []

#     async def get_messages_before(self, chat_id: str, time_point: float, limit: int = 5) -> List[Dict[str, Any]]:
#         if chat_id not in self.messages:
#             return []

#         messages = [
#             m for m in self.messages[chat_id]
#             if m["time"] < time_point
#         ]

#         return messages[-limit:]

#     async def has_new_messages(self, chat_id: str, after_time: float) -> bool:
#         if chat_id not in self.messages:
#             return False

#         return any(m["time"] > after_time for m in self.messages[chat_id])

#     # 测试辅助方法
#     def add_message(self, chat_id: str, message: Dict[str, Any]):
#         """添加测试消息"""
#         if chat_id not in self.messages:
#             self.messages[chat_id] = []
#         self.messages[chat_id].append(message)
#         self.messages[chat_id].sort(key=lambda m: m["time"])
