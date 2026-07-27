import json
import builtins
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.memory import dream_weaver, encoding_pipeline
from src.memory.atom import AtomType
from src.memory.dream_weaver import DreamWeaver, _escape_prompt_data, _validate_insights
from src.memory.encoding_pipeline import EncodingPipeline, EncodingTask, get_encoding_pipeline
from src.memory.layer2_encoder import SOURCE_USER_IDS_DETAIL_KEY
from src.memory.user_profile import PersonIdentity
from src.memory.schema import (
    InsightPool,
    NoisePool,
    PendingAtomWrite,
    configure_memory_database,
    initialize_database,
    memory_db,
)


class MemoryDatabaseFixtureMixin:
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


class DreamWeaverTest(MemoryDatabaseFixtureMixin, unittest.IsolatedAsyncioTestCase):
    def make_noise(self, content: str, *, source_scene: str = "chat", hours_ago: int = 1) -> NoisePool:
        return NoisePool.create(
            content=content,
            source_scene=source_scene,
            source_id=f"source-{content}",
            significance=0.1,
            created_at=datetime.now() - timedelta(hours=hours_ago),
        )

    def test_prompt_escaping_building_and_insight_validation_keep_noise_low_confidence(self) -> None:
        self.assertEqual(_escape_prompt_data("<tag>&"), "&lt;tag&gt;&amp;")
        noise = SimpleNamespace(source_scene="<group>&", content="<unsafe>&" + "长" * 120)

        prompt = DreamWeaver._build_weave_prompt([noise])

        self.assertIn("&lt;unsafe&gt;&amp;", prompt)
        self.assertIn("来源: &lt;group&gt;&amp;", prompt)
        self.assertIn("低置信度", prompt)
        self.assertNotIn("长" * 100, prompt)

        valid = _validate_insights(
            [
                {
                    "insight": "可能有弱关联",
                    "confidence": 9.0,
                    "noise_sources": [2, 1, 2, True, "bad", -1],
                },
                {"insight": "!!!", "noise_sources": [1, 2]},
                {"insight": "只有一个来源", "noise_sources": [1]},
                {"bad": "shape"},
            ]
        )

        self.assertEqual(valid, [{"insight": "可能有弱关联", "confidence": 0.6, "noise_sources": [1, 2]}])

    def test_parse_weave_response_accepts_json_markdown_single_dict_and_embedded_arrays(self) -> None:
        markdown = """```json
        [{"insight": "可能从两个片段看出共同话题", "mood": "curious", "confidence": 0.1, "noise_sources": [1, 2]}]
        ```"""
        single = '{"insight": "似乎有共同情绪", "noise_sources": [2, 3], "confidence": "bad"}'
        embedded = '前缀 [{"insight": "可能有弱关联", "noise_sources": [1, 3], "confidence": 0.5}] 后缀'

        self.assertEqual(DreamWeaver._parse_weave_response(markdown)[0]["confidence"], 0.2)
        self.assertEqual(DreamWeaver._parse_weave_response(single)[0]["confidence"], 0.4)
        self.assertEqual(DreamWeaver._parse_weave_response(embedded)[0]["noise_sources"], [1, 3])
        self.assertEqual(DreamWeaver._parse_weave_response("not json"), [])
        self.assertEqual(DreamWeaver._parse_weave_response("{}"), [])

    async def test_weave_skips_when_material_is_insufficient_and_saves_valid_insights(self) -> None:
        weaver = DreamWeaver(store=SimpleNamespace(), noise_retention_hours=72)
        few_entries = [self.make_noise(f"少量{i}") for i in range(3)]

        with patch.object(weaver, "_query_noise_entries", return_value=few_entries):
            self.assertEqual(await weaver.weave(), [])

        entries = [self.make_noise(f"噪声{i}") for i in range(12)]
        response = json.dumps(
            [
                {
                    "insight": "可能多次围绕同一话题开玩笑",
                    "mood": "playful",
                    "confidence": 0.5,
                    "noise_sources": [1, 3],
                },
                {
                    "insight": "重复来源编号应被规范化后保存",
                    "confidence": 0.7,
                    "noise_sources": [2, 4, 2],
                },
                {"insight": "来源越界后不足两个时应跳过", "confidence": 0.7, "noise_sources": [2, 99]},
            ],
            ensure_ascii=False,
        )

        with (
            patch.object(weaver, "_query_noise_entries", return_value=entries),
            patch.object(weaver, "_call_llm", new=AsyncMock(return_value=response)) as call_llm,
        ):
            saved = await weaver.weave()

        self.assertEqual(len(saved), 2)
        call_llm.assert_awaited_once()
        rows = list(InsightPool.select().order_by(InsightPool.id.asc()))
        self.assertEqual([row.agent_name for row in rows], ["dream_weaver", "dream_weaver"])
        self.assertEqual(json.loads(rows[0].source_atoms), [str(entries[0].id), str(entries[2].id)])
        self.assertEqual(json.loads(rows[1].source_atoms), sorted([str(entries[1].id), str(entries[3].id)]))
        self.assertEqual(rows[1].confidence, 0.6)
        self.assertEqual(saved[1]["noise_sources"], [2, 4])

        with (
            patch.object(weaver, "_query_noise_entries", return_value=entries),
            patch.object(weaver, "_call_llm", new=AsyncMock(return_value=response)),
        ):
            repeated = await weaver.weave()

        self.assertEqual(repeated, [])
        self.assertEqual(InsightPool.select().where(InsightPool.agent_name == "dream_weaver").count(), 2)

    async def test_weave_rejects_sources_outside_prompt_subset(self) -> None:
        weaver = DreamWeaver(store=SimpleNamespace(), noise_retention_hours=72)
        entries = [self.make_noise(f"素材{i}") for i in range(25)]
        response = json.dumps(
            [
                {"insight": "不得引用未展示的第21条素材", "noise_sources": [1, 21]},
                {"insight": "展示范围内的两个来源有效", "noise_sources": [1, 20]},
            ],
            ensure_ascii=False,
        )

        with (
            patch.object(weaver, "_query_noise_entries", return_value=entries),
            patch.object(weaver, "_call_llm", new=AsyncMock(return_value=response)),
        ):
            saved = await weaver.weave()

        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["insight"], "展示范围内的两个来源有效")
        row = InsightPool.get(InsightPool.agent_name == "dream_weaver")
        self.assertEqual(json.loads(row.source_atoms), sorted([str(entries[0].id), str(entries[19].id)]))
        self.assertNotIn(str(entries[20].id), json.loads(row.source_atoms))

    def test_query_noise_entries_filters_by_retention_window_and_handles_database_errors(self) -> None:
        recent = self.make_noise("recent", hours_ago=1)
        self.make_noise("old", hours_ago=10)
        weaver = DreamWeaver(store=SimpleNamespace(), noise_retention_hours=2)

        self.assertEqual([entry.id for entry in weaver._query_noise_entries()], [recent.id])

        with patch.object(dream_weaver.NoisePool, "select", side_effect=RuntimeError("db down")):
            self.assertEqual(weaver._query_noise_entries(), [])


class EncodingPipelineOutboxTest(MemoryDatabaseFixtureMixin, unittest.IsolatedAsyncioTestCase):
    def make_pipeline(self) -> EncodingPipeline:
        pipeline = object.__new__(EncodingPipeline)
        pipeline.encoder = SimpleNamespace(
            buffers=[],
            encode_all_ready=AsyncMock(return_value={}),
            get_buffer=Mock(return_value=None),
        )
        pipeline.writer = SimpleNamespace(
            store=SimpleNamespace(get_atom=AsyncMock(return_value=None)),
            write_atom=AsyncMock(),
        )
        pipeline.trace_recorder = None
        pipeline._pending_writes = []
        pipeline._pending_loaded = False
        pipeline._outbox_enabled = True
        return pipeline

    def make_pending(self, pipeline: EncodingPipeline, atom_id: str = "outbox-atom"):
        atom, semantic_detail, episodic_detail = pipeline._build_atom(
            content="user-1 喜欢爵士乐",
            atom_type=AtomType.PREFERENCE,
            detail={
                "importance": 0.8,
                "entities": ["user-1"],
                SOURCE_USER_IDS_DETAIL_KEY: ["user-1"],
                "attr_name": "music",
                "attr_value": "jazz",
            },
            source_scene="group_chat",
            source_id="stream-1",
        )
        atom.atom_id = atom_id
        if semantic_detail is not None:
            semantic_detail.atom_id = atom_id
            atom.semantic_detail = semantic_detail
        identities = [PersonIdentity(platform="qq", user_id="user-1", nickname="Alice")]
        return encoding_pipeline._PendingAtomWrite(
            stream_id="stream-1",
            atom=atom,
            semantic_detail=semantic_detail,
            episodic_detail=episodic_detail,
            profile_identities=identities,
        )

    async def test_persisted_outbox_survives_pipeline_recreation_and_retries_same_atom_id(self) -> None:
        first = self.make_pipeline()
        pending = self.make_pending(first)
        first._persist_pending_write(pending)
        self.assertEqual(PendingAtomWrite.select().count(), 1)

        recovered = self.make_pipeline()
        stats = await recovered.run_cycle()

        self.assertEqual(stats["atoms_written"], 1)
        recovered.writer.write_atom.assert_awaited_once()
        kwargs = recovered.writer.write_atom.await_args.kwargs
        self.assertEqual(kwargs["atom"].atom_id, "outbox-atom")
        self.assertEqual(kwargs["semantic_detail"].attr_value, "jazz")
        self.assertEqual(recovered._pending_writes, [])
        self.assertEqual(PendingAtomWrite.select().count(), 0)

    async def test_failed_recovery_keeps_outbox_for_next_restart(self) -> None:
        first = self.make_pipeline()
        first._persist_pending_write(self.make_pending(first, atom_id="retry-outbox-atom"))

        failing = self.make_pipeline()
        failing.writer.write_atom = AsyncMock(side_effect=RuntimeError("db down"))
        stats = await failing.run_cycle()

        self.assertEqual(stats["atoms_written"], 0)
        self.assertEqual(stats["errors"], 1)
        self.assertEqual([item.atom.atom_id for item in failing._pending_writes], ["retry-outbox-atom"])
        self.assertTrue(PendingAtomWrite.select().where(PendingAtomWrite.atom_id == "retry-outbox-atom").exists())

        recovered = self.make_pipeline()
        retry_stats = await recovered.run_cycle()

        self.assertEqual(retry_stats["atoms_written"], 1)
        self.assertEqual(recovered.writer.write_atom.await_args.kwargs["atom"].atom_id, "retry-outbox-atom")
        self.assertEqual(PendingAtomWrite.select().count(), 0)


class EncodingPipelineTest(unittest.IsolatedAsyncioTestCase):
    def make_pipeline(self) -> EncodingPipeline:
        pipeline = object.__new__(EncodingPipeline)
        pipeline.encoder = SimpleNamespace(
            buffers=[],
            encode_all_ready=AsyncMock(return_value={}),
            get_buffer=Mock(return_value=None),
        )
        pipeline.writer = SimpleNamespace(store=SimpleNamespace(), write_atom=AsyncMock())
        pipeline.trace_recorder = None
        pipeline._pending_writes = []
        pipeline._pending_loaded = True
        pipeline._outbox_enabled = False
        return pipeline

    async def run_single_atom_cycle(
        self,
        *,
        atom_type: AtomType = AtomType.PREFERENCE,
        detail: dict | None = None,
        content: str = "user-1 喜欢爵士乐",
        stream_type: str = "group_chat",
    ) -> tuple[EncodingPipeline, dict]:
        pipeline = self.make_pipeline()
        pipeline.encoder.encode_all_ready = AsyncMock(
            return_value={
                "stream-1": [
                    (
                        content,
                        atom_type,
                        detail
                        or {
                            "importance": 0.8,
                            "entities": ["user-1"],
                            SOURCE_USER_IDS_DETAIL_KEY: ["user-1"],
                            "attr_name": "music",
                            "attr_value": "jazz",
                        },
                    )
                ]
            }
        )
        pipeline.encoder.get_buffer = Mock(return_value=SimpleNamespace(stream_type=stream_type))
        return pipeline, await pipeline.run_cycle()

    async def test_constructor_sets_singleton_and_ingest_delegates_to_encoder_with_datetime(self) -> None:
        fake_encoder = SimpleNamespace(set_stream_type=Mock(), ingest_message=AsyncMock())
        fake_writer = SimpleNamespace()

        with (
            patch.object(encoding_pipeline, "BatchEncoder", return_value=fake_encoder) as encoder_cls,
            patch.object(encoding_pipeline, "MemoryWriter", return_value=fake_writer) as writer_cls,
        ):
            pipeline = EncodingPipeline(store=SimpleNamespace(), trigger_count=3, trigger_seconds=9, op_logger=object())

        self.assertIs(get_encoding_pipeline(), pipeline)
        encoder_cls.assert_called_once()
        writer_cls.assert_called_once()

        await pipeline.ingest(
            stream_id="stream-1",
            user_id="user-1",
            speaker="Alice",
            content="hello",
            timestamp=123.0,
            stream_type="private_chat",
            message_id="msg-1",
            platform="qq",
            nickname="Alice",
            cardname="群名片",
        )

        fake_encoder.set_stream_type.assert_called_once_with("stream-1", "private_chat")
        kwargs = fake_encoder.ingest_message.await_args.kwargs
        self.assertEqual(kwargs["timestamp"], datetime.fromtimestamp(123.0))
        self.assertEqual(kwargs["message_id"], "msg-1")
        self.assertEqual(kwargs["platform"], "qq")
        self.assertEqual(kwargs["nickname"], "Alice")

    def test_set_trace_recorder_assigns_recorder(self) -> None:
        pipeline = self.make_pipeline()
        recorder = SimpleNamespace(record=Mock())

        pipeline.set_trace_recorder(recorder)

        self.assertIs(pipeline.trace_recorder, recorder)

    def test_build_atom_clamps_importance_and_creates_semantic_or_episodic_details(self) -> None:
        pipeline = self.make_pipeline()

        with patch.object(encoding_pipeline, "uuid4", side_effect=["atom-pref", "atom-episode"]):
            atom, semantic, episodic = pipeline._build_atom(
                content="user-1 喜欢爵士乐",
                atom_type=AtomType.PREFERENCE,
                detail={
                    "importance": "bad",
                    "entities": "not-list",
                    "attr_category": "interest",
                    "attr_name": "music",
                    "attr_value": "jazz",
                },
                source_scene="group_chat",
                source_id="stream-1",
            )
            episode, no_semantic, episode_detail = pipeline._build_atom(
                content="Alice 在深夜聊天",
                atom_type=AtomType.EPISODIC,
                detail={
                    "importance": 2,
                    "participants": ["Alice"],
                    "emotion_tags": ["calm"],
                    "sensory_tags": ["visual"],
                    "temporal_context": "深夜",
                },
                source_scene="private_chat",
            )

        self.assertEqual(atom.atom_id, "atom-pref")
        self.assertEqual(atom.importance, 0.5)
        self.assertEqual(atom.entities, [])
        self.assertEqual(atom.ttl_days, encoding_pipeline.DEFAULT_TTL[AtomType.PREFERENCE])
        self.assertEqual(atom.decay_type, encoding_pipeline.DEFAULT_DECAY[AtomType.PREFERENCE])
        self.assertEqual(semantic.attr_category, "interest")
        self.assertIsNone(episodic)
        self.assertEqual(episode.atom_id, "atom-episode")
        self.assertEqual(episode.importance, 1.0)
        self.assertIsNone(no_semantic)
        self.assertEqual(episode_detail.participants, ["Alice"])
        self.assertEqual(episode_detail.temporal_context, "深夜")

    async def test_run_cycle_returns_empty_stats_when_no_stream_is_ready_or_encoder_fails(self) -> None:
        pipeline = self.make_pipeline()

        self.assertEqual(
            await pipeline.run_cycle(),
            {"streams_processed": 0, "atoms_written": 0, "errors": 0, "streams": {}},
        )

        pipeline.encoder.encode_all_ready = AsyncMock(side_effect=RuntimeError("encoder down"))
        stats = await pipeline.run_cycle()

        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["atoms_written"], 0)

    async def test_run_cycle_writes_atoms_records_trace_and_runs_post_write_hooks(self) -> None:
        pipeline = self.make_pipeline()
        detail = {"importance": 0.8, "entities": ["user-1"], "attr_name": "music", "attr_value": "jazz"}
        pipeline.encoder.buffers = ["buffer"]
        pipeline.encoder.encode_all_ready = AsyncMock(
            return_value={"stream-1": [("user-1 喜欢爵士乐", AtomType.PREFERENCE, detail)]}
        )
        pipeline.encoder.get_buffer = Mock(return_value=SimpleNamespace(stream_type="group_chat"))
        pipeline.trace_recorder = SimpleNamespace(record=Mock())
        check_result = SimpleNamespace(recommendation="accept", atom=None, noise=False, conflicts=[])

        class FakeObjectivityChecker:
            def __init__(self, store):
                self.store = store

            async def check_before_write(self, atom, trace_recorder=None):
                return check_result

        fake_arbiter = SimpleNamespace(check_and_resolve=AsyncMock(return_value=1))
        fake_assoc_store = SimpleNamespace(build_from_batch=Mock(return_value=1))

        with (
            patch("src.memory.objectivity_check.ObjectivityChecker", FakeObjectivityChecker),
            patch("src.memory.conflict_arbitration.ConflictArbiter", return_value=fake_arbiter),
            patch("src.memory.atom_association.AtomAssociationStore", return_value=fake_assoc_store),
            patch.object(encoding_pipeline, "uuid4", return_value="atom-written"),
        ):
            stats = await pipeline.run_cycle()

        self.assertEqual(stats, {"streams_processed": 1, "atoms_written": 1, "errors": 0, "streams": {"stream-1": 1}})
        pipeline.writer.write_atom.assert_awaited_once()
        written_kwargs = pipeline.writer.write_atom.await_args.kwargs
        self.assertEqual(written_kwargs["atom"].atom_id, "atom-written")
        self.assertEqual(written_kwargs["semantic_detail"].attr_value, "jazz")
        self.assertEqual(pipeline.trace_recorder.record.call_count, 2)
        fake_arbiter.check_and_resolve.assert_awaited_once()
        fake_assoc_store.build_from_batch.assert_called_once()

    async def test_run_cycle_uses_adjusted_atom_records_conflicts_and_updates_profiles(self) -> None:
        fake_builder = SimpleNamespace(update_profile_from_atom=Mock())
        checkers = []
        conflicts = [SimpleNamespace(new_atom_id=None)]

        class AcceptingChecker:
            def __init__(self, store):
                self.store = store
                self.record_conflict = AsyncMock(side_effect=RuntimeError("conflict db down"))
                checkers.append(self)

            async def check_before_write(self, atom, trace_recorder=None):
                atom.confidence = 0.33
                return SimpleNamespace(recommendation="accept", atom=atom, noise=False, conflicts=conflicts)

        with (
            patch("src.memory.objectivity_check.ObjectivityChecker", AcceptingChecker),
            patch("src.memory.user_profile.ProfileStore", return_value=SimpleNamespace()),
            patch("src.memory.user_profile.ProfileBuilder", return_value=fake_builder),
            patch(
                "src.memory.conflict_arbitration.ConflictArbiter",
                return_value=SimpleNamespace(check_and_resolve=AsyncMock(return_value=0)),
            ),
            patch(
                "src.memory.atom_association.AtomAssociationStore",
                return_value=SimpleNamespace(build_from_batch=Mock(return_value=0)),
            ),
        ):
            pipeline, stats = await self.run_single_atom_cycle()

        self.assertEqual(stats["atoms_written"], 1)
        written_atom = pipeline.writer.write_atom.await_args.kwargs["atom"]
        self.assertEqual(written_atom.confidence, 0.33)
        self.assertEqual(conflicts[0].new_atom_id, written_atom.atom_id)
        checkers[0].record_conflict.assert_awaited_once_with(conflicts[0])
        fake_builder.update_profile_from_atom.assert_called_once_with(
            PersonIdentity(platform="legacy", user_id="user-1"), written_atom
        )

    async def test_run_cycle_import_error_in_objectivity_check_still_writes_atom(self) -> None:
        real_import = builtins.__import__

        def import_without_objectivity(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "src.memory.objectivity_check":
                raise ImportError("objectivity disabled")
            return real_import(name, globals, locals, fromlist, level)

        with (
            patch("builtins.__import__", side_effect=import_without_objectivity),
            patch(
                "src.memory.conflict_arbitration.ConflictArbiter",
                return_value=SimpleNamespace(check_and_resolve=AsyncMock(return_value=0)),
            ),
            patch(
                "src.memory.atom_association.AtomAssociationStore",
                return_value=SimpleNamespace(build_from_batch=Mock(return_value=0)),
            ),
        ):
            pipeline, stats = await self.run_single_atom_cycle()

        self.assertEqual(stats["atoms_written"], 1)
        pipeline.writer.write_atom.assert_awaited_once()

    async def test_run_cycle_skips_atom_when_objectivity_checker_raises(self) -> None:
        class FailingChecker:
            def __init__(self, store):
                self.store = store

            async def check_before_write(self, atom, trace_recorder=None):
                raise RuntimeError("checker down")

        with patch("src.memory.objectivity_check.ObjectivityChecker", FailingChecker):
            pipeline, stats = await self.run_single_atom_cycle()

        self.assertEqual(stats, {"streams_processed": 1, "atoms_written": 0, "errors": 0, "streams": {"stream-1": 0}})
        pipeline.writer.write_atom.assert_not_awaited()

    async def test_run_cycle_counts_writer_failure_without_aborting_stream(self) -> None:
        class AcceptingChecker:
            def __init__(self, store):
                self.store = store

            async def check_before_write(self, atom, trace_recorder=None):
                return SimpleNamespace(recommendation="accept", atom=None, noise=False, conflicts=[])

        with patch("src.memory.objectivity_check.ObjectivityChecker", AcceptingChecker):
            pipeline = self.make_pipeline()
            pipeline.writer.write_atom = AsyncMock(side_effect=RuntimeError("write failed"))
            pipeline.encoder.encode_all_ready = AsyncMock(
                return_value={
                    "stream-1": [
                        (
                            "user-1 喜欢爵士乐",
                            AtomType.PREFERENCE,
                            {
                                "entities": ["user-1"],
                                SOURCE_USER_IDS_DETAIL_KEY: ["user-1"],
                                "attr_name": "music",
                            },
                        )
                    ]
                }
            )
            stats = await pipeline.run_cycle()

        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["atoms_written"], 0)
        self.assertEqual(stats["streams"], {"stream-1": 0})
        self.assertEqual(len(pipeline._pending_writes), 1)
        failed_atom_id = pipeline._pending_writes[0].atom.atom_id

        pipeline.writer.write_atom = AsyncMock(return_value=failed_atom_id)
        pipeline.encoder.encode_all_ready = AsyncMock(return_value={})
        retry_stats = await pipeline.run_cycle()

        self.assertEqual(retry_stats["atoms_written"], 1)
        self.assertEqual(retry_stats["streams"], {"stream-1": 1})
        self.assertEqual(pipeline._pending_writes, [])
        pipeline.writer.write_atom.assert_awaited_once()
        self.assertEqual(pipeline.writer.write_atom.await_args.kwargs["atom"].atom_id, failed_atom_id)

    async def test_run_cycle_updates_episodic_profiles_with_sensory_detail(self) -> None:
        fake_builder = SimpleNamespace(update_profile_from_atom=Mock())

        class AcceptingChecker:
            def __init__(self, store):
                self.store = store

            async def check_before_write(self, atom, trace_recorder=None):
                return SimpleNamespace(recommendation="accept", atom=None, noise=False, conflicts=[])

        detail = {
            "importance": 0.7,
            "entities": ["user-1"],
            SOURCE_USER_IDS_DETAIL_KEY: ["user-1"],
            "participants": ["user-1"],
            "emotion_tags": ["calm"],
            "sensory_tags": ["visual"],
            "temporal_context": "深夜",
        }

        with (
            patch("src.memory.objectivity_check.ObjectivityChecker", AcceptingChecker),
            patch("src.memory.user_profile.ProfileStore", return_value=SimpleNamespace()),
            patch("src.memory.user_profile.ProfileBuilder", return_value=fake_builder),
            patch(
                "src.memory.conflict_arbitration.ConflictArbiter",
                return_value=SimpleNamespace(check_and_resolve=AsyncMock(return_value=0)),
            ),
            patch(
                "src.memory.atom_association.AtomAssociationStore",
                return_value=SimpleNamespace(build_from_batch=Mock(return_value=0)),
            ),
        ):
            pipeline, stats = await self.run_single_atom_cycle(
                atom_type=AtomType.EPISODIC,
                detail=detail,
                content="user-1 在深夜说自己很平静",
            )

        self.assertEqual(stats["atoms_written"], 1)
        written_kwargs = pipeline.writer.write_atom.await_args.kwargs
        self.assertEqual(written_kwargs["episodic_detail"].sensory_tags, ["visual"])
        fake_builder.update_profile_from_atom.assert_called_once_with(
            PersonIdentity(platform="legacy", user_id="user-1"), written_kwargs["atom"]
        )

    async def test_run_cycle_ignores_profile_update_failures_for_semantic_and_episodic_atoms(self) -> None:
        class AcceptingChecker:
            def __init__(self, store):
                self.store = store

            async def check_before_write(self, atom, trace_recorder=None):
                return SimpleNamespace(recommendation="accept", atom=None, noise=False, conflicts=[])

        detail_preference = {
            "entities": ["user-1"],
            SOURCE_USER_IDS_DETAIL_KEY: ["user-1"],
            "attr_name": "music",
        }
        detail_episode = {
            "entities": ["user-1"],
            SOURCE_USER_IDS_DETAIL_KEY: ["user-1"],
            "emotion_tags": ["curious"],
        }
        pipeline = self.make_pipeline()
        pipeline.encoder.encode_all_ready = AsyncMock(
            return_value={
                "stream-1": [
                    ("user-1 喜欢爵士乐", AtomType.PREFERENCE, detail_preference),
                    ("user-1 有点好奇", AtomType.EPISODIC, detail_episode),
                ]
            }
        )

        with (
            patch("src.memory.objectivity_check.ObjectivityChecker", AcceptingChecker),
            patch("src.memory.user_profile.ProfileStore", side_effect=RuntimeError("profile unavailable")),
            patch(
                "src.memory.conflict_arbitration.ConflictArbiter",
                return_value=SimpleNamespace(check_and_resolve=AsyncMock(return_value=0)),
            ),
            patch(
                "src.memory.atom_association.AtomAssociationStore",
                return_value=SimpleNamespace(build_from_batch=Mock(return_value=0)),
            ),
        ):
            stats = await pipeline.run_cycle()

        self.assertEqual(stats["atoms_written"], 2)
        self.assertEqual(pipeline.writer.write_atom.await_count, 2)

    async def test_run_cycle_handles_post_write_import_and_runtime_failures(self) -> None:
        class AcceptingChecker:
            def __init__(self, store):
                self.store = store

            async def check_before_write(self, atom, trace_recorder=None):
                return SimpleNamespace(recommendation="accept", atom=None, noise=False, conflicts=[])

        real_import = builtins.__import__

        def fail_conflict_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "src.memory.conflict_arbitration":
                raise ImportError("conflict unavailable")
            return real_import(name, globals, locals, fromlist, level)

        def fail_association_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "src.memory.atom_association":
                raise ImportError("association unavailable")
            return real_import(name, globals, locals, fromlist, level)

        with (
            patch("src.memory.objectivity_check.ObjectivityChecker", AcceptingChecker),
            patch("builtins.__import__", side_effect=fail_conflict_import),
            patch(
                "src.memory.atom_association.AtomAssociationStore",
                return_value=SimpleNamespace(build_from_batch=Mock(return_value=0)),
            ),
        ):
            _, conflict_import_stats = await self.run_single_atom_cycle()

        with (
            patch("src.memory.objectivity_check.ObjectivityChecker", AcceptingChecker),
            patch("src.memory.conflict_arbitration.ConflictArbiter", side_effect=RuntimeError("arbiter down")),
            patch(
                "src.memory.atom_association.AtomAssociationStore",
                return_value=SimpleNamespace(build_from_batch=Mock(return_value=0)),
            ),
        ):
            _, conflict_runtime_stats = await self.run_single_atom_cycle()

        with (
            patch("src.memory.objectivity_check.ObjectivityChecker", AcceptingChecker),
            patch(
                "src.memory.conflict_arbitration.ConflictArbiter",
                return_value=SimpleNamespace(check_and_resolve=AsyncMock(return_value=0)),
            ),
            patch("builtins.__import__", side_effect=fail_association_import),
        ):
            _, association_import_stats = await self.run_single_atom_cycle()

        with (
            patch("src.memory.objectivity_check.ObjectivityChecker", AcceptingChecker),
            patch(
                "src.memory.conflict_arbitration.ConflictArbiter",
                return_value=SimpleNamespace(check_and_resolve=AsyncMock(return_value=0)),
            ),
            patch("src.memory.atom_association.AtomAssociationStore", side_effect=RuntimeError("association down")),
        ):
            _, association_runtime_stats = await self.run_single_atom_cycle()

        self.assertEqual(conflict_import_stats["atoms_written"], 1)
        self.assertEqual(conflict_runtime_stats["atoms_written"], 1)
        self.assertEqual(association_import_stats["atoms_written"], 1)
        self.assertEqual(association_runtime_stats["atoms_written"], 1)

    async def test_run_cycle_skips_objectivity_rejections_and_limits_profile_targets_to_source_users(self) -> None:
        pipeline = self.make_pipeline()
        detail = {
            "importance": 0.8,
            "entities": ["user-1", "user-evil"],
            SOURCE_USER_IDS_DETAIL_KEY: ["user-1"],
            "attr_name": "music",
        }
        pipeline.encoder.encode_all_ready = AsyncMock(
            return_value={"stream-1": [("user-1 喜欢爵士乐", AtomType.FACTUAL, detail)]}
        )
        pipeline.encoder.get_buffer = Mock(return_value=SimpleNamespace(stream_type="group_chat"))

        class RejectingChecker:
            def __init__(self, store):
                self.store = store

            async def check_before_write(self, atom, trace_recorder=None):
                return SimpleNamespace(recommendation="reject", atom=atom, noise=True, conflicts=[])

        with patch("src.memory.objectivity_check.ObjectivityChecker", RejectingChecker):
            stats = await pipeline.run_cycle()

        self.assertEqual(stats["atoms_written"], 0)
        pipeline.writer.write_atom.assert_not_awaited()

        atom, _, _ = pipeline._build_atom("content", AtomType.FACTUAL, detail, "group_chat", "stream-1")
        self.assertEqual(EncodingPipeline._profile_target_entities(atom, detail), ["user-1"])
        self.assertEqual(EncodingPipeline._profile_target_entities(atom, {"_source_user_ids": "bad"}), [])

    async def test_encoding_task_delegates_to_pipeline_and_swallows_failures(self) -> None:
        pipeline = SimpleNamespace(run_cycle=AsyncMock(return_value={"atoms_written": 2, "streams_processed": 1}))
        task = EncodingTask(pipeline, interval=1)

        await task.run()
        pipeline.run_cycle.assert_awaited_once()

        failing_pipeline = SimpleNamespace(run_cycle=AsyncMock(side_effect=RuntimeError("boom")))
        await EncodingTask(failing_pipeline, interval=1).run()
        failing_pipeline.run_cycle.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
