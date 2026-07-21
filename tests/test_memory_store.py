import datetime
import importlib.util
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.llm_models.embedding import embedding_source_hash
from src.llm_models.embedding_profile import EmbeddingProfile, ProfiledEmbedding
from src.memory import store as store_module
from src.memory.schema import (
    AtomAssociationModel,
    ConflictObservation,
    EpisodicDetail,
    MemoryAtom,
    MemoryTraceChain,
    RawMessageArchive,
    SemanticDetail,
    configure_memory_database,
    initialize_database,
    memory_db,
)
from src.memory.store import (
    MemoryStore,
    MemoryStoreConfig,
    QdrantManager,
    _coerce_datetime,
    _normalize_datetime_fields,
)


class MemoryDatabaseFixtureMixin:
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "memory.db"
        self.original_path = memory_db.database
        MemoryStore._instance = None
        configure_memory_database(str(self.db_path))
        initialize_database()

    def tearDown(self) -> None:
        MemoryStore._instance = None
        if not memory_db.is_closed():
            memory_db.close()
        configure_memory_database(str(self.original_path))
        self.tmpdir.cleanup()


class FakeQdrantClient:
    def __init__(
        self,
        *,
        collections: list[str] | None = None,
        vector_size: int = 1024,
        hits: list[SimpleNamespace] | None = None,
        fail: set[str] | None = None,
    ) -> None:
        self.collections = collections or []
        self.vector_size = vector_size
        self.hits = hits or []
        self.fail = fail or set()
        self.created_collections: list[tuple[str, object]] = []
        self.payload_indexes: list[tuple[str, str, str]] = []
        self.upserts: list[tuple[str, list[object]]] = []
        self.search_calls: list[dict] = []
        self.delete_calls: list[tuple[str, object]] = []
        self.set_payload_calls: list[tuple[str, dict, list[object]]] = []
        self.deleted_collections: list[str] = []

    def get_collections(self) -> SimpleNamespace:
        if "get_collections" in self.fail:
            raise RuntimeError("collections failed")
        return SimpleNamespace(collections=[SimpleNamespace(name=name) for name in self.collections])

    def get_collection(self, collection_name: str) -> SimpleNamespace:
        if "get_collection" in self.fail:
            raise RuntimeError("collection failed")
        return SimpleNamespace(
            points_count=7,
            status="green",
            config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=self.vector_size))),
        )

    def create_collection(self, collection_name: str, vectors_config: object) -> None:
        if "create_collection" in self.fail:
            raise RuntimeError("create failed")
        self.created_collections.append((collection_name, vectors_config))

    def create_payload_index(self, collection_name: str, field_name: str, field_type: str) -> None:
        self.payload_indexes.append((collection_name, field_name, field_type))

    def upsert(self, collection_name: str, points: list[object]) -> None:
        if "upsert" in self.fail:
            raise RuntimeError("upsert failed")
        self.upserts.append((collection_name, points))

    def search(self, **kwargs) -> list[SimpleNamespace]:
        if "search" in self.fail:
            raise RuntimeError("search failed")
        self.search_calls.append(kwargs)
        return self.hits

    def delete(self, collection_name: str, points_selector: object) -> None:
        if "delete" in self.fail:
            raise RuntimeError("delete failed")
        self.delete_calls.append((collection_name, points_selector))

    def set_payload(self, collection_name: str, payload: dict, points: list[object]) -> None:
        if "set_payload" in self.fail:
            raise RuntimeError("payload failed")
        self.set_payload_calls.append((collection_name, payload, points))

    def delete_collection(self, collection_name: str) -> None:
        if "delete_collection" in self.fail:
            raise RuntimeError("delete collection failed")
        self.deleted_collections.append(collection_name)


class QueryOnlyClient:
    def __init__(self, hits: list[SimpleNamespace]) -> None:
        self.hits = hits
        self.query_calls: list[dict] = []

    def query_points(self, **kwargs) -> SimpleNamespace:
        self.query_calls.append(kwargs)
        return SimpleNamespace(points=self.hits)


def create_atom(atom_id: str, **overrides) -> None:
    data = {
        "atom_id": atom_id,
        "atom_type": "factual",
        "content": f"{atom_id} 内容",
        "entities": '["user-1"]',
        "importance": 0.8,
        "confidence": 0.7,
        "weight": 0.6,
        "created_at": datetime.datetime.fromtimestamp(100.0),
        "last_accessed_at": datetime.datetime.fromtimestamp(101.0),
        "last_reinforced_at": datetime.datetime.fromtimestamp(102.0),
        "ttl_days": 7,
        "decay_type": "exponential",
        "reinforcement_count": 1,
        "source_scene": "group_chat",
        "source_id": "stream-1",
        "privacy_level": "context_sensitive",
        "status": "active",
        "embedding_id": atom_id,
    }
    data.update(overrides)
    MemoryAtom.create(**data)


class QdrantManagerUtilityTest(unittest.TestCase):
    def test_module_import_falls_back_when_qdrant_client_is_missing(self) -> None:
        module_name = "store_no_qdrant_for_test"
        spec = importlib.util.spec_from_file_location(module_name, store_module.__file__)
        module = importlib.util.module_from_spec(spec)
        real_import = __import__

        def import_without_qdrant(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith("qdrant_client"):
                raise ImportError("qdrant missing")
            return real_import(name, globals, locals, fromlist, level)

        sys.modules[module_name] = module
        try:
            with patch("builtins.__import__", side_effect=import_without_qdrant):
                spec.loader.exec_module(module)
        finally:
            sys.modules.pop(module_name, None)

        self.assertFalse(module.QDRANT_AVAILABLE)
        self.assertIsNone(module._QdrantClient)
        self.assertIsNone(module.qdrant_models)

    def test_config_repr_datetime_normalization_and_point_id_helpers(self) -> None:
        config = MemoryStoreConfig(sqlite_path="memory.db", qdrant_api_key="secret")
        nowish = _coerce_datetime(None)
        unknown_type_datetime = _coerce_datetime(object())
        data = {"created_at": 123.0, "last_accessed_at": "124", "last_reinforced_at": "bad"}

        _normalize_datetime_fields(data)

        self.assertIn("qdrant_api_key=***", repr(config))
        self.assertIsInstance(nowish, datetime.datetime)
        self.assertIsInstance(unknown_type_datetime, datetime.datetime)
        self.assertEqual(data["created_at"], datetime.datetime.fromtimestamp(123.0))
        self.assertEqual(data["last_accessed_at"], datetime.datetime.fromtimestamp(124.0))
        self.assertIsInstance(data["last_reinforced_at"], datetime.datetime)
        self.assertEqual(QdrantManager._normalize_point_id(42), 42)
        self.assertNotEqual(QdrantManager._normalize_point_id(-1), -1)
        self.assertEqual(QdrantManager._normalize_point_id("42"), 42)
        self.assertNotEqual(QdrantManager._normalize_point_id("01"), QdrantManager._normalize_point_id("1"))

        uuid_text = str(uuid.uuid4())
        self.assertEqual(QdrantManager._normalize_point_id(uuid_text), uuid_text)
        self.assertEqual(
            QdrantManager._normalize_point_id("atom-1"),
            str(uuid.uuid5(store_module._QDRANT_POINT_NAMESPACE, "atom-1")),
        )

        class BrokenInt(int):
            def __new__(cls, *args, **kwargs):
                raise ValueError("int unavailable")

        store_module.int = BrokenInt
        try:
            self.assertEqual(
                QdrantManager._normalize_point_id("123"),
                str(uuid.uuid5(store_module._QDRANT_POINT_NAMESPACE, "123")),
            )
        finally:
            delattr(store_module, "int")

    def test_filter_building_collection_size_and_query_api_compatibility(self) -> None:
        schema = [{"name": "status", "type": "keyword"}, {"name": "source_id", "type": "keyword"}]
        qdrant_filter = QdrantManager._build_filter(
            {
                "status": "active",
                "source_id": ["stream-1", "stream-2"],
                "status_empty": [],
                "keyword": "ignored",
                "empty": [],
                "none": None,
            },
            schema,
        )
        empty_filter = QdrantManager._build_filter({"unknown": "ignored"}, schema)
        manager = QdrantManager(MemoryStoreConfig())
        hit = SimpleNamespace(id="a", score=0.9, payload={"atom_id": "a"})
        search_client = FakeQdrantClient(hits=[hit])
        query_client = QueryOnlyClient([hit])

        self.assertEqual(manager._query_points("memory_atoms", [0.0]), [])
        manager._client = search_client
        search_hits = manager._query_points("memory_atoms", [0.1], qdrant_filter, limit=3)
        manager._client = query_client
        query_hits = manager._query_points("memory_atoms", [0.2], None, limit=2)

        self.assertEqual(QdrantManager._payload_field_names(schema), {"status", "source_id"})
        self.assertIsNone(QdrantManager._build_filter(None, schema))
        self.assertIsNone(empty_filter)
        self.assertEqual([condition.key for condition in qdrant_filter.must], ["status", "source_id"])
        self.assertIsNone(
            QdrantManager._collection_vector_size(SimpleNamespace(config=SimpleNamespace(params=object())))
        )
        self.assertEqual(
            QdrantManager._collection_vector_size(
                SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=128))))
            ),
            128,
        )
        self.assertEqual(
            QdrantManager._collection_vector_size(
                SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors={"": SimpleNamespace(size=256)})))
            ),
            256,
        )
        self.assertIsNone(
            QdrantManager._collection_vector_size(
                SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors={"named": object()})))
            )
        )
        self.assertEqual(search_hits, [hit])
        self.assertEqual(query_hits, [hit])
        self.assertEqual(search_client.search_calls[0]["limit"], 3)
        self.assertEqual(query_client.query_calls[0]["limit"], 2)


class QdrantManagerOperationTest(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_an_in_flight_vector_from_the_previous_embedding_profile(self) -> None:
        manager = QdrantManager(
            MemoryStoreConfig(
                collection_name_atoms="atoms",
                embedding_dimension=2,
                embedding_signature="profile-new",
            )
        )
        client = FakeQdrantClient(collections=["atoms"])
        manager._available = True
        manager._client = client
        old_profile = EmbeddingProfile("profile-old", "old", "old", "provider", 2, ("old",))
        new_profile = EmbeddingProfile("profile-new", "new", "new", "provider", 2, ("new",))

        self.assertFalse(
            await manager.upsert_atom_vector(
                "atom-old",
                ProfiledEmbedding([0.1, 0.2], old_profile),
                {},
            )
        )
        self.assertTrue(
            await manager.upsert_atom_vector(
                "atom-new",
                ProfiledEmbedding([0.1, 0.2], new_profile),
                {},
            )
        )
        self.assertEqual(len(client.upserts), 1)
        self.assertEqual(client.upserts[0][1][0].payload["embedding_signature"], "profile-new")

    async def test_upsert_atom_vector_overrides_missing_or_incorrect_payload_atom_id(self) -> None:
        manager = QdrantManager(MemoryStoreConfig(collection_name_atoms="atoms"))
        client = FakeQdrantClient(collections=["atoms"])
        manager._available = True
        manager._client = client

        self.assertTrue(await manager.upsert_atom_vector("atom-empty", [0.1], {"status": "active"}))
        self.assertTrue(
            await manager.upsert_atom_vector(
                "atom-wrong",
                [0.2],
                {"atom_id": "different-atom", "status": "archived"},
            )
        )

        written_points = [call[1][0] for call in client.upserts]
        self.assertEqual(
            [point.payload for point in written_points],
            [
                {"atom_id": "atom-empty", "status": "active"},
                {"atom_id": "atom-wrong", "status": "archived"},
            ],
        )

    async def test_batch_upsert_atom_vectors_overrides_missing_or_incorrect_payload_atom_id(self) -> None:
        manager = QdrantManager(MemoryStoreConfig(collection_name_atoms="atoms"))
        client = FakeQdrantClient(collections=["atoms"])
        manager._available = True
        manager._client = client

        written = await manager.batch_upsert_atom_vectors(
            [
                ("atom-empty", [0.1], {"status": "active"}),
                ("atom-wrong", [0.2], {"atom_id": "different-atom", "status": "archived"}),
            ]
        )

        self.assertEqual(written, 2)
        self.assertEqual(
            [point.payload for point in client.upserts[0][1]],
            [
                {"atom_id": "atom-empty", "status": "active"},
                {"atom_id": "atom-wrong", "status": "archived"},
            ],
        )

    async def test_list_atom_points_preserves_physical_ids_and_only_trusts_matching_business_ids(self) -> None:
        manager = QdrantManager(MemoryStoreConfig(collection_name_atoms="atoms"))
        valid_physical_id = manager._normalize_point_id("atom-valid")
        missing_payload_physical_id = str(uuid.uuid4())
        mismatched_physical_id = manager._normalize_point_id("atom-physical")
        client = FakeQdrantClient(collections=["atoms"])
        client.scroll = Mock(
            side_effect=[
                (
                    [
                        SimpleNamespace(id=valid_physical_id, payload={"atom_id": "atom-valid"}),
                        SimpleNamespace(id=missing_payload_physical_id, payload={}),
                    ],
                    "next-page",
                ),
                (
                    [SimpleNamespace(id=mismatched_physical_id, payload={"atom_id": "atom-payload"})],
                    None,
                ),
            ]
        )
        manager._available = True
        manager._client = client

        atom_points = await manager.list_atom_points()

        self.assertEqual(
            atom_points,
            [
                {"physical_id": valid_physical_id, "business_id": "atom-valid"},
                {"physical_id": missing_payload_physical_id, "business_id": None},
                {"physical_id": mismatched_physical_id, "business_id": None},
            ],
        )
        self.assertEqual(client.scroll.call_count, 2)
        self.assertEqual(client.scroll.call_args_list[1].kwargs["offset"], "next-page")

    async def test_list_atom_ids_scrolls_all_pages_and_uses_business_ids(self) -> None:
        manager = QdrantManager(MemoryStoreConfig(collection_name_atoms="atoms"))
        client = FakeQdrantClient(collections=["atoms"])
        client.scroll = Mock(
            side_effect=[
                (
                    [
                        SimpleNamespace(id=manager._normalize_point_id("atom-a"), payload={"atom_id": "atom-a"}),
                        SimpleNamespace(id=str(uuid.uuid4()), payload={}),
                    ],
                    "next-page",
                ),
                (
                    [
                        SimpleNamespace(
                            id=manager._normalize_point_id("atom-b"),
                            payload={"atom_id": "atom-b"},
                        )
                    ],
                    None,
                ),
            ]
        )
        manager._available = True
        manager._client = client

        atom_ids = await manager.list_atom_ids()

        self.assertEqual(atom_ids, {"atom-a", "atom-b"})
        self.assertEqual(client.scroll.call_count, 2)
        self.assertEqual(client.scroll.call_args_list[1].kwargs["offset"], "next-page")

    async def test_qdrant_manager_init_warns_when_optional_dependency_is_unavailable(self) -> None:
        with patch.object(store_module, "QDRANT_AVAILABLE", False):
            manager = QdrantManager(MemoryStoreConfig())

        self.assertFalse(manager._available)

    async def test_qdrant_initialize_supports_local_server_and_failure_modes(self) -> None:
        manager = QdrantManager(MemoryStoreConfig())
        manager._available = False
        await manager.initialize()
        self.assertIsNone(manager._client)

        local_client = FakeQdrantClient(collections=["memory_atoms", "graph_entries"])
        local = QdrantManager(MemoryStoreConfig(qdrant_local_path="/tmp/qdrant-local"))
        local._available = True
        with patch.object(store_module, "_QdrantClient", Mock(return_value=local_client)) as client_cls:
            await local.initialize()
        client_cls.assert_called_once_with(path="/tmp/qdrant-local")
        self.assertIs(local._client, local_client)

        server_client = FakeQdrantClient(collections=["atoms", "graphs"])
        server = QdrantManager(
            MemoryStoreConfig(
                qdrant_url="http://qdrant.example",
                qdrant_api_key="secret",
                collection_name_atoms="atoms",
                collection_name_graph="graphs",
            )
        )
        server._available = True
        with patch.object(store_module, "_QdrantClient", Mock(return_value=server_client)) as client_cls:
            await server.initialize()
        client_cls.assert_called_once_with(url="http://qdrant.example", api_key="secret")
        self.assertIs(server._client, server_client)

        failing = QdrantManager(MemoryStoreConfig())
        failing._available = True
        with patch.object(store_module, "_QdrantClient", Mock(side_effect=RuntimeError("connect failed"))):
            await failing.initialize()
        self.assertIsNone(failing._client)

    async def test_ensure_collection_validates_existing_collections_and_handles_creation_errors(self) -> None:
        manager = QdrantManager(MemoryStoreConfig(embedding_dimension=1024))
        manager._available = True
        existing = FakeQdrantClient(collections=["atoms"], vector_size=1024)
        manager._client = existing
        await manager._ensure_collection("atoms", [{"name": "status", "type": "keyword"}])
        self.assertEqual(existing.created_collections, [])

        incompatible = QdrantManager(MemoryStoreConfig(embedding_dimension=1024))
        incompatible._available = True
        incompatible._client = FakeQdrantClient(collections=["atoms"], vector_size=1024)
        with patch.object(incompatible, "_collection_vector_size", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "incompatible"):
                await incompatible._ensure_collection("atoms", [])

        mismatched = QdrantManager(MemoryStoreConfig(embedding_dimension=256))
        mismatched._available = True
        mismatched._client = FakeQdrantClient(collections=["atoms"], vector_size=128)
        with self.assertRaisesRegex(RuntimeError, "vector size"):
            await mismatched._ensure_collection("atoms", [])

        fallback_create = QdrantManager(MemoryStoreConfig())
        fallback_create._available = True
        fallback_create._client = FakeQdrantClient(fail={"get_collections"})
        await fallback_create._ensure_collection("atoms", [{"name": "status", "type": "keyword"}])
        self.assertEqual(fallback_create._client.created_collections[0][0], "atoms")

        create_fails = QdrantManager(MemoryStoreConfig())
        create_fails._available = True
        create_fails._client = FakeQdrantClient(fail={"create_collection"})
        await create_fails._ensure_collection("atoms", [{"name": "status", "type": "keyword"}])
        self.assertEqual(create_fails._client.created_collections, [])

    async def test_qdrant_manager_degrades_without_client_or_optional_dependency(self) -> None:
        manager = QdrantManager(MemoryStoreConfig())
        manager._available = False

        self.assertTrue(await manager.upsert_atom_vector("a", [0.1], {}))
        self.assertTrue(await manager.upsert_graph_vector("g", [0.1], {}))
        self.assertEqual(await manager.batch_upsert_atom_vectors([("a", [0.1], {})]), 1)
        self.assertEqual(await manager.search_similar_atoms([0.1]), [])
        self.assertEqual(await manager.search_similar_graph_entries([0.1]), [])
        self.assertTrue(await manager.delete_atom_vector("a"))
        self.assertTrue(await manager.set_atom_payload("a", {"status": "active"}))
        self.assertTrue(await manager.delete_graph_vector("g"))

        manager._available = True
        manager._client = None
        self.assertFalse(await manager.upsert_atom_vector("a", [0.1], {}))
        self.assertFalse(await manager.upsert_graph_vector("g", [0.1], {}))
        self.assertEqual(await manager.batch_upsert_atom_vectors([("a", [0.1], {})]), 0)
        self.assertEqual(await manager.search_similar_graph_entries([0.1]), [])
        self.assertFalse(await manager.delete_atom_vector("a"))
        self.assertFalse(await manager.set_atom_payload("a", {"status": "active"}))
        self.assertFalse(await manager.delete_graph_vector("g"))
        self.assertIsNone(await manager.collection_info("memory_atoms"))
        self.assertFalse(await manager.delete_collection("memory_atoms"))

    async def test_qdrant_manager_covers_early_returns_and_empty_filters(self) -> None:
        unavailable = QdrantManager(MemoryStoreConfig())
        unavailable._available = False
        await unavailable.initialize()
        self.assertIsNone(unavailable._client)

        manager = QdrantManager(MemoryStoreConfig())
        manager._available = True
        manager._client = None
        await manager.close()
        self.assertIsNone(manager._client)
        await manager._ensure_collection("atoms", [])
        self.assertIsNone(QdrantManager._build_filter({"status": []}, [{"name": "status", "type": "keyword"}]))

    async def test_qdrant_manager_crud_search_collection_and_failure_paths(self) -> None:
        config = MemoryStoreConfig(collection_name_atoms="atoms", collection_name_graph="graphs")
        manager = QdrantManager(config)
        hit = SimpleNamespace(id=123, score=0.75, payload={"atom_id": "a"})
        client = FakeQdrantClient(hits=[hit])
        manager._available = True
        manager._client = client

        await manager._ensure_collection("atoms", [{"name": "status", "type": "keyword"}])
        self.assertEqual(client.created_collections[0][0], "atoms")
        self.assertEqual(client.payload_indexes, [("atoms", "status", "keyword")])

        self.assertTrue(await manager.upsert_atom_vector("atom-1", [0.1, 0.2], {"status": "active"}))
        self.assertTrue(await manager.upsert_graph_vector("graph-1", [0.3], {"subject": "s"}))
        self.assertEqual(await manager.batch_upsert_atom_vectors([("a", [0.1], {}), ("b", [0.2], {})]), 2)
        self.assertEqual(
            await manager.search_similar_atoms([0.1], filters={"status": "active", "keyword": "ignored"}, limit=4),
            [{"id": "123", "score": 0.75, "payload": {"atom_id": "a"}}],
        )
        self.assertEqual(
            await manager.search_similar_graph_entries([0.2], limit=1),
            [{"id": "123", "score": 0.75, "payload": {"atom_id": "a"}}],
        )
        self.assertTrue(await manager.delete_atom_vector("atom-1"))
        self.assertTrue(await manager.delete_graph_vector("graph-1"))
        self.assertTrue(await manager.set_atom_payload("atom-1", {"weight": 0.8}))
        self.assertEqual(
            await manager.collection_info("atoms"), {"name": "atoms", "vectors_count": 7, "status": "green"}
        )
        self.assertTrue(await manager.delete_collection("graphs"))
        self.assertEqual(client.upserts[0][0], "atoms")
        self.assertEqual(client.upserts[1][0], "graphs")
        self.assertEqual(client.set_payload_calls[0][1], {"weight": 0.8})
        self.assertEqual(client.deleted_collections, ["graphs"])

        failing = QdrantManager(config)
        failing._available = True
        failing._client = FakeQdrantClient(
            fail={"upsert", "search", "delete", "set_payload", "get_collection", "delete_collection"}
        )
        self.assertFalse(await failing.upsert_atom_vector("a", [0.1], {}))
        self.assertFalse(await failing.upsert_graph_vector("g", [0.1], {}))
        self.assertEqual(await failing.batch_upsert_atom_vectors([("a", [0.1], {})]), 0)
        self.assertEqual(await failing.search_similar_atoms([0.1]), [])
        self.assertEqual(await failing.search_similar_graph_entries([0.1]), [])
        self.assertFalse(await failing.delete_atom_vector("a"))
        self.assertFalse(await failing.delete_graph_vector("g"))
        self.assertFalse(await failing.set_atom_payload("a", {"weight": 1.0}))
        self.assertIsNone(await failing.collection_info("atoms"))
        self.assertFalse(await failing.delete_collection("graphs"))

    async def test_set_atom_payload_treats_missing_local_point_as_recoverable_drift(self) -> None:
        manager = QdrantManager(MemoryStoreConfig(collection_name_atoms="atoms"))
        client = FakeQdrantClient(collections=["atoms"])
        client.set_payload = Mock(side_effect=KeyError("missing-point"))
        manager._available = True
        manager._client = client

        with (
            patch.object(store_module.logger, "debug") as debug_log,
            patch.object(store_module.logger, "exception") as exception_log,
        ):
            updated = await manager.set_atom_payload("missing-point", {"weight": 0.4})

        self.assertFalse(updated)
        debug_log.assert_called_once()
        exception_log.assert_not_called()


class MemoryStoreCrudTest(MemoryDatabaseFixtureMixin, unittest.IsolatedAsyncioTestCase):
    def make_store(self) -> MemoryStore:
        store = MemoryStore(MemoryStoreConfig(sqlite_path=str(self.db_path)))
        store.qdrant = SimpleNamespace(
            _client=object(),
            initialize=AsyncMock(),
            close=AsyncMock(),
            delete_atom_vector=AsyncMock(return_value=True),
            set_atom_payload=AsyncMock(return_value=True),
            search_similar_atoms=AsyncMock(return_value=[{"id": "vector-hit"}]),
            collection_info=AsyncMock(return_value={"name": "memory_atoms", "vectors_count": 1, "status": "green"}),
        )
        return store

    async def test_list_atom_ids_returns_filtered_persisted_ids(self) -> None:
        store = self.make_store()
        create_atom("active-atom", status="active")
        create_atom("archived-atom", status="archived")

        self.assertEqual(await store.list_atom_ids(status="active"), {"active-atom"})
        self.assertEqual(await store.list_atom_ids(), {"active-atom", "archived-atom"})
        self.assertEqual(
            await store.list_atom_source_hashes(status="active"),
            {"active-atom": embedding_source_hash("active-atom 内容")},
        )

    async def test_singleton_initialize_close_and_statistics(self) -> None:
        with self.assertRaises(RuntimeError):
            MemoryStore.get_instance()

        store = self.make_store()
        create_atom("active-factual")
        create_atom("archived-pref", atom_type="preference", status="archived")

        await store.initialize()
        self.assertIs(store, MemoryStore(MemoryStoreConfig(sqlite_path=str(self.db_path))))
        self.assertTrue(store._initialized)
        stats = await store.get_statistics()
        instance = MemoryStore.get_instance()
        await store.close()

        self.assertIs(instance, store)
        self.assertFalse(store._initialized)
        self.assertEqual(stats["total_atoms"], 2)
        self.assertEqual(stats["active_atoms"], 1)
        self.assertEqual(stats["type_distribution"], {"factual": 1, "preference": 1})
        self.assertEqual(stats["qdrant_atoms_collection"]["vectors_count"], 1)
        store.qdrant.initialize.assert_awaited_once()
        store.qdrant.close.assert_awaited_once()
        self.assertIsNone(MemoryStore._instance)

    async def test_close_skips_closed_database_and_empty_batch_get_returns_empty(self) -> None:
        store = self.make_store()
        if not memory_db.is_closed():
            memory_db.close()

        await store.close()

        self.assertEqual(await store.get_atoms_batch([]), {})

    async def test_close_closes_open_database(self) -> None:
        store = self.make_store()

        with (
            patch.object(store_module.memory_db, "is_closed", return_value=False),
            patch.object(store_module.memory_db, "close") as close,
        ):
            await store.close()

        close.assert_called_once()

    async def test_atom_crud_batch_list_search_and_json_datetime_conversion(self) -> None:
        store = self.make_store()
        atom_id = await store.insert_atom(
            {
                "atom_id": "inserted",
                "atom_type": "factual",
                "content": "小明喜欢爵士乐",
                "entities": ["user-1", {"id": "friend"}],
                "created_at": 123.0,
                "last_accessed_at": "124",
                "last_reinforced_at": datetime.datetime.fromtimestamp(125.0),
                "source_scene": "group_chat",
                "source_id": "stream-1",
            }
        )
        create_atom("older", created_at=datetime.datetime.fromtimestamp(10.0))
        create_atom("bad-json", entities="not-json", created_at=datetime.datetime.fromtimestamp(200.0))

        update_payload = {"entities": {"id": "user-2"}, "last_accessed_at": "bad"}
        batch_updates = [
            ("inserted", {"weight": 0.9, "entities": ["user-3"], "last_reinforced_at": 130.0}),
            ("older", {"status": "archived"}),
            ("missing", {"weight": 0.1}),
        ]
        expected_update_payload = {"entities": {"id": "user-2"}, "last_accessed_at": "bad"}
        expected_batch_updates = [
            ("inserted", {"weight": 0.9, "entities": ["user-3"], "last_reinforced_at": 130.0}),
            ("older", {"status": "archived"}),
            ("missing", {"weight": 0.1}),
        ]

        updated = await store.update_atom("inserted", update_payload)
        missing_update = await store.update_atom("missing", {"weight": 0.9})
        batch_count = await store.update_atoms_batch(batch_updates)
        empty_batch_count = await store.update_atoms_batch([])
        fetched = await store.get_atom("inserted")
        missing = await store.get_atom("missing")
        batch = await store.get_atoms_batch(["inserted", "older", "missing"])
        active_factual = await store.list_atoms(atom_type="factual", status="active", limit=5)
        offset_rows = await store.list_atoms(limit=1, offset=1)
        vector_results = await store.search_similar([0.1], filters={"status": "active"}, limit=3)
        rebuild_count = await store.rebuild_qdrant_index()

        self.assertEqual(atom_id, "inserted")
        row = MemoryAtom.get_by_id("inserted")
        self.assertEqual(json.loads(row.entities), ["user-3"])
        self.assertTrue(updated)
        self.assertEqual(update_payload, expected_update_payload)
        self.assertEqual(batch_updates, expected_batch_updates)
        self.assertFalse(missing_update)
        self.assertEqual(batch_count, 2)
        self.assertEqual(empty_batch_count, 0)
        self.assertEqual(fetched["entities"], ["user-3"])
        self.assertIsNone(missing)
        self.assertEqual(set(batch), {"inserted", "older"})
        self.assertEqual([atom["atom_id"] for atom in active_factual], ["bad-json", "inserted"])
        self.assertEqual(offset_rows[0]["atom_id"], "inserted")
        self.assertEqual(store._atom_to_dict(MemoryAtom.get_by_id("bad-json"))["entities"], "not-json")
        self.assertEqual(vector_results, [{"id": "vector-hit"}])
        store.qdrant.search_similar_atoms.assert_awaited_once_with([0.1], {"status": "active"}, 3)
        self.assertEqual(rebuild_count, 0)

    async def test_delete_archive_and_migrate_atom_update_related_rows_and_qdrant_payloads(self) -> None:
        store = self.make_store()
        create_atom("delete-me")
        create_atom("archive-me", content="需要归档的事实", atom_type="preference")
        create_atom("migrate-me", atom_type="episodic")
        EpisodicDetail.create(id="delete-me", atom="delete-me")
        SemanticDetail.create(id="delete-me", atom="delete-me", attr_category="general", attr_name="n", attr_value="v")
        MemoryTraceChain.create(atom_id="delete-me", step_number=1, agent_name="agent", operation_type="write")
        ConflictObservation.create(
            atom_a_id="delete-me",
            atom_b_id="other",
            conflict_type="value",
            description="conflict",
        )
        AtomAssociationModel.create(atom_a_id="delete-me", atom_b_id="other", association_type="co_occurrence")

        self.assertFalse(await store.delete_atom("missing"))
        self.assertTrue(await store.delete_atom("delete-me"))
        self.assertFalse(MemoryAtom.select().where(MemoryAtom.atom_id == "delete-me").exists())
        self.assertFalse(EpisodicDetail.select().where(EpisodicDetail.atom == "delete-me").exists())
        self.assertFalse(SemanticDetail.select().where(SemanticDetail.atom == "delete-me").exists())
        self.assertFalse(MemoryTraceChain.select().where(MemoryTraceChain.atom_id == "delete-me").exists())
        self.assertFalse(ConflictObservation.select().where(ConflictObservation.atom_a_id == "delete-me").exists())
        self.assertFalse(AtomAssociationModel.select().where(AtomAssociationModel.atom_a_id == "delete-me").exists())

        self.assertFalse(await store.archive_atom("missing"))
        self.assertTrue(await store.archive_atom("archive-me"))
        archived = MemoryAtom.get_by_id("archive-me")
        archive_row = RawMessageArchive.get(RawMessageArchive.message_id == "archive-me")
        self.assertEqual(archived.status, "archived")
        self.assertEqual(json.loads(archive_row.content)["content"], "需要归档的事实")

        self.assertFalse(await store.migrate_atom("migrate-me", ""))
        self.assertTrue(await store.migrate_atom("migrate-me", "planned"))
        self.assertFalse(await store.migrate_atom("missing", "factual"))
        self.assertEqual(MemoryAtom.get_by_id("migrate-me").atom_type, "planned")
        self.assertEqual(
            [call.args[0] for call in store.qdrant.delete_atom_vector.await_args_list],
            ["delete-me", "archive-me"],
        )
        store.qdrant.set_atom_payload.assert_awaited_once_with("migrate-me", {"atom_type": "planned"})

    async def test_crud_failure_paths_return_false_or_empty_results(self) -> None:
        store = self.make_store()

        with patch.object(store_module.MemoryAtom, "create", side_effect=RuntimeError("insert failed")):
            with self.assertRaisesRegex(RuntimeError, "insert failed"):
                await store.insert_atom({"atom_id": "bad-insert", "atom_type": "factual", "content": "bad"})

        with patch.object(store_module.MemoryAtom, "update", side_effect=RuntimeError("update failed")):
            self.assertFalse(await store.update_atom("atom-1", {"weight": 0.9}))
            self.assertEqual(await store.update_atoms_batch([("atom-1", {"weight": 0.9})]), 0)
            self.assertFalse(await store.migrate_atom("atom-1", "planned"))

        with patch.object(store_module.MemoryAtom, "delete", side_effect=RuntimeError("delete failed")):
            self.assertFalse(await store.delete_atom("atom-1"))

        with patch.object(store_module.MemoryAtom, "get_or_none", side_effect=RuntimeError("get failed")):
            self.assertFalse(await store.archive_atom("atom-1"))
            self.assertIsNone(await store.get_atom("atom-1"))

        with patch.object(store_module.MemoryAtom, "select", side_effect=RuntimeError("select failed")):
            self.assertEqual(await store.get_atoms_batch(["atom-1"]), {})
            self.assertEqual(await store.list_atoms(), [])
            stats = await store.get_statistics()

        self.assertIn("select failed", stats["error"])

    async def test_archive_atom_handles_write_failure_after_existing_atom_lookup(self) -> None:
        store = self.make_store()
        create_atom("archive-fails")

        with patch.object(store_module.RawMessageArchive, "create", side_effect=RuntimeError("archive write failed")):
            self.assertFalse(await store.archive_atom("archive-fails"))

    async def test_search_similar_logs_empty_result(self) -> None:
        store = self.make_store()
        store.qdrant.search_similar_atoms = AsyncMock(return_value=[])

        self.assertEqual(await store.search_similar([0.1], limit=1), [])


if __name__ == "__main__":
    unittest.main()
