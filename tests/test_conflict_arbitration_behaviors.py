"""Conflict arbitration behavior regressions for dream maintenance."""

from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.memory.conflict_arbitration import ConflictArbiter
from src.memory.schema import (
    ConflictObservation,
    MemoryTraceChain,
    RawMessageArchive,
    configure_memory_database,
    initialize_database,
    memory_db,
)


class FakeQdrant:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.payload_updates: list[tuple[str, dict[str, Any]]] = []

    async def delete_atom_vector(self, atom_id: str) -> None:
        self.deleted.append(atom_id)

    async def set_atom_payload(self, atom_id: str, payload: dict[str, Any]) -> bool:
        self.payload_updates.append((atom_id, payload))
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


if __name__ == "__main__":
    unittest.main()
