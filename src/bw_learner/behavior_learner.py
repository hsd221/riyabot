import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from json_repair import repair_json

from src.bw_learner.behavior_store import (
    VALID_ACTOR_TYPES,
    VALID_LEARNING_TYPES,
    behavior_pattern_store,
    normalize_source_ids,
)
from src.bw_learner.learner_utils import contains_bot_self_name, filter_message_content
from src.chat.message_receive.chat_stream import get_chat_manager
from src.chat.utils.chat_message_builder import build_anonymous_messages, build_readable_messages
from src.chat.utils.prompt_builder import global_prompt_manager
from src.common.logger import get_logger
from src.config.config import global_config, model_config
from src.llm_models.utils_model import LLMRequest

logger = get_logger("behavior_learner")


@dataclass
class BehaviorCandidate:
    actor_type: str
    learning_type: str
    action: str
    outcome: str
    source_ids: list[str]


def _strip_json_code_fence(response: str) -> str:
    raw = (response or "").strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    raw = re.sub(r"^```\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    return raw.strip()


def _load_repaired_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        repaired = repair_json(raw)
        if isinstance(repaired, str):
            return json.loads(repaired)
        return repaired


def _extract_behavior_items(parsed: Any) -> list[Any]:
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("patterns", "behaviors", "behavior_patterns", "items", "data"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
    return []


def _is_reusable_behavior_text(action: str, outcome: str) -> bool:
    combined = f"{action}\n{outcome}"
    if len(action) < 6 or len(outcome) < 4:
        return False
    if contains_bot_self_name(combined):
        return False
    banned_fragments = ("SELF", "用户ID", "具体型号", "某个配置值", "一次性查询", "一次性任务")
    return not any(fragment in combined for fragment in banned_fragments)


def parse_behavior_response(response: str) -> list[BehaviorCandidate]:
    """
    解析上游行为学习 JSON 输出。

    期望数组项包含 actor_type、learning_type、action、outcome、source_ids。
    """
    if not response:
        return []

    raw = _strip_json_code_fence(response)
    try:
        parsed = _load_repaired_json(raw)
    except Exception as exc:
        logger.warning(f"行为学习结果解析失败: {exc}")
        return []

    candidates: list[BehaviorCandidate] = []
    for item in _extract_behavior_items(parsed):
        if not isinstance(item, dict):
            continue
        actor_type = str(item.get("actor_type") or "").strip()
        learning_type = str(item.get("learning_type") or "").strip()
        action = filter_message_content(str(item.get("action") or "").strip())
        outcome = filter_message_content(str(item.get("outcome") or "").strip())
        source_ids = normalize_source_ids(item.get("source_ids") or item.get("source_id"))

        if actor_type not in VALID_ACTOR_TYPES:
            continue
        if learning_type not in VALID_LEARNING_TYPES:
            continue
        if not source_ids:
            continue
        if not _is_reusable_behavior_text(action, outcome):
            continue
        candidates.append(
            BehaviorCandidate(
                actor_type=actor_type,
                learning_type=learning_type,
                action=action,
                outcome=outcome,
                source_ids=source_ids,
            )
        )
    return candidates


class BehaviorLearner:
    """从统一消息窗口中学习可复用行为表现。"""

    def __init__(self, chat_id: str) -> None:
        self.chat_id = chat_id
        self.chat_stream = get_chat_manager().get_stream(chat_id)
        self.chat_name = get_chat_manager().get_stream_name(chat_id) or chat_id
        self.behavior_model = LLMRequest(
            model_set=model_config.model_task_config.utils, request_type="behavior.learner"
        )
        self._learning_lock = asyncio.Lock()

    async def learn_and_store(self, messages: list[Any]) -> list[BehaviorCandidate]:
        if not messages:
            return []
        async with self._learning_lock:
            return await self._learn_and_store_locked(messages)

    async def _learn_and_store_locked(self, messages: list[Any]) -> list[BehaviorCandidate]:
        chat_str = await build_anonymous_messages(messages, show_ids=True)
        if not chat_str.strip():
            return []

        scene_profile = self._build_local_scene_profile(messages)
        prompt = await global_prompt_manager.format_prompt(
            "learn_behavior",
            bot_name=global_config.bot.nickname,
            chat_str=chat_str,
            scene_profile=scene_profile,
        )

        try:
            response, _ = await self.behavior_model.generate_response_async(prompt, temperature=0.3)
        except Exception as exc:
            logger.error(f"学习行为表现失败: {exc}")
            return []

        candidates = self._filter_candidates_by_source(parse_behavior_response(response), messages)
        if not candidates:
            logger.debug(f"聊天流 {self.chat_name} 行为学习未抽取到有效候选")
            return []

        current_time = time.time()
        for candidate in candidates:
            source_text = self._build_source_text(messages, candidate.source_ids)
            behavior_pattern_store.upsert_pattern(
                chat_id=self.chat_id,
                actor_type=candidate.actor_type,
                learning_type=candidate.learning_type,
                action=candidate.action,
                outcome=candidate.outcome,
                source_text=source_text,
                source_ids=candidate.source_ids,
                current_time=current_time,
            )
        logger.info(f"聊天流 {self.chat_name} 行为学习写入 {len(candidates)} 条候选")
        return candidates

    def _filter_candidates_by_source(
        self,
        candidates: list[BehaviorCandidate],
        messages: list[Any],
    ) -> list[BehaviorCandidate]:
        filtered: list[BehaviorCandidate] = []
        max_source_id = len(messages)
        for candidate in candidates:
            valid_source_ids = []
            for source_id in candidate.source_ids:
                if not source_id.isdigit():
                    continue
                line_index = int(source_id) - 1
                if 0 <= line_index < max_source_id:
                    valid_source_ids.append(source_id)
            if valid_source_ids:
                candidate.source_ids = valid_source_ids
                filtered.append(candidate)
        return filtered

    def _build_local_scene_profile(self, messages: list[Any]) -> str:
        source_ids = [str(i + 1) for i, _ in enumerate(messages)]
        text_parts = []
        for msg in messages[-8:]:
            text = filter_message_content(getattr(msg, "processed_plain_text", None) or "")
            if text:
                text_parts.append(text)
        summary = "；".join(text_parts)[-300:] or "最近聊天上下文"
        return json.dumps(
            {
                "segments": [
                    {
                        "segment_id": "s1",
                        "title": "最近聊天",
                        "source_ids": source_ids,
                        "profile": {
                            "summary": summary,
                            "tag_clusters": [],
                            "need": {"tag_name": "根据上下文自然互动", "tag_aliases": ["自然接话", "顺着聊天回应"]},
                            "other_traits": [],
                            "confidence": 0.6,
                        },
                    }
                ]
            },
            ensure_ascii=False,
        )

    def _build_source_text(self, messages: list[Any], source_ids: list[str]) -> str:
        selected_messages = []
        for source_id in source_ids:
            if not source_id.isdigit():
                continue
            line_index = int(source_id) - 1
            if 0 <= line_index < len(messages):
                selected_messages.append(messages[line_index])
        if not selected_messages:
            return ""
        try:
            return build_readable_messages(
                selected_messages,
                replace_bot_name=True,
                timestamp_mode="relative",
                read_mark=0.0,
                show_actions=False,
                truncate=True,
            ).strip()
        except Exception:
            return "\n".join(
                filter_message_content(getattr(msg, "processed_plain_text", None) or "") for msg in selected_messages
            ).strip()


class BehaviorLearnerManager:
    def __init__(self) -> None:
        self.behavior_learners: dict[str, BehaviorLearner] = {}

    def get_behavior_learner(self, chat_id: str) -> BehaviorLearner:
        if chat_id not in self.behavior_learners:
            self.behavior_learners[chat_id] = BehaviorLearner(chat_id)
        return self.behavior_learners[chat_id]


behavior_learner_manager = BehaviorLearnerManager()
