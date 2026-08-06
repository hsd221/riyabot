"""撤回消息登记表

撤回事件与消息落库存在时序竞争：撤回通知可能在消息写入数据库之前抵达
（用户撤回极快，或消息正在做媒体解析）。此时单纯的 UPDATE 会匹配 0 行，
随后消息被正常写入，撤回标记就丢了。

因此这里维护一份内存中的近期撤回 ID 集合作为兜底：
- 撤回事件到达时先登记 ID，再尝试更新数据库；
- 消息写入前查询此集合，命中则直接不存；
- 处理链路在关键检查点查询此集合，命中则中断。
"""

import time

from typing import Dict, Optional, Set

from src.common.logger import get_logger

logger = get_logger("recall")

# 撤回 ID 的保留时长。需要覆盖「消息抵达 → 处理完成」的最长耗时，
# 包含缓冲等待、规划器与回复生成的 LLM 调用。
RECALL_TTL_SECONDS = 600.0

# 单个聊天流内保留的撤回记录上限，避免异常情况下无界增长。
MAX_ENTRIES = 2000


class RecallRegistry:
    """记录近期被撤回的消息 ID，供写入拦截与处理中断查询。"""

    def __init__(self) -> None:
        # message_id -> 登记时间戳
        self._recalled: Dict[str, float] = {}
        # 已登记但当时未能在库中匹配到的 ID，等待消息补写时拦截
        self._pending_ids: Set[str] = set()

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [msg_id for msg_id, ts in self._recalled.items() if now - ts > RECALL_TTL_SECONDS]
        for msg_id in expired:
            self._recalled.pop(msg_id, None)
            self._pending_ids.discard(msg_id)

        # 超出上限时按登记时间淘汰最旧的记录
        if len(self._recalled) > MAX_ENTRIES:
            ordered = sorted(self._recalled.items(), key=lambda item: item[1])
            for msg_id, _ in ordered[: len(self._recalled) - MAX_ENTRIES]:
                self._recalled.pop(msg_id, None)
                self._pending_ids.discard(msg_id)

    def register(self, message_id: Optional[str], *, matched_in_db: bool = False) -> None:
        """登记一个被撤回的消息 ID。

        Args:
            message_id: 被撤回消息的平台 ID
            matched_in_db: 是否已在数据库中标记成功。未匹配的会留在 pending，
                等消息补写时由 store 层拦截。
        """
        if not message_id:
            return
        key = str(message_id)
        self._recalled[key] = time.time()
        if matched_in_db:
            self._pending_ids.discard(key)
        else:
            self._pending_ids.add(key)
        self._purge_expired()

    def is_recalled(self, message_id: Optional[str]) -> bool:
        """判断消息是否在近期撤回集合中。"""
        if not message_id:
            return False
        key = str(message_id)
        ts = self._recalled.get(key)
        if ts is None:
            return False
        if time.time() - ts > RECALL_TTL_SECONDS:
            self._recalled.pop(key, None)
            self._pending_ids.discard(key)
            return False
        return True

    def resolve_pending(self, message_id: Optional[str]) -> None:
        """消息已在库中标记完成，从 pending 中移除。"""
        if not message_id:
            return
        self._pending_ids.discard(str(message_id))

    def has_pending(self, message_id: Optional[str]) -> bool:
        """判断某个撤回 ID 是否仍在等待消息补写。"""
        if not message_id:
            return False
        return str(message_id) in self._pending_ids

    def any_recalled(self, message_ids) -> bool:
        """批量判断，其中任意一个被撤回则返回 True。"""
        return any(self.is_recalled(msg_id) for msg_id in message_ids or [])

    def clear(self) -> None:
        """清空登记表，仅供测试使用。"""
        self._recalled.clear()
        self._pending_ids.clear()


# 全局单例
recall_registry = RecallRegistry()
