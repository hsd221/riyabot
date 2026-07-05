import base64
import hashlib
from dataclasses import dataclass, field
from typing import Any, Union

from maim_message import BaseMessageInfo, MessageBase, Seg


def _hash_base64_data(data: str | None) -> str | None:
    if not data:
        return None
    normalized_data = data.encode("ascii", errors="ignore").decode("ascii")
    try:
        raw_data = base64.b64decode(normalized_data)
    except Exception:
        raw_data = normalized_data.encode("utf-8", errors="ignore")
    return hashlib.md5(raw_data).hexdigest()


@dataclass
class TextComponent:
    text: str


@dataclass
class ImageComponent:
    base64_data: str | None = None
    image_hash: str | None = None
    description: str | None = None


@dataclass
class EmojiComponent:
    base64_data: str | None = None
    emoji_hash: str | None = None
    description: str | None = None


@dataclass
class VoiceComponent:
    base64_data: str | None = None
    voice_hash: str | None = None
    transcript: str | None = None


@dataclass
class AtComponent:
    target_user_id: str
    target_name: str | None = None


@dataclass
class ReplyComponent:
    target_message_id: str
    target_text: str | None = None


@dataclass
class FileComponent:
    name: str
    size: str | None = None
    url: str | None = None
    raw_data: Any = None


@dataclass
class ForwardComponent:
    nodes: list["MessageComponentSequence"] = field(default_factory=list)
    raw_data: list[Any] | None = None


@dataclass
class SegmentListComponent:
    sequence: "MessageComponentSequence" = field(default_factory=lambda: MessageComponentSequence(force_seglist=True))


@dataclass
class UnknownComponent:
    segment_type: str
    data: Any = None


MessageComponent = Union[
    TextComponent,
    ImageComponent,
    EmojiComponent,
    VoiceComponent,
    AtComponent,
    ReplyComponent,
    FileComponent,
    ForwardComponent,
    SegmentListComponent,
    UnknownComponent,
]


@dataclass
class MessageComponentSequence:
    components: list[MessageComponent] = field(default_factory=list)
    force_seglist: bool = False

    def extend(self, other: "MessageComponentSequence") -> None:
        self.components.extend(other.components)


def from_seg_to_components(seg: Seg | None) -> MessageComponentSequence:
    if seg is None:
        return MessageComponentSequence()

    segment_type = getattr(seg, "type", "")
    data = getattr(seg, "data", None)

    if segment_type == "seglist":
        sequence = MessageComponentSequence(force_seglist=True)
        for child in data or []:
            if getattr(child, "type", "") == "seglist":
                sequence.components.append(SegmentListComponent(sequence=from_seg_to_components(child)))
            else:
                sequence.extend(from_seg_to_components(child))
        return sequence

    if segment_type == "text":
        return MessageComponentSequence([TextComponent(text=str(data) if data is not None else "")])
    if segment_type == "image":
        base64_data = data if isinstance(data, str) else None
        return MessageComponentSequence(
            [ImageComponent(base64_data=base64_data, image_hash=_hash_base64_data(base64_data))]
        )
    if segment_type == "emoji":
        base64_data = data if isinstance(data, str) else None
        return MessageComponentSequence(
            [EmojiComponent(base64_data=base64_data, emoji_hash=_hash_base64_data(base64_data))]
        )
    if segment_type == "voice":
        base64_data = data if isinstance(data, str) else None
        return MessageComponentSequence(
            [VoiceComponent(base64_data=base64_data, voice_hash=_hash_base64_data(base64_data))]
        )
    if segment_type == "at":
        return MessageComponentSequence([AtComponent(target_user_id=str(data) if data is not None else "")])
    if segment_type == "reply":
        return MessageComponentSequence([ReplyComponent(target_message_id=str(data) if data is not None else "")])
    if segment_type == "file":
        if isinstance(data, dict):
            return MessageComponentSequence(
                [
                    FileComponent(
                        name=str(data.get("name") or data.get("file") or "未知文件"),
                        size=str(data.get("size") or data.get("file_size") or "") or None,
                        url=str(data.get("url") or "") or None,
                        raw_data=data,
                    )
                ]
            )
        return MessageComponentSequence([FileComponent(name=str(data) if data is not None else "未知文件")])
    if segment_type == "forward":
        nodes = []
        if isinstance(data, list):
            for node_dict in data:
                try:
                    message = MessageBase.from_dict(node_dict)
                    nodes.append(from_seg_to_components(message.message_segment))
                except Exception:
                    nodes.append(MessageComponentSequence([UnknownComponent(segment_type="forward_node", data=node_dict)]))
        return MessageComponentSequence([ForwardComponent(nodes=nodes, raw_data=data if isinstance(data, list) else None)])

    return MessageComponentSequence([UnknownComponent(segment_type=segment_type, data=data)])


async def from_components_to_seg(seq: MessageComponentSequence) -> Seg:
    return _sequence_to_seg_sync(seq)


def components_to_plain_text(seq: MessageComponentSequence) -> str:
    plain_parts = [_component_to_plain_text(component) for component in seq.components]
    return " ".join(part for part in plain_parts if part)


def _component_to_seg(component: MessageComponent) -> Seg:
    if isinstance(component, TextComponent):
        return Seg(type="text", data=component.text)
    if isinstance(component, ImageComponent):
        if component.base64_data:
            return Seg(type="image", data=component.base64_data)
        return Seg(type="text", data=_component_to_plain_text(component))
    if isinstance(component, EmojiComponent):
        if component.base64_data:
            return Seg(type="emoji", data=component.base64_data)
        return Seg(type="text", data=_component_to_plain_text(component))
    if isinstance(component, VoiceComponent):
        if component.base64_data:
            return Seg(type="voice", data=component.base64_data)
        return Seg(type="text", data=_component_to_plain_text(component))
    if isinstance(component, AtComponent):
        return Seg(type="at", data=component.target_user_id)
    if isinstance(component, ReplyComponent):
        return Seg(type="reply", data=component.target_message_id)
    if isinstance(component, FileComponent):
        if component.raw_data is not None:
            return Seg(type="file", data=component.raw_data)
        return Seg(
            type="file",
            data={
                "name": component.name,
                "size": component.size,
                "url": component.url,
            },
        )
    if isinstance(component, ForwardComponent):
        if component.raw_data is not None:
            return Seg(type="forward", data=component.raw_data)
        forward_nodes = []
        for node in component.nodes:
            node_seg = _sequence_to_seg_sync(node)
            forward_nodes.append(MessageBase(message_segment=node_seg, message_info=BaseMessageInfo()).to_dict())
        return Seg(type="forward", data=forward_nodes)
    if isinstance(component, SegmentListComponent):
        return _sequence_to_seg_sync(component.sequence)
    return Seg(type=component.segment_type, data=component.data)


def _sequence_to_seg_sync(seq: MessageComponentSequence) -> Seg:
    segments = [_component_to_seg(component) for component in seq.components]
    if seq.force_seglist:
        return Seg(type="seglist", data=segments)
    if not segments:
        return Seg(type="text", data="")
    if len(segments) == 1:
        return segments[0]
    return Seg(type="seglist", data=segments)


def _component_to_plain_text(component: MessageComponent) -> str:
    if isinstance(component, TextComponent):
        return component.text
    if isinstance(component, ImageComponent):
        return f"[图片：{component.description}]" if component.description else "[图片]"
    if isinstance(component, EmojiComponent):
        return f"[表情包：{component.description}]" if component.description else "[表情包]"
    if isinstance(component, VoiceComponent):
        return f"[语音：{component.transcript}]" if component.transcript else "[语音消息]"
    if isinstance(component, AtComponent):
        display_name = component.target_name or component.target_user_id
        return f"[@{display_name}]"
    if isinstance(component, ReplyComponent):
        if component.target_text:
            return f"[回复：{component.target_text}]"
        return f"[回复:{component.target_message_id}]"
    if isinstance(component, FileComponent):
        file_text = f"[文件: {component.name}"
        if component.size:
            file_text += f", 大小: {component.size}"
        file_text += "]"
        if component.url:
            file_text += f" 链接: {component.url}"
        return file_text
    if isinstance(component, ForwardComponent):
        node_text = [components_to_plain_text(node) for node in component.nodes]
        return "[合并消息]: " + "\n--  ".join(text for text in node_text if text)
    if isinstance(component, SegmentListComponent):
        return components_to_plain_text(component.sequence)
    if component.data is None:
        return f"[{component.segment_type}]"
    return f"[{component.segment_type}:{component.data}]"
