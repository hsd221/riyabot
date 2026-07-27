from __future__ import annotations

import datetime
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from peewee import IntegrityError

from src.memory.insight_engine import InsightEngine, _assoc_label, _atype_label, _display_name
from src.memory.schema import (
    AtomAssociationModel,
    InsightPool,
    MemoryAtom,
    configure_memory_database,
    initialize_database,
    memory_db,
)


def create_atom(atom_id: str, atom_type: str, *, content: str | None = None, entities: list[str] | None = None) -> None:
    now = datetime.datetime.now()
    MemoryAtom.create(
        atom_id=atom_id,
        atom_type=atom_type,
        content=content or f"{atom_id} content",
        entities=json.dumps(entities or [], ensure_ascii=False),
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


class InsightEngineDatabaseTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "memory.db"
        configure_memory_database(str(db_path))
        initialize_database()

    def tearDown(self) -> None:
        if not memory_db.is_closed():
            memory_db.close()
        self.tmpdir.cleanup()

    def test_atomic_scan_detects_distribution_skew_and_multifaceted_entities(self) -> None:
        for index in range(5):
            create_atom(f"episodic-{index}", "episodic", entities=["群聊"])
        create_atom("fact-xiaoming", "factual", entities=["小明"])
        create_atom("preference-xiaoming", "preference", entities=["小明"])
        create_atom("relational-xiaoming", "relational", entities=["小明"])

        insights = InsightEngine(object())._scan_atomic_patterns()

        self.assertTrue(any("episodic类型记忆占比" in insight["content"] for insight in insights))
        multifaceted = [insight for insight in insights if "「小明」" in insight["content"]]
        self.assertEqual(len(multifaceted), 1)
        self.assertEqual(
            json.loads(multifaceted[0]["source_atoms"]),
            ["fact-xiaoming", "preference-xiaoming", "relational-xiaoming"],
        )

    def test_profile_evolution_scan_detects_recent_mood_shift_and_style_change(self) -> None:
        engine = InsightEngine(object())
        engine._profile_store = SimpleNamespace(
            list_profiles=lambda: ["user_42", "empty"],
            get_profile=lambda user_id: {
                "user_42": SimpleNamespace(
                    mood_history=[
                        {"emotion_tags": ["neutral"]},
                        {"emotion_tags": ["joy"]},
                        {"emotion_tags": ["joy"]},
                        {"emotion_tags": ["sadness"]},
                    ],
                    expression_style="短句, 反问",
                    expression_patterns={"old_style": 2},
                )
            }.get(user_id),
        )

        insights = engine._scan_profile_evolution()

        self.assertTrue(any("用户42最近情绪更加积极阳光" in insight["content"] for insight in insights))
        self.assertTrue(any("用户42最近表达风格偏向「短句」" in insight["content"] for insight in insights))

    def test_association_scan_detects_hub_atoms_and_dominant_relationship_type(self) -> None:
        create_atom("hub", "factual", content="小明围绕钢琴训练形成持续记忆")
        for index in range(4):
            leaf_id = f"leaf-{index}"
            create_atom(leaf_id, "episodic")
            AtomAssociationModel.create(
                atom_a_id="hub",
                atom_b_id=leaf_id,
                association_type="co_occurrence",
                weight=0.8,
                evidence_count=2,
            )

        insights = InsightEngine(object())._scan_association_network()

        self.assertTrue(
            any(
                "形成了一个记忆集群" in insight["content"] and "关联了4条" in insight["content"] for insight in insights
            )
        )
        self.assertTrue(any("以共现关系为主" in insight["content"] for insight in insights))

    def test_association_scan_ignores_edges_connected_to_archived_atoms(self) -> None:
        create_atom("archived-hub", "factual", content="这条归档记忆不应继续形成洞见")
        MemoryAtom.update(status="archived").where(MemoryAtom.atom_id == "archived-hub").execute()
        for index in range(4):
            leaf_id = f"active-leaf-{index}"
            create_atom(leaf_id, "episodic")
            AtomAssociationModel.create(
                atom_a_id="archived-hub",
                atom_b_id=leaf_id,
                association_type="causal",
                weight=0.8,
                evidence_count=2,
            )

        insights = InsightEngine(object())._scan_association_network()

        self.assertEqual(insights, [])

    def test_dream_synthesis_scan_summarizes_repeated_recent_themes(self) -> None:
        now = datetime.datetime.now()
        for index in range(3):
            InsightPool.create(
                content="钢琴 压力",
                source_atoms=json.dumps([f"atom-{index}"]),
                agent_name="dream_weaver",
                confidence=0.5,
                created_at=now - datetime.timedelta(days=index),
            )
        InsightPool.create(
            content="钢琴 压力",
            source_atoms=None,
            agent_name="dream_weaver",
            confidence=0.5,
            created_at=now - datetime.timedelta(days=40),
        )

        insights = InsightEngine(object())._scan_dream_synthesis()

        self.assertEqual(len(insights), 1)
        self.assertIn("「钢琴、压力」", insights[0]["content"])
        self.assertEqual(len(json.loads(insights[0]["source_atoms"])), 3)

    async def test_generate_monthly_insights_persists_successful_scans_and_continues_after_scan_errors(self) -> None:
        engine = InsightEngine(object())
        atomic = {"content": "原子洞察", "source_atoms": None, "confidence": 0.61}
        association = {"content": "关联洞察", "source_atoms": json.dumps(["atom-1"]), "confidence": 0.72}

        with (
            patch.object(engine, "_scan_atomic_patterns", return_value=[atomic]),
            patch.object(engine, "_scan_profile_evolution", side_effect=RuntimeError("profile down")),
            patch.object(engine, "_scan_association_network", return_value=[association]),
            patch.object(engine, "_scan_dream_synthesis", return_value=[]),
        ):
            insights = await engine.generate_monthly_insights()

        self.assertEqual(insights, [atomic, association])
        saved = list(InsightPool.select().where(InsightPool.agent_name == "insight_engine").order_by(InsightPool.id))
        self.assertEqual([item.content for item in saved], ["原子洞察", "关联洞察"])
        self.assertEqual(saved[1].source_atoms, json.dumps(["atom-1"]))
        self.assertAlmostEqual(saved[1].confidence, 0.72)

        with (
            patch.object(engine, "_scan_atomic_patterns", return_value=[atomic]),
            patch.object(engine, "_scan_profile_evolution", return_value=[]),
            patch.object(engine, "_scan_association_network", return_value=[association]),
            patch.object(engine, "_scan_dream_synthesis", return_value=[]),
        ):
            repeated = await engine.generate_monthly_insights()

        self.assertEqual(repeated, [])
        self.assertEqual(InsightPool.select().where(InsightPool.agent_name == "insight_engine").count(), 2)

    async def test_generate_monthly_insights_normalizes_source_order_before_deduplication(self) -> None:
        engine = InsightEngine(object())
        first = {
            "content": "来源顺序不应制造重复",
            "source_atoms": json.dumps(["atom-b", "atom-a", "atom-a"]),
            "confidence": 0.7,
        }
        second = {
            "content": "来源顺序不应制造重复",
            "source_atoms": json.dumps(["atom-a", "atom-b"]),
            "confidence": 0.7,
        }

        with (
            patch.object(engine, "_scan_atomic_patterns", side_effect=[[first], [second]]),
            patch.object(engine, "_scan_profile_evolution", return_value=[]),
            patch.object(engine, "_scan_association_network", return_value=[]),
            patch.object(engine, "_scan_dream_synthesis", return_value=[]),
        ):
            first_saved = await engine.generate_monthly_insights()
            second_saved = await engine.generate_monthly_insights()

        self.assertEqual(first_saved, [first])
        self.assertEqual(second_saved, [])
        saved = InsightPool.get(InsightPool.agent_name == "insight_engine")
        self.assertEqual(json.loads(saved.source_atoms), ["atom-a", "atom-b"])

    def test_initialize_database_normalizes_existing_insights_and_adds_unique_identity_index(self) -> None:
        memory_db.execute_sql("DROP INDEX IF EXISTS idx_insight_pool_identity")
        InsightPool.create(
            content="并发幂等洞见",
            source_atoms=json.dumps(["atom-b", "atom-a", "atom-a"]),
            agent_name="insight_engine",
            confidence=0.6,
        )
        InsightPool.create(
            content="并发幂等洞见",
            source_atoms=json.dumps(["atom-a", "atom-b"]),
            agent_name="insight_engine",
            confidence=0.8,
        )

        initialize_database()

        rows = list(InsightPool.select().where(InsightPool.content == "并发幂等洞见"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0].source_atoms), ["atom-a", "atom-b"])
        self.assertEqual(rows[0].confidence, 0.8)
        with self.assertRaises(IntegrityError):
            InsightPool.create(
                content="并发幂等洞见",
                source_atoms=json.dumps(["atom-a", "atom-b"]),
                agent_name="insight_engine",
                confidence=0.4,
            )

    def test_unique_identity_index_treats_null_sources_as_same_identity(self) -> None:
        InsightPool.create(
            content="无来源洞见",
            source_atoms=None,
            agent_name="insight_engine",
            confidence=0.6,
        )

        with self.assertRaises(IntegrityError):
            InsightPool.create(
                content="无来源洞见",
                source_atoms=None,
                agent_name="insight_engine",
                confidence=0.7,
            )


class InsightEngineHelperTest(unittest.TestCase):
    def test_label_helpers_return_known_translations_and_fallbacks(self) -> None:
        self.assertEqual(_atype_label("preference"), "偏好")
        self.assertEqual(_atype_label("custom"), "custom")
        self.assertEqual(_assoc_label("causal"), "因果")
        self.assertEqual(_assoc_label("custom"), "custom")
        self.assertEqual(_display_name("user_42"), "用户42")
        self.assertEqual(_display_name("alice"), "alice")


if __name__ == "__main__":
    unittest.main()
