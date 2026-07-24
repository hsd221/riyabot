"""Evidence-grounded learning from normalized historical group chats."""

from __future__ import annotations

import hashlib
import inspect
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Iterator, Mapping

from src.bw_learner.behavior_store import behavior_pattern_store
from src.bw_learner.history_candidates import (
    MAX_CONSOLIDATION_DYNAMIC_CHARS as MAX_CONSOLIDATION_DYNAMIC_CHARS,
    BehaviorCandidate as BehaviorCandidate,
    ExpressionCandidate as ExpressionCandidate,
    HistoryCandidates as HistoryCandidates,
    HistoryLearningOutputError as HistoryLearningOutputError,
    HistoryWindowResult as HistoryWindowResult,
    JargonCandidate as JargonCandidate,
    MemoryCandidate as MemoryCandidate,
    ProfileCandidate as ProfileCandidate,
    WindowContinuation as WindowContinuation,
    _candidate_evidence_ids,
    _consolidation_prompt_payload,
    _final_fallback,
    _inherit_candidate_provenance,
    _limit_history_candidates,
    _merge_window_candidates,
    _partition_consolidation_candidates,
    _restrict_consolidated_candidates,
    _retain_candidate_evidence,
    history_candidates_from_json as history_candidates_from_json,
    parse_history_candidates as parse_history_candidates,
    parse_history_window_result as parse_history_window_result,
)
from src.bw_learner.history_import import (
    HistoryWindow,
    ImportedMessage,
    history_window_to_jsonl,
    index_history_windows,
    iter_history_windows,
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

DEPTH_WINDOW_BUDGETS: dict[str, int | None] = {"fast": 8, "balanced": 20, "deep": 40, "full": None}
MAX_CONTINUATION_TAIL_MESSAGES = 12
MAX_CONTINUATION_FOLLOW_UP_MESSAGES = 40
MAX_CONTINUATION_WINDOW_MESSAGES = 80
MAX_CONTINUATION_WINDOW_CHARS = 12_000
MAX_CONSOLIDATION_ROUNDS = 12
MAX_WINDOW_EXTRACTION_PAGES = 20


class HistoryLearningCancelled(RuntimeError):
    """Raised when a caller cancels a running import between model calls."""


def _empty_counts() -> dict[str, int]:
    return {"expressions": 0, "behaviors": 0, "jargons": 0}


@dataclass(frozen=True)
class HistoryStoreResult:
    created: dict[str, int] = field(default_factory=_empty_counts)
    updated: dict[str, int] = field(default_factory=_empty_counts)


@dataclass(frozen=True)
class HistoryLearningResult:
    """Learning output with a bounded write set and an unbounded audit catalog.

    ``candidates`` is kept backward-compatible as the runtime write/review set.
    ``candidate_catalog`` contains the complete validated window union plus any
    consolidated representatives, so a large import is not hidden by the
    runtime database safety cap.
    """

    candidates: HistoryCandidates
    total_window_count: int
    selected_window_count: int
    selected_window_ids: tuple[str, ...]
    model_call_count: int
    store_result: HistoryStoreResult | None
    continuation_window_ids: tuple[str, ...] = ()
    candidate_catalog: HistoryCandidates | None = None
    candidate_catalog_complete: bool = True
    incomplete_window_ids: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        catalog = self.candidate_catalog or self.candidates
        result = {
            "candidates": self.candidates.to_json(),
            "candidate_catalog": catalog.to_json(),
            "total_window_count": self.total_window_count,
            "selected_window_count": self.selected_window_count,
            "selected_window_ids": list(self.selected_window_ids),
            "continuation_window_ids": list(self.continuation_window_ids),
            "candidate_catalog_complete": self.candidate_catalog_complete,
            "incomplete_window_ids": list(self.incomplete_window_ids),
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
ExtractionPageCallback = Callable[[int], Awaitable[None] | None]


def group_chat_id(platform: str, group_id: str | int) -> str:
    """Return the same stable ID used by ChatManager for a group stream."""

    key = f"{platform}_{group_id}"
    return hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()


def _with_following_window(
    windows: Iterable[HistoryWindow],
) -> Iterator[tuple[HistoryWindow, HistoryWindow | None]]:
    iterator = iter(windows)
    current = next(iterator, None)
    while current is not None:
        following = next(iterator, None)
        yield current, following
        current = following


async def _notify(callback: ProgressCallback | None, stage: str, current: int, total: int) -> None:
    if callback is None:
        return
    result = callback(stage, current, total)
    if inspect.isawaitable(result):
        await result


async def _notify_extraction_page(callback: ExtractionPageCallback | None, page: int) -> None:
    if callback is None:
        return
    result = callback(page)
    if inspect.isawaitable(result):
        await result


def _already_extracted_payload(candidates: HistoryCandidates) -> dict[str, list[dict[str, Any]]]:
    """Return compact semantic fingerprints that keep extraction pages distinct."""

    payload = candidates.to_json()
    fields = {
        "expressions": ("candidate_id", "situation", "style"),
        "behaviors": ("candidate_id", "actor_type", "learning_type", "action", "outcome"),
        "jargons": ("candidate_id", "content", "meaning"),
        "memories": ("candidate_id", "atom_type", "subject_id", "content"),
        "profiles": ("candidate_id", "subject_id", "category", "name", "value"),
    }
    return {
        kind: [{key: item[key] for key in keys if key in item} for item in payload[kind]]
        for kind, keys in fields.items()
    }


def _build_continuation_window(
    current: HistoryWindow,
    following: HistoryWindow,
    tail_evidence_ids: tuple[str, ...],
) -> HistoryWindow:
    """Join a validated tail to the next chronological window once."""

    current_by_id = {message.message_id: message for message in current.messages}
    try:
        tail_messages = [current_by_id[evidence_id] for evidence_id in tail_evidence_ids]
    except KeyError as error:
        raise ValueError("continuation tail must belong to the current window") from error

    messages: list[ImportedMessage] = []
    seen_ids: set[str] = set()

    def append(message: ImportedMessage) -> bool:
        if message.message_id in seen_ids:
            return True
        if len(messages) >= MAX_CONTINUATION_WINDOW_MESSAGES:
            return False
        if (
            messages
            and sum(len(item.content) for item in messages) + len(message.content) > MAX_CONTINUATION_WINDOW_CHARS
        ):
            return False
        messages.append(message)
        seen_ids.add(message.message_id)
        return True

    for message in tail_messages[:MAX_CONTINUATION_TAIL_MESSAGES]:
        if not append(message):
            break
    for message in following.messages[:MAX_CONTINUATION_FOLLOW_UP_MESSAGES]:
        if not append(message):
            break

    if not messages:
        return following
    sender_ids = frozenset(message.sender_id for message in messages if not message.is_bot)
    high_signal_messages = sum(not message.is_low_signal and not message.is_bot for message in messages)
    replies = sum(message.reply_to_id is not None for message in messages)
    unique_content = len({message.content.casefold() for message in messages})
    signal_score = high_signal_messages * 2.0 + replies * 0.75 + unique_content * 0.25 + len(sender_ids) * 0.5
    return HistoryWindow(
        window_id=f"{current.window_id}+{following.window_id}:continuation",
        messages=tuple(messages),
        start_timestamp=messages[0].timestamp,
        end_timestamp=messages[-1].timestamp,
        sender_ids=sender_ids,
        char_count=sum(len(message.content) for message in messages),
        signal_score=signal_score,
    )


def _exclude_candidates_referencing(
    candidates: HistoryCandidates,
    excluded_evidence_ids: Iterable[str],
) -> HistoryCandidates:
    excluded = frozenset(excluded_evidence_ids)

    def keep(candidate: Any) -> bool:
        return excluded.isdisjoint(candidate.evidence_ids)

    return HistoryCandidates(
        expressions=tuple(filter(keep, candidates.expressions)),
        behaviors=tuple(filter(keep, candidates.behaviors)),
        jargons=tuple(filter(keep, candidates.jargons)),
        memories=tuple(filter(keep, candidates.memories)),
        profiles=tuple(filter(keep, candidates.profiles)),
    )


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

    async def extract_window_result(
        self,
        window: HistoryWindow,
        *,
        chat_name: str,
        eligible_sender_ids: Iterable[str] | None = None,
        excluded_sender_ids: Iterable[str] | None = None,
        extract_memories: bool = False,
        update_profiles: bool = False,
        page_progress: ExtractionPageCallback | None = None,
    ) -> HistoryWindowResult:
        evidence = {message.message_id: message for message in window.messages}
        eligible = tuple(sorted(str(sender_id) for sender_id in eligible_sender_ids or ()))
        excluded = tuple(sorted(str(sender_id) for sender_id in excluded_sender_ids or ()))
        accumulated = HistoryCandidates()
        continuation = WindowContinuation()
        page_count = 0
        catalog_complete = False

        while page_count < MAX_WINDOW_EXTRACTION_PAGES:
            page_count += 1
            response = await self._request(
                "learning.history.extract",
                max_tokens=3_500,
                chat_name_json=dump_prompt_json(chat_name),
                window_id_json=dump_prompt_json(window.window_id),
                eligible_sender_ids_json=dump_prompt_json(eligible or "all_non_bot"),
                excluded_sender_ids_json=dump_prompt_json(excluded),
                extract_memories_json=dump_prompt_json(extract_memories),
                update_profiles_json=dump_prompt_json(update_profiles),
                extraction_page_json=dump_prompt_json(page_count),
                already_extracted_candidates_json=dump_prompt_json(_already_extracted_payload(accumulated)),
                messages_jsonl=history_window_to_jsonl(window),
            )
            await _notify_extraction_page(page_progress, page_count)
            try:
                page_result = parse_history_window_result(
                    response,
                    evidence,
                    eligible_sender_ids=eligible or None,
                    excluded_sender_ids=excluded,
                    allow_memories=extract_memories,
                    allow_profiles=update_profiles,
                    provenance=(window.window_id,),
                )
            except HistoryLearningOutputError:
                if page_count == 1:
                    raise
                logger.warning(f"历史学习窗口 {window.window_id} 第 {page_count} 页输出无效，保留此前完整候选")
                break

            previous_total = accumulated.total
            accumulated = _merge_window_candidates((accumulated, page_result.candidates))
            if page_result.continuation.needs_follow_up:
                continuation = page_result.continuation
            if not page_result.has_more_candidates:
                catalog_complete = True
                break
            if accumulated.total == previous_total:
                logger.warning(f"历史学习窗口 {window.window_id} 第 {page_count} 页没有新增候选，停止继续翻页")
                break

        if not catalog_complete and page_count >= MAX_WINDOW_EXTRACTION_PAGES:
            logger.warning(f"历史学习窗口 {window.window_id} 达到 {MAX_WINDOW_EXTRACTION_PAGES} 页安全上限")
        return HistoryWindowResult(
            candidates=accumulated,
            continuation=continuation,
            has_more_candidates=not catalog_complete,
            extraction_page_count=page_count,
            catalog_complete=catalog_complete,
        )

    async def extract_window(
        self,
        window: HistoryWindow,
        *,
        chat_name: str,
        eligible_sender_ids: Iterable[str] | None = None,
        excluded_sender_ids: Iterable[str] | None = None,
        extract_memories: bool = False,
        update_profiles: bool = False,
    ) -> HistoryCandidates:
        return (
            await self.extract_window_result(
                window,
                chat_name=chat_name,
                eligible_sender_ids=eligible_sender_ids,
                excluded_sender_ids=excluded_sender_ids,
                extract_memories=extract_memories,
                update_profiles=update_profiles,
            )
        ).candidates

    async def consolidate(
        self,
        candidates: HistoryCandidates,
        evidence: Mapping[str, ImportedMessage],
        *,
        chat_name: str,
        eligible_sender_ids: Iterable[str] | None = None,
        excluded_sender_ids: Iterable[str] | None = None,
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
        return _inherit_candidate_provenance(
            _restrict_consolidated_candidates(
                parse_history_candidates(
                    response,
                    evidence,
                    eligible_sender_ids=eligible_sender_ids,
                    excluded_sender_ids=excluded_sender_ids,
                    require_repeated_jargon=True,
                    allow_memories=extract_memories,
                    allow_profiles=update_profiles,
                ),
                prompt_candidates,
            ),
            prompt_candidates,
        )

    async def consolidate_hierarchically(
        self,
        candidates: HistoryCandidates,
        evidence: Mapping[str, ImportedMessage],
        *,
        chat_name: str,
        eligible_sender_ids: Iterable[str] | None = None,
        excluded_sender_ids: Iterable[str] | None = None,
        extract_memories: bool = False,
        update_profiles: bool = False,
        progress: ProgressCallback | None = None,
        should_cancel: CancellationCheck | None = None,
    ) -> tuple[HistoryCandidates, int]:
        """Reduce all candidates through bounded model batches until one final result remains."""

        current = candidates
        batches = _partition_consolidation_candidates(current, evidence)
        estimated_calls = max(1, len(batches) * 2 - 1)
        completed_calls = 0
        await _notify(progress, "consolidating", completed_calls, estimated_calls)

        for _round in range(MAX_CONSOLIDATION_ROUNDS):
            reduced: list[HistoryCandidates] = []
            for batch in batches:
                if should_cancel and should_cancel():
                    raise HistoryLearningCancelled("聊天记录学习已取消")
                try:
                    result = await self.consolidate(
                        batch,
                        evidence,
                        chat_name=chat_name,
                        eligible_sender_ids=eligible_sender_ids,
                        excluded_sender_ids=excluded_sender_ids,
                        extract_memories=extract_memories,
                        update_profiles=update_profiles,
                    )
                except HistoryLearningOutputError as error:
                    logger.warning(f"历史学习分层合并输出无效，使用确定性合并结果: {error}")
                    result = _final_fallback(batch, evidence)
                reduced.append(result)
                completed_calls += 1
                await _notify(progress, "consolidating", completed_calls, estimated_calls)

            if len(batches) == 1:
                await _notify(progress, "consolidating", completed_calls, completed_calls)
                return reduced[0], completed_calls

            current = _merge_window_candidates(reduced)
            next_batches = _partition_consolidation_candidates(current, evidence)
            if len(next_batches) >= len(batches):
                logger.warning("历史学习分层合并未继续收敛，使用已完成首层审阅的确定性结果")
                await _notify(progress, "consolidating", completed_calls, completed_calls)
                return _final_fallback(current, evidence), completed_calls
            batches = next_batches
            estimated_calls = max(estimated_calls, completed_calls + len(batches))

        logger.warning("历史学习分层合并达到轮次上限，使用确定性最终筛选")
        return _final_fallback(current, evidence), completed_calls

    async def learn(
        self,
        normalized_path: str | Path,
        *,
        chat_id: str,
        chat_name: str,
        depth: str = "balanced",
        eligible_sender_ids: Iterable[str] | None = None,
        excluded_sender_ids: Iterable[str] | None = None,
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
        excluded = tuple(dict.fromkeys(str(sender_id) for sender_id in excluded_sender_ids or ()))
        options = dict(window_options or {})
        window_index = index_history_windows(normalized_path, **options)
        budget = DEPTH_WINDOW_BUDGETS[depth]
        selected_summaries = (
            window_index
            if budget is None
            else select_history_windows(window_index, budget=budget, priority_sender_ids=eligible)
        )
        selected_window_ids = tuple(summary.window_id for summary in selected_summaries)
        selected_window_id_set = frozenset(selected_window_ids)
        evidence: dict[str, ImportedMessage] = {}
        extracted: list[HistoryCandidates] = []
        continuation_window_ids: list[str] = []
        continuation_keys: set[tuple[str, str]] = set()
        incomplete_window_ids: list[str] = []
        model_call_count = 0
        extraction_total = len(selected_summaries)
        extraction_completed = 0
        await _notify(progress, "extracting", extraction_completed, extraction_total)

        async def record_extraction_page(page: int) -> None:
            nonlocal extraction_completed, extraction_total, model_call_count
            if page > 1:
                extraction_total += 1
            model_call_count += 1
            extraction_completed += 1
            await _notify(progress, "extracting", extraction_completed, extraction_total)

        for window, following in _with_following_window(iter_history_windows(normalized_path, **options)):
            if window.window_id not in selected_window_id_set:
                continue
            if should_cancel and should_cancel():
                raise HistoryLearningCancelled("聊天记录学习已取消")
            window_result: HistoryWindowResult | None = None
            continuation: HistoryWindow | None = None
            try:
                window_result = await self.extract_window_result(
                    window,
                    chat_name=chat_name,
                    eligible_sender_ids=eligible or None,
                    excluded_sender_ids=excluded,
                    extract_memories=extract_memories,
                    update_profiles=update_profiles,
                    page_progress=record_extraction_page,
                )
                window_candidates = window_result.candidates
                if window_result.continuation.needs_follow_up:
                    window_candidates = _exclude_candidates_referencing(
                        window_candidates,
                        window_result.continuation.tail_evidence_ids,
                    )
                extracted.append(window_candidates)
                _retain_candidate_evidence(window_candidates, window.messages, evidence)
                if not window_result.catalog_complete:
                    incomplete_window_ids.append(window.window_id)
            except HistoryLearningOutputError as error:
                logger.warning(f"历史学习窗口 {window.window_id} 输出无效，已跳过: {error}")
                incomplete_window_ids.append(window.window_id)

            if window_result is not None and window_result.continuation.needs_follow_up and following is not None:
                continuation_key = (window.window_id, following.window_id)
                if continuation_key not in continuation_keys:
                    continuation_keys.add(continuation_key)
                    continuation = _build_continuation_window(
                        window,
                        following,
                        window_result.continuation.tail_evidence_ids,
                    )
                    continuation_window_ids.append(continuation.window_id)
                    extraction_total += 1

            if continuation is None:
                continue
            try:
                follow_up_result = await self.extract_window_result(
                    continuation,
                    chat_name=chat_name,
                    eligible_sender_ids=eligible or None,
                    excluded_sender_ids=excluded,
                    extract_memories=extract_memories,
                    update_profiles=update_profiles,
                    page_progress=record_extraction_page,
                )
                extracted.append(follow_up_result.candidates)
                _retain_candidate_evidence(follow_up_result.candidates, continuation.messages, evidence)
                if not follow_up_result.catalog_complete:
                    incomplete_window_ids.append(continuation.window_id)
            except HistoryLearningOutputError as error:
                logger.warning(f"历史学习续接窗口 {continuation.window_id} 输出无效，已跳过: {error}")
                incomplete_window_ids.append(continuation.window_id)

        if should_cancel and should_cancel():
            raise HistoryLearningCancelled("聊天记录学习已取消")
        merged = _merge_window_candidates(extracted)
        consolidated_candidates, consolidation_calls = await self.consolidate_hierarchically(
            merged,
            evidence,
            chat_name=chat_name,
            eligible_sender_ids=eligible or None,
            excluded_sender_ids=excluded,
            extract_memories=extract_memories,
            update_profiles=update_profiles,
            progress=progress,
            should_cancel=should_cancel,
        )
        model_call_count += consolidation_calls
        candidate_catalog = _merge_window_candidates((merged, consolidated_candidates))
        runtime_candidates = _limit_history_candidates(consolidated_candidates)
        final_evidence_ids = _candidate_evidence_ids(runtime_candidates)
        evidence = {
            evidence_id: message for evidence_id, message in evidence.items() if evidence_id in final_evidence_ids
        }

        store_result = None
        if store:
            if should_cancel and should_cancel():
                raise HistoryLearningCancelled("聊天记录学习已取消")
            await _notify(progress, "storing", 0, 1)
            store_result = store_history_candidates(chat_id, runtime_candidates, evidence)
            await _notify(progress, "storing", 1, 1)
        return HistoryLearningResult(
            candidates=runtime_candidates,
            total_window_count=len(window_index),
            selected_window_count=len(selected_summaries),
            selected_window_ids=selected_window_ids,
            model_call_count=model_call_count,
            store_result=store_result,
            continuation_window_ids=tuple(continuation_window_ids),
            candidate_catalog=candidate_catalog,
            candidate_catalog_complete=not incomplete_window_ids,
            incomplete_window_ids=tuple(dict.fromkeys(incomplete_window_ids)),
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
