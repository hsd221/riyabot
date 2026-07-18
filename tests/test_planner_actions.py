import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.chat.planner_actions import action_manager, action_modifier, planner as group_planner
from src.chat.utils.structured_prompt import DYNAMIC_CONTEXT_BOUNDARY, split_chat_prompt
from src.common.data_models.database_data_model import DatabaseMessages
from src.common.data_models.info_data_model import ActionPlannerInfo
from src.llm_models.payload_content import ToolCall
from src.plugin_system.base.component_types import ActionActivationType, ActionInfo, ComponentType


def make_action_info(
    name: str,
    *,
    activation_type: ActionActivationType = ActionActivationType.ALWAYS,
    probability: float = 0.0,
    keywords: list[str] | None = None,
    case_sensitive: bool = False,
    associated_types: list[str] | None = None,
    parallel_action: bool = False,
    plugin_name: str = "plugin.test",
) -> ActionInfo:
    return ActionInfo(
        name=name,
        component_type=ComponentType.ACTION,
        description=f"{name} desc",
        plugin_name=plugin_name,
        action_parameters={"value": "参数说明"},
        action_require=["需要上下文"],
        associated_types=associated_types or [],
        activation_type=activation_type,
        random_activation_probability=probability,
        activation_keywords=keywords or [],
        keyword_case_sensitive=case_sensitive,
        parallel_action=parallel_action,
    )


def make_db_message(message_id: str = "db-101", *, text: str = "hello") -> DatabaseMessages:
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


class ActionManagerTest(unittest.TestCase):
    def test_create_action_instantiates_registered_component_with_plugin_config(self) -> None:
        class FakeAction:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        component_info = make_action_info("plugin_action", plugin_name="plugin.owner")
        chat_stream = SimpleNamespace(stream_id="stream-1")

        with (
            patch.object(action_manager.component_registry, "get_default_actions", return_value={}),
            patch.object(
                action_manager.component_registry,
                "get_component_class",
                return_value=FakeAction,
            ) as get_component_class,
            patch.object(
                action_manager.component_registry,
                "get_component_info",
                return_value=component_info,
            ) as get_component_info,
            patch.object(
                action_manager.component_registry,
                "get_plugin_config",
                return_value={"enabled": True},
            ) as get_plugin_config,
        ):
            manager = action_manager.ActionManager()
            instance = manager.create_action(
                action_name="plugin_action",
                action_data={"x": 1},
                action_reasoning="because",
                cycle_timers={"plan": 0.1},
                thinking_id="tid-1",
                chat_stream=chat_stream,
                log_prefix="[stream]",
                shutting_down=True,
                action_message=make_db_message(),
            )

        self.assertIsInstance(instance, FakeAction)
        self.assertEqual(instance.kwargs["action_data"], {"x": 1})
        self.assertEqual(instance.kwargs["action_reasoning"], "because")
        self.assertEqual(instance.kwargs["plugin_config"], {"enabled": True})
        self.assertTrue(instance.kwargs["shutting_down"])
        get_component_class.assert_called_once_with("plugin_action", ComponentType.ACTION)
        get_component_info.assert_called_once_with("plugin_action", ComponentType.ACTION)
        get_plugin_config.assert_called_once_with("plugin.owner")

    def test_create_action_returns_none_for_missing_registry_entries_and_factory_errors(self) -> None:
        with (
            patch.object(action_manager.component_registry, "get_default_actions", return_value={}),
            patch.object(action_manager.component_registry, "get_component_class", return_value=None),
        ):
            manager = action_manager.ActionManager()
            self.assertIsNone(
                manager.create_action("missing", {}, "", {}, "tid", SimpleNamespace(stream_id="s"), "[s]")
            )

        with (
            patch.object(action_manager.component_registry, "get_default_actions", return_value={}),
            patch.object(action_manager.component_registry, "get_component_class", return_value=Mock),
            patch.object(action_manager.component_registry, "get_component_info", return_value=None),
        ):
            manager = action_manager.ActionManager()
            self.assertIsNone(
                manager.create_action("missing_info", {}, "", {}, "tid", SimpleNamespace(stream_id="s"), "[s]")
            )

        class BrokenAction:
            def __init__(self, **kwargs):
                raise RuntimeError("factory down")

        with (
            patch.object(action_manager.component_registry, "get_default_actions", return_value={}),
            patch.object(action_manager.component_registry, "get_component_class", return_value=BrokenAction),
            patch.object(
                action_manager.component_registry,
                "get_component_info",
                return_value=make_action_info("broken"),
            ),
            patch.object(action_manager.component_registry, "get_plugin_config", return_value={}),
        ):
            manager = action_manager.ActionManager()
            self.assertIsNone(manager.create_action("broken", {}, "", {}, "tid", SimpleNamespace(stream_id="s"), "[s]"))

    def test_using_actions_are_copied_removed_and_restored_from_defaults(self) -> None:
        defaults = {"a": make_action_info("a"), "b": make_action_info("b")}
        with patch.object(
            action_manager.component_registry, "get_default_actions", side_effect=lambda: defaults.copy()
        ):
            manager = action_manager.ActionManager()
            using_actions = manager.get_using_actions()
            using_actions["c"] = make_action_info("c")

            self.assertEqual(set(manager.get_using_actions()), {"a", "b"})
            self.assertTrue(manager.remove_action_from_using("a"))
            self.assertFalse(manager.remove_action_from_using("missing"))
            self.assertEqual(set(manager.get_using_actions()), {"b"})

            manager.restore_actions()

        self.assertEqual(set(manager.get_using_actions()), {"a", "b"})


class ActionModifierTest(unittest.IsolatedAsyncioTestCase):
    async def test_modify_actions_removes_disabled_and_adapter_mismatched_actions(self) -> None:
        actions = {
            "keep": make_action_info("keep", associated_types=["text"]),
            "disabled": make_action_info("disabled", associated_types=["text"]),
            "image_action": make_action_info("image_action", associated_types=["image"]),
        }
        manager = action_manager.ActionManager.__new__(action_manager.ActionManager)
        manager._using_actions = {}
        fake_stream = SimpleNamespace(
            stream_id="stream-1",
            context=SimpleNamespace(check_types=Mock(side_effect=lambda required: set(required).issubset({"text"}))),
        )
        fake_chat_manager = SimpleNamespace(
            get_stream=Mock(return_value=fake_stream),
            get_stream_name=Mock(return_value="Group"),
        )

        with (
            patch.object(action_manager.component_registry, "get_default_actions", return_value=actions.copy()),
            patch.object(action_modifier, "get_chat_manager", return_value=fake_chat_manager),
            patch.object(
                action_modifier.global_announcement_manager,
                "get_disabled_chat_actions",
                return_value=["disabled", "not-present"],
            ),
            patch.object(action_modifier, "get_raw_msg_before_timestamp_with_chat", return_value=[make_db_message()]),
            patch.object(action_modifier, "build_readable_messages", return_value="history"),
            patch.object(action_modifier.global_config, "chat", SimpleNamespace(max_context_size=30)),
        ):
            modifier = action_modifier.ActionModifier(manager, "stream-1")
            await modifier.modify_actions(message_content="latest message")

        self.assertEqual(set(manager.get_using_actions()), {"keep"})
        fake_stream.context.check_types.assert_any_call(["text"])
        fake_stream.context.check_types.assert_any_call(["image"])

    async def test_deactivated_actions_by_type_handles_never_random_keyword_and_unknown(self) -> None:
        modifier = action_modifier.ActionModifier.__new__(action_modifier.ActionModifier)
        modifier.log_prefix = "[stream]"
        actions = {
            "always": make_action_info("always", activation_type=ActionActivationType.ALWAYS),
            "never": make_action_info("never", activation_type=ActionActivationType.NEVER),
            "random_miss": make_action_info(
                "random_miss",
                activation_type=ActionActivationType.RANDOM,
                probability=0.4,
            ),
            "keyword_hit": make_action_info(
                "keyword_hit",
                activation_type=ActionActivationType.KEYWORD,
                keywords=["Ping"],
            ),
            "keyword_miss": make_action_info(
                "keyword_miss",
                activation_type=ActionActivationType.KEYWORD,
                keywords=["missing"],
            ),
        }
        actions["unknown"] = make_action_info("unknown")
        actions["unknown"].activation_type = "future-type"

        with (
            patch.object(action_modifier.random, "shuffle", side_effect=lambda values: None),
            patch.object(action_modifier.random, "random", return_value=0.8),
        ):
            deactivated = await modifier._get_deactivated_actions_by_type(actions, "ping the bot")

        self.assertEqual({name for name, _ in deactivated}, {"never", "random_miss", "keyword_miss"})
        self.assertTrue(modifier._check_keyword_activation("keyword_hit", actions["keyword_hit"], "ping now"))
        self.assertFalse(modifier._check_keyword_activation("keyword_miss", actions["keyword_miss"], "ping now"))

        case_sensitive = make_action_info(
            "case",
            activation_type=ActionActivationType.KEYWORD,
            keywords=["Ping"],
            case_sensitive=True,
        )
        self.assertFalse(modifier._check_keyword_activation("case", case_sensitive, "ping now"))
        self.assertTrue(modifier._check_keyword_activation("case", case_sensitive, "Ping now"))


class ActionPlannerTest(unittest.IsolatedAsyncioTestCase):
    def make_planner(self) -> group_planner.ActionPlanner:
        planner = group_planner.ActionPlanner.__new__(group_planner.ActionPlanner)
        planner.chat_id = "stream-1"
        planner.log_prefix = "[stream-1]"
        planner.action_manager = SimpleNamespace(get_using_actions=Mock(return_value={"plugin": object()}))
        planner.planner_llm = SimpleNamespace()
        planner.last_obs_time_mark = 0.0
        planner.plan_log = []
        return planner

    async def test_group_planner_prompt_builds_with_runtime_fields(self) -> None:
        planner = self.make_planner()
        planner._build_planner_memory_context = AsyncMock(return_value="<CONTEXT_EVIDENCE>memory</CONTEXT_EVIDENCE>")
        message_ids = [("m101", make_db_message("db-101"))]

        with (
            patch.object(
                group_planner.global_config,
                "bot",
                SimpleNamespace(nickname="Riya", alias_names=["小夜"]),
            ),
            patch.object(
                group_planner.global_config,
                "personality",
                SimpleNamespace(plan_style="LEGACY_GROUP_ACTION_RULE"),
            ),
        ):
            prompt, returned_ids = await planner.build_planner_prompt(
                chat_content_block="[m101] Alice: hello",
                message_id_list=message_ids,
            )

        self.assertIs(returned_ids, message_ids)
        self.assertIn("[m101] Alice: hello", prompt)
        self.assertIn("<CONTEXT_EVIDENCE>memory</CONTEXT_EVIDENCE>", prompt)
        self.assertIn("你的名字是Riya,也有人叫你小夜", prompt)
        self.assertIn("无 Tool Call", prompt)
        self.assertNotIn("LEGACY_GROUP_ACTION_RULE", prompt)
        self.assertNotIn("{chat_content_block}", prompt)

    async def test_native_tool_calls_replace_action_json_protocol(self) -> None:
        from src.chat.chat_tool_registry import ToolSource

        planner = self.make_planner()
        plugin_info = make_action_info("plugin")
        definitions = [
            {"name": "reply", "description": "reply", "parameters": []},
            {"name": "plugin", "description": "plugin", "parameters": []},
        ]
        planner.tool_registry = SimpleNamespace(
            set_available_actions=Mock(),
            get_tool_definitions=Mock(return_value=definitions),
            get_source=Mock(side_effect=lambda name: ToolSource.BUILTIN if name == "reply" else ToolSource.ACTION),
            execute=AsyncMock(),
        )
        planner.planner_llm = SimpleNamespace(
            generate_response_async=AsyncMock(
                return_value=(
                    "",
                    (
                        "需要回应 m101",
                        "planner-model",
                        [
                            ToolCall(
                                "call-1",
                                "reply",
                                {"target_message_id": "m101", "reply_reason": "回答问题"},
                            ),
                            ToolCall(
                                "call-2",
                                "plugin",
                                {"target_message_id": "m101", "reason": "执行插件", "value": "x"},
                            ),
                        ],
                    ),
                )
            )
        )
        message = make_db_message("db-101")

        with patch.object(group_planner.global_config, "debug", SimpleNamespace(show_planner_prompt=False)):
            reasoning, actions, raw, raw_reasoning, duration = await planner._execute_main_planner(
                prompt="planner prompt",
                message_id_list=[("m101", message)],
                filtered_actions={"plugin": plugin_info},
                available_actions={"plugin": plugin_info},
                loop_start_time=123.0,
            )

        self.assertEqual([action.action_type for action in actions], ["reply", "plugin"])
        self.assertTrue(all(action.action_message is message for action in actions))
        self.assertEqual(actions[1].action_data["value"], "x")
        self.assertNotIn("reason", actions[1].action_data)
        self.assertEqual(actions[0].action_data["loop_start_time"], 123.0)
        self.assertEqual(actions[0].action_reasoning, "回答问题")
        self.assertEqual(actions[1].action_reasoning, "执行插件")
        self.assertIn("消息（hello）", reasoning)
        self.assertEqual(raw, "")
        self.assertEqual(raw_reasoning, "需要回应 m101")
        self.assertIsNotNone(duration)
        planner.planner_llm.generate_response_async.assert_awaited_once_with(
            prompt="planner prompt",
            tools=definitions,
            raise_when_empty=False,
        )
        planner.tool_registry.execute.assert_not_awaited()

    async def test_structured_group_planner_sends_rules_and_dynamic_context_as_distinct_roles(self) -> None:
        planner = self.make_planner()
        planner.tool_registry = SimpleNamespace(
            set_available_actions=Mock(),
            get_tool_definitions=Mock(return_value=[]),
        )
        planner.planner_llm = SimpleNamespace(
            generate_response_async=AsyncMock(return_value=("", ("无需回复", "planner-model", [])))
        )
        prompt = f"稳定规划规则\n{DYNAMIC_CONTEXT_BOUNDARY}\n本轮聊天输入"

        with patch.object(group_planner.global_config, "debug", SimpleNamespace(show_planner_prompt=False)):
            _, actions, *_ = await planner._execute_main_planner(
                prompt=prompt,
                message_id_list=[],
                filtered_actions={},
                available_actions={},
                loop_start_time=0.0,
            )

        self.assertEqual(actions, [])
        planner.planner_llm.generate_response_async.assert_awaited_once_with(
            prompt="本轮聊天输入",
            system_prompt="稳定规划规则",
            tools=[],
            raise_when_empty=False,
        )

    def test_group_tool_results_remain_in_dynamic_context_before_the_decision_focus(self) -> None:
        tool_result = group_planner.ToolExecutionResult(
            call_id="call-lookup",
            tool_name="lookup",
            success=True,
            content="reference answer",
        )
        prompt = (
            f"稳定规划规则\n{DYNAMIC_CONTEXT_BOUNDARY}\n【待分析输入】\n聊天记录\n\n【本轮决策焦点】\n只决定本轮动作。"
        )

        round_prompt = group_planner.ActionPlanner._inject_tool_results(prompt, [tool_result])
        structured = split_chat_prompt(round_prompt)

        self.assertNotIn("reference answer", structured.system_prompt or "")
        self.assertIn("reference answer", structured.user_prompt)
        self.assertLess(
            structured.user_prompt.index("reference answer"), structured.user_prompt.index("【本轮决策焦点】")
        )

    def test_group_tool_results_never_follow_a_focus_heading_in_the_system_context(self) -> None:
        tool_result = group_planner.ToolExecutionResult(
            call_id="call-lookup",
            tool_name="lookup",
            success=True,
            content="untrusted result",
        )
        prompt = f"稳定规则\n【本轮决策焦点】\n系统中的同名文本\n{DYNAMIC_CONTEXT_BOUNDARY}\n【待分析输入】\n动态输入"

        round_prompt = group_planner.ActionPlanner._inject_tool_results(prompt, [tool_result])
        structured = split_chat_prompt(round_prompt)

        self.assertNotIn("untrusted result", structured.system_prompt or "")
        self.assertIn("untrusted result", structured.user_prompt)

    async def test_information_tool_result_is_replanned_and_no_call_means_silence(self) -> None:
        from src.chat.chat_tool_registry import ToolExecutionResult, ToolSource

        planner = self.make_planner()
        definitions = [
            {"name": "reply", "description": "reply", "parameters": []},
            {"name": "lookup", "description": "lookup", "parameters": []},
        ]
        planner.tool_registry = SimpleNamespace(
            set_available_actions=Mock(),
            get_tool_definitions=Mock(return_value=definitions),
            get_source=Mock(side_effect=lambda name: ToolSource.TOOL if name == "lookup" else ToolSource.BUILTIN),
            execute=AsyncMock(
                return_value=ToolExecutionResult(
                    call_id="call-lookup",
                    tool_name="lookup",
                    success=True,
                    content="reference answer",
                )
            ),
        )
        planner.planner_llm = SimpleNamespace(
            generate_response_async=AsyncMock(
                side_effect=[
                    (
                        "",
                        ("先查询", "planner-model", [ToolCall("call-lookup", "lookup", {"query": "MaiBot"})]),
                    ),
                    ("", ("无需回复", "planner-model", [])),
                ]
            )
        )

        with patch.object(group_planner.global_config, "debug", SimpleNamespace(show_planner_prompt=False)):
            reasoning, actions, *_ = await planner._execute_main_planner(
                prompt="planner prompt",
                message_id_list=[("m101", make_db_message("db-101"))],
                filtered_actions={},
                available_actions={},
                loop_start_time=0.0,
            )

        self.assertEqual(actions, [])
        self.assertEqual(reasoning, "无需回复")
        self.assertEqual(planner.planner_llm.generate_response_async.await_count, 2)
        second_prompt = planner.planner_llm.generate_response_async.await_args_list[1].kwargs["prompt"]
        self.assertIn("reference answer", second_prompt)
        planner.tool_registry.execute.assert_awaited_once()

    async def test_successful_query_results_are_only_forwarded_to_reply(self) -> None:
        from src.chat.chat_tool_registry import ToolExecutionResult, ToolSource

        planner = self.make_planner()
        plugin_info = make_action_info("plugin")
        planner.tool_registry = SimpleNamespace(
            set_available_actions=Mock(),
            get_tool_definitions=Mock(return_value=[]),
            get_source=Mock(
                side_effect=lambda name: {
                    "lookup": ToolSource.TOOL,
                    "reply": ToolSource.BUILTIN,
                    "plugin": ToolSource.ACTION,
                }.get(name)
            ),
            allows_parallel=Mock(return_value=True),
            execute=AsyncMock(
                side_effect=[
                    ToolExecutionResult("lookup-ok", "lookup", True, "reference answer"),
                    ToolExecutionResult("lookup-failed", "lookup", False, "private failure"),
                ]
            ),
        )
        planner.planner_llm = SimpleNamespace(
            generate_response_async=AsyncMock(
                side_effect=[
                    (
                        "",
                        (
                            "先查询",
                            "planner-model",
                            [
                                ToolCall("lookup-ok", "lookup", {"query": "MaiBot"}),
                                ToolCall("lookup-failed", "lookup", {"query": "secret"}),
                            ],
                        ),
                    ),
                    (
                        "",
                        (
                            "使用查询结果",
                            "planner-model",
                            [
                                ToolCall(
                                    "reply-call",
                                    "reply",
                                    {
                                        "target_message_id": "m101",
                                        "reply_reason": "依据查询结果回答",
                                        "quote": True,
                                        "unknown_adapter": "drop",
                                    },
                                ),
                                ToolCall(
                                    "plugin-call",
                                    "plugin",
                                    {
                                        "target_message_id": "m101",
                                        "reason": "执行插件",
                                        "value": "payload",
                                        "extra_info": "drop",
                                    },
                                ),
                            ],
                        ),
                    ),
                ]
            )
        )

        with patch.object(group_planner.global_config, "debug", SimpleNamespace(show_planner_prompt=False)):
            _, actions, *_ = await planner._execute_main_planner(
                prompt="planner prompt",
                message_id_list=[("m101", make_db_message("db-101"))],
                filtered_actions={"plugin": plugin_info},
                available_actions={"plugin": plugin_info},
                loop_start_time=123.0,
            )

        reply, plugin = actions
        self.assertEqual(reply.action_reasoning, "依据查询结果回答")
        self.assertEqual(set(reply.action_data), {"quote", "loop_start_time", "extra_info"})
        self.assertIn("reference answer", reply.action_data["extra_info"])
        self.assertNotIn("private failure", reply.action_data["extra_info"])
        self.assertEqual(plugin.action_reasoning, "执行插件")
        self.assertEqual(plugin.action_data, {"value": "payload", "loop_start_time": 123.0})

    def test_effect_calls_reject_invalid_or_self_targets_and_dynamically_disabled_actions(self) -> None:
        from src.chat.chat_tool_registry import ToolSource

        planner = self.make_planner()
        plugin_info = make_action_info("plugin")
        planner._is_message_from_self = Mock(side_effect=lambda message: message.message_id == "self-db")
        planner.tool_registry = SimpleNamespace(
            get_source=Mock(side_effect=lambda name: ToolSource.BUILTIN if name == "reply" else ToolSource.ACTION),
            is_available=Mock(side_effect=lambda name: name != "disabled"),
            allows_parallel=Mock(return_value=True),
        )
        calls = [
            ToolCall("missing", "reply", {"target_message_id": "m404", "reply_reason": "missing"}),
            ToolCall("self", "reply", {"target_message_id": "m-self", "reply_reason": "self"}),
            ToolCall("disabled", "disabled", {"target_message_id": "m-user", "reason": "disabled"}),
        ]

        actions = planner._tool_calls_to_actions(
            calls,
            message_id_list=[
                ("m-self", make_db_message("self-db")),
                ("m-user", make_db_message("user-db")),
            ],
            available_actions={"disabled": plugin_info},
            planner_reasoning="fallback",
            loop_start_time=1.0,
            tool_results=[],
        )

        self.assertEqual(actions, [])

    def test_non_parallel_action_is_the_only_effect_selected(self) -> None:
        from src.chat.chat_tool_registry import ToolSource

        planner = self.make_planner()
        exclusive_info = make_action_info("exclusive", parallel_action=False)
        planner._is_message_from_self = Mock(return_value=False)
        planner.tool_registry = SimpleNamespace(
            get_source=Mock(side_effect=lambda name: ToolSource.BUILTIN if name == "reply" else ToolSource.ACTION),
            is_available=Mock(return_value=True),
            allows_parallel=Mock(side_effect=lambda name: name != "exclusive"),
        )
        message = make_db_message()

        actions = planner._tool_calls_to_actions(
            [
                ToolCall("reply", "reply", {"target_message_id": "m1", "reply_reason": "reply"}),
                ToolCall(
                    "exclusive",
                    "exclusive",
                    {"target_message_id": "m1", "reason": "exclusive", "value": "x"},
                ),
            ],
            message_id_list=[("m1", message)],
            available_actions={"exclusive": exclusive_info},
            planner_reasoning="fallback",
            loop_start_time=1.0,
            tool_results=[],
        )

        self.assertEqual([action.action_type for action in actions], ["exclusive"])

    async def test_query_round_limit_ends_with_silence(self) -> None:
        from src.chat.chat_tool_registry import ToolExecutionResult, ToolSource

        planner = self.make_planner()
        planner.tool_registry = SimpleNamespace(
            set_available_actions=Mock(),
            get_tool_definitions=Mock(return_value=[]),
            get_source=Mock(return_value=ToolSource.TOOL),
            execute=AsyncMock(
                side_effect=lambda call, **_kwargs: ToolExecutionResult(
                    call.call_id,
                    call.func_name,
                    True,
                    "result",
                )
            ),
        )
        planner.planner_llm = SimpleNamespace(
            generate_response_async=AsyncMock(
                side_effect=[
                    ("", (f"round {index}", "planner-model", [ToolCall(f"call-{index}", "lookup", {})]))
                    for index in range(3)
                ]
            )
        )

        with patch.object(group_planner.global_config, "debug", SimpleNamespace(show_planner_prompt=False)):
            _, actions, *_ = await planner._execute_main_planner(
                prompt="planner prompt",
                message_id_list=[],
                filtered_actions={},
                available_actions={},
                loop_start_time=0.0,
            )

        self.assertEqual(actions, [])
        self.assertEqual(planner.planner_llm.generate_response_async.await_count, 3)
        self.assertEqual(planner.tool_registry.execute.await_count, 3)

    async def test_query_tool_calls_are_capped_per_round(self) -> None:
        from src.chat.chat_tool_registry import ToolExecutionResult, ToolSource

        planner = self.make_planner()
        planner.tool_registry = SimpleNamespace(
            set_available_actions=Mock(),
            get_tool_definitions=Mock(return_value=[]),
            get_source=Mock(return_value=ToolSource.TOOL),
            execute=AsyncMock(
                side_effect=lambda call, **_kwargs: ToolExecutionResult(
                    call.call_id,
                    call.func_name,
                    True,
                    "result",
                )
            ),
        )
        planner.planner_llm = SimpleNamespace(
            generate_response_async=AsyncMock(
                side_effect=[
                    (
                        "",
                        (
                            "query",
                            "planner-model",
                            [ToolCall(f"call-{index}", "lookup", {}) for index in range(8)],
                        ),
                    ),
                    ("", ("done", "planner-model", [])),
                ]
            )
        )

        with patch.object(group_planner.global_config, "debug", SimpleNamespace(show_planner_prompt=False)):
            await planner._execute_main_planner(
                prompt="planner prompt",
                message_id_list=[],
                filtered_actions={},
                available_actions={},
                loop_start_time=0.0,
            )

        self.assertLessEqual(planner.tool_registry.execute.await_count, 4)

    def test_filter_actions_by_activation_type_and_plan_logs_are_bounded(self) -> None:
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
            "case_sensitive_miss": make_action_info(
                "case_sensitive_miss",
                activation_type=ActionActivationType.KEYWORD,
                keywords=["MaiBot"],
                case_sensitive=True,
            ),
            "case_insensitive_hit": make_action_info(
                "case_insensitive_hit",
                activation_type=ActionActivationType.KEYWORD,
                keywords=["MAIBOT"],
            ),
        }

        with patch.object(group_planner.random, "random", return_value=0.5):
            filtered = planner._filter_actions_by_activation_type(actions, "今天聊猫和maibot")

        self.assertEqual(set(filtered), {"always", "random_hit", "keyword", "case_insensitive_hit"})

        for index in range(22):
            planner.add_plan_log(f"reason-{index}", [])
            planner.add_plan_excute_log(f"exec-{index}")

        self.assertEqual(len(planner.plan_log), 20)
        self.assertEqual(planner.plan_log[0][0], "reason-12")
        self.assertEqual(planner.plan_log[1][2], "exec-12")
        log_text = planner.get_plan_log_str(max_action_records=1, max_execution_records=1)
        self.assertIn("reason-21", log_text)
        self.assertIn("exec-21", log_text)

    async def test_planner_failure_ends_with_silence(self) -> None:
        planner = self.make_planner()
        planner.tool_registry = SimpleNamespace(
            set_available_actions=Mock(),
            get_tool_definitions=Mock(return_value=[]),
        )
        planner.planner_llm = SimpleNamespace(generate_response_async=AsyncMock(side_effect=RuntimeError("llm down")))
        reasoning, actions, raw, raw_reasoning, duration = await planner._execute_main_planner(
            prompt="prompt",
            message_id_list=[],
            filtered_actions={},
            available_actions={},
            loop_start_time=0.0,
        )

        self.assertIn("LLM 请求失败", reasoning)
        self.assertEqual(actions, [])
        self.assertIsNone(raw)
        self.assertIsNone(raw_reasoning)
        self.assertIsNotNone(duration)

    async def test_plan_respects_event_cancellation_modified_prompt_and_force_reply(self) -> None:
        planner = self.make_planner()
        action_info = make_action_info("plugin")
        force_message = make_db_message("force-db")
        planner.build_planner_prompt = AsyncMock(return_value=("original prompt", [("m101", make_db_message())]))
        planner._execute_main_planner = AsyncMock(
            return_value=(
                "reason",
                [],
                "raw",
                None,
                1.0,
            )
        )
        fake_chat_config = SimpleNamespace(max_context_size=10)

        with (
            patch.object(group_planner.global_config, "chat", fake_chat_config),
            patch.object(group_planner, "get_raw_msg_before_timestamp_with_chat", return_value=[make_db_message()]),
            patch.object(
                group_planner,
                "build_readable_messages_with_id",
                return_value=("chat", [("m101", make_db_message())]),
            ),
            patch.object(group_planner.events_manager, "handle_mai_events", new=AsyncMock(return_value=(False, None))),
        ):
            cancelled = await planner.plan({"plugin": action_info}, loop_start_time=1.0)

        self.assertEqual(cancelled, [])

        modified_message = SimpleNamespace(
            _modify_flags=SimpleNamespace(modify_llm_prompt=True),
            llm_prompt="modified prompt",
        )
        with (
            patch.object(group_planner.global_config, "chat", fake_chat_config),
            patch.object(group_planner, "get_raw_msg_before_timestamp_with_chat", return_value=[make_db_message()]),
            patch.object(
                group_planner,
                "build_readable_messages_with_id",
                return_value=("chat", [("m101", make_db_message())]),
            ),
            patch.object(
                group_planner.events_manager,
                "handle_mai_events",
                new=AsyncMock(return_value=(True, modified_message)),
            ),
            patch.object(group_planner.PlanReplyLogger, "log_plan"),
        ):
            actions = await planner.plan(
                {"plugin": action_info},
                loop_start_time=2.0,
                force_reply_message=force_message,
            )

        self.assertEqual(planner._execute_main_planner.await_args.kwargs["prompt"], "modified prompt")
        self.assertEqual(actions[0].action_type, "reply")
        self.assertIs(actions[0].action_message, force_message)
        self.assertEqual(actions[0].reasoning, "用户提及了我，必须回复该消息")
        self.assertNotIn("no_reply", [action.action_type for action in actions])

    async def test_force_reply_overrides_non_parallel_legacy_action(self) -> None:
        planner = self.make_planner()
        exclusive_info = make_action_info("exclusive", parallel_action=False)
        force_message = make_db_message("force-db")
        planner.tool_registry = SimpleNamespace(allows_parallel=Mock(return_value=False))
        planner.build_planner_prompt = AsyncMock(return_value=("prompt", [("m1", make_db_message())]))
        planner._execute_main_planner = AsyncMock(
            return_value=(
                "reason",
                [
                    ActionPlannerInfo(
                        action_type="exclusive",
                        reasoning="exclusive",
                        action_data={"value": "x"},
                        action_message=make_db_message(),
                    )
                ],
                "raw",
                None,
                1.0,
            )
        )
        fake_chat_config = SimpleNamespace(max_context_size=10)

        with (
            patch.object(group_planner.global_config, "chat", fake_chat_config),
            patch.object(group_planner, "get_raw_msg_before_timestamp_with_chat", return_value=[make_db_message()]),
            patch.object(
                group_planner,
                "build_readable_messages_with_id",
                return_value=("chat", [("m1", make_db_message())]),
            ),
            patch.object(group_planner.events_manager, "handle_mai_events", new=AsyncMock(return_value=(True, None))),
            patch.object(group_planner.PlanReplyLogger, "log_plan"),
        ):
            actions = await planner.plan(
                {"exclusive": exclusive_info},
                loop_start_time=2.0,
                force_reply_message=force_message,
            )

        self.assertEqual([action.action_type for action in actions], ["reply"])
        self.assertIs(actions[0].action_message, force_message)


if __name__ == "__main__":
    unittest.main()
