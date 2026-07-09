import datetime
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.memory.inspiration_engine import InspirationEngine
from src.memory.schema import (
    InsightPool,
    MemoryAtom as MemoryAtomModel,
    NoisePool,
    configure_memory_database,
    initialize_database,
    memory_db,
)


def create_atom(atom_id: str, *, content: str, weight: float = 0.5, status: str = "active", **overrides) -> None:
    data = {
        "atom_id": atom_id,
        "atom_type": "factual",
        "content": content,
        "entities": json.dumps(["小明"], ensure_ascii=False),
        "importance": 0.7,
        "confidence": 0.8,
        "weight": weight,
        "created_at": datetime.datetime.now() - datetime.timedelta(days=30),
        "last_accessed_at": datetime.datetime.now(),
        "last_reinforced_at": datetime.datetime.now(),
        "ttl_days": 30,
        "decay_type": "exponential",
        "reinforcement_count": 0,
        "source_scene": "group_chat",
        "privacy_level": "context_sensitive",
        "status": status,
    }
    data.update(overrides)
    MemoryAtomModel.create(**data)


def create_noise(content: str, *, significance: float = 0.5, created_at: datetime.datetime | None = None) -> NoisePool:
    return NoisePool.create(
        content=content,
        significance=significance,
        created_at=created_at or datetime.datetime.now(),
    )


class InspirationEngineTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_path = memory_db.database
        configure_memory_database(str(Path(self.tmpdir.name) / "memory.db"))
        initialize_database()

    def tearDown(self) -> None:
        if not memory_db.is_closed():
            memory_db.close()
        configure_memory_database(str(self.original_path))
        self.tmpdir.cleanup()

    async def test_recycle_promotes_foreshadows_and_discards_candidates(self) -> None:
        create_atom("piano", content="小明 钢琴 练习记录", weight=0.9)
        create_atom("training", content="训练 复盘 比赛准备", weight=0.8)
        create_atom("match", content="比赛 舞台 迟到", weight=0.7)
        create_atom("hint", content="伏笔 线索 和 钢琴", weight=0.6)
        create_noise("昨天 小明 钢琴 训练 比赛 的片段", significance=1.3)
        create_noise("伏笔 钢琴 的奇怪片段", significance=0.4)
        create_noise("空白片段", significance=0.1)
        writer = SimpleNamespace(write_atom=AsyncMock(return_value=True))
        engine = InspirationEngine(store=SimpleNamespace(), writer=writer, retention_days=7)

        def fake_extract_keywords(content: str, max_keywords: int = 5) -> list[str]:
            if "空白" in content:
                return []
            if "伏笔" in content:
                return ["伏笔", "钢琴"]
            return ["钢琴", "训练", "比赛"]

        with patch("src.memory.inspiration_engine.extract_keywords", side_effect=fake_extract_keywords):
            result = await engine.recycle()

        self.assertEqual(result, {"promoted": 1, "discarded": 1, "insights": 1})
        self.assertEqual(NoisePool.select().count(), 0)
        writer.write_atom.assert_awaited_once()
        promoted_atom = writer.write_atom.await_args.kwargs["atom"]
        self.assertTrue(promoted_atom.atom_id.startswith("recycled_"))
        self.assertEqual(promoted_atom.content, "昨天 小明 钢琴 训练 比赛 的片段")
        self.assertEqual(promoted_atom.importance, 1.0)
        self.assertEqual(promoted_atom.confidence, engine.PROMOTED_CONFIDENCE)
        self.assertEqual(promoted_atom.source_scene, "dream")

        insight = InsightPool.get()
        self.assertEqual(insight.agent_name, "dream_foreshadowing")
        self.assertEqual(insight.confidence, engine.FORESHADOW_CONFIDENCE)
        self.assertIn("伏笔洞见", insight.content)
        self.assertIn("伏笔、钢琴", insight.content)
        self.assertIn("piano", json.loads(insight.source_atoms))

    async def test_recycle_discards_keyworded_noise_when_it_matches_too_few_atoms(self) -> None:
        create_atom("single", content="钢琴 孤立线索", weight=0.9)
        create_noise("钢琴 但没有形成足够关联", significance=0.4)
        engine = InspirationEngine(store=SimpleNamespace(), writer=SimpleNamespace(write_atom=AsyncMock()), retention_days=7)

        with patch("src.memory.inspiration_engine.extract_keywords", return_value=["钢琴"]):
            result = await engine.recycle()

        self.assertEqual(result, {"promoted": 0, "discarded": 1, "insights": 0})
        self.assertEqual(NoisePool.select().count(), 0)
        self.assertEqual(InsightPool.select().count(), 0)
        engine._writer.write_atom.assert_not_awaited()

    async def test_recycle_returns_empty_stats_when_no_candidates_exist(self) -> None:
        engine = InspirationEngine(store=SimpleNamespace(), writer=SimpleNamespace(), retention_days=7)

        self.assertEqual(await engine.recycle(), {"promoted": 0, "discarded": 0, "insights": 0})

    def test_query_candidates_keeps_recent_high_and_low_signal_samples_and_handles_errors(self) -> None:
        now = datetime.datetime.now()
        old = create_noise("过期噪声", significance=1.0, created_at=now - datetime.timedelta(days=30))
        high = create_noise("高分噪声", significance=0.9, created_at=now)
        middle = create_noise("中分噪声", significance=0.5, created_at=now - datetime.timedelta(minutes=1))
        low = create_noise("低分噪声", significance=0.1, created_at=now - datetime.timedelta(minutes=2))
        engine = InspirationEngine(store=SimpleNamespace(), writer=SimpleNamespace(), retention_days=7)
        engine.CANDIDATE_LIMIT = 3
        engine.LOW_SIGNAL_SAMPLE_LIMIT = 2

        candidate_ids = [candidate.id for candidate in engine._query_candidates()]

        self.assertEqual(candidate_ids, [high.id, low.id, middle.id])
        self.assertNotIn(old.id, candidate_ids)

        with patch("src.memory.inspiration_engine.NoisePool.select", side_effect=RuntimeError("db down")):
            self.assertEqual(engine._query_candidates(), [])

    def test_keyword_matching_filters_active_atoms_orders_by_weight_limits_and_handles_errors(self) -> None:
        create_atom("weak", content="钢琴 旧线索", weight=0.1)
        create_atom("strong", content="钢琴 强线索", weight=0.9)
        create_atom("archived", content="钢琴 已归档", weight=1.0, status="archived")
        engine = InspirationEngine(store=SimpleNamespace(), writer=SimpleNamespace(), retention_days=7)

        self.assertEqual(engine._count_keyword_matches([]), 0)
        self.assertEqual(engine._count_keyword_matches(["钢琴"]), 2)
        limited = engine._matched_keyword_atoms(["钢琴"], limit=1)
        self.assertEqual([atom.atom_id for atom in limited], ["strong"])
        self.assertEqual(engine._matched_keyword_atoms([]), [])

        with patch("src.memory.inspiration_engine.MemoryAtomModel.select", side_effect=RuntimeError("db down")):
            self.assertEqual(engine._matched_keyword_atoms(["钢琴"]), [])

    def test_temporal_gap_requires_marker_and_absence_of_recent_active_memory(self) -> None:
        engine = InspirationEngine(store=SimpleNamespace(), writer=SimpleNamespace(), retention_days=7)

        self.assertFalse(engine._has_temporal_gap("钢琴训练"))
        self.assertTrue(engine._has_temporal_gap("昨天的钢琴训练"))

        create_atom("recent", content="最近已经覆盖过", created_at=datetime.datetime.now())
        self.assertFalse(engine._has_temporal_gap("昨天的钢琴训练"))

        with patch("src.memory.inspiration_engine.MemoryAtomModel.select", side_effect=RuntimeError("db down")):
            self.assertFalse(engine._has_temporal_gap("昨天的钢琴训练"))

    async def test_promote_keeps_noise_when_writer_fails_and_delete_handles_database_errors(self) -> None:
        noise = create_noise("昨天的重要噪声", significance=0.8)
        writer = SimpleNamespace(write_atom=AsyncMock(side_effect=RuntimeError("writer down")))
        engine = InspirationEngine(store=SimpleNamespace(), writer=writer, retention_days=7)

        await engine._promote(noise)

        self.assertTrue(NoisePool.select().where(NoisePool.id == noise.id).exists())
        with patch("src.memory.inspiration_engine.NoisePool.delete", side_effect=RuntimeError("db down")):
            InspirationEngine._delete_noise(noise.id)

    def test_foreshadowing_insight_truncates_sources_uses_fallback_keywords_and_handles_errors(self) -> None:
        noise = create_noise("  伏笔   内容   " * 20, significance=0.2)
        matched_atoms = [SimpleNamespace(atom_id=f"atom-{index}") for index in range(4)]
        engine = InspirationEngine(store=SimpleNamespace(), writer=SimpleNamespace(), retention_days=7)
        engine.FORESHADOW_SOURCE_LIMIT = 2

        engine._write_foreshadowing_insight(noise, [], matched_atoms)

        insight = InsightPool.get()
        self.assertIn("相关线索", insight.content)
        self.assertLessEqual(len(insight.content), 160)
        self.assertEqual(json.loads(insight.source_atoms), ["atom-0", "atom-1"])

        with patch("src.memory.inspiration_engine.InsightPool.create", side_effect=RuntimeError("db down")):
            engine._write_foreshadowing_insight(noise, ["钢琴"], matched_atoms)


if __name__ == "__main__":
    unittest.main()
