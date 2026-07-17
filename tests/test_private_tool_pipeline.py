import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.chat.brain_chat import private_tool_pipeline
from src.common.data_models.database_data_model import DatabaseMessages
from src.llm_models.payload_content import ToolCall


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


class PrivateToolPlannerTest(unittest.IsolatedAsyncioTestCase):
    def test_private_planner_prompt_builds_with_runtime_fields(self) -> None:
        planner = private_tool_pipeline.PrivateToolPlanner.__new__(private_tool_pipeline.PrivateToolPlanner)
        tool_result = private_tool_pipeline.ToolExecutionResult(
            call_id="call-1",
            tool_name="lookup",
            success=True,
            content="reference answer",
        )

        with (
            patch.object(
                private_tool_pipeline.global_config,
                "bot",
                SimpleNamespace(nickname="Riya", alias_names=["小夜"]),
            ),
            patch.object(
                private_tool_pipeline.global_config,
                "experimental",
                SimpleNamespace(private_plan_style="LEGACY_PRIVATE_ACTION_RULE"),
            ),
        ):
            prompt = planner._build_prompt(
                chat_content="[m1] Alice: hello",
                chat_target="Alice",
                tool_results=[tool_result],
            )

        self.assertIn("[m1] Alice: hello", prompt)
        self.assertIn("Alice", prompt)
        self.assertIn("reference answer", prompt)
        self.assertIn("你的名字是Riya，也可以叫你小夜", prompt)
        self.assertIn("无 Tool Call", prompt)
        self.assertNotIn("LEGACY_PRIVATE_ACTION_RULE", prompt)
        self.assertNotIn("{tool_results_block}", prompt)

    def test_load_context_uses_frozen_turn_boundary(self) -> None:
        planner = private_tool_pipeline.PrivateToolPlanner.__new__(private_tool_pipeline.PrivateToolPlanner)
        planner.chat_id = "stream-1"
        planner.last_obs_time_mark = 0.0
        message = make_message()

        with (
            patch.object(
                private_tool_pipeline,
                "get_raw_msg_before_timestamp_with_chat",
                return_value=[message],
            ) as get_messages,
            patch.object(
                private_tool_pipeline,
                "build_readable_messages_with_id",
                return_value=("[m1] Alice: hello", [("m1", message)]),
            ),
            patch.object(
                private_tool_pipeline,
                "get_chat_type_and_target_info",
                return_value=(False, SimpleNamespace(person_name="Alice", user_nickname="Alice")),
            ),
            patch.object(private_tool_pipeline.time, "time", return_value=99.0),
        ):
            _, messages_by_id, _, started_at = planner._load_context(context_end_time=10.0)

        self.assertEqual(get_messages.call_args.kwargs["timestamp"], 10.0)
        self.assertEqual(started_at, 10.0)
        self.assertIs(messages_by_id["m1"], message)

    async def test_plan_uses_native_tool_calls_and_keeps_message_mapping(self) -> None:
        action_snapshot = {"legacy": object()}
        action_manager = SimpleNamespace(
            restore_actions=Mock(),
            get_using_actions=Mock(return_value=action_snapshot),
        )
        registry = SimpleNamespace(
            refresh_available_actions=Mock(),
            get_tool_definitions=Mock(
                return_value=[
                    {
                        "name": "reply",
                        "description": "reply",
                        "parameters": [],
                    }
                ]
            ),
        )
        planner = private_tool_pipeline.PrivateToolPlanner.__new__(private_tool_pipeline.PrivateToolPlanner)
        planner.chat_id = "stream-1"
        planner.log_prefix = "[stream-1]"
        planner.tool_registry = registry
        planner.action_manager = action_manager
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
            decision = await planner.plan(
                tool_results=[previous_result],
                loop_start_time=5.0,
                refresh_actions=True,
            )

        self.assertEqual(decision.tool_calls[0].func_name, "reply")
        self.assertIs(decision.messages_by_id["m1"], message)
        self.assertEqual(decision.reasoning, "需要回复")
        self.assertEqual(decision.started_at, 9.0)
        self.assertEqual(decision.tool_results, [previous_result])
        action_manager.restore_actions.assert_called_once_with()
        registry.refresh_available_actions.assert_called_once_with(
            action_snapshot,
            chat_content="[m1] Alice: hello",
        )
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
        planner.tool_registry = SimpleNamespace(
            set_available_actions=Mock(),
            get_tool_definitions=Mock(return_value=[]),
        )
        planner.action_manager = None
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
        registry = SimpleNamespace(execute=AsyncMock())
        pipeline = private_tool_pipeline.PrivateToolPipeline(planner=planner, tool_registry=registry)
        reply_handler = AsyncMock()

        result = await pipeline.run(reply_handler=reply_handler)

        self.assertFalse(result.reply_sent)
        self.assertFalse(result.should_continue)
        reply_handler.assert_not_awaited()
        registry.execute.assert_not_awaited()

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
        registry = SimpleNamespace(
            get_source=Mock(return_value=None),
            allows_parallel=Mock(return_value=True),
            execute=AsyncMock(return_value=lookup_result),
        )
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

        result = await pipeline.run(
            reply_handler=reply_handler,
            loop_start_time=5.0,
            context_end_time=5.0,
            cycle_timers={"cycle_start": 1.0},
            thinking_id="tid-1",
        )

        self.assertTrue(result.reply_sent)
        self.assertEqual(result.reply_text, "hello")
        self.assertEqual(planner.plan.await_count, 2)
        self.assertEqual(
            [call.kwargs["refresh_actions"] for call in planner.plan.await_args_list],
            [True, False],
        )
        self.assertEqual(
            [call.kwargs["context_end_time"] for call in planner.plan.await_args_list],
            [5.0, 5.0],
        )
        second_results = planner.plan.await_args_list[1].kwargs["tool_results"]
        self.assertEqual(second_results, [lookup_result])
        registry.execute.assert_awaited_once_with(
            lookup_call,
            messages_by_id=first_decision.messages_by_id,
            reasoning="先查询",
            cycle_timers={"cycle_start": 1.0},
            thinking_id="tid-1",
            loop_start_time=5.0,
        )
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
            get_source=Mock(return_value=None),
            allows_parallel=Mock(return_value=True),
            execute=AsyncMock(
                return_value=private_tool_pipeline.ToolExecutionResult(
                    call_id="call-tool",
                    tool_name="lookup",
                    success=True,
                    content="result",
                )
            ),
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
        registry.execute.assert_awaited_once()
        reply_handler.assert_awaited_once()

    async def test_non_parallel_legacy_action_suppresses_other_non_reply_calls(self) -> None:
        from src.chat.chat_tool_registry import ToolExecutionResult, ToolSource

        exclusive_call = ToolCall(
            "call-action",
            "exclusive",
            {"target_message_id": "m1", "reason": "run", "value": "x"},
        )
        lookup_call = ToolCall("call-tool", "lookup", {"query": "MaiBot"})
        first_decision = private_tool_pipeline.PlannerDecision(
            prompt="prompt-1",
            content="",
            reasoning="choose action",
            model_name="model",
            tool_calls=[lookup_call, exclusive_call],
            messages_by_id={"m1": make_message()},
            started_at=1.0,
        )
        silent_decision = private_tool_pipeline.PlannerDecision(
            prompt="prompt-2",
            content="",
            reasoning="done",
            model_name="model",
            tool_calls=[],
            messages_by_id={"m1": make_message()},
            started_at=2.0,
        )
        planner = SimpleNamespace(plan=AsyncMock(side_effect=[first_decision, silent_decision]))
        registry = SimpleNamespace(
            get_source=Mock(side_effect=lambda name: ToolSource.ACTION if name == "exclusive" else ToolSource.TOOL),
            allows_parallel=Mock(side_effect=lambda name: name != "exclusive"),
            execute=AsyncMock(return_value=ToolExecutionResult("call-action", "exclusive", True, "done")),
        )
        pipeline = private_tool_pipeline.PrivateToolPipeline(planner=planner, tool_registry=registry)

        await pipeline.run(reply_handler=AsyncMock())

        registry.execute.assert_awaited_once()
        self.assertIs(registry.execute.await_args.args[0], exclusive_call)

    async def test_full_budget_still_records_reply_failure(self) -> None:
        from src.chat.chat_tool_registry import MAX_ACCUMULATED_TOOL_RESULT_CHARS

        lookup_calls = [ToolCall(f"call-{index}", "lookup", {}) for index in range(2)]
        reply_call = ToolCall("call-reply", "reply", {"target_message_id": "missing"})
        planner = SimpleNamespace(
            plan=AsyncMock(
                side_effect=[
                    private_tool_pipeline.PlannerDecision(
                        prompt="prompt-1",
                        content="",
                        reasoning="query",
                        model_name="model",
                        tool_calls=lookup_calls,
                        messages_by_id={},
                        started_at=1.0,
                    ),
                    private_tool_pipeline.PlannerDecision(
                        prompt="prompt-2",
                        content="",
                        reasoning="reply",
                        model_name="model",
                        tool_calls=[reply_call],
                        messages_by_id={},
                        started_at=1.0,
                    ),
                ]
            )
        )
        registry = SimpleNamespace(
            get_source=Mock(return_value=None),
            allows_parallel=Mock(return_value=True),
            execute=AsyncMock(
                side_effect=lambda call, **_kwargs: private_tool_pipeline.ToolExecutionResult(
                    call.call_id,
                    call.func_name,
                    True,
                    "x" * (MAX_ACCUMULATED_TOOL_RESULT_CHARS // 2),
                )
            ),
        )
        pipeline = private_tool_pipeline.PrivateToolPipeline(
            planner=planner,
            tool_registry=registry,
            max_rounds=2,
        )
        reply_handler = AsyncMock(
            return_value=private_tool_pipeline.ToolExecutionResult(
                call_id=reply_call.call_id,
                tool_name="reply",
                success=False,
                content="目标消息不存在",
            )
        )

        result = await pipeline.run(reply_handler=reply_handler)

        self.assertLessEqual(
            sum(len(item.content) for item in result.tool_results),
            MAX_ACCUMULATED_TOOL_RESULT_CHARS,
        )
        reply_results = [item for item in result.tool_results if item.call_id == reply_call.call_id]
        self.assertEqual(len(reply_results), 1, "预算已满时也必须保留已执行 reply 的失败状态")
        self.assertFalse(reply_results[0].success)
        self.assertEqual(reply_results[0].content, "目标消息不存在")

    async def test_reply_replan_signal_ends_inner_turn_before_stale_side_effects(self) -> None:
        reply_call = ToolCall("call-reply", "reply", {"target_message_id": "m1"})
        stale_tool_call = ToolCall("call-stale", "lookup", {})
        planner = SimpleNamespace(
            plan=AsyncMock(
                side_effect=[
                    private_tool_pipeline.PlannerDecision(
                        prompt="prompt-1",
                        content="",
                        reasoning="reply",
                        model_name="model",
                        tool_calls=[reply_call],
                        messages_by_id={"m1": make_message()},
                        started_at=1.0,
                    ),
                    private_tool_pipeline.PlannerDecision(
                        prompt="prompt-2",
                        content="",
                        reasoning="stale side effect",
                        model_name="model",
                        tool_calls=[stale_tool_call],
                        messages_by_id={"m1": make_message()},
                        started_at=1.0,
                    ),
                ]
            )
        )
        registry = SimpleNamespace(
            get_source=Mock(return_value=None),
            allows_parallel=Mock(return_value=True),
            execute=AsyncMock(
                return_value=private_tool_pipeline.ToolExecutionResult(
                    call_id=stale_tool_call.call_id,
                    tool_name=stale_tool_call.func_name,
                    success=True,
                    content="executed",
                )
            ),
        )
        pipeline = private_tool_pipeline.PrivateToolPipeline(
            planner=planner,
            tool_registry=registry,
            max_rounds=2,
        )
        reply_handler = AsyncMock(
            return_value=private_tool_pipeline.ToolExecutionResult(
                call_id=reply_call.call_id,
                tool_name="reply",
                success=False,
                content="收到新消息，请重新规划",
                should_continue=True,
            )
        )

        result = await pipeline.run(reply_handler=reply_handler)

        planner.plan.assert_awaited_once()
        registry.execute.assert_not_awaited()
        self.assertTrue(result.should_continue)

    async def test_tool_calls_and_accumulated_results_are_bounded(self) -> None:
        calls = [ToolCall(f"call-{index}", "lookup", {}) for index in range(8)]
        first_decision = private_tool_pipeline.PlannerDecision(
            prompt="prompt-1",
            content="",
            reasoning="query",
            model_name="model",
            tool_calls=calls,
            messages_by_id={},
            started_at=1.0,
        )
        silent_decision = private_tool_pipeline.PlannerDecision(
            prompt="prompt-2",
            content="",
            reasoning="done",
            model_name="model",
            tool_calls=[],
            messages_by_id={},
            started_at=1.0,
        )
        planner = SimpleNamespace(plan=AsyncMock(side_effect=[first_decision, silent_decision]))
        registry = SimpleNamespace(
            get_source=Mock(return_value=None),
            allows_parallel=Mock(return_value=True),
            execute=AsyncMock(
                side_effect=lambda call, **_kwargs: private_tool_pipeline.ToolExecutionResult(
                    call.call_id,
                    call.func_name,
                    True,
                    "x" * 6000,
                )
            ),
        )
        pipeline = private_tool_pipeline.PrivateToolPipeline(planner=planner, tool_registry=registry)

        result = await pipeline.run(reply_handler=AsyncMock())

        self.assertLessEqual(registry.execute.await_count, 4)
        self.assertLessEqual(sum(len(item.content) for item in result.tool_results), 12000)


if __name__ == "__main__":
    unittest.main()
