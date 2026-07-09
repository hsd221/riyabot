import datetime
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.memory.atom_association import AssociationType, AtomAssociationStore
from src.memory.graph_store import GraphStore
from src.memory.schema import (
    AtomAssociationModel,
    GraphEdge,
    GraphEntry,
    GraphNode,
    configure_memory_database,
    initialize_database,
    memory_db,
)


class MemoryGraphDatabaseFixtureMixin:
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


class AtomAssociationStoreTest(MemoryGraphDatabaseFixtureMixin, unittest.TestCase):
    def test_add_get_delete_normalizes_pairs_and_reinforces_existing_edges(self) -> None:
        store = AtomAssociationStore()

        store.add_association("atom-b", "atom-a", AssociationType.CO_OCCURRENCE, 0.4)
        store.add_association("atom-a", "atom-b", AssociationType.CO_OCCURRENCE, 0.99)

        rows = list(AtomAssociationModel.select())
        associations = store.get_associations("atom-a")

        self.assertEqual(store.count(), 1)
        self.assertEqual(rows[0].atom_a_id, "atom-a")
        self.assertEqual(rows[0].atom_b_id, "atom-b")
        self.assertEqual(rows[0].evidence_count, 2)
        self.assertAlmostEqual(rows[0].weight, 0.46)
        self.assertEqual(associations[0]["association_type"], "co_occurrence")
        self.assertIsNotNone(associations[0]["created_at"])
        self.assertTrue(store.delete_association("atom-b", "atom-a", AssociationType.CO_OCCURRENCE))
        self.assertFalse(store.delete_association("atom-b", "atom-a", AssociationType.CO_OCCURRENCE))
        self.assertEqual(store.count(), 0)

    def test_build_from_batch_applies_co_occurrence_causal_and_sequential_rules_then_prunes(self) -> None:
        store = AtomAssociationStore()
        atoms = [
            SimpleNamespace(atom_id="atom-a", entities=["小明", "爵士乐"], created_at=100.0),
            SimpleNamespace(atom_id="atom-b", entities=["小明", "爵士乐", "夜宵"], created_at=130.0),
            SimpleNamespace(atom_id="atom-c", entities=["无关"], created_at=datetime.datetime.fromtimestamp(100.0)),
        ]

        created = store.build_from_batch(
            atoms,
            stream_map={"atom-a": "stream-1", "atom-b": "stream-1", "atom-c": "stream-2"},
        )
        rows = list(AtomAssociationModel.select())

        self.assertEqual(created, 3)
        self.assertEqual(store.count(), 3)
        self.assertEqual({row.association_type for row in rows}, {"co_occurrence", "causal", "sequential"})
        self.assertEqual(store._resolve_ts(datetime.datetime.fromtimestamp(5.0)), 5.0)
        self.assertIsNone(store._resolve_ts("not-a-time"))

        chain = store.get_chain("atom-a", max_depth=2)
        self.assertEqual({item["atom_id"] for item in chain}, {"atom-b"})
        self.assertEqual(store.prune_weak(threshold=0.5), 1)
        self.assertEqual(store.count(), 2)

    def test_store_failures_return_safe_defaults(self) -> None:
        store = AtomAssociationStore()

        with patch("src.memory.atom_association.AtomAssociationModel.select", side_effect=RuntimeError("boom")):
            self.assertEqual(store.get_associations("atom-a"), [])
            self.assertEqual(store.get_chain("atom-a"), [])
            self.assertEqual(store.count(), 0)

        with patch("src.memory.atom_association.AtomAssociationModel.delete", side_effect=RuntimeError("boom")):
            self.assertFalse(store.delete_association("atom-a", "atom-b", AssociationType.SEQUENTIAL))
            self.assertEqual(store.prune_weak(), 0)


class GraphStoreTest(MemoryGraphDatabaseFixtureMixin, unittest.TestCase):
    def test_node_edge_entry_crud_and_searches(self) -> None:
        store = GraphStore()

        alice_id = store.add_node("person", "Alice", {"alias": "小明"})
        jazz_id = store.find_or_create_node("topic", "Jazz")
        duplicate_jazz_id = store.find_or_create_node("topic", "Jazz")
        edge_id = store.add_edge(alice_id, jazz_id, "likes", confidence=0.9)
        entry_id = store.add_entry("Alice", "likes", "Jazz", evidence="Alice said so", confidence=0.8)

        self.assertEqual(duplicate_jazz_id, jazz_id)
        self.assertEqual(store.get_node(alice_id)["properties"], {"alias": "小明"})
        self.assertEqual([node["label"] for node in store.search_nodes("%Ali%", node_type="person")], ["Alice"])
        self.assertTrue(store.edge_exists(alice_id, jazz_id, "likes"))
        self.assertEqual(store.get_edges_for_node(alice_id)[0]["predicate"], "likes")
        self.assertEqual(store.search_entries(subject="%Ali%", predicate="likes", obj="%Jazz%")[0]["id"], entry_id)
        self.assertEqual(store.get_stats(), {"node_count": 2, "edge_count": 1, "entry_count": 1})

        linked_alice_id, linked_jazz_id = store.link_atoms("Alice", "person", "Jazz", "topic", "likes")
        self.assertEqual((linked_alice_id, linked_jazz_id), (alice_id, jazz_id))
        self.assertEqual(store.edge_count(), 1)
        self.assertTrue(store.delete_entry(entry_id))
        self.assertTrue(store.delete_edge(edge_id))
        self.assertTrue(store.delete_node(alice_id))
        self.assertIsNone(store.get_node(alice_id))

    def test_neighbors_related_atoms_and_entity_search_expand_through_graph_entries(self) -> None:
        store = GraphStore()
        alice_id = store.add_node("person", "Alice")
        jazz_id = store.add_node("topic", "Jazz")
        club_id = store.add_node("place", "Blue Note")
        store.add_edge(alice_id, jazz_id, "likes", confidence=0.9)
        store.add_edge(jazz_id, club_id, "heard_at", confidence=0.7)
        store.add_entry("Alice", "likes", "Jazz")
        store.add_entry("Jazz", "heard_at", "Blue Note")

        neighbors = store.get_neighbors(str(alice_id), depth=2)
        related_atoms = store.get_related_atoms("Alice", max_depth=1)
        search_results = store.search_by_entity("Jazz", top_k=5)

        self.assertEqual([item["node"]["label"] for item in neighbors], ["Jazz", "Blue Note"])
        self.assertGreaterEqual(set(related_atoms), {"Alice", "Jazz", "Blue Note"})
        self.assertEqual(search_results[0]["node"]["label"], "Jazz")
        self.assertEqual(len(search_results[0]["edges"]), 2)
        self.assertEqual(len(search_results[0]["entries"]), 2)

    def test_graph_store_safe_defaults_on_query_failures(self) -> None:
        store = GraphStore()

        with patch.object(GraphNode, "select", side_effect=RuntimeError("boom")):
            self.assertEqual(store.search_nodes("%x%"), [])
            self.assertEqual(store.search_by_entity("x"), [])
            self.assertEqual(store.get_related_atoms("x"), [])
            self.assertEqual(store.node_count(), 0)

        with patch.object(GraphEdge, "select", side_effect=RuntimeError("boom")):
            self.assertEqual(store.get_edges_for_node(1), [])
            self.assertEqual(store.get_neighbors("1"), [])
            self.assertFalse(store.edge_exists(1, 2, "likes"))
            self.assertEqual(store.edge_count(), 0)

        with patch.object(GraphEntry, "select", side_effect=RuntimeError("boom")):
            self.assertEqual(store.search_entries(), [])
            self.assertEqual(store.entry_count(), 0)


if __name__ == "__main__":
    unittest.main()
