import json
import re

from typing import Any

from src.common.logger import get_logger
from src.common.prompt_manager import prompt_manager


logger = get_logger("emoji")

_DESCRIPTION_PATTERN = re.compile(r"^情感：.+；适用场景：.+；表达意图：.+；画面内容：.+；画面文字：.+；风格/梗：.+$")
_EMOTION_SEPARATOR_PATTERN = re.compile(r"[,，、/|；;\n]+")
_FIELD_LIMITS = {
    "scene": 100,
    "intent": 80,
    "content": 160,
    "text": 100,
    "style": 80,
}
_FIELD_DEFAULTS = {
    "scene": "需结合聊天上下文判断",
    "intent": "传达画面中的反应",
    "text": "未单独识别",
    "style": "无明确梗或特殊风格",
}


def _sanitize_field(value: Any, fallback: str, max_length: int) -> str:
    """将不可信模型字段压缩为可安全嵌入消息占位符的单行文本。"""
    if not isinstance(value, str):
        value = ""
    clean_value = " ".join(value.split()).strip(" \t\r\n\"'")
    clean_value = clean_value.replace("[", "［").replace("]", "］")
    clean_value = clean_value.replace("；", "，").replace(";", "，")
    clean_value = clean_value or fallback
    if len(clean_value) > max_length:
        clean_value = f"{clean_value[: max_length - 1].rstrip()}…"
    return clean_value


def _parse_emotions(value: Any) -> list[str]:
    if isinstance(value, list):
        candidates = value
    elif isinstance(value, str):
        candidates = _EMOTION_SEPARATOR_PATTERN.split(value)
    else:
        candidates = []

    emotions: list[str] = []
    for candidate in candidates:
        emotion = _sanitize_field(candidate, "", 16)
        if emotion and emotion not in emotions:
            emotions.append(emotion)
        if len(emotions) == 3:
            break
    return emotions or ["中性反应"]


def _load_json_object(payload: str) -> dict[str, Any] | None:
    text = str(payload or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    object_start = text.find("{")
    object_end = text.rfind("}")
    if object_start < 0 or object_end <= object_start:
        return None

    try:
        result = json.loads(text[object_start : object_end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    return result if isinstance(result, dict) else None


def parse_semantic_emoji_description(payload: str, visual_description: str) -> tuple[str, list[str]]:
    """解析模型 JSON，并输出固定顺序的多维表情包描述和检索情绪标签。"""
    data = _load_json_object(payload) or {}
    emotions = _parse_emotions(data.get("emotion"))
    visual_fallback = _sanitize_field(visual_description, "未能可靠识别画面内容", _FIELD_LIMITS["content"])

    scene = _sanitize_field(data.get("scene"), _FIELD_DEFAULTS["scene"], _FIELD_LIMITS["scene"])
    intent = _sanitize_field(data.get("intent"), _FIELD_DEFAULTS["intent"], _FIELD_LIMITS["intent"])
    content = _sanitize_field(data.get("content"), visual_fallback, _FIELD_LIMITS["content"])
    image_text = _sanitize_field(data.get("text"), _FIELD_DEFAULTS["text"], _FIELD_LIMITS["text"])
    style = _sanitize_field(data.get("style"), _FIELD_DEFAULTS["style"], _FIELD_LIMITS["style"])

    description = (
        f"情感：{'、'.join(emotions)}；适用场景：{scene}；表达意图：{intent}；"
        f"画面内容：{content}；画面文字：{image_text}；风格/梗：{style}"
    )
    return description, emotions


def unwrap_emoji_description(description: str | None) -> str:
    """移除消息层的 ``[表情包：...]`` 包装，数据库旧值和新值均可处理。"""
    text = str(description or "").strip()
    if text.startswith("[表情包：") and text.endswith("]"):
        return text[len("[表情包：") : -1].strip()
    return text


def is_semantic_emoji_description(description: str | None) -> bool:
    """判断描述是否符合当前多维语义协议。"""
    return bool(_DESCRIPTION_PATTERN.fullmatch(unwrap_emoji_description(description)))


def extract_semantic_emoji_emotions(description: str | None) -> list[str]:
    """从已验证的多维描述中提取用于选图的简短情绪标签。"""
    if not is_semantic_emoji_description(description):
        return []
    emotion_field = unwrap_emoji_description(description).split("；", maxsplit=1)[0].removeprefix("情感：")
    return _parse_emotions(emotion_field)


async def build_semantic_emoji_description(model: Any, visual_description: str) -> tuple[str, list[str]]:
    """基于视觉原始解析生成可入库、可检索的多维语义描述。"""
    source_description = _sanitize_field(visual_description, "未能可靠识别画面内容", 4000)
    prompt = prompt_manager.format_prompt(
        "media.emoji.semantic_description",
        description=source_description,
    )
    try:
        response, _ = await model.generate_response_async(prompt, temperature=0.2, max_tokens=512)
    except Exception as error:
        logger.warning(f"生成表情包多维描述失败，使用确定性降级描述: {error}")
        response = ""
    return parse_semantic_emoji_description(response, source_description)
