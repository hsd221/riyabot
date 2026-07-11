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
from src.config.official_configs import ExperimentalConfig
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

    def test_native_private_pipeline_is_enabled_by_default(self) -> None:
        self.assertTrue(ExperimentalConfig().private_tool_pipeline)

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
        registry = SimpleNamespace(execute_plugin=AsyncMock())
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
        registry.execute_plugin.assert_not_awaited()
        chat._send_and_store_reply.assert_awaited_once()


class BrainChattingPipelineInitializationTest(unittest.TestCase):
    def test_initialization_selects_native_pipeline_or_legacy_actions_from_config(self) -> None:
        manager = SimpleNamespace(
            get_stream=Mock(return_value=make_stream()),
            get_stream_name=Mock(return_value="Alice"),
        )
        registry = object()
        planner = object()
        pipeline = object()

        with (
            patch.object(brain_chat, "get_chat_manager", return_value=manager),
            patch.object(brain_chat.expression_learner_manager, "get_expression_learner", return_value=object()),
            patch.object(brain_chat, "_HAS_MEMORY_ARCHIVE", False),
            patch.object(
                brain_chat.global_config,
                "experimental",
                SimpleNamespace(private_tool_pipeline=True),
            ),
            patch.object(brain_chat, "PrivateToolRegistry", return_value=registry) as registry_class,
            patch.object(brain_chat, "PrivateToolPlanner", return_value=planner) as planner_class,
            patch.object(brain_chat, "PrivateToolPipeline", return_value=pipeline) as pipeline_class,
            patch.object(brain_chat, "ActionManager") as action_manager_class,
            patch.object(brain_chat, "BrainPlanner") as legacy_planner_class,
            patch.object(brain_chat, "ActionModifier") as action_modifier_class,
        ):
            native_chat = brain_chat.BrainChatting("stream-1")

        self.assertIs(native_chat.tool_pipeline, pipeline)
        self.assertIsNone(native_chat.action_manager)
        registry_class.assert_called_once_with(chat_id="stream-1")
        planner_class.assert_called_once_with(chat_id="stream-1", tool_registry=registry)
        pipeline_class.assert_called_once_with(planner=planner, tool_registry=registry)
        action_manager_class.assert_not_called()
        legacy_planner_class.assert_not_called()
        action_modifier_class.assert_not_called()

        legacy_manager = object()
        legacy_planner = object()
        legacy_modifier = object()
        with (
            patch.object(brain_chat, "get_chat_manager", return_value=manager),
            patch.object(brain_chat.expression_learner_manager, "get_expression_learner", return_value=object()),
            patch.object(brain_chat, "_HAS_MEMORY_ARCHIVE", False),
            patch.object(
                brain_chat.global_config,
                "experimental",
                SimpleNamespace(private_tool_pipeline=False),
            ),
            patch.object(brain_chat, "PrivateToolRegistry") as registry_class,
            patch.object(brain_chat, "PrivateToolPlanner") as planner_class,
            patch.object(brain_chat, "PrivateToolPipeline") as pipeline_class,
            patch.object(brain_chat, "ActionManager", return_value=legacy_manager),
            patch.object(brain_chat, "BrainPlanner", return_value=legacy_planner),
            patch.object(brain_chat, "ActionModifier", return_value=legacy_modifier),
        ):
            legacy_chat = brain_chat.BrainChatting("stream-1")

        self.assertIsNone(legacy_chat.tool_pipeline)
        self.assertIs(legacy_chat.action_manager, legacy_manager)
        self.assertIs(legacy_chat.action_planner, legacy_planner)
        self.assertIs(legacy_chat.action_modifier, legacy_modifier)
        registry_class.assert_not_called()
        planner_class.assert_not_called()
        pipeline_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
