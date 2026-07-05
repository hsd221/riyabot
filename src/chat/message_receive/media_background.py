import asyncio
import base64
import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional

from src.chat.utils.utils_image import get_image_manager
from src.chat.utils.utils_voice import get_voice_text
from src.common.database.database_model import Emoji, EmojiDescriptionCache, ImageDescriptions, Images, Messages
from src.common.logger import get_logger

logger = get_logger("chat_media_background")


_MEDIA_PLACEHOLDERS = {
    "image": "[图片]",
    "emoji": "[表情包]",
    "voice": "[语音消息]",
}


@dataclass
class _MediaTaskState:
    kind: str
    media_hash: str
    status: str = "pending"
    result_text: Optional[str] = None
    task: Optional[asyncio.Task] = None
    message_refs: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class _MessageMediaRef:
    kind: str
    task_key: str
    occurrence_index: int


_media_task_states: dict[str, _MediaTaskState] = {}
_message_media_refs: dict[str, list[_MessageMediaRef]] = {}
_backfill_locks: dict[str, asyncio.Lock] = {}
_media_analysis_semaphore = asyncio.Semaphore(3)


def _hash_media_data(media_data: str) -> str:
    normalized_data = media_data.encode("ascii", errors="ignore").decode("ascii")
    try:
        media_bytes = base64.b64decode(normalized_data)
    except Exception:
        media_bytes = normalized_data.encode("utf-8", errors="ignore")
    return hashlib.md5(media_bytes).hexdigest()


def _make_task_key(kind: str, media_data: str) -> str:
    return f"{kind}:{_hash_media_data(media_data)}"


def _is_successful_result(kind: str, result_text: Optional[str]) -> bool:
    if not result_text:
        return False
    if kind == "image":
        return result_text.startswith("[图片：")
    if kind == "emoji":
        return result_text.startswith("[表情包：")
    if kind == "voice":
        return result_text.startswith("[语音：")
    return False


def _format_cached_result(kind: str, description: str | None) -> Optional[str]:
    if not description:
        return None
    description = str(description).strip()
    if not description:
        return None
    if kind == "image":
        return description if description.startswith("[图片：") else f"[图片：{description}]"
    if kind == "emoji":
        return description if description.startswith("[表情包：") else f"[表情包：{description}]"
    if kind == "voice":
        return description if description.startswith("[语音：") else f"[语音：{description}]"
    return None


def _load_cached_media_result(kind: str, media_hash: str) -> Optional[str]:
    """Best-effort persistent cache lookup for media tasks.

    This avoids re-running VLM for image/emoji descriptions after restart. Voice
    transcription has no existing persistent cache in this codebase yet.
    """
    try:
        if kind == "image":
            image_record = (
                Images.select()
                .where((Images.emoji_hash == media_hash) & (Images.description.is_null(False)))
                .order_by(Images.timestamp.desc())
                .first()
            )
            if result := _format_cached_result("image", getattr(image_record, "description", None)):
                return result

            description_record = ImageDescriptions.get_or_none(
                (ImageDescriptions.image_description_hash == media_hash) & (ImageDescriptions.type == "image")
            )
            return _format_cached_result("image", getattr(description_record, "description", None))

        if kind == "emoji":
            emoji_record = Emoji.get_or_none(Emoji.emoji_hash == media_hash)
            if emoji_record and emoji_record.emotion:
                return _format_cached_result("emoji", str(emoji_record.emotion).replace("，", ","))
            if result := _format_cached_result("emoji", getattr(emoji_record, "description", None)):
                return result

            cache_record = EmojiDescriptionCache.get_or_none(EmojiDescriptionCache.emoji_hash == media_hash)
            if cache_record and cache_record.emotion_tags:
                return _format_cached_result("emoji", str(cache_record.emotion_tags).replace("，", ","))
            return _format_cached_result("emoji", getattr(cache_record, "description", None))
    except Exception as e:
        logger.debug(f"读取{kind}持久缓存失败，继续后台识别: {e}")

    return None


def _media_token_pattern(kind: str) -> str:
    if kind == "image":
        return r"\[图片(?:：[^\]]+)?\]"
    if kind == "emoji":
        return r"\[表情包(?:：[^\]]+)?\]"
    return r"\[(?:语音消息|语音：[^\]]+)\]"


def _replace_placeholder_occurrence(kind: str, content: str, result_text: str, occurrence_index: int) -> str:
    placeholder = _MEDIA_PLACEHOLDERS[kind]
    for index, match in enumerate(re.finditer(_media_token_pattern(kind), content)):
        if index != occurrence_index:
            continue
        if match.group(0) != placeholder:
            return content
        return f"{content[: match.start()]}{result_text}{content[match.end() :]}"
    return content


def _remember_message_ref(message_id: Optional[str], task_key: str, state: _MediaTaskState) -> None:
    if not message_id:
        return
    message_id = str(message_id)
    refs = _message_media_refs.setdefault(message_id, [])
    occurrence_index = sum(1 for ref in refs if ref.kind == state.kind)
    refs.append(_MessageMediaRef(kind=state.kind, task_key=task_key, occurrence_index=occurrence_index))
    state.message_refs.append((message_id, occurrence_index))


def _schedule_placeholder_backfill(kind: str, message_id: str, result_text: str, occurrence_index: int) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("当前没有运行中的事件循环，跳过媒体占位回填调度")
        return
    loop.create_task(_backfill_message_placeholder(kind, message_id, result_text, occurrence_index))


def _get_backfill_lock(message_id: str) -> asyncio.Lock:
    lock = _backfill_locks.get(message_id)
    if lock is None:
        lock = asyncio.Lock()
        _backfill_locks[message_id] = lock
    return lock


async def _backfill_message_placeholder(kind: str, message_id: str, result_text: str, occurrence_index: int) -> None:
    async with _get_backfill_lock(message_id):
        for attempt in range(6):
            try:
                message_record = (
                    Messages.select().where(Messages.message_id == message_id).order_by(Messages.time.desc()).first()
                )
                if not message_record:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue

                processed_text = message_record.processed_plain_text or ""
                backfilled_text = _replace_placeholder_occurrence(kind, processed_text, result_text, occurrence_index)
                if backfilled_text == processed_text:
                    return

                message_record.processed_plain_text = backfilled_text
                message_record.save()
                logger.debug(f"后台媒体识别完成，已回填消息 {message_id} 的 {kind} 占位")
                return
            except Exception as e:
                logger.warning(f"回填消息 {message_id} 的 {kind} 占位失败: {e}")
                await asyncio.sleep(0.5 * (attempt + 1))


async def _analyze_media(kind: str, media_data: str) -> Optional[str]:
    if kind == "image":
        return await get_image_manager().get_image_description(media_data)
    if kind == "emoji":
        return await get_image_manager().get_emoji_description(media_data)
    if kind == "voice":
        return await get_voice_text(media_data)
    return None


async def _run_media_task(task_key: str, media_data: str) -> None:
    state = _media_task_states[task_key]
    try:
        async with _media_analysis_semaphore:
            result_text = await _analyze_media(state.kind, media_data)
        if not _is_successful_result(state.kind, result_text):
            state.status = "failed"
            logger.warning(f"后台{state.kind}识别未得到可用结果，保留原始占位")
            return

        state.result_text = result_text
        state.status = "done"
        for message_id, occurrence_index in list(state.message_refs):
            _schedule_placeholder_backfill(state.kind, message_id, result_text, occurrence_index)
    except Exception as e:
        state.status = "failed"
        logger.warning(f"后台{state.kind}识别任务失败: {e}")
    finally:
        state.task = None


def _schedule_media_task(kind: str, media_data: str, message_id: Optional[str]) -> None:
    if not media_data:
        return

    media_hash = _hash_media_data(media_data)
    task_key = f"{kind}:{media_hash}"
    state = _media_task_states.get(task_key)
    if state is None:
        state = _MediaTaskState(kind=kind, media_hash=media_hash)
        _media_task_states[task_key] = state

    _remember_message_ref(message_id, task_key, state)

    if state.status in {"pending", "failed"} and (cached_result := _load_cached_media_result(kind, media_hash)):
        state.status = "done"
        state.result_text = cached_result
        if message_id:
            occurrence_index = _message_media_refs[str(message_id)][-1].occurrence_index
            _schedule_placeholder_backfill(kind, str(message_id), cached_result, occurrence_index)
        return

    if state.status == "done" and state.result_text and message_id:
        occurrence_index = _message_media_refs[str(message_id)][-1].occurrence_index
        _schedule_placeholder_backfill(kind, str(message_id), state.result_text, occurrence_index)
        return

    if state.status == "processing" and state.task:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("当前没有运行中的事件循环，跳过后台媒体识别调度")
        return

    state.status = "processing"
    state.task = loop.create_task(_run_media_task(task_key, media_data))


def schedule_image_description_task(image_base64: str, message_id: Optional[str] = None) -> None:
    _schedule_media_task("image", image_base64, message_id)


def schedule_emoji_description_task(emoji_base64: str, message_id: Optional[str] = None) -> None:
    _schedule_media_task("emoji", emoji_base64, message_id)


def schedule_voice_transcription_task(voice_base64: str, message_id: Optional[str] = None) -> None:
    _schedule_media_task("voice", voice_base64, message_id)


def enhance_media_placeholders(message_id: Optional[str], content: Optional[str]) -> str:
    if not content:
        return ""
    if not message_id:
        return content

    enhanced_content = content
    for media_ref in _message_media_refs.get(str(message_id), []):
        state = _media_task_states.get(media_ref.task_key)
        if not state or state.status != "done" or not state.result_text:
            continue
        enhanced_content = _replace_placeholder_occurrence(
            media_ref.kind,
            enhanced_content,
            state.result_text,
            media_ref.occurrence_index,
        )

    return enhanced_content
