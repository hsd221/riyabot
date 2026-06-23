# src/common/ — Infrastructure

Shared foundation: networking, database, logging, data models. Used by all other `src/` subsystems.

## STRUCTURE
```
common/
├── server.py              # FastAPI internal API server (uvicorn, 127.0.0.1:8080)
├── tcp_connector.py       # TCP connector for adapter communication
├── remote.py              # Telemetry heartbeat task
├── message_repository.py  # Message storage abstraction
├── logger.py              # structlog setup (994 lines), get_logger(), initialize_logging()
├── toml_utils.py          # TOML read/write helpers
├── message/
│   └── api.py             # MessageServer (maim_message wrapper) — QQ msg broker
├── database/
│   ├── database.py        # peewee SQLite connection manager
│   └── database_model.py  # ORM models: Messages, ActionRecords, LLMUsage, OnlineTime...
├── data_models/           # Pydantic v2 models (7 files)
│   ├── message.py         # MessageRecv, MessageSending, ChatMessageContext
│   ├── llm.py             # LLM request/response types
│   ├── database.py        # DB row models
│   └── info.py            # UserInfo, GroupInfo, ChatStreamInfo
└── server/                # Server utilities
```

## WHERE TO LOOK
| Task | Location |
|------|----------|
| Add DB table | `database/database_model.py` — add peewee Model class |
| Add Pydantic model | `data_models/` — match domain (message/llm/info/database) |
| Logging config | `logger.py` — `initialize_logging()`, `get_logger(name)`, `shutdown_logging()` |
| Internal API server | `server.py` — add routes here (NOT WebUI routes) |
| Message broker | `message/api.py` — MessageServer, message handler registration |
| Telemetry | `remote.py` — TelemetryHeartBeatTask |

## CONVENTIONS
- **Logger**: structlog-based. Get via `from src.common.logger import get_logger; logger = get_logger("prefix")`.
- **DB**: peewee ORM + SQLite. No migrations framework — models define schema directly.
- **Data models**: Pydantic v2 for validation. DB models (peewee) separate from API models (Pydantic).
- **Two servers**: `server.py` (internal API, 8080) is distinct from `src/webui/webui_server.py` (WebUI, 8001). Don't confuse them.

## ANTI-PATTERNS
- **Internal vs WebUI server**: `server.py` is for plugin/internal RPC. WebUI routes go in `src/webui/`. Adding WebUI routes to `server.py` breaks separation.
- **No migrations**: schema changes require manual DB recreation or migration scripts. `data/` is gitignored.
