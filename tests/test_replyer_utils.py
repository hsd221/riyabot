import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.chat.replyer import group_generator, private_generator, replyer_manager
from src.chat.utils.structured_prompt import DYNAMIC_CONTEXT_BOUNDARY
from src.common.data_models.info_data_model import ActionPlannerInfo, TargetPersonInfo
from src.plugin_system.base.component_types import ActionInfo, ComponentType


def make_action_info(name: str, description: str = "") -> ActionInfo:
    return ActionInfo(
        name=name,
        component_type=ComponentType.ACTION,
        description=description or f"{name} desc",
    )


def make_stream(*, stream_id: str = "stream-1", group: bool = True):
    return SimpleNamespace(
        stream_id=stream_id,
        platform="qq",
        group_info=SimpleNamespace(group_id="group-1") if group else None,
    )


def make_group_replyer() -> group_generator.DefaultReplyer:
    replyer = group_generator.DefaultReplyer.__new__(group_generator.DefaultReplyer)
    replyer.chat_stream = make_stream(group=True)
    replyer.chat_target_info = TargetPersonInfo(person_name="Group")
    replyer.tool_executor = SimpleNamespace()
    replyer._last_retrieved_atom_ids = []
    replyer.express_model = SimpleNamespace()
    return replyer


def make_private_replyer() -> private_generator.PrivateReplyer:
    replyer = private_generator.PrivateReplyer.__new__(private_generator.PrivateReplyer)
    replyer.chat_stream = make_stream(group=False)
    replyer.chat_target_info = TargetPersonInfo(person_name="Alice", user_nickname="AliceNick")
    replyer.tool_executor = SimpleNamespace()
    replyer._last_retrieved_atom_ids = []
    replyer.express_model = SimpleNamespace()
    return replyer


class ReplyerManagerTest(unittest.TestCase):
    def test_manager_returns_none_without_stream_id_and_caches_group_or_private_replyers(self) -> None:
        class FakeDefaultReplyer:
            def __init__(self, chat_stream, request_type: str = "replyer"):
                self.chat_stream = chat_stream
                self.request_type = request_type

        class FakePrivateReplyer:
            def __init__(self, chat_stream, request_type: str = "replyer"):
                self.chat_stream = chat_stream
                self.request_type = request_type

        manager = replyer_manager.ReplyerManager()

        with (
            patch.object(replyer_manager, "DefaultReplyer", FakeDefaultReplyer),
            patch.object(replyer_manager, "PrivateReplyer", FakePrivateReplyer),
        ):
            self.assertIsNone(manager.get_replyer())

            group_stream = make_stream(stream_id="group-stream", group=True)
            group_replyer = manager.get_replyer(group_stream, request_type="first")
            self.assertIsInstance(group_replyer, FakeDefaultReplyer)
            self.assertIs(manager.get_replyer(group_stream, request_type="ignored"), group_replyer)
            self.assertEqual(group_replyer.request_type, "first")

            private_stream = make_stream(stream_id="private-stream", group=False)
            fake_chat_manager = SimpleNamespace(get_stream=Mock(return_value=private_stream))
            with patch.object(replyer_manager, "get_chat_manager", return_value=fake_chat_manager):
                private_replyer = manager.get_replyer(chat_id="private-stream", request_type="private")

            self.assertIsInstance(private_replyer, FakePrivateReplyer)
            self.assertEqual(private_replyer.chat_stream, private_stream)

            fake_chat_manager = SimpleNamespace(get_stream=Mock(return_value=None))
            with patch.object(replyer_manager, "get_chat_manager", return_value=fake_chat_manager):
                self.assertIsNone(manager.get_replyer(chat_id="missing"))


class ReplyerSharedHelpersTest(unittest.IsolatedAsyncioTestCase):
    async def test_main_reply_prompts_use_jsonl_for_the_full_chat_history(self) -> None:
        group_replyer = make_group_replyer()
        group_replyer.build_expression_habits = AsyncMock(return_value=("", []))
        group_replyer.build_behavior_reference = AsyncMock(return_value="")
        group_replyer.build_tool_info = AsyncMock(return_value="")
        group_replyer.get_prompt_info = AsyncMock(return_value="")
        group_replyer.build_actions_prompt = AsyncMock(return_value="")
        group_replyer.build_personality_prompt = AsyncMock(return_value="identity")
        group_replyer._build_jargon_explanation = AsyncMock(return_value="")
        group_replyer.build_keywords_reaction_prompt = AsyncMock(return_value="")
        group_replyer.get_chat_prompt_for_chat = Mock(return_value="")

        with (
            patch.object(group_generator.global_config, "chat", SimpleNamespace(max_context_size=10)),
            patch.object(group_generator.global_config, "personality", SimpleNamespace(reply_style="自然")),
            patch.object(group_generator.global_config, "bot", SimpleNamespace(nickname="Riya")),
            patch.object(
                group_generator,
                "get_raw_msg_before_timestamp_with_chat",
                side_effect=[[object()], []],
            ),
            patch.object(
                group_generator,
                "build_readable_messages",
                side_effect=["short-history", "structured-group-history"],
            ) as group_build_messages,
            patch.object(
                group_generator,
                "build_memory_retrieval_prompt",
                new=AsyncMock(return_value=("", [])),
            ),
        ):
            group_prompt, *_ = await group_replyer.build_prompt_reply_context(reply_time_point=10.0)

        self.assertIn("structured-group-history", group_prompt)
        self.assertNotIn("output_format", group_build_messages.call_args_list[0].kwargs)
        self.assertEqual(group_build_messages.call_args_list[1].kwargs["output_format"], "jsonl")

        private_replyer = make_private_replyer()
        private_replyer.build_expression_habits = AsyncMock(return_value=("", []))
        private_replyer.build_behavior_reference = AsyncMock(return_value="")
        private_replyer.build_tool_info = AsyncMock(return_value="")
        private_replyer.get_prompt_info = AsyncMock(return_value="")
        private_replyer.build_actions_prompt = AsyncMock(return_value="")
        private_replyer.build_personality_prompt = AsyncMock(return_value="identity")
        private_replyer.build_keywords_reaction_prompt = AsyncMock(return_value="")
        private_replyer.get_chat_prompt_for_chat = Mock(return_value="")

        with (
            patch.object(private_generator.global_config, "chat", SimpleNamespace(max_context_size=10)),
            patch.object(private_generator.global_config, "personality", SimpleNamespace(reply_style="自然")),
            patch.object(
                private_generator.global_config,
                "bot",
                SimpleNamespace(qq_account="bot", platforms=[], nickname="Riya"),
            ),
            patch.object(
                private_generator.global_config,
                "expression",
                SimpleNamespace(enable_jargon_explanation=False),
            ),
            patch.object(
                private_generator,
                "get_raw_msg_before_timestamp_with_chat",
                side_effect=[[object()], []],
            ),
            patch.object(
                private_generator,
                "build_readable_messages",
                side_effect=["structured-private-history", "short-history"],
            ) as private_build_messages,
            patch.object(
                private_generator,
                "build_memory_retrieval_prompt",
                new=AsyncMock(return_value=("", [])),
            ),
        ):
            private_prompt, _ = await private_replyer.build_prompt_reply_context()

        self.assertIn("structured-private-history", private_prompt)
        self.assertEqual(private_build_messages.call_args_list[0].kwargs["output_format"], "jsonl")
        self.assertNotIn("output_format", private_build_messages.call_args_list[1].kwargs)

    async def test_replyers_send_stable_rules_and_dynamic_context_as_distinct_roles(self) -> None:
        prompt = f"稳定回复规则\n{DYNAMIC_CONTEXT_BOUNDARY}\n本轮回复输入"

        for replyer in (make_group_replyer(), make_private_replyer()):
            with self.subTest(replyer=type(replyer).__name__):
                replyer.express_model = SimpleNamespace(
                    generate_response_async=AsyncMock(return_value=(" 回复内容 ", ("推理", "model-x", None)))
                )

                content, reasoning, model_name, tool_calls = await replyer.llm_generate_content(prompt)

                self.assertEqual(content, "回复内容")
                self.assertEqual(reasoning, "推理")
                self.assertEqual(model_name, "model-x")
                self.assertIsNone(tool_calls)
                replyer.express_model.generate_response_async.assert_awaited_once_with(
                    prompt="本轮回复输入",
                    system_prompt="稳定回复规则",
                )

    def test_reply_target_and_picid_helpers_handle_text_pictures_and_missing_targets(self) -> None:
        group_replyer = make_group_replyer()
        private_replyer = make_private_replyer()

        for replyer, module in (
            (group_replyer, group_generator),
            (private_replyer, private_generator),
        ):
            self.assertEqual(replyer._parse_reply_target(None), ("", ""))
            self.assertEqual(replyer._parse_reply_target("Alice: hello: again"), ("Alice", "hello: again"))
            self.assertEqual(replyer._parse_reply_target("Bob：你好"), ("Bob", "你好"))
            self.assertEqual(replyer._parse_reply_target("no delimiter"), ("", ""))

            with patch.object(module, "_translate_pid_to_description", side_effect=lambda pic_id: f"desc-{pic_id}"):
                self.assertEqual(
                    replyer._replace_picids_with_descriptions("看 [picid:p1] 和 [picid:p2]"),
                    "看 [图片：desc-p1] 和 [图片：desc-p2]",
                )
                only_pic = replyer._analyze_target_content("[picid:p1]")
                mixed = replyer._analyze_target_content("hello [picid:p2] world")

            self.assertEqual(only_pic, (True, False, "[图片:desc-p1]", ""))
            self.assertFalse(mixed[0])
            self.assertTrue(mixed[1])
            self.assertEqual(mixed[2], "[图片:desc-p2]")
            self.assertIn("hello", mixed[3])
            self.assertIn("world", mixed[3])
            self.assertEqual(replyer._analyze_target_content("  "), (False, False, "", ""))

    async def test_keyword_actions_personality_and_chat_prompt_helpers_are_stable(self) -> None:
        group_replyer = make_group_replyer()
        private_replyer = make_private_replyer()
        keyword_config = SimpleNamespace(
            keyword_rules=[SimpleNamespace(keywords=["猫", "cat"], reaction="夸猫")],
            regex_rules=[SimpleNamespace(regex=[r"天气(?P<city>\w+)"], reaction="查询[city]天气")],
        )
        bot_config = SimpleNamespace(nickname="Mai", alias_names=["小麦"])
        personality_config = SimpleNamespace(
            personality="友善",
            states=["困倦"],
            state_probability=1.0,
        )
        chat_manager = SimpleNamespace(
            get_stream_id=Mock(side_effect=lambda platform, target_id, is_group: f"{platform}:{target_id}:{is_group}")
        )
        experimental = SimpleNamespace(
            chat_prompts=[
                "bad",
                123,
                "qq:123:group:群聊额外提示:带冒号",
                "qq:456:private:私聊额外提示",
            ]
        )

        for replyer, module, expected_chat_id, absent_chat_id in (
            (group_replyer, group_generator, "qq:123:True", "qq:456:False"),
            (private_replyer, private_generator, "qq:456:False", "qq:123:True"),
        ):
            with patch.object(module.global_config, "keyword_reaction", keyword_config):
                self.assertEqual(await replyer.build_keywords_reaction_prompt(None), "")
                reaction = await replyer.build_keywords_reaction_prompt("猫在天气Shanghai")

            self.assertIn("夸猫，", reaction)
            self.assertIn("查询Shanghai天气，", reaction)

            actions = {
                "reply": make_action_info("reply", "skip"),
                "plugin": make_action_info("plugin", "插件说明"),
            }
            chosen = [
                ActionPlannerInfo(action_type="plugin", reasoning="需要插件"),
                ActionPlannerInfo(action_type="missing", reasoning=None),
                ActionPlannerInfo(action_type="reply", reasoning="skip"),
            ]
            actions_prompt = await replyer.build_actions_prompt(actions, chosen)
            self.assertIn("- plugin: 插件说明", actions_prompt)
            self.assertIn("- plugin: 插件说明，原因：需要插件", actions_prompt)
            self.assertIn("- missing: 无描述，原因：无原因", actions_prompt)
            self.assertNotIn("- reply", actions_prompt)

            with (
                patch.object(module.global_config, "bot", bot_config),
                patch.object(module.global_config, "personality", personality_config),
                patch.object(module.random, "random", return_value=0.0),
                patch.object(module.random, "choice", return_value="困倦"),
            ):
                self.assertEqual(await replyer.build_personality_prompt(), "你的名字是Mai,也有人叫你小麦，你友善;")

            with (
                patch.object(module.global_config, "experimental", experimental),
                patch("src.chat.message_receive.chat_stream.get_chat_manager", return_value=chat_manager),
            ):
                self.assertEqual(
                    replyer.get_chat_prompt_for_chat(expected_chat_id),
                    experimental.chat_prompts[-2 if module is group_generator else -1].split(":", 3)[3],
                )
                self.assertEqual(replyer.get_chat_prompt_for_chat(absent_chat_id), "")
                self.assertIsNone(replyer._parse_chat_prompt_config_to_chat_id("bad"))

    async def test_tool_expression_and_timing_helpers_use_fakes_without_external_effects(self) -> None:
        group_replyer = make_group_replyer()
        private_replyer = make_private_replyer()

        group_replyer.tool_executor = SimpleNamespace(
            execute_from_chat_message=AsyncMock(
                return_value=([{"tool_name": "weather", "content": "晴", "type": "tool_result"}], None, None)
            )
        )
        private_replyer.tool_executor = SimpleNamespace(
            execute_from_chat_message=AsyncMock(
                return_value=([{"tool_name": "calc", "content": "42", "type": "answer"}], None, None)
            )
        )

        self.assertEqual(await group_replyer.build_tool_info("", "", "", enable_tool=False), "")
        self.assertIn("- 【weather】: 晴", await group_replyer.build_tool_info("history", "Alice", "target"))
        self.assertIn("- 【calc】answer: 42", await private_replyer.build_tool_info("history", "Alice", "target"))

        group_replyer.tool_executor = SimpleNamespace(
            execute_from_chat_message=AsyncMock(side_effect=RuntimeError("tool down"))
        )
        self.assertEqual(await group_replyer.build_tool_info("history", "Alice", "target"), "")

        expression_config_disabled = SimpleNamespace(
            get_expression_config_for_chat=Mock(return_value=(False, None, None))
        )
        expression_config_enabled = SimpleNamespace(
            get_expression_config_for_chat=Mock(return_value=(True, None, None))
        )

        with patch.object(group_generator.global_config, "expression", expression_config_disabled):
            self.assertEqual(await group_replyer.build_expression_habits("history", "target"), ("", []))

        with (
            patch.object(group_generator.global_config, "expression", expression_config_enabled),
            patch.object(
                group_generator.expression_selector,
                "select_suitable_expressions",
                new=AsyncMock(
                    return_value=(
                        [{"situation": "开心", "style": "短句"}, {"bad": "ignored"}],
                        [1, 2],
                    )
                ),
            ) as selector,
        ):
            habits, ids = await group_replyer.build_expression_habits("history", "target", "reason", think_level=2)

        self.assertIn("当开心时：短句", habits)
        self.assertEqual(ids, [1, 2])
        self.assertEqual(selector.await_args.kwargs["think_level"], 2)

        async def value():
            return "done"

        with patch.object(group_generator.time, "time", side_effect=[10.0, 12.5]):
            name, result, duration = await group_replyer._time_and_run_task(value(), "task")

        self.assertEqual((name, result, duration), ("task", "done", 2.5))

    async def test_group_jargon_helpers_clean_unknown_words_and_fallback_on_failures(self) -> None:
        replyer = make_group_replyer()

        self.assertEqual(await replyer._build_unknown_words_jargon(None, "stream-1"), "")
        self.assertEqual(await replyer._build_unknown_words_jargon(["", 1, "  "], "stream-1"), "")

        with patch.object(
            group_generator,
            "retrieve_concepts_with_jargon",
            new=AsyncMock(return_value="黑话解释"),
        ) as retrieve:
            self.assertEqual(await replyer._build_unknown_words_jargon(["  梗  ", 1, ""], "stream-1"), "黑话解释")

        retrieve.assert_awaited_once_with(["梗"], "stream-1")

        with patch.object(
            group_generator,
            "retrieve_concepts_with_jargon",
            new=AsyncMock(side_effect=RuntimeError("down")),
        ):
            self.assertEqual(await replyer._build_unknown_words_jargon(["梗"], "stream-1"), "")

        with patch.object(
            group_generator.global_config,
            "expression",
            SimpleNamespace(enable_jargon_explanation=False, jargon_mode="context"),
        ):
            self.assertEqual(await replyer._build_jargon_explanation("stream-1", [], "history", ["梗"]), "")

        with (
            patch.object(
                group_generator.global_config,
                "expression",
                SimpleNamespace(enable_jargon_explanation=True, jargon_mode="planner"),
            ),
            patch.object(
                replyer, "_build_unknown_words_jargon", new=AsyncMock(return_value="planner解释")
            ) as planner_jargon,
        ):
            self.assertEqual(await replyer._build_jargon_explanation("stream-1", [], "history", ["梗"]), "planner解释")

        planner_jargon.assert_awaited_once_with(["梗"], "stream-1")

        with (
            patch.object(
                group_generator.global_config,
                "expression",
                SimpleNamespace(enable_jargon_explanation=True, jargon_mode="context"),
            ),
            patch.object(group_generator, "explain_jargon_in_context", new=AsyncMock(return_value="context解释")),
        ):
            self.assertEqual(await replyer._build_jargon_explanation("stream-1", [], "history", None), "context解释")

    async def test_group_generate_and_rewrite_reply_cover_prompt_llm_and_failure_paths(self) -> None:
        replyer = make_group_replyer()
        replyer.build_prompt_reply_context = AsyncMock(return_value=("prompt", [7], ["timing"], "zero"))
        replyer.llm_generate_content = AsyncMock(return_value=("content", "reasoning", "model-x", [{"tool": "x"}]))

        with (
            patch(
                "src.plugin_system.core.events_manager.events_manager.handle_mai_events",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch.object(group_generator.PlanReplyLogger, "log_reply") as log_reply,
        ):
            success, response = await replyer.generate_reply_with_context(log_reply=True)

        self.assertTrue(success)
        self.assertEqual(response.prompt, "prompt")
        self.assertEqual(response.content, "content")
        self.assertEqual(response.reasoning, "reasoning")
        self.assertEqual(response.model, "model-x")
        self.assertEqual(response.selected_expressions, [7])
        self.assertEqual(response.tool_calls, [{"tool": "x"}])
        self.assertEqual(response.timing_logs, ["timing"])
        log_reply.assert_called_once()

        replyer.build_prompt_reply_context = AsyncMock(return_value=("", [], [], "zero"))
        success, response = await replyer.generate_reply_with_context(log_reply=False)
        self.assertFalse(success)
        self.assertEqual(response.prompt, "")
        self.assertEqual(response.selected_expressions, [])

        replyer.build_prompt_rewrite_context = AsyncMock(return_value="rewrite prompt")
        replyer.llm_generate_content = AsyncMock(return_value=("rewritten", "rewrite reasoning", "model-y", None))
        success, response = await replyer.rewrite_reply_with_context("raw", "reason", "Alice: hi")

        self.assertTrue(success)
        self.assertEqual(response.prompt, "rewrite prompt")
        self.assertEqual(response.content, "rewritten")
        self.assertEqual(response.reasoning, "rewrite reasoning")
        self.assertEqual(response.model, "model-y")

        replyer.build_prompt_rewrite_context = AsyncMock(return_value="")
        success, response = await replyer.rewrite_reply_with_context("raw", "reason", "Alice: hi")
        self.assertFalse(success)
        self.assertEqual(response.prompt, "")

    async def test_private_generate_reply_applies_event_prompt_and_response_modifications(self) -> None:
        replyer = make_private_replyer()
        replyer._last_retrieved_atom_ids = ["atom-1"]
        replyer.build_prompt_reply_context = AsyncMock(return_value=("prompt", [3]))
        replyer.llm_generate_content = AsyncMock(return_value=("content", "reasoning", "model-z", [{"tool": "z"}]))
        modified_prompt = SimpleNamespace(
            _modify_flags=SimpleNamespace(
                modify_llm_prompt=True,
                modify_llm_response_content=False,
                modify_llm_response_reasoning=False,
            ),
            llm_prompt="modified prompt",
        )
        modified_response = SimpleNamespace(
            _modify_flags=SimpleNamespace(
                modify_llm_prompt=False,
                modify_llm_response_content=True,
                modify_llm_response_reasoning=True,
            ),
            llm_response_content="after content",
            llm_response_reasoning="after reasoning",
        )

        with patch(
            "src.plugin_system.core.events_manager.events_manager.handle_mai_events",
            new=AsyncMock(side_effect=[(True, modified_prompt), (True, modified_response)]),
        ):
            success, response = await replyer.generate_reply_with_context(from_plugin=False, stream_id="stream-1")

        self.assertTrue(success)
        replyer.llm_generate_content.assert_awaited_once_with("modified prompt")
        self.assertEqual(response.prompt, "modified prompt")
        self.assertEqual(response.content, "after content")
        self.assertEqual(response.reasoning, "after reasoning")
        self.assertEqual(response.model, "model-z")
        self.assertEqual(response.retrieved_atom_ids, [])
        self.assertEqual(response.tool_calls, [{"tool": "z"}])


if __name__ == "__main__":
    unittest.main()
