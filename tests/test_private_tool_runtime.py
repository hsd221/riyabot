import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from maim_message import UserInfo

from src.chat.brain_chat import brain_chat, private_tool_pipeline
from src.chat.heart_flow.turn_scheduler import TurnDecision
from src.chat.message_receive.chat_stream import ChatStream
from src.common.data_models.database_data_model import DatabaseMessages
from src.common.data_models.message_data_model import ReplySetModel
from src.config import config as config_module
from src.config.official_configs import ChatConfig, ExperimentalConfig
from src.llm_models.payload_content import ToolCall


def make_stream() -> ChatStream:
    return ChatStream(
        stream_id="stream-1",
        platform="qq",
        user_info=UserInfo(platform="qq", user_id="user-1", user_nickname="Alice"),
        group_info=None,
    )


def make_message(message_id: str = "db-1", user_id: str = "user-1") -> DatabaseMessages:
    return DatabaseMessages(
        message_id=message_id,
        time=10.0,
        chat_id="stream-1",
        processed_plain_text="hello",
        user_id=user_id,
        user_nickname="Alice",
        user_platform="qq",
        chat_info_stream_id="stream-1",
        chat_info_platform="qq",
        chat_info_user_id="user-1",
        chat_info_user_nickname="Alice",
        chat_info_user_platform="qq",
    )


def make_chat() -> brain_chat.BrainChatting:
    chat = brain_chat.BrainChatting.__new__(brain_chat.BrainChatting)
    chat.stream_id = "stream-1"
    chat.chat_stream = make_stream()
    chat.log_prefix = "[stream-1]"
    chat.last_read_time = 1.0
    chat._last_successful_reply = False
    chat._new_message_event = asyncio.Event()
    chat.tool_pipeline = object()
    return chat


def make_decision(message: DatabaseMessages | None = None) -> private_tool_pipeline.PlannerDecision:
    messages_by_id = {"m1": message} if message else {}
    return private_tool_pipeline.PlannerDecision(
        prompt="prompt",
        content="",
        reasoning="需要回复",
        model_name="planner",
        tool_calls=[],
        messages_by_id=messages_by_id,
        started_at=10.0,
    )


class PrivateReplyToolRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_reply_tool_invokes_replyer_without_nested_tools_and_sends_result(self) -> None:
        chat = make_chat()
        message = make_message()
        decision = make_decision(message)
        decision.tool_results.append(
            private_tool_pipeline.ToolExecutionResult(
                call_id="call-lookup",
                tool_name="lookup",
                success=True,
                content="reference answer",
            )
        )
        tool_call = ToolCall(
            "call-1",
            "reply",
            {"target_message_id": "m1", "reply_reason": "回答对方的问题"},
        )
        reply_set = ReplySetModel()
        reply_set.add_text_content("hello")
        llm_response = SimpleNamespace(
            reply_set=reply_set,
            selected_expressions=[1],
            retrieved_atom_ids=[],
        )
        loop_info = {"loop_action_info": {"action_taken": True}}
        chat._send_and_store_reply = AsyncMock(return_value=(loop_info, "hello", {}))
        chat._apply_memory_feedback = AsyncMock()

        with (
            patch.object(
                brain_chat.generator_api,
                "generate_reply",
                new=AsyncMock(return_value=(True, llm_response)),
            ) as generate_reply,
            patch.object(
                brain_chat.message_api,
                "get_messages_by_time_in_chat",
                side_effect=[[], []],
            ) as get_inbound_messages,
        ):
            result = await chat._execute_reply_tool(tool_call, decision, {}, "tid-1")

        self.assertTrue(result.success)
        self.assertTrue(result.terminal)
        self.assertEqual(result.reply_text, "hello")
        self.assertIs(result.loop_info, loop_info)
        kwargs = generate_reply.await_args.kwargs
        self.assertFalse(kwargs["enable_tool"])
        self.assertEqual(kwargs["available_actions"], {})
        self.assertIsNone(kwargs["chosen_actions"])
        self.assertIs(kwargs["reply_message"], message)
        self.assertEqual(kwargs["reply_reason"], "回答对方的问题")
        self.assertIn("lookup", kwargs["extra_info"])
        self.assertIn("reference answer", kwargs["extra_info"])
        self.assertEqual(get_inbound_messages.call_count, 2)
        self.assertTrue(get_inbound_messages.call_args.kwargs["filter_mai"])
        self.assertEqual(get_inbound_messages.call_args.kwargs["limit"], 1)
        chat._apply_memory_feedback.assert_awaited_once_with(llm_response, "hello")

    async def test_reply_tool_rejects_unknown_target_without_calling_replyer(self) -> None:
        chat = make_chat()
        decision = make_decision()
        tool_call = ToolCall("call-1", "reply", {"target_message_id": "missing", "reply_reason": "回答"})

        with patch.object(brain_chat.generator_api, "generate_reply", new=AsyncMock()) as generate_reply:
            result = await chat._execute_reply_tool(tool_call, decision, {}, "tid-1")

        self.assertFalse(result.success)
        self.assertFalse(result.terminal)
        self.assertIn("不存在", result.content)
        generate_reply.assert_not_awaited()

    async def test_reply_tool_rejects_message_not_sent_by_chat_target(self) -> None:
        chat = make_chat()
        decision = make_decision(make_message(user_id="bot-1"))
        tool_call = ToolCall("call-1", "reply", {"target_message_id": "m1", "reply_reason": "回答"})

        with patch.object(brain_chat.generator_api, "generate_reply", new=AsyncMock()) as generate_reply:
            result = await chat._execute_reply_tool(tool_call, decision, {}, "tid-1")

        self.assertFalse(result.success)
        self.assertFalse(result.terminal)
        self.assertIn("不是当前聊天对象", result.content)
        generate_reply.assert_not_awaited()

    async def test_reply_generated_during_new_message_is_discarded_and_replanned(self) -> None:
        chat = make_chat()
        message = make_message()
        decision = make_decision(message)
        tool_call = ToolCall("call-1", "reply", {"target_message_id": "m1", "reply_reason": "回答"})
        reply_set = ReplySetModel()
        reply_set.add_text_content("stale")
        llm_response = SimpleNamespace(
            reply_set=reply_set,
            selected_expressions=None,
            retrieved_atom_ids=[],
        )
        chat._send_and_store_reply = AsyncMock()
        chat._apply_memory_feedback = AsyncMock()

        with (
            patch.object(
                brain_chat.generator_api,
                "generate_reply",
                new=AsyncMock(return_value=(True, llm_response)),
            ),
            patch.object(
                brain_chat.message_api,
                "get_messages_by_time_in_chat",
                side_effect=[[], [make_message("db-2")]],
            ),
        ):
            result = await chat._execute_reply_tool(tool_call, decision, {}, "tid-1")

        self.assertFalse(result.success)
        self.assertFalse(result.terminal)
        self.assertTrue(result.should_continue)
        self.assertIn("新消息", result.content)
        chat._send_and_store_reply.assert_not_awaited()
        chat._apply_memory_feedback.assert_not_awaited()


class PrivateTurnGateRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_native_observe_enters_planner_path_before_legacy_reflection(self) -> None:
        chat = make_chat()
        chat._observe_native = AsyncMock(return_value=False)
        chat._check_reflect_tracker = AsyncMock()
        message = make_message()

        result = await chat._observe([message])

        self.assertFalse(result)
        chat._observe_native.assert_awaited_once_with([message])
        chat._check_reflect_tracker.assert_not_awaited()

    async def test_native_loop_does_not_call_planner_without_new_messages(self) -> None:
        chat = make_chat()
        chat.turn_scheduler = SimpleNamespace(
            decide_private_turn=Mock(
                return_value=TurnDecision(
                    should_observe=False,
                    sleep_seconds=0.1,
                    reason="no_new_private_message",
                )
            )
        )
        chat._observe = AsyncMock()

        with patch.object(brain_chat.message_api, "get_messages_by_time_in_chat", return_value=[]):
            should_continue = await chat._loopbody()

        self.assertFalse(should_continue)
        chat._observe.assert_not_awaited()

    async def test_private_wait_polling_wakes_without_consuming_the_turn_gate_cursor(self) -> None:
        chat = make_chat()
        chat.running = True
        message = make_message()

        with (
            patch.object(
                brain_chat.message_api,
                "get_messages_by_time_in_chat",
                return_value=[message],
            ),
            patch.object(brain_chat.time, "time", return_value=10.0),
        ):
            await chat._wait_for_new_message()

        self.assertEqual(chat.last_read_time, 1.0)

    async def test_native_loop_waits_once_and_sends_buffered_private_messages_to_planner(self) -> None:
        chat = make_chat()
        first_message = make_message("db-1")
        second_message = make_message("db-2")
        chat.turn_scheduler = SimpleNamespace(
            get_private_buffer_wait_seconds=Mock(return_value=1.5),
            decide_private_turn=Mock(
                return_value=TurnDecision(
                    should_observe=True,
                    sleep_seconds=0.1,
                    reason="private_new_message",
                    should_update_last_read_time=True,
                    should_set_new_message_event=True,
                )
            ),
        )
        chat._observe = AsyncMock(return_value=False)

        with (
            patch.object(
                brain_chat.message_api,
                "get_messages_by_time_in_chat",
                side_effect=[[first_message], [first_message, second_message]],
            ) as get_messages,
            patch.object(brain_chat.asyncio, "sleep", new=AsyncMock()) as sleep,
            patch.object(brain_chat.time, "time", side_effect=[10.0, 11.5]),
        ):
            should_continue = await chat._loopbody()

        self.assertFalse(should_continue)
        sleep.assert_awaited_once_with(1.5)
        chat._observe.assert_awaited_once_with(recent_messages_list=[first_message, second_message])
        self.assertEqual(get_messages.call_count, 2)
        self.assertEqual(get_messages.call_args_list[0].kwargs["start_time"], 1.0)
        self.assertEqual(get_messages.call_args_list[1].kwargs["start_time"], 1.0)
        self.assertEqual(get_messages.call_args_list[1].kwargs["end_time"], 11.5)
        self.assertTrue(all(call.kwargs["limit"] == 0 for call in get_messages.call_args_list))
        self.assertEqual(chat.last_read_time, 11.5)
        self.assertTrue(chat._new_message_event.is_set())

    async def test_native_loop_skips_buffer_wait_when_private_buffer_is_disabled(self) -> None:
        chat = make_chat()
        message = make_message()
        chat.turn_scheduler = SimpleNamespace(
            get_private_buffer_wait_seconds=Mock(return_value=0.0),
            decide_private_turn=Mock(
                return_value=TurnDecision(
                    should_observe=True,
                    reason="private_new_message",
                    should_update_last_read_time=True,
                )
            ),
        )
        chat._observe = AsyncMock(return_value=False)

        with (
            patch.object(
                brain_chat.message_api,
                "get_messages_by_time_in_chat",
                return_value=[message],
            ) as get_messages,
            patch.object(brain_chat.asyncio, "sleep", new=AsyncMock()) as sleep,
            patch.object(brain_chat.time, "time", return_value=10.0),
        ):
            should_continue = await chat._loopbody()

        self.assertFalse(should_continue)
        sleep.assert_not_awaited()
        get_messages.assert_called_once()
        chat._observe.assert_awaited_once_with(recent_messages_list=[message])
        self.assertEqual(chat.last_read_time, 10.0)

    def test_message_buffer_defaults_differ_for_group_and_private_chat(self) -> None:
        self.assertEqual(ChatConfig().group_message_buffer_seconds, 3.0)
        self.assertEqual(ChatConfig().private_message_buffer_seconds, 1.5)

    def test_private_tool_pipeline_flag_is_removed_from_schema_and_generated_defaults(self) -> None:
        self.assertFalse(hasattr(ExperimentalConfig(), "private_tool_pipeline"))
        generated = config_module.generate_default_bot_config()
        self.assertIn(f'version = "{config_module.BOT_CONFIG_VERSION}"', generated)
        self.assertNotIn("private_tool_pipeline", generated)
        self.assertNotIn("visual_style", generated)

    async def test_native_turn_binds_reply_handler_and_loop_start_time(self) -> None:
        chat = make_chat()
        expected = private_tool_pipeline.PrivateTurnResult()
        chat.tool_pipeline = SimpleNamespace(run=AsyncMock(return_value=expected))
        chat._execute_reply_tool = AsyncMock(
            return_value=private_tool_pipeline.ToolExecutionResult(
                call_id="call-1",
                tool_name="reply",
                success=True,
                content="sent",
                terminal=True,
            )
        )

        result = await chat._run_native_tool_turn({}, "tid-1")

        self.assertIs(result, expected)
        kwargs = chat.tool_pipeline.run.await_args.kwargs
        self.assertEqual(kwargs["loop_start_time"], 1.0)
        self.assertEqual(kwargs["context_end_time"], 1.0)
        self.assertEqual(kwargs["cycle_timers"], {})
        self.assertEqual(kwargs["thinking_id"], "tid-1")
        reply_handler = kwargs["reply_handler"]
        tool_call = ToolCall("call-1", "reply", {"target_message_id": "m1", "reply_reason": "answer"})
        decision = make_decision(make_message())
        await reply_handler(tool_call, decision)
        chat._execute_reply_tool.assert_awaited_once_with(tool_call, decision, {}, "tid-1")

    async def test_native_turn_runs_reply_tool_end_to_end(self) -> None:
        chat = make_chat()
        message = make_message()
        reply_call = ToolCall(
            "call-1",
            "reply",
            {"target_message_id": "m1", "reply_reason": "回答"},
        )
        decision = make_decision(message)
        decision.tool_calls = [reply_call]
        planner = SimpleNamespace(plan=AsyncMock(return_value=decision))
        registry = SimpleNamespace(execute=AsyncMock())
        chat.tool_pipeline = private_tool_pipeline.PrivateToolPipeline(planner=planner, tool_registry=registry)

        reply_set = ReplySetModel()
        reply_set.add_text_content("hello")
        llm_response = SimpleNamespace(
            reply_set=reply_set,
            selected_expressions=None,
            retrieved_atom_ids=[],
        )
        loop_info = {"loop_action_info": {"action_taken": True}}
        chat._send_and_store_reply = AsyncMock(return_value=(loop_info, "hello", {}))
        chat._apply_memory_feedback = AsyncMock()

        with (
            patch.object(
                brain_chat.generator_api,
                "generate_reply",
                new=AsyncMock(return_value=(True, llm_response)),
            ),
            patch.object(
                brain_chat.message_api,
                "get_messages_by_time_in_chat",
                side_effect=[[], []],
            ),
        ):
            result = await chat._run_native_tool_turn({}, "tid-1")

        self.assertTrue(result.reply_sent)
        self.assertEqual(result.reply_text, "hello")
        self.assertFalse(result.should_continue)
        registry.execute.assert_not_awaited()
        chat._send_and_store_reply.assert_awaited_once()


class BrainChattingPipelineInitializationTest(unittest.TestCase):
    def test_initialization_always_builds_unified_tool_pipeline_with_legacy_action_adapter(self) -> None:
        manager = SimpleNamespace(
            get_stream=Mock(return_value=make_stream()),
            get_stream_name=Mock(return_value="Alice"),
        )
        action_manager = object()
        registry = object()
        planner = object()
        pipeline = object()

        with (
            patch.object(brain_chat, "get_chat_manager", return_value=manager),
            patch.object(brain_chat.expression_learner_manager, "get_expression_learner", return_value=object()),
            patch.object(brain_chat, "_HAS_MEMORY_ARCHIVE", False),
            patch.object(brain_chat, "ActionManager", return_value=action_manager) as action_manager_class,
            patch.object(brain_chat, "ChatToolRegistry", return_value=registry) as registry_class,
            patch.object(brain_chat, "PrivateToolPlanner", return_value=planner) as planner_class,
            patch.object(brain_chat, "PrivateToolPipeline", return_value=pipeline) as pipeline_class,
        ):
            chat = brain_chat.BrainChatting("stream-1")

        self.assertIs(chat.action_manager, action_manager)
        self.assertIs(chat.tool_registry, registry)
        self.assertIs(chat.tool_pipeline, pipeline)
        action_manager_class.assert_called_once_with()
        registry_class.assert_called_once_with(
            chat_id="stream-1",
            chat_scope="private",
            action_manager=action_manager,
            chat_stream=chat.chat_stream,
        )
        planner_class.assert_called_once_with(
            chat_id="stream-1",
            tool_registry=registry,
            action_manager=action_manager,
        )
        pipeline_class.assert_called_once_with(planner=planner, tool_registry=registry)


if __name__ == "__main__":
    unittest.main()
