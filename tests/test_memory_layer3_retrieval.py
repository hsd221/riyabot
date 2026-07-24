import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.memory import layer3_retrieval
from src.memory.atom import AtomType, DecayType, EpisodicDetail, MemoryAtom, SemanticDetail
from src.memory.layer3_retrieval import (
    PRIVACY_CONTEXT_SENSITIVE,
    PRIVACY_PRIVATE,
    PRIVACY_PUBLIC,
    MemoryRetriever,
    MemoryWriter,
    PartitionManager,
    PrivacyFilter,
    RetrievedAtom,
    _convert_atom_type,
    _convert_decay_type,
    _entities_include_user,
    _global_memory_allowed,
    _query_relevance,
    _resolve_scene_type,
    _stream_id_from_blacklist_entry,
    cosine_similarity,
    rank_atoms,
)
from src.memory.schema import (
    EpisodicDetail as EpisodicDetailModel,
    MemoryAtom as MemoryAtomModel,
    SemanticDetail as SemanticDetailModel,
    configure_memory_database,
    initialize_database,
    memory_db,
)
from src.memory.write_ops import WriteOpLogger


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


def make_atom(**overrides) -> MemoryAtom:
    data = {
        "atom_id": "atom-1",
        "atom_type": AtomType.PREFERENCE,
        "content": "user-1 喜欢爵士乐",
        "entities": ["user-1", "爵士乐"],
        "importance": 0.8,
        "confidence": 0.7,
        "weight": 0.6,
        "created_at": 100.0,
        "last_accessed_at": 200.0,
        "last_reinforced_at": 300.0,
        "ttl_days": 60.0,
        "decay_type": DecayType.EXPONENTIAL,
        "reinforcement_count": 2,
        "source_scene": "group_chat",
        "source_id": "stream-1",
        "privacy_level": PRIVACY_CONTEXT_SENSITIVE,
        "trace_chain_id": "trace-1",
        "status": "active",
        "embedding": [0.1, 0.2],
    }
    data.update(overrides)
    return MemoryAtom(**data)


def create_model_atom(atom_id: str, **overrides) -> None:
    data = {
        "atom_id": atom_id,
        "atom_type": "preference",
        "content": f"{atom_id} 小明喜欢爵士乐",
        "entities": '["user-1", {"id": "friend"}]',
        "importance": 0.8,
        "confidence": 0.7,
        "weight": 0.6,
        "created_at": datetime.fromtimestamp(100.0),
        "last_accessed_at": datetime.fromtimestamp(200.0),
        "last_reinforced_at": datetime.fromtimestamp(300.0),
        "ttl_days": 60,
        "decay_type": "exponential",
        "reinforcement_count": 2,
        "source_scene": "group_chat",
        "source_id": "stream-1",
        "privacy_level": PRIVACY_CONTEXT_SENSITIVE,
        "status": "active",
        "embedding_id": atom_id,
    }
    data.update(overrides)
    MemoryAtomModel.create(**data)


class Layer3UtilityTest(unittest.TestCase):
    def test_cosine_rank_relevance_and_type_helpers_cover_boundaries(self) -> None:
        self.assertEqual(cosine_similarity([], [1.0]), 0.0)
        self.assertEqual(cosine_similarity([0.0], [1.0]), 0.0)
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.5, 0.0]), 1.0)

        ranked = rank_atoms(
            [
                {"atom_id": "miss", "weight": 0.9, "embedding": [0.0, 1.0]},
                {"atom_id": "match", "weight": 0.4, "embedding": [1.0, 0.0]},
                {"atom_id": "no-embedding", "weight": 1.0},
            ],
            [1.0, 0.0],
        )
        self.assertEqual([atom["atom_id"] for atom in ranked], ["match", "miss", "no-embedding"])
        self.assertEqual(
            rank_atoms([{"atom_id": "a", "weight": 0.2}, {"atom_id": "b", "weight": 0.7}])[0]["atom_id"], "b"
        )

        self.assertEqual(_convert_decay_type(DecayType.LINEAR), "linear")
        self.assertEqual(_convert_decay_type("step"), "step")
        self.assertEqual(_convert_atom_type(AtomType.FACTUAL), "factual")
        self.assertEqual(_convert_atom_type("planned"), "planned")
        self.assertEqual(_query_relevance("爵士乐", "小明喜欢爵士乐"), 1.0)
        self.assertGreater(_query_relevance("爵士音乐", "爵士演出"), 0.0)
        self.assertEqual(_query_relevance("苹果", "香蕉", similarity_score=0.95), 0.0)
        self.assertEqual(_query_relevance("", "", similarity_score=0.4), 0.4)

    def test_entities_privacy_scene_and_global_memory_helpers(self) -> None:
        self.assertTrue(_entities_include_user('[{"id": "user-1"}, "other"]', "user-1"))
        self.assertTrue(_entities_include_user({"qq": "12345"}, "12345"))
        self.assertTrue(_entities_include_user("user-1", "user-1"))
        self.assertFalse(_entities_include_user('["user-12"]', "user-1"))
        self.assertFalse(_entities_include_user(None, "user-1"))

        atoms = [
            {"atom_id": "public", "privacy_level": PRIVACY_PUBLIC, "source_scene": "private_chat", "source_id": "p1"},
            {"atom_id": "group", "privacy_level": PRIVACY_CONTEXT_SENSITIVE, "source_scene": "group_chat"},
            {
                "atom_id": "group-scoped",
                "privacy_level": PRIVACY_CONTEXT_SENSITIVE,
                "source_scene": "group_chat",
                "source_id": "group-1",
            },
            {
                "atom_id": "private",
                "privacy_level": PRIVACY_PRIVATE,
                "source_scene": "private_chat",
                "source_id": "user-1",
            },
            {"atom_id": "unknown", "privacy_level": "secret", "source_scene": "group_chat"},
        ]

        group_atoms = PrivacyFilter.filter_atoms(atoms, target_scene="group_chat", target_scope="group-1")
        other_group_atoms = PrivacyFilter.filter_atoms(atoms, target_scene="group_chat", target_scope="group-2")
        private_atoms = PrivacyFilter.filter_atoms(atoms, target_scene="private_chat", target_scope="user-1")

        self.assertEqual([atom["atom_id"] for atom in group_atoms], ["public", "group", "group-scoped"])
        self.assertEqual([atom["atom_id"] for atom in other_group_atoms], ["public", "group"])
        self.assertEqual([atom["atom_id"] for atom in private_atoms], ["public", "private"])
        self.assertEqual(_resolve_scene_type("abc_group"), "group_chat")
        self.assertEqual(_resolve_scene_type("direct"), "private_chat")
        self.assertEqual(_resolve_scene_type("ignored", "system"), "system")

        self.assertEqual(_stream_id_from_blacklist_entry("qq:123:group"), hashlib.md5(b"qq_123").hexdigest())
        self.assertEqual(
            _stream_id_from_blacklist_entry("qq:123:private"),
            hashlib.md5(b"qq_123_private").hexdigest(),
        )
        self.assertIsNone(_stream_id_from_blacklist_entry("bad-entry"))

        with patch.object(layer3_retrieval, "_global_memory_enabled", return_value=False):
            self.assertFalse(_global_memory_allowed("stream-1"))
        with (
            patch.object(layer3_retrieval, "_global_memory_enabled", return_value=True),
            patch.object(layer3_retrieval, "_global_memory_blacklist_source_ids", return_value={"blocked"}),
        ):
            self.assertTrue(_global_memory_allowed("stream-1"))
            self.assertFalse(_global_memory_allowed("blocked"))
        self.assertFalse(_global_memory_allowed("stream-1", include_global=False))


class Layer3SQLiteRetrievalTest(MemoryDatabaseFixtureMixin, unittest.IsolatedAsyncioTestCase):
    async def test_partition_stats_and_sqlite_retrieval_paths_are_filtered_and_ordered(self) -> None:
        create_model_atom("group-high", weight=0.8, content="小明喜欢爵士乐", source_id="stream-1")
        create_model_atom("group-low", weight=0.2, content="小明也聊过爵士乐", source_id="stream-1")
        create_model_atom("other-group", weight=0.7, source_id="stream-2")
        create_model_atom("private", weight=0.9, source_scene="private_chat", source_id="user-1")
        create_model_atom("archived", weight=0.95, status="archived")
        create_model_atom("partial-user", weight=0.6, entities='["user-12"]', source_id="stream-3")
        create_model_atom("bad-json", weight=0.5, content="bad-json 无关内容", entities="not-json")
        retriever = MemoryRetriever(store=SimpleNamespace())

        stats = await PartitionManager.get_partition_stats(SimpleNamespace())
        scene_results = await retriever.retrieve_by_scene("group_chat", limit=10, min_weight=0.3)
        source_results = await retriever.retrieve_by_source(
            "stream-1", source_scene="group_chat", limit=10, min_weight=0.0
        )
        user_results = await retriever.retrieve_by_user(
            "user-1", source_id="stream-1", source_scene="group_chat", limit=10
        )
        keyword_results = await retriever.keyword_search(
            "爵士乐",
            filters={"source_scene": "group_chat", "source_id": "stream-1", "atom_type": "preference"},
            limit=10,
        )
        fetched = await retriever._fetch_atoms_by_ids(["private", "group-high", "missing"])

        self.assertEqual(PartitionManager.get_partition("group_chat"), "群聊记忆")
        self.assertEqual(PartitionManager.get_partition("unknown"), "unknown")
        self.assertEqual(PartitionManager.get_partition_filters("dream"), {"source_scene": "dream"})
        self.assertEqual(stats["group_chat"], 6)
        self.assertEqual(stats["private_chat"], 1)
        self.assertEqual(
            [atom["atom_id"] for atom in scene_results], ["group-high", "other-group", "partial-user", "bad-json"]
        )
        self.assertEqual([atom["atom_id"] for atom in source_results], ["group-high", "bad-json", "group-low"])
        self.assertEqual([atom["atom_id"] for atom in user_results], ["group-high", "group-low"])
        self.assertEqual([atom["atom_id"] for atom in keyword_results], ["group-high", "group-low"])
        self.assertEqual([atom["atom_id"] for atom in fetched], ["private", "group-high"])
        self.assertEqual(retriever._model_to_result(MemoryAtomModel.get_by_id("bad-json"))["entities"], "not-json")
        self.assertEqual(await retriever.retrieve_by_source(""), [])

    def test_prompt_formatting_and_append_helpers_respect_line_boundaries(self) -> None:
        atoms = [
            {"atom_id": "a", "atom_type": "factual", "content": "short", "weight": 0.8, "relevance_score": 0.5},
            {"atom_id": "b", "atom_type": "preference", "content": "long content", "weight": 0.4},
        ]

        formatted = MemoryRetriever._format_atoms_for_prompt(atoms)
        one_line, ids = MemoryRetriever._format_atoms_for_prompt_with_ids(atoms, max_chars=45)
        appended, added = MemoryRetriever._append_prompt_line(one_line, "- extra", max_chars=80)
        blocked, blocked_added = MemoryRetriever._append_prompt_line(one_line, "- too long", max_chars=10)

        self.assertIn("相关度0.50", formatted)
        self.assertEqual(ids, ["a"])
        self.assertTrue(added)
        self.assertIn("- extra", appended)
        self.assertFalse(blocked_added)
        self.assertEqual(blocked, one_line)


class Layer3VectorAndContextTest(MemoryDatabaseFixtureMixin, unittest.IsolatedAsyncioTestCase):
    async def test_retrieve_hybrid_fuses_vector_and_bm25_rankings(self) -> None:
        bm25 = SimpleNamespace(
            search=AsyncMock(
                return_value=[
                    RetrievedAtom(
                        atom_id="shared",
                        content="Alpha-42 精确命中",
                        atom_type="factual",
                        weight=0.8,
                        similarity_score=5.0,
                    ),
                    RetrievedAtom(
                        atom_id="exact-only",
                        content="Alpha-42 只被词法检索命中",
                        atom_type="factual",
                        weight=0.8,
                        similarity_score=4.0,
                    ),
                ]
            )
        )
        retriever = MemoryRetriever(store=SimpleNamespace(), bm25_retriever=bm25)
        retriever.retrieve_by_vector = AsyncMock(
            return_value=[
                {
                    "atom_id": "semantic-only",
                    "content": "语义相关候选",
                    "atom_type": "factual",
                    "weight": 0.8,
                    "similarity_score": 0.95,
                    "final_score": 0.76,
                },
                {
                    "atom_id": "shared",
                    "content": "Alpha-42 精确命中",
                    "atom_type": "factual",
                    "weight": 0.8,
                    "similarity_score": 0.8,
                    "final_score": 0.64,
                },
            ]
        )
        atom_map = {
            atom_id: {
                "atom_id": atom_id,
                "content": atom_id,
                "atom_type": "factual",
                "weight": 0.8,
            }
            for atom_id in ("shared", "semantic-only", "exact-only")
        }
        retriever._fetch_atoms_by_ids = AsyncMock(
            side_effect=lambda atom_ids: [atom_map[atom_id].copy() for atom_id in atom_ids]
        )

        filters = {"source_scene": "group_chat", "source_id": "stream-1", "status": "active"}
        query_text = "需要查证的问题: Alpha-42 是什么\n当前目标消息: Alpha-42 是啥\n近邻上下文: 这里是应该排除的旧话题"
        results = await retriever.retrieve_hybrid(
            query_text=query_text,
            filters=filters,
            top_k=3,
        )

        self.assertEqual([atom["atom_id"] for atom in results], ["shared", "semantic-only", "exact-only"])
        self.assertEqual(results[0]["retrieval_sources"], ["vector", "bm25"])
        self.assertEqual(results[1]["retrieval_sources"], ["vector"])
        self.assertEqual(results[2]["retrieval_sources"], ["bm25"])
        bm25.search.assert_awaited_once_with("Alpha-42 是什么 Alpha-42 是啥", top_k=6, filters=filters)

    async def test_retrieve_hybrid_uses_like_only_after_vector_and_bm25_are_empty(self) -> None:
        bm25_atom = RetrievedAtom(
            atom_id="bm25-only",
            content="Alpha-42 精确命中",
            atom_type="factual",
            weight=0.7,
            similarity_score=3.0,
        )
        bm25 = SimpleNamespace(search=AsyncMock(return_value=[bm25_atom]))
        retriever = MemoryRetriever(store=SimpleNamespace(), bm25_retriever=bm25)
        retriever.retrieve_by_vector = AsyncMock(return_value=[])
        retriever.keyword_search = AsyncMock(return_value=[{"atom_id": "like-only"}])
        retriever._fetch_atoms_by_ids = AsyncMock(
            return_value=[
                {
                    "atom_id": "bm25-only",
                    "content": "Alpha-42 精确命中",
                    "atom_type": "factual",
                    "weight": 0.7,
                }
            ]
        )

        bm25_results = await retriever.retrieve_hybrid(query_text="Alpha-42", top_k=2)

        self.assertEqual([atom["atom_id"] for atom in bm25_results], ["bm25-only"])
        retriever.keyword_search.assert_not_awaited()

        bm25.search.return_value = []
        like_results = await retriever.retrieve_hybrid(query_text="Alpha-42", top_k=2)

        self.assertEqual(like_results, [{"atom_id": "like-only"}])
        retriever.keyword_search.assert_awaited_once_with(query="Alpha-42", filters=None, limit=2)

    async def test_retrieve_hybrid_keeps_vector_results_when_bm25_query_is_empty(self) -> None:
        bm25 = SimpleNamespace(search=AsyncMock(side_effect=AssertionError("BM25 should not receive an empty query")))
        retriever = MemoryRetriever(store=SimpleNamespace(), bm25_retriever=bm25)
        retriever.retrieve_by_vector = AsyncMock(
            return_value=[
                {
                    "atom_id": "semantic-only",
                    "content": "语义相关候选",
                    "atom_type": "factual",
                    "weight": 0.8,
                    "similarity_score": 0.9,
                }
            ]
        )
        retriever._fetch_atoms_by_ids = AsyncMock(
            return_value=[
                {
                    "atom_id": "semantic-only",
                    "content": "语义相关候选",
                    "atom_type": "factual",
                    "weight": 0.8,
                }
            ]
        )

        results = await retriever.retrieve_hybrid(query_text="近邻上下文: 这是只供向量理解的旧话题", top_k=2)

        self.assertEqual([atom["atom_id"] for atom in results], ["semantic-only"])
        self.assertEqual(results[0]["retrieval_sources"], ["vector"])

    async def test_retrieve_hybrid_keeps_bm25_results_when_vector_search_raises(self) -> None:
        bm25 = SimpleNamespace(
            search=AsyncMock(
                return_value=[
                    RetrievedAtom(
                        atom_id="exact-only",
                        content="Alpha-42 精确命中",
                        atom_type="factual",
                        weight=0.7,
                        similarity_score=3.0,
                    )
                ]
            )
        )
        retriever = MemoryRetriever(store=SimpleNamespace(), bm25_retriever=bm25)
        retriever.retrieve_by_vector = AsyncMock(side_effect=RuntimeError("vector search unavailable"))
        retriever._fetch_atoms_by_ids = AsyncMock(
            return_value=[
                {
                    "atom_id": "exact-only",
                    "content": "Alpha-42 精确命中",
                    "atom_type": "factual",
                    "weight": 0.7,
                }
            ]
        )

        results = await retriever.retrieve_hybrid(query_text="Alpha-42", top_k=2)

        self.assertEqual([atom["atom_id"] for atom in results], ["exact-only"])
        self.assertEqual(results[0]["retrieval_sources"], ["bm25"])

    async def test_retrieve_by_vector_skips_embedding_while_vector_search_is_disabled(self) -> None:
        store = SimpleNamespace(
            qdrant=SimpleNamespace(vector_search_enabled=False),
            search_similar=AsyncMock(return_value=[]),
        )
        retriever = MemoryRetriever(store)

        with (
            patch.object(layer3_retrieval, "generate_query_embedding", new=AsyncMock()) as generate_embedding,
            patch.object(retriever, "keyword_search", new=AsyncMock(return_value=[{"atom_id": "kw"}])) as keyword,
        ):
            result = await retriever.retrieve_by_vector(
                query_text="爵士乐",
                filters={"keyword": "爵士乐", "status": "active"},
                top_k=3,
            )

        self.assertEqual(result, [{"atom_id": "kw"}])
        generate_embedding.assert_not_awaited()
        store.search_similar.assert_not_awaited()
        keyword.assert_awaited_once_with(
            query="爵士乐",
            filters={"keyword": "爵士乐", "status": "active"},
            limit=3,
        )

    async def test_retrieve_by_vector_uses_embedding_fallback_fetches_full_atoms_and_sorts(self) -> None:
        store = SimpleNamespace(search_similar=AsyncMock(return_value=[]))
        retriever = MemoryRetriever(store)

        with (
            patch.object(layer3_retrieval, "generate_query_embedding", new=AsyncMock(return_value=None)),
            patch.object(retriever, "keyword_search", new=AsyncMock(return_value=[{"atom_id": "kw"}])) as keyword,
        ):
            self.assertEqual(await retriever.retrieve_by_vector(query_text="爵士乐", top_k=1), [{"atom_id": "kw"}])
        keyword.assert_awaited_once()

        store.search_similar = AsyncMock(
            return_value=[
                {"payload": {"atom_id": "a"}, "score": 0.5},
                {"id": "b", "payload": {}, "score": 0.9},
            ]
        )
        with patch.object(
            retriever,
            "_fetch_atoms_by_ids",
            new=AsyncMock(return_value=[{"atom_id": "a", "weight": 0.8}, {"atom_id": "b", "weight": 0.2}]),
        ) as fetch:
            results = await retriever.retrieve_by_vector(query_embedding=[1.0], top_k=2, min_weight=0.3)

        fetch.assert_awaited_once_with(["a", "b"])
        self.assertEqual([atom["atom_id"] for atom in results], ["a"])
        self.assertEqual(results[0]["similarity_score"], 0.5)
        self.assertEqual(results[0]["final_score"], 0.4)

        store.search_similar = AsyncMock(return_value=[])
        with patch.object(retriever, "keyword_search", new=AsyncMock(return_value=[])) as empty_keyword:
            self.assertEqual(
                await retriever.retrieve_by_vector(
                    query_embedding=[1.0],
                    filters={"keyword": "fallback"},
                ),
                [],
            )
        empty_keyword.assert_awaited_once_with(query="fallback", filters={"keyword": "fallback"}, limit=10)

    async def test_context_for_reply_merges_dedupes_sensory_tags_and_associations(self) -> None:
        EpisodicDetailModel.create(
            id="local-episodic",
            atom="local-episodic",
            sensory_tags=json.dumps(["visual", "emotional:joy"], ensure_ascii=False),
            temporal_context="深夜",
        )
        retriever = MemoryRetriever(store=SimpleNamespace())
        retriever.retrieve_hybrid = AsyncMock(
            return_value=[
                {
                    "atom_id": "query-match",
                    "content": "小明喜欢爵士乐",
                    "atom_type": "preference",
                    "weight": 0.7,
                    "source_scene": "group_chat",
                    "source_id": "stream-1",
                    "similarity_score": 0.6,
                }
            ]
        )
        retriever.retrieve_by_source = AsyncMock(
            return_value=[
                {
                    "atom_id": "local-episodic",
                    "content": "小明在爵士乐音乐会很开心",
                    "atom_type": "episodic",
                    "weight": 0.8,
                    "source_scene": "group_chat",
                    "source_id": "stream-1",
                }
            ]
        )
        retriever.retrieve_by_user = AsyncMock(return_value=[{"atom_id": "query-match", "content": "duplicate"}])
        retriever.retrieve_by_scene = AsyncMock(return_value=[])
        retriever._expand_with_associations = AsyncMock(
            return_value=[
                {
                    "atom_id": "assoc",
                    "content": "爵士乐相关记忆",
                    "atom_type": "factual",
                    "weight": 0.9,
                }
            ]
        )

        formatted, atom_ids = await retriever.get_context_for_reply_with_ids(
            stream_id="stream-1",
            user_id="user-1",
            scene_type="group_chat",
            max_atoms=2,
            max_chars=500,
            include_global=False,
            query_text="爵士乐",
        )
        delegated = await retriever.get_context_for_reply(
            stream_id="stream-1",
            scene_type="group_chat",
            max_atoms=1,
            include_global=False,
            query_text="爵士乐",
        )
        delegated_ids = await retriever.get_atom_ids_for_reply(
            stream_id="stream-1",
            scene_type="group_chat",
            max_atoms=1,
            include_global=False,
        )

        self.assertIn("[情感: joy] [感官: visual] [时间: 深夜]", formatted)
        self.assertIn("A1 [关联]", formatted)
        self.assertEqual(atom_ids, ["local-episodic", "query-match", "assoc"])
        self.assertIn("local-episodic", delegated_ids)
        self.assertIsInstance(delegated, str)

    async def test_cross_scene_context_applies_global_gate_blacklist_privacy_and_query_relevance(self) -> None:
        retriever = MemoryRetriever(store=SimpleNamespace())
        retriever.retrieve_hybrid = AsyncMock(
            return_value=[
                {
                    "atom_id": "public",
                    "content": "公开爵士乐记忆",
                    "atom_type": "factual",
                    "weight": 0.8,
                    "privacy_level": PRIVACY_PUBLIC,
                    "source_scene": "private_chat",
                    "source_id": "allowed",
                },
                {
                    "atom_id": "blocked",
                    "content": "公开爵士乐但被黑名单过滤",
                    "atom_type": "factual",
                    "weight": 0.9,
                    "privacy_level": PRIVACY_PUBLIC,
                    "source_scene": "private_chat",
                    "source_id": "blocked-source",
                },
                {
                    "atom_id": "private",
                    "content": "私密爵士乐记忆",
                    "atom_type": "factual",
                    "weight": 0.9,
                    "privacy_level": PRIVACY_PRIVATE,
                    "source_scene": "private_chat",
                    "source_id": "private-user",
                },
            ]
        )
        retriever.retrieve_by_scene = AsyncMock(return_value=[])
        retriever.retrieve_by_user = AsyncMock(return_value=[])

        with patch.object(layer3_retrieval, "_global_memory_allowed", return_value=False):
            self.assertEqual(await retriever.get_cross_scene_context_with_ids("group_chat", "stream-1"), ("", []))

        with (
            patch.object(layer3_retrieval, "_global_memory_allowed", return_value=True),
            patch.object(layer3_retrieval, "_global_memory_blacklist_source_ids", return_value={"blocked-source"}),
        ):
            formatted, atom_ids = await retriever.get_cross_scene_context_with_ids(
                scene_type="group_chat",
                stream_id="stream-1",
                max_atoms=3,
                max_chars=300,
                query_text="爵士乐",
            )
            text_only = await retriever.get_cross_scene_context(
                scene_type="group_chat",
                stream_id="stream-1",
                max_atoms=1,
                max_chars=300,
                query_text="爵士乐",
            )

        self.assertEqual(atom_ids, ["public"])
        self.assertIn("公开爵士乐记忆", formatted)
        self.assertIn("公开爵士乐记忆", text_only)


class MemoryWriterLayer3Test(MemoryDatabaseFixtureMixin, unittest.IsolatedAsyncioTestCase):
    async def test_write_atom_keeps_write_ops_serializable_when_store_mutates_payload(self) -> None:
        async def insert_atom(atom_data: dict) -> str:
            for field_name in ("created_at", "last_accessed_at", "last_reinforced_at"):
                atom_data[field_name] = datetime.fromtimestamp(atom_data[field_name])
            return atom_data["atom_id"]

        qdrant = SimpleNamespace(upsert_atom_vector=AsyncMock(return_value=True))
        store = SimpleNamespace(qdrant=qdrant, insert_atom=AsyncMock(side_effect=insert_atom))
        op_logger = WriteOpLogger(str(Path(self.tmpdir.name) / "write-ops.db"))
        writer = MemoryWriter(store, op_logger)

        atom_id = await writer.write_atom(make_atom(atom_id="mutated-payload"))

        self.assertEqual(atom_id, "mutated-payload")
        qdrant.upsert_atom_vector.assert_awaited_once()
        with open(op_logger.log_file, encoding="utf-8") as log_file:
            write_ops = [json.loads(line) for line in log_file if line.strip()]
        self.assertEqual(
            [(write_op["target"], write_op["status"]) for write_op in write_ops],
            [("sqlite", "completed"), ("qdrant", "completed")],
        )

    async def test_update_atom_keeps_write_ops_serializable_when_store_mutates_updates(self) -> None:
        converter = MemoryWriter(SimpleNamespace())
        content_atom = converter._atom_to_store_dict(make_atom(atom_id="content-update"))
        payload_atom = converter._atom_to_store_dict(make_atom(atom_id="payload-update"))
        payload_atom.pop("content")
        persisted = {
            "content-update": content_atom,
            "payload-update": payload_atom,
        }

        async def update_atom(atom_id: str, atom_updates: dict) -> bool:
            for field_name in ("last_accessed_at", "last_reinforced_at"):
                atom_updates[field_name] = datetime.fromtimestamp(atom_updates[field_name])
            persisted[atom_id].update(atom_updates)
            return True

        qdrant = SimpleNamespace(
            upsert_atom_vector=AsyncMock(return_value=True),
            set_atom_payload=AsyncMock(return_value=True),
        )
        store = SimpleNamespace(
            qdrant=qdrant,
            get_atom=AsyncMock(side_effect=lambda atom_id: dict(persisted[atom_id])),
            update_atom=AsyncMock(side_effect=update_atom),
        )
        op_logger = WriteOpLogger(str(Path(self.tmpdir.name) / "update-write-ops.db"))
        writer = MemoryWriter(store, op_logger)

        with patch.object(layer3_retrieval, "generate_embedding", new=AsyncMock(return_value=[0.2, 0.8])):
            content_updated = await writer.update_atom(
                "content-update",
                {"content": "更新后的爵士乐事实", "last_accessed_at": 400.0},
            )
            payload_updated = await writer.update_atom(
                "payload-update",
                {"weight": 0.65, "last_accessed_at": 500.0},
            )

        self.assertEqual(content_updated["content"], "更新后的爵士乐事实")
        self.assertEqual(payload_updated["weight"], 0.65)
        self.assertEqual(store.update_atom.await_count, 2)
        qdrant.upsert_atom_vector.assert_awaited_once()
        qdrant.set_atom_payload.assert_awaited_once()
        self.assertEqual(qdrant.upsert_atom_vector.await_args.kwargs["payload"]["atom_id"], "content-update")
        self.assertEqual(qdrant.set_atom_payload.await_args.args[1]["weight"], 0.65)
        with open(op_logger.log_file, encoding="utf-8") as log_file:
            write_ops = [json.loads(line) for line in log_file if line.strip()]
        self.assertEqual(
            [(write_op["target"], write_op["status"]) for write_op in write_ops],
            [
                ("sqlite", "completed"),
                ("qdrant", "completed"),
                ("sqlite", "completed"),
                ("qdrant", "completed"),
            ],
        )

    async def test_writer_validation_conversion_detail_writes_and_qdrant_payloads(self) -> None:
        qdrant = SimpleNamespace(upsert_atom_vector=AsyncMock(return_value=True))
        writer = MemoryWriter(SimpleNamespace(qdrant=qdrant))
        atom = make_atom()

        store_dict = writer._atom_to_store_dict(atom)
        converted = writer._dict_to_atom({**store_dict, "entities": ["user-1"]})
        no_embedding = make_atom(atom_id="no-embedding", embedding=None)

        self.assertTrue(writer._validate_atom(atom))
        self.assertFalse(writer._validate_atom(make_atom(atom_id="")))
        self.assertFalse(writer._validate_atom(make_atom(content="")))
        self.assertFalse(writer._validate_atom(make_atom(importance=1.2)))
        self.assertFalse(writer._validate_atom(make_atom(confidence=-0.1)))
        self.assertFalse(writer._validate_atom(make_atom(atom_type="factual")))
        self.assertFalse(writer._validate_atom(make_atom(source_scene="bad-scene")))
        self.assertEqual(store_dict["atom_type"], "preference")
        self.assertEqual(json.loads(store_dict["entities"]), ["user-1", "爵士乐"])
        self.assertEqual(store_dict["decay_type"], "exponential")
        self.assertEqual(store_dict["trace_chain_id"], "trace-1")
        self.assertEqual(converted.atom_type, AtomType.PREFERENCE)
        self.assertEqual(converted.decay_type, DecayType.EXPONENTIAL)

        self.assertTrue(await writer._upsert_qdrant(no_embedding))
        self.assertTrue(await writer._upsert_qdrant(atom))
        qdrant.upsert_atom_vector.assert_awaited_once()
        self.assertEqual(qdrant.upsert_atom_vector.await_args.kwargs["point_id"], "atom-1")
        self.assertEqual(qdrant.upsert_atom_vector.await_args.kwargs["payload"]["source_id"], "stream-1")

        await writer._write_episodic_detail(
            "episode-1",
            EpisodicDetail(
                atom_id="episode-1",
                event_time=123.0,
                participants=["Alice"],
                emotion_tags=["joy"],
                sensory_tags=["visual"],
                temporal_context="夜晚",
            ),
        )
        await writer._write_semantic_detail(
            "semantic-1",
            SemanticDetail(
                atom_id="semantic-1",
                attr_category="interest",
                attr_name="music",
                attr_value="jazz",
                evidence_list=["msg-1"],
                evidence_counter=2,
            ),
        )
        await writer._write_semantic_detail(
            "semantic-1",
            SemanticDetail(
                atom_id="semantic-1",
                attr_category="interest",
                attr_name="music",
                attr_value="jazz",
                subject_key="qq:user-1",
                evidence_list=["msg-2"],
                evidence_counter=1,
            ),
        )

        episode = EpisodicDetailModel.get_by_id("episode-1")
        semantic = SemanticDetailModel.get_by_id("semantic-1")
        self.assertEqual(json.loads(episode.participants), ["Alice"])
        self.assertEqual(episode.temporal_context, "夜晚")
        self.assertEqual(semantic.attr_value, "jazz")
        self.assertEqual(semantic.subject_key, "qq:user-1")
        self.assertEqual(json.loads(semantic.evidence_list), ["msg-1", "msg-2"])
        self.assertEqual(semantic.evidence_counter, 2)

    async def test_write_batch_and_update_atom_paths_delegate_to_store_and_swallow_qdrant_failures(self) -> None:
        qdrant = SimpleNamespace(
            upsert_atom_vector=AsyncMock(return_value=False),
            set_atom_payload=AsyncMock(return_value=True),
        )
        store = SimpleNamespace(
            qdrant=qdrant,
            insert_atom=AsyncMock(),
            update_atom=AsyncMock(return_value=True),
            get_atom=AsyncMock(),
        )
        writer = MemoryWriter(store)

        with patch.object(layer3_retrieval, "generate_embedding", new=AsyncMock(return_value=[0.3, 0.4])) as embed:
            atom_id = await writer.write_atom(make_atom(atom_id="write-me", embedding=None))

        self.assertEqual(atom_id, "write-me")
        store.insert_atom.assert_awaited_once()
        embed.assert_awaited_once_with("user-1 喜欢爵士乐")
        qdrant.upsert_atom_vector.assert_awaited_once()

        with self.assertRaises(ValueError):
            await writer.write_atom(make_atom(atom_id=""))

        qdrant.upsert_atom_vector.reset_mock()
        batch_ids = await writer.batch_write([make_atom(atom_id="batch-ok"), make_atom(atom_id="", content="bad")])
        self.assertEqual(batch_ids, ["batch-ok"])
        self.assertEqual(store.insert_atom.await_count, 2)
        qdrant.upsert_atom_vector.assert_awaited_once()

        current = writer._atom_to_store_dict(make_atom(atom_id="update-me"))
        updated = {**current, "content": "更新后的爵士乐事实", "weight": 0.75}
        current_without_content = {key: value for key, value in current.items() if key != "content"}
        store.get_atom = AsyncMock(
            side_effect=[None, current, updated, current_without_content, {**current_without_content, "weight": 0.65}]
        )
        self.assertIsNone(await writer.update_atom("missing", {"weight": 0.9}))

        with patch.object(
            layer3_retrieval, "generate_embedding", new=AsyncMock(return_value=[0.9, 0.1])
        ) as update_embed:
            content_update = await writer.update_atom("update-me", {"content": "更新后的爵士乐事实"})
        update_embed.assert_awaited_once_with("更新后的爵士乐事实")
        self.assertEqual(content_update["content"], "更新后的爵士乐事实")

        payload_update = await writer.update_atom("update-me", {"weight": 0.65})

        self.assertEqual(payload_update["weight"], 0.65)
        qdrant.set_atom_payload.assert_awaited_once()
        payload_args = qdrant.set_atom_payload.await_args.args
        self.assertEqual(payload_args[0], "update-me")
        self.assertEqual(payload_args[1]["weight"], 0.65)
        self.assertEqual(payload_args[1]["source_scene"], "group_chat")


if __name__ == "__main__":
    unittest.main()
