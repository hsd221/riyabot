import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.chat.brain_chat import brain_chat, brain_planner
from src.chat.message_receive.chat_stream import ChatStream
from src.common.data_models.database_data_model import DatabaseMessages
from src.common.data_models.info_data_model import ActionPlannerInfo, TargetPersonInfo
from src.common.data_models.message_data_model import ReplyContent, ReplySetModel
from src.common.data_models.message_data_model import ReplyContentType
from src.plugin_system.base.component_types import (
    ActionActivationType,
    ActionInfo,
    ComponentType,
)
from maim_message import GroupInfo, UserInfo


def make_action_info(
    name: str,
    *,
    activation_type: ActionActivationType = ActionActivationType.ALWAYS,
    probability: float = 0.0,
    keywords: list[str] | None = None,
) -> ActionInfo:
    return ActionInfo(
        name=name,
        component_type=ComponentType.ACTION,
        description=f"{name} desc",
        action_parameters={"value": "参数说明"},
        action_require=["需要上下文"],
        activation_type=activation_type,
        random_activation_probability=probability,
        activation_keywords=keywords or [],
    )


def make_db_message(message_id: str = "msg-1", *, text: str = "hello") -> DatabaseMessages:
    return DatabaseMessages(
        message_id=message_id,
        time=10.0,
        chat_id="stream-1",
        processed_plain_text=text,
        user_id="user-1",
        user_nickname="Alice",
        user_platform="qq",
        chat_info_stream_id="stream-1",
        chat_info_platform="qq",
        chat_info_user_id="user-1",
        chat_info_user_nickname="Alice",
        chat_info_user_platform="qq",
    )


def make_stream() -> ChatStream:
    return ChatStream(
        stream_id="stream-1",
        platform="qq",
        user_info=UserInfo(platform="qq", user_id="user-1", user_nickname="Alice"),
        group_info=GroupInfo(platform="qq", group_id="group-1", group_name="Group"),
    )


class BrainPlannerUnitTest(unittest.IsolatedAsyncioTestCase):
    def make_planner(self) -> brain_planner.BrainPlanner:
        planner = brain_planner.BrainPlanner.__new__(brain_planner.BrainPlanner)
        planner.chat_id = "stream-1"
        planner.log_prefix = "[stream-1]"
        planner.action_manager = SimpleNamespace(get_using_actions=Mock(return_value={"plugin": object()}))
        planner.planner_llm = SimpleNamespace()
        planner.last_obs_time_mark = 0.0
        planner.plan_log = []
        return planner

    def test_parse_single_action_resolves_target_fallbacks_and_normalizes_actions(self) -> None:
        planner = self.make_planner()
        latest = make_db_message("db-2", text="latest")
        message_id_list = [("m1", make_db_message("db-1")), ("m2", latest)]
        plugin_info = make_action_info("plugin")

        reply = planner._parse_single_action(
            {"action": "reply", "target_message_id": "m1", "reason": "回复", "extra": 1},
            message_id_list,
            [("plugin", plugin_info)],
        )[0]
        self.assertEqual(reply.action_type, "reply")
        self.assertEqual(reply.reasoning, "回复")
        self.assertEqual(reply.action_data, {"target_message_id": "m1", "extra": 1})
        self.assertEqual(reply.action_message.message_id, "db-1")

        missing_target = planner._parse_single_action(
            {"action": "wait", "target_message_id": "missing", "wait_seconds": 3},
            message_id_list,
            [("plugin", plugin_info)],
        )[0]
        self.assertEqual(missing_target.action_type, "wait")
        self.assertIs(missing_target.action_message, latest)

        listening = planner._parse_single_action(
            {"action": "listening", "reason": "听"},
            message_id_list,
            [],
        )[0]
        self.assertEqual(listening.action_type, "wait")

        invalid = planner._parse_single_action(
            {"action": "bad_action", "reason": "bad"},
            message_id_list,
            [("plugin", plugin_info)],
        )[0]
        self.assertEqual(invalid.action_type, "complete_talk")
        self.assertIn("bad_action", invalid.reasoning)

    def test_extract_json_from_markdown_supports_fenced_arrays_comments_and_incomplete_blocks(self) -> None:
        planner = self.make_planner()
        content = """
        这里是理由
        ```json
        // comment
        [{"action": "reply", "reason": "ok"}, {"action": "wait", "wait_seconds": 2}]
        ```
        """
        json_objects, reasoning = planner._extract_json_from_markdown(content)

        self.assertEqual([item["action"] for item in json_objects], ["reply", "wait"])
        self.assertEqual(reasoning, "这里是理由")

        incomplete, incomplete_reason = planner._extract_json_from_markdown(
            '理由\n```json\n{"action": "complete_talk", "reason": "done"}'
        )
        self.assertEqual(incomplete, [{"action": "complete_talk", "reason": "done"}])
        self.assertEqual(incomplete_reason, "理由")

        empty, empty_reason = planner._extract_json_from_markdown("没有 json")
        self.assertEqual(empty, [])
        self.assertEqual(empty_reason, "")

    def test_filter_action_activation_types_and_plan_log_limit(self) -> None:
        planner = self.make_planner()
        actions = {
            "never": make_action_info("never", activation_type=ActionActivationType.NEVER),
            "always": make_action_info("always", activation_type=ActionActivationType.ALWAYS),
            "random_hit": make_action_info(
                "random_hit",
                activation_type=ActionActivationType.RANDOM,
                probability=0.8,
            ),
            "keyword": make_action_info(
                "keyword",
                activation_type=ActionActivationType.KEYWORD,
                keywords=["猫"],
            ),
            "keyword_miss": make_action_info(
                "keyword_miss",
                activation_type=ActionActivationType.KEYWORD,
                keywords=["狗"],
            ),
        }

        with patch.object(brain_planner.random, "random", return_value=0.5):
            filtered = planner._filter_actions_by_activation_type(actions, "今天聊猫")

        self.assertEqual(set(filtered), {"always", "random_hit", "keyword"})

        for index in range(22):
            planner.add_plan_log(f"reason-{index}", [])

        self.assertEqual(len(planner.plan_log), 20)
        self.assertEqual(planner.plan_log[0][0], "reason-2")
        self.assertEqual(planner._create_complete_talk("done", actions)[0].action_type, "complete_talk")

    async def test_build_action_options_and_get_necessary_info_use_registered_actions(self) -> None:
        planner = self.make_planner()
        prompt = SimpleNamespace(
            format=Mock(
                side_effect=lambda **kwargs: (
                    f"{kwargs['action_name']}|{kwargs['action_description']}|"
                    f"{kwargs['action_parameters']}|{kwargs['action_require']}"
                )
            )
        )

        with patch.object(brain_planner.global_prompt_manager, "get_prompt_async", new=AsyncMock(return_value=prompt)):
            block = await planner._build_action_options_block({"plugin": make_action_info("plugin")})

        self.assertIn("plugin|plugin desc", block)
        self.assertIn('"value":"参数说明"', block)
        self.assertIn("- 需要上下文", block)
        self.assertEqual(await planner._build_action_options_block({}), "")

        registered = {"plugin": make_action_info("plugin")}
        with (
            patch.object(
                brain_planner, "get_chat_type_and_target_info", return_value=(False, TargetPersonInfo(user_id="u"))
            ),
            patch.object(brain_planner.component_registry, "get_components_by_type", return_value=registered),
        ):
            is_group, target, available = planner.get_necessary_info()

        self.assertFalse(is_group)
        self.assertEqual(target.user_id, "u")
        self.assertEqual(available, registered)

    async def test_execute_main_planner_parses_llm_output_and_falls_back_on_errors(self) -> None:
        planner = self.make_planner()
        planner.planner_llm = SimpleNamespace(
            generate_response_async=AsyncMock(
                return_value=(
                    '理由\n```json\n{"action":"reply","target_message_id":"m1","reason":"回复"}\n```',
                    ("raw reasoning", None, None),
                )
            )
        )
        available = {"plugin": make_action_info("plugin")}

        with patch.object(
            brain_planner.global_config,
            "debug",
            SimpleNamespace(show_planner_prompt=False),
        ):
            reasoning, actions, raw, raw_reasoning, duration = await planner._execute_main_planner(
                prompt="prompt",
                message_id_list=[("m1", make_db_message("db-1"))],
                filtered_actions={},
                available_actions=available,
                loop_start_time=123.0,
            )

        self.assertEqual(reasoning, "理由")
        self.assertEqual(actions[0].action_type, "reply")
        self.assertEqual(actions[0].action_data["loop_start_time"], 123.0)
        self.assertEqual(raw, '理由\n```json\n{"action":"reply","target_message_id":"m1","reason":"回复"}\n```')
        self.assertEqual(raw_reasoning, "raw reasoning")
        self.assertIsNotNone(duration)

        planner.planner_llm = SimpleNamespace(generate_response_async=AsyncMock(side_effect=RuntimeError("llm down")))
        reasoning, actions, raw, raw_reasoning, duration = await planner._execute_main_planner(
            prompt="prompt",
            message_id_list=[],
            filtered_actions={},
            available_actions=available,
            loop_start_time=0.0,
        )

        self.assertIn("LLM 请求失败", reasoning)
        self.assertEqual(actions[0].action_type, "complete_talk")
        self.assertIsNone(raw)
        self.assertIsNone(raw_reasoning)
        self.assertIsNone(duration)

    async def test_plan_respects_event_cancellation_and_modified_prompt(self) -> None:
        planner = self.make_planner()
        planner.get_necessary_info = Mock(return_value=(False, TargetPersonInfo(person_name="Alice"), {}))
        planner.build_planner_prompt = AsyncMock(return_value=("original prompt", [("m1", make_db_message())]))
        planner._execute_main_planner = AsyncMock(return_value=("reason", [], "raw", None, 1.0))
        fake_chat_config = SimpleNamespace(max_context_size=10)

        with (
            patch.object(brain_planner.global_config, "chat", fake_chat_config),
            patch.object(brain_planner, "get_raw_msg_before_timestamp_with_chat", return_value=[make_db_message()]),
            patch.object(
                brain_planner, "build_readable_messages_with_id", return_value=("chat", [("m1", make_db_message())])
            ),
            patch.object(brain_planner.events_manager, "handle_mai_events", new=AsyncMock(return_value=(False, None))),
        ):
            cancelled = await planner.plan({}, loop_start_time=1.0)

        self.assertEqual(cancelled[0].action_type, "complete_talk")
        self.assertEqual(cancelled[0].reasoning, "规划 hook 取消本轮规划")

        modified_message = SimpleNamespace(
            _modify_flags=SimpleNamespace(modify_llm_prompt=True),
            llm_prompt="modified prompt",
        )
        with (
            patch.object(brain_planner.global_config, "chat", fake_chat_config),
            patch.object(brain_planner, "get_raw_msg_before_timestamp_with_chat", return_value=[make_db_message()]),
            patch.object(
                brain_planner, "build_readable_messages_with_id", return_value=("chat", [("m1", make_db_message())])
            ),
            patch.object(
                brain_planner.events_manager, "handle_mai_events", new=AsyncMock(return_value=(True, modified_message))
            ),
            patch.object(brain_planner.PlanReplyLogger, "log_plan"),
        ):
            await planner.plan({}, loop_start_time=2.0)

        self.assertEqual(planner._execute_main_planner.await_args.kwargs["prompt"], "modified prompt")


class BrainChattingUnitTest(unittest.IsolatedAsyncioTestCase):
    def make_chat(self) -> brain_chat.BrainChatting:
        chat = brain_chat.BrainChatting.__new__(brain_chat.BrainChatting)
        chat.stream_id = "stream-1"
        chat.chat_stream = make_stream()
        chat.log_prefix = "[stream-1]"
        chat.running = False
        chat._loop_task = None
        chat._new_message_event = asyncio.Event()
        chat.history_loop = []
        chat._cycle_counter = 0
        chat._current_cycle_detail = None
        chat.last_read_time = 1.0
        chat.action_manager = SimpleNamespace()
        chat._last_successful_reply = False
        chat.message_archiver = None
        chat.topic_summarizer = None
        return chat

    async def test_start_cycle_end_cycle_and_loop_completion_are_stable(self) -> None:
        chat = self.make_chat()
        loop_info = {
            "loop_plan_info": {"ok": True},
            "loop_action_info": {"action_taken": False},
        }
        with patch.object(brain_chat.time, "time", return_value=10.25):
            timers, thinking_id = chat.start_cycle()
            chat.end_cycle(loop_info, {"step": 0.5})

        self.assertEqual(timers, {})
        self.assertEqual(thinking_id, "tid10.25")
        self.assertEqual(len(chat.history_loop), 1)
        self.assertEqual(chat.history_loop[0].loop_plan_info, {"ok": True})
        self.assertEqual(chat.history_loop[0].loop_action_info, {"action_taken": False})
        self.assertEqual(chat.history_loop[0].timers, {"step": 0.5})

        done_task = asyncio.Future()
        done_task.set_result(None)
        chat._handle_loop_completion(done_task)

        failed_task = asyncio.Future()
        failed_task.set_exception(RuntimeError("boom"))
        chat._handle_loop_completion(failed_task)

    async def test_handle_action_uses_action_manager_and_handles_failures(self) -> None:
        chat = self.make_chat()
        handler = SimpleNamespace(execute=AsyncMock(return_value=(True, "done text")))
        chat.action_manager = SimpleNamespace(create_action=Mock(return_value=handler))

        success, action_text, command = await chat._handle_action(
            "plugin",
            "reason",
            {"x": 1},
            {},
            "tid1",
            make_db_message(),
        )

        self.assertTrue(success)
        self.assertEqual(action_text, "done text")
        self.assertEqual(command, "")
        self.assertEqual(chat.action_manager.create_action.call_args.kwargs["action_name"], "plugin")

        chat.action_manager = SimpleNamespace(create_action=Mock(return_value=None))
        self.assertEqual(await chat._handle_action("missing", "", {}, {}, "tid1"), (False, "", ""))

        chat.action_manager = SimpleNamespace(create_action=Mock(side_effect=RuntimeError("factory down")))
        self.assertEqual(await chat._handle_action("bad", "", {}, {}, "tid1"), (False, "", ""))

        chat.action_manager = SimpleNamespace(
            create_action=Mock(return_value=SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("run down"))))
        )
        self.assertEqual(await chat._handle_action("bad", "", {}, {}, "tid1"), (False, "", ""))

    async def test_send_response_sends_only_text_parts_and_uses_reply_for_first_message_when_needed(self) -> None:
        chat = self.make_chat()
        reply_set = ReplySetModel(
            reply_data=[
                ReplyContent(content_type=ReplyContentType.TEXT, content="第一句"),
                ReplyContent(content_type=ReplyContentType.EMOJI, content="ignored"),
                ReplyContent(content_type=ReplyContentType.TEXT, content="第二句"),
            ]
        )
        action_message = make_db_message()

        with (
            patch.object(brain_chat.message_api, "count_new_messages", return_value=3),
            patch.object(brain_chat.random, "randint", return_value=3),
            patch.object(brain_chat.send_api, "text_to_stream", new=AsyncMock()) as text_to_stream,
        ):
            reply_text = await chat._send_response(reply_set, action_message, selected_expressions=[1])

        self.assertEqual(reply_text, "第一句第二句")
        self.assertEqual(text_to_stream.await_count, 2)
        first_kwargs = text_to_stream.await_args_list[0].kwargs
        second_kwargs = text_to_stream.await_args_list[1].kwargs
        self.assertTrue(first_kwargs["set_reply"])
        self.assertFalse(first_kwargs["typing"])
        self.assertFalse(second_kwargs["set_reply"])
        self.assertTrue(second_kwargs["typing"])
        self.assertEqual(first_kwargs["selected_expressions"], [1])

    async def test_execute_action_handles_complete_wait_listening_plugin_and_reply_paths(self) -> None:
        chat = self.make_chat()
        available_actions = {"plugin": make_action_info("plugin")}

        with patch.object(brain_chat.database_api, "store_action_info", new=AsyncMock()) as store_action:
            complete = await chat._execute_action(
                ActionPlannerInfo(action_type="complete_talk", reasoning="done", action_data={}),
                [],
                "tid1",
                available_actions,
                {},
            )
        self.assertEqual(complete, {"action_type": "complete_talk", "success": True, "reply_text": "", "command": ""})
        store_action.assert_awaited_once()

        chat._new_message_event = SimpleNamespace(clear=Mock(), wait=Mock(return_value="event-token"))
        with (
            patch.object(brain_chat.database_api, "store_action_info", new=AsyncMock()),
            patch.object(brain_chat.asyncio, "wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)),
        ):
            wait_result = await chat._execute_action(
                ActionPlannerInfo(action_type="wait", reasoning="等等", action_data={"wait_seconds": "-1"}),
                [],
                "tid1",
                available_actions,
                {},
            )
        self.assertEqual(wait_result["action_type"], "wait")
        self.assertTrue(wait_result["success"])
        self.assertFalse(chat._last_successful_reply)

        chat._new_message_event = SimpleNamespace(clear=Mock(), wait=Mock(return_value="event-token"))
        with (
            patch.object(brain_chat.database_api, "store_action_info", new=AsyncMock()),
            patch.object(brain_chat.asyncio, "wait_for", new=AsyncMock(return_value=True)),
        ):
            listening_result = await chat._execute_action(
                ActionPlannerInfo(action_type="listening", reasoning="听", action_data={}),
                [],
                "tid1",
                available_actions,
                {},
            )
        self.assertEqual(listening_result["action_type"], "listening")
        self.assertTrue(listening_result["success"])

        chat._handle_action = AsyncMock(return_value=(True, "plugin text", "cmd"))
        plugin_result = await chat._execute_action(
            ActionPlannerInfo(action_type="plugin", reasoning="do", action_data={}, action_message=make_db_message()),
            [],
            "tid1",
            available_actions,
            {},
        )
        self.assertEqual(
            plugin_result, {"action_type": "plugin", "success": True, "reply_text": "plugin text", "command": "cmd"}
        )
        self.assertFalse(chat._last_successful_reply)

        llm_response = SimpleNamespace(
            reply_set=ReplySetModel(reply_data=[ReplyContent(content_type=ReplyContentType.TEXT, content="hi")]),
            selected_expressions=[2],
            retrieved_atom_ids=[],
        )
        chat._send_and_store_reply = AsyncMock(return_value=({"loop": "info"}, "hi", {}))
        with patch.object(brain_chat.generator_api, "generate_reply", new=AsyncMock(return_value=(True, llm_response))):
            reply_result = await chat._execute_action(
                ActionPlannerInfo(
                    action_type="reply",
                    reasoning="reply",
                    action_data={"unknown_words": [" 词 ", "", 1]},
                    action_message=make_db_message(),
                ),
                [],
                "tid1",
                available_actions,
                {},
            )

        self.assertEqual(reply_result["action_type"], "reply")
        self.assertTrue(reply_result["success"])
        self.assertEqual(reply_result["reply_text"], "hi")
        self.assertTrue(chat._last_successful_reply)

        with patch.object(brain_chat.generator_api, "generate_reply", new=AsyncMock(return_value=(False, None))):
            failed_reply = await chat._execute_action(
                ActionPlannerInfo(
                    action_type="reply", reasoning="reply", action_data={}, action_message=make_db_message()
                ),
                [],
                "tid1",
                available_actions,
                {},
            )
        self.assertFalse(failed_reply["success"])


if __name__ == "__main__":
    unittest.main()
