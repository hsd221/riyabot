import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.base_command import BaseCommand
from src.plugin_system.base.base_events_handler import BaseEventHandler
from src.plugin_system.base.base_tool import BaseTool
from src.plugin_system.base.component_types import (
    ActionActivationType,
    ActionInfo,
    CommandInfo,
    ComponentInfo,
    ComponentType,
    EventHandlerInfo,
    EventType,
    PluginInfo,
    ToolInfo,
    ToolParamType,
)
from src.plugin_system.core.component_registry import ComponentRegistry


class FakeAction(BaseAction):
    action_name = "act"
    activation_type = ActionActivationType.ALWAYS

    async def execute(self):
        return True, "done"


class FakeCommand(BaseCommand):
    command_name = "greet"
    command_pattern = r"^/greet\s+(?P<name>\w+)$"

    async def execute(self):
        return True, None, 0


class BroadFakeCommand(FakeCommand):
    command_name = "broad"
    command_pattern = r"^/mix.*$"


class FakeTool(BaseTool):
    name = "lookup"
    description = "Lookup data"
    parameters = [("query", ToolParamType.STRING, "Query", True, None)]
    available_for_llm = True

    async def execute(self, function_args):
        return {"query": function_args["query"]}


class DisabledFakeTool(FakeTool):
    name = "disabled_lookup"


class RegistryEventHandler(BaseEventHandler):
    event_type = EventType.ON_MESSAGE
    handler_name = "registry_event"

    async def execute(self, message):
        return True, True, None, None, None


class RegistryEventHandlerAlt(RegistryEventHandler):
    handler_name = "registry_event_alt"


class ExplodingPopDict(dict):
    def pop(self, key, *args):
        raise RuntimeError("forced pop failure")


class ComponentRegistryTest(unittest.IsolatedAsyncioTestCase):
    def make_action_info(self, *, name: str = "act", enabled: bool = True) -> ActionInfo:
        return ActionInfo(
            name=name,
            component_type=ComponentType.ACTION,
            plugin_name="plugin-a",
            enabled=enabled,
        )

    def make_command_info(
        self, *, name: str = "greet", pattern: str = FakeCommand.command_pattern, enabled: bool = True
    ) -> CommandInfo:
        return CommandInfo(
            name=name,
            component_type=ComponentType.COMMAND,
            plugin_name="plugin-a",
            enabled=enabled,
            command_pattern=pattern,
        )

    def make_event_info(self, *, name: str = "registry_event", enabled: bool = True) -> EventHandlerInfo:
        return EventHandlerInfo(
            name=name,
            component_type=ComponentType.EVENT_HANDLER,
            event_type=EventType.ON_MESSAGE,
            plugin_name="plugin-a",
            enabled=enabled,
        )

    def make_registry_with_tool(self, *, enabled: bool = True) -> tuple[ComponentRegistry, ToolInfo]:
        registry = ComponentRegistry()
        tool_info = ToolInfo(
            name="lookup",
            component_type=ComponentType.TOOL,
            description="Lookup",
            enabled=enabled,
            tool_parameters=FakeTool.parameters,
            tool_description=FakeTool.description,
            plugin_name="plugin-a",
        )
        self.assertTrue(registry.register_component(tool_info, FakeTool))
        return registry, tool_info

    def test_register_plugin_rejects_duplicates_removes_entries_and_reports_stats(self) -> None:
        registry = ComponentRegistry()
        plugin = PluginInfo(display_name="Plugin A", name="plugin-a", description="desc")

        self.assertTrue(registry.register_plugin(plugin))
        self.assertFalse(registry.register_plugin(plugin))
        self.assertIs(registry.get_plugin_info("plugin-a"), plugin)
        self.assertEqual(registry.get_all_plugins(), {"plugin-a": plugin})
        self.assertEqual(registry.get_registry_stats()["total_plugins"], 1)
        self.assertTrue(registry.remove_plugin_registry("plugin-a"))
        self.assertFalse(registry.remove_plugin_registry("plugin-a"))

    def test_register_component_rejects_invalid_names_and_conflicts(self) -> None:
        registry = ComponentRegistry()
        bad_component = ComponentInfo(
            name="bad.name",
            component_type=ComponentType.ACTION,
            plugin_name="plugin-a",
        )
        bad_plugin = ComponentInfo(
            name="bad",
            component_type=ComponentType.ACTION,
            plugin_name="plugin.a",
        )
        action_info = ActionInfo(
            name="act",
            component_type=ComponentType.ACTION,
            plugin_name="plugin-a",
            enabled=True,
        )

        self.assertFalse(registry.register_component(bad_component, FakeAction))
        self.assertFalse(registry.register_component(bad_plugin, FakeAction))
        self.assertTrue(registry.register_component(action_info, FakeAction))
        self.assertFalse(registry.register_component(action_info, FakeAction))
        self.assertIs(registry.get_registered_action_info("act"), action_info)
        self.assertEqual(registry.get_default_actions(), {"act": action_info})

    def test_register_component_rejects_unknown_component_types(self) -> None:
        registry = ComponentRegistry()
        scheduler_info = ComponentInfo(
            name="scheduled_job",
            component_type=ComponentType.SCHEDULER,
            plugin_name="plugin-a",
        )

        self.assertFalse(registry.register_component(scheduler_info, FakeAction))

    def test_private_registration_helpers_reject_missing_names_and_invalid_types(self) -> None:
        registry = ComponentRegistry()

        self.assertFalse(registry._register_action_component(self.make_action_info(name=""), FakeAction))
        self.assertFalse(
            registry._register_action_component(
                ComponentInfo(name="plain_action", component_type=ComponentType.ACTION),
                FakeAction,
            )
        )
        self.assertFalse(registry._register_command_component(self.make_command_info(name=""), FakeCommand))
        self.assertFalse(
            registry._register_command_component(
                ComponentInfo(name="plain_command", component_type=ComponentType.COMMAND),
                FakeCommand,
            )
        )
        self.assertFalse(
            registry._register_event_handler_component(self.make_event_info(name=""), RegistryEventHandler)
        )
        self.assertFalse(
            registry._register_event_handler_component(
                ComponentInfo(name="plain_event", component_type=ComponentType.EVENT_HANDLER),
                RegistryEventHandler,
            )
        )

    def test_command_registration_supports_case_insensitive_matching_and_lookup_copies(self) -> None:
        registry = ComponentRegistry()
        command_info = CommandInfo(
            name="greet",
            component_type=ComponentType.COMMAND,
            plugin_name="plugin-a",
            enabled=True,
            command_pattern=FakeCommand.command_pattern,
        )

        self.assertTrue(registry.register_component(command_info, FakeCommand))
        found = registry.find_command_by_text("/GREET Alice")
        command_registry = registry.get_command_registry()
        command_registry.clear()

        self.assertIsNotNone(found)
        command_class, matched_groups, found_info = found
        self.assertIs(command_class, FakeCommand)
        self.assertEqual(matched_groups, {"name": "Alice"})
        self.assertIs(found_info, command_info)
        self.assertIs(registry.get_component_info("command.greet"), command_info)
        self.assertIs(registry.get_component_class("greet", ComponentType.COMMAND), FakeCommand)
        self.assertIs(registry.get_component_class("command.greet"), FakeCommand)
        self.assertEqual(registry.get_command_registry(), {"greet": FakeCommand})

    def test_command_registration_ignores_duplicate_pattern_and_missing_matches(self) -> None:
        registry = ComponentRegistry()
        first = self.make_command_info(name="first", pattern=r"^/same$")
        second = self.make_command_info(name="second", pattern=r"^/same$")

        self.assertTrue(registry.register_component(first, FakeCommand))
        self.assertTrue(registry.register_component(second, FakeCommand))
        self.assertEqual(registry.find_command_by_text("/missing"), None)
        self.assertEqual(len(registry.get_command_patterns()), 1)

    def test_find_command_by_text_uses_first_pattern_when_multiple_patterns_match(self) -> None:
        registry = ComponentRegistry()
        first = self.make_command_info(name="first", pattern=r"^/mix\s+(?P<name>\w+)$")
        second = self.make_command_info(name="second", pattern=BroadFakeCommand.command_pattern)

        self.assertTrue(registry.register_component(first, FakeCommand))
        self.assertTrue(registry.register_component(second, BroadFakeCommand))

        command_class, matched_groups, found_info = registry.find_command_by_text("/mix Alice")

        self.assertIs(command_class, FakeCommand)
        self.assertEqual(matched_groups, {"name": "Alice"})
        self.assertIs(found_info, first)

    def test_component_lookup_auto_resolves_and_reports_ambiguous_names(self) -> None:
        registry = ComponentRegistry()
        action_info = self.make_action_info(name="shared")
        command_info = self.make_command_info(name="shared", pattern=r"^/shared$")

        self.assertTrue(registry.register_component(action_info, FakeAction))
        self.assertTrue(registry.register_component(command_info, FakeCommand))

        self.assertIs(registry.get_component_info("action.shared"), action_info)
        self.assertIs(registry.get_component_info("shared"), action_info)
        self.assertIs(registry.get_component_class("shared"), FakeAction)
        self.assertIsNone(registry.get_component_info("missing"))
        self.assertIsNone(registry.get_component_class("missing"))
        self.assertEqual(set(registry.get_components_by_type(ComponentType.ACTION)), {"shared"})

    def test_component_lookup_helpers_return_unique_matches_and_specific_info(self) -> None:
        registry = ComponentRegistry()
        action_info = self.make_action_info(name="solo_action")
        event_info = self.make_event_info(name="solo_event", enabled=False)
        tool_info = ToolInfo(
            name="solo_tool",
            component_type=ComponentType.TOOL,
            description="Lookup",
            enabled=True,
            tool_parameters=FakeTool.parameters,
            tool_description=FakeTool.description,
            plugin_name="plugin-a",
        )

        self.assertTrue(registry.register_component(action_info, FakeAction))
        self.assertTrue(registry.register_component(tool_info, FakeTool))
        self.assertTrue(registry.register_component(event_info, RegistryEventHandler))

        self.assertIs(registry.get_component_info("solo_action"), action_info)
        self.assertIs(registry.get_component_class("solo_action"), FakeAction)
        self.assertIs(registry.get_registered_tool_info("solo_tool"), tool_info)
        self.assertIsNone(registry.get_registered_tool_info("missing"))
        self.assertIs(registry.get_registered_event_handler_info("solo_event"), event_info)
        self.assertIsNone(registry.get_registered_event_handler_info("missing"))

    async def test_tool_registration_tracks_llm_availability_and_enable_disable_updates_all_views(self) -> None:
        registry, tool_info = self.make_registry_with_tool(enabled=False)

        self.assertEqual(registry.get_tool_registry(), {"lookup": FakeTool})
        self.assertEqual(registry.get_llm_available_tools(), {})
        self.assertFalse(registry.get_enabled_components_by_type(ComponentType.TOOL))
        self.assertTrue(registry.enable_component("lookup", ComponentType.TOOL))
        self.assertTrue(tool_info.enabled)
        self.assertEqual(registry.get_llm_available_tools(), {"lookup": FakeTool})
        self.assertFalse(await registry.disable_component("missing", ComponentType.TOOL))
        self.assertTrue(await registry.disable_component("lookup", ComponentType.TOOL))
        self.assertFalse(tool_info.enabled)
        self.assertEqual(registry.get_llm_available_tools(), {})
        self.assertEqual(registry.get_enabled_components_by_type(ComponentType.TOOL), {})

    async def test_action_command_tool_enable_disable_and_remove_update_specific_registries(self) -> None:
        registry = ComponentRegistry()
        action_info = self.make_action_info(enabled=False)
        command_info = self.make_command_info(enabled=False)
        tool_info = ToolInfo(
            name="lookup",
            component_type=ComponentType.TOOL,
            description="Lookup",
            enabled=True,
            tool_parameters=FakeTool.parameters,
            tool_description=FakeTool.description,
            plugin_name="plugin-a",
        )

        self.assertTrue(registry.register_component(action_info, FakeAction))
        self.assertTrue(registry.register_component(command_info, FakeCommand))
        self.assertTrue(registry.register_component(tool_info, FakeTool))

        self.assertTrue(registry.enable_component("act", ComponentType.ACTION))
        self.assertEqual(registry.get_default_actions(), {"act": action_info})
        self.assertTrue(registry.enable_component("greet", ComponentType.COMMAND))
        self.assertIsNotNone(registry.find_command_by_text("/greet Bob"))
        self.assertFalse(registry.enable_component("missing", ComponentType.COMMAND))

        self.assertTrue(await registry.disable_component("act", ComponentType.ACTION))
        self.assertEqual(registry.get_default_actions(), {})
        self.assertTrue(await registry.disable_component("greet", ComponentType.COMMAND))
        self.assertIsNone(registry.find_command_by_text("/greet Bob"))

        self.assertFalse(await registry.remove_component("act", ComponentType.ACTION, "plugin-a"))
        self.assertTrue(await registry.remove_component("greet", ComponentType.COMMAND, "plugin-a"))
        self.assertTrue(await registry.remove_component("lookup", ComponentType.TOOL, "plugin-a"))
        self.assertFalse(await registry.remove_component("missing", ComponentType.ACTION, "plugin-a"))
        self.assertEqual(registry.get_action_registry(), {})
        self.assertEqual(registry.get_command_registry(), {})
        self.assertEqual(registry.get_tool_registry(), {})

    async def test_remove_and_disable_components_handle_registry_errors(self) -> None:
        registry = ComponentRegistry()
        command_info = self.make_command_info(name="temporary", pattern=r"^/temporary$")
        action_info = self.make_action_info(name="missing_default", enabled=False)
        tool_info = ToolInfo(
            name="explode",
            component_type=ComponentType.TOOL,
            description="Lookup",
            enabled=True,
            tool_parameters=FakeTool.parameters,
            tool_description=FakeTool.description,
            plugin_name="plugin-a",
        )

        self.assertTrue(registry.register_component(command_info, FakeCommand))
        self.assertTrue(await registry.remove_component("temporary", ComponentType.COMMAND, "plugin-a"))
        self.assertIsNone(registry.find_command_by_text("/temporary"))

        self.assertTrue(registry.register_component(action_info, FakeAction))
        self.assertFalse(await registry.disable_component("missing_default", ComponentType.ACTION))

        self.assertTrue(registry.register_component(tool_info, FakeTool))
        registry._llm_available_tools = ExplodingPopDict({"explode": FakeTool})
        self.assertFalse(await registry.disable_component("explode", ComponentType.TOOL))

        remove_registry = ComponentRegistry()
        remove_tool_info = ToolInfo(
            name="explode_remove",
            component_type=ComponentType.TOOL,
            description="Lookup",
            enabled=True,
            tool_parameters=FakeTool.parameters,
            tool_description=FakeTool.description,
            plugin_name="plugin-a",
        )
        self.assertTrue(remove_registry.register_component(remove_tool_info, FakeTool))
        remove_registry._tool_registry = ExplodingPopDict({"explode_remove": FakeTool})
        self.assertFalse(await remove_registry.remove_component("explode_remove", ComponentType.TOOL, "plugin-a"))

    async def test_event_handler_registration_uses_events_manager_only_when_enabled(self) -> None:
        registry = ComponentRegistry()
        events_module = importlib.import_module("src.plugin_system.core.events_manager")
        enabled_info = EventHandlerInfo(
            name="registry_event",
            component_type=ComponentType.EVENT_HANDLER,
            event_type=EventType.ON_MESSAGE,
            plugin_name="plugin-a",
            enabled=True,
        )
        disabled_info = EventHandlerInfo(
            name="registry_event_disabled",
            component_type=ComponentType.EVENT_HANDLER,
            event_type=EventType.ON_MESSAGE,
            plugin_name="plugin-a",
            enabled=False,
        )

        with patch.object(events_module.events_manager, "register_event_subscriber", return_value=True) as register:
            self.assertTrue(registry.register_component(enabled_info, RegistryEventHandler))

        self.assertEqual(registry.get_event_handler_registry(), {"registry_event": RegistryEventHandler})
        self.assertEqual(registry.get_enabled_event_handlers(), {"registry_event": RegistryEventHandler})
        register.assert_called_once_with(enabled_info, RegistryEventHandler)

        class DisabledRegistryEventHandler(RegistryEventHandler):
            handler_name = "registry_event_disabled"

        with patch.object(events_module.events_manager, "register_event_subscriber", return_value=True) as register:
            self.assertTrue(registry.register_component(disabled_info, DisabledRegistryEventHandler))

        self.assertIn("registry_event_disabled", registry.get_event_handler_registry())
        self.assertNotIn("registry_event_disabled", registry.get_enabled_event_handlers())
        register.assert_not_called()

        with patch.object(
            events_module.events_manager, "unregister_event_subscriber", new=AsyncMock(return_value=True)
        ):
            self.assertTrue(await registry.remove_component("registry_event", ComponentType.EVENT_HANDLER, "plugin-a"))

        self.assertNotIn("registry_event", registry.get_event_handler_registry())

    async def test_event_handler_register_enable_disable_and_failure_paths(self) -> None:
        registry = ComponentRegistry()
        events_module = importlib.import_module("src.plugin_system.core.events_manager")
        enabled_info = self.make_event_info(name="registry_event", enabled=True)
        alt_info = self.make_event_info(name="registry_event_alt", enabled=True)
        disabled_info = self.make_event_info(name="registry_event_disabled", enabled=False)

        with patch.object(events_module.events_manager, "register_event_subscriber", return_value=False):
            self.assertFalse(registry.register_component(enabled_info, RegistryEventHandler))

        with patch.object(events_module.events_manager, "register_event_subscriber", return_value=True) as register:
            self.assertTrue(registry.register_component(alt_info, RegistryEventHandlerAlt))
            self.assertTrue(registry.register_component(disabled_info, RegistryEventHandlerAlt))
            self.assertTrue(registry.enable_component("registry_event_disabled", ComponentType.EVENT_HANDLER))
        self.assertEqual(register.call_count, 2)
        self.assertIn("registry_event_alt", registry.get_registered_event_handler_info("registry_event_alt").name)
        self.assertIn("registry_event_disabled", registry.get_enabled_event_handlers())

        with patch.object(
            events_module.events_manager, "unregister_event_subscriber", new=AsyncMock(return_value=True)
        ) as unregister:
            self.assertTrue(await registry.disable_component("registry_event_alt", ComponentType.EVENT_HANDLER))
        unregister.assert_awaited_once_with("registry_event_alt")
        self.assertNotIn("registry_event_alt", registry.get_enabled_event_handlers())

    def test_plugin_components_config_and_registry_stats_cover_all_component_types(self) -> None:
        registry = ComponentRegistry()
        plugin_module = importlib.import_module("src.plugin_system.core.plugin_manager")
        action_info = self.make_action_info(name="stat_action", enabled=True)
        command_info = self.make_command_info(name="stat_command", pattern=r"^/stats$", enabled=False)
        event_info = self.make_event_info(name="stat_event", enabled=False)
        tool_info = ToolInfo(
            name="stat_tool",
            component_type=ComponentType.TOOL,
            description="Lookup",
            enabled=True,
            tool_parameters=FakeTool.parameters,
            tool_description=FakeTool.description,
            plugin_name="plugin-a",
        )
        enabled_plugin = PluginInfo(
            display_name="Plugin A",
            name="plugin-a",
            description="desc",
            components=[action_info, command_info],
        )
        disabled_plugin = PluginInfo(display_name="Plugin B", name="plugin-b", description="desc", enabled=False)

        self.assertTrue(registry.register_plugin(enabled_plugin))
        self.assertTrue(registry.register_plugin(disabled_plugin))
        self.assertTrue(registry.register_component(action_info, FakeAction))
        self.assertTrue(registry.register_component(command_info, FakeCommand))
        self.assertTrue(registry.register_component(tool_info, FakeTool))
        self.assertTrue(registry.register_component(event_info, RegistryEventHandler))

        self.assertEqual(registry.get_plugin_components("plugin-a"), [action_info, command_info])
        self.assertEqual(registry.get_plugin_components("missing"), [])
        with patch.object(
            plugin_module.plugin_manager,
            "get_plugin_instance",
            return_value=SimpleNamespace(config={"threshold": 3}),
        ):
            self.assertEqual(registry.get_plugin_config("plugin-a"), {"threshold": 3})
        with patch.object(plugin_module.plugin_manager, "get_plugin_instance", return_value=None):
            self.assertIsNone(registry.get_plugin_config("missing"))

        stats = registry.get_registry_stats()
        self.assertEqual(stats["action_components"], 1)
        self.assertEqual(stats["command_components"], 1)
        self.assertEqual(stats["tool_components"], 1)
        self.assertEqual(stats["event_handlers"], 1)
        self.assertEqual(stats["total_components"], 4)
        self.assertEqual(stats["total_plugins"], 2)
        self.assertEqual(stats["enabled_components"], 2)
        self.assertEqual(stats["enabled_plugins"], 1)
        self.assertEqual(stats["components_by_type"][ComponentType.ACTION.value], 1)
        self.assertEqual(stats["components_by_type"][ComponentType.COMMAND.value], 1)
        self.assertEqual(stats["components_by_type"][ComponentType.TOOL.value], 1)
        self.assertEqual(stats["components_by_type"][ComponentType.EVENT_HANDLER.value], 1)


if __name__ == "__main__":
    unittest.main()
