# tests - Backend Regression and Flow Tests

## OVERVIEW
Backend tests use standard-library `unittest`, including async test cases. Test files use `test_<area>.py`; keep tests deterministic and independent of private runtime state.

## WHERE TO LOOK
| Task | Location | Notes |
|---|---|---|
| Unit/regression coverage | `test_*.py` | Match module names and test the public behavior being changed. |
| Message-flow simulation | `simulator.py` | Configured chat-history simulation entry point. |
| Short end-to-end flow | `run_e2e.py --quick` | Requires its documented local configuration. |
| Test fixtures | `data/` and per-test fixtures | Keep data minimal and non-sensitive. |

## CONVENTIONS
- Use `IsolatedAsyncioTestCase` for async paths; avoid unmanaged event loops and timing-sensitive sleeps.
- Test failure and recovery behavior in addition to the success path when changing persistence, concurrency, authentication, or external-client boundaries.
- Prefer fakes/mocks for networks, providers, and filesystem side effects. Do not require a live model provider or private database for unit tests.
- Assert observable contracts, return values, state transitions, and emitted errors rather than private implementation details.

## ANTI-PATTERNS
- Do not delete or weaken a regression test to make a change pass.
- Do not commit `tests/artifacts/`, credentials, exported private chats, or runtime databases.
- Do not make the suite depend on test execution order or local `config/`, `data/`, and `logs/` state.

## COMMANDS
```bash
uv run python -m unittest discover -s tests -p 'test_*.py'
uv run python -m unittest tests.test_plugin_manager
uv run python tests/run_e2e.py --quick
```
