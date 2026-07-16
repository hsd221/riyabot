import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.common.data_models.database_data_model import DatabaseMessages
from src.llm_models.payload_content import ToolCall
from src.llm_models.payload_content.tool_option import ToolParamType
from src.plugin_system.base.component_types import ActionActivationType, ActionInfo, ComponentType


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


def make_action(name: str, *, parallel: bool = True) -> ActionInfo:
    return ActionInfo(
        name=name,
        component_type=ComponentType.ACTION,
        description=f"{name} description",
        action_parameters={"value": "要传递的内容"},
        action_require=["只有聊天中明确需要时才能调用"],
        parallel_action=parallel,
    )


class LegacyActionToolDefinitionTest(unittest.TestCase):
    def test_action_is_exposed_as_native_tool_definition(self) -> None:
        from src.chat.chat_tool_registry import action_info_to_tool_definition

        definition = action_info_to_tool_definition(make_action("legacy", parallel=False))

        self.assertEqual(definition["name"], "legacy")
        self.assertIn("legacy description", definition["description"])
        self.assertIn("只有聊天中明确需要", definition["description"])
        self.assertIn("不要同时调用其他", definition["description"])
        parameters = {parameter[0]: parameter for parameter in definition["parameters"]}
        self.assertEqual(set(parameters), {"target_message_id", "reason", "value"})
        self.assertEqual(parameters["target_message_id"][1], ToolParamType.STRING)
        self.assertTrue(parameters["target_message_id"][3])
        self.assertTrue(parameters["value"][3])

    def test_reply_reference_only_contains_successful_results_and_is_bounded(self) -> None:
        from src.chat.chat_tool_registry import (
            MAX_TOOL_RESULT_CHARS,
            TOOL_RESULT_TRUNCATION_MARKER,
            ToolExecutionResult,
            format_tool_results_for_reply,
        )

        reference = format_tool_results_for_reply(
            [
                ToolExecutionResult("ok", "lookup", True, "x" * (MAX_TOOL_RESULT_CHARS * 2)),
                ToolExecutionResult("failed", "lookup", False, "private failure"),
                ToolExecutionResult("reply", "reply", True, "not a reference"),
            ]
        )

        self.assertLessEqual(len(reference), MAX_TOOL_RESULT_CHARS)
        self.assertIn("不可信", reference)
        self.assertNotIn("private failure", reference)
        self.assertNotIn("not a reference", reference)
        self.assertTrue(reference.endswith(TOOL_RESULT_TRUNCATION_MARKER))


class ChatToolRegistryTest(unittest.IsolatedAsyncioTestCase):
    def make_registry(self):
        from src.chat.chat_tool_registry import ChatToolRegistry

        action_manager = SimpleNamespace(create_action=Mock())
        executor = SimpleNamespace(execute_tool_call=AsyncMock())
        registry = ChatToolRegistry(
            chat_id="stream-1",
            chat_scope="group",
            action_manager=action_manager,
            executor=executor,
        )
        return registry, action_manager, executor

    def test_catalog_filters_disabled_entries_and_reserves_builtin_names(self) -> None:
        from src.chat import chat_tool_registry

        registry, _, _ = self.make_registry()
        registry.set_available_actions(
            {
                "allowed_action": make_action("allowed_action"),
                "blocked_action": make_action("blocked_action"),
                "reply": make_action("reply"),
                "lookup": make_action("lookup"),
                "blocked_tool": make_action("blocked_tool"),
            }
        )
        native_definitions = [
            ("lookup", {"name": "lookup", "description": "lookup", "parameters": []}),
            ("blocked_tool", {"name": "blocked_tool", "description": "blocked", "parameters": []}),
            ("reply", {"name": "reply", "description": "conflict", "parameters": []}),
        ]

        with (
            patch.object(chat_tool_registry, "get_llm_available_tool_definitions", return_value=native_definitions),
            patch.object(
                chat_tool_registry.global_announcement_manager,
                "get_disabled_chat_tools",
                return_value=["blocked_tool"],
            ),
            patch.object(
                chat_tool_registry.global_announcement_manager,
                "get_disabled_chat_actions",
                return_value=["blocked_action"],
            ),
        ):
            definitions = registry.get_tool_definitions()

        self.assertEqual([definition["name"] for definition in definitions], ["reply", "lookup", "allowed_action"])
        self.assertEqual(registry.get_source("reply").value, "builtin")
        self.assertEqual(registry.get_source("lookup").value, "tool")
        self.assertEqual(registry.get_source("allowed_action").value, "action")
        self.assertIsNone(registry.get_source("blocked_action"))

    def test_set_available_actions_freezes_exact_snapshot_without_refiltering(self) -> None:
        from src.chat import chat_tool_registry
        from src.chat.chat_tool_registry import ChatToolRegistry

        context = SimpleNamespace(check_types=Mock(return_value=False))
        registry = ChatToolRegistry(
            chat_id="stream-1",
            chat_scope="private",
            action_manager=SimpleNamespace(create_action=Mock()),
            executor=SimpleNamespace(execute_tool_call=AsyncMock()),
            chat_stream=SimpleNamespace(context=context),
        )
        always = make_action("always")
        never = make_action("never")
        never.activation_type = ActionActivationType.NEVER
        keyword = make_action("keyword")
        keyword.activation_type = ActionActivationType.KEYWORD
        keyword.activation_keywords = ["MaiBot"]
        keyword.keyword_case_sensitive = False
        random_action = make_action("random")
        random_action.activation_type = ActionActivationType.RANDOM
        random_action.random_activation_probability = 0.5
        associated = make_action("associated")
        associated.associated_types = ["image"]

        with patch.object(chat_tool_registry.random, "random") as random_value:
            registry.set_available_actions(
                {action.name: action for action in (always, never, keyword, random_action, associated)},
            )
            with (
                patch.object(chat_tool_registry, "get_llm_available_tool_definitions", return_value=[]),
                patch.object(
                    chat_tool_registry.global_announcement_manager,
                    "get_disabled_chat_actions",
                    return_value=[],
                ),
                patch.object(
                    chat_tool_registry.global_announcement_manager,
                    "get_disabled_chat_tools",
                    return_value=[],
                ),
            ):
                first = registry.get_tool_definitions()
                second = registry.get_tool_definitions()

        self.assertEqual(
            [definition["name"] for definition in first],
            ["reply", "always", "never", "keyword", "random", "associated"],
        )
        self.assertEqual(second, first)
        random_value.assert_not_called()
        context.check_types.assert_not_called()

    def test_refresh_available_actions_filters_private_snapshot_once(self) -> None:
        from src.chat import chat_tool_registry
        from src.chat.chat_tool_registry import ChatToolRegistry

        context = SimpleNamespace(check_types=Mock(return_value=False))
        registry = ChatToolRegistry(
            chat_id="stream-1",
            chat_scope="private",
            action_manager=SimpleNamespace(create_action=Mock()),
            executor=SimpleNamespace(execute_tool_call=AsyncMock()),
            chat_stream=SimpleNamespace(context=context),
        )
        always = make_action("always")
        never = make_action("never")
        never.activation_type = ActionActivationType.NEVER
        keyword = make_action("keyword")
        keyword.activation_type = ActionActivationType.KEYWORD
        keyword.activation_keywords = ["MaiBot"]
        keyword.keyword_case_sensitive = False
        random_action = make_action("random")
        random_action.activation_type = ActionActivationType.RANDOM
        random_action.random_activation_probability = 0.5
        associated = make_action("associated")
        associated.associated_types = ["image"]

        with (
            patch.object(chat_tool_registry.random, "random", return_value=0.1) as random_value,
            patch.object(chat_tool_registry, "get_llm_available_tool_definitions", return_value=[]),
            patch.object(
                chat_tool_registry.global_announcement_manager,
                "get_disabled_chat_actions",
                return_value=[],
            ),
            patch.object(
                chat_tool_registry.global_announcement_manager,
                "get_disabled_chat_tools",
                return_value=[],
            ),
        ):
            registry.refresh_available_actions(
                {action.name: action for action in (always, never, keyword, random_action, associated)},
                chat_content="please use maibot",
            )
            definitions = registry.get_tool_definitions()

        self.assertEqual([definition["name"] for definition in definitions], ["reply", "always", "keyword", "random"])
        random_value.assert_called_once_with()
        context.check_types.assert_called_once_with(["image"])

    async def test_native_tool_execution_copies_arguments_and_rechecks_disabled_state(self) -> None:
        from src.chat import chat_tool_registry

        registry, _, executor = self.make_registry()
        original_args = {"query": "MaiBot"}
        executor.execute_tool_call.return_value = {"content": {"answer": 42}}

        with (
            patch.object(
                chat_tool_registry,
                "get_llm_available_tool_definitions",
                return_value=[("lookup", {"name": "lookup", "description": "lookup", "parameters": []})],
            ),
            patch.object(
                chat_tool_registry.global_announcement_manager,
                "get_disabled_chat_actions",
                return_value=[],
            ),
            patch.object(
                chat_tool_registry.global_announcement_manager,
                "get_disabled_chat_tools",
                side_effect=[[], [], ["lookup"]],
            ),
        ):
            registry.get_tool_definitions()
            success = await registry.execute(ToolCall("call-1", "lookup", original_args))
            disabled = await registry.execute(ToolCall("call-2", "lookup", original_args))

        self.assertTrue(success.success)
        self.assertEqual(success.content, '{"answer": 42}')
        self.assertFalse(disabled.success)
        self.assertIn("禁用", disabled.content)
        self.assertEqual(original_args, {"query": "MaiBot"})
        safe_call = executor.execute_tool_call.await_args.args[0]
        self.assertIsNot(safe_call.args, original_args)

    async def test_legacy_action_call_uses_existing_handler_and_validates_target(self) -> None:
        from src.chat import chat_tool_registry

        registry, action_manager, executor = self.make_registry()
        action_info = make_action("legacy")
        registry.set_available_actions({"legacy": action_info})
        handler = SimpleNamespace(execute=AsyncMock(return_value=(True, "done")))
        action_manager.create_action.return_value = handler
        message = make_message()

        with (
            patch.object(chat_tool_registry, "get_llm_available_tool_definitions", return_value=[]),
            patch.object(
                chat_tool_registry.global_announcement_manager,
                "get_disabled_chat_actions",
                return_value=[],
            ),
            patch.object(
                chat_tool_registry.global_announcement_manager,
                "get_disabled_chat_tools",
                return_value=[],
            ),
        ):
            registry.get_tool_definitions()
            result = await registry.execute(
                ToolCall(
                    "call-1",
                    "legacy",
                    {
                        "target_message_id": "m1",
                        "reason": "需要执行",
                        "reply_reason": "不应透传",
                        "quote": True,
                        "extra_info": "不应透传",
                        "value": "payload",
                    },
                ),
                messages_by_id={"m1": message},
                reasoning="planner reasoning",
                cycle_timers={"cycle_start": 1.0},
                thinking_id="thinking-1",
                loop_start_time=12.0,
            )
            missing = await registry.execute(
                ToolCall("call-2", "legacy", {"target_message_id": "missing", "value": "payload"}),
                messages_by_id={"m1": message},
                reasoning="planner reasoning",
            )

        self.assertTrue(result.success)
        self.assertEqual(result.content, "done")
        kwargs = action_manager.create_action.call_args_list[0].kwargs
        self.assertEqual(kwargs["action_name"], "legacy")
        self.assertEqual(kwargs["action_data"], {"value": "payload", "loop_start_time": 12.0})
        self.assertEqual(kwargs["action_reasoning"], "需要执行")
        self.assertIs(kwargs["action_message"], message)
        handler.execute.assert_awaited_once_with()
        executor.execute_tool_call.assert_not_awaited()
        self.assertFalse(missing.success)
        self.assertIn("不存在", missing.content)
        self.assertEqual(action_manager.create_action.call_count, 1)

    async def test_legacy_action_result_is_bounded_before_planner_reuse(self) -> None:
        from src.chat import chat_tool_registry

        registry, action_manager, _ = self.make_registry()
        registry.set_available_actions({"legacy": make_action("legacy")})
        action_manager.create_action.return_value = SimpleNamespace(
            execute=AsyncMock(return_value=(True, "x" * (chat_tool_registry.MAX_TOOL_RESULT_CHARS * 2)))
        )

        with (
            patch.object(chat_tool_registry, "get_llm_available_tool_definitions", return_value=[]),
            patch.object(
                chat_tool_registry.global_announcement_manager,
                "get_disabled_chat_actions",
                return_value=[],
            ),
            patch.object(
                chat_tool_registry.global_announcement_manager,
                "get_disabled_chat_tools",
                return_value=[],
            ),
        ):
            registry.get_tool_definitions()
            result = await registry.execute(
                ToolCall(
                    "call-1",
                    "legacy",
                    {"target_message_id": "m1", "reason": "run", "value": "payload"},
                ),
                messages_by_id={"m1": make_message()},
            )

        self.assertEqual(len(result.content), chat_tool_registry.MAX_TOOL_RESULT_CHARS)
        self.assertTrue(result.content.endswith(chat_tool_registry.TOOL_RESULT_TRUNCATION_MARKER))


if __name__ == "__main__":
    unittest.main()
