# PROJECT KNOWLEDGE BASE

## OVERVIEW
RiyaBot is a Python 3.10+ QQ-chat bot with a React 19/TypeScript dashboard. `bot.py` owns Runner/Worker process lifecycle; `src/main.py` assembles `MainSystem` and backend services.

## STRUCTURE
```text
.
├── src/                 # backend packages and built-in plugins
├── webui/               # Bun/Vite dashboard; builds static assets for src/webui/
├── tests/               # stdlib unittest, simulator, and configured E2E tooling
├── prompts/             # external prompt templates and section contracts
├── plugins/             # externally loaded plugins; each has _manifest.json
├── scripts/             # maintenance, migration, evaluation, and load tools
├── config/, data/, logs/ # generated/runtime state; not source
├── docker-config/       # host-persisted Compose configuration boundary
├── Dockerfile
└── docker-compose.yml
```

`src/plugins/built_in/` ships with the core package; `plugins/` is the separately loaded external-plugin boundary. Do not treat them as interchangeable. Read the nearest nested `AGENTS.md` before editing `src/chat/`, `src/common/`, `src/config/`, `src/llm_models/`, `src/memory/`, `src/plugin_system/`, `src/webui/`, `webui/`, `tests/`, or `plugins/`.

## WHERE TO LOOK
| Task | Location | Notes |
|---|---|---|
| Process lifecycle and service wiring | `bot.py`, `src/main.py` | Runner restarts Worker; `MainSystem` is the composition root. |
| Chat turn, tool, reply behavior | `src/chat/` | Owns inbound streams, group/private orchestration, and tool registry. |
| Persistent memory and retrieval | `src/memory/` | SQLite source data plus optional Qdrant vector indexes. |
| Learned behavior and expressions | `src/bw_learner/` | Separate from durable memory storage. |
| Model requests and embeddings | `src/llm_models/` | Provider clients, payloads, request traces, embedding profile. |
| Plugin SDK and runtime | `src/plugin_system/`, `plugins/` | Public facades versus external plugin implementations. |
| Dashboard frontend/backend | `webui/`, `src/webui/` | Build frontend before relying on `webui/dist/` in backend serving. |
| Prompts | `prompts/`, `src/common/prompt_manager.py` | Keep dotted IDs, metadata, and `###SECTION:` variants stable. |

## CODE MAP
| Symbol / boundary | Location | Role |
|---|---|---|
| Runner/Worker entry | `bot.py` | Supervises the worker process. |
| `MainSystem` | `src/main.py` | Initializes and connects core services. |
| `ChatToolRegistry` | `src/chat/chat_tool_registry.py` | Shared native tool-call boundary. |
| `MemoryStore` / `QdrantManager` | `src/memory/store.py` | SQLite/Qdrant storage and vector-index lifecycle. |
| `PluginManager` | `src/plugin_system/core/plugin_manager.py` | Plugin discovery, loading, and lifecycle. |
| `webui_server` / API routers | `src/webui/` | Dashboard HTTP, WebSocket, auth, and static serving. |

## REUSE BEFORE BUILDING
Before adding a helper, client, cache, task runner, persistence layer, security check, or provider adapter, search the listed module and reuse or extend it. Do not introduce a parallel implementation without documenting why the existing boundary cannot satisfy the requirement.

| Need | Reuse first | Location |
|---|---|---|
| Structured/redacted logging | `get_logger()`, `redact_secret()`, `redact_text()`, `hash_id()` | `src/common/logger.py` |
| Fire-and-forget coroutine | `spawn_background_task()` | `src/common/background_tasks.py` |
| Named/cancellable background work | `AsyncTask`, `async_task_manager` | `src/manager/async_task_manager.py` |
| Prompt loading, formatting, scoped overrides | singleton `prompt_manager` | `src/common/prompt_manager.py` |
| Shared application SQLite | Peewee `db` | `src/common/database/database.py` |
| TOML schema, parsing, secure/atomic I/O | `Config`, `update_config()`, `update_model_config()` | `src/config/` |
| Durable memory or vector index | `MemoryStore`, `QdrantManager` | `src/memory/store.py` |
| Native chat Tool registration/execution | `ChatToolRegistry`, `ToolExecutionResult` | `src/chat/chat_tool_registry.py` |
| Plugin-side model calls | `src.plugin_system.apis.llm_api` facade | `src/plugin_system/apis/llm_api.py` |
| WebUI authentication and same-site checks | `get_current_token()`, `require_same_site_request()` | `src/webui/auth.py` |
| WebUI user-controlled filesystem paths | `resolve_path_within()` | `src/webui/path_utils.py` |
| WebUI request-body limits | `RequestBodyLimitMiddleware`, `WEBUI_PATH_BODY_LIMITS` | `src/webui/request_limits.py` |
| Sanitized WebUI 500 responses | `internal_server_error()`, `log_exception_type()` | `src/webui/error_utils.py` |

Search the owning package before creating any new utility. Use the public facade where one exists; for example, plugins import `src.plugin_system.apis` rather than runtime `core/` internals.

## CONVENTIONS
- Python: four spaces, double quotes, 120-character limit; Ruff enforces `E`, `F`, and `B`. Use `snake_case` functions/modules and `PascalCase` classes.
- Tests use standard-library `unittest`, including `IsolatedAsyncioTestCase`; name them `tests/test_<area>.py`.
- React remains typed and functional; follow `webui/` Prettier and package scripts.
- Core TOML definitions live in `src/config/`; generated TOML in `config/` is runtime state, not hand-maintained source.
- Use Conventional Commit prefixes: `feat:`, `fix:`, `refactor:`, `chore:`.

## BRANCH AND SUBMISSION WORKFLOW
- Treat `dev` as the integration branch and `main` as the stable release branch.
- Land all normal changes in `dev` first, through a pull request or an explicitly authorized direct commit to `dev`.
- Promote validated changes from `dev` to `main` only through a pull request. Do not commit or merge normal work directly into `main`.
- Direct updates to `main` are reserved for emergencies such as critical fixes and hot patches. After an emergency update, immediately synchronize the same change back into `dev` so the branches do not diverge.

## ANTI-PATTERNS (THIS PROJECT)
- Do not commit `.env`, credentials, tokens, private databases, `config/`, `data/`, `logs/`, or `tests/artifacts/`.
- Do not edit `webui/dist/`, `webui/node_modules/`, caches, or `.claude/worktrees/` as source; those worktrees are separate copies.
- Do not bypass prompt loading with ad hoc file reads or rename dotted prompt IDs/`###SECTION:` headings during unrelated work.
- Do not expose plugin input, model output, uploads, remote responses, or adapter traffic as trusted data.
- Do not alter configuration, plugin, database, Docker-path, or authentication schemas without a compatibility/migration note.
- Do not create a second logger, SQLite connection, prompt loader, task registry, config writer, model client facade, authentication guard, path validator, or request-size limiter when the reuse table already covers the need.

## COMMANDS
```bash
uv sync
python bot.py
ruff check . && ruff format --check .
uv run python -m unittest discover -s tests -p 'test_*.py'
cd webui && bun install && bun run dev
cd webui && bun run lint && bun run build
docker build -t riyabot .
docker compose up -d
```

## NOTES
- Docker builds the dashboard in its Bun stage; a host `webui/dist/` build is not required for `docker build`.
- Compose persists runtime state under container `/RiyaBot` and host-side `data/RiyaBot` / `docker-config`; preserve these boundaries during deployment changes.
