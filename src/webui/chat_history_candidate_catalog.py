"""Bounded persistence and pagination for chat-history learning candidates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Literal

from src.bw_learner.history_candidates import HistoryCandidates


CandidateKind = Literal["expressions", "behaviors", "jargons", "memories", "profiles"]
CANDIDATE_KINDS: tuple[CandidateKind, ...] = (
    "expressions",
    "behaviors",
    "jargons",
    "memories",
    "profiles",
)
MAX_CANDIDATE_LINE_CHARS = 100_000


class CandidateCatalogUnavailableError(RuntimeError):
    """Raised when a result references a missing or invalid external catalog."""

    def __init__(self, reason: Literal["missing", "corrupt"]):
        super().__init__(reason)
        self.reason = reason


def write_candidate_catalog(
    task_dir: Path,
    candidates: HistoryCandidates,
    *,
    complete: bool,
    incomplete_window_ids: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    """Persist the complete catalog as JSONL so API responses stay bounded."""

    temporary = task_dir / "candidate_catalog.jsonl.tmp"
    destination = task_dir / "candidate_catalog.jsonl"
    payload = candidates.to_json()
    temporary.touch(mode=0o600, exist_ok=True)
    temporary.chmod(0o600)
    with temporary.open("w", encoding="utf-8") as output:
        for kind in CANDIDATE_KINDS:
            for candidate in payload[kind]:
                output.write(
                    json.dumps(
                        {"kind": kind, "candidate": candidate},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                output.write("\n")
    temporary.replace(destination)
    return {
        "total": candidates.total,
        "counts": candidates.counts,
        "complete": complete,
        "incomplete_window_ids": list(dict.fromkeys(str(item) for item in incomplete_window_ids)),
        "storage": "paged",
    }


def _paged_catalog_summary(result_payload: dict[str, Any]) -> dict[str, Any] | None:
    summary = result_payload.get("candidate_catalog")
    if isinstance(summary, dict) and summary.get("storage") == "paged":
        return summary
    return None


def _iter_paged_candidates(catalog_path: Path) -> Iterator[tuple[CandidateKind, dict[str, Any]]]:
    try:
        with catalog_path.open("r", encoding="utf-8") as source:
            for line in source:
                if len(line) > MAX_CANDIDATE_LINE_CHARS:
                    raise CandidateCatalogUnavailableError("corrupt")
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, TypeError) as error:
                    raise CandidateCatalogUnavailableError("corrupt") from error
                if not isinstance(entry, dict) or entry.get("kind") not in CANDIDATE_KINDS:
                    raise CandidateCatalogUnavailableError("corrupt")
                candidate = entry.get("candidate")
                if not isinstance(candidate, dict):
                    raise CandidateCatalogUnavailableError("corrupt")
                yield entry["kind"], candidate
    except CandidateCatalogUnavailableError:
        raise
    except FileNotFoundError as error:
        raise CandidateCatalogUnavailableError("missing") from error
    except (OSError, UnicodeError) as error:
        raise CandidateCatalogUnavailableError("corrupt") from error


def _iter_inline_candidates(result_payload: dict[str, Any], kind: CandidateKind) -> Iterator[dict[str, Any]]:
    for container_key in ("candidate_catalog", "candidates"):
        container = result_payload.get(container_key)
        if not isinstance(container, dict):
            continue
        raw_candidates = container.get(kind)
        if isinstance(raw_candidates, list):
            yield from (candidate for candidate in raw_candidates if isinstance(candidate, dict))
            return


def _candidate_matches_query(candidate: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    remaining: list[Any] = [candidate]
    while remaining:
        value = remaining.pop()
        if isinstance(value, dict):
            remaining.extend(value.values())
        elif isinstance(value, list):
            remaining.extend(value)
        elif value is not None and query in str(value).casefold():
            return True
    return False


def _expected_catalog_counts(summary: dict[str, Any]) -> dict[CandidateKind, int]:
    raw_counts = summary.get("counts")
    expected_total = summary.get("total")
    if not isinstance(raw_counts, dict) or type(expected_total) is not int:
        raise CandidateCatalogUnavailableError("corrupt")
    counts: dict[CandidateKind, int] = {}
    for kind in CANDIDATE_KINDS:
        value = raw_counts.get(kind)
        if type(value) is not int or value < 0:
            raise CandidateCatalogUnavailableError("corrupt")
        counts[kind] = value
    if expected_total < 0 or sum(counts.values()) != expected_total:
        raise CandidateCatalogUnavailableError("corrupt")
    return counts


def page_candidate_catalog(
    task_dir: Path,
    result_payload: dict[str, Any],
    *,
    kind: CandidateKind,
    query: str,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    """Return one filtered page while validating external catalog completeness."""

    catalog_path = task_dir / "candidate_catalog.jsonl"
    summary = _paged_catalog_summary(result_payload)
    start = (page - 1) * page_size
    data: list[dict[str, Any]] = []
    total_items = 0
    if summary is None:
        for candidate in _iter_inline_candidates(result_payload, kind):
            if not _candidate_matches_query(candidate, query):
                continue
            if start <= total_items < start + page_size:
                data.append(candidate)
            total_items += 1
        return data, total_items

    if not catalog_path.is_file():
        raise CandidateCatalogUnavailableError("missing")
    catalog_counts = {candidate_kind: 0 for candidate_kind in CANDIDATE_KINDS}
    for candidate_kind, candidate in _iter_paged_candidates(catalog_path):
        catalog_counts[candidate_kind] += 1
        if candidate_kind != kind or not _candidate_matches_query(candidate, query):
            continue
        if start <= total_items < start + page_size:
            data.append(candidate)
        total_items += 1

    if catalog_counts != _expected_catalog_counts(summary):
        raise CandidateCatalogUnavailableError("corrupt")
    return data, total_items
