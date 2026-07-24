"""Validated candidate models and bounded consolidation for history learning."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, Iterable, Mapping

from json_repair import repair_json

from src.bw_learner.history_import import ImportedMessage
from src.chat.utils.structured_prompt import dump_prompt_json


MAX_MODEL_RESPONSE_CHARS = 200_000
MAX_CONSOLIDATION_DYNAMIC_CHARS = 120_000
MAX_CONSOLIDATION_CANDIDATE_CHARS = 64_000
MAX_CONSOLIDATION_EVIDENCE_CHARS = 160
MAX_CONSOLIDATION_EVIDENCE_IDS = 2
_CONSOLIDATION_BATCH_LIMITS = {
    "expressions": 30,
    "behaviors": 20,
    "jargons": 30,
    "memories": 25,
    "profiles": 30,
}
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


@dataclass(frozen=True)
class ExpressionCandidate:
    situation: str
    style: str
    evidence_ids: tuple[str, ...]
    confidence: float
    candidate_id: str = ""
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True)
class BehaviorCandidate:
    actor_type: str
    learning_type: str
    action: str
    outcome: str
    evidence_ids: tuple[str, ...]
    confidence: float
    candidate_id: str = ""
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True)
class JargonCandidate:
    content: str
    meaning: str
    evidence_ids: tuple[str, ...]
    confidence: float
    candidate_id: str = ""
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryCandidate:
    atom_type: str
    content: str
    subject_id: str
    evidence_ids: tuple[str, ...]
    confidence: float
    importance: float
    candidate_id: str = ""
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfileCandidate:
    subject_id: str
    category: str
    name: str
    value: str
    evidence_ids: tuple[str, ...]
    confidence: float
    candidate_id: str = ""
    provenance: tuple[str, ...] = ()


def _candidate_kind(candidate: Any) -> str | None:
    if isinstance(candidate, ExpressionCandidate):
        return "expression"
    if isinstance(candidate, BehaviorCandidate):
        return "behavior"
    if isinstance(candidate, JargonCandidate):
        return "jargon"
    if isinstance(candidate, MemoryCandidate):
        return "memory"
    if isinstance(candidate, ProfileCandidate):
        return "profile"
    return None


def _candidate_identity(candidate: Any) -> tuple[str, ...]:
    if isinstance(candidate, ExpressionCandidate):
        return (candidate.situation.casefold(), candidate.style.casefold())
    if isinstance(candidate, BehaviorCandidate):
        return (
            candidate.actor_type.casefold(),
            candidate.learning_type.casefold(),
            candidate.action.casefold(),
            candidate.outcome.casefold(),
        )
    if isinstance(candidate, JargonCandidate):
        return (candidate.content.casefold(),)
    if isinstance(candidate, MemoryCandidate):
        return (candidate.atom_type.casefold(), candidate.subject_id.casefold(), candidate.content.casefold())
    if isinstance(candidate, ProfileCandidate):
        return (
            candidate.subject_id.casefold(),
            candidate.category.casefold(),
            candidate.name.casefold(),
            candidate.value.casefold(),
        )
    return ()


def _stable_candidate_id(candidate: Any) -> str:
    kind = _candidate_kind(candidate) or "candidate"
    identity = json.dumps((kind, *_candidate_identity(candidate)), ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"{kind}:{digest}"


def _with_candidate_metadata(candidate: Any, *, provenance: Iterable[str] = ()) -> Any:
    if _candidate_kind(candidate) is None:
        return candidate
    merged_provenance = tuple(
        dict.fromkeys(
            str(source) for source in (*getattr(candidate, "provenance", ()), *provenance) if str(source).strip()
        )
    )
    return replace(
        candidate,
        candidate_id=_stable_candidate_id(candidate),
        provenance=merged_provenance,
    )


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

    @property
    def counts(self) -> dict[str, int]:
        return {
            "expressions": len(self.expressions),
            "behaviors": len(self.behaviors),
            "jargons": len(self.jargons),
            "memories": len(self.memories),
            "profiles": len(self.profiles),
        }

    def to_json(self, *, include_metadata: bool = True) -> dict[str, Any]:
        def serialize(collection: Iterable[Any]) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            for candidate in collection:
                enriched = _with_candidate_metadata(candidate)
                payload = asdict(enriched)
                if include_metadata:
                    payload["provenance"] = list(enriched.provenance)
                else:
                    payload.pop("candidate_id", None)
                    payload.pop("provenance", None)
                result.append(payload)
            return result

        return {
            "expressions": serialize(self.expressions),
            "behaviors": serialize(self.behaviors),
            "jargons": serialize(self.jargons),
            "memories": serialize(self.memories),
            "profiles": serialize(self.profiles),
        }


def history_candidates_from_json(value: Mapping[str, Any] | None) -> HistoryCandidates:
    """Rehydrate the server-produced candidate payload for a deferred commit."""

    payload = value if isinstance(value, Mapping) else {}

    def items(key: str) -> list[Mapping[str, Any]]:
        raw = payload.get(key, [])
        return [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []

    def evidence_ids(item: Mapping[str, Any]) -> tuple[str, ...]:
        raw = item.get("evidence_ids", [])
        return (
            tuple(str(source_id) for source_id in raw if isinstance(source_id, (str, int)))
            if isinstance(raw, list)
            else ()
        )

    def number(item: Mapping[str, Any], key: str, default: float = 0.0) -> float:
        try:
            return float(item.get(key, default))
        except (TypeError, ValueError):
            return default

    def provenance(item: Mapping[str, Any]) -> tuple[str, ...]:
        raw = item.get("provenance", [])
        if not isinstance(raw, list):
            return ()
        return tuple(dict.fromkeys(str(source)[:128] for source in raw if isinstance(source, (str, int))))[:64]

    expressions = tuple(
        _with_candidate_metadata(
            ExpressionCandidate(
                str(item.get("situation", "")),
                str(item.get("style", "")),
                evidence_ids(item),
                number(item, "confidence"),
                provenance=provenance(item),
            )
        )
        for item in items("expressions")
    )
    behaviors = tuple(
        _with_candidate_metadata(
            BehaviorCandidate(
                str(item.get("actor_type", "")),
                str(item.get("learning_type", "")),
                str(item.get("action", "")),
                str(item.get("outcome", "")),
                evidence_ids(item),
                number(item, "confidence"),
                provenance=provenance(item),
            )
        )
        for item in items("behaviors")
    )
    jargons = tuple(
        _with_candidate_metadata(
            JargonCandidate(
                str(item.get("content", "")),
                str(item.get("meaning", "")),
                evidence_ids(item),
                number(item, "confidence"),
                provenance=provenance(item),
            )
        )
        for item in items("jargons")
    )
    memories = tuple(
        _with_candidate_metadata(
            MemoryCandidate(
                str(item.get("atom_type", "")),
                str(item.get("content", "")),
                str(item.get("subject_id", "")),
                evidence_ids(item),
                number(item, "confidence"),
                number(item, "importance"),
                provenance=provenance(item),
            )
        )
        for item in items("memories")
    )
    profiles = tuple(
        _with_candidate_metadata(
            ProfileCandidate(
                str(item.get("subject_id", "")),
                str(item.get("category", "")),
                str(item.get("name", "")),
                str(item.get("value", "")),
                evidence_ids(item),
                number(item, "confidence"),
                provenance=provenance(item),
            )
        )
        for item in items("profiles")
    )
    return HistoryCandidates(expressions, behaviors, jargons, memories, profiles)


@dataclass(frozen=True)
class WindowContinuation:
    """A bounded request to inspect the next chronological window."""

    needs_follow_up: bool = False
    tail_evidence_ids: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class HistoryWindowResult:
    candidates: HistoryCandidates
    continuation: WindowContinuation = WindowContinuation()
    has_more_candidates: bool = False
    extraction_page_count: int = 1
    catalog_complete: bool = True


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


def _parse_window_continuation(
    parsed: Mapping[str, Any], evidence: Mapping[str, ImportedMessage]
) -> WindowContinuation:
    raw = parsed.get("window_boundary")
    if not isinstance(raw, dict) or raw.get("needs_follow_up") is not True:
        return WindowContinuation()

    raw_tail_ids = raw.get("tail_evidence_ids")
    if not isinstance(raw_tail_ids, list):
        return WindowContinuation()
    tail_ids = _evidence_ids(raw_tail_ids[-12:], evidence)
    ordered_ids = tuple(evidence)
    if not tail_ids or tuple(ordered_ids[-len(tail_ids) :]) != tail_ids:
        return WindowContinuation()

    reason = _clean_model_text(raw.get("reason"), minimum=1, maximum=240) or ""
    return WindowContinuation(needs_follow_up=True, tail_evidence_ids=tail_ids, reason=reason)


def _parse_has_more_candidates(parsed: Mapping[str, Any]) -> bool:
    raw = parsed.get("extraction_page")
    return isinstance(raw, dict) and raw.get("has_more") is True


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


def parse_history_window_result(
    response: str,
    evidence: Mapping[str, ImportedMessage],
    *,
    eligible_sender_ids: Iterable[str] | None = None,
    excluded_sender_ids: Iterable[str] | None = None,
    require_repeated_jargon: bool = False,
    allow_memories: bool = False,
    allow_profiles: bool = False,
    provenance: Iterable[str] | None = None,
) -> HistoryWindowResult:
    """Parse model JSON and reject every candidate not grounded in supplied evidence."""

    parsed = _load_model_object(response)
    eligible = frozenset(str(sender_id) for sender_id in eligible_sender_ids) if eligible_sender_ids else None
    excluded = frozenset(str(sender_id) for sender_id in excluded_sender_ids or ())
    candidate_provenance = tuple(
        dict.fromkeys(str(source)[:128] for source in provenance or () if str(source).strip())
    )[:64]

    def sender_is_eligible(sender_id: str) -> bool:
        return sender_id not in excluded and (eligible is None or sender_id in eligible)

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
            and sender_is_eligible(evidence[source_id].sender_id)
        )
        if situation and style and confidence is not None and source_ids:
            expressions.append(
                ExpressionCandidate(situation, style, source_ids, confidence, provenance=candidate_provenance)
            )

    for item in _candidate_items(parsed, "behaviors", 40):
        actor_type = _clean_model_text(item.get("actor_type"), minimum=4, maximum=32)
        learning_type = _clean_model_text(item.get("learning_type"), minimum=4, maximum=32)
        action = _clean_model_text(item.get("action"), minimum=6, maximum=500)
        outcome = _clean_model_text(item.get("outcome"), minimum=4, maximum=500)
        confidence = _confidence(item.get("confidence"))
        source_ids = _evidence_ids(item.get("evidence_ids"), evidence)
        excluded_human_evidence = bool(
            any(
                not evidence[source_id].is_bot and not sender_is_eligible(evidence[source_id].sender_id)
                for source_id in source_ids
            )
        )
        source_ids = tuple(
            source_id
            for source_id in source_ids
            if evidence[source_id].is_bot or sender_is_eligible(evidence[source_id].sender_id)
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
                BehaviorCandidate(
                    actor_type,
                    learning_type,
                    action,
                    outcome,
                    source_ids,
                    confidence,
                    provenance=candidate_provenance,
                )  # type: ignore[arg-type]
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
                and sender_is_eligible(evidence[source_id].sender_id)
            )
        minimum_evidence = 2 if require_repeated_jargon else 1
        if content and meaning and confidence is not None and len(source_ids) >= minimum_evidence:
            jargons.append(JargonCandidate(content, meaning, source_ids, confidence, provenance=candidate_provenance))

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
                and sender_is_eligible(evidence[source_id].sender_id)
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
                memories.append(
                    MemoryCandidate(
                        atom_type,
                        content,
                        subject_id,
                        source_ids,
                        confidence,
                        importance,
                        provenance=candidate_provenance,
                    )
                )

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
                    and sender_is_eligible(subject_id)
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
                profiles.append(
                    ProfileCandidate(
                        subject_id,
                        category,
                        name,
                        value,
                        source_ids,
                        confidence,
                        provenance=candidate_provenance,
                    )
                )

    has_more_candidates = _parse_has_more_candidates(parsed)
    return HistoryWindowResult(
        candidates=HistoryCandidates(
            expressions=tuple(
                _deduplicate(expressions, lambda item: (item.situation.casefold(), item.style.casefold()))
            ),
            behaviors=tuple(
                _deduplicate(
                    behaviors,
                    lambda item: (
                        item.actor_type,
                        item.learning_type,
                        item.action.casefold(),
                        item.outcome.casefold(),
                    ),
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
        ),
        continuation=_parse_window_continuation(parsed, evidence),
        has_more_candidates=has_more_candidates,
        catalog_complete=not has_more_candidates,
    )


def parse_history_candidates(
    response: str,
    evidence: Mapping[str, ImportedMessage],
    *,
    eligible_sender_ids: Iterable[str] | None = None,
    excluded_sender_ids: Iterable[str] | None = None,
    require_repeated_jargon: bool = False,
    allow_memories: bool = False,
    allow_profiles: bool = False,
    provenance: Iterable[str] | None = None,
) -> HistoryCandidates:
    """Parse model JSON and return only evidence-grounded learning candidates."""

    return parse_history_window_result(
        response,
        evidence,
        eligible_sender_ids=eligible_sender_ids,
        excluded_sender_ids=excluded_sender_ids,
        require_repeated_jargon=require_repeated_jargon,
        allow_memories=allow_memories,
        allow_profiles=allow_profiles,
        provenance=provenance,
    ).candidates


def _merge_candidate_evidence(first: Any, second: Any) -> Any:
    merged_ids = tuple(dict.fromkeys((*first.evidence_ids, *second.evidence_ids)))[:12]
    confidence = max(first.confidence, second.confidence)
    merged_provenance = tuple(dict.fromkeys((*first.provenance, *second.provenance)))[:64]
    if isinstance(first, MemoryCandidate):
        return _with_candidate_metadata(
            replace(
                first,
                evidence_ids=merged_ids,
                confidence=confidence,
                importance=max(first.importance, second.importance),
                provenance=merged_provenance,
            )
        )
    return _with_candidate_metadata(
        replace(first, evidence_ids=merged_ids, confidence=confidence, provenance=merged_provenance)
    )


def _deduplicate(items: Iterable[Any], key: Callable[[Any], Any]) -> list[Any]:
    merged: dict[Any, Any] = {}
    for item in items:
        item = _with_candidate_metadata(item)
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

    return HistoryCandidates(
        expressions=tuple(merged_expressions),
        behaviors=tuple(merged_behaviors),
        jargons=tuple(merged_jargons),
        memories=tuple(merged_memories),
        profiles=tuple(merged_profiles),
    )


def _candidate_evidence_ids(candidates: HistoryCandidates) -> frozenset[str]:
    return frozenset(
        evidence_id
        for collection in (
            candidates.expressions,
            candidates.behaviors,
            candidates.jargons,
            candidates.memories,
            candidates.profiles,
        )
        for candidate in collection
        for evidence_id in candidate.evidence_ids
    )


def _retain_candidate_evidence(
    candidates: HistoryCandidates,
    messages: Iterable[ImportedMessage],
    evidence: dict[str, ImportedMessage],
) -> None:
    required_ids = _candidate_evidence_ids(candidates)
    evidence.update((message.message_id, message) for message in messages if message.message_id in required_ids)


def _limit_history_candidates(candidates: HistoryCandidates) -> HistoryCandidates:
    rank = lambda item: (len(item.evidence_ids), item.confidence)  # noqa: E731
    return HistoryCandidates(
        expressions=tuple(sorted(candidates.expressions, key=rank, reverse=True)[:30]),
        behaviors=tuple(sorted(candidates.behaviors, key=rank, reverse=True)[:20]),
        jargons=tuple(sorted(candidates.jargons, key=rank, reverse=True)[:30]),
        memories=tuple(sorted(candidates.memories, key=rank, reverse=True)[:25]),
        profiles=tuple(sorted(candidates.profiles, key=rank, reverse=True)[:30]),
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
        expressions=candidates.expressions,
        behaviors=candidates.behaviors,
        jargons=jargons,
        memories=candidates.memories,
        profiles=candidates.profiles,
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


def _inherit_candidate_provenance(candidates: HistoryCandidates, source: HistoryCandidates) -> HistoryCandidates:
    """Carry source-window provenance onto model-consolidated candidates."""

    source_collections = {
        "expression": source.expressions,
        "behavior": source.behaviors,
        "jargon": source.jargons,
        "memory": source.memories,
        "profile": source.profiles,
    }

    def enrich(kind: str, collection: Iterable[Any]) -> tuple[Any, ...]:
        source_items = source_collections[kind]
        enriched: list[Any] = []
        for candidate in collection:
            candidate_ids = set(candidate.evidence_ids)
            provenance: list[str] = list(candidate.provenance)
            identity = _candidate_identity(candidate)
            for original in source_items:
                if candidate_ids.intersection(original.evidence_ids) or identity == _candidate_identity(original):
                    provenance.extend(original.provenance)
            enriched.append(_with_candidate_metadata(candidate, provenance=provenance))
        return tuple(enriched)

    return HistoryCandidates(
        expressions=enrich("expression", candidates.expressions),
        behaviors=enrich("behavior", candidates.behaviors),
        jargons=enrich("jargon", candidates.jargons),
        memories=enrich("memory", candidates.memories),
        profiles=enrich("profile", candidates.profiles),
    )


def _candidate_prompt_payload(candidates: HistoryCandidates) -> dict[str, Any]:
    return candidates.to_json(include_metadata=False)


def _prompt_candidate(candidate: Any) -> Any:
    return replace(candidate, evidence_ids=candidate.evidence_ids[:MAX_CONSOLIDATION_EVIDENCE_IDS])


class _ConsolidationPromptTooLarge(ValueError):
    """Raised when a consolidation unit must be partitioned before prompting."""


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
    prompt_candidates = HistoryCandidates(
        expressions=tuple(_prompt_candidate(candidate) for candidate in candidates.expressions),
        behaviors=tuple(_prompt_candidate(candidate) for candidate in candidates.behaviors),
        jargons=tuple(_prompt_candidate(candidate) for candidate in candidates.jargons),
        memories=tuple(_prompt_candidate(candidate) for candidate in candidates.memories),
        profiles=tuple(_prompt_candidate(candidate) for candidate in candidates.profiles),
    )
    candidates_json = dump_prompt_json(_candidate_prompt_payload(prompt_candidates))
    if len(candidates_json) > MAX_CONSOLIDATION_CANDIDATE_CHARS:
        raise _ConsolidationPromptTooLarge("候选超过单次聚合预算")
    evidence_json = dump_prompt_json(_referenced_evidence(prompt_candidates, evidence))
    if len(candidates_json) + len(evidence_json) > MAX_CONSOLIDATION_DYNAMIC_CHARS:
        raise _ConsolidationPromptTooLarge("候选和证据超过单次聚合预算")
    return prompt_candidates, candidates_json, evidence_json


def _partition_consolidation_candidates(
    candidates: HistoryCandidates,
    evidence: Mapping[str, ImportedMessage],
) -> list[HistoryCandidates]:
    """Greedily create bounded prompts while preserving every candidate exactly once."""

    collections: dict[str, list[Any]] = {
        "expressions": [],
        "behaviors": [],
        "jargons": [],
        "memories": [],
        "profiles": [],
    }
    batches: list[HistoryCandidates] = []

    def current_candidates() -> HistoryCandidates:
        return HistoryCandidates(**{key: tuple(value) for key, value in collections.items()})

    def reset() -> None:
        for collection in collections.values():
            collection.clear()

    for key in collections:
        for candidate in getattr(candidates, key):
            if len(collections[key]) >= _CONSOLIDATION_BATCH_LIMITS[key]:
                batches.append(current_candidates())
                reset()
            collections[key].append(candidate)
            try:
                _consolidation_prompt_payload(current_candidates(), evidence)
            except _ConsolidationPromptTooLarge as error:
                collections[key].pop()
                bounded = current_candidates()
                if not bounded.total:
                    raise _ConsolidationPromptTooLarge("单个历史学习候选超过聚合预算") from error
                batches.append(bounded)
                reset()
                collections[key].append(candidate)
                _consolidation_prompt_payload(current_candidates(), evidence)

    final_batch = current_candidates()
    if final_batch.total or not batches:
        batches.append(final_batch)
    return batches
