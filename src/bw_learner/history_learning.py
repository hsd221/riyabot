"""Evidence-grounded learning from normalized historical group chats."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping

from json_repair import repair_json

from src.bw_learner.behavior_store import behavior_pattern_store
from src.bw_learner.history_import import (
    HistoryWindow,
    ImportedMessage,
    build_history_windows,
    history_window_to_jsonl,
    select_history_windows,
)
from src.bw_learner.learner_utils import chat_id_list_contains, parse_chat_id_list, update_chat_id_list
from src.chat.utils.structured_prompt import dump_prompt_json, split_chat_prompt
from src.common.database.database_model import Expression, Jargon
from src.common.logger import get_logger
from src.common.prompt_manager import prompt_manager
from src.config.config import global_config, model_config
from src.llm_models.utils_model import LLMRequest


logger = get_logger("history_learning")

DEPTH_WINDOW_BUDGETS = {"fast": 8, "balanced": 20, "deep": 40}
MAX_MODEL_RESPONSE_CHARS = 200_000
MAX_CONSOLIDATION_DYNAMIC_CHARS = 120_000
MAX_CONSOLIDATION_CANDIDATE_CHARS = 64_000
MAX_CONSOLIDATION_EVIDENCE_CHARS = 160
MAX_CONSOLIDATION_EVIDENCE_IDS = 2
MIN_CONFIDENCE = 0.5
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE_RE = re.compile(r"\s+")
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_BEHAVIOR_TYPE_PAIRS = {
    ("other_user", "observed_behavior"),
    ("group_collective", "observed_behavior"),
    ("maibot_self", "self_reflection"),
}
_MEMORY_TYPES = {"episodic", "factual", "relational", "preference", "planned"}
_PROFILE_CATEGORIES = {"interest", "preference", "personality", "habit", "skill", "fact"}
_SENSITIVE_DATA_TERMS = {
    "api key",
    "apikey",
    "access key",
    "private key",
    "secret",
    "token",
    "住址",
    "地址",
    "住在",
    "居住地",
    "宗教",
    "密码",
    "凭据",
    "密钥",
    "手机号",
    "微信号",
    "qq号",
    "政治",
    "身份证",
    "护照",
    "社保",
    "银行卡",
    "邮箱",
    "健康",
    "医疗",
    "诊断",
    "用药",
    "药物",
    "疾病",
    "病史",
    "财务",
    "收入",
    "工资",
    "薪资",
    "资产",
    "负债",
    "债务",
    "联系方式",
    "电话",
    "性取向",
}
_PROFILE_RESTRICTED_TERMS = {
    "真实姓名",
    "姓名",
    "名字",
    "学校",
    "班级",
    "院系",
    "学号",
}
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_IDENTITY_NUMBER_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\w)")
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


class HistoryLearningOutputError(ValueError):
    """Raised when a model response cannot be treated as bounded structured data."""


class HistoryLearningCancelled(RuntimeError):
    """Raised when a caller cancels a running import between model calls."""


@dataclass(frozen=True)
class ExpressionCandidate:
    situation: str
    style: str
    evidence_ids: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class BehaviorCandidate:
    actor_type: str
    learning_type: str
    action: str
    outcome: str
    evidence_ids: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class JargonCandidate:
    content: str
    meaning: str
    evidence_ids: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class MemoryCandidate:
    atom_type: str
    content: str
    subject_id: str
    evidence_ids: tuple[str, ...]
    confidence: float
    importance: float


@dataclass(frozen=True)
class ProfileCandidate:
    subject_id: str
    category: str
    name: str
    value: str
    evidence_ids: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class HistoryCandidates:
    expressions: tuple[ExpressionCandidate, ...] = ()
    behaviors: tuple[BehaviorCandidate, ...] = ()
    jargons: tuple[JargonCandidate, ...] = ()
    memories: tuple[MemoryCandidate, ...] = ()
    profiles: tuple[ProfileCandidate, ...] = ()

    @property
    def total(self) -> int:
        return len(self.expressions) + len(self.behaviors) + len(self.jargons) + len(self.memories) + len(self.profiles)

    def to_json(self) -> dict[str, Any]:
        return {
            "expressions": [asdict(candidate) for candidate in self.expressions],
            "behaviors": [asdict(candidate) for candidate in self.behaviors],
            "jargons": [asdict(candidate) for candidate in self.jargons],
            "memories": [asdict(candidate) for candidate in self.memories],
            "profiles": [asdict(candidate) for candidate in self.profiles],
        }


def _empty_counts() -> dict[str, int]:
    return {"expressions": 0, "behaviors": 0, "jargons": 0}


@dataclass(frozen=True)
class HistoryStoreResult:
    created: dict[str, int] = field(default_factory=_empty_counts)
    updated: dict[str, int] = field(default_factory=_empty_counts)


@dataclass(frozen=True)
class HistoryLearningResult:
    candidates: HistoryCandidates
    total_window_count: int
    selected_window_count: int
    selected_window_ids: tuple[str, ...]
    model_call_count: int
    store_result: HistoryStoreResult | None

    def to_json(self) -> dict[str, Any]:
        result = {
            "candidates": self.candidates.to_json(),
            "total_window_count": self.total_window_count,
            "selected_window_count": self.selected_window_count,
            "selected_window_ids": list(self.selected_window_ids),
            "model_call_count": self.model_call_count,
            "store_result": None,
        }
        if self.store_result is not None:
            result["store_result"] = {
                "created": self.store_result.created,
                "updated": self.store_result.updated,
            }
        return result


ProgressCallback = Callable[[str, int, int], Awaitable[None] | None]
CancellationCheck = Callable[[], bool]


def group_chat_id(platform: str, group_id: str | int) -> str:
    """Return the same stable ID used by ChatManager for a group stream."""

    key = f"{platform}_{group_id}"
    return hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()


def _clean_model_text(value: Any, *, minimum: int, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = _SPACE_RE.sub(" ", _CONTROL_RE.sub("", value)).strip()
    if not minimum <= len(cleaned) <= maximum:
        return None
    return cleaned


def _confidence(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if not MIN_CONFIDENCE <= confidence <= 1.0:
        return None
    return confidence


def _bounded_score(value: Any, *, minimum: float = 0.0) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if minimum <= score <= 1.0 else None


def _contains_sensitive_data(*values: str) -> bool:
    combined = " ".join(values).casefold()
    if any(term in combined for term in _SENSITIVE_DATA_TERMS):
        return True
    return bool(_PHONE_RE.search(combined) or _IDENTITY_NUMBER_RE.search(combined) or _EMAIL_RE.search(combined))


def _contains_disallowed_profile_data(*values: str) -> bool:
    combined = " ".join(values).casefold()
    return _contains_sensitive_data(combined) or any(term in combined for term in _PROFILE_RESTRICTED_TERMS)


def _evidence_ids(value: Any, evidence: Mapping[str, ImportedMessage]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for raw_id in value[:12]:
        if not isinstance(raw_id, (str, int)):
            continue
        evidence_id = str(raw_id).strip()
        if not evidence_id or len(evidence_id) > 128 or evidence_id not in evidence or evidence_id in result:
            continue
        result.append(evidence_id)
    return tuple(result)


def _load_model_object(response: str) -> dict[str, Any]:
    if not isinstance(response, str) or len(response) > MAX_MODEL_RESPONSE_CHARS:
        raise HistoryLearningOutputError("模型输出为空或超过大小限制")
    raw = response.strip()
    if not raw:
        raise HistoryLearningOutputError("模型输出为空")
    match = _CODE_FENCE_RE.search(raw)
    if match:
        raw = match.group(1).strip()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        try:
            repaired = repair_json(raw)
            parsed = json.loads(repaired) if isinstance(repaired, str) else repaired
        except Exception as error:
            raise HistoryLearningOutputError("模型输出不是合法 JSON") from error
    if not isinstance(parsed, dict) or not any(
        key in parsed for key in ("expressions", "behaviors", "jargons", "memories", "profiles")
    ):
        raise HistoryLearningOutputError("模型输出缺少学习候选字段")
    return parsed


def _candidate_items(parsed: Mapping[str, Any], key: str, maximum: int) -> list[dict[str, Any]]:
    value = parsed.get(key, [])
    if not isinstance(value, list):
        return []
    return [item for item in value[:maximum] if isinstance(item, dict)]


def parse_history_candidates(
    response: str,
    evidence: Mapping[str, ImportedMessage],
    *,
    eligible_sender_ids: Iterable[str] | None = None,
    require_repeated_jargon: bool = False,
    allow_memories: bool = False,
    allow_profiles: bool = False,
) -> HistoryCandidates:
    """Parse model JSON and reject every candidate not grounded in supplied evidence."""

    parsed = _load_model_object(response)
    eligible = frozenset(str(sender_id) for sender_id in eligible_sender_ids) if eligible_sender_ids else None
    expressions: list[ExpressionCandidate] = []
    behaviors: list[BehaviorCandidate] = []
    jargons: list[JargonCandidate] = []
    memories: list[MemoryCandidate] = []
    profiles: list[ProfileCandidate] = []

    for item in _candidate_items(parsed, "expressions", 60):
        situation = _clean_model_text(item.get("situation"), minimum=4, maximum=400)
        style = _clean_model_text(item.get("style"), minimum=4, maximum=400)
        confidence = _confidence(item.get("confidence"))
        source_ids = _evidence_ids(item.get("evidence_ids"), evidence)
        source_ids = tuple(
            source_id
            for source_id in source_ids
            if not evidence[source_id].is_bot
            and not evidence[source_id].is_low_signal
            and (eligible is None or evidence[source_id].sender_id in eligible)
        )
        if situation and style and confidence is not None and source_ids:
            expressions.append(ExpressionCandidate(situation, style, source_ids, confidence))

    for item in _candidate_items(parsed, "behaviors", 40):
        actor_type = _clean_model_text(item.get("actor_type"), minimum=4, maximum=32)
        learning_type = _clean_model_text(item.get("learning_type"), minimum=4, maximum=32)
        action = _clean_model_text(item.get("action"), minimum=6, maximum=500)
        outcome = _clean_model_text(item.get("outcome"), minimum=4, maximum=500)
        confidence = _confidence(item.get("confidence"))
        source_ids = _evidence_ids(item.get("evidence_ids"), evidence)
        excluded_human_evidence = bool(
            eligible
            and any(
                not evidence[source_id].is_bot and evidence[source_id].sender_id not in eligible
                for source_id in source_ids
            )
        )
        source_ids = tuple(
            source_id
            for source_id in source_ids
            if evidence[source_id].is_bot or eligible is None or evidence[source_id].sender_id in eligible
        )
        pair = (actor_type, learning_type)
        source_messages = [evidence[source_id] for source_id in source_ids]
        actor_is_grounded = False
        if pair == ("maibot_self", "self_reflection"):
            actor_is_grounded = any(message.is_bot for message in source_messages)
        elif pair == ("other_user", "observed_behavior"):
            actor_is_grounded = any(not message.is_bot for message in source_messages)
        elif pair == ("group_collective", "observed_behavior"):
            actor_is_grounded = len({message.sender_id for message in source_messages if not message.is_bot}) >= 2
        if (
            pair in _BEHAVIOR_TYPE_PAIRS
            and action
            and outcome
            and confidence is not None
            and len(source_ids) >= 2
            and actor_is_grounded
            and not excluded_human_evidence
        ):
            behaviors.append(
                BehaviorCandidate(actor_type, learning_type, action, outcome, source_ids, confidence)  # type: ignore[arg-type]
            )

    for item in _candidate_items(parsed, "jargons", 60):
        content = _clean_model_text(item.get("content"), minimum=2, maximum=64)
        meaning = _clean_model_text(item.get("meaning"), minimum=2, maximum=500)
        confidence = _confidence(item.get("confidence"))
        source_ids = _evidence_ids(item.get("evidence_ids"), evidence)
        if content:
            source_ids = tuple(
                source_id
                for source_id in source_ids
                if content in evidence[source_id].content
                and not evidence[source_id].is_bot
                and not evidence[source_id].is_low_signal
                and (eligible is None or evidence[source_id].sender_id in eligible)
            )
        minimum_evidence = 2 if require_repeated_jargon else 1
        if content and meaning and confidence is not None and len(source_ids) >= minimum_evidence:
            jargons.append(JargonCandidate(content, meaning, source_ids, confidence))

    if allow_memories:
        for item in _candidate_items(parsed, "memories", 50):
            atom_type = _clean_model_text(item.get("atom_type"), minimum=4, maximum=20)
            content = _clean_model_text(item.get("content"), minimum=6, maximum=500)
            subject_id = _clean_model_text(item.get("subject_id") or "", minimum=1, maximum=128) or ""
            confidence = _confidence(item.get("confidence"))
            importance = _bounded_score(item.get("importance"), minimum=0.2)
            source_ids = _evidence_ids(item.get("evidence_ids"), evidence)
            source_ids = tuple(
                source_id
                for source_id in source_ids
                if not evidence[source_id].is_low_signal
                and (not subject_id or evidence[source_id].sender_id == subject_id)
                and (eligible is None or evidence[source_id].sender_id in eligible)
            )
            source_messages = [evidence[source_id] for source_id in source_ids]
            if (
                atom_type in _MEMORY_TYPES
                and content
                and confidence is not None
                and confidence >= 0.65
                and importance is not None
                and source_ids
                and any(not message.is_bot for message in source_messages)
                and not _contains_sensitive_data(content)
            ):
                memories.append(MemoryCandidate(atom_type, content, subject_id, source_ids, confidence, importance))

    if allow_profiles:
        for item in _candidate_items(parsed, "profiles", 50):
            subject_id = _clean_model_text(item.get("subject_id"), minimum=1, maximum=128)
            category = _clean_model_text(item.get("category"), minimum=4, maximum=24)
            name = _clean_model_text(item.get("name"), minimum=2, maximum=64)
            value = _clean_model_text(item.get("value"), minimum=2, maximum=160)
            confidence = _confidence(item.get("confidence"))
            source_ids = _evidence_ids(item.get("evidence_ids"), evidence)
            if subject_id:
                source_ids = tuple(
                    source_id
                    for source_id in source_ids
                    if evidence[source_id].sender_id == subject_id
                    and not evidence[source_id].is_bot
                    and not evidence[source_id].is_low_signal
                    and (eligible is None or subject_id in eligible)
                )
            minimum_evidence = 2 if category in {"personality", "habit"} else 1
            if (
                subject_id
                and category in _PROFILE_CATEGORIES
                and name
                and value
                and confidence is not None
                and confidence >= 0.7
                and len(source_ids) >= minimum_evidence
                and not _contains_disallowed_profile_data(name, value)
            ):
                profiles.append(ProfileCandidate(subject_id, category, name, value, source_ids, confidence))

    return HistoryCandidates(
        expressions=tuple(_deduplicate(expressions, lambda item: (item.situation.casefold(), item.style.casefold()))),
        behaviors=tuple(
            _deduplicate(
                behaviors,
                lambda item: (item.actor_type, item.learning_type, item.action.casefold(), item.outcome.casefold()),
            )
        ),
        jargons=tuple(_deduplicate(jargons, lambda item: item.content.casefold())),
        memories=tuple(
            _deduplicate(
                memories,
                lambda item: (item.atom_type, item.subject_id, item.content.casefold()),
            )
        ),
        profiles=tuple(
            _deduplicate(
                profiles,
                lambda item: (item.subject_id, item.category, item.name.casefold(), item.value.casefold()),
            )
        ),
    )


def _merge_candidate_evidence(first: Any, second: Any) -> Any:
    merged_ids = tuple(dict.fromkeys((*first.evidence_ids, *second.evidence_ids)))[:12]
    confidence = max(first.confidence, second.confidence)
    if isinstance(first, ExpressionCandidate):
        return ExpressionCandidate(first.situation, first.style, merged_ids, confidence)
    if isinstance(first, BehaviorCandidate):
        return BehaviorCandidate(
            first.actor_type,
            first.learning_type,
            first.action,
            first.outcome,
            merged_ids,
            confidence,
        )
    if isinstance(first, JargonCandidate):
        return JargonCandidate(first.content, first.meaning, merged_ids, confidence)
    if isinstance(first, MemoryCandidate):
        return MemoryCandidate(
            first.atom_type,
            first.content,
            first.subject_id,
            merged_ids,
            confidence,
            max(first.importance, second.importance),
        )
    return ProfileCandidate(
        first.subject_id,
        first.category,
        first.name,
        first.value,
        merged_ids,
        confidence,
    )


def _deduplicate(items: Iterable[Any], key: Callable[[Any], Any]) -> list[Any]:
    merged: dict[Any, Any] = {}
    for item in items:
        item_key = key(item)
        if item_key in merged:
            merged[item_key] = _merge_candidate_evidence(merged[item_key], item)
        else:
            merged[item_key] = item
    return list(merged.values())


def _merge_window_candidates(results: Iterable[HistoryCandidates]) -> HistoryCandidates:
    expressions: list[ExpressionCandidate] = []
    behaviors: list[BehaviorCandidate] = []
    jargons: list[JargonCandidate] = []
    memories: list[MemoryCandidate] = []
    profiles: list[ProfileCandidate] = []
    for result in results:
        expressions.extend(result.expressions)
        behaviors.extend(result.behaviors)
        jargons.extend(result.jargons)
        memories.extend(result.memories)
        profiles.extend(result.profiles)

    merged_expressions = _deduplicate(expressions, lambda item: (item.situation.casefold(), item.style.casefold()))
    merged_behaviors = _deduplicate(
        behaviors,
        lambda item: (item.actor_type, item.learning_type, item.action.casefold(), item.outcome.casefold()),
    )
    merged_jargons = _deduplicate(jargons, lambda item: item.content.casefold())
    merged_memories = _deduplicate(
        memories,
        lambda item: (item.atom_type, item.subject_id, item.content.casefold()),
    )
    merged_profiles = _deduplicate(
        profiles,
        lambda item: (item.subject_id, item.category, item.name.casefold(), item.value.casefold()),
    )

    rank = lambda item: (len(item.evidence_ids), item.confidence)  # noqa: E731
    return HistoryCandidates(
        expressions=tuple(sorted(merged_expressions, key=rank, reverse=True)[:25]),
        behaviors=tuple(sorted(merged_behaviors, key=rank, reverse=True)[:20]),
        jargons=tuple(sorted(merged_jargons, key=rank, reverse=True)[:25]),
        memories=tuple(sorted(merged_memories, key=rank, reverse=True)[:25]),
        profiles=tuple(sorted(merged_profiles, key=rank, reverse=True)[:30]),
    )


def _final_fallback(candidates: HistoryCandidates, evidence: Mapping[str, ImportedMessage]) -> HistoryCandidates:
    jargons = tuple(
        candidate
        for candidate in candidates.jargons
        if len(
            {
                source_id
                for source_id in candidate.evidence_ids
                if source_id in evidence
                and candidate.content in evidence[source_id].content
                and not evidence[source_id].is_bot
            }
        )
        >= 2
    )
    return HistoryCandidates(
        expressions=candidates.expressions[:30],
        behaviors=candidates.behaviors[:20],
        jargons=jargons[:30],
        memories=candidates.memories[:25],
        profiles=candidates.profiles[:30],
    )


def _restrict_consolidated_candidates(
    candidates: HistoryCandidates,
    source: HistoryCandidates,
) -> HistoryCandidates:
    """Prevent consolidation from promoting evidence across candidate categories."""

    def evidence_pool(items: Iterable[Any]) -> frozenset[str]:
        return frozenset(source_id for item in items for source_id in item.evidence_ids)

    expression_evidence = evidence_pool(source.expressions)
    behavior_evidence = evidence_pool(source.behaviors)
    jargon_evidence = evidence_pool(source.jargons)
    memory_evidence = evidence_pool(source.memories)
    profile_evidence = evidence_pool(source.profiles)
    behavior_types = {(item.actor_type, item.learning_type) for item in source.behaviors}
    jargon_terms = {item.content.casefold() for item in source.jargons}
    memory_types = {(item.atom_type, item.subject_id) for item in source.memories}
    profile_types = {(item.subject_id, item.category) for item in source.profiles}

    def grounded(item: Any, allowed: frozenset[str]) -> bool:
        return bool(item.evidence_ids) and set(item.evidence_ids).issubset(allowed)

    return HistoryCandidates(
        expressions=tuple(item for item in candidates.expressions if grounded(item, expression_evidence)),
        behaviors=tuple(
            item
            for item in candidates.behaviors
            if grounded(item, behavior_evidence) and (item.actor_type, item.learning_type) in behavior_types
        ),
        jargons=tuple(
            item
            for item in candidates.jargons
            if grounded(item, jargon_evidence) and item.content.casefold() in jargon_terms
        ),
        memories=tuple(
            item
            for item in candidates.memories
            if grounded(item, memory_evidence) and (item.atom_type, item.subject_id) in memory_types
        ),
        profiles=tuple(
            item
            for item in candidates.profiles
            if grounded(item, profile_evidence) and (item.subject_id, item.category) in profile_types
        ),
    )


def _candidate_prompt_payload(candidates: HistoryCandidates) -> dict[str, Any]:
    return candidates.to_json()


def _prompt_candidate(candidate: Any) -> Any:
    return replace(candidate, evidence_ids=candidate.evidence_ids[:MAX_CONSOLIDATION_EVIDENCE_IDS])


def _drop_largest_prompt_candidate(collections: Mapping[str, list[Any]]) -> bool:
    populated = [value for value in collections.values() if value]
    if not populated:
        return False
    largest_collection = max(
        populated,
        key=lambda collection: len(dump_prompt_json(asdict(collection[-1]))),
    )
    largest_collection.pop()
    return True


def _bounded_consolidation_candidates(candidates: HistoryCandidates) -> tuple[HistoryCandidates, str]:
    collections: dict[str, list[Any]] = {
        "expressions": [_prompt_candidate(candidate) for candidate in candidates.expressions],
        "behaviors": [_prompt_candidate(candidate) for candidate in candidates.behaviors],
        "jargons": [_prompt_candidate(candidate) for candidate in candidates.jargons],
        "memories": [_prompt_candidate(candidate) for candidate in candidates.memories],
        "profiles": [_prompt_candidate(candidate) for candidate in candidates.profiles],
    }
    while True:
        bounded = HistoryCandidates(**{key: tuple(value) for key, value in collections.items()})
        candidates_json = dump_prompt_json(_candidate_prompt_payload(bounded))
        if len(candidates_json) <= MAX_CONSOLIDATION_CANDIDATE_CHARS:
            return bounded, candidates_json
        if not _drop_largest_prompt_candidate(collections):
            return HistoryCandidates(), dump_prompt_json(HistoryCandidates().to_json())


def _referenced_evidence(candidates: HistoryCandidates, evidence: Mapping[str, ImportedMessage]) -> dict[str, Any]:
    referenced_ids: list[str] = []
    for collection in (
        candidates.expressions,
        candidates.behaviors,
        candidates.jargons,
        candidates.memories,
        candidates.profiles,
    ):
        for candidate in collection:
            for source_id in candidate.evidence_ids[:MAX_CONSOLIDATION_EVIDENCE_IDS]:
                if source_id not in referenced_ids:
                    referenced_ids.append(source_id)
    return {
        source_id: {
            "sender_id": evidence[source_id].sender_id,
            "is_bot": evidence[source_id].is_bot,
            "is_low_signal": evidence[source_id].is_low_signal,
            "content": evidence[source_id].content[:MAX_CONSOLIDATION_EVIDENCE_CHARS],
        }
        for source_id in referenced_ids
        if source_id in evidence
    }


def _consolidation_prompt_payload(
    candidates: HistoryCandidates,
    evidence: Mapping[str, ImportedMessage],
) -> tuple[HistoryCandidates, str, str]:
    bounded, _ = _bounded_consolidation_candidates(candidates)
    collections = {
        "expressions": list(bounded.expressions),
        "behaviors": list(bounded.behaviors),
        "jargons": list(bounded.jargons),
        "memories": list(bounded.memories),
        "profiles": list(bounded.profiles),
    }
    while True:
        bounded = HistoryCandidates(**{key: tuple(value) for key, value in collections.items()})
        candidates_json = dump_prompt_json(_candidate_prompt_payload(bounded))
        evidence_json = dump_prompt_json(_referenced_evidence(bounded, evidence))
        if len(candidates_json) + len(evidence_json) <= MAX_CONSOLIDATION_DYNAMIC_CHARS:
            return bounded, candidates_json, evidence_json
        if not _drop_largest_prompt_candidate(collections):
            return HistoryCandidates(), dump_prompt_json(HistoryCandidates().to_json()), dump_prompt_json({})


async def _notify(callback: ProgressCallback | None, stage: str, current: int, total: int) -> None:
    if callback is None:
        return
    result = callback(stage, current, total)
    if inspect.isawaitable(result):
        await result


class ChatHistoryLearner:
    """Bounded model pipeline for extraction, consolidation, validation, and storage."""

    def __init__(self, llm: Any | None = None) -> None:
        self.llm = llm or LLMRequest(
            model_set=model_config.model_task_config.utils,
            request_type="history.learning",
        )

    async def _request(self, prompt_id: str, *, max_tokens: int, **values: Any) -> str:
        formatted = prompt_manager.format_prompt(prompt_id, bot_name=global_config.bot.nickname, **values)
        structured = split_chat_prompt(formatted)
        response, _ = await self.llm.generate_response_async(
            **structured.as_request_kwargs(),
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return response

    async def extract_window(
        self,
        window: HistoryWindow,
        *,
        chat_name: str,
        eligible_sender_ids: Iterable[str] | None = None,
        extract_memories: bool = False,
        update_profiles: bool = False,
    ) -> HistoryCandidates:
        evidence = {message.message_id: message for message in window.messages}
        eligible = tuple(sorted(str(sender_id) for sender_id in eligible_sender_ids or ()))
        response = await self._request(
            "learning.history.extract",
            max_tokens=3_500,
            chat_name_json=dump_prompt_json(chat_name),
            window_id_json=dump_prompt_json(window.window_id),
            eligible_sender_ids_json=dump_prompt_json(eligible or "all_non_bot"),
            extract_memories_json=dump_prompt_json(extract_memories),
            update_profiles_json=dump_prompt_json(update_profiles),
            messages_jsonl=history_window_to_jsonl(window),
        )
        return parse_history_candidates(
            response,
            evidence,
            eligible_sender_ids=eligible or None,
            allow_memories=extract_memories,
            allow_profiles=update_profiles,
        )

    async def consolidate(
        self,
        candidates: HistoryCandidates,
        evidence: Mapping[str, ImportedMessage],
        *,
        chat_name: str,
        eligible_sender_ids: Iterable[str] | None = None,
        extract_memories: bool = False,
        update_profiles: bool = False,
    ) -> HistoryCandidates:
        prompt_candidates, candidates_json, evidence_json = _consolidation_prompt_payload(candidates, evidence)
        response = await self._request(
            "learning.history.consolidate",
            max_tokens=6_000,
            chat_name_json=dump_prompt_json(chat_name),
            candidates_json=candidates_json,
            evidence_json=evidence_json,
            extract_memories_json=dump_prompt_json(extract_memories),
            update_profiles_json=dump_prompt_json(update_profiles),
        )
        return _restrict_consolidated_candidates(
            parse_history_candidates(
                response,
                evidence,
                eligible_sender_ids=eligible_sender_ids,
                require_repeated_jargon=True,
                allow_memories=extract_memories,
                allow_profiles=update_profiles,
            ),
            prompt_candidates,
        )

    async def learn(
        self,
        normalized_path: str | Path,
        *,
        chat_id: str,
        chat_name: str,
        depth: str = "balanced",
        eligible_sender_ids: Iterable[str] | None = None,
        store: bool = True,
        window_options: Mapping[str, Any] | None = None,
        progress: ProgressCallback | None = None,
        should_cancel: CancellationCheck | None = None,
        extract_memories: bool = False,
        update_profiles: bool = False,
    ) -> HistoryLearningResult:
        if depth not in DEPTH_WINDOW_BUDGETS:
            raise ValueError(f"unsupported learning depth: {depth}")
        eligible = tuple(dict.fromkeys(str(sender_id) for sender_id in eligible_sender_ids or ()))
        windows = build_history_windows(normalized_path, **dict(window_options or {}))
        selected = select_history_windows(
            windows,
            budget=DEPTH_WINDOW_BUDGETS[depth],
            priority_sender_ids=eligible,
        )
        evidence = {message.message_id: message for window in selected for message in window.messages}
        extracted: list[HistoryCandidates] = []
        model_call_count = 0
        await _notify(progress, "extracting", 0, len(selected))
        for index, window in enumerate(selected, start=1):
            if should_cancel and should_cancel():
                raise HistoryLearningCancelled("聊天记录学习已取消")
            try:
                extracted.append(
                    await self.extract_window(
                        window,
                        chat_name=chat_name,
                        eligible_sender_ids=eligible or None,
                        extract_memories=extract_memories,
                        update_profiles=update_profiles,
                    )
                )
            except HistoryLearningOutputError as error:
                logger.warning(f"历史学习窗口 {window.window_id} 输出无效，已跳过: {error}")
            model_call_count += 1
            await _notify(progress, "extracting", index, len(selected))

        if should_cancel and should_cancel():
            raise HistoryLearningCancelled("聊天记录学习已取消")
        merged = _merge_window_candidates(extracted)
        await _notify(progress, "consolidating", 0, 1)
        try:
            final_candidates = await self.consolidate(
                merged,
                evidence,
                chat_name=chat_name,
                eligible_sender_ids=eligible or None,
                extract_memories=extract_memories,
                update_profiles=update_profiles,
            )
        except HistoryLearningOutputError as error:
            logger.warning(f"历史学习合并输出无效，使用确定性合并结果: {error}")
            final_candidates = _final_fallback(merged, evidence)
        model_call_count += 1
        await _notify(progress, "consolidating", 1, 1)

        store_result = None
        if store:
            if should_cancel and should_cancel():
                raise HistoryLearningCancelled("聊天记录学习已取消")
            await _notify(progress, "storing", 0, 1)
            store_result = store_history_candidates(chat_id, final_candidates, evidence)
            await _notify(progress, "storing", 1, 1)
        return HistoryLearningResult(
            candidates=final_candidates,
            total_window_count=len(windows),
            selected_window_count=len(selected),
            selected_window_ids=tuple(window.window_id for window in selected),
            model_call_count=model_call_count,
            store_result=store_result,
        )


def _source_context(source_ids: Iterable[str], evidence: Mapping[str, ImportedMessage]) -> str:
    lines = []
    for source_id in source_ids:
        message = evidence.get(source_id)
        if message is None:
            continue
        sender = message.sender_card or message.sender_name or message.sender_id
        lines.append(f"[{source_id}] {sender}: {message.content}")
    return "\n".join(lines)[-2_000:]


def _upsert_expression(chat_id: str, candidate: ExpressionCandidate, current_time: float) -> bool:
    expression = Expression.get_or_none(
        (Expression.chat_id == chat_id)
        & (Expression.situation == candidate.situation)
        & (Expression.style == candidate.style)
    )
    if expression is None:
        Expression.create(
            situation=candidate.situation,
            style=candidate.style,
            content_list=json.dumps([candidate.situation], ensure_ascii=False),
            count=1,
            last_active_time=current_time,
            chat_id=chat_id,
            create_date=current_time,
            checked=False,
            rejected=False,
        )
        return True
    expression.count = (expression.count or 0) + 1
    expression.last_active_time = current_time
    expression.checked = False
    expression.save()
    return False


def _find_chat_jargon(chat_id: str, content: str) -> Jargon | None:
    for jargon in Jargon.select().where(Jargon.content == content):
        if chat_id_list_contains(parse_chat_id_list(jargon.chat_id), chat_id):
            return jargon
    return None


def _upsert_jargon(
    chat_id: str,
    candidate: JargonCandidate,
    evidence: Mapping[str, ImportedMessage],
) -> bool:
    raw_context = [_source_context((source_id,), evidence) for source_id in candidate.evidence_ids]
    raw_context = [context for context in raw_context if context]
    jargon = _find_chat_jargon(chat_id, candidate.content)
    if jargon is None:
        Jargon.create(
            content=candidate.content,
            raw_content=json.dumps(raw_context, ensure_ascii=False),
            meaning=candidate.meaning,
            chat_id=json.dumps([[chat_id, 1]], ensure_ascii=False),
            is_global=False,
            count=1,
            is_jargon=True,
            last_inference_count=1,
            is_complete=False,
        )
        return True

    try:
        existing_context = json.loads(jargon.raw_content or "[]")
    except (json.JSONDecodeError, TypeError):
        existing_context = [jargon.raw_content] if jargon.raw_content else []
    if not isinstance(existing_context, list):
        existing_context = [str(existing_context)]
    jargon.raw_content = json.dumps(list(dict.fromkeys([*existing_context, *raw_context]))[-30:], ensure_ascii=False)
    jargon.count = (jargon.count or 0) + 1
    jargon.chat_id = json.dumps(
        update_chat_id_list(parse_chat_id_list(jargon.chat_id), chat_id, increment=1),
        ensure_ascii=False,
    )
    jargon.meaning = candidate.meaning
    jargon.is_jargon = True
    jargon.last_inference_count = jargon.count
    jargon.save()
    return False


def store_history_candidates(
    chat_id: str,
    candidates: HistoryCandidates,
    evidence: Mapping[str, ImportedMessage],
) -> HistoryStoreResult:
    """Atomically upsert validated candidates into existing learning tables."""

    created = _empty_counts()
    updated = _empty_counts()
    current_time = time.time()
    database = Expression._meta.database
    with database.atomic():
        for candidate in candidates.expressions:
            bucket = created if _upsert_expression(chat_id, candidate, current_time) else updated
            bucket["expressions"] += 1

        for candidate in candidates.behaviors:
            existing, _ = behavior_pattern_store.find_similar_pattern(
                chat_id,
                candidate.actor_type,
                candidate.learning_type,
                candidate.action,
                candidate.outcome,
            )
            behavior_pattern_store.upsert_pattern(
                chat_id=chat_id,
                actor_type=candidate.actor_type,
                learning_type=candidate.learning_type,
                action=candidate.action,
                outcome=candidate.outcome,
                source_text=_source_context(candidate.evidence_ids, evidence),
                source_ids=list(candidate.evidence_ids),
                current_time=current_time,
            )
            (updated if existing is not None else created)["behaviors"] += 1

        for candidate in candidates.jargons:
            bucket = created if _upsert_jargon(chat_id, candidate, evidence) else updated
            bucket["jargons"] += 1
    return HistoryStoreResult(created=created, updated=updated)
