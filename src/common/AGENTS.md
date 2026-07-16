# src/common - Shared Infrastructure

## Scope
`src/common/` contains infrastructure shared across chat, memory, plugins, model clients, and the WebUI. Keep domain-specific planning, memory, and UI behavior in their owning packages rather than adding it here.

## Directory Map
- `logger.py`: structlog configuration, redaction, `get_logger()`, startup, and shutdown.
- `database/`: the shared Peewee SQLite connection and persistent ORM models.
- `data_models/`: dataclass-based transport and domain models built on `BaseDataModel`.
- `message/api.py`: `maim_message` server integration and message handler registration.
- `message_repository.py`: conversion and queries around persisted messages.
- `prompt_loader.py`: prompt file I/O, metadata parsing, section parsing, and cache revision tracking.
- `prompt_manager.py`: canonical prompt registry, formatting, aliases, scoped overrides, and hot reload.
- `server.py` and `tcp_connector.py`: internal adapter/API transport, separate from the WebUI server.
- `agreement.py`, `remote.py`, `toml_utils.py`, and `knowledge_utils/`: shared policy and utility code.

## Data and Prompt Boundaries
The current files are `message_data_model.py`, `message_component_model.py`, `info_data_model.py`, `llm_data_model.py`, and `database_data_model.py`; do not import old shorthand modules such as `data_models.message` or `data_models.llm`. These models are dataclasses, not Pydantic schemas. Peewee table definitions belong in `database/database_model.py`; conversion objects belong in `data_models/database_data_model.py`.

Business code should obtain prompt text through the singleton `prompt_manager`. Keep filesystem parsing and cache behavior in `prompt_loader.py`. Prompt IDs derive from paths under `prompts/`; metadata and `###SECTION` declarations must satisfy `prompts/README.md` and the prompt contract tests.

## Service and Safety Rules
- Acquire loggers with `get_logger(name)` and use structured context for new security-sensitive events. Never log credentials, raw tokens, or private upstream bodies.
- The internal `Server` uses `HOST` and `PORT`; it is not `src/webui/webui_server.py`. The message-injection endpoint must remain opt-in and authenticated when exposed beyond loopback.
- Runtime data belongs under `data/`. Schema changes require an explicit compatibility or migration plan because there is no general migration framework.
- Preserve existing path, URL, and TOML validation helpers instead of adding ad hoc string checks.

## Verification
Use focused standard-library tests:

```bash
uv run python -m unittest tests.test_common_data_models tests.test_common_database_models
uv run python -m unittest tests.test_common_logger tests.test_common_server tests.test_unified_prompt_manager
```
