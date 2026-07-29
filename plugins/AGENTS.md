# plugins - External Plugin Implementations

## OVERVIEW
This directory holds externally loaded plugins, separate from bundled `src/plugins/built_in/`. Each plugin is a deployment/API boundary and must conform to the SDK in `src/plugin_system/`.

## CONVENTIONS
- Every plugin directory needs `_manifest.json` and its registered `BasePlugin` implementation.
- Use public imports and facades from `src.plugin_system` or `src.plugin_system.apis`; do not depend on `core/` internals from plugin code.
- Declare user-editable configuration with the SDK's schema/config-file mechanisms. Keep values and secrets out of `_manifest.json` unless the manifest contract explicitly requires metadata.
- Plugin and component names must not contain `.` because the registry applies namespaces.
- Use `BaseTool` for structured LLM calls, `BaseAction` for compatible autonomous actions, `BaseCommand` for direct commands, and `BaseEventHandler` for events.

## SAFETY
- Plugins run in the RiyaBot process without a sandbox. Validate messages, files, URLs, and remote responses; bound network/file work and avoid secret-bearing logs.
- Preserve manifest host-version and dependency checks. Dependencies are checked rather than installed automatically at runtime.
- Re-check enabled state through the existing runtime path before executing a component.

## VERIFICATION
```bash
uv run python -m unittest tests.test_plugin_manager tests.test_component_registry
uv run python -m unittest tests.test_plugin_base_classes tests.test_plugin_apis tests.test_plugin_events
```

For plugin changes, test manifest loading plus the changed component contract. Do not edit generated runtime plugin copies under `data/` as source.
