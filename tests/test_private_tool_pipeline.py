import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.chat.brain_chat import private_tool_pipeline
from src.common.data_models.database_data_model import DatabaseMessages
from src.llm_models.payload_content import ToolCall
from src.llm_models.payload_content.tool_option import ToolParamType


def make_message(message_id: str = "db-1") -> DatabaseMessages:
    return DatabaseMessages(
        message_id=message_id,
        time=10.0,
        chat_id="stream-1",
        processed_plain_text="hello",
        user_id="user-1",
        user_nickname="Alice",
        user_platform="qq",
        chat_info_stream_id="stream-1",
        chat_info_platform="qq",
        chat_info_user_id="user-1",
        chat_info_user_nickname="Alice",
        chat_info_user_platform="qq",
    )


class PrivateToolRegistryTest(unittest.IsolatedAsyncioTestCase):
    def make_registry(self):
        executor = SimpleNamespace(execute_tool_call=AsyncMock())
        registry = private_tool_pipeline.PrivateToolRegistry(
            chat_id="stream-1",
            executor=executor,
        )
        return registry, executor

    def test_definitions_reserve_reply_and_filter_disabled_plugin_tools(self) -> None:
        registry, _ = self.make_registry()
        lookup_definition = {
            "name": "lookup",
            "description": "lookup",
            "parameters": [("query", ToolParamType.STRING, "query", True, None)],
        }
        conflicting_reply = {
            "name": "reply",
            "description": "plugin reply",
            "parameters": [],
        }
        disabled_definition = {
            "name": "disabled",
            "description": "disabled",
            "parameters": [],
        }

        with (
            patch.object(
                private_tool_pipeline,
                "get_llm_available_tool_definitions",
                return_value=[
                    ("lookup", lookup_definition),
                    ("reply", conflicting_reply),
                    ("safe_alias", conflicting_reply),
                    ("disabled", disabled_definition),
                ],
            ),
            patch.object(
                private_tool_pipeline.global_announcement_manager,
                "get_disabled_chat_tools",
                return_value=["disabled"],
            ),
        ):
            definitions = registry.get_tool_definitions()

        self.assertEqual(
            [definition["name"] for definition in definitions],
            ["reply", "lookup", "safe_alias"],
        )
        reply_parameters = definitions[0]["parameters"]
        self.assertEqual(reply_parameters[0][0], "target_message_id")
        self.assertEqual(reply_parameters[0][1], ToolParamType.STRING)
        self.assertTrue(reply_parameters[0][3])

    async def test_execute_plugin_normalizes_success_missing_tool_and_errors(self) -> None:
        class CustomResult:
            def __str__(self) -> str:
                return "custom result"

        registry, executor = self.make_registry()
        executor.execute_tool_call.side_effect = [
            {"content": {"answer": 42}},
            RuntimeError("boom"),
            {"content": CustomResult()},
            {"content": "x" * (private_tool_pipeline.MAX_TOOL_RESULT_CHARS + 20)},
        ]

        available_definitions = [
            (name, {"name": name, "description": name, "parameters": []})
            for name in ("lookup", "broken", "custom", "large", "disabled")
        ]
        with (
            patch.object(
                private_tool_pipeline,
                "get_llm_available_tool_definitions",
                return_value=available_definitions,
            ),
            patch.object(
                private_tool_pipeline.global_announcement_manager,
                "get_disabled_chat_tools",
                return_value=["disabled"],
            ),
        ):
            success = await registry.execute_plugin(ToolCall("call-1", "lookup", {"query": "MaiBot"}))
            missing = await registry.execute_plugin(ToolCall("call-2", "missing", {}))
            disabled = await registry.execute_plugin(ToolCall("call-disabled", "disabled", {}))
            failed = await registry.execute_plugin(ToolCall("call-3", "broken", {}))
            custom = await registry.execute_plugin(ToolCall("call-4", "custom", {}))
            truncated = await registry.execute_plugin(ToolCall("call-5", "large", {}))

        self.assertTrue(success.success)
        self.assertEqual(success.content, '{"answer": 42}')
        self.assertFalse(missing.success)
        self.assertIn("不可用", missing.content)
        self.assertFalse(disabled.success)
        self.assertIn("禁用", disabled.content)
        self.assertFalse(failed.success)
        self.assertIn("boom", failed.content)
        self.assertEqual(custom.content, "custom result")
        self.assertEqual(len(truncated.content), private_tool_pipeline.MAX_TOOL_RESULT_CHARS)
        self.assertTrue(truncated.content.endswith("[工具结果已截断]"))
        self.assertEqual(executor.execute_tool_call.await_count, 4)


class PrivateToolPlannerTest(unittest.IsolatedAsyncioTestCase):
    async def test_plan_uses_native_tool_calls_and_keeps_message_mapping(self) -> None:
        registry = SimpleNamespace(
            get_tool_definitions=Mock(
                return_value=[
                    {
                        "name": "reply",
                        "description": "reply",
                        "parameters": [],
                    }
                ]
            )
        )
        planner = private_tool_pipeline.PrivateToolPlanner.__new__(private_tool_pipeline.PrivateToolPlanner)
        planner.chat_id = "stream-1"
        planner.log_prefix = "[stream-1]"
        planner.tool_registry = registry
        planner.last_obs_time_mark = 0.0
        planner.planner_llm = SimpleNamespace(
            generate_response_async=AsyncMock(
                return_value=(
                    "",
                    (
                        "需要回复",
                        "planner-model",
                        [ToolCall("call-1", "reply", {"target_message_id": "m1", "reply_reason": "回答问题"})],
                    ),
                )
            )
        )
        message = make_message()
        planner._load_context = Mock(return_value=("[m1] Alice: hello", {"m1": message}, "Alice", 9.0))
        planner._build_prompt = Mock(return_value="planner prompt")
        previous_result = private_tool_pipeline.ToolExecutionResult(
            call_id="call-0",
            tool_name="lookup",
            success=True,
            content="result",
        )

        with (
            patch.object(
                private_tool_pipeline.events_manager,
                "handle_mai_events",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch.object(private_tool_pipeline.PlanReplyLogger, "log_plan"),
        ):
            decision = await planner.plan(tool_results=[previous_result], loop_start_time=5.0)

        self.assertEqual(decision.tool_calls[0].func_name, "reply")
        self.assertIs(decision.messages_by_id["m1"], message)
        self.assertEqual(decision.reasoning, "需要回复")
        self.assertEqual(decision.started_at, 9.0)
        self.assertEqual(decision.tool_results, [previous_result])
        planner._build_prompt.assert_called_once_with(
            chat_content="[m1] Alice: hello",
            chat_target="Alice",
            tool_results=[previous_result],
        )
        planner.planner_llm.generate_response_async.assert_awaited_once_with(
            prompt="planner prompt",
            tools=registry.get_tool_definitions.return_value,
            raise_when_empty=False,
        )

    async def test_cancelled_or_failed_plan_ends_without_tools(self) -> None:
        planner = private_tool_pipeline.PrivateToolPlanner.__new__(private_tool_pipeline.PrivateToolPlanner)
        planner.chat_id = "stream-1"
        planner.log_prefix = "[stream-1]"
        planner.tool_registry = SimpleNamespace(get_tool_definitions=Mock(return_value=[]))
        planner.last_obs_time_mark = 0.0
        planner.planner_llm = SimpleNamespace(generate_response_async=AsyncMock(side_effect=RuntimeError("down")))
        planner._load_context = Mock(return_value=("history", {}, "Alice", 9.0))
        planner._build_prompt = Mock(return_value="prompt")

        with patch.object(
            private_tool_pipeline.events_manager,
            "handle_mai_events",
            new=AsyncMock(return_value=(False, None)),
        ):
            cancelled = await planner.plan()

        self.assertEqual(cancelled.tool_calls, [])
        planner.planner_llm.generate_response_async.assert_not_awaited()

        with patch.object(
            private_tool_pipeline.events_manager,
            "handle_mai_events",
            new=AsyncMock(return_value=(True, None)),
        ):
            failed = await planner.plan()

        self.assertEqual(failed.tool_calls, [])
        self.assertIn("down", failed.content)


class PrivateToolPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_tool_call_ends_turn_without_invoking_replyer(self) -> None:
        planner = SimpleNamespace(
            plan=AsyncMock(
                return_value=private_tool_pipeline.PlannerDecision(
                    prompt="prompt",
                    content="不回复",
                    reasoning="",
                    model_name="model",
                    tool_calls=[],
                    messages_by_id={},
                    started_at=1.0,
                )
            )
        )
        registry = SimpleNamespace(execute_plugin=AsyncMock())
        pipeline = private_tool_pipeline.PrivateToolPipeline(planner=planner, tool_registry=registry)
        reply_handler = AsyncMock()

        result = await pipeline.run(reply_handler=reply_handler)

        self.assertFalse(result.reply_sent)
        self.assertFalse(result.should_continue)
        reply_handler.assert_not_awaited()
        registry.execute_plugin.assert_not_awaited()

    async def test_plugin_result_returns_to_planner_before_reply(self) -> None:
        lookup_call = ToolCall("call-1", "lookup", {"query": "MaiBot"})
        reply_call = ToolCall("call-2", "reply", {"target_message_id": "m1", "reply_reason": "回答"})
        first_decision = private_tool_pipeline.PlannerDecision(
            prompt="prompt-1",
            content="",
            reasoning="先查询",
            model_name="model",
            tool_calls=[lookup_call],
            messages_by_id={"m1": make_message()},
            started_at=1.0,
        )
        second_decision = private_tool_pipeline.PlannerDecision(
            prompt="prompt-2",
            content="",
            reasoning="查询后回复",
            model_name="model",
            tool_calls=[reply_call],
            messages_by_id={"m1": make_message()},
            started_at=2.0,
        )
        planner = SimpleNamespace(plan=AsyncMock(side_effect=[first_decision, second_decision]))
        lookup_result = private_tool_pipeline.ToolExecutionResult(
            call_id="call-1",
            tool_name="lookup",
            success=True,
            content="lookup result",
        )
        registry = SimpleNamespace(execute_plugin=AsyncMock(return_value=lookup_result))
        pipeline = private_tool_pipeline.PrivateToolPipeline(planner=planner, tool_registry=registry)
        reply_result = private_tool_pipeline.ToolExecutionResult(
            call_id="call-2",
            tool_name="reply",
            success=True,
            content="reply sent",
            terminal=True,
            reply_text="hello",
            loop_info={"loop_action_info": {"action_taken": True}},
        )
        reply_handler = AsyncMock(return_value=reply_result)

        result = await pipeline.run(reply_handler=reply_handler, loop_start_time=5.0)

        self.assertTrue(result.reply_sent)
        self.assertEqual(result.reply_text, "hello")
        self.assertEqual(planner.plan.await_count, 2)
        second_results = planner.plan.await_args_list[1].kwargs["tool_results"]
        self.assertEqual(second_results, [lookup_result])
        reply_handler.assert_awaited_once_with(reply_call, second_decision)

    async def test_reply_is_deferred_when_information_tools_are_in_same_plan(self) -> None:
        reply_call = ToolCall("call-reply", "reply", {"target_message_id": "m1", "reply_reason": "回答"})
        lookup_call = ToolCall("call-tool", "lookup", {"query": "MaiBot"})
        planner = SimpleNamespace(
            plan=AsyncMock(
                side_effect=[
                    private_tool_pipeline.PlannerDecision(
                        prompt="prompt-1",
                        content="",
                        reasoning="mixed",
                        model_name="model",
                        tool_calls=[reply_call, lookup_call],
                        messages_by_id={"m1": make_message()},
                        started_at=1.0,
                    ),
                    private_tool_pipeline.PlannerDecision(
                        prompt="prompt-2",
                        content="",
                        reasoning="reply",
                        model_name="model",
                        tool_calls=[reply_call],
                        messages_by_id={"m1": make_message()},
                        started_at=2.0,
                    ),
                ]
            )
        )
        registry = SimpleNamespace(
            execute_plugin=AsyncMock(
                return_value=private_tool_pipeline.ToolExecutionResult(
                    call_id="call-tool",
                    tool_name="lookup",
                    success=True,
                    content="result",
                )
            )
        )
        pipeline = private_tool_pipeline.PrivateToolPipeline(planner=planner, tool_registry=registry)
        reply_handler = AsyncMock(
            return_value=private_tool_pipeline.ToolExecutionResult(
                call_id="call-reply",
                tool_name="reply",
                success=True,
                content="sent",
                terminal=True,
                reply_text="hello",
            )
        )

        result = await pipeline.run(reply_handler=reply_handler)

        self.assertTrue(result.reply_sent)
        registry.execute_plugin.assert_awaited_once_with(lookup_call)
        reply_handler.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
