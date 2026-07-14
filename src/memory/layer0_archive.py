"""第0层：原始消息归档器

从聊天流中捕获原始消息并写入 RawMessageArchive 表。
不做任何加工，保证数据原始完整性，供梦境系统回放使用。

使用方式:
    from src.memory.layer0_archive import MessageArchiver

    archiver = MessageArchiver()
    record_id = await archiver.archive_group_message(message)
    records = await archiver.query_by_stream("group_12345")
"""

from __future__ import annotations

import time
from typing import Any, Optional

from peewee import IntegrityError

from src.common.logger import get_logger
from src.memory.schema import RawMessageArchive, memory_db

logger = get_logger("memory.layer0")

# ---------------------------------------------------------------------------
# 字段提取候选列表（duck-typing 支持）
# ---------------------------------------------------------------------------

_FIELD_CANDIDATES: dict[str, list[str]] = {
    "stream_id": ["group_id", "stream_id", "chat_id"],
    "message_id": ["message_id", "id", "msg_id"],
    "user_id": ["user_id", "sender_id", "author_id"],
    "content": ["content", "text", "message", "body"],
    "timestamp": ["timestamp", "time", "created_at"],
}

_OPTIONAL_FIELD_CANDIDATES: dict[str, list[str]] = {
    "platform": ["user_platform", "platform"],
    "nickname": ["user_nickname", "nickname", "speaker"],
    "cardname": ["user_cardname", "cardname"],
}


def _get_attr(obj: Any, candidates: list[str]) -> Any:
    """从对象中尝试获取属性，返回第一个非 None 的值。

    Args:
        obj: 任意对象
        candidates: 候选属性名列表，按优先级排列

    Returns:
        第一个非 None 的属性值

    Raises:
        ValueError: 所有候选属性均不存在或为 None
    """
    for attr_name in candidates:
        val = getattr(obj, attr_name, None)
        if val is not None:
            return val
    logger.warning(
        "消息对象缺少必要属性",
        field_candidates=candidates,
        object_type=type(obj).__name__,
    )
    raise ValueError(f"无法从 {type(obj).__name__} 对象中提取字段，已尝试: {candidates}")


def _resolve_timestamp(timestamp_val: Any) -> float:
    """将多种时间戳格式统一为 float（Unix 时间戳，秒级）。"""
    if timestamp_val is None:
        return time.time()
    if isinstance(timestamp_val, (int, float)):
        # 如果数值大于 1e11（毫秒级时间戳），转换为秒
        if timestamp_val > 1e11:
            return timestamp_val / 1000.0
        return float(timestamp_val)
    if hasattr(timestamp_val, "timestamp"):
        return timestamp_val.timestamp()
    return time.time()


def _model_to_dict(record: RawMessageArchive) -> dict[str, Any]:
    """将 RawMessageArchive 模型实例转为纯字典。

    Args:
        record: Peewee 模型实例

    Returns:
        字段字典（不含 Peewee 模型方法）
    """
    return {
        "id": record.id,
        "stream_id": record.stream_id,
        "message_id": record.message_id,
        "user_id": record.user_id,
        "platform": record.platform,
        "nickname": record.nickname,
        "cardname": record.cardname,
        "group_id": record.group_id,
        "group_name": record.group_name,
        "content": record.content,
        "timestamp": record.timestamp,
        "chat_type": record.chat_type,
        "dream_status": record.dream_status,
        "dream_route": record.dream_route,
        "dream_significance": record.dream_significance,
        "dream_processed_at": record.dream_processed_at,
    }


# ---------------------------------------------------------------------------
# MessageArchiver
# ---------------------------------------------------------------------------


class MessageArchiver:
    """第0层：原始消息归档器

    从聊天流中捕获原始消息并写入 RawMessageArchive 表。
    不做任何加工，保证数据原始完整性，供梦境系统回放使用。
    """

    def __init__(self) -> None:
        self._logger = logger

    # -- 核心归档方法 -------------------------------------------------------

    def _extract_message_fields(self, message: Any, chat_type: str) -> dict[str, Any]:
        """从任意消息对象中提取公共字段，支持 duck-typing。

        Args:
            message: 消息对象（任意类型，通过属性名探测提取）
            chat_type: 聊天类型（"group" 或 "private"）

        Returns:
            包含 stream_id / message_id / user_id / content / timestamp / chat_type 的字典

        Raises:
            ValueError: 无法从消息对象中提取必需字段
        """
        raw: dict[str, Any] = {}
        for field_name, candidates in _FIELD_CANDIDATES.items():
            raw[field_name] = _get_attr(message, candidates)

        for field_name, candidates in _OPTIONAL_FIELD_CANDIDATES.items():
            value = next((getattr(message, name, None) for name in candidates if getattr(message, name, None)), "")
            raw[field_name] = str(value or "").strip()
        raw["platform"] = raw["platform"].lower() or "legacy"

        group_info = getattr(message, "group_info", None)
        raw["group_id"] = str(getattr(group_info, "group_id", "") or "").strip()
        raw["group_name"] = str(getattr(group_info, "group_name", "") or "").strip()

        raw["timestamp"] = _resolve_timestamp(raw["timestamp"])
        raw["chat_type"] = chat_type
        return raw

    def _insert_record(self, fields: dict[str, Any]) -> RawMessageArchive:
        """将字段字典写入 RawMessageArchive 表。

        Args:
            fields: 消息字段字典

        Returns:
            创建的 RawMessageArchive 实例
        """
        try:
            with memory_db.atomic():
                record = RawMessageArchive.get_or_none(
                    RawMessageArchive.stream_id == fields["stream_id"],
                    RawMessageArchive.message_id == fields["message_id"],
                    RawMessageArchive.chat_type == fields["chat_type"],
                )
                if record is not None:
                    logger.debug(
                        "归档记录已存在，跳过重复写入",
                        stream_id=record.stream_id,
                        message_id=record.message_id,
                        msg_type=record.chat_type,
                    )
                    return record
                record = RawMessageArchive.create(**fields)
        except IntegrityError:
            record = RawMessageArchive.get_or_none(
                RawMessageArchive.stream_id == fields["stream_id"],
                RawMessageArchive.message_id == fields["message_id"],
                RawMessageArchive.chat_type == fields["chat_type"],
            )
            if record is None:
                raise
            logger.debug(
                "归档记录发生并发唯一冲突，返回已存在记录",
                stream_id=record.stream_id,
                message_id=record.message_id,
                msg_type=record.chat_type,
            )
        logger.debug(
            "写入归档记录",
            stream_id=record.stream_id,
            msg_type=record.chat_type,
        )
        return record

    async def archive_group_message(self, message: Any) -> str:
        """归档一条群聊消息。

        Args:
            message: 群聊消息对象

        Returns:
            归档记录 ID (str)
        """
        fields = self._extract_message_fields(message, chat_type="group")
        record = self._insert_record(fields)
        self._logger.debug(
            f"群聊消息已归档 | stream={fields['stream_id']} "
            f"msg={fields['message_id']} user={fields['user_id']} id={record.id}"
        )
        return str(record.id)

    async def archive_private_message(self, message: Any) -> str:
        """归档一条私聊消息。

        Args:
            message: 私聊消息对象

        Returns:
            归档记录 ID (str)
        """
        fields = self._extract_message_fields(message, chat_type="private")
        record = self._insert_record(fields)
        self._logger.debug(
            f"私聊消息已归档 | stream={fields['stream_id']} "
            f"msg={fields['message_id']} user={fields['user_id']} id={record.id}"
        )
        return str(record.id)

    async def archive_batch(self, messages: list[Any]) -> list[str]:
        """批量归档消息。

        Args:
            messages: 消息对象列表

        Returns:
            归档记录 ID 列表
        """
        ids: list[str] = []
        with memory_db.atomic():
            for msg in messages:
                fields = self._extract_message_fields(msg, chat_type=getattr(msg, "chat_type", "group"))
                record = self._insert_record(fields)
                ids.append(str(record.id))
        self._logger.info(f"批量归档 {len(ids)} 条消息")
        return ids

    # -- 查询方法 -----------------------------------------------------------

    async def query_by_stream(
        self,
        stream_id: str,
        limit: int = 100,
        before_timestamp: Optional[float] = None,
        after_timestamp: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """按流 ID 查询历史消息（按时间戳降序）。

        Args:
            stream_id: 聊天流 ID
            limit: 最大返回条数
            before_timestamp: 只返回早于此时间戳的消息
            after_timestamp: 只返回晚于此时间戳的消息

        Returns:
            消息字典列表
        """
        query = RawMessageArchive.select().where(RawMessageArchive.stream_id == stream_id)

        if before_timestamp is not None:
            query = query.where(RawMessageArchive.timestamp < before_timestamp)
        if after_timestamp is not None:
            query = query.where(RawMessageArchive.timestamp > after_timestamp)

        query = query.order_by(RawMessageArchive.timestamp.desc()).limit(limit)

        records = list(query)
        logger.debug("按流查询归档", stream_id=stream_id, count=len(records))
        return [_model_to_dict(r) for r in records]

    async def query_by_user(
        self,
        user_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """按用户 ID 查询消息（按时间戳降序）。

        Args:
            user_id: 用户 ID
            limit: 最大返回条数

        Returns:
            消息字典列表
        """
        query = (
            RawMessageArchive.select()
            .where(RawMessageArchive.user_id == user_id)
            .order_by(RawMessageArchive.timestamp.desc())
            .limit(limit)
        )
        records = list(query)
        logger.debug("按用户查询归档", user_id=user_id, count=len(records))
        return [_model_to_dict(r) for r in records]

    async def get_stream_stats(self, stream_id: str) -> dict[str, Any]:
        """获取流的统计信息。

        Args:
            stream_id: 聊天流 ID

        Returns:
            包含消息数 / 时间范围 / 活跃用户数的字典
        """
        with memory_db.atomic():
            query = RawMessageArchive.select().where(RawMessageArchive.stream_id == stream_id)

            total = query.count()

            if total == 0:
                logger.debug("归档流统计", stream_id=stream_id, total=0)
                return {
                    "stream_id": stream_id,
                    "total_messages": 0,
                    "time_range": None,
                    "active_users": 0,
                }

            earliest = query.order_by(RawMessageArchive.timestamp.asc()).first()
            latest = query.order_by(RawMessageArchive.timestamp.desc()).first()

            # 去重统计活跃用户数
            user_ids = query.select(RawMessageArchive.user_id).distinct().tuples()
            active_users = len(list(user_ids))

        logger.debug("归档流统计", stream_id=stream_id, total=total)
        return {
            "stream_id": stream_id,
            "total_messages": total,
            "time_range": {
                "earliest": earliest.timestamp if earliest else None,
                "latest": latest.timestamp if latest else None,
            },
            "active_users": active_users,
        }

    # -- 维护方法 -----------------------------------------------------------

    async def cleanup_old_messages(self, older_than_days: int = 30) -> int:
        """清理超过指定天数的旧消息。

        Args:
            older_than_days: 保留天数阈值（默认 30 天）

        Returns:
            删除的消息条数
        """
        cutoff = time.time() - older_than_days * 86400

        with memory_db.atomic():
            query = RawMessageArchive.delete().where(RawMessageArchive.timestamp < cutoff)
            deleted = query.execute()

        if deleted:
            self._logger.info(f"清理旧消息完成 | 删除 {deleted} 条 | 阈值 {older_than_days} 天")
        return deleted
