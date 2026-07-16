# src/webui - FastAPI WebUI Backend

## Scope and Routing
This package serves the dashboard API, authenticated WebSockets, and the built frontend from `webui/dist/`. `webui_server.py` configures exception handling, request limits, same-site protection, anti-crawler behavior, CORS, security headers, routes, and the SPA fallback. The default address is `127.0.0.1:8001`, configurable through `WEBUI_HOST` and `WEBUI_PORT`.

`routes.py` owns the primary `/api/webui` router and includes configuration, statistics, people, expressions, jargon, behavior, emoji, memory, plugins, models, setup, and system routes. `webui_server.py` also registers separate routers for `/api/chat`, `/api/planner`, `/api/replier`, `/api/webui/knowledge`, and `/ws/logs`. Register API and WebSocket routes before `_setup_static_files()` because the SPA route is a catch-all.

## Where to Work
- `auth.py`, `token_manager.py`, `ws_auth.py`: password login, HttpOnly sessions, same-site checks, and one-use WebSocket tokens.
- `config_routes.py`, `config_schema.py`: schema-driven bot/model/adapter configuration.
- `model_routes.py`: provider discovery and connection testing with outbound URL controls.
- `plugin_routes.py`, `git_mirror_service.py`, `path_utils.py`: plugin marketplace, repositories, and confined filesystem paths.
- `chat_routes.py`, `logs_ws.py`, `plugin_progress_ws.py`: local chat and authenticated streaming.
- `memory_routes.py`, `behavior_routes.py`, `expression_routes.py`, `jargon_routes.py`: current learned-state APIs.
- `error_utils.py`, `request_limits.py`, `rate_limiter.py`: shared defensive boundaries.

## Authentication and Security
Password authentication issues an HttpOnly `maibot_session`; do not store passwords or session tokens in frontend JavaScript storage. Reuse `get_current_token()` or `verify_auth_token_from_cookie_or_header()` for protected HTTP routes. WebSockets should accept a short-lived token from `/api/webui/ws-token` and verify origin; keep cookie fallback only through existing helpers.

All state-changing HTTP requests pass global same-site protection. Preserve request-size, connection-count, path-confinement, SSRF, and response-size limits. Sanitize server failures with `error_utils.py`; never return exception text, filesystem paths, tokens, or upstream response bodies. Provider `401/403` responses must remain translated to `502`, since frontend `401` means the WebUI session expired.

## Deprecated or Placeholder Paths
`knowledge_routes.py` is a disabled LPMM compatibility surface that returns empty data; new memory features belong in `memory_routes.py`. Legacy `/auth/verify`, `/auth/update`, and `/auth/regenerate` routes are deprecated. `/api/webui/system/reload-config` is a placeholder, not a supported reload mechanism. Do not build new clients on these paths.

## Verification

```bash
uv run python -m unittest tests.test_webui_route_security tests.test_webui_password_auth
uv run python -m unittest tests.test_webui_backend_utils tests.test_webui_server
```
