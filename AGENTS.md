# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-23
**Commit:** 24e434e
**Branch:** HEAD (detached)

## OVERVIEW
MaiBot (MaiCore) — LLM-driven interactive QQ group chat agent. Python 3.10+ backend + React 19 frontend. Aims to be a "lifelike presence" not a "helpful assistant".

## STRUCTURE
```
maibot/
├── bot.py                # Entry: Runner/Worker dual-process (exit 42 = restart)
├── src/                  # Core Python package
│   ├── main.py           # MainSystem: init + 4 concurrent coroutines
│   ├── chat/             # ★ Largest subsystem (21k lines) — see src/chat/AGENTS.md
│   ├── plugin_system/    # Plugin SDK v2 — see src/plugin_system/AGENTS.md
│   ├── webui/            # FastAPI WebUI backend — see src/webui/AGENTS.md
│   ├── common/           # Infra: server, DB, logger, data models — see src/common/AGENTS.md
│   ├── config/           # global_config singleton from TOML; typed dataclasses
│   ├── llm_models/       # LLM client abstraction (OpenAI + Gemini)
│   ├── memory_system/    # Memory retrieval + chat history summarization
│   ├── bw_learner/       # Behavior learning: expression/jargon mining from chat
│   ├── dream/            # Autonomous background maintenance tasks ("dreaming")
│   ├── person_info/      # User/group profile management
│   ├── manager/          # async_task_manager, local_store_manager
│   └── plugins/built_in/ # 4 built-in plugins (emoji/tts/knowledge/plugin_mgmt)
├── webui/                # ★ React+Vite frontend — see webui/AGENTS.md
├── plugins/              # External user plugins (each needs _manifest.json)
├── config/               # Runtime TOML configs (gitignored)
├── template/             # Config templates (bot_config_template.toml etc.)
├── scripts/              # 20 dev/analysis scripts (NOT tests)
├── data/                 # SQLite DB + JSON stores (gitignored)
├── logs/                 # JSONL structured logs
├── docs-src/             # Documentation source
├── Dockerfile            # Multi-stage: lpmm-builder (Cython) + runtime
└── docker-compose.yml    # 4 services: core/adapters/napcat/sqlite-web
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Startup flow | `bot.py` → `src/main.py` | Runner spawns Worker; Worker runs MainSystem |
| Add chat behavior (group) | `src/chat/heart_flow/` + `src/chat/planner_actions/` | ReAct-style LLM planner |
| Add chat behavior (private) | `src/chat/brain_chat/PFC/` | Brain-metaphor state machine |
| LLM reply generation | `src/chat/replyer/group_generator.py`, `private_generator.py` | 1251/1116 lines resp. |
| Write a plugin | `src/plugin_system/base/` + `plugins/hello_world_plugin/` | 4 component types |
| WebUI backend route | `src/webui/` | FastAPI; register API routes BEFORE static files |
| WebUI frontend page | `webui/src/routes/` | TanStack Router, 19 routes |
| Config schema | `src/config/official_configs.py` | Typed dataclasses (BotConfig, PersonalityConfig...) |
| LLM usage stats | `src/chat/utils/statistic.py` | 2307 lines incl. 900-line HTML report |
| Emoji system | `src/chat/emoji_system/emoji_manager.py` | Singleton via get_emoji_manager() |
| Memory retrieval | `src/memory_system/memory_retrieval.py` | 1288 lines |

## CODE MAP
| Symbol | Type | Location | Role |
|--------|------|----------|------|
| MainSystem | class | src/main.py | System init + task scheduling (4 coroutines) |
| Heartflow | class | src/chat/heart_flow/heartflow.py | Dispatches group→HeartFChatting, private→BrainChatting |
| Conversation | class | src/chat/brain_chat/PFC/conversation.py | PFC state machine (private chat) |
| ActionPlanner | class | src/chat/planner_actions/planner.py | Group chat LLM action selection (882 lines) |
| DefaultReplyer | class | src/chat/replyer/group_generator.py | Group LLM reply generation |
| PluginManager | class | src/plugin_system/core/plugin_manager.py | Plugin discovery + loading |
| ComponentRegistry | class | src/plugin_system/core/component_registry.py | Component namespace registry |
| EventsManager | class | src/plugin_system/core/events_manager.py | Event pub/sub (10 event types) |
| EmojiManager | class | src/chat/emoji_system/emoji_manager.py | Emoji registration + LLM tagging |
| global_config | obj | src/config/config.py | Singleton config from TOML |

## CONVENTIONS
- **Ruff**: line-length 120, rules E/F/B, ignore E711/E501. quote-style double, indent space.
- **Deps**: uv (uv.lock + TUNA mirror). `requirements.txt` mirrors pyproject.toml.
- **Docstrings**: Chinese, nearly universal.
- **Logger names**: short prefixes — `"bc"` (BrainChat), `"hfc"` (HeartFChat), `"pfc"`, `"planner"`, `"replyer"`, `"emoji"`, `"maibot_statistic"`.
- **Singletons**: explicit `_instance` class attr (PFCManager, ChatManager, EmojiManager).
- **No type checking**: no mypy/pyright configured. Type hints present but not enforced.
- **No tests**: zero test infrastructure. Only 2 manual debug scripts in scripts/.

## ANTI-PATTERNS (THIS PROJECT)
- **DO NOT import** `src/chat/knowledge/mem_active_manager.py` — raises DeprecationWarning on import (crashes).
- **Deprecated fields**: `focus_activation_type`, `normal_activation_type` → use `activation_type`.
- **Renamed action**: `listening` → `wait` (backward-compat conversion in brain_planner.py).
- **webui_server.py**: MUST register API routes BEFORE static files (ordering constraint).
- **dream_agent.py**: `message_factory` must be sync, NOT async.
- **config_base.py**: only `Optional[T]` allowed; multi-type Union (e.g. `float | str`) throws TypeError.
- **model_routes.py**: translate provider 401/403 → 502 (frontend treats 401 as WebUI auth failure).
- **CONTRIBUTE.md**: feature PRs NOT accepted — only bugfix/docs. Features must go through issue first.
- **No test scripts in repo** — use `.local/` for local verification.
- **Deployments NOT backward-compatible** across versions.

## UNIQUE STYLES
- **Dual chat architecture**: group chats use `planner_actions/` (ReAct LLM), private chats use `PFC/` (brain metaphor). Same problem, different architectures.
- **PFC = literal brain metaphor**: ChatObserver (sensory), GoalAnalyzer (dlPFC), ActionPlanner (premotor), ReplyGenerator (Broca), ReplyChecker (ACC), KnowledgeFetcher (hippocampus), Waiter (attention).
- **Runner/Worker**: bot.py is both — Runner (daemon, monitors exit code 42) and Worker (MAIBOT_WORKER_PROCESS=1 env var).
- **Two FastAPI servers**: internal API (127.0.0.1:8080) + WebUI (0.0.0.0:8001), independent.
- **WebUI version dual-track**: `webui/src/lib/version.ts` = Dashboard version (0.11.7 Beta); MaiBot backend version (0.12.2) hardcoded in frontend JS. `pyproject.toml` version (0.11.6) is yet another value, not kept in sync with releases.

## COMMANDS
```bash
# Run (local)
python bot.py

# Lint + format
ruff check --fix . && ruff format .

# Deps
uv sync                          # or: pip install -r requirements.txt

# WebUI frontend (build before docker build!)
cd webui && bun install && bun run build    # → webui/dist/

# Docker
git clone https://github.com/Mai-with-u/MaiMBot-LPMM.git MaiMBot-LPMM  # required build dep
docker build -t maibot .
docker compose up -d             # 4 services: core/adapters/napcat/sqlite-web

# Pre-commit
pre-commit run --all-files
```

## NOTES
- **LPMM external dep**: Docker build requires `MaiMBot-LPMM/` dir in context (Cython-compiled `quick_algo`).
- **Docker does NOT build WebUI**: run `bun run build` BEFORE `docker build` or WebUI will be stale/missing.
- **EULA confirmation**: startup blocks on EULA/privacy agreement. In Docker, set env vars to bypass.
- **pyproject.toml version (0.11.6) != release (v0.12.2)** — not kept in sync.
- **CI**: 5 workflows on self-hosted Windows runners (ruff + docker build main/dev + precheck). No test CI.
- **config/ and data/ are gitignored** — copy from template/ on fresh setup.
- **Plugin manifest**: `_manifest.json` required in every plugin dir. Validated by ManifestValidator.
