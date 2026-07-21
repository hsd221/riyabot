import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.memory import store as store_module
from src.memory.schema import VectorIndexState, configure_memory_database, initialize_database, memory_db
from src.memory.store import MemoryStoreConfig, QdrantManager


class AliasQdrantClient:
    def __init__(
        self,
        collections: dict[str, int],
        aliases: dict[str, str] | None = None,
        point_counts: dict[str, int] | None = None,
    ) -> None:
        self.collections = dict(collections)
        self.aliases = dict(aliases or {})
        self.point_counts = dict(point_counts or {})
        self.created_collections: list[tuple[str, int]] = []
        self.upserts: list[tuple[str, list[object]]] = []
        self.deleted_points: list[tuple[str, object]] = []
        self.payload_updates: list[tuple[str, dict[str, object], list[object]]] = []
        self.alias_updates: list[list[object]] = []
        self.search_calls: list[dict[str, object]] = []

    def get_collections(self) -> SimpleNamespace:
        return SimpleNamespace(collections=[SimpleNamespace(name=name) for name in self.collections])

    def get_aliases(self) -> SimpleNamespace:
        return SimpleNamespace(
            aliases=[
                SimpleNamespace(alias_name=alias, collection_name=collection)
                for alias, collection in self.aliases.items()
            ]
        )

    def get_collection(self, collection_name: str) -> SimpleNamespace:
        physical_name = self.aliases.get(collection_name, collection_name)
        return SimpleNamespace(
            points_count=self.point_counts.get(physical_name, 0),
            status="green",
            config=SimpleNamespace(
                params=SimpleNamespace(vectors=SimpleNamespace(size=self.collections[physical_name]))
            ),
        )

    def create_collection(self, collection_name: str, vectors_config: object) -> None:
        size = int(vectors_config.size)
        self.collections[collection_name] = size
        self.point_counts[collection_name] = 0
        self.created_collections.append((collection_name, size))

    def create_payload_index(self, **kwargs) -> None:
        del kwargs

    def update_collection_aliases(self, change_aliases_operations: list[object]) -> bool:
        self.alias_updates.append(change_aliases_operations)
        for operation in change_aliases_operations:
            delete_alias = getattr(operation, "delete_alias", None)
            create_alias = getattr(operation, "create_alias", None)
            if delete_alias is not None:
                self.aliases.pop(delete_alias.alias_name, None)
            if create_alias is not None:
                self.aliases[create_alias.alias_name] = create_alias.collection_name
        return True

    def upsert(self, collection_name: str, points: list[object]) -> None:
        self.upserts.append((collection_name, points))

    def delete(self, collection_name: str, points_selector: object) -> None:
        self.deleted_points.append((collection_name, points_selector))

    def set_payload(self, collection_name: str, payload: dict[str, object], points: list[object]) -> None:
        self.payload_updates.append((collection_name, payload, points))

    def search(self, **kwargs) -> list[object]:
        self.search_calls.append(kwargs)
        return []


class VectorMigrationManagerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.original_path = memory_db.database
        self.addCleanup(lambda: configure_memory_database(str(self.original_path)))
        configure_memory_database(str(Path(self.temp_dir.name) / "memory.db"))
        initialize_database()

    async def test_signature_change_creates_target_and_disables_reads_until_activation(self) -> None:
        client = AliasQdrantClient(
            {"memory_atoms": 1024, "graph_entries": 1024}, {"memory_atoms__active": "memory_atoms"}
        )
        config = MemoryStoreConfig(
            embedding_dimension=1536,
            embedding_signature="new-signature",
            qdrant_local_path=str(Path(self.temp_dir.name) / "qdrant"),
        )
        manager = QdrantManager(config)
        manager._available = True
        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await manager.initialize()

        self.assertTrue(manager.atom_migration_pending)
        self.assertFalse(manager.vector_search_enabled)
        self.assertIsNotNone(manager.atom_migration_target)
        self.assertEqual(client.aliases["memory_atoms__active"], "memory_atoms")
        self.assertEqual(client.created_collections[0][1], 1536)

        await manager.upsert_atom_vector("atom-1", [0.1, 0.2], {"atom_id": "atom-1"})
        self.assertEqual(client.upserts[-1][0], manager.atom_migration_target)

        self.assertEqual(await manager.search_similar_atoms([0.1, 0.2]), [])
        self.assertEqual(client.search_calls, [])

    async def test_runtime_reconfigure_prepares_new_targets_without_aliasing_old_vectors(self) -> None:
        client = AliasQdrantClient(
            {"memory_atoms": 1024, "graph_entries": 1024},
            {"memory_atoms__active": "memory_atoms", "graph_entries__active": "graph_entries"},
        )
        manager = QdrantManager(
            MemoryStoreConfig(
                embedding_dimension=1024,
                embedding_signature="old-signature",
                qdrant_local_path=str(Path(self.temp_dir.name) / "qdrant"),
            )
        )
        manager._available = True
        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await manager.initialize()

        profile = SimpleNamespace(signature="new-signature", model_name="new-model", dimension=1536)
        self.assertTrue(await manager.reconfigure_embedding(profile))

        self.assertEqual(manager.config.embedding_signature, "new-signature")
        self.assertEqual(manager.config.embedding_dimension, 1536)
        self.assertTrue(manager.atom_migration_pending)
        self.assertTrue(manager.graph_migration_pending)
        self.assertFalse(manager.vector_search_enabled)
        self.assertFalse(manager.graph_search_enabled)
        self.assertEqual(
            client.collections[manager.atom_migration_target],
            1536,
        )
        self.assertEqual(
            client.collections[manager.graph_migration_target],
            1536,
        )

    async def test_runtime_reconfigure_failure_restores_the_previous_in_memory_state(self) -> None:
        manager = QdrantManager(
            MemoryStoreConfig(
                embedding_dimension=1024,
                embedding_signature=None,
                embedding_model_name="old-model",
            )
        )
        manager._available = True
        manager._client = SimpleNamespace(update_collection_aliases=object(), get_aliases=object())
        manager._active_atoms_collection = "atoms-old"
        manager._active_graph_collection = "graph-old"

        async def mutate_atoms_then_succeed() -> None:
            manager._active_atoms_collection = "atoms-new"
            manager._atom_migration_target = "atoms-target-new"

        async def mutate_graph_then_fail() -> None:
            manager._active_graph_collection = "graph-new"
            manager._graph_migration_target = "graph-target-new"
            raise RuntimeError("graph setup failed")

        profile = SimpleNamespace(signature="new-signature", model_name="new-model", dimension=1536)
        with (
            patch.object(manager, "_initialize_versioned_atoms", new=AsyncMock(side_effect=mutate_atoms_then_succeed)),
            patch.object(
                manager,
                "_initialize_graph_collection",
                new=AsyncMock(side_effect=mutate_graph_then_fail),
            ),
        ):
            reconfigured = await manager.reconfigure_embedding(profile)

        self.assertFalse(reconfigured)
        self.assertIsNone(manager.config.embedding_signature)
        self.assertEqual(manager.config.embedding_dimension, 1024)
        self.assertEqual(manager.config.embedding_model_name, "old-model")
        self.assertEqual(manager._active_atoms_collection, "atoms-old")
        self.assertEqual(manager._active_graph_collection, "graph-old")
        self.assertIsNone(manager.atom_migration_target)
        self.assertIsNone(manager.graph_migration_target)
        self.assertTrue(manager._embedding_operations_enabled)

    async def test_graph_signature_change_creates_target_and_disables_graph_reads(self) -> None:
        VectorIndexState.create(
            index_name="graph_entries",
            active_signature="old-signature",
            active_dimension=1024,
            active_collection="graph_entries",
            status="ready",
        )
        client = AliasQdrantClient(
            {"memory_atoms": 1024, "graph_entries": 1024},
            {
                "memory_atoms__active": "memory_atoms",
                "graph_entries__active": "graph_entries",
            },
        )
        manager = QdrantManager(
            MemoryStoreConfig(
                embedding_dimension=1024,
                embedding_signature="new-signature",
                qdrant_local_path=str(Path(self.temp_dir.name) / "qdrant"),
            )
        )
        manager._available = True

        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await manager.initialize()

        self.assertTrue(manager.graph_migration_pending)
        self.assertFalse(manager.graph_search_enabled)
        self.assertEqual(client.aliases["graph_entries__active"], "graph_entries")
        self.assertIsNotNone(manager.graph_migration_target)
        self.assertIn(manager.graph_migration_target, client.collections)
        self.assertEqual(await manager.search_similar_graph_entries([0.1, 0.2]), [])
        self.assertEqual(client.search_calls, [])

    async def test_graph_migration_progress_survives_manager_restart(self) -> None:
        VectorIndexState.create(
            index_name="graph_entries",
            active_signature="old-signature",
            active_dimension=1024,
            active_collection="graph_entries",
            status="ready",
        )
        client = AliasQdrantClient(
            {"memory_atoms": 1024, "graph_entries": 1024},
            {
                "memory_atoms__active": "memory_atoms",
                "graph_entries__active": "graph_entries",
            },
        )
        config = MemoryStoreConfig(
            embedding_dimension=1024,
            embedding_signature="new-signature",
            qdrant_local_path=str(Path(self.temp_dir.name) / "qdrant"),
        )
        manager = QdrantManager(config)
        manager._available = True
        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await manager.initialize()

        target = manager.graph_migration_target
        self.assertIsNotNone(target)
        await manager.mark_graph_migration_progress(
            last_processed_id="7",
            migrated_count=7,
            total_count=11,
        )

        restarted_manager = QdrantManager(config)
        restarted_manager._available = True
        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await restarted_manager.initialize()

        state = restarted_manager.get_graph_migration_state()
        self.assertIsNotNone(state)
        self.assertTrue(restarted_manager.graph_migration_pending)
        self.assertEqual(restarted_manager.graph_migration_target, target)
        self.assertEqual(state.last_processed_id, "7")
        self.assertEqual(state.migrated_count, 7)
        self.assertEqual(state.total_count, 11)

    async def test_graph_delete_covers_active_and_target_during_migration(self) -> None:
        VectorIndexState.create(
            index_name="graph_entries",
            active_signature="old-signature",
            active_dimension=1024,
            active_collection="graph_entries",
            status="ready",
        )
        client = AliasQdrantClient(
            {"memory_atoms": 1024, "graph_entries": 1024},
            {
                "memory_atoms__active": "memory_atoms",
                "graph_entries__active": "graph_entries",
            },
        )
        manager = QdrantManager(
            MemoryStoreConfig(
                embedding_dimension=1024,
                embedding_signature="new-signature",
                qdrant_local_path=str(Path(self.temp_dir.name) / "qdrant"),
            )
        )
        manager._available = True
        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await manager.initialize()

        target = manager.graph_migration_target
        self.assertIsNotNone(target)
        self.assertTrue(await manager.delete_graph_vector("7"))
        self.assertEqual(
            {collection for collection, _selector in client.deleted_points},
            {"graph_entries__active", target},
        )

    async def test_graph_activation_switches_alias_and_reenables_reads(self) -> None:
        VectorIndexState.create(
            index_name="graph_entries",
            active_signature="old-signature",
            active_dimension=1024,
            active_collection="graph_entries",
            status="ready",
        )
        client = AliasQdrantClient(
            {"memory_atoms": 1024, "graph_entries": 1024},
            {
                "memory_atoms__active": "memory_atoms",
                "graph_entries__active": "graph_entries",
            },
        )
        manager = QdrantManager(
            MemoryStoreConfig(
                embedding_dimension=1024,
                embedding_signature="new-signature",
                qdrant_local_path=str(Path(self.temp_dir.name) / "qdrant"),
            )
        )
        manager._available = True
        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await manager.initialize()

        target = manager.graph_migration_target
        self.assertIsNotNone(target)
        self.assertTrue(await manager.activate_graph_migration())
        self.assertEqual(client.aliases["graph_entries__active"], target)
        self.assertFalse(manager.graph_migration_pending)
        self.assertTrue(manager.graph_search_enabled)

        await manager.search_similar_graph_entries([0.1, 0.2])
        self.assertEqual(client.search_calls[-1]["collection_name"], "graph_entries__active")
        state = VectorIndexState.get_by_id("graph_entries")
        self.assertEqual(state.status, "ready")
        self.assertEqual(state.active_collection, target)
        self.assertEqual(state.active_signature, "new-signature")
        self.assertIsNone(state.target_collection)

    async def test_first_upgrade_rebuilds_nonempty_legacy_collection_even_when_dimension_matches(self) -> None:
        client = AliasQdrantClient(
            {"memory_atoms": 1024, "graph_entries": 1024},
            point_counts={"memory_atoms": 3},
        )
        manager = QdrantManager(
            MemoryStoreConfig(
                embedding_dimension=1024,
                embedding_signature="current-signature",
                qdrant_local_path=str(Path(self.temp_dir.name) / "qdrant"),
            )
        )
        manager._available = True

        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await manager.initialize()

        self.assertTrue(manager.atom_migration_pending)
        self.assertFalse(manager.vector_search_enabled)
        self.assertEqual(client.aliases["memory_atoms__active"], "memory_atoms")
        self.assertNotEqual(manager.atom_migration_target, "memory_atoms")
        state = VectorIndexState.get_by_id("memory_atoms")
        self.assertNotEqual(state.active_signature, "current-signature")
        self.assertEqual(state.target_signature, "current-signature")

    async def test_missing_alias_is_restored_from_persisted_active_collection(self) -> None:
        current_collection = QdrantManager._versioned_collection_name("memory_atoms", "current-signature", 1024)
        VectorIndexState.create(
            index_name="memory_atoms",
            active_signature="current-signature",
            active_dimension=1024,
            active_collection=current_collection,
            status="ready",
        )
        client = AliasQdrantClient(
            {
                "memory_atoms": 1024,
                current_collection: 1024,
                "graph_entries": 1024,
            }
        )
        manager = QdrantManager(
            MemoryStoreConfig(
                embedding_dimension=1024,
                embedding_signature="current-signature",
                qdrant_local_path=str(Path(self.temp_dir.name) / "qdrant"),
            )
        )
        manager._available = True

        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await manager.initialize()

        self.assertEqual(client.aliases["memory_atoms__active"], current_collection)
        self.assertFalse(manager.atom_migration_pending)
        self.assertTrue(manager.vector_search_enabled)

    async def test_physical_dimension_mismatch_overrides_stale_persisted_state(self) -> None:
        VectorIndexState.create(
            index_name="memory_atoms",
            active_signature="current-signature",
            active_dimension=1024,
            active_collection="memory_atoms",
            status="ready",
        )
        client = AliasQdrantClient(
            {"memory_atoms": 1536, "graph_entries": 1024},
            {
                "memory_atoms__active": "memory_atoms",
                "graph_entries__active": "graph_entries",
            },
        )
        manager = QdrantManager(
            MemoryStoreConfig(
                embedding_dimension=1024,
                embedding_signature="current-signature",
                qdrant_local_path=str(Path(self.temp_dir.name) / "qdrant"),
            )
        )
        manager._available = True

        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await manager.initialize()

        self.assertTrue(manager.atom_migration_pending)
        self.assertFalse(manager.vector_search_enabled)
        target = manager.atom_migration_target
        self.assertIsNotNone(target)
        self.assertEqual(client.collections[target], 1024)
        state = VectorIndexState.get_by_id("memory_atoms")
        self.assertEqual(state.active_dimension, 1536)
        self.assertEqual(state.active_signature, "legacy-unknown")
        self.assertEqual(state.target_dimension, 1024)

    async def test_restart_recovers_alias_switch_completed_before_state_save(self) -> None:
        target_collection = QdrantManager._versioned_collection_name("memory_atoms", "new-signature", 1536)
        VectorIndexState.create(
            index_name="memory_atoms",
            active_signature="old-signature",
            active_dimension=1024,
            active_collection="memory_atoms",
            target_signature="new-signature",
            target_dimension=1536,
            target_collection=target_collection,
            status="migrating",
        )
        client = AliasQdrantClient(
            {
                "memory_atoms": 1024,
                target_collection: 1536,
                "graph_entries": 1536,
            },
            {"memory_atoms__active": target_collection},
        )
        manager = QdrantManager(
            MemoryStoreConfig(
                embedding_dimension=1536,
                embedding_signature="new-signature",
                qdrant_local_path=str(Path(self.temp_dir.name) / "qdrant"),
            )
        )
        manager._available = True

        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await manager.initialize()

        self.assertFalse(manager.atom_migration_pending)
        self.assertTrue(manager.vector_search_enabled)
        state = VectorIndexState.get_by_id("memory_atoms")
        self.assertEqual(state.status, "ready")
        self.assertEqual(state.active_collection, target_collection)
        self.assertEqual(state.active_signature, "new-signature")
        self.assertIsNone(state.target_collection)

    async def test_delete_and_payload_updates_cover_active_and_target_during_migration(self) -> None:
        client = AliasQdrantClient(
            {"memory_atoms": 1024, "graph_entries": 1024},
            {"memory_atoms__active": "memory_atoms"},
        )
        manager = QdrantManager(
            MemoryStoreConfig(
                embedding_dimension=1536,
                embedding_signature="new-signature",
                qdrant_local_path=str(Path(self.temp_dir.name) / "qdrant"),
            )
        )
        manager._available = True
        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await manager.initialize()

        target = manager.atom_migration_target
        self.assertIsNotNone(target)
        self.assertTrue(await manager.delete_atom_vector("atom-1"))
        self.assertTrue(await manager.set_atom_payload("atom-1", {"weight": 0.8}))

        self.assertEqual(
            {collection for collection, _selector in client.deleted_points},
            {"memory_atoms__active", target},
        )
        self.assertEqual(
            {collection for collection, _payload, _points in client.payload_updates},
            {"memory_atoms__active", target},
        )

    async def test_migration_progress_is_persisted_for_restart_resume(self) -> None:
        client = AliasQdrantClient(
            {"memory_atoms": 1024, "graph_entries": 1024},
            {"memory_atoms__active": "memory_atoms"},
        )
        manager = QdrantManager(
            MemoryStoreConfig(
                embedding_dimension=1536,
                embedding_signature="new-signature",
                qdrant_local_path=str(Path(self.temp_dir.name) / "qdrant"),
            )
        )
        manager._available = True
        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await manager.initialize()

        await manager.mark_atom_migration_progress(
            last_processed_id="atom-7",
            migrated_count=7,
            total_count=11,
        )

        state = VectorIndexState.get_by_id("memory_atoms")
        self.assertEqual(state.status, "migrating")
        self.assertEqual(state.last_processed_id, "atom-7")
        self.assertEqual(state.migrated_count, 7)
        self.assertEqual(state.total_count, 11)

    async def test_activation_switches_alias_and_reenables_reads(self) -> None:
        client = AliasQdrantClient(
            {"memory_atoms": 1024, "graph_entries": 1024}, {"memory_atoms__active": "memory_atoms"}
        )
        config = MemoryStoreConfig(
            embedding_dimension=1536,
            embedding_signature="new-signature",
            qdrant_local_path=str(Path(self.temp_dir.name) / "qdrant"),
        )
        manager = QdrantManager(config)
        manager._available = True
        with patch.object(store_module, "_QdrantClient", Mock(return_value=client)):
            await manager.initialize()

        target = manager.atom_migration_target
        self.assertIsNotNone(target)
        self.assertTrue(await manager.activate_atom_migration())
        self.assertEqual(client.aliases["memory_atoms__active"], target)
        self.assertFalse(manager.atom_migration_pending)
        self.assertTrue(manager.vector_search_enabled)
        state = VectorIndexState.get_by_id("memory_atoms")
        self.assertEqual(state.status, "ready")
        self.assertEqual(state.active_signature, "new-signature")
        self.assertEqual(state.active_dimension, 1536)
        self.assertEqual(state.active_collection, target)
        self.assertIsNone(state.target_collection)


if __name__ == "__main__":
    unittest.main()
