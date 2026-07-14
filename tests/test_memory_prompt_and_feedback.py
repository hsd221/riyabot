import datetime
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.memory import prompt_integration
from src.memory.atom import AtomType, MemoryAtom
from src.memory.feedback import ReinforcementTracker, _char_bigram_jaccard
from src.memory.schema import configure_memory_database, initialize_database, memory_db
from src.memory.user_profile import ProfileStore, UserProfile


def make_atom(atom_id: str, content: str, *, weight: float = 0.5) -> MemoryAtom:
    return MemoryAtom(
        atom_id=atom_id,
        atom_type=AtomType.FACTUAL,
        content=content,
        weight=weight,
        importance=0.5,
        confidence=0.5,
        created_at=0.0,
        last_accessed_at=0.0,
        ttl_days=7.0,
    )


class MemoryPromptIntegrationTest(unittest.IsolatedAsyncioTestCase):
    def test_prompt_text_helpers_compact_escape_strip_hints_and_parse_questions(self) -> None:
        self.assertEqual(prompt_integration._compact_text("  a\n b  c  ", 100), "a b c")
        self.assertEqual(prompt_integration._compact_text("abcdef", 3), "def")
        self.assertEqual(prompt_integration._escape_evidence_text("<tag>&"), "&lt;tag&gt;&amp;")
        self.assertEqual(prompt_integration.neutralize_prompt_boundaries("---BEGIN x ---END"), "--- BEGIN x --- END")
        self.assertEqual(prompt_integration._strip_message_speakers("[12:00] Alice: 之前说过什么"), "之前说过什么")
        self.assertTrue(prompt_integration._has_memory_hint("还记得上次说过的约定吗"))
        self.assertTrue(prompt_integration._should_ask_memory_question_llm("", "那个人是谁来着？"))
        self.assertFalse(prompt_integration._should_ask_memory_question_llm("", "你好"))
        self.assertTrue(prompt_integration._should_run_memory_retrieval("", "", [" 黑话 "], None))
        self.assertFalse(prompt_integration._should_run_memory_retrieval("", "你好", [], None))

        fenced = '```json\n{"questions": ["  - 之前说过什么？", "重复"]}\n```'
        self.assertEqual(prompt_integration._parse_memory_questions(fenced), ["之前说过什么？"])
        self.assertEqual(prompt_integration._parse_memory_questions('{"questions": "谁是小明？"}'), ["谁是小明？"])
        self.assertEqual(prompt_integration._parse_memory_questions("not json"), [])

    def test_followup_context_hint_and_query_text_keep_nearby_memory_clues(self) -> None:
        history = "Alice: 之前说过猫猫喜欢爵士乐\nBob: 后来大家换话题了"

        self.assertEqual(prompt_integration._build_followup_context_hint(history, "后来呢？"), "之前说过猫猫喜欢爵士乐")

        query = prompt_integration._build_memory_query_text(
            chat_talking_prompt_short=history,
            sender="Alice",
            target="后来呢？",
            unknown_words=["赛博夜宵"],
            question=None,
        )

        self.assertIn("当前目标消息: 后来呢？", query)
        self.assertIn("追问线索: 之前说过猫猫喜欢爵士乐", query)
        self.assertIn("待理解词语: 赛博夜宵", query)
        self.assertIn("近邻上下文:", query)

    def test_format_reference_block_escapes_evidence_and_omits_empty_blocks(self) -> None:
        self.assertEqual(
            prompt_integration._format_reference_block(
                target="",
                sender="",
                question=None,
                profile_text="",
                memory_context="",
                cross_scene_text="",
            ),
            "",
        )

        block = prompt_integration._format_reference_block(
            target="<目标>",
            sender="Alice",
            question="之前说过什么？",
            profile_text="喜欢 <猫>",
            memory_context="本地 & 记忆",
            cross_scene_text="跨场景 > 记忆",
        )

        self.assertIn('<CONTEXT_EVIDENCE priority="low" source="memory">', block)
        self.assertIn("Alice: &lt;目标&gt;", block)
        self.assertIn("<profile>\n喜欢 &lt;猫&gt;\n</profile>", block)
        self.assertIn("<local_memory>\n本地 &amp; 记忆\n</local_memory>", block)
        self.assertIn("<cross_scene_memory>\n跨场景 &gt; 记忆\n</cross_scene_memory>", block)

    async def test_build_memory_retrieval_prompt_skips_low_information_and_formats_retrieved_context(self) -> None:
        no_context = await prompt_integration.build_memory_retrieval_prompt(
            chat_talking_prompt_short="",
            target="你好",
            chat_stream=SimpleNamespace(stream_id="stream-1", group_info=None, user_info=None),
            allow_llm_question=False,
        )
        missing_stream = await prompt_integration.build_memory_retrieval_prompt(chat_stream=SimpleNamespace())

        self.assertEqual(no_context, ("", []))
        self.assertEqual(missing_stream, ("", []))

        class FakeRetriever:
            def __init__(self, store, graph_store=None):
                self.store = store
                self.graph_store = graph_store

            async def get_context_for_reply_with_ids(self, **kwargs):
                return "local <memory>", ["atom-a"]

            async def get_cross_scene_context_with_ids(self, **kwargs):
                return "cross & memory", ["atom-b", "atom-a"]

        with (
            patch("src.memory.get_memory_store", return_value=object()),
            patch("src.memory.layer3_retrieval.MemoryRetriever", FakeRetriever),
        ):
            block, atom_ids = await prompt_integration.build_memory_retrieval_prompt(
                chat_talking_prompt_short="Alice: 之前说过喜欢猫",
                sender="Alice",
                target="还记得之前说过什么吗？",
                chat_stream=SimpleNamespace(stream_id="stream-1", group_info=object(), user_info=None),
                question="之前说过什么？",
            )

        self.assertIn("local &lt;memory&gt;", block)
        self.assertIn("cross &amp; memory", block)
        self.assertEqual(atom_ids, ["atom-a", "atom-b"])


class MemoryFeedbackTest(unittest.IsolatedAsyncioTestCase):
    def test_bigram_jaccard_and_usage_analysis_return_expected_reinforcement_levels(self) -> None:
        self.assertEqual(_char_bigram_jaccard("", "abc"), 0.0)
        self.assertEqual(_char_bigram_jaccard("abc", "abc"), 1.0)

        tracker = ReinforcementTracker(SimpleNamespace())
        usage = tracker.analyze_reply_for_memory_usage(
            "小明喜欢爵士乐，也喜欢猫。",
            [
                make_atom("strong", "小明喜欢爵士乐，也喜欢猫。"),
                make_atom("normal", "小明喜欢爵士乐"),
                make_atom("none", "完全无关的内容"),
                make_atom("empty", ""),
            ],
        )

        self.assertEqual(usage["strong"], "strong")
        self.assertEqual(usage["normal"], "normal")
        self.assertEqual(usage["none"], "none")
        self.assertEqual(usage["empty"], "none")
        self.assertEqual(tracker.analyze_reply_for_memory_usage("", []), {})

    def test_dict_to_atom_and_build_updates_normalize_serialized_store_data(self) -> None:
        atom = ReinforcementTracker._dict_to_atom(
            {
                "atom_id": "atom-1",
                "atom_type": "preference",
                "content": "小明喜欢猫",
                "entities": '["小明", "猫"]',
                "importance": "0.8",
                "confidence": "0.7",
                "weight": "0.6",
                "created_at": datetime.datetime.fromtimestamp(1.0),
                "last_accessed_at": 2.0,
                "last_reinforced_at": None,
                "ttl_days": "30",
                "decay_type": "linear",
                "reinforcement_count": "2",
                "source_scene": "group_chat",
            }
        )
        updated = make_atom("atom-1", "小明喜欢猫", weight=0.9)
        updated.reinforcement_count = 3
        updated.last_reinforced_at = 10.0
        updated.last_accessed_at = 11.0

        updates = ReinforcementTracker._build_updates(atom, updated)

        self.assertEqual(atom.atom_type.value, "preference")
        self.assertEqual(atom.entities, ["小明", "猫"])
        self.assertEqual(updates["weight"], 0.9)
        self.assertEqual(updates["reinforcement_count"], 3)

        self.assertEqual(updates["last_reinforced_at"], datetime.datetime.fromtimestamp(10.0))
        self.assertEqual(updates["last_accessed_at"], datetime.datetime.fromtimestamp(11.0))

    async def test_usage_feedback_groups_levels_and_apply_reinforcement_persists_batch_updates(self) -> None:
        tracker = ReinforcementTracker(SimpleNamespace())
        tracker.apply_reinforcement = AsyncMock()

        await tracker.apply_usage_feedback({"a": "normal", "b": "strong", "c": "none", "ignored": "bad"})

        self.assertEqual(
            [call.args for call in tracker.apply_reinforcement.await_args_list],
            [(["c"], "none"), (["a"], "normal"), (["b"], "strong")],
        )

        class FakeQdrant:
            def __init__(self):
                self.set_atom_payload = AsyncMock(return_value=True)

        class FakeStore:
            def __init__(self):
                self.qdrant = FakeQdrant()
                self.update_atoms_batch = AsyncMock()

            async def get_atoms_batch(self, atom_ids):
                return {
                    "atom-1": {
                        "atom_id": "atom-1",
                        "atom_type": "factual",
                        "content": "小明喜欢猫",
                        "weight": 0.2,
                        "importance": 0.5,
                        "confidence": 0.5,
                        "created_at": 0.0,
                        "last_accessed_at": 0.0,
                        "ttl_days": 7,
                        "decay_type": "exponential",
                        "reinforcement_count": 0,
                    }
                }

        store = FakeStore()
        real_tracker = ReinforcementTracker(store)

        await real_tracker.apply_reinforcement(["atom-1", "missing"], level="normal")

        store.update_atoms_batch.assert_awaited_once()
        atom_id, updates = store.update_atoms_batch.await_args.args[0][0]
        self.assertEqual(atom_id, "atom-1")
        self.assertIn("weight", updates)
        store.qdrant.set_atom_payload.assert_awaited_once()


class MemoryPromptProfileIntegrationTest(unittest.IsolatedAsyncioTestCase):
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

    async def test_regular_reply_context_includes_verified_profile_and_expression_without_memory_query(self) -> None:
        store = ProfileStore()
        store.save_profile(
            UserProfile(
                user_id="42",
                platform="qq",
                nickname="小明",
                impression="喜欢爵士乐",
                expression_style="简洁",
                expression_patterns={"favorite_expressions": ["好耶"]},
            )
        )
        stream = SimpleNamespace(
            stream_id="qq:42",
            platform="qq",
            group_info=None,
            user_info=SimpleNamespace(user_id="42", platform="qq"),
        )

        block, atom_ids = await prompt_integration.build_memory_retrieval_prompt(
            target="你好",
            chat_stream=stream,
            allow_llm_question=False,
        )

        self.assertEqual(atom_ids, [])
        self.assertIn("<profile>", block)
        self.assertIn("喜欢爵士乐", block)
        self.assertIn("表达:简洁", block)

        other_platform = SimpleNamespace(
            stream_id="discord:42",
            platform="discord",
            group_info=None,
            user_info=SimpleNamespace(user_id="42", platform="discord"),
        )
        other_block, _ = await prompt_integration.build_memory_retrieval_prompt(
            target="你好",
            chat_stream=other_platform,
            allow_llm_question=False,
        )
        self.assertEqual(other_block, "")


if __name__ == "__main__":
    unittest.main()
