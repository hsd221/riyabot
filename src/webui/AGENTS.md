# src/webui/ — WebUI Backend (FastAPI)

28 Python files. Serves React frontend + REST API + WebSocket. Separate from `webui/` (frontend source).

## STRUCTURE
```
webui/
├── webui_server.py      # Server bootstrap + static file serving (port 0.0.0.0:8001)
├── routes.py            # Unified route registration hub
├── auth.py              # Cookie-based session auth
├── ws_auth.py           # WebSocket auth
├── token_manager.py     # Session tokens
├── rate_limiter.py      # Rate limiting
├── anti_crawler.py      # Bot detection middleware
├── api/                 # API handlers: replier.py, planner.py
├── routers/             # Route modules: system.py
├── chat_routes.py       # Chat endpoints
├── config_routes.py     # Bot/model config CRUD
├── model_routes.py      # Model provider management
├── knowledge_routes.py  # [已移除] LPMM knowledge endpoints — 返回空占位
├── emoji_routes.py      # Emoji management (1311 lines)
├── plugin_routes.py     # Plugin management (2060 lines)
├── annual_report_routes.py  # Statistics report (938 lines)
└── utils/               # Shared utilities
```

## WHERE TO LOOK
| Task | Location |
|------|----------|
| Add API route | `routes.py` (register here) + relevant `*_routes.py` |
| Auth flow | `auth.py` + `token_manager.py` + `ws_auth.py` |
| Config API (bot/model) | `config_routes.py` — schema-driven CRUD |
| Model provider proxy | `model_routes.py` — LLM API passthrough |
| Emoji upload/management | `emoji_routes.py` |
| Plugin CRUD | `plugin_routes.py` (largest file) |
| Statistics/report | `annual_report_routes.py` + `chat/utils/statistic.py` |

## CONVENTIONS
- **API prefix**: all routes under `/api/webui/`.
- **Auth**: HttpOnly Cookie sessions. Frontend sends `credentials: 'include'`.
- **WebSocket**: `/ws/logs` for log streaming, `/ws/chat` for chat relay.
- **Static files**: served from `webui/dist/` (built by `cd webui && bun run build`).

## ANTI-PATTERNS
- **Route ordering**: MUST call `_register_api_routes()` BEFORE `_setup_static_files()` in `webui_server.py:33`. Static catch-all breaks API routes if registered first.
- **401→502 translation**: `model_routes.py:137` — provider 401/403 must return 502. Frontend `fetchWithAuth` treats 401 as WebUI auth failure (logs user out).
- **Anti-crawler false positives**: `anti_crawler.py:43` — `bot`, `curl`, `python-requests`, `httpx`, `aiohttp` keywords removed to avoid blocking legit clients.

## NOTES
- Independent from internal API server (`src/common/server.py`, 127.0.0.1:8080). Two FastAPI servers run concurrently.
- CORS enabled for dev (Vite dev server at :7999).
