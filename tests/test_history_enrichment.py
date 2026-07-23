import tempfile
import unittest
from pathlib import Path

from src.bw_learner.history_import import ImportedMessage, write_normalized_messages
from src.bw_learner.history_learning import HistoryCandidates, MemoryCandidate, ProfileCandidate
from src.memory.schema import configure_memory_database, initialize_database, memory_db
from src.memory.user_profile import ProfileStore, UserProfile


class RecordingMemoryWriter:
    def __init__(self) -> None:
        self.calls = []

    async def write_atom(self, atom, *, episodic_detail=None, semantic_detail=None):
        self.calls.append((atom, episodic_detail, semantic_detail))
        return atom.atom_id


class HistoryEnrichmentStorageTest(unittest.IsolatedAsyncioTestCase):
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

    async def test_imported_profiles_are_unverified_and_do_not_modify_verified_runtime_identity(self) -> None:
        from src.bw_learner.history_enrichment import store_history_enrichment

        profile_store = ProfileStore()
        profile_store.save_profile(
            UserProfile(
                user_id="42",
                platform="qq",
                nickname="运行时昵称",
                facts={"城市": "上海"},
                identity_source="message_sender",
                verification_status="verified",
            )
        )
        evidence = {
            "m1": ImportedMessage(
                message_id="m1",
                timestamp=1_750_000_000.0,
                sender_id="42",
                sender_name="导出昵称",
                sender_card="群名片",
                content="我平时最喜欢听爵士乐",
                reply_to_id=None,
                is_bot=False,
                is_low_signal=False,
            )
        }
        candidates = HistoryCandidates(
            memories=(
                MemoryCandidate(
                    "factual",
                    "群成员 42 表示自己喜欢爵士乐",
                    "42",
                    ("m1",),
                    0.8,
                    0.7,
                ),
            ),
            profiles=(ProfileCandidate("42", "interest", "音乐", "爵士乐", ("m1",), 0.82),),
        )
        writer = RecordingMemoryWriter()

        result = await store_history_enrichment(
            import_id="import-1",
            chat_id="chat-1",
            group_id="group-1",
            chat_name="测试群",
            candidates=candidates,
            evidence=evidence,
            extract_memories=True,
            update_profiles=True,
            memory_writer=writer,
            profile_store=profile_store,
        )

        verified = profile_store.get_profile("42", platform="qq")
        imported = profile_store.get_profile("42", platform="qq-import")
        self.assertIsNotNone(verified)
        self.assertIsNotNone(imported)
        assert verified is not None and imported is not None
        self.assertEqual(verified.facts, {"城市": "上海"})
        self.assertEqual(verified.verification_status, "verified")
        self.assertEqual(imported.interests, ["爵士乐"])
        self.assertEqual(imported.identity_source, "chat_history_import")
        self.assertEqual(imported.verification_status, "unverified")
        self.assertEqual(result.memories_created, 1)
        self.assertEqual(result.profiles_created, 1)
        self.assertEqual(len(writer.calls), 2)
        self.assertTrue(all(call[0].source_id == "chat-1" for call in writer.calls))
        self.assertEqual(writer.calls[1][2].subject_key, "qq-import:42")

    async def test_evidence_loader_returns_only_messages_referenced_by_enrichment_candidates(self) -> None:
        from src.bw_learner.history_enrichment import load_history_enrichment_evidence

        normalized = Path(self.tmpdir.name) / "normalized.jsonl"
        messages = [
            ImportedMessage(
                message_id=f"m{index}",
                timestamp=1_750_000_000.0 + index,
                sender_id="42",
                sender_name="测试用户",
                sender_card="",
                content=f"第 {index} 条消息",
                reply_to_id=None,
                is_bot=False,
                is_low_signal=False,
            )
            for index in range(4)
        ]
        write_normalized_messages(normalized, messages)
        candidates = HistoryCandidates(
            memories=(MemoryCandidate("factual", "有依据的事实", "42", ("m1",), 0.8, 0.7),),
            profiles=(ProfileCandidate("42", "interest", "话题", "测试", ("m3",), 0.8),),
        )

        evidence = load_history_enrichment_evidence(normalized, candidates)

        self.assertEqual(set(evidence), {"m1", "m3"})
        self.assertEqual(evidence["m3"].content, "第 3 条消息")


if __name__ == "__main__":
    unittest.main()
