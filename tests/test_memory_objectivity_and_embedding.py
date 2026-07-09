import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.memory.atom import AtomType, MemoryAtom
from src.memory.embedding_utils import generate_embedding, generate_query_embedding
from src.memory.objectivity_check import (
    ConflictInfo,
    ObjectivityChecker,
    _char_ngrams,
    _extract_numeric_facts,
    _remove_negations,
    check_contradiction,
    compute_content_similarity,
    extract_entity_set,
)
from src.memory.schema import (
    ConflictObservation,
    NoisePool,
    configure_memory_database,
    initialize_database,
    memory_db,
)


def make_atom(
    atom_id: str = "atom-new",
    content: str = "小明喜欢爵士乐",
    *,
    entities: list[str] | None = None,
    importance: float = 0.8,
    confidence: float = 0.8,
    source_scene: str = "group_chat",
    source_id: str | None = "stream-1",
) -> MemoryAtom:
    return MemoryAtom(
        atom_id=atom_id,
        atom_type=AtomType.FACTUAL,
        content=content,
        entities=["小明"] if entities is None else entities,
        importance=importance,
        confidence=confidence,
        weight=0.5,
        created_at=0.0,
        last_accessed_at=0.0,
        ttl_days=180,
        source_scene=source_scene,
        source_id=source_id,
    )


class FakeStore:
    def __init__(self, by_type: list[dict] | None = None, recent: list[dict] | None = None) -> None:
        self.by_type = by_type or []
        self.recent = recent or []
        self.calls: list[dict] = []

    async def list_atoms(self, **kwargs):
        self.calls.append(kwargs)
        if "atom_type" in kwargs:
            return self.by_type
        return self.recent


class MemoryObjectivityDatabaseFixtureMixin:
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


class EmbeddingUtilsTest(unittest.IsolatedAsyncioTestCase):
    async def test_generate_embedding_skips_blank_delegates_to_lazy_import_and_handles_errors(self) -> None:
        fake_module = types.ModuleType("src.chat.utils.utils")
        fake_module.get_embedding = AsyncMock(return_value=[0.1, 0.2])

        with patch.dict(sys.modules, {"src.chat.utils.utils": fake_module}):
            self.assertIsNone(await generate_embedding("   "))
            self.assertEqual(await generate_embedding("hello"), [0.1, 0.2])
            self.assertEqual(await generate_query_embedding("query"), [0.1, 0.2])

        fake_error_module = types.ModuleType("src.chat.utils.utils")
        fake_error_module.get_embedding = AsyncMock(side_effect=RuntimeError("embedding unavailable"))
        with patch.dict(sys.modules, {"src.chat.utils.utils": fake_error_module}):
            self.assertIsNone(await generate_embedding("hello"))


class ObjectivityTextHelperTest(unittest.TestCase):
    def test_text_similarity_entity_extraction_numeric_facts_and_contradictions(self) -> None:
        self.assertEqual(_char_ngrams("abc", 2), {"ab", "bc"})
        self.assertEqual(_char_ngrams("a", 2), {"a"})
        self.assertEqual(_char_ngrams("abc", 0), set())
        self.assertEqual(compute_content_similarity("", ""), 1.0)
        self.assertEqual(compute_content_similarity("", "abc"), 0.0)
        self.assertEqual(compute_content_similarity("小明喜欢猫", "小明喜欢猫"), 1.0)

        entities = extract_entity_set('Bob 说 "猫猫" @Alice 喜欢 OpenAI/GPT-4', known_entities=["小明"])
        self.assertGreaterEqual(entities, {"小明", "猫猫", "Alice", "Bob", "OpenAI/GPT-4"})
        self.assertEqual(_extract_numeric_facts("小明 25岁 身高180cm"), [(25.0, "岁"), (180.0, "cm")])
        self.assertEqual(_remove_negations("小明不喜欢猫"), "小明喜欢猫")
        self.assertTrue(check_contradiction("小明25岁", "小明26岁"))
        self.assertTrue(check_contradiction("小明喜欢爵士乐", "小明不喜欢爵士乐"))
        self.assertFalse(check_contradiction("小明喜欢爵士乐", "小红喜欢摇滚乐"))


class ObjectivityCheckerTest(MemoryObjectivityDatabaseFixtureMixin, unittest.IsolatedAsyncioTestCase):
    async def test_noise_self_consistency_confidence_and_recommendation_boundaries(self) -> None:
        checker = ObjectivityChecker(FakeStore())  # type: ignore[arg-type]

        self.assertTrue(await checker.filter_noise(make_atom(content="  ")))
        self.assertTrue(await checker.filter_noise(make_atom(content="!!!")))
        self.assertTrue(await checker.filter_noise(make_atom(content="短句", entities=[])))
        self.assertTrue(await checker.filter_noise(make_atom(content="小明有一段低重要性记忆", importance=0.01)))
        self.assertFalse(await checker.filter_noise(make_atom(content="小明说自己喜欢爵士乐")))

        good_score = await checker.check_self_consistency(
            make_atom(content='小明说自己25岁并喜欢"爵士乐"', entities=["小明", "爵士乐"])
        )
        weak_score = await checker.check_self_consistency(make_atom(content="12345", entities=[]))
        light_conflict = ConflictInfo("old", "旧", "新", "duplicate", 0.9)
        heavy_conflicts = [ConflictInfo(str(i), "旧", "新", "contradiction", 0.7) for i in range(3)]

        self.assertGreaterEqual(good_score, 0.9)
        self.assertLess(weak_score, 0.5)
        self.assertEqual(checker.adjust_confidence(make_atom(confidence=0.8), 1.0, []).confidence, 0.8)
        self.assertAlmostEqual(
            checker.adjust_confidence(make_atom(confidence=0.8), 0.5, [light_conflict]).confidence,
            0.576,
        )
        self.assertAlmostEqual(
            checker.adjust_confidence(make_atom(confidence=0.8), 0.2, heavy_conflicts).confidence,
            0.28,
        )
        self.assertEqual(checker._decide_recommendation(make_atom(), 0.7, [], False), "write")
        self.assertEqual(checker._decide_recommendation(make_atom(), 0.1, [], False), "reject")
        self.assertEqual(checker._decide_recommendation(make_atom(), 0.7, heavy_conflicts, False), "review")
        self.assertEqual(
            checker._decide_recommendation(make_atom(confidence=0.2), 0.7, [light_conflict], False),
            "reject",
        )

    async def test_detect_conflicts_deduplicates_scoped_candidates_and_classifies_conflict_types(self) -> None:
        store = FakeStore(
            by_type=[
                {
                    "atom_id": "duplicate",
                    "content": "小明喜欢爵士乐",
                    "source_scene": "group_chat",
                    "source_id": "stream-1",
                },
                {
                    "atom_id": "other-stream",
                    "content": "小明喜欢爵士乐",
                    "source_scene": "private_chat",
                    "source_id": "stream-2",
                },
            ],
            recent=[
                {
                    "atom_id": "contradiction",
                    "content": "小明不喜欢爵士乐",
                    "source_scene": "group_chat",
                    "source_id": "stream-1",
                },
                {
                    "atom_id": "atom-new",
                    "content": "小明喜欢爵士乐",
                    "source_scene": "group_chat",
                    "source_id": "stream-1",
                },
            ],
        )
        checker = ObjectivityChecker(store)  # type: ignore[arg-type]

        conflicts = await checker.detect_conflicts(make_atom())

        self.assertEqual([call.get("atom_type") for call in store.calls], ["factual", None])
        self.assertEqual(
            {(conflict.existing_atom_id, conflict.conflict_type) for conflict in conflicts},
            {("duplicate", "duplicate"), ("contradiction", "contradiction")},
        )

    async def test_check_before_write_records_noise_trace_and_persistent_conflict_rows(self) -> None:
        checker = ObjectivityChecker(FakeStore())  # type: ignore[arg-type]
        trace_recorder = SimpleNamespace(record=Mock(return_value=True))

        noise_result = await checker.check_before_write(make_atom(content="!!"), trace_recorder=trace_recorder)
        write_result = await checker.check_before_write(make_atom(content="小明说自己喜欢爵士乐"), trace_recorder)
        conflict_id = await checker.record_conflict(
            ConflictInfo(
                existing_atom_id="old-atom",
                existing_content="小明喜欢爵士乐",
                new_content="小明不喜欢爵士乐",
                conflict_type="contradiction",
                overlap_score=0.7,
                new_atom_id="new-atom",
            )
        )
        noise_id = await checker.record_noise("x" * 260, source_scene="group_chat", significance=0.3)

        self.assertFalse(noise_result.passed)
        self.assertEqual(noise_result.recommendation, "reject")
        self.assertTrue(write_result.passed)
        self.assertEqual(write_result.recommendation, "write")
        trace_recorder.record.assert_called_once()
        self.assertEqual(NoisePool.select().count(), 2)
        self.assertNotEqual(conflict_id, "")
        self.assertNotEqual(noise_id, "")
        conflict = ConflictObservation.get_by_id(int(conflict_id))
        noise = NoisePool.get_by_id(int(noise_id))
        self.assertEqual(conflict.atom_a_id, "old-atom")
        self.assertEqual(conflict.atom_b_id, "new-atom")
        self.assertIn("重叠度: 0.70", conflict.description)
        self.assertEqual(noise.source_scene, "group_chat")
        self.assertEqual(len(noise.content), 200)

    async def test_record_failures_return_empty_ids(self) -> None:
        checker = ObjectivityChecker(FakeStore())  # type: ignore[arg-type]

        with patch("src.memory.objectivity_check.ConflictObservation.create", side_effect=RuntimeError("boom")):
            self.assertEqual(await checker.record_conflict(ConflictInfo("old", "a", "b", "contradiction", 0.5)), "")
        with patch("src.memory.objectivity_check.NoisePool.create", side_effect=RuntimeError("boom")):
            self.assertEqual(await checker.record_noise("noise"), "")


if __name__ == "__main__":
    unittest.main()
