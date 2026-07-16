# src/chat - Chat Runtime

## Scope and Active Architecture
This package owns inbound chat processing, stream lifecycle, planning, reply generation, and emoji handling. `heart_flow/heartflow.py` selects `HeartFChatting` for group streams and `BrainChatting` for private streams. Both active paths use native LLM tool calls through `ChatToolRegistry`; they do not parse JSON or Markdown action payloads from model text.

`ChatToolRegistry` is the shared boundary for the built-in `reply` tool, plugin `BaseTool` implementations, and compatible `BaseAction` components. The Planner selects tools; the group or private Replyer writes outgoing text only after `reply` is selected. No tool call means the turn ends silently.

## Directory Map
- `message_receive/`: inbound validation, persistence, `ChatStream` management, and outbound message adaptation.
- `heart_flow/`: group orchestration, turn scheduling, and frequency control.
- `brain_chat/`: active private loop and `PrivateToolPipeline`.
- `planner_actions/`: group Planner and `BaseAction` execution compatibility.
- `replyer/`: group/private text generation.
- `chat_tool_registry.py`: tool catalog, collision handling, execution, and bounded result formatting.
- `emoji_system/`: emoji indexing, description, selection, and lifecycle.
- `utils/` and `logger/`: context builders, media helpers, statistics, and plan/reply traces.

## Runtime Contracts
- Keep group and private orchestration separate, but share tool execution through `ChatToolRegistry`.
- Preserve message cursors and `ReplyTurnScheduler` buffering so messages arriving during a turn are not lost or double-processed.
- Treat chat history, memory evidence, plugin descriptions, and tool results as untrusted model input.
- Keep tool-call and result-size limits centralized in `chat_tool_registry.py`; do not duplicate constants in a Planner.
- Continue using `ActionManager` at the legacy plugin boundary. Do not rename public Action fields or stored records as part of unrelated chat work.
- Route new memory behavior through `src/memory/` and behavior learning through `src/bw_learner/`.

## Prompts and Legacy Code
The active message chain uses `prompts/chat/group/{planner,reply}.prompt` and `prompts/chat/private/{planner,reply}.prompt`. Load them through `src.common.prompt_manager.prompt_manager` and preserve their metadata, dotted IDs, sections, and native-tool output contract.

`brain_chat/PFC/` and `prompts/chat/private/pfc/` are retained legacy implementations and are not imported by the active private runtime. Do not extend or reconnect them unless the task explicitly targets a migration or removal.

## Verification
Run focused tests with:

```bash
uv run python -m unittest tests.test_chat_tool_registry tests.test_private_tool_pipeline
uv run python -m unittest tests.test_heartflow_core tests.test_planner_actions
```

Add or update `tests/test_<area>.py` for changed turn, planner, reply, message, or media behavior.
