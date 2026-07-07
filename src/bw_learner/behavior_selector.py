import re
from typing import Any

from src.bw_learner.behavior_store import behavior_pattern_store, behavior_pattern_to_dict
from src.chat.message_receive.chat_stream import get_chat_manager
from src.common.logger import get_logger
from src.config.config import global_config

logger = get_logger("behavior_selector")


def _tokenize(text: str) -> set[str]:
    normalized = (text or "").lower()
    latin_tokens = set(re.findall(r"[a-z0-9_+#.-]{2,}", normalized))
    chinese_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    tokens = set(latin_tokens)
    for chunk in chinese_chunks:
        if len(chunk) <= 4:
            tokens.add(chunk)
            continue
        for size in (2, 3, 4):
            tokens.update(chunk[i : i + size] for i in range(0, len(chunk) - size + 1))
    return {token for token in tokens if token.strip()}


class BehaviorSelector:
    """为回复 prompt 召回行为表现参考。"""

    @staticmethod
    def _parse_stream_config_to_chat_id(stream_config_str: str) -> str | None:
        try:
            platform, raw_id, stream_type = stream_config_str.split(":", 2)
        except ValueError:
            return None
        return get_chat_manager().get_stream_id(platform, raw_id, is_group=stream_type == "group")

    def can_use_behavior_for_chat(self, chat_id: str) -> bool:
        behavior_config = getattr(global_config, "behavior", None)
        if behavior_config and hasattr(behavior_config, "get_behavior_config_for_chat"):
            use_behavior, _ = behavior_config.get_behavior_config_for_chat(chat_id)
            return use_behavior
        return True

    def get_related_chat_ids(self, chat_id: str) -> list[str]:
        behavior_config = getattr(global_config, "behavior", None)
        groups = getattr(behavior_config, "behavior_groups", None) or []
        if any("*" in group for group in groups):
            return [chat_id]
        for group in groups:
            parsed_group = []
            for stream_config in group:
                parsed_chat_id = self._parse_stream_config_to_chat_id(str(stream_config))
                if parsed_chat_id:
                    parsed_group.append(parsed_chat_id)
            if chat_id in parsed_group:
                return parsed_group
        return [chat_id]

    def _score_pattern(self, pattern: dict[str, Any], context_tokens: set[str], context_text: str) -> float:
        searchable_text = "\n".join(
            str(pattern.get(key) or "") for key in ("action", "outcome", "source_text", "actor_type", "learning_type")
        )
        pattern_tokens = _tokenize(searchable_text)
        if not pattern_tokens:
            return 0.0

        overlap = context_tokens & pattern_tokens
        token_score = len(overlap) / max(len(pattern_tokens), 1)
        substring_score = 0.0
        for field in ("action", "outcome", "source_text"):
            value = str(pattern.get(field) or "")
            if value and (value in context_text or context_text in value):
                substring_score = max(substring_score, 0.5)
        count_bonus = min(float(pattern.get("count") or 1), 8.0) * 0.03
        score = float(pattern.get("score") or 1.0)
        score_bonus = min(score, 5.0) * 0.02
        return token_score + substring_score + count_bonus + score_bonus

    def select_suitable_behaviors(
        self,
        chat_id: str,
        context_text: str,
        max_num: int = 3,
    ) -> tuple[list[dict[str, Any]], list[int]]:
        if max_num <= 0 or not self.can_use_behavior_for_chat(chat_id):
            return [], []

        context_text = (context_text or "").strip()
        if not context_text:
            return [], []

        context_tokens = _tokenize(context_text)
        if not context_tokens:
            return [], []

        patterns = [
            behavior_pattern_to_dict(pattern)
            for pattern in behavior_pattern_store.list_patterns(self.get_related_chat_ids(chat_id), enabled_only=True)
        ]
        scored_patterns = []
        for pattern in patterns:
            score = self._score_pattern(pattern, context_tokens, context_text)
            if score > 0:
                scored_patterns.append((score, pattern))

        scored_patterns.sort(
            key=lambda item: (
                item[0],
                float(item[1].get("score") or 0.0),
                int(item[1].get("count") or 0),
            ),
            reverse=True,
        )
        selected = [pattern for _, pattern in scored_patterns[:max_num]]
        selected_ids = [int(pattern["id"]) for pattern in selected if pattern.get("id") is not None]
        for pattern_id in selected_ids:
            behavior_pattern_store.mark_selected(pattern_id)
        if selected:
            logger.debug(f"行为参考召回 {len(selected)} 条: chat_id={chat_id}, ids={selected_ids}")
        return selected, selected_ids

    def build_reference_block(self, chat_id: str, context_text: str, max_num: int = 3) -> tuple[str, list[int]]:
        selected, selected_ids = self.select_suitable_behaviors(chat_id, context_text, max_num=max_num)
        if not selected:
            return "", []

        lines = ["行为参考：以下是相似聊天场景中学到的可复用行为表现，只作参考，不要生硬照搬。"]
        for pattern in selected:
            actor_label = {
                "other_user": "其他用户",
                "group_collective": "群体互动",
                "maibot_self": "自己过往反馈",
            }.get(str(pattern.get("actor_type")), "行为")
            lines.append(f"- [{actor_label}] 可以{pattern.get('action', '')}；通常会让{pattern.get('outcome', '')}。")
        return "\n".join(lines) + "\n", selected_ids


behavior_selector = BehaviorSelector()
