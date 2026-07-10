"""DreamTask behavior regressions.

These tests cover the dream system responsibilities that should exist
independently of the scheduler and external LLM/vector services.
"""

from __future__ import annotations

import datetime
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from src.memory.dream_agent import DreamTask
from src.memory.layer1_summarizer import UnclosedTopicBridge
from src.memory.schema import (
    ConflictObservation,
    DreamRun,
    EpisodicDetail,
    InsightPool,
    MemoryTraceChain,
    MemoryAtom,
    NoisePool,
    RawMessageArchive,
    SemanticDetail,
    configure_memory_database,
    initialize_database,
    memory_db,
)
from src.memory.user_profile import ProfileStore, UserProfile


class FakeQdrant:
    def __init__(self) -> None:
        self.payload_updates: list[tuple[str, dict[str, Any]]] = []
        self.vector_upserts: list[tuple[str, list[float], dict[str, Any]]] = []

    async def set_atom_payload(self, atom_id: str, payload: dict[str, Any]) -> None:
        self.payload_updates.append((atom_id, payload))

    async def upsert_atom_vector(
        self,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> bool:
        self.vector_upserts.append((point_id, vector, payload))
        return True


class FakeStore:
    def __init__(self) -> None:
        self.qdrant = FakeQdrant()


class FakeForgettingManager:
    def __init__(self) -> None:
        self.calls = 0

    async def run_sweep(self) -> dict[str, int]:
        self.calls += 1
        return {"decayed": 2, "archived": 1, "deleted": 0}


class DreamTaskDatabaseTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "memory.db"
        configure_memory_database(str(db_path))
        initialize_database()
        self._bridge_data_dir = UnclosedTopicBridge._DATA_DIR
        self._bridge_file_path = UnclosedTopicBridge._FILE_PATH
        UnclosedTopicBridge._DATA_DIR = self.tmpdir.name
        UnclosedTopicBridge._FILE_PATH = str(Path(self.tmpdir.name) / "topic_bridge.json")
        self.generate_embedding = AsyncMock(return_value=[0.1, 0.2, 0.3])
        self._embedding_patcher = patch(
            "src.memory.dream_agent.generate_embedding",
            new=self.generate_embedding,
        )
        self._embedding_patcher.start()

    def tearDown(self) -> None:
        self._embedding_patcher.stop()
        UnclosedTopicBridge._DATA_DIR = self._bridge_data_dir
        UnclosedTopicBridge._FILE_PATH = self._bridge_file_path
        if not memory_db.is_closed():
            memory_db.close()
        self.tmpdir.cleanup()

    async def test_consolidate_persists_last_accessed_at_to_keep_dream_boost_effective(self) -> None:
        old_access = datetime.datetime.now() - datetime.timedelta(days=10)
        MemoryAtom.create(
            atom_id="atom-dream-boost",
            atom_type="episodic",
            content="小明在群里明确说自己正在练习钢琴",
            entities='["小明"]',
            importance=0.8,
            confidence=0.8,
            weight=0.2,
            created_at=old_access,
            last_accessed_at=old_access,
            last_reinforced_at=old_access,
            ttl_days=30,
            decay_type="exponential",
            reinforcement_count=0,
            source_scene="group_chat",
            privacy_level="context_sensitive",
            status="active",
        )

        task = DreamTask(FakeStore())

        consolidated = await task._consolidate()

        atom = MemoryAtom.get(MemoryAtom.atom_id == "atom-dream-boost")
        self.assertEqual(consolidated, 1)
        self.assertGreater(atom.weight, 0.2)
        self.assertGreater(atom.last_accessed_at, old_access)
        self.assertTrue(
            any("last_accessed_at" in payload for _, payload in task._store.qdrant.payload_updates),
            "Qdrant payload should receive the refreshed access timestamp alongside weight",
        )

    async def test_reassess_memory_scores_uses_semantic_evidence_and_pending_conflicts(self) -> None:
        now = datetime.datetime.now()
        MemoryAtom.create(
            atom_id="atom-supported",
            atom_type="factual",
            content="小明长期喜欢爵士乐",
            entities='["小明", "爵士乐"]',
            importance=0.45,
            confidence=0.5,
            weight=0.225,
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
        SemanticDetail.create(
            id="atom-supported",
            atom="atom-supported",
            attr_category="interest",
            attr_name="music",
            attr_value="jazz",
            evidence_list='["msg-1", "msg-2", "msg-3"]',
            evidence_counter=3,
        )
        MemoryAtom.create(
            atom_id="atom-contested",
            atom_type="factual",
            content="小明讨厌爵士乐",
            entities='["小明", "爵士乐"]',
            importance=0.7,
            confidence=0.8,
            weight=0.56,
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
        ConflictObservation.create(
            atom_a_id="atom-contested",
            atom_b_id="atom-supported",
            conflict_type="contradiction",
            description="音乐偏好冲突",
            status="pending",
            created_at=now,
        )

        task = DreamTask(FakeStore())

        updated = await task._reassess_memory_scores()

        supported = MemoryAtom.get(MemoryAtom.atom_id == "atom-supported")
        contested = MemoryAtom.get(MemoryAtom.atom_id == "atom-contested")
        self.assertEqual(updated, 2)
        self.assertGreater(supported.confidence, 0.5)
        self.assertGreater(supported.importance, 0.45)
        self.assertGreater(supported.weight, 0.225)
        self.assertLess(contested.confidence, 0.8)
        self.assertLess(contested.weight, 0.56)
        qdrant_payloads = [payload for _, payload in task._store.qdrant.payload_updates]
        self.assertTrue(any("confidence" in payload and "importance" in payload for payload in qdrant_payloads))

    async def test_forgetting_sweep_archives_low_weight_atoms_without_injected_manager(self) -> None:
        old_time = datetime.datetime.now() - datetime.timedelta(days=1)
        MemoryAtom.create(
            atom_id="atom-faded-default-sweep",
            atom_type="episodic",
            content="小明很久以前随口提到一件无后续的小事",
            entities='["小明"]',
            importance=0.2,
            confidence=0.4,
            weight=0.05,
            created_at=old_time,
            last_accessed_at=old_time,
            last_reinforced_at=old_time,
            ttl_days=365,
            decay_type="exponential",
            reinforcement_count=0,
            source_scene="group_chat",
            privacy_level="context_sensitive",
            status="active",
        )
        task = DreamTask(FakeStore())

        stats = await task._run_forgetting_sweep()

        atom = MemoryAtom.get(MemoryAtom.atom_id == "atom-faded-default-sweep")
        archived = RawMessageArchive.get_or_none(RawMessageArchive.message_id == "atom-faded-default-sweep")
        self.assertGreaterEqual(stats["archived"], 1)
        self.assertEqual(atom.status, "archived")
        self.assertIsNotNone(archived)
        assert archived is not None
        self.assertEqual(archived.chat_type, "memory_archive_episodic")
        self.assertIn("小明很久以前", archived.content)

    async def test_triage_raw_archive_routes_daily_material_by_significance(self) -> None:
        now_ts = datetime.datetime.now().timestamp()
        high = RawMessageArchive.create(
            stream_id="group-1",
            message_id="msg-high",
            user_id="user-a",
            content="小明崩溃大哭，说自己再也不想上学了",
            timestamp=now_ts,
            chat_type="group",
        )
        medium = RawMessageArchive.create(
            stream_id="group-1",
            message_id="msg-medium",
            user_id="user-b",
            content="小明说今天开始练钢琴",
            timestamp=now_ts,
            chat_type="group",
        )
        low = RawMessageArchive.create(
            stream_id="group-1",
            message_id="msg-low",
            user_id="user-c",
            content="哈哈哈",
            timestamp=now_ts,
            chat_type="group",
        )

        task = DreamTask(FakeStore())

        stats = await task._triage_raw_archive(max_age_days=1)

        self.assertEqual(stats, {"high": 1, "medium": 1, "low": 1, "skipped": 0})
        self.assertEqual(
            {
                RawMessageArchive.get_by_id(high.id).dream_route,
                RawMessageArchive.get_by_id(medium.id).dream_route,
                RawMessageArchive.get_by_id(low.id).dream_route,
            },
            {"high", "medium", "low"},
        )
        self.assertEqual(MemoryAtom.select().count(), 2)
        self.assertEqual(EpisodicDetail.select().count(), 2)
        self.assertEqual(NoisePool.select().count(), 1)
        self.assertTrue(
            MemoryTraceChain.select()
            .where(MemoryTraceChain.agent_name == "DreamTriageAgent", MemoryTraceChain.operation_type == "triage")
            .exists()
        )

        repeated = await task._triage_raw_archive(max_age_days=1)

        self.assertEqual(repeated, {"high": 0, "medium": 0, "low": 0, "skipped": 0})
        self.assertEqual(MemoryAtom.select().count(), 2)
        self.assertEqual(NoisePool.select().count(), 1)

    async def test_triage_syncs_new_active_dream_raw_atom_to_qdrant(self) -> None:
        raw = RawMessageArchive.create(
            stream_id="group-1",
            message_id="msg-vector-sync",
            user_id="user-a",
            content="小明说今天开始练钢琴",
            timestamp=datetime.datetime.now().timestamp(),
            chat_type="group",
        )
        task = DreamTask(FakeStore())
        embedding = [0.1, 0.2, 0.3]

        self.generate_embedding.return_value = embedding
        stats = await task._triage_raw_archive(max_age_days=1)

        atom_id = f"dream-raw-{raw.id}"
        atom = MemoryAtom.get(MemoryAtom.atom_id == atom_id)
        self.assertEqual(stats["medium"], 1)
        self.assertEqual(atom.status, "active")
        self.generate_embedding.assert_awaited_once_with(atom.content)
        self.assertTrue(
            any(
                point_id == atom_id and vector == embedding and payload.get("status") == "active"
                for point_id, vector, payload in task._store.qdrant.vector_upserts
            ),
            "A newly active dream-raw atom must have a matching Qdrant vector before triage returns",
        )

    async def test_triage_treats_archived_conversation_summary_as_summary_material(self) -> None:
        now_ts = datetime.datetime.now().timestamp()
        summary = RawMessageArchive.create(
            stream_id="group-1",
            message_id="summary-1",
            user_id="system",
            content="本轮对话摘要：小明说自己开始准备钢琴考试，压力很大",
            timestamp=now_ts,
            chat_type="summary",
        )

        task = DreamTask(FakeStore())

        stats = await task._triage_raw_archive(max_age_days=1)

        self.assertEqual(stats["high"], 1)
        atom = MemoryAtom.get(MemoryAtom.atom_id == f"dream-raw-{summary.id}")
        self.assertEqual(atom.source_scene, "summary")
        self.assertIn("对话摘要", atom.content)
        self.assertIn("raw_message_archive", atom.source_id or "")

    async def test_ingest_topic_bridge_summaries_as_pending_dream_material_without_consuming_bridge(self) -> None:
        now_ts = datetime.datetime.now().timestamp()
        bridge_path = Path(UnclosedTopicBridge._FILE_PATH)
        bridge_payload = {
            "group-1": [
                {
                    "topic_id": "piano-pressure",
                    "topic_name": "钢琴、压力",
                    "keywords": ["钢琴", "压力"],
                    "last_active": now_ts,
                    "participant_count": 2,
                    "message_count": 6,
                    "summary": "小明说自己开始准备钢琴考试，压力很大",
                }
            ]
        }
        bridge_path.write_text(json.dumps(bridge_payload, ensure_ascii=False), encoding="utf-8")

        task = DreamTask(FakeStore())

        ingested = task._ingest_topic_bridge_summaries(max_age_days=1)

        self.assertEqual(ingested, 1)
        archived = RawMessageArchive.get(RawMessageArchive.chat_type == "topic_summary")
        self.assertEqual(archived.stream_id, "group-1")
        self.assertEqual(archived.user_id, "system")
        self.assertEqual(archived.dream_status, "pending")
        self.assertIn("话题摘要", archived.content)
        self.assertEqual(json.loads(bridge_path.read_text(encoding="utf-8")), bridge_payload)

        stats = await task._triage_raw_archive(max_age_days=1)

        self.assertEqual(stats["high"], 1)
        atom = MemoryAtom.get(MemoryAtom.source_id == f"raw_message_archive:{archived.id}")
        self.assertEqual(atom.source_scene, "summary")
        self.assertIn("对话摘要", atom.content)

    async def test_ingest_topic_bridge_summaries_skips_legacy_raw_archive_schema_without_warning(self) -> None:
        now_ts = datetime.datetime.now().timestamp()
        bridge_path = Path(UnclosedTopicBridge._FILE_PATH)
        bridge_payload = {
            "group-1": [
                {
                    "topic_id": "piano-pressure",
                    "last_active": now_ts,
                    "summary": "小明说自己开始准备钢琴考试，压力很大",
                }
            ]
        }
        bridge_path.write_text(json.dumps(bridge_payload, ensure_ascii=False), encoding="utf-8")
        with memory_db:
            memory_db.drop_tables([RawMessageArchive], safe=True)
            memory_db.execute_sql(
                """
                CREATE TABLE raw_message_archive (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stream_id TEXT,
                    message_id TEXT,
                    user_id TEXT,
                    content TEXT,
                    timestamp REAL,
                    chat_type TEXT
                )
                """
            )

        task = DreamTask(FakeStore())

        with self.assertNoLogs("memory.dream", level="WARNING"):
            ingested = task._ingest_topic_bridge_summaries(max_age_days=1)

        self.assertEqual(ingested, 0)
        with memory_db:
            row_count = memory_db.execute_sql("SELECT COUNT(*) FROM raw_message_archive").fetchone()[0]
        self.assertEqual(row_count, 0)

    async def test_high_significance_triage_runs_emotion_replay_and_pattern_extraction(self) -> None:
        now_ts = datetime.datetime.now().timestamp()
        raw = RawMessageArchive.create(
            stream_id="group-1",
            message_id="msg-high-emotion",
            user_id="user-a",
            content="小明崩溃大哭，说自己再也不想上学了，压力大到受不了",
            timestamp=now_ts,
            chat_type="group",
        )
        task = DreamTask(FakeStore())

        stats = await task._triage_raw_archive(max_age_days=1)

        atom_id = f"dream-raw-{raw.id}"
        self.assertEqual(stats["high"], 1)
        self.assertTrue(MemoryAtom.select().where(MemoryAtom.atom_id == atom_id).exists())
        trace_operations = [
            (trace.agent_name, trace.operation_type)
            for trace in MemoryTraceChain.select()
            .where(MemoryTraceChain.atom_id == atom_id)
            .order_by(MemoryTraceChain.step_number.asc())
        ]
        self.assertEqual(
            trace_operations,
            [
                ("DreamTriageAgent", "triage"),
                ("DreamEmotionReplayAgent", "emotion_replay"),
                ("DreamPatternAgent", "pattern_extract"),
            ],
        )

        emotion_insight = InsightPool.get_or_none(InsightPool.agent_name == "dream_emotion_replay")
        pattern_insight = InsightPool.get_or_none(InsightPool.agent_name == "dream_pattern_extract")
        self.assertIsNotNone(emotion_insight)
        self.assertIsNotNone(pattern_insight)
        assert emotion_insight is not None
        assert pattern_insight is not None
        self.assertIn("情绪重演", emotion_insight.content)
        self.assertIn("distress", emotion_insight.content)
        self.assertIn("模式提炼", pattern_insight.content)
        self.assertIn("压力", pattern_insight.content)
        self.assertIn(atom_id, emotion_insight.source_atoms or "")
        self.assertIn(atom_id, pattern_insight.source_atoms or "")

    async def test_high_significance_emotion_replay_updates_profile_mood_history(self) -> None:
        now_ts = datetime.datetime.now().timestamp()
        RawMessageArchive.create(
            stream_id="group-1",
            message_id="msg-high-profile-mood",
            user_id="user-a",
            content="小明焦虑到崩溃，说压力大到受不了",
            timestamp=now_ts,
            chat_type="group",
        )
        task = DreamTask(FakeStore())

        await task._triage_raw_archive(max_age_days=1)

        profile = ProfileStore().get_profile("user-a")
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(len(profile.mood_history), 1)
        mood_entry = profile.mood_history[0]
        self.assertIn("distress", mood_entry["emotion_tags"])
        self.assertIn("emotional:distress", mood_entry["sensory_tags"])
        self.assertIn("小明焦虑到崩溃", mood_entry["content"])

    async def test_adjust_privacy_levels_locks_sensitive_private_memories(self) -> None:
        now = datetime.datetime.now()
        MemoryAtom.create(
            atom_id="atom-private-sensitive",
            atom_type="episodic",
            content="小明在私聊中告诉我他的身份证号码是 123456789012345678",
            entities='["小明"]',
            importance=0.7,
            confidence=0.8,
            weight=0.56,
            created_at=now,
            last_accessed_at=now,
            last_reinforced_at=now,
            ttl_days=30,
            decay_type="exponential",
            reinforcement_count=0,
            source_scene="private_chat",
            source_id="private-stream-1",
            privacy_level="context_sensitive",
            status="active",
        )

        task = DreamTask(FakeStore())

        stats = await task._adjust_privacy_levels()

        atom = MemoryAtom.get(MemoryAtom.atom_id == "atom-private-sensitive")
        self.assertEqual(stats, {"locked_private": 1, "unlocked_public": 0})
        self.assertEqual(atom.privacy_level, "private")
        self.assertTrue(
            any(
                atom_id == "atom-private-sensitive" and payload.get("privacy_level") == "private"
                for atom_id, payload in task._store.qdrant.payload_updates
            )
        )

    async def test_adjust_privacy_levels_unlocks_cross_scene_low_risk_facts(self) -> None:
        now = datetime.datetime.now()
        group_raw = RawMessageArchive.create(
            stream_id="group-1",
            message_id="msg-group-fact",
            user_id="user-a",
            content="小明说自己喜欢爵士乐",
            timestamp=now.timestamp(),
            chat_type="group",
        )
        private_raw = RawMessageArchive.create(
            stream_id="private-1",
            message_id="msg-private-fact",
            user_id="user-a",
            content="小明私聊里也说自己喜欢爵士乐",
            timestamp=now.timestamp(),
            chat_type="private",
        )
        MemoryAtom.create(
            atom_id="atom-cross-scene-fact",
            atom_type="preference",
            content="小明喜欢爵士乐",
            entities='["小明", "爵士乐"]',
            importance=0.75,
            confidence=0.85,
            weight=0.6375,
            created_at=now,
            last_accessed_at=now,
            last_reinforced_at=now,
            ttl_days=60,
            decay_type="exponential",
            reinforcement_count=0,
            source_scene="group_chat",
            source_id="group-1",
            privacy_level="context_sensitive",
            status="active",
        )
        SemanticDetail.create(
            id="atom-cross-scene-fact",
            atom="atom-cross-scene-fact",
            attr_category="interest",
            attr_name="music",
            attr_value="jazz",
            evidence_list=f'["raw_message_archive:{group_raw.id}", "raw_message_archive:{private_raw.id}"]',
            evidence_counter=2,
        )

        task = DreamTask(FakeStore())

        stats = await task._adjust_privacy_levels()

        atom = MemoryAtom.get(MemoryAtom.atom_id == "atom-cross-scene-fact")
        self.assertEqual(stats, {"locked_private": 0, "unlocked_public": 1})
        self.assertEqual(atom.privacy_level, "public")
        self.assertTrue(
            any(
                atom_id == "atom-cross-scene-fact" and payload.get("privacy_level") == "public"
                for atom_id, payload in task._store.qdrant.payload_updates
            )
        )

    async def test_merge_overflowing_user_memories_generalizes_soft_cap_overflow(self) -> None:
        now = datetime.datetime.now()
        for index in range(5):
            MemoryAtom.create(
                atom_id=f"atom-xiaoming-overflow-{index}",
                atom_type="episodic",
                content=f"小明第 {index} 次提到自己在练习爵士钢琴",
                entities='["小明", "爵士钢琴"]',
                importance=0.45 + index * 0.02,
                confidence=0.7,
                weight=0.1 + index * 0.05,
                created_at=now - datetime.timedelta(days=10 - index),
                last_accessed_at=now - datetime.timedelta(days=10 - index),
                last_reinforced_at=now - datetime.timedelta(days=10 - index),
                ttl_days=30,
                decay_type="exponential",
                reinforcement_count=0,
                source_scene="group_chat",
                source_id=f"group-1-msg-{index}",
                privacy_level="context_sensitive",
                status="active",
            )

        task = DreamTask(FakeStore())

        stats = await task._merge_overflowing_user_memories(soft_cap=3, batch_size=10)

        active_atoms = list(MemoryAtom.select().where(MemoryAtom.status == "active"))
        archived_atoms = list(MemoryAtom.select().where(MemoryAtom.status == "archived"))
        summary = MemoryAtom.get(MemoryAtom.source_scene == "dream", MemoryAtom.source_id.startswith("dream_soft_cap:"))
        self.assertEqual(
            stats,
            {"users_compacted": 1, "atoms_archived": 3, "summaries_created": 1, "summaries_updated": 0},
        )
        self.assertEqual(len(active_atoms), 3)
        self.assertEqual(len(archived_atoms), 3)
        self.assertIn("小明", summary.content)
        self.assertIn("泛化", summary.content)
        self.assertEqual(summary.atom_type, "factual")
        self.assertTrue(
            MemoryTraceChain.select()
            .where(
                MemoryTraceChain.atom_id == summary.atom_id,
                MemoryTraceChain.agent_name == "DreamSoftCapAgent",
                MemoryTraceChain.operation_type == "merge",
            )
            .exists()
        )
        self.assertTrue(
            any(
                atom_id == summary.atom_id and payload.get("status") == "active"
                for atom_id, payload in task._store.qdrant.payload_updates
            )
        )
        self.assertTrue(any(payload.get("status") == "archived" for _, payload in task._store.qdrant.payload_updates))

        repeated = await task._merge_overflowing_user_memories(soft_cap=3, batch_size=10)

        self.assertEqual(
            repeated,
            {"users_compacted": 0, "atoms_archived": 0, "summaries_created": 0, "summaries_updated": 0},
        )

    async def test_audit_profiles_rebuilds_stale_profile_and_records_insight(self) -> None:
        now = datetime.datetime.now()
        profile_store = ProfileStore()
        profile_store.save_profile(
            UserProfile(
                user_id="小明",
                preferences={"music": "rock"},
                facts={"city": "上海"},
                stats={"message_count": 12},
                mood_history=[
                    {
                        "timestamp": now.isoformat(),
                        "sensory_tags": ["emotional:calm"],
                        "emotion_tags": ["calm"],
                        "temporal_context": "旧记录",
                        "content": "旧情绪片段",
                    }
                ],
                expression_style="short",
                expression_patterns={"ending": ["呢"]},
                impression="旧画像",
            )
        )
        MemoryAtom.create(
            atom_id="atom-profile-supported",
            atom_type="preference",
            content="小明最近多次说自己喜欢爵士钢琴",
            entities='["小明", "爵士钢琴"]',
            importance=0.75,
            confidence=0.85,
            weight=0.6375,
            created_at=now,
            last_accessed_at=now,
            last_reinforced_at=now,
            ttl_days=180,
            decay_type="exponential",
            reinforcement_count=0,
            source_scene="group_chat",
            source_id="group-1",
            privacy_level="context_sensitive",
            status="active",
        )
        SemanticDetail.create(
            id="atom-profile-supported",
            atom="atom-profile-supported",
            attr_category="preference",
            attr_name="music",
            attr_value="jazz",
            evidence_list='["msg-1", "msg-2"]',
            evidence_counter=2,
        )

        task = DreamTask(FakeStore())

        discrepancies = task._audit_profiles()

        audited = profile_store.get_profile("小明")
        self.assertIsNotNone(audited)
        assert audited is not None
        self.assertGreaterEqual(discrepancies, 2)
        self.assertEqual(audited.preferences, {"music": "jazz"})
        self.assertEqual(audited.facts, {})
        self.assertEqual(audited.stats.get("message_count"), 12)
        self.assertEqual(audited.mood_history[0]["content"], "旧情绪片段")
        self.assertEqual(audited.expression_style, "short")
        self.assertEqual(audited.expression_patterns, {"ending": ["呢"]})

        insight = InsightPool.get_or_none(InsightPool.agent_name == "dream_profile_audit")
        self.assertIsNotNone(insight)
        assert insight is not None
        self.assertIn("画像审计", insight.content)
        self.assertIn("city", insight.content)
        self.assertIn("music", insight.content)
        self.assertIn("atom-profile-supported", insight.source_atoms or "")

    async def test_monthly_cycle_persists_detailed_report_as_observable_insight(self) -> None:
        class MonthlyDreamTask(DreamTask):
            def _audit_atom_distribution(self) -> dict[str, Any]:
                return {
                    "total": 4,
                    "total_active": 3,
                    "total_archived": 1,
                    "total_forgotten": 0,
                    "type_distribution": {"episodic": 2, "factual": 1},
                    "weight_ranges": {"low(0-0.3)": 1, "mid(0.3-0.7)": 1, "high(0.7-1.0)": 1},
                    "empty_types": ["planned"],
                }

            def _audit_profiles(self) -> int:
                return 2

            async def _resolve_conflicts(self) -> int:
                return 1

            async def _reassess_memory_scores(
                self,
                max_age_days: int | None = None,
                batch_size: int | None = None,
            ) -> int:
                return 3

            async def _adjust_privacy_levels(
                self,
                max_age_days: int | None = None,
                batch_size: int | None = None,
            ) -> dict[str, int]:
                return {"locked_private": 1, "unlocked_public": 1}

            async def _merge_overflowing_user_memories(
                self,
                soft_cap: int | None = None,
                batch_size: int | None = None,
            ) -> dict[str, int]:
                return {"users_compacted": 1, "atoms_archived": 2, "summaries_created": 1, "summaries_updated": 0}

            async def _run_forgetting_sweep(self) -> dict[str, int]:
                return {"decayed": 2, "archived": 1, "deleted": 0}

            async def _build_graph(self, limit: int | None = None) -> tuple[int, int]:
                return (1, 1)

            async def _recycle_noise(self, retention_days: int) -> tuple[int, int, int]:
                return (1, 0, 1)

            async def _clean_noise(self, older_than_days: int | None = None) -> int:
                return 1

        task = MonthlyDreamTask(FakeStore())

        await task._run_monthly_cycle()

        run = DreamRun.get(DreamRun.run_type == "monthly")
        self.assertEqual(run.status, "completed")
        self.assertIn("N2", run.summary)
        self.assertIn("N3", run.summary)
        self.assertIn("REM", run.summary)

        report = InsightPool.get_or_none(InsightPool.agent_name == "dream_monthly_report")
        self.assertIsNotNone(report)
        assert report is not None
        self.assertIn("月度梦境报告", report.content)
        self.assertIn("健康问题", report.content)
        self.assertIn("画像差异: 2 条不匹配", report.content)
        self.assertIn("空分区: planned", report.content)
        self.assertIn("伏笔洞见: 1 条", report.content)
        self.assertIn(str(run.id), report.source_atoms or "")


class DreamTaskCycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_daily_cycle_runs_conflict_resolution_and_forgetting_sweep(self) -> None:
        events: list[str] = []

        class DailyDreamTask(DreamTask):
            def _create_dream_run(self, run_type: str) -> int | None:
                events.append(f"create:{run_type}")
                return 1

            def _finalize_dream_run(
                self,
                dream_run_id: int,
                status: str,
                atoms_processed: int,
                summary: str | None = None,
            ) -> None:
                events.append(f"finalize:{status}:{summary}")

            async def _consolidate(self, max_age_days: int | None = None, batch_size: int | None = None) -> int:
                events.append("consolidate")
                return 3

            async def _triage_raw_archive(
                self,
                max_age_days: int | None = 1,
                batch_size: int | None = None,
            ) -> dict[str, int]:
                events.append("triage_raw")
                return {"high": 1, "medium": 1, "low": 1, "skipped": 0}

            async def _resolve_conflicts(self) -> int:
                events.append("resolve_conflicts")
                return 2

            async def _reassess_memory_scores(
                self,
                max_age_days: int | None = None,
                batch_size: int | None = None,
            ) -> int:
                events.append("reassess")
                return 5

            async def _adjust_privacy_levels(
                self,
                max_age_days: int | None = None,
                batch_size: int | None = None,
            ) -> dict[str, int]:
                events.append("privacy")
                return {"locked_private": 1, "unlocked_public": 1}

            async def _run_forgetting_sweep(self) -> dict[str, int]:
                events.append("forgetting")
                return {"decayed": 2, "archived": 1, "deleted": 0}

            async def _clean_noise(self) -> int:
                events.append("clean_noise")
                return 4

        task = DailyDreamTask(FakeStore(), forgetting_manager=FakeForgettingManager())

        await task._run_daily_cycle()

        final_summary = next(event for event in events if event.startswith("finalize:completed:"))
        self.assertIn("N2", final_summary)
        self.assertIn("N3", final_summary)
        self.assertIn("REM", final_summary)
        self.assertIn("triage_raw", events)
        self.assertIn("resolve_conflicts", events)
        self.assertIn("reassess", events)
        self.assertIn("privacy", events)
        self.assertIn("forgetting", events)
        self.assertLess(events.index("triage_raw"), events.index("resolve_conflicts"))
        self.assertLess(events.index("resolve_conflicts"), events.index("reassess"))
        self.assertLess(events.index("reassess"), events.index("privacy"))
        self.assertLess(events.index("privacy"), events.index("forgetting"))
        self.assertLess(events.index("forgetting"), events.index("clean_noise"))

    async def test_weekly_cycle_recycles_noise_before_cleaning_it(self) -> None:
        events: list[str] = []

        class WeeklyDreamTask(DreamTask):
            def _create_dream_run(self, run_type: str) -> int | None:
                events.append(f"create:{run_type}")
                return 1

            def _finalize_dream_run(
                self,
                dream_run_id: int,
                status: str,
                atoms_processed: int,
                summary: str | None = None,
            ) -> None:
                events.append(f"finalize:{status}:{summary}")

            async def _consolidate(self, max_age_days: int | None = None, batch_size: int | None = None) -> int:
                events.append("consolidate")
                return 0

            async def _merge_overflowing_user_memories(
                self,
                soft_cap: int | None = None,
                batch_size: int | None = None,
            ) -> dict[str, int]:
                events.append("soft_cap")
                return {"users_compacted": 1, "atoms_archived": 2, "summaries_created": 1, "summaries_updated": 0}

            async def _resolve_conflicts(self) -> int:
                events.append("resolve_conflicts")
                return 0

            async def _reassess_memory_scores(
                self,
                max_age_days: int | None = None,
                batch_size: int | None = None,
            ) -> int:
                events.append("reassess")
                return 0

            async def _adjust_privacy_levels(
                self,
                max_age_days: int | None = None,
                batch_size: int | None = None,
            ) -> dict[str, int]:
                events.append("privacy")
                return {"locked_private": 0, "unlocked_public": 1}

            async def _run_forgetting_sweep(self) -> dict[str, int]:
                events.append("forgetting")
                return {"decayed": 0, "archived": 0, "deleted": 0}

            async def _recycle_noise(self, retention_days: int) -> tuple[int, int, int]:
                events.append(f"recycle:{retention_days}")
                return (1, 0, 1)

            async def _clean_noise(self, older_than_days: int | None = None) -> int:
                events.append(f"clean:{older_than_days}")
                return 0

            async def _build_graph(self, limit: int | None = None) -> tuple[int, int]:
                events.append(f"graph:{limit}")
                return (0, 0)

            async def _detect_cross_day_patterns(self) -> int:
                events.append("patterns")
                return 0

        task = WeeklyDreamTask(FakeStore())

        await task._run_weekly_cycle()

        final_summary = next(event for event in events if event.startswith("finalize:completed:"))
        self.assertIn("N2", final_summary)
        self.assertIn("N3", final_summary)
        self.assertIn("REM", final_summary)
        self.assertIn("privacy", events)
        self.assertIn("soft_cap", events)
        self.assertIn("recycle:14", events)
        self.assertIn("伏笔洞见1条", final_summary)
        self.assertLess(events.index("privacy"), events.index("forgetting"))
        self.assertLess(events.index("consolidate"), events.index("soft_cap"))
        self.assertLess(events.index("soft_cap"), events.index("forgetting"))
        self.assertLess(events.index("recycle:14"), events.index("clean:30"))


if __name__ == "__main__":
    unittest.main()
