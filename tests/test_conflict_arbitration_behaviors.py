"""Conflict arbitration behavior regressions for dream maintenance."""

from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from src.memory.conflict_arbitration import ConflictArbiter, ConflictDecision, Resolution
from src.memory.schema import (
    ConflictObservation,
    MemoryTraceChain,
    RawMessageArchive,
    SemanticDetail,
    configure_memory_database,
    initialize_database,
    memory_db,
)


class FakeQdrant:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.payload_updates: list[tuple[str, dict[str, Any]]] = []
        self.upserts: list[dict[str, Any]] = []

    async def delete_atom_vector(self, atom_id: str) -> None:
        self.deleted.append(atom_id)

    async def set_atom_payload(self, atom_id: str, payload: dict[str, Any]) -> bool:
        self.payload_updates.append((atom_id, payload))
        return True

    async def upsert_atom_vector(self, **kwargs) -> bool:
        self.upserts.append(kwargs)
        return True


class FakeStore:
    def __init__(self) -> None:
        self.qdrant = FakeQdrant()
        self.atoms: dict[str, dict[str, Any]] = {
            "atom-a": {
                "atom_id": "atom-a",
                "atom_type": "preference",
                "content": "小明长期喜欢摇滚",
                "entities": ["小明", "摇滚"],
                "confidence": 0.9,
                "created_at": "2026-07-01T00:00:00",
            },
            "atom-b": {
                "atom_id": "atom-b",
                "atom_type": "preference",
                "content": "小明现在讨厌摇滚",
                "entities": ["小明", "摇滚"],
                "confidence": 0.4,
                "created_at": "2026-07-06T00:00:00",
            },
        }
        self.updates: list[tuple[str, dict[str, Any]]] = []

    async def get_atom(self, atom_id: str) -> dict[str, Any] | None:
        return self.atoms.get(atom_id)

    async def update_atom(self, atom_id: str, updates: dict[str, Any]) -> bool:
        self.updates.append((atom_id, updates))
        self.atoms.setdefault(atom_id, {}).update(updates)
        return True


class ConflictArbitrationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "memory.db"
        configure_memory_database(str(db_path))
        initialize_database()

    def tearDown(self) -> None:
        if not memory_db.is_closed():
            memory_db.close()
        self.tmpdir.cleanup()

    async def test_empty_insufficient_missing_b_and_deferred_groups_do_not_resolve(self) -> None:
        arbiter = ConflictArbiter(FakeStore())

        self.assertEqual(await arbiter.check_and_resolve(), 0)

        base = datetime.datetime(2026, 7, 1, 8, 0, 0)
        ConflictObservation.create(
            atom_a_id="atom-a",
            atom_b_id="atom-b",
            conflict_type="contradiction",
            description="只有一次观察",
            status="pending",
            created_at=base,
        )
        self.assertEqual(await arbiter.check_and_resolve(), 0)

        for days in (0, 1, 2):
            ConflictObservation.create(
                atom_a_id="atom-a",
                atom_b_id="",
                conflict_type="missing_b",
                description="旧记录缺少 atom_b_id",
                status="pending",
                created_at=base + datetime.timedelta(days=days),
            )
        self.assertEqual(await arbiter.check_and_resolve(), 0)

        missing_store = FakeStore()
        for days in (0, 1, 2):
            ConflictObservation.create(
                atom_a_id="atom-a",
                atom_b_id="deleted-atom",
                conflict_type="deleted",
                description="对端原子已经不存在",
                status="pending",
                created_at=base + datetime.timedelta(days=days),
            )
        self.assertEqual(await ConflictArbiter(missing_store).check_and_resolve(), 0)
        self.assertEqual(missing_store.updates, [])

    async def test_needs_llm_resolution_is_left_pending(self) -> None:
        base = datetime.datetime(2026, 7, 1, 8, 0, 0)
        for days in (0, 1, 2):
            ConflictObservation.create(
                atom_a_id="atom-a",
                atom_b_id="atom-b",
                conflict_type="ambiguous",
                description="规则无法区分",
                status="pending",
                created_at=base + datetime.timedelta(days=days),
            )
        store = FakeStore()
        store.atoms["atom-a"].update({"confidence": 0.7, "created_at": "2026-07-01T00:00:00"})
        store.atoms["atom-b"].update({"confidence": 0.7, "created_at": "2026-07-01T00:00:00"})

        self.assertEqual(await ConflictArbiter(store).check_and_resolve(), 0)
        self.assertEqual(store.updates, [])
        self.assertEqual(ConflictObservation.select().where(ConflictObservation.status == "pending").count(), 3)

    async def test_reversed_atom_pair_observations_accumulate_into_one_conflict_group(self) -> None:
        base = datetime.datetime(2026, 7, 1, 8, 0, 0)
        ConflictObservation.create(
            atom_a_id="atom-a",
            atom_b_id="atom-b",
            conflict_type="contradiction",
            description="第一天观察到矛盾",
            status="pending",
            created_at=base,
        )
        ConflictObservation.create(
            atom_a_id="atom-b",
            atom_b_id="atom-a",
            conflict_type="contradiction",
            description="第二天反向记录同一组矛盾",
            status="pending",
            created_at=base + datetime.timedelta(days=1),
        )
        ConflictObservation.create(
            atom_a_id="atom-a",
            atom_b_id="atom-b",
            conflict_type="contradiction",
            description="第二天再次观察到矛盾",
            status="pending",
            created_at=base + datetime.timedelta(days=1, minutes=5),
        )

        store = FakeStore()
        resolved = await ConflictArbiter(store).check_and_resolve()

        self.assertEqual(resolved, 1)
        self.assertIn(("atom-b", {"status": "archived"}), store.updates)
        self.assertEqual(ConflictObservation.select().where(ConflictObservation.status == "pending").count(), 0)

    async def test_batch_mark_failure_does_not_cancel_resolved_count(self) -> None:
        base = datetime.datetime(2026, 7, 1, 8, 0, 0)
        for days in (0, 1, 2):
            ConflictObservation.create(
                atom_a_id="atom-a",
                atom_b_id="atom-b",
                conflict_type="contradiction",
                description="跨天观察到同一冲突",
                status="pending",
                created_at=base + datetime.timedelta(days=days),
            )
        arbiter = ConflictArbiter(FakeStore())

        with (
            patch.object(arbiter, "_apply_resolution", new=AsyncMock(return_value=None)),
            patch.object(ConflictObservation, "update", side_effect=RuntimeError("mark down")),
        ):
            self.assertEqual(await arbiter.check_and_resolve(), 1)

    async def test_same_day_repeated_observations_do_not_trigger_arbitration(self) -> None:
        base = datetime.datetime(2026, 7, 1, 8, 0, 0)
        for minute in (0, 5, 10):
            ConflictObservation.create(
                atom_a_id="atom-a",
                atom_b_id="atom-b",
                conflict_type="contradiction",
                description="同一天重复观察到矛盾",
                status="pending",
                created_at=base + datetime.timedelta(minutes=minute),
            )

        store = FakeStore()
        resolved = await ConflictArbiter(store).check_and_resolve()

        self.assertEqual(resolved, 0)
        self.assertEqual(store.updates, [])
        self.assertEqual(ConflictObservation.select().where(ConflictObservation.status == "pending").count(), 3)

    def test_distinct_observation_days_accepts_datetime_and_string_values(self) -> None:
        conflicts = [
            SimpleNamespace(created_at=datetime.datetime(2026, 7, 1, 8, 0, 0)),
            SimpleNamespace(created_at="2026-07-02T08:00:00"),
            SimpleNamespace(created_at="2026-07-02T09:00:00"),
        ]

        self.assertEqual(ConflictArbiter._distinct_observation_days(conflicts), 2)

    async def test_trace_chain_reliability_can_outweigh_atom_confidence(self) -> None:
        base = datetime.datetime(2026, 7, 1, 8, 0, 0)
        for days in (0, 1, 2):
            ConflictObservation.create(
                atom_a_id="atom-a",
                atom_b_id="atom-b",
                conflict_type="contradiction",
                description="跨天观察到同一偏好冲突",
                status="pending",
                created_at=base + datetime.timedelta(days=days),
            )
        MemoryTraceChain.create(
            atom_id="atom-a",
            step_number=1,
            agent_name="Layer2Encoder",
            operation_type="extract",
            input_source="不完整摘要",
            output_summary="低可靠抽取",
            confidence_decay=0.3,
            timestamp=base,
        )
        MemoryTraceChain.create(
            atom_id="atom-a",
            step_number=2,
            agent_name="ObjectivityChecker",
            operation_type="verify",
            input_source="缺少原文",
            output_summary="弱校验",
            confidence_decay=0.6,
            timestamp=base,
        )
        MemoryTraceChain.create(
            atom_id="atom-b",
            step_number=1,
            agent_name="DreamTriageAgent",
            operation_type="triage",
            input_source="raw_message_archive:42 | 小明说自己现在已经听腻摇滚了",
            output_summary="高显著性原文回放",
            confidence_decay=0.95,
            timestamp=base + datetime.timedelta(days=2),
        )

        store = FakeStore()
        resolved = await ConflictArbiter(store).check_and_resolve()

        self.assertEqual(resolved, 1)
        self.assertIn(("atom-a", {"status": "archived"}), store.updates)

    async def test_trace_reliability_verifies_raw_archive_reference(self) -> None:
        base = datetime.datetime(2026, 7, 1, 8, 0, 0)
        raw = RawMessageArchive.create(
            stream_id="group-1",
            message_id="msg-real-raw",
            user_id="user-a",
            content="小明明确说自己现在已经听腻摇滚了",
            timestamp=base.timestamp(),
            chat_type="group",
            dream_significance=0.85,
        )
        conflict = ConflictObservation.create(
            atom_a_id="atom-a",
            atom_b_id="atom-b",
            conflict_type="contradiction",
            description="同一偏好的新旧冲突",
            status="pending",
            created_at=base + datetime.timedelta(days=2),
        )
        store = FakeStore()
        store.atoms["atom-a"].update({"confidence": 0.8, "created_at": "2026-07-01T00:00:00"})
        store.atoms["atom-b"].update({"confidence": 0.8, "created_at": "2026-07-01T00:00:00"})
        MemoryTraceChain.create(
            atom_id="atom-a",
            step_number=1,
            agent_name="DreamTriageAgent",
            operation_type="triage",
            input_source="raw_message_archive:999999 | 已不存在的原始消息",
            output_summary="悬空原始引用",
            confidence_decay=0.65,
            timestamp=base,
        )
        MemoryTraceChain.create(
            atom_id="atom-b",
            step_number=1,
            agent_name="DreamTriageAgent",
            operation_type="triage",
            input_source=f"raw_message_archive:{raw.id} | 小明明确说自己现在已经听腻摇滚了",
            output_summary="可追溯原文",
            confidence_decay=0.65,
            timestamp=base,
        )

        resolution = await ConflictArbiter(store).resolve(conflict)

        self.assertEqual(resolution.decision.value, "keep_b")
        self.assertIn("追溯链更可靠", resolution.reason)

    async def test_evidence_count_precedes_trace_confidence_and_recency_rules(self) -> None:
        arbiter = ConflictArbiter(FakeStore())
        atom_a = {
            "atom_id": "atom-a",
            "confidence": 0.5,
            "created_at": "2026-07-01T00:00:00",
        }
        atom_b = {
            "atom_id": "atom-b",
            "confidence": 0.9,
            "created_at": "2026-07-06T00:00:00",
        }

        with patch.object(ConflictArbiter, "_get_evidence_count", side_effect=[2, 1]):
            keep_a = await arbiter._evidence_based_arbitrate(atom_a, atom_b)
        with patch.object(ConflictArbiter, "_get_evidence_count", side_effect=[1, 2]):
            keep_b = await arbiter._evidence_based_arbitrate(atom_a, atom_b)

        self.assertEqual(keep_a.decision, ConflictDecision.KEEP_A)
        self.assertIn("证据更充分", keep_a.reason)
        self.assertEqual(keep_b.decision, ConflictDecision.KEEP_B)

    async def test_confidence_recency_and_ambiguous_tiebreakers_return_expected_decisions(self) -> None:
        arbiter = ConflictArbiter(FakeStore())
        with (
            patch.object(ConflictArbiter, "_get_evidence_count", return_value=0),
            patch.object(ConflictArbiter, "_get_trace_reliability_score", return_value=0.5),
        ):
            keep_a = await arbiter._evidence_based_arbitrate(
                {"atom_id": "atom-a", "confidence": 0.8, "created_at": "2026-07-01T00:00:00"},
                {"atom_id": "atom-b", "confidence": 0.6, "created_at": "2026-07-06T00:00:00"},
            )
            keep_b_by_confidence = await arbiter._evidence_based_arbitrate(
                {"atom_id": "atom-a", "confidence": 0.6, "created_at": "2026-07-01T00:00:00"},
                {"atom_id": "atom-b", "confidence": 0.8, "created_at": "2026-07-06T00:00:00"},
            )
            keep_a_by_recency = await arbiter._evidence_based_arbitrate(
                {"atom_id": "atom-a", "confidence": 0.7, "created_at": "2026-07-06T00:00:00"},
                {"atom_id": "atom-b", "confidence": 0.7, "created_at": "2026-07-01T00:00:00"},
            )
            needs_llm = await arbiter._evidence_based_arbitrate(
                {"atom_id": "atom-a", "confidence": 0.7, "created_at": "2026-07-01T00:00:00"},
                {"atom_id": "atom-b", "confidence": 0.7, "created_at": "2026-07-01T00:00:00"},
            )

        self.assertEqual(keep_a.decision, ConflictDecision.KEEP_A)
        self.assertEqual(keep_b_by_confidence.decision, ConflictDecision.KEEP_B)
        self.assertEqual(keep_a_by_recency.decision, ConflictDecision.KEEP_A)
        self.assertEqual(needs_llm.decision, ConflictDecision.NEEDS_LLM)

    async def test_trace_reliability_can_choose_atom_a_before_confidence(self) -> None:
        arbiter = ConflictArbiter(FakeStore())
        with (
            patch.object(ConflictArbiter, "_get_evidence_count", return_value=0),
            patch.object(ConflictArbiter, "_get_trace_reliability_score", side_effect=[0.8, 0.5]),
        ):
            resolution = await arbiter._evidence_based_arbitrate(
                {"atom_id": "atom-a", "confidence": 0.4, "created_at": "2026-07-01T00:00:00"},
                {"atom_id": "atom-b", "confidence": 0.9, "created_at": "2026-07-06T00:00:00"},
            )

        self.assertEqual(resolution.decision, ConflictDecision.KEEP_A)
        self.assertIn("追溯链更可靠", resolution.reason)

    def test_evidence_trace_and_raw_archive_helpers_return_safe_defaults(self) -> None:
        base = datetime.datetime(2026, 7, 1, 8, 0, 0)
        SemanticDetail.create(
            id="atom-a",
            atom="atom-a",
            attr_category="profile",
            attr_name="preference",
            attr_value="rock",
            evidence_counter=4,
        )
        MemoryTraceChain.create(
            atom_id="trace-a",
            step_number=1,
            agent_name="ObjectivityChecker",
            operation_type="verify",
            input_source="raw_message_archive without numeric id",
            output_summary="verified",
            confidence_decay=0.4,
            timestamp=base,
        )

        self.assertEqual(ConflictArbiter._get_evidence_count("atom-a"), 4)
        self.assertAlmostEqual(ConflictArbiter._get_trace_reliability_score("trace-a"), 0.53)
        self.assertEqual(ConflictArbiter._raw_archive_reliability_boost(set()), 0.0)
        with patch("src.memory.conflict_arbitration.int", side_effect=ValueError("bad id")):
            self.assertEqual(ConflictArbiter._raw_archive_ids_from_text("raw_message_archive:123"), set())

        with patch.object(SemanticDetail, "get_or_none", side_effect=RuntimeError("detail down")):
            self.assertEqual(ConflictArbiter._get_evidence_count("atom-a"), 0)
        with patch.object(MemoryTraceChain, "select", side_effect=RuntimeError("trace down")):
            self.assertEqual(ConflictArbiter._get_trace_reliability_score("trace-a"), 0.5)
        with patch.object(RawMessageArchive, "get_or_none", side_effect=RuntimeError("raw down")):
            self.assertEqual(ConflictArbiter._raw_archive_reliability_boost({123}), -0.05)
        with patch.object(
            RawMessageArchive,
            "get_or_none",
            return_value=SimpleNamespace(content="", chat_type="unknown", dream_significance="bad"),
        ):
            self.assertEqual(ConflictArbiter._raw_archive_reliability_boost({123}), 0.18)

    async def test_factual_contradictions_do_not_merge_just_because_entities_match(self) -> None:
        conflict = ConflictObservation.create(
            atom_a_id="atom-a",
            atom_b_id="atom-b",
            conflict_type="contradiction",
            description="同一实体事实矛盾",
            status="pending",
            created_at=datetime.datetime(2026, 7, 6, 8, 0, 0),
        )
        store = FakeStore()
        store.atoms["atom-a"].update(
            {
                "atom_type": "factual",
                "content": "小明住在上海",
                "entities": ["小明", "居住城市"],
                "confidence": 0.8,
                "created_at": "2026-07-01T00:00:00",
            }
        )
        store.atoms["atom-b"].update(
            {
                "atom_type": "factual",
                "content": "小明住在北京",
                "entities": ["小明", "居住城市"],
                "confidence": 0.8,
                "created_at": "2026-07-06T00:00:00",
            }
        )

        resolution = await ConflictArbiter(store).resolve(conflict)

        self.assertEqual(resolution.decision.value, "keep_b")
        self.assertIsNone(resolution.merged_content)

    async def test_duplicate_factual_observations_can_merge_same_entity_facts(self) -> None:
        conflict = ConflictObservation.create(
            atom_a_id="atom-a",
            atom_b_id="atom-b",
            conflict_type="duplicate",
            description="同一实体重复事实",
            status="pending",
            created_at=datetime.datetime(2026, 7, 6, 8, 0, 0),
        )
        store = FakeStore()
        store.atoms["atom-a"].update(
            {
                "atom_type": "factual",
                "content": "小明住在上海",
                "entities": ["小明", "居住城市"],
            }
        )
        store.atoms["atom-b"].update(
            {
                "atom_type": "factual",
                "content": "小明确认自己住在上海",
                "entities": ["小明", "居住城市"],
            }
        )

        resolution = await ConflictArbiter(store).resolve(conflict)

        self.assertEqual(resolution.decision.value, "merge")
        self.assertIn("小明住在上海", resolution.merged_content or "")
        self.assertIn("小明确认自己住在上海", resolution.merged_content or "")

    def test_merge_predicate_and_content_merge_helpers_cover_negative_and_deduping_cases(self) -> None:
        self.assertFalse(ConflictArbiter._can_merge("contradiction", {}, {}))
        self.assertFalse(
            ConflictArbiter._can_merge(
                "duplicate",
                {"entities": [], "atom_type": "factual"},
                {"entities": ["小明"], "atom_type": "factual"},
            )
        )
        self.assertFalse(
            ConflictArbiter._can_merge(
                "duplicate",
                {"entities": ["小明"], "atom_type": "factual"},
                {"entities": ["小红"], "atom_type": "factual"},
            )
        )
        self.assertFalse(
            ConflictArbiter._can_merge(
                "duplicate",
                {"entities": ["小明"], "atom_type": "factual"},
                {"entities": ["小明"], "atom_type": "preference"},
            )
        )
        self.assertFalse(
            ConflictArbiter._can_merge(
                "duplicate",
                {"entities": ["小明"], "atom_type": "preference"},
                {"entities": ["小明"], "atom_type": "preference"},
            )
        )

        self.assertEqual(ConflictArbiter._merge_atoms({"content": ""}, {"content": "补充"}), "补充")
        self.assertEqual(ConflictArbiter._merge_atoms({"content": "主内容"}, {"content": ""}), "主内容")
        self.assertEqual(ConflictArbiter._merge_atoms({"content": "主内容包含补充"}, {"content": "补充"}), "主内容包含补充")
        self.assertEqual(ConflictArbiter._merge_atoms({"content": "补充"}, {"content": "主内容包含补充"}), "主内容包含补充")
        self.assertEqual(ConflictArbiter._merge_atoms({"content": "较长的内容"}, {"content": "短"}), "较长的内容；短")

    async def test_apply_resolution_merge_updates_content_reembeds_and_archives_loser(self) -> None:
        conflict = ConflictObservation.create(
            atom_a_id="atom-a",
            atom_b_id="atom-b",
            conflict_type="duplicate",
            description="合并重复事实",
            status="pending",
            created_at=datetime.datetime(2026, 7, 6, 8, 0, 0),
        )
        store = FakeStore()
        store.atoms["atom-a"].update(
            {
                "atom_type": "factual",
                "weight": 0.8,
                "importance": 0.7,
                "status": "active",
                "source_scene": "group_chat",
                "source_id": "stream-1",
                "privacy_level": "context_sensitive",
            }
        )
        resolution = Resolution(
            decision=ConflictDecision.MERGE,
            atom_a_id="atom-a",
            atom_b_id="atom-b",
            merged_content="合并后的内容",
            reason="duplicate",
        )

        with patch("src.memory.conflict_arbitration.generate_embedding", new=AsyncMock(return_value=[0.1, 0.2])):
            await ConflictArbiter(store)._apply_resolution(resolution, conflict)

        merge_update = store.updates[0]
        self.assertEqual(merge_update[0], "atom-a")
        self.assertEqual(merge_update[1]["content"], "合并后的内容")
        self.assertAlmostEqual(merge_update[1]["confidence"], 0.95)
        self.assertIn(("atom-b", {"status": "archived"}), store.updates)
        self.assertEqual(store.qdrant.deleted, ["atom-b"])
        self.assertEqual(store.qdrant.upserts[0]["point_id"], "atom-a")
        self.assertEqual(store.qdrant.upserts[0]["payload"]["source_id"], "stream-1")
        self.assertEqual(ConflictObservation.get_by_id(conflict.id).status, "resolved")

    async def test_apply_resolution_both_reduces_confidence_and_handles_update_or_mark_failures(self) -> None:
        conflict = ConflictObservation.create(
            atom_a_id="atom-a",
            atom_b_id="atom-b",
            conflict_type="ambiguous",
            description="双方都降置信度",
            status="pending",
            created_at=datetime.datetime(2026, 7, 6, 8, 0, 0),
        )
        store = FakeStore()

        await ConflictArbiter(store)._apply_resolution(
            Resolution(ConflictDecision.BOTH, "atom-a", "atom-b", confidence_impact=0.25),
            conflict,
        )

        self.assertIn(("atom-a", {"confidence": 0.675}), store.updates)
        self.assertIn(("atom-b", {"confidence": 0.30000000000000004}), store.updates)
        self.assertEqual(store.qdrant.payload_updates[-1], ("atom-b", {"confidence": 0.30000000000000004}))

        failing_store = FakeStore()
        failing_store.update_atom = AsyncMock(side_effect=RuntimeError("update down"))  # type: ignore[method-assign]
        await ConflictArbiter(failing_store)._apply_resolution(
            Resolution(ConflictDecision.KEEP_A, "atom-a", "atom-b"),
            conflict,
        )

        with patch.object(ConflictObservation, "update", side_effect=RuntimeError("mark down")):
            await ConflictArbiter(FakeStore())._apply_resolution(
                Resolution(ConflictDecision.KEEP_A, "atom-a", "atom-b"),
                conflict,
            )

    async def test_merge_qdrant_sync_failure_and_missing_confidence_fallback_do_not_block_archiving(self) -> None:
        conflict = ConflictObservation.create(
            atom_a_id="atom-a",
            atom_b_id="atom-b",
            conflict_type="duplicate",
            description="合并时向量同步失败",
            status="pending",
            created_at=datetime.datetime(2026, 7, 6, 8, 0, 0),
        )
        store = FakeStore()
        resolution = Resolution(ConflictDecision.MERGE, "atom-a", "atom-b", merged_content="合并失败仍归档")
        arbiter = ConflictArbiter(store)

        self.assertEqual(await arbiter._get_confidence("missing"), 0.5)
        with patch("src.memory.conflict_arbitration.generate_embedding", new=AsyncMock(side_effect=RuntimeError("embed down"))):
            await arbiter._apply_resolution(resolution, conflict)

        self.assertIn(("atom-b", {"status": "archived"}), store.updates)


if __name__ == "__main__":
    unittest.main()
