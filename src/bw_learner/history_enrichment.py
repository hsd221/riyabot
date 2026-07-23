"""Store evidence-grounded history memories and isolated imported profiles."""

from __future__ import annotations

import hashlib
import inspect
import json
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from src.bw_learner.history_import import ChatHistoryFormatError, ImportedMessage, iter_normalized_messages
from src.bw_learner.history_learning import (
    HistoryCandidates,
    HistoryLearningCancelled,
    MemoryCandidate,
    ProfileCandidate,
)
from src.common.logger import get_logger
from src.memory.atom import (
    DEFAULT_DECAY,
    DEFAULT_TTL,
    AtomType,
    EpisodicDetail,
    MemoryAtom,
    SemanticDetail,
)
from src.memory.layer3_retrieval import MemoryWriter
from src.memory.schema import MemoryTraceChain
from src.memory.store import MemoryStore
from src.memory.user_profile import PersonIdentity, ProfileBuilder, ProfileStore, make_profile_id


logger = get_logger("history_enrichment")
ProgressCallback = Callable[[str, int, int], Awaitable[None] | None]
CancellationCheck = Callable[[], bool]
IMPORT_PROFILE_PLATFORM = "qq-import"


@dataclass(frozen=True)
class HistoryEnrichmentStoreResult:
    memories_created: int = 0
    profiles_created: int = 0
    profiles_updated: int = 0
    profiles_skipped: int = 0
    write_failures: int = 0

    def to_json(self) -> dict[str, int]:
        return asdict(self)


def load_history_enrichment_evidence(
    normalized_path: str | Path,
    candidates: HistoryCandidates,
) -> dict[str, ImportedMessage]:
    """Stream only the normalized messages referenced by memory/profile candidates."""

    referenced_ids = {
        evidence_id
        for collection in (candidates.memories, candidates.profiles)
        for candidate in collection
        for evidence_id in candidate.evidence_ids
    }
    if not referenced_ids:
        return {}

    evidence: dict[str, ImportedMessage] = {}
    with closing(iter_normalized_messages(normalized_path)) as messages:
        for message in messages:
            if message.message_id in referenced_ids:
                evidence[message.message_id] = message
                if len(evidence) == len(referenced_ids):
                    break
    if referenced_ids - evidence.keys():
        raise ChatHistoryFormatError("规范化聊天记录缺少候选证据")
    return evidence


async def _notify(callback: ProgressCallback | None, current: int, total: int) -> None:
    if callback is None:
        return
    result = callback("storing_enrichment", current, max(1, total))
    if inspect.isawaitable(result):
        await result


def _import_atom_id(import_id: str, kind: str, candidate: MemoryCandidate | ProfileCandidate) -> str:
    payload = json.dumps(asdict(candidate), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{import_id}\0{kind}\0{payload}".encode()).hexdigest()[:40]
    return f"history-{digest}"


def _evidence_messages(
    evidence_ids: tuple[str, ...],
    evidence: Mapping[str, ImportedMessage],
) -> list[ImportedMessage]:
    return [evidence[evidence_id] for evidence_id in evidence_ids if evidence_id in evidence]


def _import_entities(messages: list[ImportedMessage], subject_id: str = "") -> list[str]:
    sender_ids = [subject_id] if subject_id else [message.sender_id for message in messages if not message.is_bot]
    return [make_profile_id(IMPORT_PROFILE_PLATFORM, sender_id) for sender_id in dict.fromkeys(sender_ids) if sender_id]


def _record_trace(atom_id: str, import_id: str, content: str) -> None:
    try:
        MemoryTraceChain.create(
            atom_id=atom_id,
            step_number=1,
            agent_name="ChatHistoryImportLearner",
            operation_type="extract",
            input_source=f"chat_history_import:{import_id}",
            output_summary=content[:240],
            confidence_decay=1.0,
        )
    except Exception as error:
        logger.warning("历史导入记忆追溯链写入失败", atom_id=atom_id, error_type=type(error).__name__)


async def _default_memory_writer() -> MemoryWriter:
    store = MemoryStore()
    if not getattr(store, "_initialized", False):
        await store.initialize()
    return MemoryWriter(store)


def _memory_atom(
    import_id: str,
    chat_id: str,
    candidate: MemoryCandidate,
    evidence: Mapping[str, ImportedMessage],
) -> tuple[MemoryAtom, EpisodicDetail | None]:
    messages = _evidence_messages(candidate.evidence_ids, evidence)
    atom_type = AtomType(candidate.atom_type)
    event_time = max((message.timestamp for message in messages), default=time.time())
    atom = MemoryAtom(
        atom_id=_import_atom_id(import_id, "memory", candidate),
        atom_type=atom_type,
        content=candidate.content,
        entities=_import_entities(messages, candidate.subject_id),
        importance=candidate.importance,
        confidence=candidate.confidence,
        created_at=event_time,
        last_accessed_at=time.time(),
        ttl_days=DEFAULT_TTL[atom_type],
        decay_type=DEFAULT_DECAY[atom_type],
        source_scene="group_chat",
        source_id=chat_id,
        privacy_level="context_sensitive",
        status="active",
    )
    if atom_type is not AtomType.EPISODIC:
        return atom, None
    return atom, EpisodicDetail(
        atom_id=atom.atom_id,
        event_time=event_time,
        participants=_import_entities(messages, candidate.subject_id),
    )


def _profile_identity(
    candidate: ProfileCandidate,
    evidence: Mapping[str, ImportedMessage],
    *,
    group_id: str,
    chat_name: str,
) -> PersonIdentity:
    messages = _evidence_messages(candidate.evidence_ids, evidence)
    sender = next((message for message in reversed(messages) if message.sender_id == candidate.subject_id), None)
    return PersonIdentity(
        platform=IMPORT_PROFILE_PLATFORM,
        user_id=candidate.subject_id,
        nickname=sender.sender_name if sender else "",
        cardname=sender.sender_card if sender else "",
        group_id=group_id,
        group_name=chat_name,
        identity_source="chat_history_import",
        verification_status="unverified",
    )


def _profile_atom(
    import_id: str,
    chat_id: str,
    candidate: ProfileCandidate,
    evidence: Mapping[str, ImportedMessage],
    identity: PersonIdentity,
) -> tuple[MemoryAtom, SemanticDetail]:
    messages = _evidence_messages(candidate.evidence_ids, evidence)
    atom_type = AtomType.PREFERENCE if candidate.category in {"interest", "preference"} else AtomType.FACTUAL
    display_name = identity.cardname or identity.nickname or identity.user_id
    event_time = max((message.timestamp for message in messages), default=time.time())
    atom = MemoryAtom(
        atom_id=_import_atom_id(import_id, "profile", candidate),
        atom_type=atom_type,
        content=f"{display_name}的{candidate.name}是{candidate.value}",
        entities=[identity.profile_id],
        importance=0.6,
        confidence=min(candidate.confidence, 0.85),
        created_at=event_time,
        last_accessed_at=time.time(),
        ttl_days=DEFAULT_TTL[atom_type],
        decay_type=DEFAULT_DECAY[atom_type],
        source_scene="group_chat",
        source_id=chat_id,
        privacy_level="context_sensitive",
        status="active",
    )
    detail = SemanticDetail(
        atom_id=atom.atom_id,
        attr_category=candidate.category,
        attr_name=candidate.name,
        attr_value=candidate.value,
        subject_key=identity.profile_id,
        evidence_list=[f"history-import:{import_id}:{item}" for item in candidate.evidence_ids],
        evidence_counter=len(candidate.evidence_ids),
    )
    atom.semantic_detail = detail
    return atom, detail


async def store_history_enrichment(
    *,
    import_id: str,
    chat_id: str,
    group_id: str,
    chat_name: str,
    candidates: HistoryCandidates,
    evidence: Mapping[str, ImportedMessage],
    extract_memories: bool,
    update_profiles: bool,
    memory_writer: MemoryWriter | Any | None = None,
    profile_store: ProfileStore | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancellationCheck | None = None,
) -> HistoryEnrichmentStoreResult:
    """Persist optional history enrichment without trusting imported runtime identities."""

    selected_memories = candidates.memories if extract_memories else ()
    selected_profiles = candidates.profiles if update_profiles else ()
    total = len(selected_memories) + len(selected_profiles)
    if total == 0:
        return HistoryEnrichmentStoreResult()

    writer = memory_writer or await _default_memory_writer()
    profiles = profile_store or ProfileStore()
    builder = ProfileBuilder(profiles)
    memories_created = 0
    profiles_created = 0
    profiles_updated = 0
    profiles_skipped = 0
    write_failures = 0
    current = 0
    await _notify(progress, current, total)

    for candidate in selected_memories:
        if should_cancel and should_cancel():
            raise HistoryLearningCancelled("聊天记录学习已取消")
        atom, episodic_detail = _memory_atom(import_id, chat_id, candidate, evidence)
        try:
            await writer.write_atom(atom, episodic_detail=episodic_detail)
            _record_trace(atom.atom_id, import_id, atom.content)
            memories_created += 1
        except Exception as error:
            write_failures += 1
            logger.warning(
                "历史导入记忆写入失败",
                atom_id=atom.atom_id,
                error_type=type(error).__name__,
            )
        current += 1
        await _notify(progress, current, total)

    for candidate in selected_profiles:
        if should_cancel and should_cancel():
            raise HistoryLearningCancelled("聊天记录学习已取消")
        identity = _profile_identity(candidate, evidence, group_id=group_id, chat_name=chat_name)
        existing = profiles.get_profile(identity.profile_id)
        if existing is not None and existing.verification_status == "verified":
            profiles_skipped += 1
            current += 1
            await _notify(progress, current, total)
            continue

        atom, semantic_detail = _profile_atom(import_id, chat_id, candidate, evidence, identity)
        try:
            await writer.write_atom(atom, semantic_detail=semantic_detail)
            _record_trace(atom.atom_id, import_id, atom.content)
            updated = builder.update_profile_from_atom(identity, atom)
            if updated is None:
                raise RuntimeError("画像候选未产生有效更新")
            import_ids = updated.stats.setdefault("_history_import_ids", [])
            if not isinstance(import_ids, list):
                import_ids = []
                updated.stats["_history_import_ids"] = import_ids
            if import_id not in import_ids:
                import_ids.append(import_id)
                del import_ids[:-20]
            profiles.save_profile(updated)
            if existing is None:
                profiles_created += 1
            else:
                profiles_updated += 1
        except Exception as error:
            write_failures += 1
            logger.warning(
                "历史导入画像写入失败",
                profile_id=identity.profile_id,
                error_type=type(error).__name__,
            )
        current += 1
        await _notify(progress, current, total)

    return HistoryEnrichmentStoreResult(
        memories_created=memories_created,
        profiles_created=profiles_created,
        profiles_updated=profiles_updated,
        profiles_skipped=profiles_skipped,
        write_failures=write_failures,
    )
