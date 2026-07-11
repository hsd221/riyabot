# Repository Guidelines

## Project Structure & Module Organization
MaiBot is a Python 3.10+ backend with a React 19/Vite dashboard. `bot.py` starts the runner/worker process; `src/main.py` initializes the system. Backend code lives in `src/`: `chat/` handles group/private chat behavior, `plugin_system/` contains the plugin SDK, `common/` holds infrastructure utilities, `config/` defines TOML schemas, and `webui/` exposes the FastAPI dashboard backend. Frontend code is in `webui/src/`; prompts are grouped by domain under `prompts/`, where paths map to dotted prompt IDs; external plugins live under `plugins/` and require `_manifest.json`. Runtime `config/`, `data/`, and `logs/` are gitignored; copy from `template/` for local setup. Read nested `AGENTS.md` files before editing covered subtrees.

## Build, Test, and Development Commands
- `uv sync`: install Python dependencies from `pyproject.toml` and `uv.lock`.
- `python bot.py`: run MaiBot locally; startup may require EULA/privacy confirmation and local TOML config.
- `ruff check --fix . && ruff format .`: lint and format Python.
- `cd webui && bun install && bun run dev`: install and run the dashboard.
- `cd webui && bun run build`: type-check and build frontend assets into `webui/dist/`; run this before Docker builds.
- `docker compose up -d`: start the bundled services after config and frontend assets are prepared.

## Coding Style & Naming Conventions
Python formatting is controlled by Ruff: spaces, double quotes, line length 120, rules `E`, `F`, and `B`; `E501` and `E711` are ignored. Match nearby docstrings and comments, often Chinese in backend modules. Prefer existing helpers, logger prefixes such as `planner`, `replyer`, and `pfc`, and explicit singletons using `_instance`. Prompt files support `###SECTION: name` blocks; load them through the prompt loader/manager.

## Testing Guidelines
There is no pytest coverage gate. Verification is script-driven: use `MAIBOT_WORKER_PROCESS=1 uv run python tests/simulator.py --file tests/data/chat_exports/chat_histories_1.json` for message-flow checks, or `uv run python tests/run_e2e.py --quick` for short E2E. Do not commit generated `tests/artifacts/` output unless updating fixtures.

## Commit & Pull Request Guidelines
Recent history uses Conventional Commit-style prefixes such as `fix:`, `feat:`, `refactor:`, `chore:`, and `baseline:`. PRs should describe behavior changes, list validation, link issues, and include screenshots for dashboard UI changes. Per `docs-src/CONTRIBUTE.md`, feature PRs are generally not accepted directly; propose features through an issue first.

## Configuration and Safety Notes
Do not commit secrets, local databases, generated logs, or runtime TOML files. Avoid importing deprecated modules such as `src/chat/knowledge/mem_active_manager.py`. WebUI API routes must be registered before static files, and provider `401/403` errors should be translated so they are not mistaken for WebUI auth failures.
