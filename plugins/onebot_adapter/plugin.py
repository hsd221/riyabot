from typing import List, Tuple, Type

from src.plugin_system import (
    BaseEventHandler,
    BasePlugin,
    ConfigField,
    EventHandlerInfo,
    EventType,
    PythonDependency,
    register_plugin,
)


class OneBotAdapterStartHandler(BaseEventHandler):
    event_type = EventType.ON_START
    handler_name = "onebot_adapter_start"
    handler_description = "启动 OneBot/NapCat 适配器"
    weight = 100
    intercept_message = True

    async def execute(self, message):
        del message
        if not self.get_config("plugin.enabled", True):
            return True, True, "OneBot/NapCat 适配器插件已禁用", None, None

        from .adapter_core.runtime import adapter_runtime

        await adapter_runtime.start()
        return True, True, "OneBot/NapCat 适配器已启动", None, None


class OneBotAdapterStopHandler(BaseEventHandler):
    event_type = EventType.ON_STOP
    handler_name = "onebot_adapter_stop"
    handler_description = "停止 OneBot/NapCat 适配器"
    weight = 100
    intercept_message = True

    async def execute(self, message):
        del message
        from .adapter_core.runtime import adapter_runtime

        await adapter_runtime.stop()
        return True, True, "OneBot/NapCat 适配器已停止", None, None


@register_plugin
class OneBotAdapterPlugin(BasePlugin):
    plugin_name = "onebot_adapter"
    enable_plugin = True
    dependencies: list[str] = []
    python_dependencies = [
        PythonDependency("websockets", ">=15.0.1"),
        PythonDependency("loguru", ">=0.7.3"),
        PythonDependency("sqlmodel", ">=0.0.27"),
        PythonDependency("watchdog", ">=3.0.0"),
    ]
    config_file_name = "plugin_config.toml"
    config_schema = {
        "plugin": {
            "enabled": ConfigField(bool, default=True, description="是否启用 OneBot/NapCat 适配器插件"),
            "config_version": ConfigField(str, default="1.0.0", description="配置文件版本"),
        }
    }

    def get_plugin_components(self) -> List[Tuple[EventHandlerInfo, Type[BaseEventHandler]]]:
        if not self.get_config("plugin.enabled", True):
            return []
        return [
            (OneBotAdapterStartHandler.get_handler_info(), OneBotAdapterStartHandler),
            (OneBotAdapterStopHandler.get_handler_info(), OneBotAdapterStopHandler),
        ]
