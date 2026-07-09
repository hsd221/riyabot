import json
import math
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.memory import atom as memory_atom
from src.memory.bm25_retrieval import BM25Retriever, reciprocal_rank_fusion, tokenize
from src.memory.forgetting import ForgettingManager, _safe_timestamp
from src.memory.layer3_retrieval import RetrievedAtom
from src.memory.trace_chain import TraceChainRecorder, TraceStep
from src.memory.schema import MemoryAtom as MemoryAtomModel
from src.memory.schema import RawMessageArchive, configure_memory_database, initialize_database, memory_db


def make_atom(**overrides) -> memory_atom.MemoryAtom:
    data = {
        "atom_id": "atom-1",
        "atom_type": memory_atom.AtomType.FACTUAL,
        "content": "小明喜欢爵士乐",
        "importance": 0.8,
        "confidence": 0.5,
        "weight": 0.4,
        "created_at": 0.0,
        "last_accessed_at": 0.0,
        "ttl_days": 10.0,
        "decay_type": memory_atom.DecayType.EXPONENTIAL,
        "reinforcement_count": 0,
    }
    data.update(overrides)
    return memory_atom.MemoryAtom(**data)


def retrieved(atom_id: str, *, score: float = 0.0, weight: float = 0.5) -> RetrievedAtom:
    return RetrievedAtom(
        atom_id=atom_id,
        content=f"content-{atom_id}",
        atom_type="factual",
        weight=weight,
        similarity_score=score,
        final_score=score,
    )


class MemoryAtomCoreTest(unittest.TestCase):
    def test_time_conversion_days_since_and_decay_modes_cover_boundaries(self) -> None:
        with patch.object(memory_atom, "_now", return_value=123.0):
            self.assertEqual(memory_atom.to_timestamp(None), 123.0)
            self.assertEqual(memory_atom.to_timestamp("not-a-date"), 123.0)

        dt = datetime.fromtimestamp(456.0)
        self.assertEqual(memory_atom.to_timestamp(456), 456.0)
        self.assertEqual(memory_atom.to_timestamp(dt), 456.0)
        self.assertEqual(memory_atom.to_timestamp(datetime.fromtimestamp(789.0).isoformat()), 789.0)
        self.assertEqual(memory_atom.to_datetime(456.0), dt)
        self.assertEqual(memory_atom.days_since(10.0, current_time=0.0), 0.0)
        self.assertEqual(memory_atom.days_since(0.0, current_time=2 * 86400.0), 2.0)

        linear = make_atom(decay_type=memory_atom.DecayType.LINEAR)
        step = make_atom(decay_type=memory_atom.DecayType.STEP)
        exponential = make_atom(decay_type=memory_atom.DecayType.EXPONENTIAL)

        self.assertEqual(memory_atom.compute_decay_factor(make_atom(ttl_days=0.0), current_time=0.0), 0.0)
        self.assertEqual(memory_atom.compute_decay_factor(linear, current_time=5 * 86400.0), 0.75)
        self.assertAlmostEqual(
            memory_atom.compute_decay_factor(exponential, current_time=5 * 86400.0),
            math.exp(-0.5),
        )
        self.assertEqual(memory_atom.compute_decay_factor(step, current_time=5 * 86400.0), 1.0)
        self.assertEqual(memory_atom.compute_decay_factor(step, current_time=15 * 86400.0), 0.1)
        self.assertEqual(memory_atom.compute_decay_factor(step, current_time=20 * 86400.0), 0.0)

    def test_weight_update_reinforcement_consolidation_and_fade_levels(self) -> None:
        atom = make_atom(decay_type=memory_atom.DecayType.LINEAR, reinforcement_count=20)

        self.assertEqual(memory_atom.compute_weight(atom, current_time=0.0), 0.8)
        updated = memory_atom.update_weight(atom, current_time=5.0, consolidation_factor=1.25)
        self.assertIsNot(updated, atom)
        self.assertEqual(atom.last_accessed_at, 0.0)
        self.assertEqual(updated.last_accessed_at, 5.0)
        self.assertGreater(updated.weight, 0.0)

        with patch.object(memory_atom, "_now", return_value=10.0):
            not_used = memory_atom.reinforce_memory(make_atom(weight=0.03), level="none")
            normal = memory_atom.reinforce_memory(make_atom(), level="normal")
            strong = memory_atom.reinforce_memory(make_atom(), level="strong")
            consolidated = memory_atom.apply_dream_consolidation(make_atom(), boost=0.3)

        self.assertEqual(not_used.weight, 0.0)
        self.assertEqual(normal.reinforcement_count, 1)
        self.assertEqual(strong.reinforcement_count, 2)
        self.assertIsNotNone(normal.last_reinforced_at)
        self.assertGreaterEqual(consolidated.weight, make_atom().weight)

        with self.assertRaises(ValueError):
            memory_atom.reinforce_memory(make_atom(), level="invalid")
        with self.assertRaises(ValueError):
            memory_atom.apply_dream_consolidation(make_atom(), boost=0.31)

        self.assertEqual(memory_atom.get_fade_level(0.8), "完整")
        self.assertEqual(memory_atom.get_fade_level(0.5), "摘要")
        self.assertEqual(memory_atom.get_fade_level(0.2), "模糊")
        self.assertEqual(memory_atom.get_fade_level(0.1), "残影")


class BM25RetrievalTest(unittest.IsolatedAsyncioTestCase):
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

    def test_tokenize_and_reciprocal_rank_fusion_are_cjk_aware_and_stable(self) -> None:
        self.assertEqual(tokenize("小明喜欢 Jazz music"), ["小明", "明喜", "喜欢", "jazz", "music"])
        self.assertEqual(tokenize("A  B"), ["a", "b"])

        atom_a = retrieved("a")
        atom_b = retrieved("b")
        atom_c = retrieved("c")
        fused = reciprocal_rank_fusion([[atom_a, atom_b], [atom_b, atom_c]], k=10)

        self.assertEqual([atom.atom_id for atom in fused], ["b", "a", "c"])
        self.assertGreater(fused[0].final_score, fused[1].final_score)
        self.assertEqual(reciprocal_rank_fusion([]), [])

    async def test_bm25_search_builds_index_filters_partition_and_invalidates_cache(self) -> None:
        MemoryAtomModel.create(
            atom_id="jazz",
            atom_type="preference",
            content="小明喜欢爵士乐",
            entities='["小明", "爵士乐"]',
            importance=0.9,
            confidence=0.8,
            weight=0.75,
            source_scene="group_chat",
            source_id="stream-1",
            status="active",
        )
        MemoryAtomModel.create(
            atom_id="rock",
            atom_type="preference",
            content="小红讨厌摇滚乐",
            entities='["小红", "摇滚乐"]',
            importance=0.5,
            confidence=0.6,
            weight=0.2,
            source_scene="private_chat",
            source_id="stream-2",
            status="active",
        )
        MemoryAtomModel.create(
            atom_id="archived",
            atom_type="factual",
            content="小明曾经喜欢爵士乐",
            weight=0.9,
            source_scene="group_chat",
            status="archived",
        )

        retriever = BM25Retriever(store=SimpleNamespace())
        results = await retriever.search("爵士乐", top_k=5)
        group_results = await retriever.search("爵士乐", top_k=5, partition="group_chat")
        private_results = await retriever.search("爵士乐", top_k=5, partition="private_chat")

        self.assertEqual([atom.atom_id for atom in results], ["jazz"])
        self.assertEqual(results[0].fade_level, "完整")
        self.assertEqual([atom.atom_id for atom in group_results], ["jazz"])
        self.assertEqual(private_results, [])
        self.assertTrue(retriever._index_built)

        retriever.invalidate_cache()
        self.assertFalse(retriever._index_built)
        self.assertEqual(retriever._doc_count, 0)
        self.assertEqual(retriever._doc_lengths, {})

    async def test_hybrid_search_handles_empty_query_empty_sides_and_weighted_rrf(self) -> None:
        retriever = BM25Retriever(store=SimpleNamespace())
        vector_atom = retrieved("vector")
        bm25_atom = retrieved("bm25")

        self.assertEqual(await retriever.hybrid_search("", [vector_atom], top_k=1), [vector_atom])

        with patch.object(retriever, "search", new=AsyncMock(return_value=[])):
            self.assertEqual(await retriever.hybrid_search("query", [vector_atom], top_k=1), [vector_atom])

        with patch.object(retriever, "search", new=AsyncMock(return_value=[bm25_atom])):
            self.assertEqual(await retriever.hybrid_search("query", [], top_k=1), [bm25_atom])

        with patch.object(retriever, "search", new=AsyncMock(return_value=[bm25_atom])):
            fused = await retriever.hybrid_search(
                "query",
                [vector_atom],
                top_k=2,
                bm25_weight=0.3,
                vector_weight=0.7,
            )

        self.assertEqual([atom.atom_id for atom in fused], ["vector", "bm25"])
        self.assertGreater(fused[0].final_score, fused[1].final_score)


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


def create_memory_atom(atom_id: str, *, weight: float = 0.5, status: str = "active", **overrides) -> None:
    data = {
        "atom_id": atom_id,
        "atom_type": "preference",
        "content": f"{atom_id} 记忆内容",
        "entities": '["小明"]',
        "importance": 0.8,
        "confidence": 0.7,
        "weight": weight,
        "ttl_days": 7,
        "decay_type": "exponential",
        "reinforcement_count": 2,
        "source_scene": "group_chat",
        "source_id": "stream-1",
        "privacy_level": "context_sensitive",
        "status": status,
        "embedding_id": f"embedding-{atom_id}",
    }
    data.update(overrides)
    MemoryAtomModel.create(**data)


class ForgettingManagerTest(MemoryDatabaseFixtureMixin, unittest.IsolatedAsyncioTestCase):
    def test_safe_timestamp_accepts_datetime_numeric_none_and_default(self) -> None:
        moment = datetime.fromtimestamp(123.0)

        self.assertEqual(_safe_timestamp(moment), 123.0)
        self.assertEqual(_safe_timestamp(456), 456.0)
        self.assertEqual(_safe_timestamp(None, default=789.0), 789.0)
        self.assertGreater(_safe_timestamp(None), 0.0)

    async def test_archive_faded_serializes_atom_metadata_and_deletes_qdrant_vector(self) -> None:
        created_at = datetime.fromtimestamp(100.0)
        create_memory_atom("low-weight", weight=0.05, created_at=created_at, content="小明喜欢爵士乐")
        create_memory_atom("healthy", weight=0.5)
        store = SimpleNamespace(qdrant=SimpleNamespace(delete_atom_vector=AsyncMock(return_value=True)))
        manager = ForgettingManager(store, archive_threshold=0.1)  # type: ignore[arg-type]

        archived = await manager._archive_faded()

        archive = RawMessageArchive.get(RawMessageArchive.message_id == "low-weight")
        archived_atom = MemoryAtomModel.get_by_id("low-weight")
        healthy_atom = MemoryAtomModel.get_by_id("healthy")
        archive_payload = json.loads(archive.content)

        self.assertEqual(archived, 1)
        self.assertEqual(archived_atom.status, "archived")
        self.assertEqual(healthy_atom.status, "active")
        self.assertEqual(archive.stream_id, "memory_archive_group_chat")
        self.assertEqual(archive.chat_type, "memory_archive_preference")
        self.assertEqual(archive.timestamp, 100.0)
        self.assertEqual(archive_payload["content"], "小明喜欢爵士乐")
        self.assertEqual(archive_payload["metadata"]["atom_id"], "low-weight")
        self.assertEqual(archive_payload["metadata"]["embedding_id"], "embedding-low-weight")
        store.qdrant.delete_atom_vector.assert_awaited_once_with("low-weight")

    async def test_purge_expired_delegates_to_store_and_counts_successful_deletes(self) -> None:
        create_memory_atom("delete-ok", weight=0.005)
        create_memory_atom("delete-fail", weight=0.006)
        create_memory_atom("keep", weight=0.5)
        store = SimpleNamespace(delete_atom=AsyncMock(side_effect=[True, False]))
        manager = ForgettingManager(store, delete_threshold=0.01)  # type: ignore[arg-type]

        deleted = await manager._purge_expired()

        self.assertEqual(deleted, 1)
        self.assertEqual([call.args[0] for call in store.delete_atom.await_args_list], ["delete-ok", "delete-fail"])

    async def test_force_forget_archives_existing_atoms_before_store_delete(self) -> None:
        create_memory_atom("forget-me", weight=0.9, content="需要强制遗忘的内容")
        store = SimpleNamespace(delete_atom=AsyncMock(return_value=True))
        manager = ForgettingManager(store)  # type: ignore[arg-type]

        forgotten = await manager.force_forget(["missing", "forget-me"])

        self.assertEqual(forgotten, 1)
        self.assertTrue(RawMessageArchive.select().where(RawMessageArchive.message_id == "forget-me").exists())
        store.delete_atom.assert_awaited_once_with("forget-me")

    async def test_get_decay_stats_counts_active_atoms_by_fade_level_and_archive_need(self) -> None:
        create_memory_atom("full", weight=0.8)
        create_memory_atom("summary", weight=0.5)
        create_memory_atom("fuzzy", weight=0.2)
        create_memory_atom("shadow", weight=0.05)
        create_memory_atom("archived", weight=0.01, status="archived")
        manager = ForgettingManager(SimpleNamespace(), archive_threshold=0.1, delete_threshold=0.01)  # type: ignore[arg-type]

        stats = await manager.get_decay_stats()

        self.assertEqual(stats["total_active_atoms"], 4)
        self.assertEqual(stats["avg_weight"], 0.3875)
        self.assertEqual(stats["max_weight"], 0.8)
        self.assertEqual(stats["min_weight"], 0.05)
        self.assertEqual(stats["fade_level_counts"], {"完整": 1, "摘要": 1, "模糊": 1, "残影": 1})
        self.assertEqual(stats["needs_archive"], 1)


class TraceChainRecorderTest(MemoryDatabaseFixtureMixin, unittest.TestCase):
    def test_record_and_get_lineage_return_ordered_trace_steps(self) -> None:
        recorder = TraceChainRecorder()

        self.assertTrue(recorder.record(TraceStep("atom-1", 2, "ObjectivityChecker", "verify", output_summary="ok")))
        self.assertTrue(recorder.record(TraceStep("atom-1", 1, "Layer2Encoder", "extract", input_source="msg-1")))

        lineage = recorder.get_lineage("atom-1")

        self.assertEqual([step.step_order for step in lineage], [1, 2])
        self.assertEqual(lineage[0].agent_name, "Layer2Encoder")
        self.assertEqual(lineage[0].input_source, "msg-1")
        self.assertEqual(lineage[1].operation, "verify")
        self.assertEqual(recorder.get_chain("atom-1"), lineage)

    def test_batch_record_empty_records_and_distinct_atom_query(self) -> None:
        recorder = TraceChainRecorder()

        self.assertEqual(recorder.batch_record([]), 0)
        count = recorder.batch_record(
            [
                TraceStep("atom-1", 1, "Layer2Encoder", "extract"),
                TraceStep("atom-1", 2, "MemoryWriter", "write"),
                TraceStep("atom-2", 1, "Layer2Encoder", "extract"),
            ]
        )

        self.assertEqual(count, 3)
        self.assertEqual(len(recorder.get_lineage("atom-1")), 2)
        self.assertEqual(set(recorder.get_atoms_with_traces(limit=10)), {"atom-1", "atom-2"})

    def test_recording_failures_return_false_or_partial_count(self) -> None:
        recorder = TraceChainRecorder()

        with patch("src.memory.trace_chain.MemoryTraceChain.create", side_effect=RuntimeError("boom")):
            self.assertFalse(recorder.record(TraceStep("atom-1", 1, "Agent", "op")))
            self.assertEqual(
                recorder.batch_record(
                    [
                        TraceStep("atom-1", 1, "Agent", "op"),
                        TraceStep("atom-1", 2, "Agent", "op"),
                    ]
                ),
                0,
            )

        with patch("src.memory.trace_chain.MemoryTraceChain.select", side_effect=RuntimeError("boom")):
            self.assertEqual(recorder.get_lineage("atom-1"), [])
            self.assertEqual(recorder.get_atoms_with_traces(), [])


if __name__ == "__main__":
    unittest.main()
