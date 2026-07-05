import json
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, List, Optional, Union

from maim_message import Seg, UserInfo

from src.chat.message_receive.chat_stream import get_chat_manager
from src.chat.message_receive.message import MessageRecv, MessageSending
from src.chat.message_receive.uni_message_sender import UniversalMessageSender
from src.common.data_models.message_component_model import (
    EmojiComponent,
    ImageComponent,
    MessageComponentSequence,
    TextComponent,
    VoiceComponent,
    from_components_to_seg,
    from_seg_to_components,
)
from src.common.logger import get_logger
from src.config.config import global_config
from src.plugin_system.base.component_types import EventType

if TYPE_CHECKING:
    from src.common.data_models.database_data_model import DatabaseMessages

logger = get_logger("send_service")


def _normalize_additional_config(additional_config) -> dict:
    if isinstance(additional_config, Mapping):
        return dict(additional_config)
    if isinstance(additional_config, str) and additional_config.strip():
        try:
            parsed = json.loads(additional_config)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            logger.debug(
                "数据库消息 additional_config 不是有效 JSON，已忽略", event_code="send.additional_config.invalid_json"
            )
    return {}


def db_message_to_message_recv(message_obj: "DatabaseMessages") -> MessageRecv:
    """将数据库消息重建为可用于引用回复的 MessageRecv。"""
    user_info = {
        "platform": message_obj.user_info.platform or "",
        "user_id": message_obj.user_info.user_id or "",
        "user_nickname": message_obj.user_info.user_nickname or "",
        "user_cardname": message_obj.user_info.user_cardname or "",
    }

    group_info = None
    if message_obj.chat_info.group_info:
        group_info = {
            "platform": message_obj.chat_info.group_info.group_platform or "",
            "group_id": message_obj.chat_info.group_info.group_id or "",
            "group_name": message_obj.chat_info.group_info.group_name or "",
        }

    message_info = {
        "platform": message_obj.chat_info.platform or "",
        "message_id": message_obj.message_id,
        "time": message_obj.time,
        "group_info": group_info,
        "user_info": user_info,
        "additional_config": _normalize_additional_config(message_obj.additional_config),
        "format_info": {"content_format": "", "accept_format": ""},
        "template_info": {"template_items": {}},
    }
    message_text = message_obj.processed_plain_text or ""

    return MessageRecv(
        {
            "message_info": message_info,
            "message_segment": Seg(type="text", data=message_text).to_dict(),
            "raw_message": message_text,
            "processed_plain_text": message_text,
        }
    )


def build_message_to_stream(
    message_segment: Seg,
    stream_id: str,
    *,
    display_message: str = "",
    reply_message: Optional["DatabaseMessages"] = None,
    selected_expressions: Optional[List[int]] = None,
    message_components: MessageComponentSequence | None = None,
) -> MessageSending | None:
    target_stream = get_chat_manager().get_stream(stream_id)
    if not target_stream:
        logger.error("发送目标聊天流不存在", event_code="send.stream_not_found", stream_id=stream_id)
        return None

    current_time = time.time()
    bot_user_info = UserInfo(
        user_id=global_config.bot.qq_account,
        user_nickname=global_config.bot.nickname,
        platform=target_stream.platform,
    )

    reply_to_platform_id = ""
    anchor_message: Union[MessageRecv, None] = None
    if reply_message:
        anchor_message = db_message_to_message_recv(reply_message)
        logger.debug(
            "引用回复锚点消息已找到",
            event_code="send.reply_anchor.found",
            sender_id=anchor_message.message_info.user_info.user_id,  # type: ignore
            message_id=anchor_message.message_info.message_id,
        )
        if anchor_message:
            anchor_message.update_chat_stream(target_stream)
            assert anchor_message.message_info.user_info, "用户信息缺失"
            reply_to_platform_id = (
                f"{anchor_message.message_info.platform}:{anchor_message.message_info.user_info.user_id}"
            )

    message = MessageSending(
        message_id=f"send_api_{int(current_time * 1000)}",
        chat_stream=target_stream,
        bot_user_info=bot_user_info,
        sender_info=target_stream.user_info,
        message_segment=message_segment,
        display_message=display_message,
        reply=anchor_message,
        is_head=True,
        is_emoji=(message_segment.type == "emoji"),
        thinking_start_time=current_time,
        reply_to=reply_to_platform_id,
        selected_expressions=selected_expressions,
    )
    if message_components is not None:
        message.message_components = message_components
        message.preserve_message_components = True
    return message


async def message_to_stream_with_message(
    message_segment: Seg,
    stream_id: str,
    *,
    display_message: str = "",
    typing: bool = False,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    show_log: bool = True,
    selected_expressions: Optional[List[int]] = None,
    message_components: MessageComponentSequence | None = None,
) -> MessageSending | None:
    if set_reply and not reply_message:
        logger.warning("引用回复缺少锚点消息", event_code="send.reply_anchor.missing", stream_id=stream_id)
        return None

    if show_log:
        logger.debug(
            "消息开始发送",
            event_code="send.message.started",
            stream_id=stream_id,
            segment_type=message_segment.type,
            typing=typing,
            set_reply=set_reply,
            storage_message=storage_message,
        )

    try:
        bot_message = build_message_to_stream(
            message_segment=message_segment,
            stream_id=stream_id,
            display_message=display_message,
            reply_message=reply_message,
            selected_expressions=selected_expressions,
            message_components=message_components,
        )
        if not bot_message:
            return None

        from src.plugin_system.core.events_manager import events_manager

        continue_flag, modified_message = await events_manager.handle_mai_events(
            EventType.ON_SEND_AFTER_BUILD_MESSAGE,
            message=bot_message,
            stream_id=stream_id,
        )
        if not continue_flag:
            logger.info(
                "发送构建后 hook 取消消息",
                event_code="send.message.cancelled_by_after_build_hook",
                stream_id=stream_id,
                segment_type=message_segment.type,
            )
            return None
        if modified_message:
            if modified_message._modify_flags.modify_message_segments:
                bot_message.message_segment = Seg(type="seglist", data=modified_message.message_segments)
                bot_message.message_components = from_seg_to_components(bot_message.message_segment)
            if modified_message._modify_flags.modify_plain_text:
                bot_message.processed_plain_text = modified_message.plain_text
            selected = modified_message.additional_data.get("selected_expressions")
            if isinstance(selected, list):
                bot_message.selected_expressions = selected

        message_sender = UniversalMessageSender()
        sent_msg = await message_sender.send_message(
            bot_message,
            typing=typing,
            set_reply=set_reply,
            storage_message=storage_message,
            show_log=show_log,
        )
        if not sent_msg:
            logger.error(
                "消息发送失败",
                event_code="send.message.failed",
                stream_id=stream_id,
                segment_type=message_segment.type,
            )
            return None

        logger.debug(
            "消息发送完成",
            event_code="send.message.completed",
            stream_id=stream_id,
            segment_type=message_segment.type,
        )
        return bot_message
    except Exception:
        logger.exception(
            "消息发送异常",
            event_code="send.message.exception",
            stream_id=stream_id,
            segment_type=message_segment.type,
        )
        return None


async def message_to_stream(
    message_segment: Seg,
    stream_id: str,
    *,
    display_message: str = "",
    typing: bool = False,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    show_log: bool = True,
    selected_expressions: Optional[List[int]] = None,
    message_components: MessageComponentSequence | None = None,
) -> bool:
    return (
        await message_to_stream_with_message(
            message_segment=message_segment,
            stream_id=stream_id,
            display_message=display_message,
            typing=typing,
            set_reply=set_reply,
            reply_message=reply_message,
            storage_message=storage_message,
            show_log=show_log,
            selected_expressions=selected_expressions,
            message_components=message_components,
        )
        is not None
    )


async def components_to_stream_with_message(
    components: MessageComponentSequence,
    stream_id: str,
    *,
    display_message: str = "",
    typing: bool = False,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    show_log: bool = True,
    selected_expressions: Optional[List[int]] = None,
) -> MessageSending | None:
    message_segment = await from_components_to_seg(components)
    original_segment_dict = message_segment.to_dict()
    sent_message = await message_to_stream_with_message(
        message_segment=message_segment,
        stream_id=stream_id,
        display_message=display_message,
        typing=typing,
        set_reply=set_reply,
        reply_message=reply_message,
        storage_message=storage_message,
        show_log=show_log,
        selected_expressions=selected_expressions,
        message_components=components,
    )
    if sent_message and sent_message.message_segment.to_dict() == original_segment_dict:
        sent_message.message_components = components
    return sent_message


async def components_to_stream(
    components: MessageComponentSequence,
    stream_id: str,
    *,
    display_message: str = "",
    typing: bool = False,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    show_log: bool = True,
    selected_expressions: Optional[List[int]] = None,
) -> bool:
    return (
        await components_to_stream_with_message(
            components=components,
            stream_id=stream_id,
            display_message=display_message,
            typing=typing,
            set_reply=set_reply,
            reply_message=reply_message,
            storage_message=storage_message,
            show_log=show_log,
            selected_expressions=selected_expressions,
        )
        is not None
    )


async def text_to_stream_with_message(
    text: str,
    stream_id: str,
    *,
    typing: bool = False,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    selected_expressions: Optional[List[int]] = None,
) -> MessageSending | None:
    return await components_to_stream_with_message(
        components=MessageComponentSequence([TextComponent(text=text)]),
        stream_id=stream_id,
        typing=typing,
        set_reply=set_reply,
        reply_message=reply_message,
        storage_message=storage_message,
        selected_expressions=selected_expressions,
    )


async def image_to_stream_with_message(
    image_base64: str,
    stream_id: str,
    *,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    show_log: bool = True,
) -> MessageSending | None:
    return await components_to_stream_with_message(
        components=MessageComponentSequence([ImageComponent(base64_data=image_base64)]),
        stream_id=stream_id,
        set_reply=set_reply,
        reply_message=reply_message,
        storage_message=storage_message,
        show_log=show_log,
    )


async def image_to_stream(
    image_base64: str,
    stream_id: str,
    *,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    show_log: bool = True,
) -> bool:
    return (
        await image_to_stream_with_message(
            image_base64=image_base64,
            stream_id=stream_id,
            set_reply=set_reply,
            reply_message=reply_message,
            storage_message=storage_message,
            show_log=show_log,
        )
        is not None
    )


async def emoji_to_stream_with_message(
    emoji_base64: str,
    stream_id: str,
    *,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    show_log: bool = True,
) -> MessageSending | None:
    return await components_to_stream_with_message(
        components=MessageComponentSequence([EmojiComponent(base64_data=emoji_base64)]),
        stream_id=stream_id,
        set_reply=set_reply,
        reply_message=reply_message,
        storage_message=storage_message,
        show_log=show_log,
    )


async def emoji_to_stream(
    emoji_base64: str,
    stream_id: str,
    *,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    show_log: bool = True,
) -> bool:
    return (
        await emoji_to_stream_with_message(
            emoji_base64=emoji_base64,
            stream_id=stream_id,
            set_reply=set_reply,
            reply_message=reply_message,
            storage_message=storage_message,
            show_log=show_log,
        )
        is not None
    )


async def voice_to_stream_with_message(
    voice_base64: str,
    stream_id: str,
    *,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    show_log: bool = True,
) -> MessageSending | None:
    return await components_to_stream_with_message(
        components=MessageComponentSequence([VoiceComponent(base64_data=voice_base64)]),
        stream_id=stream_id,
        set_reply=set_reply,
        reply_message=reply_message,
        storage_message=storage_message,
        show_log=show_log,
    )


async def voice_to_stream(
    voice_base64: str,
    stream_id: str,
    *,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    show_log: bool = True,
) -> bool:
    return (
        await voice_to_stream_with_message(
            voice_base64=voice_base64,
            stream_id=stream_id,
            set_reply=set_reply,
            reply_message=reply_message,
            storage_message=storage_message,
            show_log=show_log,
        )
        is not None
    )


async def text_to_stream(
    text: str,
    stream_id: str,
    *,
    typing: bool = False,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    selected_expressions: Optional[List[int]] = None,
) -> bool:
    return (
        await text_to_stream_with_message(
            text=text,
            stream_id=stream_id,
            typing=typing,
            set_reply=set_reply,
            reply_message=reply_message,
            storage_message=storage_message,
            selected_expressions=selected_expressions,
        )
        is not None
    )
