import json
import unittest
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from peewee import SqliteDatabase

from src.bw_learner import expression_reflector, jargon_explainer, jargon_miner, reflect_tracker
from src.common.database.database_model import Jargon


class JargonDatabaseTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = SqliteDatabase(":memory:")
        self.original_db = Jargon._meta.database
        self.db.bind([Jargon], bind_refs=False, bind_backrefs=False)
        self.db.connect()
        self.db.create_tables([Jargon])

    def tearDown(self) -> None:
        self.db.drop_tables([Jargon])
        self.db.close()
        Jargon._meta.set_database(self.original_db)

    def make_miner(self) -> jargon_miner.JargonMiner:
        miner = jargon_miner.JargonMiner.__new__(jargon_miner.JargonMiner)
        miner.chat_id = "chat-1"
        miner.stream_name = "Test Chat"
        miner.cache_limit = 2
        miner.cache = OrderedDict()
        miner._infer_meaning_by_id = AsyncMock()
        return miner

    def test_single_char_threshold_and_lru_cache_helpers_are_stable(self) -> None:
        self.assertTrue(jargon_miner._is_single_char_jargon("中"))
        self.assertTrue(jargon_miner._is_single_char_jargon("A"))
        self.assertTrue(jargon_miner._is_single_char_jargon("1"))
        self.assertFalse(jargon_miner._is_single_char_jargon("梗词"))
        self.assertFalse(jargon_miner._is_single_char_jargon(""))

        self.assertFalse(jargon_miner._should_infer_meaning(SimpleNamespace(is_complete=True, count=100)))
        self.assertFalse(
            jargon_miner._should_infer_meaning(SimpleNamespace(is_complete=False, count=1, last_inference_count=0))
        )
        self.assertTrue(
            jargon_miner._should_infer_meaning(SimpleNamespace(is_complete=False, count=2, last_inference_count=0))
        )
        self.assertFalse(
            jargon_miner._should_infer_meaning(SimpleNamespace(is_complete=False, count=2, last_inference_count=2))
        )

        miner = self.make_miner()
        miner._add_to_cache("")
        miner._add_to_cache("A")
        miner._add_to_cache(" 梗词 ")
        miner._add_to_cache("旧词")
        miner._add_to_cache("梗词")
        miner._add_to_cache("新词")

        self.assertEqual(miner.get_cached_jargons(), ["梗词", "新词"])

    async def test_process_extracted_entries_merges_records_updates_chat_counts_cache_and_schedules_inference(
        self,
    ) -> None:
        Jargon.create(
            content="梗词",
            raw_content='["旧上下文"]',
            chat_id='[["chat-1", 1]]',
            count=1,
            is_global=False,
        )
        miner = self.make_miner()
        scheduled = []

        def fake_create_task(coro):
            scheduled.append(coro)
            coro.close()
            return SimpleNamespace(cancel=Mock())

        fake_config = SimpleNamespace(expression=SimpleNamespace(all_global_jargon=False))
        with (
            patch.object(jargon_miner, "global_config", fake_config),
            patch.object(jargon_miner.asyncio, "create_task", side_effect=fake_create_task),
        ):
            await miner.process_extracted_entries(
                [
                    {"content": "梗词", "raw_content": ["新上下文", "旧上下文"]},
                    {"content": "新词", "raw_content": ["第一次出现"]},
                    {"content": "Alice", "raw_content": ["应被过滤"]},
                ],
                person_name_filter=lambda value: value == "Alice",
            )

        existing = Jargon.get(Jargon.content == "梗词")
        created = Jargon.get(Jargon.content == "新词")

        self.assertEqual(existing.count, 2)
        self.assertEqual(json.loads(existing.raw_content), ["旧上下文", "新上下文"])
        self.assertEqual(json.loads(existing.chat_id), [["chat-1", 2]])
        self.assertEqual(created.count, 1)
        self.assertEqual(json.loads(created.raw_content), ["第一次出现"])
        self.assertEqual(json.loads(created.chat_id), [["chat-1", 1]])
        self.assertFalse(created.is_global)
        self.assertEqual(miner.get_cached_jargons(), ["梗词", "新词"])
        self.assertEqual(len(scheduled), 1)
        self.assertFalse(Jargon.select().where(Jargon.content == "Alice").exists())

    async def test_search_retrieve_and_text_matching_respect_chat_scope_global_records_and_fuzzy_fallback(self) -> None:
        Jargon.create(content="yyds", meaning="永远的神", chat_id='[["chat-1", 1]]', count=5, is_global=False)
        Jargon.create(content="CPU", meaning="被占用", chat_id='[["chat-2", 1]]', count=10, is_global=False)
        Jargon.create(content="全局梗", meaning="全局含义", chat_id="", count=7, is_global=True)
        Jargon.create(content="空含义", meaning="", chat_id='[["chat-1", 1]]', count=1, is_global=False)
        fake_config = SimpleNamespace(expression=SimpleNamespace(all_global_jargon=False))

        with patch.object(jargon_miner, "global_config", fake_config):
            self.assertEqual(
                jargon_miner.search_jargon("YYDS", chat_id="chat-1", fuzzy=False)[0]["meaning"], "永远的神"
            )
            self.assertEqual(jargon_miner.search_jargon("CPU", chat_id="chat-1", fuzzy=False), [])
            self.assertEqual(jargon_miner.search_jargon("全局", chat_id="chat-1")[0]["content"], "全局梗")
            retrieved = await jargon_explainer.retrieve_concepts_with_jargon([" yyds ", "全局"], "chat-1")

        self.assertIn("'yyds' 为黑话或者网络简写，含义为：永远的神", retrieved)
        self.assertIn("未精确匹配到'全局'", retrieved)
        self.assertIn("找到 '全局梗' 的含义为：全局含义", retrieved)

        with patch.object(jargon_explainer, "global_config", fake_config):
            self.assertEqual(
                jargon_explainer.match_jargon_from_text("这里 yyds 还有全局梗", "chat-1"), ["全局梗", "yyds"]
            )
            self.assertEqual(jargon_explainer.match_jargon_from_text("CPU 不属于此群", "chat-1"), [])


class JargonExplainerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = SqliteDatabase(":memory:")
        self.original_db = Jargon._meta.database
        self.db.bind([Jargon], bind_refs=False, bind_backrefs=False)
        self.db.connect()
        self.db.create_tables([Jargon])

    def tearDown(self) -> None:
        self.db.drop_tables([Jargon])
        self.db.close()
        Jargon._meta.set_database(self.original_db)

    def test_match_jargon_from_messages_skips_bot_messages_uses_word_boundaries_and_chat_filters(self) -> None:
        Jargon.create(content="cpu", meaning="被占用", chat_id='[["chat-1", 1]]', count=5, is_global=False)
        Jargon.create(content="梗词", meaning="一个梗", chat_id='[["chat-1", 1]]', count=4, is_global=False)
        Jargon.create(content="other", meaning="别群", chat_id='[["chat-2", 1]]', count=3, is_global=False)
        explainer = jargon_explainer.JargonExplainer.__new__(jargon_explainer.JargonExplainer)
        explainer.chat_id = "chat-1"
        messages = [
            SimpleNamespace(user_id="bot", processed_plain_text="cpu"),
            SimpleNamespace(user_id="user", processed_plain_text="cpux 不应匹配"),
            SimpleNamespace(user_id="user", processed_plain_text="CPU 和梗词"),
        ]
        fake_config = SimpleNamespace(expression=SimpleNamespace(all_global_jargon=False))

        with (
            patch.object(jargon_explainer, "global_config", fake_config),
            patch.object(
                jargon_explainer, "is_bot_message", side_effect=lambda msg: getattr(msg, "user_id", "") == "bot"
            ),
            patch.object(jargon_explainer, "contains_bot_self_name", return_value=False),
        ):
            matched = explainer.match_jargon_from_messages(messages)

        self.assertEqual(matched, [{"content": "cpu"}, {"content": "梗词"}])

    async def test_explain_jargon_deduplicates_searches_and_falls_back_to_raw_explanations(self) -> None:
        explainer = jargon_explainer.JargonExplainer.__new__(jargon_explainer.JargonExplainer)
        explainer.chat_id = "chat-1"
        explainer.llm = SimpleNamespace(generate_response_async=AsyncMock(return_value=(" 总结解释 ", None)))

        with (
            patch.object(
                explainer,
                "match_jargon_from_messages",
                return_value=[{"content": "yyds"}, {"content": "yyds"}, {"content": "cpu"}],
            ),
            patch.object(
                jargon_explainer,
                "search_jargon",
                side_effect=[
                    [{"content": "yyds", "meaning": "永远的神"}],
                    [{"content": "cpu", "meaning": "被占用"}],
                ],
            ),
            patch.object(
                jargon_explainer.global_prompt_manager,
                "format_prompt",
                new=AsyncMock(return_value="prompt"),
            ) as format_prompt,
        ):
            summary = await explainer.explain_jargon([object()], "聊天上下文")

        self.assertEqual(summary, "总结解释")
        format_prompt.assert_awaited_once()
        explainer.llm.generate_response_async.assert_awaited_once_with("prompt", temperature=0.3)

        explainer.llm = SimpleNamespace(generate_response_async=AsyncMock(return_value=("", None)))
        with (
            patch.object(explainer, "match_jargon_from_messages", return_value=[{"content": "yyds"}]),
            patch.object(jargon_explainer, "search_jargon", return_value=[{"content": "yyds", "meaning": "永远的神"}]),
            patch.object(jargon_explainer.global_prompt_manager, "format_prompt", new=AsyncMock(return_value="prompt")),
        ):
            fallback = await explainer.explain_jargon([object()], "聊天上下文")

        self.assertEqual(fallback, "上下文中的黑话解释：\n- yyds: 永远的神")
        self.assertIsNone(await explainer.explain_jargon([], "聊天上下文"))


class ReflectionHelpersTest(unittest.IsolatedAsyncioTestCase):
    async def test_check_tracker_exists_resolves_private_group_and_existing_stream_configs(self) -> None:
        private_stream = SimpleNamespace(stream_id="private-stream")
        group_stream = SimpleNamespace(stream_id="group-stream")
        existing_stream = SimpleNamespace(stream_id="existing-stream")
        manager = SimpleNamespace(
            get_or_create_stream=AsyncMock(side_effect=[private_stream, group_stream]),
            get_stream=Mock(return_value=existing_stream),
        )
        tracker_manager = SimpleNamespace(get_tracker=Mock(side_effect=[object(), None, object()]))

        with (
            patch.object(expression_reflector, "get_chat_manager", return_value=manager),
            patch.object(reflect_tracker, "reflect_tracker_manager", tracker_manager),
        ):
            self.assertTrue(await expression_reflector._check_tracker_exists("qq:10001:private"))
            self.assertFalse(await expression_reflector._check_tracker_exists("qq:20002:group"))
            self.assertTrue(await expression_reflector._check_tracker_exists("existing-stream"))
            self.assertFalse(await expression_reflector._check_tracker_exists("bad:10001:unknown"))

        self.assertEqual(manager.get_or_create_stream.await_count, 2)
        manager.get_stream.assert_called_once_with("existing-stream")

    async def test_send_to_operator_registers_tracker_and_sends_text(self) -> None:
        chat_stream = SimpleNamespace(stream_id="operator-stream")
        manager = SimpleNamespace(get_or_create_stream=AsyncMock(return_value=chat_stream), get_stream=Mock())
        tracker = object()
        tracker_manager = SimpleNamespace(add_tracker=Mock())
        expr = SimpleNamespace(id=7, situation="问候", style="短句")

        with (
            patch.object(expression_reflector, "get_chat_manager", return_value=manager),
            patch.object(reflect_tracker, "ReflectTracker", return_value=tracker) as tracker_cls,
            patch.object(reflect_tracker, "reflect_tracker_manager", tracker_manager),
            patch.object(expression_reflector.send_api, "text_to_stream", new=AsyncMock()) as text_to_stream,
            patch.object(expression_reflector.time, "time", return_value=100.0),
        ):
            await expression_reflector._send_to_operator("qq:10001:private", "请检查", expr)

        tracker_cls.assert_called_once_with(chat_stream=chat_stream, expression=expr, created_time=100.0)
        tracker_manager.add_tracker.assert_called_once_with("operator-stream", tracker)
        text_to_stream.assert_awaited_once_with(text="请检查", stream_id="operator-stream", typing=True)
        self.assertIn("问候", expression_reflector._generate_ask_text(expr))

    async def test_reflect_tracker_approves_rejects_ignores_timeouts_and_manager_caches_trackers(self) -> None:
        def make_tracker(response: str):
            expression = SimpleNamespace(
                id=1,
                situation="旧情景",
                style="旧风格",
                checked=False,
                rejected=False,
                modified_by=None,
                save=Mock(),
            )
            tracker = reflect_tracker.ReflectTracker.__new__(reflect_tracker.ReflectTracker)
            tracker.chat_stream = SimpleNamespace(stream_id="chat-1")
            tracker.expression = expression
            tracker.created_time = 90.0
            tracker.last_check_msg_count = 0
            tracker.max_message_count = 30
            tracker.max_duration = 100.0
            tracker.judge_model = SimpleNamespace(generate_response_async=AsyncMock(return_value=(response, None)))
            return tracker, expression

        approve_tracker, approve_expr = make_tracker('{"judgment": "Approve"}')
        with (
            patch.object(reflect_tracker.time, "time", return_value=100.0),
            patch.object(reflect_tracker, "get_raw_msg_by_timestamp_with_chat", return_value=[object()]),
            patch.object(reflect_tracker, "build_readable_messages", return_value="context"),
            patch.object(reflect_tracker.global_prompt_manager, "format_prompt", new=AsyncMock(return_value="prompt")),
        ):
            self.assertTrue(await approve_tracker.trigger_tracker())

        self.assertTrue(approve_expr.checked)
        self.assertFalse(approve_expr.rejected)
        self.assertEqual(approve_expr.modified_by, "ai")
        approve_expr.save.assert_called_once()

        reject_tracker, reject_expr = make_tracker(
            '{"judgment": "Reject", "corrected_situation": "新情景", "corrected_style": "新风格"}'
        )
        with (
            patch.object(reflect_tracker.time, "time", return_value=100.0),
            patch.object(reflect_tracker, "get_raw_msg_by_timestamp_with_chat", return_value=[object()]),
            patch.object(reflect_tracker, "build_readable_messages", return_value="context"),
            patch.object(reflect_tracker.global_prompt_manager, "format_prompt", new=AsyncMock(return_value="prompt")),
        ):
            self.assertTrue(await reject_tracker.trigger_tracker())
        self.assertEqual(reject_expr.situation, "新情景")
        self.assertEqual(reject_expr.style, "新风格")
        self.assertFalse(reject_expr.rejected)

        ignore_tracker, _ = make_tracker('{"judgment": "Ignore"}')
        with (
            patch.object(reflect_tracker.time, "time", return_value=100.0),
            patch.object(reflect_tracker, "get_raw_msg_by_timestamp_with_chat", return_value=[object()]),
            patch.object(reflect_tracker, "build_readable_messages", return_value="context"),
            patch.object(reflect_tracker.global_prompt_manager, "format_prompt", new=AsyncMock(return_value="prompt")),
        ):
            self.assertFalse(await ignore_tracker.trigger_tracker())

        timeout_tracker, _ = make_tracker('{"judgment": "Approve"}')
        timeout_tracker.created_time = 0.0
        with patch.object(reflect_tracker.time, "time", return_value=200.0):
            self.assertTrue(await timeout_tracker.trigger_tracker())

        manager = reflect_tracker.ReflectTrackerManager()
        manager.add_tracker("chat-1", approve_tracker)
        self.assertIs(manager.get_tracker("chat-1"), approve_tracker)
        manager.remove_tracker("chat-1")
        self.assertIsNone(manager.get_tracker("chat-1"))


if __name__ == "__main__":
    unittest.main()
