"""Streaming import and sampling utilities for exported group chat history."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, TextIO


MAX_RAW_JSON_VALUE_CHARS = 2 * 1024 * 1024


class ChatHistoryFormatError(ValueError):
    """Raised when an uploaded history file is malformed or unsupported."""


@dataclass(frozen=True)
class ImportedChat:
    name: str
    source_id: str
    chat_type: str = "group"
    self_user_id: str = ""


@dataclass(frozen=True)
class ImportedParticipant:
    source_id: str
    name: str
    card: str
    message_count: int
    is_bot: bool = False


@dataclass(frozen=True)
class ImportedMessage:
    message_id: str
    timestamp: float
    sender_id: str
    sender_name: str
    sender_card: str
    content: str
    reply_to_id: str | None
    is_bot: bool
    is_low_signal: bool

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> ImportedMessage:
        return cls(
            message_id=str(value["message_id"]),
            timestamp=float(value["timestamp"]),
            sender_id=str(value["sender_id"]),
            sender_name=str(value.get("sender_name") or ""),
            sender_card=str(value.get("sender_card") or ""),
            content=str(value["content"]),
            reply_to_id=str(value["reply_to_id"]) if value.get("reply_to_id") else None,
            is_bot=bool(value.get("is_bot", False)),
            is_low_signal=bool(value.get("is_low_signal", False)),
        )


@dataclass(frozen=True)
class ChatHistoryAnalysis:
    source_format: str
    chat: ImportedChat
    total_messages: int
    retained_messages: int
    filtered_messages: int
    noise_counts: dict[str, int]
    participants: tuple[ImportedParticipant, ...]
    start_timestamp: float | None
    end_timestamp: float | None
    normalized_path: Path

    def to_json(self) -> dict[str, Any]:
        result = asdict(self)
        result["normalized_path"] = str(self.normalized_path)
        return result


@dataclass(frozen=True)
class HistoryWindow:
    window_id: str
    messages: tuple[ImportedMessage, ...]
    start_timestamp: float
    end_timestamp: float
    sender_ids: frozenset[str]
    char_count: int
    signal_score: float

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def evidence_ids(self) -> frozenset[str]:
        return frozenset(message.message_id for message in self.messages)


class _IncrementalJSONReader:
    """Small JSON token reader that never retains the consumed file prefix."""

    def __init__(self, source: TextIO, chunk_chars: int) -> None:
        if chunk_chars <= 0:
            raise ValueError("read_chunk_chars must be greater than zero")
        self._source = source
        self._chunk_chars = chunk_chars
        self._decoder = json.JSONDecoder()
        self._buffer = ""
        self._position = 0
        self._eof = False

    def _compact(self) -> None:
        if self._position and (self._position > 65_536 or self._position == len(self._buffer)):
            self._buffer = self._buffer[self._position :]
            self._position = 0

    def _read_more(self) -> bool:
        if self._eof:
            return False
        self._compact()
        chunk = self._source.read(self._chunk_chars)
        if chunk:
            self._buffer += chunk
            return True
        self._eof = True
        return False

    def _ensure_available(self) -> bool:
        while self._position >= len(self._buffer):
            if not self._read_more():
                return False
        return True

    def skip_whitespace(self) -> None:
        while True:
            while self._position < len(self._buffer) and self._buffer[self._position].isspace():
                self._position += 1
            if self._position < len(self._buffer) or not self._read_more():
                return

    def peek(self) -> str:
        self.skip_whitespace()
        if not self._ensure_available():
            raise ChatHistoryFormatError("聊天记录 JSON 意外结束")
        return self._buffer[self._position]

    def expect(self, expected: str) -> None:
        actual = self.peek()
        if actual != expected:
            raise ChatHistoryFormatError(f"聊天记录 JSON 格式错误：预期 {expected!r}，实际为 {actual!r}")
        self._position += 1

    def decode_value(self) -> Any:
        self.skip_whitespace()
        self._compact()
        start = self._position
        while True:
            try:
                value, end = self._decoder.raw_decode(self._buffer, self._position)
            except json.JSONDecodeError as error:
                if len(self._buffer) - start > MAX_RAW_JSON_VALUE_CHARS:
                    raise ChatHistoryFormatError("聊天记录中的单个 JSON 值超过大小限制") from error
                if self._read_more():
                    continue
                raise ChatHistoryFormatError(f"无法解析聊天记录 JSON：{error.msg}") from error
            if end - start > MAX_RAW_JSON_VALUE_CHARS:
                raise ChatHistoryFormatError("聊天记录中的单个 JSON 值超过大小限制")
            self._position = end
            return value


_PLACEHOLDER_RE = re.compile(
    r"^(?:\[(?:图片|动画表情|表情|语音|视频|文件|JSON消息|XML消息|转发消息|卡片)(?::[^\]]*)?\]\s*)+$",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")
MAX_MESSAGE_ID_CHARS = 64
MAX_SENDER_ID_CHARS = 64
MAX_DISPLAY_NAME_CHARS = 256
MAX_MESSAGE_CONTENT_CHARS = 6_000
MAX_TIMESTAMP_SECONDS = 32_503_680_000.0
_LOW_SIGNAL_CONTENT = {
    "嗯",
    "哦",
    "啊",
    "行",
    "好",
    "对",
    "是",
    "可",
    "成",
    "草",
    "艹",
    "6",
    "66",
    "666",
    "1",
    "+1",
    "ok",
    "okay",
    "yes",
    "no",
    "收到",
    "确实",
    "哈哈",
    "哈哈哈",
}


def _iter_export_events(source_path: Path, read_chunk_chars: int) -> Iterator[tuple[str, str, Any]]:
    """Yield (kind, key, value), streaming members of the messages array."""

    try:
        source = source_path.open("r", encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise ChatHistoryFormatError(f"无法读取聊天记录文件：{error}") from error

    with source:
        reader = _IncrementalJSONReader(source, read_chunk_chars)
        reader.expect("{")
        if reader.peek() == "}":
            reader.expect("}")
            return

        while True:
            key = reader.decode_value()
            if not isinstance(key, str):
                raise ChatHistoryFormatError("聊天记录 JSON 的字段名必须是字符串")
            reader.expect(":")

            if key == "messages":
                reader.expect("[")
                if reader.peek() != "]":
                    while True:
                        yield "message", key, reader.decode_value()
                        separator = reader.peek()
                        if separator == "]":
                            break
                        reader.expect(",")
                reader.expect("]")
            else:
                yield "field", key, reader.decode_value()

            separator = reader.peek()
            if separator == "}":
                reader.expect("}")
                break
            reader.expect(",")


def _clean_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text.replace("\x00", " ")).strip()


def _bounded_identifier(value: Any, maximum: int) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return ""
    normalized = str(value).strip()
    return normalized if 0 < len(normalized) <= maximum else ""


def _bounded_display_text(value: Any) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return ""
    return _clean_text(str(value))[:MAX_DISPLAY_NAME_CHARS]


def _find_export_self_user_id(source_path: Path, read_chunk_chars: int) -> str:
    with closing(_iter_export_events(source_path, read_chunk_chars)) as events:
        for event, key, value in events:
            if event != "field" or key != "chatInfo" or not isinstance(value, dict):
                continue
            return _bounded_identifier(value.get("selfUin"), MAX_SENDER_ID_CHARS)
    return ""


def _extract_message_text(raw: dict[str, Any]) -> tuple[str, str | None]:
    content = raw.get("content")
    if not isinstance(content, dict):
        return "", None

    elements = content.get("elements")
    text_parts: list[str] = []
    text_chars = 0
    reply_to_id: str | None = None
    has_elements = isinstance(elements, list)
    if has_elements:
        for element in elements:
            if not isinstance(element, dict):
                continue
            element_type = str(element.get("type") or "").lower()
            data = element.get("data")
            if not isinstance(data, dict):
                continue
            if element_type == "reply" and data.get("referencedMessageId") is not None:
                reply_to_id = str(data["referencedMessageId"])
            elif element_type == "text":
                value = data.get("text")
                if isinstance(value, str) and text_chars < MAX_MESSAGE_CONTENT_CHARS:
                    bounded = value[: MAX_MESSAGE_CONTENT_CHARS - text_chars]
                    text_parts.append(bounded)
                    text_chars += len(bounded)

    if text_parts:
        return _clean_text("".join(text_parts))[:MAX_MESSAGE_CONTENT_CHARS], reply_to_id
    if has_elements:
        return "", reply_to_id

    fallback = content.get("text")
    if isinstance(fallback, str):
        return _clean_text(fallback)[:MAX_MESSAGE_CONTENT_CHARS], reply_to_id
    return "", reply_to_id


def _is_punctuation_only(content: str) -> bool:
    meaningful = [character for character in content if not character.isspace()]
    return bool(meaningful) and all(unicodedata.category(character)[0] in {"P", "S"} for character in meaningful)


def _is_low_signal(content: str) -> bool:
    normalized = content.casefold().strip().rstrip("!！.。~～")
    return normalized in _LOW_SIGNAL_CONTENT


def _normalize_timestamp(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp /= 1000.0
    if not math.isfinite(timestamp) or not 0 < timestamp <= MAX_TIMESTAMP_SECONDS:
        return None
    return timestamp


def _normalize_message(raw: Any, bot_user_ids: set[str]) -> tuple[ImportedMessage | None, str | None]:
    if not isinstance(raw, dict):
        return None, "invalid_message"
    if raw.get("recalled"):
        return None, "recalled"
    if raw.get("system") or str(raw.get("type") or "").lower() == "system":
        return None, "system"

    content, reply_to_id = _extract_message_text(raw)
    if not content or _PLACEHOLDER_RE.fullmatch(content):
        return None, "no_text"
    if _is_punctuation_only(content):
        return None, "punctuation_only"

    timestamp = _normalize_timestamp(raw.get("timestamp"))
    if timestamp is None:
        return None, "invalid_timestamp"

    sender = raw.get("sender")
    sender = sender if isinstance(sender, dict) else {}
    sender_id = _bounded_identifier(sender.get("uin") or sender.get("uid"), MAX_SENDER_ID_CHARS)
    if not sender_id:
        return None, "missing_sender"
    message_id = _bounded_identifier(raw.get("id"), MAX_MESSAGE_ID_CHARS)
    if not message_id:
        return None, "missing_message_id"
    reply_to_id = _bounded_identifier(reply_to_id, MAX_MESSAGE_ID_CHARS) or None

    return (
        ImportedMessage(
            message_id=message_id,
            timestamp=timestamp,
            sender_id=sender_id,
            sender_name=_bounded_display_text(sender.get("name")),
            sender_card=_bounded_display_text(sender.get("groupCard")),
            content=content,
            reply_to_id=reply_to_id,
            is_bot=sender_id in bot_user_ids,
            is_low_signal=_is_low_signal(content),
        ),
        None,
    )


def analyze_qq_chat_export(
    source_path: str | Path,
    normalized_path: str | Path,
    *,
    bot_user_ids: set[str] | None = None,
    read_chunk_chars: int = 256 * 1024,
    duplicate_burst_seconds: float = 120.0,
) -> ChatHistoryAnalysis:
    """Analyze a QQChatExporter group export and write filtered JSONL."""

    source_path = Path(source_path)
    normalized_path = Path(normalized_path)
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    explicit_bot_ids = {str(user_id) for user_id in (bot_user_ids or set())}
    effective_bot_ids = set(explicit_bot_ids)
    if self_user_id := _find_export_self_user_id(source_path, read_chunk_chars):
        effective_bot_ids.add(self_user_id)
    fields: dict[str, Any] = {}
    noise_counts: Counter[str] = Counter()
    participants: dict[str, dict[str, Any]] = {}
    seen_message_ids: set[str] = set()
    burst_state: dict[tuple[str, bytes], tuple[float, int]] = {}
    total_messages = 0
    retained_messages = 0
    start_timestamp: float | None = None
    end_timestamp: float | None = None

    try:
        with normalized_path.open("w", encoding="utf-8") as normalized_file:
            for event, key, value in _iter_export_events(source_path, read_chunk_chars):
                if event == "field":
                    if key in {"metadata", "chatInfo"}:
                        fields[key] = value
                    if key == "chatInfo" and isinstance(value, dict):
                        self_user_id = _bounded_identifier(value.get("selfUin"), MAX_SENDER_ID_CHARS)
                        if self_user_id:
                            effective_bot_ids.add(self_user_id)
                    continue

                total_messages += 1
                message, reason = _normalize_message(value, effective_bot_ids)
                if message is None:
                    noise_counts[reason or "invalid_message"] += 1
                    continue
                if message.message_id in seen_message_ids:
                    noise_counts["duplicate_id"] += 1
                    continue
                seen_message_ids.add(message.message_id)

                content_digest = hashlib.blake2s(message.content.casefold().encode(), digest_size=16).digest()
                burst_key = (message.sender_id, content_digest)
                previous_timestamp, previous_count = burst_state.get(burst_key, (float("-inf"), 0))
                if 0 <= message.timestamp - previous_timestamp <= duplicate_burst_seconds:
                    burst_count = previous_count + 1
                else:
                    burst_count = 1
                burst_state[burst_key] = (message.timestamp, burst_count)
                if burst_count > 2:
                    noise_counts["duplicate_burst"] += 1
                    continue

                normalized_file.write(json.dumps(message.to_json(), ensure_ascii=False, separators=(",", ":")))
                normalized_file.write("\n")
                retained_messages += 1
                start_timestamp = (
                    message.timestamp if start_timestamp is None else min(start_timestamp, message.timestamp)
                )
                end_timestamp = message.timestamp if end_timestamp is None else max(end_timestamp, message.timestamp)
                participant = participants.setdefault(
                    message.sender_id,
                    {
                        "source_id": message.sender_id,
                        "name": message.sender_name,
                        "card": message.sender_card,
                        "message_count": 0,
                        "is_bot": message.is_bot,
                    },
                )
                participant["message_count"] += 1
                if message.sender_card:
                    participant["card"] = message.sender_card
                if message.sender_name:
                    participant["name"] = message.sender_name
    except Exception:
        normalized_path.unlink(missing_ok=True)
        raise

    metadata = fields.get("metadata")
    chat_info = fields.get("chatInfo")
    if not isinstance(metadata, dict) or str(metadata.get("name") or "").casefold() != "qqchatexporter":
        normalized_path.unlink(missing_ok=True)
        raise ChatHistoryFormatError("不支持的聊天记录格式，仅支持 QQChatExporter JSON")
    if not isinstance(chat_info, dict) or str(chat_info.get("type") or "").casefold() != "group":
        normalized_path.unlink(missing_ok=True)
        raise ChatHistoryFormatError("仅支持 QQ 群聊导出记录")

    source_id = _bounded_identifier(
        chat_info.get("peerUin") or chat_info.get("peerUid") or chat_info.get("uin"),
        MAX_SENDER_ID_CHARS,
    )
    if not source_id:
        normalized_path.unlink(missing_ok=True)
        raise ChatHistoryFormatError("聊天记录缺少群号")
    chat = ImportedChat(
        name=_bounded_display_text(chat_info.get("name")) or source_id,
        source_id=source_id,
        self_user_id=_bounded_identifier(chat_info.get("selfUin"), MAX_SENDER_ID_CHARS),
    )
    participant_items = tuple(
        ImportedParticipant(**participant)
        for participant in sorted(participants.values(), key=lambda item: (-item["message_count"], item["source_id"]))
    )
    return ChatHistoryAnalysis(
        source_format="qq_chat_exporter",
        chat=chat,
        total_messages=total_messages,
        retained_messages=retained_messages,
        filtered_messages=total_messages - retained_messages,
        noise_counts=dict(sorted(noise_counts.items())),
        participants=participant_items,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        normalized_path=normalized_path,
    )


def write_normalized_messages(path: str | Path, messages: Iterable[ImportedMessage]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for message in messages:
            output.write(json.dumps(message.to_json(), ensure_ascii=False, separators=(",", ":")))
            output.write("\n")


def iter_normalized_messages(path: str | Path) -> Iterator[ImportedMessage]:
    try:
        with Path(path).open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise TypeError("message must be an object")
                    yield ImportedMessage.from_json(value)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                    raise ChatHistoryFormatError(f"规范化聊天记录第 {line_number} 行损坏") from error
    except OSError as error:
        raise ChatHistoryFormatError(f"无法读取规范化聊天记录：{error}") from error


def _create_window(index: int, messages: list[ImportedMessage]) -> HistoryWindow:
    high_signal_messages = sum(not message.is_low_signal and not message.is_bot for message in messages)
    replies = sum(message.reply_to_id is not None for message in messages)
    unique_content = len({message.content.casefold() for message in messages})
    sender_ids = frozenset(message.sender_id for message in messages if not message.is_bot)
    signal_score = high_signal_messages * 2.0 + replies * 0.75 + unique_content * 0.25 + len(sender_ids) * 0.5
    return HistoryWindow(
        window_id=f"window-{index:06d}",
        messages=tuple(messages),
        start_timestamp=messages[0].timestamp,
        end_timestamp=messages[-1].timestamp,
        sender_ids=sender_ids,
        char_count=sum(len(message.content) for message in messages),
        signal_score=signal_score,
    )


def build_history_windows(
    normalized_path: str | Path,
    *,
    max_messages: int = 80,
    max_chars: int = 12_000,
    max_gap_seconds: float = 20 * 60,
    overlap_messages: int = 6,
) -> list[HistoryWindow]:
    """Build coherent windows bounded by time, count, and prompt size."""

    if max_messages <= 0 or max_chars <= 0:
        raise ValueError("window limits must be greater than zero")
    if overlap_messages < 0 or overlap_messages >= max_messages:
        raise ValueError("overlap_messages must be between zero and max_messages - 1")

    windows: list[HistoryWindow] = []
    current: list[ImportedMessage] = []
    current_chars = 0

    def flush(*, keep_overlap: bool) -> None:
        nonlocal current, current_chars
        if not current:
            return
        windows.append(_create_window(len(windows) + 1, current))
        if keep_overlap and overlap_messages:
            current = current[-overlap_messages:]
            current_chars = sum(len(message.content) for message in current)
        else:
            current = []
            current_chars = 0

    for message in iter_normalized_messages(normalized_path):
        if current:
            gap = message.timestamp - current[-1].timestamp
            if gap > max_gap_seconds or gap < 0:
                flush(keep_overlap=False)
            elif len(current) >= max_messages or current_chars + len(message.content) > max_chars:
                flush(keep_overlap=True)
                if len(current) >= max_messages or current_chars + len(message.content) > max_chars:
                    current = []
                    current_chars = 0

        current.append(message)
        current_chars += len(message.content)
    flush(keep_overlap=False)
    return windows


def select_history_windows(
    windows: Iterable[HistoryWindow],
    *,
    budget: int,
    priority_sender_ids: Iterable[str] = (),
) -> list[HistoryWindow]:
    """Select deterministic, time-distributed, participant-covering windows."""

    candidates = list(windows)
    if budget <= 0 or not candidates:
        return []
    if len(candidates) <= budget:
        return candidates

    priority = frozenset(str(sender_id) for sender_id in priority_sender_ids)
    selected_indices: list[int] = []
    covered_senders: set[str] = set()

    for slot in range(budget):
        target = slot * (len(candidates) - 1) / max(1, budget - 1)
        best_index = max(
            (index for index in range(len(candidates)) if index not in selected_indices),
            key=lambda index: (
                len((candidates[index].sender_ids & priority) - covered_senders) * 5.0
                + candidates[index].signal_score
                - abs(index - target) * 0.75,
                -abs(index - target),
                -index,
            ),
        )
        selected_indices.append(best_index)
        covered_senders.update(candidates[best_index].sender_ids & priority)

    return [candidates[index] for index in sorted(selected_indices)]


def history_window_to_jsonl(window: HistoryWindow) -> str:
    """Serialize model input as inert JSONL with stable evidence IDs."""

    rows = []
    for message in window.messages:
        rendered = json.dumps(
            {
                "evidence_id": message.message_id,
                "timestamp": message.timestamp,
                "sender_id": message.sender_id,
                "sender_name": message.sender_card or message.sender_name,
                "content": message.content,
                "reply_to_id": message.reply_to_id,
                "is_bot": message.is_bot,
                "low_signal": message.is_low_signal,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        rows.append(rendered.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))
    return "\n".join(rows)


ProgressCallback = Callable[[int, int], None]
