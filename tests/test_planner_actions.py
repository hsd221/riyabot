import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.chat.planner_actions import action_manager, action_modifier, planner as group_planner
from src.common.data_models.database_data_model import DatabaseMessages
from src.common.data_models.info_data_model import ActionPlannerInfo, TargetPersonInfo
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

    def test_parse_single_action_resolves_targets_questions_self_messages_and_invalid_actions(self) -> None:
        planner = self.make_planner()
        planner._is_message_from_self = Mock(return_value=False)
        latest = make_db_message("db-102", text="latest")
        message_id_list = [("m101", make_db_message("db-101", text="hello")), ("m102", latest)]
        plugin_info = make_action_info("plugin")

        reply = planner._parse_single_action(
            {
                "action": "reply",
                "target_message_id": "m101",
                "question": "  需要查什么  ",
                "extra": 1,
            },
            message_id_list,
            [("plugin", plugin_info)],
            "因为 m101",
        )[0]
        self.assertEqual(reply.action_type, "reply")
        self.assertEqual(reply.reasoning, "因为 消息（hello）")
        self.assertEqual(reply.action_data["question"], "需要查什么")
        self.assertEqual(reply.action_data["target_message_id"], "m101")
        self.assertEqual(reply.action_message.message_id, "db-101")
        self.assertEqual(reply.available_actions, {"plugin": plugin_info})
        self.assertEqual(reply.action_reasoning, "因为 m101")

        missing_target = planner._parse_single_action(
            {"action": "reply", "target_message_id": "missing", "question": None},
            message_id_list,
            [("plugin", plugin_info)],
        )[0]
        self.assertEqual(missing_target.action_type, "reply")
        self.assertIs(missing_target.action_message, latest)
        self.assertNotIn("question", missing_target.action_data)

        invalid_question = planner._parse_single_action(
            {"action": "reply", "target_message_id": "m101", "question": ["bad"]},
            message_id_list,
            [("plugin", plugin_info)],
        )[0]
        self.assertNotIn("question", invalid_question.action_data)

        planner._is_message_from_self = Mock(return_value=True)
        self_target = planner._parse_single_action(
            {"action": "reply", "target_message_id": "m101"},
            message_id_list,
            [("plugin", plugin_info)],
        )[0]
        self.assertEqual(self_target.action_type, "no_reply")
        self.assertIsNone(self_target.action_message)
        self.assertIn("来自机器人自身", self_target.reasoning)

        planner._is_message_from_self = Mock(return_value=False)
        invalid = planner._parse_single_action(
            {"action": "bad_action", "target_message_id": "m101"},
            message_id_list,
            [("plugin", plugin_info)],
        )[0]
        self.assertEqual(invalid.action_type, "no_reply")
        self.assertIn("bad_action", invalid.reasoning)

    def test_extract_json_from_markdown_supports_fenced_arrays_comments_and_incomplete_blocks(self) -> None:
        planner = self.make_planner()
        content = """
        这里是理由
        ```json
        // comment
        [{"action": "reply"}, {"action": "plugin"}]
        ```
        """
        json_objects, reasoning = planner._extract_json_from_markdown(content)

        self.assertEqual([item["action"] for item in json_objects], ["reply", "plugin"])
        self.assertEqual(reasoning, "这里是理由")

        incomplete, incomplete_reason = planner._extract_json_from_markdown('理由\n```json\n{"action": "no_reply"}')
        self.assertEqual(incomplete, [{"action": "no_reply"}])
        self.assertEqual(incomplete_reason, "理由")

        empty, empty_reason = planner._extract_json_from_markdown("没有 json")
        self.assertEqual(empty, [])
        self.assertEqual(empty_reason, "")

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
        }

        with patch.object(group_planner.random, "random", return_value=0.5):
            filtered = planner._filter_actions_by_activation_type(actions, "今天聊猫")

        self.assertEqual(set(filtered), {"always", "random_hit", "keyword"})

        for index in range(22):
            planner.add_plan_log(f"reason-{index}", [])
            planner.add_plan_excute_log(f"exec-{index}")

        self.assertEqual(len(planner.plan_log), 20)
        self.assertEqual(planner.plan_log[0][0], "reason-12")
        self.assertEqual(planner.plan_log[1][2], "exec-12")
        log_text = planner.get_plan_log_str(max_action_records=1, max_execution_records=1)
        self.assertIn("reason-21", log_text)
        self.assertIn("exec-21", log_text)
        self.assertEqual(planner._create_no_reply("silent", actions)[0].action_type, "no_reply")

    async def test_build_action_options_and_get_necessary_info_use_registered_actions(self) -> None:
        planner = self.make_planner()
        prompt = SimpleNamespace(
            format=Mock(
                side_effect=lambda **kwargs: (
                    f"{kwargs['action_name']}|{kwargs['action_description']}|"
                    f"{kwargs['parallel_text']}|{kwargs['action_parameters']}|{kwargs['action_require']}"
                )
            )
        )

        with patch.object(group_planner.global_prompt_manager, "get_prompt_async", new=AsyncMock(return_value=prompt)):
            block = await planner._build_action_options_block(
                {
                    "plugin": make_action_info("plugin", parallel_action=False),
                    "parallel": make_action_info("parallel", parallel_action=True),
                }
            )

        self.assertIn("plugin|plugin desc|(当选择这个动作时，请不要选择其他动作)", block)
        self.assertIn("parallel|parallel desc||", block)
        self.assertIn('"value":"参数说明"', block)
        self.assertIn("- 需要上下文", block)
        self.assertEqual(await planner._build_action_options_block({}), "")

        registered = {"plugin": make_action_info("plugin")}
        with (
            patch.object(group_planner, "get_chat_type_and_target_info", return_value=(True, TargetPersonInfo())),
            patch(
                "src.plugin_system.core.component_registry.component_registry.get_components_by_type",
                return_value=registered,
            ),
        ):
            is_group, target, available = planner.get_necessary_info()

        self.assertTrue(is_group)
        self.assertIsInstance(target, TargetPersonInfo)
        self.assertEqual(available, registered)

    async def test_execute_main_planner_parses_actions_adds_loop_time_and_falls_back_on_errors(self) -> None:
        planner = self.make_planner()
        planner.planner_llm = SimpleNamespace(
            generate_response_async=AsyncMock(
                return_value=(
                    (
                        "理由 m101\n```json\n"
                        '{"action":"reply","target_message_id":"m101"}\n'
                        '{"action":"plugin","target_message_id":"m101"}\n'
                        "```"
                    ),
                    ("raw reasoning", None, None),
                )
            )
        )
        available = {"plugin": make_action_info("plugin")}

        with (
            patch.object(group_planner.global_config, "debug", SimpleNamespace(show_planner_prompt=False)),
            patch.object(group_planner.random, "shuffle", side_effect=lambda values: None),
        ):
            reasoning, actions, raw, raw_reasoning, duration = await planner._execute_main_planner(
                prompt="prompt",
                message_id_list=[("m101", make_db_message("db-101"))],
                filtered_actions=available,
                available_actions=available,
                loop_start_time=123.0,
            )

        self.assertEqual(reasoning, "理由 消息（hello）")
        self.assertEqual([action.action_type for action in actions], ["reply", "plugin"])
        self.assertEqual([action.action_data["loop_start_time"] for action in actions], [123.0, 123.0])
        self.assertIn('"action":"reply"', raw)
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
        self.assertEqual(actions[0].action_type, "no_reply")
        self.assertIsNone(raw)
        self.assertIsNone(raw_reasoning)
        self.assertIsNone(duration)

    async def test_plan_respects_event_cancellation_modified_prompt_and_force_reply(self) -> None:
        planner = self.make_planner()
        action_info = make_action_info("plugin")
        force_message = make_db_message("force-db")
        planner.get_necessary_info = Mock(return_value=(True, TargetPersonInfo(), {"plugin": action_info}))
        planner.build_planner_prompt = AsyncMock(return_value=("original prompt", [("m101", make_db_message())]))
        planner._execute_main_planner = AsyncMock(
            return_value=(
                "reason",
                [
                    ActionPlannerInfo(
                        action_type="no_reply",
                        reasoning="silent",
                        action_data={},
                        action_message=None,
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
                return_value=("chat", [("m101", make_db_message())]),
            ),
            patch.object(group_planner.events_manager, "handle_mai_events", new=AsyncMock(return_value=(False, None))),
        ):
            cancelled = await planner.plan({"plugin": action_info}, loop_start_time=1.0)

        self.assertEqual(cancelled[0].action_type, "no_reply")
        self.assertEqual(cancelled[0].reasoning, "规划 hook 取消本轮规划")
        self.assertEqual(cancelled[0].action_data["loop_start_time"], 1.0)

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


if __name__ == "__main__":
    unittest.main()
