import json
import time
from typing import Any, Optional

from src.bw_learner.learner_utils import calculate_similarity
from src.common.database.database_model import BehaviorPattern
from src.common.logger import get_logger

logger = get_logger("behavior_store")

ACTOR_OTHER_USER = "other_user"
ACTOR_GROUP_COLLECTIVE = "group_collective"
ACTOR_MAIBOT_SELF = "maibot_self"

LEARNING_OBSERVED = "observed_behavior"
LEARNING_SELF_REFLECTION = "self_reflection"

VALID_ACTOR_TYPES = {ACTOR_OTHER_USER, ACTOR_GROUP_COLLECTIVE, ACTOR_MAIBOT_SELF}
VALID_LEARNING_TYPES = {LEARNING_OBSERVED, LEARNING_SELF_REFLECTION}


def normalize_source_ids(source_ids: Any) -> list[str]:
    """将模型输出或数据库字段统一成 source_id 字符串列表。"""
    if not source_ids:
        return []
    if isinstance(source_ids, str):
        try:
            parsed = json.loads(source_ids)
        except json.JSONDecodeError:
            return [source_ids] if source_ids.strip() else []
        return normalize_source_ids(parsed)
    if isinstance(source_ids, (int, float)):
        return [str(int(source_ids))]
    if isinstance(source_ids, list):
        normalized = []
        for item in source_ids:
            value = str(item).strip()
            if value:
                normalized.append(value)
        return normalized
    return []


def behavior_pattern_to_dict(pattern: BehaviorPattern) -> dict[str, Any]:
    return {
        "id": pattern.id,
        "chat_id": pattern.chat_id,
        "actor_type": pattern.actor_type,
        "learning_type": pattern.learning_type,
        "action": pattern.action,
        "outcome": pattern.outcome,
        "source_text": pattern.source_text,
        "source_ids": normalize_source_ids(pattern.source_ids),
        "count": pattern.count,
        "score": pattern.score,
        "enabled": pattern.enabled,
        "selected_count": pattern.selected_count,
        "last_selected_time": pattern.last_selected_time,
        "last_active_time": pattern.last_active_time,
        "create_date": pattern.create_date,
    }


class BehaviorPatternStore:
    """行为模式的最小存取层，保留上游“相似模式合并”的核心语义。"""

    def __init__(self, similarity_threshold: float = 0.78) -> None:
        self.similarity_threshold = similarity_threshold

    def _similarity(self, action: str, outcome: str, pattern: BehaviorPattern) -> float:
        action_similarity = calculate_similarity(action, pattern.action or "")
        outcome_similarity = calculate_similarity(outcome, pattern.outcome or "")
        return action_similarity * 0.65 + outcome_similarity * 0.35

    def find_similar_pattern(
        self,
        chat_id: str,
        actor_type: str,
        learning_type: str,
        action: str,
        outcome: str,
    ) -> tuple[Optional[BehaviorPattern], float]:
        best_pattern = None
        best_similarity = 0.0
        query = BehaviorPattern.select().where(
            (BehaviorPattern.chat_id == chat_id)
            & (BehaviorPattern.actor_type == actor_type)
            & (BehaviorPattern.learning_type == learning_type)
        )
        for pattern in query:
            similarity = self._similarity(action, outcome, pattern)
            if similarity > best_similarity:
                best_similarity = similarity
                best_pattern = pattern
        if best_pattern and best_similarity >= self.similarity_threshold:
            return best_pattern, best_similarity
        return None, best_similarity

    def upsert_pattern(
        self,
        chat_id: str,
        actor_type: str,
        learning_type: str,
        action: str,
        outcome: str,
        source_text: str = "",
        source_ids: Optional[list[str]] = None,
        current_time: Optional[float] = None,
    ) -> BehaviorPattern:
        current_time = current_time or time.time()
        source_ids = normalize_source_ids(source_ids)
        pattern, similarity = self.find_similar_pattern(chat_id, actor_type, learning_type, action, outcome)
        if pattern is not None:
            stored_source_ids = normalize_source_ids(pattern.source_ids)
            merged_source_ids = [*stored_source_ids]
            for source_id in source_ids:
                if source_id not in merged_source_ids:
                    merged_source_ids.append(source_id)

            pattern.count = (pattern.count or 0) + 1
            pattern.score = min(5.0, float(pattern.score or 1.0) + 0.1)
            pattern.source_ids = json.dumps(merged_source_ids[-30:], ensure_ascii=False)
            if source_text:
                pattern.source_text = source_text[-2000:]
            pattern.last_active_time = current_time
            pattern.enabled = True
            pattern.save()
            logger.debug(f"合并相似行为模式: id={pattern.id}, similarity={similarity:.3f}")
            return pattern

        return BehaviorPattern.create(
            chat_id=chat_id,
            actor_type=actor_type,
            learning_type=learning_type,
            action=action,
            outcome=outcome,
            source_text=source_text[-2000:] if source_text else "",
            source_ids=json.dumps(source_ids, ensure_ascii=False),
            count=1,
            score=1.0,
            enabled=True,
            selected_count=0,
            last_selected_time=None,
            last_active_time=current_time,
            create_date=current_time,
        )

    def list_patterns(self, chat_ids: list[str], enabled_only: bool = True, limit: int = 200) -> list[BehaviorPattern]:
        if not chat_ids:
            return []
        conditions = BehaviorPattern.chat_id.in_(chat_ids)
        if enabled_only:
            conditions = conditions & (BehaviorPattern.enabled)
        query = (
            BehaviorPattern.select()
            .where(conditions)
            .order_by(
                BehaviorPattern.score.desc(), BehaviorPattern.count.desc(), BehaviorPattern.last_active_time.desc()
            )
        )
        if limit > 0:
            query = query.limit(limit)
        return list(query)

    def mark_selected(self, pattern_id: int) -> None:
        pattern = BehaviorPattern.get_or_none(BehaviorPattern.id == pattern_id)
        if not pattern:
            return
        pattern.selected_count = (pattern.selected_count or 0) + 1
        pattern.last_selected_time = time.time()
        pattern.save()


behavior_pattern_store = BehaviorPatternStore()
