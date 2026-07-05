"""
发送API模块

专门负责发送各种类型的消息，采用标准Python包设计模式

使用方式：
    from src.plugin_system.apis import send_api

    # 方式1：直接使用stream_id（推荐）
    await send_api.text_to_stream("hello", stream_id)
    await send_api.emoji_to_stream(emoji_base64, stream_id)
    await send_api.custom_to_stream("video", video_data, stream_id)

    # 方式2：使用群聊/私聊指定函数
    await send_api.text_to_group("hello", "123456")
    await send_api.text_to_user("hello", "987654")

    # 方式3：使用通用custom_message函数
    await send_api.custom_message("video", video_data, "123456", True)
"""

from typing import Optional, Union, Dict, List, TYPE_CHECKING, Tuple

from src.common.logger import get_logger
from src.common.data_models.message_data_model import ReplyContentType
from src.services import send_service
from maim_message import Seg, UserInfo, MessageBase, BaseMessageInfo

if TYPE_CHECKING:
    from src.common.data_models.database_data_model import DatabaseMessages
    from src.common.data_models.message_data_model import ReplySetModel, ReplyContent, ForwardNode

logger = get_logger("send_api")


# =============================================================================
# 内部实现函数（不暴露给外部）
# =============================================================================


async def _send_to_target(
    message_segment: Seg,
    stream_id: str,
    display_message: str = "",
    typing: bool = False,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    show_log: bool = True,
    selected_expressions: Optional[List[int]] = None,
) -> bool:
    """向指定目标发送消息的内部实现

    Args:
        message_segment:
        stream_id: 目标流ID
        display_message: 显示消息
        typing: 是否模拟打字等待。
        reply_to: 回复消息，格式为"发送者:消息内容"
        storage_message: 是否存储消息到数据库
        show_log: 发送是否显示日志

    Returns:
        bool: 是否发送成功
    """
    return await send_service.message_to_stream(
        message_segment=message_segment,
        stream_id=stream_id,
        display_message=display_message,
        typing=typing,
        set_reply=set_reply,
        reply_message=reply_message,
        storage_message=storage_message,
        show_log=show_log,
        selected_expressions=selected_expressions,
    )


def db_message_to_message_recv(message_obj: "DatabaseMessages"):
    """将数据库dict重建为MessageRecv对象
    Args:
        message_dict: 消息字典

    Returns:
        Optional[MessageRecv]: 找到的消息，如果没找到则返回None
    """
    return send_service.db_message_to_message_recv(message_obj)


# =============================================================================
# 公共API函数 - 预定义类型的发送函数
# =============================================================================


async def text_to_stream(
    text: str,
    stream_id: str,
    typing: bool = False,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    storage_message: bool = True,
    selected_expressions: Optional[List[int]] = None,
) -> bool:
    """向指定流发送文本消息

    Args:
        text: 要发送的文本内容
        stream_id: 聊天流ID
        typing: 是否显示正在输入
        reply_to: 回复消息，格式为"发送者:消息内容"
        storage_message: 是否存储消息到数据库

    Returns:
        bool: 是否发送成功
    """
    return await send_service.text_to_stream(
        text=text,
        stream_id=stream_id,
        typing=typing,
        set_reply=set_reply,
        reply_message=reply_message,
        storage_message=storage_message,
        selected_expressions=selected_expressions,
    )


async def emoji_to_stream(
    emoji_base64: str,
    stream_id: str,
    storage_message: bool = True,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
) -> bool:
    """向指定流发送表情包

    Args:
        emoji_base64: 表情包的base64编码
        stream_id: 聊天流ID
        storage_message: 是否存储消息到数据库

    Returns:
        bool: 是否发送成功
    """
    return await send_service.emoji_to_stream(
        emoji_base64=emoji_base64,
        stream_id=stream_id,
        set_reply=set_reply,
        reply_message=reply_message,
        storage_message=storage_message,
    )


async def image_to_stream(
    image_base64: str,
    stream_id: str,
    storage_message: bool = True,
    set_reply: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
) -> bool:
    """向指定流发送图片

    Args:
        image_base64: 图片的base64编码
        stream_id: 聊天流ID
        storage_message: 是否存储消息到数据库

    Returns:
        bool: 是否发送成功
    """
    return await send_service.image_to_stream(
        image_base64=image_base64,
        stream_id=stream_id,
        set_reply=set_reply,
        reply_message=reply_message,
        storage_message=storage_message,
    )


async def command_to_stream(
    command: Union[str, dict],
    stream_id: str,
    storage_message: bool = True,
    display_message: str = "",
) -> bool:
    """向指定流发送命令

    Args:
        command: 命令
        stream_id: 聊天流ID
        storage_message: 是否存储消息到数据库
        display_message: 显示消息

    Returns:
        bool: 是否发送成功
    """
    return await _send_to_target(
        message_segment=Seg(type="command", data=command),  # type: ignore
        stream_id=stream_id,
        display_message=display_message,
        typing=False,
        storage_message=storage_message,
        set_reply=False,
    )


async def custom_to_stream(
    message_type: str,
    content: str | Dict,
    stream_id: str,
    display_message: str = "",
    typing: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    set_reply: bool = False,
    storage_message: bool = True,
    show_log: bool = True,
) -> bool:
    """向指定流发送自定义类型消息

    Args:
        message_type: 消息类型，如"text"、"image"、"emoji"、"video"、"file"等
        content: 消息内容（通常是base64编码或文本）
        stream_id: 聊天流ID
        display_message: 显示消息
        typing: 是否显示正在输入
        reply_to: 回复消息，格式为"发送者:消息内容"
        storage_message: 是否存储消息到数据库
        show_log: 是否显示日志
    Returns:
        bool: 是否发送成功
    """
    return await _send_to_target(
        message_segment=Seg(type=message_type, data=content),  # type: ignore
        stream_id=stream_id,
        display_message=display_message,
        typing=typing,
        reply_message=reply_message,
        set_reply=set_reply,
        storage_message=storage_message,
        show_log=show_log,
    )


async def custom_reply_set_to_stream(
    reply_set: "ReplySetModel",
    stream_id: str,
    display_message: str = "",  # 基本没用
    typing: bool = False,
    reply_message: Optional["DatabaseMessages"] = None,
    set_reply: bool = False,
    storage_message: bool = True,
    show_log: bool = True,
) -> bool:
    """
    向指定流发送混合型消息集

    Args:
        reply_set: ReplySetModel 对象，包含多个 ReplyContent
        stream_id: 聊天流ID
        display_message: 显示消息
        typing: 是否显示正在输入
        reply_to: 回复消息，格式为"发送者:消息内容"
        storage_message: 是否存储消息到数据库
        show_log: 是否显示日志
    """
    flag: bool = True
    for reply_content in reply_set.reply_data:
        status: bool = False
        message_seg, need_typing = _parse_content_to_seg(reply_content)
        status = await _send_to_target(
            message_segment=message_seg,
            stream_id=stream_id,
            display_message=display_message,
            typing=bool(need_typing and typing),
            reply_message=reply_message,
            set_reply=set_reply,
            storage_message=storage_message,
            show_log=show_log,
        )
        if not status:
            flag = False
            logger.error(
                f"[SendAPI] 发送{repr(reply_content.content_type)}消息失败，消息内容：{str(reply_content.content)[:100]}"
            )

    return flag


def _parse_content_to_seg(reply_content: "ReplyContent") -> Tuple[Seg, bool]:
    """
    把 ReplyContent 转换为 Seg 结构 (Forward 中仅递归一次)
    Args:
        reply_content: ReplyContent 对象
    Returns:
        Tuple[Seg, bool]: 转换后的 Seg 结构和是否需要typing的标志
    """
    content_type = reply_content.content_type
    if content_type == ReplyContentType.TEXT:
        text_data: str = reply_content.content  # type: ignore
        return Seg(type="text", data=text_data), True
    elif content_type == ReplyContentType.IMAGE:
        return Seg(type="image", data=reply_content.content), False  # type: ignore
    elif content_type == ReplyContentType.EMOJI:
        return Seg(type="emoji", data=reply_content.content), False  # type: ignore
    elif content_type == ReplyContentType.COMMAND:
        return Seg(type="command", data=reply_content.content), False  # type: ignore
    elif content_type == ReplyContentType.VOICE:
        return Seg(type="voice", data=reply_content.content), False  # type: ignore
    elif content_type == ReplyContentType.HYBRID:
        hybrid_message_list_data: List[ReplyContent] = reply_content.content  # type: ignore
        assert isinstance(hybrid_message_list_data, list), "混合类型内容必须是列表"
        sub_seg_list: List[Seg] = []
        for sub_content in hybrid_message_list_data:
            sub_content_type = sub_content.content_type
            sub_content_data = sub_content.content

            if sub_content_type == ReplyContentType.TEXT:
                sub_seg_list.append(Seg(type="text", data=sub_content_data))  # type: ignore
            elif sub_content_type == ReplyContentType.IMAGE:
                sub_seg_list.append(Seg(type="image", data=sub_content_data))  # type: ignore
            elif sub_content_type == ReplyContentType.EMOJI:
                sub_seg_list.append(Seg(type="emoji", data=sub_content_data))  # type: ignore
            else:
                logger.warning(f"[SendAPI] 混合类型中不支持的子内容类型: {repr(sub_content_type)}")
                continue
        return Seg(type="seglist", data=sub_seg_list), True
    elif content_type == ReplyContentType.FORWARD:
        forward_message_list_data: List["ForwardNode"] = reply_content.content  # type: ignore
        assert isinstance(forward_message_list_data, list), "转发类型内容必须是列表"
        forward_message_list: List[Dict] = []
        for forward_node in forward_message_list_data:
            message_segment = Seg(type="id", data=forward_node.content)  # type: ignore
            user_info: Optional[UserInfo] = None
            if forward_node.user_id and forward_node.user_nickname:
                assert isinstance(forward_node.content, list), "转发节点内容必须是列表"
                user_info = UserInfo(user_id=forward_node.user_id, user_nickname=forward_node.user_nickname)
                single_node_content: List[Seg] = []
                for sub_content in forward_node.content:
                    if sub_content.content_type != ReplyContentType.FORWARD:
                        sub_seg, _ = _parse_content_to_seg(sub_content)
                        single_node_content.append(sub_seg)
                message_segment = Seg(type="seglist", data=single_node_content)
            forward_message_list.append(
                MessageBase(
                    message_segment=message_segment, message_info=BaseMessageInfo(user_info=user_info)
                ).to_dict()
            )
        return Seg(type="forward", data=forward_message_list), False  # type: ignore
    else:
        message_type_in_str = content_type.value if isinstance(content_type, ReplyContentType) else str(content_type)
        return Seg(type=message_type_in_str, data=reply_content.content), True  # type: ignore
