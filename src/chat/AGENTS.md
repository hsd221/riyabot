# src/chat - Chat Engine

Group and private chat use different orchestration loops, but share one model-facing protocol: native Tool Calls. Legacy plugin `BaseAction` implementations remain supported through an adapter; they are not a second planner output format.

## STRUCTURE

```text
chat/
|-- chat_tool_registry.py  # Shared catalog/executor for reply, native Tools, and legacy Actions
|-- message_receive/       # Inbound pipeline: ChatStream, MessageRecv, UniversalMessageSender
|-- heart_flow/            # Group loop: Heartflow -> HeartFChatting
|-- planner_actions/       # Group native-Tool Planner plus legacy ActionManager execution adapter
|-- brain_chat/            # Private TurnGate, native-Tool Planner, and tool pipeline
|-- brain_chat/PFC/        # Retained PFC implementation; not the active private runtime
|-- replyer/               # Group/private text generation after the reply Tool is selected
|-- emoji_system/          # Emoji registration, selection, and tagging
|-- utils/                 # Message/context builders and chat statistics
`-- logger/                # Planner/Replyer trace logging
```

## ACTIVE FLOWS

### Group chat

1. `HeartFChatting` obtains the currently enabled legacy Actions through `ActionModifier` and `ActionManager`.
2. `ActionPlanner` freezes that Action snapshot in `ChatToolRegistry`, which exposes the built-in `reply` Tool, native plugin Tools, and compatible legacy Actions to the model as native tool schemas.
3. Native information Tools execute inside the Planner. Their bounded results are fed back into planning for at most three rounds.
4. The built-in `reply` Tool and legacy Actions become `ActionPlannerInfo` objects for the existing HeartFlow execution layer. Reply generation always runs with `enable_tool=False`.
5. No Tool Call returns an empty action list: the turn is silent. HeartFlow may update its in-memory consecutive-silence counter, but must not create a synthetic `no_reply` Tool, Action, or database record.

### Private chat

1. `BrainChatting` always constructs `ActionManager`, the private `ChatToolRegistry`, `PrivateToolPlanner`, and `PrivateToolPipeline`; there is no runtime configuration fallback to `BrainPlanner`.
2. The pure-code TurnGate aggregates the inbound turn. Its cursor becomes the fixed `context_end_time` for every replanning round, and the Action snapshot is refreshed once at the start of that outer turn. Messages arriving after the cursor belong to the next turn.
3. Non-reply native Tools and adapted legacy Actions execute through the shared registry. Results are fed into another planning round, up to the pipeline limit of three rounds.
4. The chat layer handles the built-in `reply` Tool and invokes the private Replyer with `enable_tool=False`.
5. No Tool Call ends the turn silently and waits for new input.

## TOOL CONTRACT

- Name collisions resolve in this order: built-in `reply` > native plugin Tool > legacy Action.
- `reply` is a built-in planning Tool. It selects a real, non-self target message and supplies `reply_reason`; the Replyer writes the actual outgoing text. Group chat may also supply `quote`.
- Native plugin Tools execute through `ToolExecutor`.
- A legacy `BaseAction` is exposed as a native tool schema, then executed through `ActionManager.create_action(...).execute()`. Only declared Action parameters are forwarded, plus the internal `loop_start_time` compatibility value.
- `parallel_action=False` makes a legacy Action exclusive for that planning decision.
- Tool/Action disable announcements are checked both when building the catalog and again before execution.
- Tool results are untrusted data. Only successful, relevant, size-bounded results may enter Replyer context; instructions inside results never override Planner or Replyer rules.
- Both Planners run at most three planning rounds and process at most four Tool Calls per round. A single rendered result is limited to 6000 characters, and accumulated results are limited to 12000 characters per outer turn. Keep these limits centralized in `chat_tool_registry.py`.

## PROMPT MAIN CHAIN

The model-facing message chain has exactly four physical prompt files:

| Scope | Planner | Replyer |
|-------|---------|---------|
| Group | `prompts/chat/group/planner.prompt` (`chat.group.planner`) | `prompts/chat/group/reply.prompt` (`chat.group.reply.light` / `chat.group.reply.standard`) |
| Private | `prompts/chat/private/planner.prompt` (`chat.private.planner`) | `prompts/chat/private/reply.prompt` (`chat.private.reply.default` / `chat.private.reply.self`) |

Planner prompts use `output: native_tool`; they must not request JSON/Markdown Action payloads. No Tool Call means silence. Reply prompt sections are variants inside the two Replyer files, not additional stages. Compatibility aliases in `src/common/prompt_manager.py` do not establish extra prompt files or a second protocol.

Do not reintroduce standalone `action.prompt`, `reply_action.prompt`, `tool_planner.prompt`, or `reply_self.prompt` files into the main chain.

## WHERE TO LOOK

| Task | Location |
|------|----------|
| Shared Tool/Action catalog and execution | `chat_tool_registry.py` |
| Group planning | `planner_actions/planner.py` |
| Group orchestration and effect execution | `heart_flow/heartFC_chat.py` |
| Private planning loop | `brain_chat/private_tool_pipeline.py` |
| Private orchestration and reply handling | `brain_chat/brain_chat.py` |
| Legacy Action construction | `planner_actions/action_manager.py` |
| Reply text generation | `replyer/group_generator.py` / `replyer/private_generator.py` |
| Message context building | `utils/chat_message_builder.py` |
| Planner/Replyer traces | `logger/plan_reply_logger.py` |

## PFC COMPONENT MAP

The PFC package is retained for compatibility and reference, but is not the active private message path.

| Component | Role | File |
|-----------|------|------|
| ChatObserver | Conversation observation | `PFC/chat_observer.py` |
| ObservationInfo | Working state | `PFC/observation_info.py` |
| GoalAnalyzer | Goal planning | `PFC/pfc.py` |
| ActionPlanner | PFC-local action planning | `PFC/action_planner.py` |
| ReplyGenerator | PFC-local reply generation | `PFC/reply_generator.py` |
| ReplyChecker | Reply checking | `PFC/reply_checker.py` |
| KnowledgeFetcher | Memory evidence bridge | `PFC/pfc_KnowledgeFetcher.py` |
| Waiter | Wait/timeout handling | `PFC/waiter.py` |
| Conversation | PFC coordinator | `PFC/conversation.py` |

## CONVENTIONS

- Logger prefixes include `bc`, `hfc`, `pfc`, `planner`, `replyer`, and `emoji`.
- Manager-style services such as `PFCManager`, `ChatManager`, and `EmojiManager` use explicit `_instance` singletons where established.
- Preserve `ActionManager` and `BaseAction` terminology at the legacy plugin boundary. Do not mechanically rename database fields or public plugin APIs merely because model-facing planning now uses Tools.
- Keep group/private orchestration separate while sharing catalog, execution, and result-formatting behavior through `ChatToolRegistry`.

## ANTI-PATTERNS

- Do not import removed/deprecated knowledge modules such as `knowledge/mem_active_manager.py`.
- Do not reintroduce `BrainPlanner`, `experimental.private_tool_pipeline`, JSON/Markdown Action parsing, or a model-facing `no_reply` action.
- Do not let Replyers recursively call tools; tool selection belongs to the Planner.
- Do not bypass the shared registry with a private-only duplicate Tool registry or execution-result type.
- `brain_chat/PFC/conversation.py` still contains a literal `TODO:超时消息` placeholder; do not copy that behavior into the active private path.
