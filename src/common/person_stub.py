"""Person name resolver stub — 用户画像系统接入前的临时实现

所有 Person(platform, user_id).person_name 调用点统一返回 user_id 作为显示名。
后续接入用户画像系统时，替换此文件即可。
"""

import hashlib
from typing import Optional

from src.common.logger import get_logger

logger = get_logger("person_stub")


def get_person_id(platform: str = "", user_id: str | int = "") -> str:
    """根据平台和用户ID计算唯一person_id（MD5哈希）

    保持与原实现相同的哈希算法，确保person_id兼容性。
    """
    if not platform or not user_id:
        return str(user_id)
    if "-" in platform:
        platform = platform.split("-")[1]
    components = [platform, str(user_id)]
    key = "_".join(components)
    return hashlib.md5(key.encode()).hexdigest()


class Person:
    """Person 类桩 — 后续替换为用户画像系统

    保持原接口兼容，所有属性提供合理的默认值。
    支持原有的 person_id, is_known, person_name 属性 + register_person 类方法。
    """

    def __init__(
        self,
        platform: str = "",
        user_id: str = "",
        person_id: str = "",
        person_name: str = "",
    ):
        self.platform = platform or "unknown"
        self.user_id = user_id
        self.is_known = True  # 默认已知，避免群聊中额外的判断逻辑
        self.nickname = ""
        self.person_name = user_id or "unknown"
        self.person_id = ""
        self.name_reason: Optional[str] = None
        self.know_times = 0
        self.know_since: Optional[float] = None
        self.last_know: Optional[float] = None
        self.memory_points: list[str] = []
        self.group_nick_name: list[dict[str, str]] = []

        if person_id:
            self.person_id = person_id
        elif person_name:
            self.person_id = person_name
            self.person_name = person_name
        elif platform and user_id:
            self.person_id = get_person_id(platform, user_id)
            self.person_name = user_id
            self.user_id = str(user_id)
        else:
            logger.error("[PersonStub] 初始化失败，缺少必要参数")
            raise ValueError("Person 初始化失败，缺少必要参数")

    @classmethod
    def register_person(
        cls,
        platform: str,
        user_id: str,
        nickname: str = "",
        group_id: str = "",
        group_nick_name: str = "",
    ):
        """注册新用户 — 桩实现，不做任何持久化"""
        logger.debug(f"[STUB] register_person: {platform=}, {user_id=}, {nickname=}")
        return cls(platform=platform, user_id=user_id, person_name=nickname or user_id)

    async def build_relationship(self, chat_content: str = "", info_type: str = "") -> str:
        """构建关系信息 — 桩实现"""
        return ""

    def get_relation_info(self) -> str:
        """获取关系信息 — 桩实现"""
        return f"{self.person_name}({self.user_id})"

    def __repr__(self) -> str:
        return f"Person(person_id={self.person_id}, platform={self.platform}, user_id={self.user_id})"


def is_person_known(
    person_id: str | None = None,
    user_id: str | None = None,
    platform: str | None = None,
    person_name: str | None = None,
) -> bool:
    """检查用户是否已知 — 桩实现，默认返回 True"""
    return True


def store_person_memory_from_answer(person_name: str, memory_content: str, chat_id: str) -> None:
    """存储记忆 — 桩实现"""
    pass
