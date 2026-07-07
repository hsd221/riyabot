"""InspirationEngine behavior regressions."""

from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.memory.inspiration_engine import InspirationEngine
from src.memory.schema import (
    InsightPool,
    MemoryAtom,
    NoisePool,
    configure_memory_database,
    initialize_database,
    memory_db,
)


class FakeWriter:
    def __init__(self) -> None:
        self.written_atoms: list[Any] = []

    async def write_atom(self, atom: Any) -> None:
        self.written_atoms.append(atom)


class InspirationEngineDatabaseTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "memory.db"
        configure_memory_database(str(db_path))
        initialize_database()

    def tearDown(self) -> None:
        if not memory_db.is_closed():
            memory_db.close()
        self.tmpdir.cleanup()

    async def test_recycle_turns_connected_noise_into_foreshadowing_insight(self) -> None:
        now = datetime.datetime.now()
        MemoryAtom.create(
            atom_id="atom-piano-pressure-1",
            atom_type="episodic",
            content="小明最近提到钢琴练习带来很大压力",
            entities='["小明", "钢琴"]',
            importance=0.7,
            confidence=0.8,
            weight=0.56,
            created_at=now,
            last_accessed_at=now,
            last_reinforced_at=now,
            ttl_days=30,
            decay_type="exponential",
            reinforcement_count=0,
            source_scene="group_chat",
            privacy_level="context_sensitive",
            status="active",
        )
        MemoryAtom.create(
            atom_id="atom-piano-pressure-2",
            atom_type="factual",
            content="小明因为钢琴比赛和上学安排感到压力",
            entities='["小明", "钢琴"]',
            importance=0.75,
            confidence=0.85,
            weight=0.64,
            created_at=now,
            last_accessed_at=now,
            last_reinforced_at=now,
            ttl_days=180,
            decay_type="exponential",
            reinforcement_count=0,
            source_scene="group_chat",
            privacy_level="context_sensitive",
            status="active",
        )
        noise = NoisePool.create(
            content="之前小明说钢琴压力像石头一样压着他",
            source_scene="group_chat",
            source_id="raw_message_archive:42",
            significance=0.32,
            created_at=now,
            ttl_days=30,
        )
        writer = FakeWriter()
        engine = InspirationEngine(store=None, writer=writer, retention_days=30)

        result = await engine.recycle()

        self.assertEqual(result, {"promoted": 0, "discarded": 0, "insights": 1})
        self.assertFalse(NoisePool.select().where(NoisePool.id == noise.id).exists())
        self.assertEqual(writer.written_atoms, [])

        insight = InsightPool.get_or_none(InsightPool.agent_name == "dream_foreshadowing")
        self.assertIsNotNone(insight)
        assert insight is not None
        self.assertIn("伏笔", insight.content)
        self.assertIn("小明", insight.content)
        self.assertIn("atom-piano-pressure-1", insight.source_atoms or "")
        self.assertIn("atom-piano-pressure-2", insight.source_atoms or "")
        self.assertLess(insight.confidence, 0.6)

    async def test_recycle_reconsiders_low_significance_noise_when_it_connects_later(self) -> None:
        now = datetime.datetime.now()
        MemoryAtom.create(
            atom_id="atom-low-signal-piano-1",
            atom_type="episodic",
            content="小明最近说钢琴课让他压力很大",
            entities='["小明", "钢琴"]',
            importance=0.7,
            confidence=0.8,
            weight=0.56,
            created_at=now,
            last_accessed_at=now,
            last_reinforced_at=now,
            ttl_days=30,
            decay_type="exponential",
            reinforcement_count=0,
            source_scene="group_chat",
            privacy_level="context_sensitive",
            status="active",
        )
        MemoryAtom.create(
            atom_id="atom-low-signal-piano-2",
            atom_type="factual",
            content="小明因为钢琴比赛安排感到压力",
            entities='["小明", "钢琴"]',
            importance=0.75,
            confidence=0.85,
            weight=0.64,
            created_at=now,
            last_accessed_at=now,
            last_reinforced_at=now,
            ttl_days=180,
            decay_type="exponential",
            reinforcement_count=0,
            source_scene="group_chat",
            privacy_level="context_sensitive",
            status="active",
        )
        noise = NoisePool.create(
            content="很早之前小明只是随口说钢琴压力像一块石头",
            source_scene="group_chat",
            source_id="raw_message_archive:99",
            significance=0.12,
            created_at=now,
            ttl_days=30,
        )
        writer = FakeWriter()
        engine = InspirationEngine(store=None, writer=writer, retention_days=30)

        result = await engine.recycle()

        self.assertEqual(result, {"promoted": 0, "discarded": 0, "insights": 1})
        self.assertFalse(NoisePool.select().where(NoisePool.id == noise.id).exists())
        self.assertEqual(writer.written_atoms, [])
        insight = InsightPool.get_or_none(InsightPool.agent_name == "dream_foreshadowing")
        self.assertIsNotNone(insight)
        assert insight is not None
        self.assertIn("atom-low-signal-piano-1", insight.source_atoms or "")
        self.assertIn("atom-low-signal-piano-2", insight.source_atoms or "")

    async def test_recycle_samples_low_signal_noise_even_when_high_signal_queue_is_full(self) -> None:
        now = datetime.datetime.now()
        MemoryAtom.create(
            atom_id="atom-biased-sample-piano-1",
            atom_type="episodic",
            content="小明最近说钢琴练习让他压力很大",
            entities='["小明", "钢琴"]',
            importance=0.7,
            confidence=0.8,
            weight=0.56,
            created_at=now,
            last_accessed_at=now,
            last_reinforced_at=now,
            ttl_days=30,
            decay_type="exponential",
            reinforcement_count=0,
            source_scene="group_chat",
            privacy_level="context_sensitive",
            status="active",
        )
        MemoryAtom.create(
            atom_id="atom-biased-sample-piano-2",
            atom_type="factual",
            content="小明因为钢琴考试和作业安排感到压力",
            entities='["小明", "钢琴"]',
            importance=0.75,
            confidence=0.85,
            weight=0.64,
            created_at=now,
            last_accessed_at=now,
            last_reinforced_at=now,
            ttl_days=180,
            decay_type="exponential",
            reinforcement_count=0,
            source_scene="group_chat",
            privacy_level="context_sensitive",
            status="active",
        )
        for index in range(InspirationEngine.CANDIDATE_LIMIT + 5):
            NoisePool.create(
                content=f"无关闲聊片段 {index}",
                source_scene="group_chat",
                source_id=f"raw_message_archive:high-{index}",
                significance=0.34,
                created_at=now,
                ttl_days=30,
            )
        low_signal_noise = NoisePool.create(
            content="很早之前小明把钢琴压力说成一块石头",
            source_scene="group_chat",
            source_id="raw_message_archive:low-connected",
            significance=0.08,
            created_at=now - datetime.timedelta(days=10),
            ttl_days=30,
        )
        writer = FakeWriter()
        engine = InspirationEngine(store=None, writer=writer, retention_days=30)

        result = await engine.recycle()

        self.assertEqual(result["insights"], 1)
        self.assertFalse(NoisePool.select().where(NoisePool.id == low_signal_noise.id).exists())
        self.assertEqual(writer.written_atoms, [])
        insight = InsightPool.get_or_none(InsightPool.agent_name == "dream_foreshadowing")
        self.assertIsNotNone(insight)
        assert insight is not None
        self.assertIn("atom-biased-sample-piano-1", insight.source_atoms or "")
        self.assertIn("atom-biased-sample-piano-2", insight.source_atoms or "")


if __name__ == "__main__":
    unittest.main()
