"""Memory system regression tests for ingestion durability and identity handling."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from peewee import IntegrityError

import src.memory.layer3_retrieval as layer3_module
import src.memory.write_ops as write_ops_module
from src.memory.atom import AtomType, MemoryAtom as MemoryAtomDC, SemanticDetail
from src.memory.encoding_pipeline import EncodingPipeline
from src.memory.layer0_archive import MessageArchiver
from src.memory.layer2_encoder import (
    MAX_DETAIL_TEXT_LENGTH,
    MAX_ENTITIES_PER_ATOM,
    SOURCE_USER_IDS_DETAIL_KEY,
    BatchEncoder,
)
from src.memory.layer3_retrieval import MemoryWriter
from src.memory.schema import MemoryAtom, RawMessageArchive, configure_memory_database, initialize_database, memory_db
from src.memory.store import MemoryStore, MemoryStoreConfig, QdrantManager
from src.memory.write_ops import OpStatus, OpType, WriteOp, WriteOpLogger


class FakeMessage:
    def __init__(
        self,
        *,
        stream_id: str = "stream-1",
        message_id: str = "msg-1",
        user_id: str = "user-1",
        content: str = "小明说自己喜欢爵士乐",
        timestamp: float = 1_783_456_789.0,
    ) -> None:
        self.stream_id = stream_id
        self.message_id = message_id
        self.user_id = user_id
        self.content = content
        self.timestamp = timestamp


class FakeStore:
    pass


class BadJsonEncoder(BatchEncoder):
    async def _call_llm(self, prompt: str) -> str:
        return "这不是 JSON"


class EntityPoisoningEncoder(BatchEncoder):
    async def _call_llm(self, prompt: str) -> str:
        return """
        [
          {
            "content": "user-1 长期喜欢爵士乐",
            "atom_type": "preference",
            "entities": ["user-1", "user-evil", "爵士乐"],
            "importance": 0.8,
            "detail": {"attr_name": "music", "attr_value": "jazz"}
          }
        ]
        """


class FakeQdrant:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, list[float], dict[str, Any]]] = []

    async def upsert_atom_vector(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> bool:
        self.upserts.append((point_id, vector, payload))
        return True


class FakeReplayStore:
    def __init__(self, atoms: dict[str, dict[str, Any]] | None = None) -> None:
        self.atoms = atoms or {}
        self.insert_calls = 0
        self.qdrant = FakeQdrant()

    async def get_atom(self, atom_id: str) -> dict[str, Any] | None:
        return self.atoms.get(atom_id)

    async def insert_atom(self, atom: dict[str, Any]) -> str:
        self.insert_calls += 1
        atom_id = atom["atom_id"]
        if atom_id in self.atoms:
            raise ValueError(f"duplicate atom: {atom_id}")
        self.atoms[atom_id] = dict(atom)
        return atom_id


class FakeCollectionClient:
    def __init__(self, vector_size: int | None = None, vector_config: Any | None = None) -> None:
        self.vector_size = vector_size
        self.vector_config = vector_config

    def get_collections(self) -> SimpleNamespace:
        return SimpleNamespace(collections=[SimpleNamespace(name="memory_atoms")])

    def get_collection(self, collection_name: str) -> SimpleNamespace:
        vectors = self.vector_config
        if vectors is None:
            vectors = SimpleNamespace(size=self.vector_size)
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=vectors,
                )
            )
        )


class MemoryRegressionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "memory.db"
        configure_memory_database(str(db_path))
        initialize_database()

    def tearDown(self) -> None:
        MemoryStore._instance = None
        if not memory_db.is_closed():
            memory_db.close()
        self.tmpdir.cleanup()

    async def test_raw_archive_is_idempotent_for_same_stream_message_and_type(self) -> None:
        archiver = MessageArchiver()
        message = FakeMessage()

        first_id = await archiver.archive_group_message(message)
        second_id = await archiver.archive_group_message(message)

        self.assertEqual(first_id, second_id)
        self.assertEqual(RawMessageArchive.select().count(), 1)

    async def test_raw_archive_unique_index_dedupes_existing_rows_before_creation(self) -> None:
        for index_row in memory_db.execute_sql("PRAGMA index_list(raw_message_archive)").fetchall():
            index_name = index_row[1]
            is_unique = bool(index_row[2])
            if is_unique:
                memory_db.execute_sql(f'DROP INDEX IF EXISTS "{index_name}"')

        RawMessageArchive.create(
            stream_id="stream-1",
            message_id="msg-1",
            user_id="user-1",
            content="第一条",
            timestamp=1.0,
            chat_type="group",
            dream_status="pending",
        )
        RawMessageArchive.create(
            stream_id="stream-1",
            message_id="msg-1",
            user_id="user-1",
            content="重复条",
            timestamp=1.0,
            chat_type="group",
            dream_status="triaged",
            dream_route="high",
            dream_significance=0.9,
        )

        initialize_database()

        rows = list(
            RawMessageArchive.select().where(
                RawMessageArchive.stream_id == "stream-1",
                RawMessageArchive.message_id == "msg-1",
                RawMessageArchive.chat_type == "group",
            )
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].dream_status, "triaged")
        self.assertEqual(rows[0].dream_route, "high")

        with self.assertRaises(IntegrityError):
            RawMessageArchive.create(
                stream_id="stream-1",
                message_id="msg-1",
                user_id="user-1",
                content="第三条",
                timestamp=1.0,
                chat_type="group",
            )

    def test_encoding_prompt_keeps_stable_user_id_next_to_display_name(self) -> None:
        encoder = BatchEncoder(store=FakeStore())  # type: ignore[arg-type]

        prompt = encoder._build_encoding_prompt(
            [
                {
                    "message_id": "msg-1",
                    "user_id": "user-123",
                    "speaker": "会变的群昵称",
                    "content": "我一直喜欢爵士乐",
                    "timestamp": 1_783_456_789.0,
                }
            ],
            topic_summary="",
        )

        self.assertIn("user_id=user-123", prompt)
        self.assertIn("会变的群昵称", prompt)

    async def test_invalid_llm_json_does_not_clear_encoding_buffer(self) -> None:
        encoder = BadJsonEncoder(store=FakeStore())  # type: ignore[arg-type]
        await encoder.ingest_message(
            stream_id="stream-1",
            user_id="user-1",
            speaker="小明",
            content="我一直喜欢爵士乐",
            timestamp=None,
            message_id="msg-1",
        )

        extracted = await encoder.encode_batch("stream-1", force=True)

        self.assertEqual(extracted, [])
        self.assertEqual(len(encoder.get_buffer("stream-1") or []), 1)

    async def test_encoder_attaches_source_user_ids_without_trusting_llm_entities(self) -> None:
        encoder = EntityPoisoningEncoder(store=FakeStore())  # type: ignore[arg-type]
        await encoder.ingest_message(
            stream_id="stream-1",
            user_id="user-1",
            speaker="小明",
            content="我一直喜欢爵士乐",
            timestamp=None,
            message_id="msg-1",
        )

        extracted = await encoder.encode_batch("stream-1", force=True)

        self.assertEqual(len(extracted), 1)
        _, _, detail = extracted[0]
        self.assertEqual(detail[SOURCE_USER_IDS_DETAIL_KEY], ["user-1"])
        self.assertEqual(detail["entities"], ["user-1", "user-evil", "爵士乐"])

    def test_profile_targets_are_limited_to_source_user_ids(self) -> None:
        atom = MemoryAtomDC(
            atom_id="atom-profile-target",
            atom_type=AtomType.PREFERENCE,
            content="user-1 长期喜欢爵士乐",
            entities=["user-1", "user-evil", "爵士乐", "user-1"],
            source_scene="group_chat",
            source_id="stream-1",
        )
        detail = {SOURCE_USER_IDS_DETAIL_KEY: ["user-1"]}

        self.assertEqual(EncodingPipeline._profile_target_entities(atom, detail), ["user-1"])

    def test_llm_detail_fields_are_capped_and_scalar_lists_are_rejected(self) -> None:
        encoder = BatchEncoder(store=FakeStore())  # type: ignore[arg-type]
        factual = encoder._validate_atom_item(
            {
                "content": "user-1 说自己喜欢很长的音乐描述",
                "atom_type": "factual",
                "entities": [f"user-{idx}" for idx in range(30)],
                "importance": 2,
                "detail": {
                    "attr_category": "interest" * 40,
                    "attr_name": "music" * 40,
                    "attr_value": "jazz" * 200,
                },
            }
        )
        self.assertIsNotNone(factual)
        _, _, factual_detail = factual
        self.assertEqual(len(factual_detail["entities"]), MAX_ENTITIES_PER_ATOM)
        self.assertLessEqual(len(factual_detail["attr_value"]), MAX_DETAIL_TEXT_LENGTH)

        episodic = encoder._validate_atom_item(
            {
                "content": "user-1 在群里说了自己很开心",
                "atom_type": "episodic",
                "entities": ["user-1"],
                "detail": {
                    "participants": "user-evil",
                    "emotion_tags": "happy",
                    "sensory_tags": ["visual", "x" * 500],
                    "temporal_context": "night" * 100,
                },
            }
        )
        self.assertIsNotNone(episodic)
        _, _, episodic_detail = episodic
        self.assertEqual(episodic_detail["participants"], ["user-1"])
        self.assertEqual(episodic_detail["emotion_tags"], [])
        self.assertLessEqual(len(episodic_detail["sensory_tags"][1]), MAX_DETAIL_TEXT_LENGTH)
        self.assertLessEqual(len(episodic_detail["temporal_context"]), MAX_DETAIL_TEXT_LENGTH)

    async def test_write_atom_rolls_back_when_semantic_detail_fails(self) -> None:
        store = MemoryStore(
            MemoryStoreConfig(
                sqlite_path=str(Path(self.tmpdir.name) / "memory.db"),
                qdrant_local_path=str(Path(self.tmpdir.name) / "qdrant"),
            )
        )
        writer = MemoryWriter(store)
        atom = MemoryAtomDC(
            atom_id="atom-bad-detail",
            atom_type=AtomType.FACTUAL,
            content="user-1 长期喜欢爵士乐",
            entities=["user-1"],
            source_scene="group_chat",
            source_id="stream-1",
        )
        bad_detail = SemanticDetail(
            atom_id=atom.atom_id,
            attr_category=None,  # type: ignore[arg-type]
            attr_name="music",
            attr_value="jazz",
        )

        original_generate_embedding = layer3_module.generate_embedding

        async def no_embedding(_: str) -> None:
            return None

        layer3_module.generate_embedding = no_embedding  # type: ignore[assignment]
        try:
            with self.assertRaises(IntegrityError):
                await writer.write_atom(atom=atom, semantic_detail=bad_detail)
        finally:
            layer3_module.generate_embedding = original_generate_embedding

        self.assertFalse(MemoryAtom.select().where(MemoryAtom.atom_id == atom.atom_id).exists())

    async def test_replay_in_progress_qdrant_insert_does_not_reinsert_sqlite(self) -> None:
        atom = {
            "atom_id": "atom-qdrant-only",
            "atom_type": "factual",
            "content": "user-1 喜欢爵士乐",
            "weight": 0.8,
            "importance": 0.7,
            "confidence": 0.9,
            "status": "active",
            "source_scene": "group_chat",
            "source_id": "stream-1",
            "privacy_level": "context_sensitive",
        }
        store = FakeReplayStore(atoms={atom["atom_id"]: atom})
        logger = WriteOpLogger(str(Path(self.tmpdir.name) / "memory.db"))
        logger.log_op(
            WriteOp(
                op_id="op-qdrant",
                op_type=OpType.INSERT_ATOM,
                target="qdrant",
                atom_ids=[atom["atom_id"]],
                payload={"atom": atom},
                status=OpStatus.IN_PROGRESS,
            )
        )

        original_generate_embedding = write_ops_module.generate_embedding

        async def fake_embedding(_: str) -> list[float]:
            return [0.1, 0.2]

        write_ops_module.generate_embedding = fake_embedding  # type: ignore[assignment]
        try:
            recovered = await logger.replay_failed_ops(store)
        finally:
            write_ops_module.generate_embedding = original_generate_embedding

        self.assertEqual(recovered, ["op-qdrant"])
        self.assertEqual(store.insert_calls, 0)
        self.assertEqual(len(store.qdrant.upserts), 1)
        self.assertEqual(logger.get_op("op-qdrant").status, OpStatus.COMPLETED)

    async def test_replay_sqlite_insert_is_idempotent_when_atom_exists(self) -> None:
        atom = {
            "atom_id": "atom-existing",
            "atom_type": "factual",
            "content": "user-1 喜欢爵士乐",
        }
        store = FakeReplayStore(atoms={atom["atom_id"]: atom})
        logger = WriteOpLogger(str(Path(self.tmpdir.name) / "memory.db"))
        logger.log_op(
            WriteOp(
                op_id="op-sqlite",
                op_type=OpType.INSERT_ATOM,
                target="sqlite",
                atom_ids=[atom["atom_id"]],
                payload={"atom": atom},
                status=OpStatus.FAILED,
            )
        )

        recovered = await logger.replay_failed_ops(store)

        self.assertEqual(recovered, ["op-sqlite"])
        self.assertEqual(store.insert_calls, 0)
        self.assertEqual(len(store.qdrant.upserts), 0)
        self.assertEqual(logger.get_op("op-sqlite").status, OpStatus.COMPLETED)

    async def test_qdrant_existing_collection_dimension_mismatch_fails_initialization(self) -> None:
        manager = QdrantManager(MemoryStoreConfig(embedding_dimension=256))
        manager._client = FakeCollectionClient(vector_size=128)  # type: ignore[assignment]
        manager._available = True

        with self.assertRaises(RuntimeError):
            await manager._ensure_collection("memory_atoms", [])

    async def test_qdrant_existing_named_vector_collection_fails_initialization(self) -> None:
        manager = QdrantManager(MemoryStoreConfig(embedding_dimension=256))
        manager._client = FakeCollectionClient(vector_config={"named": SimpleNamespace(size=256)})  # type: ignore[assignment]
        manager._available = True

        with self.assertRaises(RuntimeError):
            await manager._ensure_collection("memory_atoms", [])


if __name__ == "__main__":
    unittest.main()
