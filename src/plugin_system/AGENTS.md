# src/plugin_system/ — Plugin SDK v2

Component-driven, event-enhanced framework. 4 component types + 12 API modules.

## STRUCTURE
```
plugin_system/
├── base/                # Abstract base classes
│   ├── plugin_base.py       # PluginBase (670 lines): manifest + config + lifecycle
│   ├── base_plugin.py       # BasePlugin: component registration orchestrator
│   ├── base_action.py       # Action component (LLM Planner triggers via activation_type)
│   ├── base_command.py      # Command component (regex-matched)
│   ├── base_tool.py         # Tool component (LLM function-calling)
│   ├── base_events_handler.py  # EventHandler component (lifecycle hooks)
│   ├── component_types.py   # ActionInfo, CommandInfo, ToolInfo, PluginInfo, EventType...
│   └── config_types.py      # ConfigField, ConfigSection, ConfigTab (WebUI schema)
├── core/                # Runtime
│   ├── plugin_manager.py    # Discovery + loading (importlib, 491 lines)
│   ├── events_manager.py    # Pub/sub: 10 event types, weight-sorted (412 lines)
│   └── component_registry.py  # Namespace registry: {type}.{name} (620 lines)
├── apis/                # 12 API modules (import: `from src.plugin_system.apis import xxx_api`)
│   ├── send_api.py          # text/image/emoji/voice/forward to stream
│   ├── message_api.py       # query history, build readable strings
│   ├── database_api.py      # peewee ORM CRUD
│   ├── llm_api.py           # list models, generate_with_model()
│   ├── chat_api.py          # stream queries, group/private enumeration
│   ├── config_api.py, person_api.py, emoji_api.py, generator_api.py
│   ├── plugin_register_api.py  # @register_plugin decorator
│   └── frequency_api.py, logging_api.py, plugin_manage_api.py
└── utils/manifest_utils.py  # ManifestValidator + VersionComparator
```

## WHERE TO LOOK
| Task | Location |
|------|----------|
| Write a plugin | `base/base_plugin.py` + `plugins/hello_world_plugin/` (reference) |
| Add API for plugins | `apis/` — add module, export in `apis/__init__.py` |
| Add event type | `base/component_types.py` EventType enum + `core/events_manager.py` |
| Plugin discovery debug | `core/plugin_manager.py` `_load_plugin_modules_from_directory()` |
| Component interaction | `core/component_registry.py` — namespaced `f"{type}.{name}"` |

## CONVENTIONS
- **Manifest**: `_manifest.json` required in every plugin dir. Validated by `ManifestValidator`.
- **Registration**: `@register_plugin` decorator → `plugin_manager.plugin_classes[name] = cls`.
- **Component namespaces**: `action.greet`, `command.time`, `tool.search`, `event_handler.on_msg`. No `.` in names.
- **Config schema**: plugins declare `config_schema` (ConfigField list) → exported to WebUI via `get_webui_config_schema()`.
- **Version compat**: `host_application.min_version` / `max_version` in manifest checked against `MMC_VERSION`.

## ANTI-PATTERNS
- **Deprecated**: `focus_activation_type`, `normal_activation_type` → use `activation_type` (`component_types.py:126`).
- **No process sandbox**: all plugins share Python runtime. Isolation via naming + config + version checks only.
- **No auto-install**: `python_dependencies` declared but only checked (`get_missing_packages()`), never installed.
