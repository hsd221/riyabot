import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

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

    async def test_writer_initialization_failure_is_reported_without_aborting_base_learning(self) -> None:
        from src.bw_learner import history_enrichment

        candidate = MemoryCandidate(
            "factual",
            "群里决定周五发布新版本",
            "",
            ("m1",),
            0.86,
            0.75,
        )
        evidence = {
            "m1": ImportedMessage(
                message_id="m1",
                timestamp=1_750_000_000.0,
                sender_id="42",
                sender_name="测试用户",
                sender_card="群名片",
                content="群里决定周五发布新版本",
                reply_to_id=None,
                is_bot=False,
                is_low_signal=False,
            )
        }

        with patch.object(
            history_enrichment,
            "_default_memory_writer",
            new=AsyncMock(side_effect=RuntimeError("memory unavailable")),
        ):
            result = await history_enrichment.store_history_enrichment(
                import_id="import-writer-failure",
                chat_id="chat-1",
                group_id="group-1",
                chat_name="测试群",
                candidates=HistoryCandidates(memories=(candidate,)),
                evidence=evidence,
                extract_memories=True,
                update_profiles=False,
            )

        self.assertEqual(result.memories_created, 0)
        self.assertEqual(result.write_failures, 1)

    async def test_existing_profile_requires_a_decision_and_is_kept_by_default(self) -> None:
        from src.bw_learner.history_enrichment import find_history_profile_conflicts, store_history_enrichment

        profile_store = ProfileStore()
        profile_store.save_profile(
            UserProfile(
                user_id="42",
                platform="qq",
                nickname="运行时昵称",
                cardname="运行时群名片",
                group_nicknames=[
                    {
                        "platform": "qq",
                        "group_id": "existing-group",
                        "group_name": "现有群聊",
                        "group_nick_name": "现有群名片",
                    }
                ],
                facts={"城市": "上海"},
                interests=["摇滚"],
                stats={
                    "_profile_field_sources": {
                        "preferences": {},
                        "interests": {
                            "音乐": {
                                "atom_id": "existing",
                                "weight": 1.0,
                                "confidence": 0.99,
                                "evidence_counter": 20,
                                "created_at": 1_800_000_000.0,
                                "category": "interest",
                                "value": "摇滚",
                            }
                        },
                        "facts": {},
                        "traits": {},
                    }
                },
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

        conflicts = find_history_profile_conflicts(
            candidates=candidates,
            evidence=evidence,
            group_id="group-1",
            chat_name="测试群",
            profile_store=profile_store,
        )
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
        self.assertIsNotNone(verified)
        assert verified is not None
        self.assertEqual(verified.facts, {"城市": "上海"})
        self.assertEqual(verified.interests, ["摇滚"])
        self.assertEqual(verified.verification_status, "verified")
        self.assertEqual(conflicts[0]["profile_id"], "qq:42")
        self.assertEqual(conflicts[0]["imported"][0]["value"], "爵士乐")
        self.assertEqual(result.memories_created, 1)
        self.assertEqual(result.profiles_skipped, 1)
        self.assertEqual(len(writer.calls), 1)
        self.assertTrue(all(call[0].source_id == "chat-1" for call in writer.calls))

    async def test_approved_profile_update_uses_runtime_identity_without_downgrading_it(self) -> None:
        from src.bw_learner.history_enrichment import store_history_enrichment

        profile_store = ProfileStore()
        profile_store.save_profile(
            UserProfile(
                user_id="42",
                platform="qq",
                nickname="运行时昵称",
                cardname="运行时群名片",
                group_nicknames=[
                    {
                        "platform": "qq",
                        "group_id": "existing-group",
                        "group_name": "现有群聊",
                        "group_nick_name": "现有群名片",
                    }
                ],
                facts={"城市": "上海"},
                interests=["摇滚"],
                stats={
                    "_profile_field_sources": {
                        "preferences": {},
                        "interests": {
                            "音乐": {
                                "atom_id": "existing",
                                "weight": 1.0,
                                "confidence": 0.99,
                                "evidence_counter": 20,
                                "created_at": 1_800_000_000.0,
                                "category": "interest",
                                "value": "摇滚",
                            }
                        },
                        "facts": {},
                        "traits": {},
                    }
                },
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
        candidates = HistoryCandidates(profiles=(ProfileCandidate("42", "interest", "音乐", "爵士乐", ("m1",), 0.82),))
        writer = RecordingMemoryWriter()

        result = await store_history_enrichment(
            import_id="import-2",
            chat_id="chat-1",
            group_id="group-1",
            chat_name="测试群",
            candidates=candidates,
            evidence=evidence,
            extract_memories=False,
            update_profiles=True,
            memory_writer=writer,
            profile_store=profile_store,
            profile_decisions={"qq:42": "apply_imported"},
        )

        updated = profile_store.get_profile("42", platform="qq")
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.interests, ["爵士乐"])
        self.assertEqual(updated.nickname, "运行时昵称")
        self.assertEqual(updated.cardname, "运行时群名片")
        self.assertEqual(
            updated.group_nicknames,
            [
                {
                    "platform": "qq",
                    "group_id": "existing-group",
                    "group_name": "现有群聊",
                    "group_nick_name": "现有群名片",
                }
            ],
        )
        self.assertEqual(updated.verification_status, "verified")
        self.assertEqual(updated.identity_source, "message_sender")
        self.assertEqual(result.profiles_updated, 1)
        self.assertEqual(writer.calls[0][2].subject_key, "qq:42")

    async def test_new_profile_accepts_every_candidate_from_the_same_import(self) -> None:
        from src.bw_learner.history_enrichment import store_history_enrichment

        profile_store = ProfileStore()
        evidence = {
            "m1": ImportedMessage(
                message_id="m1",
                timestamp=1_750_000_000.0,
                sender_id="42",
                sender_name="测试用户",
                sender_card="群名片",
                content="我平时最喜欢听爵士乐",
                reply_to_id=None,
                is_bot=False,
                is_low_signal=False,
            ),
            "m2": ImportedMessage(
                message_id="m2",
                timestamp=1_750_000_001.0,
                sender_id="42",
                sender_name="测试用户",
                sender_card="群名片",
                content="我比较擅长排查 HTTP 错误",
                reply_to_id=None,
                is_bot=False,
                is_low_signal=False,
            ),
        }
        candidates = HistoryCandidates(
            profiles=(
                ProfileCandidate("42", "interest", "音乐", "爵士乐", ("m1",), 0.82),
                ProfileCandidate("42", "skill", "擅长领域", "排查 HTTP 错误", ("m2",), 0.86),
            )
        )
        writer = RecordingMemoryWriter()

        result = await store_history_enrichment(
            import_id="import-new-profile",
            chat_id="chat-1",
            group_id="group-1",
            chat_name="测试群",
            candidates=candidates,
            evidence=evidence,
            extract_memories=False,
            update_profiles=True,
            memory_writer=writer,
            profile_store=profile_store,
        )

        profile = profile_store.get_profile("42", platform="qq")
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.interests, ["爵士乐"])
        self.assertEqual(profile.facts["擅长领域"], "排查 HTTP 错误")
        self.assertEqual(result.profiles_created, 1)
        self.assertEqual(result.profiles_updated, 1)
        self.assertEqual(result.profiles_skipped, 0)
        self.assertEqual(len(writer.calls), 2)

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
