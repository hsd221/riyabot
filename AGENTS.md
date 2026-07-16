# Repository Guidelines

## Project Structure & Module Organization
RiyaBot combines a Python 3.10+ backend with a React 19/TypeScript dashboard. `bot.py` manages the runner/worker lifecycle; `src/main.py` initializes `MainSystem`. Backend code is under `src/`: `chat/`, `memory/`, `bw_learner/`, `llm_models/`, `plugin_system/`, and shared `common/`, `config/`, `services/`, and `webui/`. Dashboard code is in `webui/src/`, unit tests in `tests/test_*.py`, prompts in `prompts/`, and external plugins in `plugins/` with `_manifest.json`. Runtime `config/`, `data/`, and `logs/` are not source. Read the nearest nested `AGENTS.md` before editing.

## Build, Test, and Development Commands
- `uv sync`: install the locked Python dependencies.
- `python bot.py`: start the local runner and worker after preparing configuration.
- `ruff check . && ruff format --check .`: validate Python; use `--fix` and `ruff format .` to repair issues.
- `uv run python -m unittest discover -s tests -p 'test_*.py'`: run the unit test suite.
- `cd webui && bun install && bun run dev`: install dependencies and start Vite on port 7999.
- `cd webui && bun run lint && bun run build`: lint, type-check, and build the dashboard.
- `docker compose up -d`: start configured services; build the WebUI first.

## Coding Style & Naming Conventions
Python uses four-space indentation, double quotes, and a 120-character limit; Ruff enforces `E`, `F`, and `B`. Use `snake_case` for modules/functions and `PascalCase` for classes. Keep React code typed and functional, using the repository Prettier configuration. Preserve dotted prompt IDs and existing `###SECTION: name` variants.

## Testing Guidelines
Tests use standard-library `unittest`, including `IsolatedAsyncioTestCase`; name files `test_<area>.py`. Run focused tests with `uv run python -m unittest tests.test_plugin_manager`. Use `tests/simulator.py` or `tests/run_e2e.py --quick` for configured message-flow checks. Do not commit `tests/artifacts/` output.

## Commit & Pull Request Guidelines
Use Conventional Commit prefixes (`feat:`, `fix:`, `refactor:`, `chore:`). Keep PRs focused; explain behavior and motivation, affected configuration/API/data boundaries, validation commands, and linked issues. Include screenshots or recordings for WebUI changes. Discuss substantial features in an issue first.

## Configuration and Safety Notes
Create local `.env` from `template/template.env`; core TOML files are generated from the Python definitions under `src/config/`. Never commit credentials, tokens, private databases, runtime configuration, or logs. Treat plugin input, model output, uploads, and remote responses as untrusted. Document migrations for configuration schemas, plugin APIs, databases, Docker paths, or authentication.
