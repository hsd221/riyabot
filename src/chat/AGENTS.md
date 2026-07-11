# src/chat/ — Chat Engine

Largest subsystem (21k lines, 60+ files). Dual-path cognitive architecture for group vs private chat.

## STRUCTURE
```
chat/
├── message_receive/     # Inbound pipeline: ChatStream, MessageRecv, UniversalMessageSender
├── heart_flow/          # Group chat main loop: Heartflow → HeartFChatting (750 lines)
├── planner_actions/     # Group chat LLM planner: ActionPlanner (882 lines, ReAct-style)
├── brain_chat/          # Private chat: TurnGate → native-tool Planner → ToolRegistry → Replyer
├── brain_chat/PFC/      # ★ Prefrontal Cortex state machine (16 files, literal brain metaphor)
├── replyer/             # LLM reply gen: group_generator (1251) + private_generator (1116)
├── knowledge/           # [已移除] LPMM knowledge base — 不要导入旧模块
├── emoji_system/        # EmojiManager singleton (1154 lines): registration + LLM tagging
├── utils/               # statistic.py (2307!), chat_message_builder (1085), utils (986)
└── logger/              # PlanReplyLogger: disk logs for LLM plan/reply traces
```

## WHERE TO LOOK
| Task | Location |
|------|----------|
| Group chat behavior | `heart_flow/heartFC_chat.py` + `planner_actions/planner.py` |
| Private chat behavior | `brain_chat/brain_chat.py` + `brain_chat/private_tool_pipeline.py` |
| Reply text generation | `replyer/group_generator.py` / `private_generator.py` |
| Tool/reply selection (private) | `brain_chat/private_tool_pipeline.py` (native tool calls; no JSON action protocol) |
| Goal setting | `PFC/pfc.py` (GoalAnalyzer, max 3 concurrent goals) |
| Knowledge retrieval | `PFC/pfc_KnowledgeFetcher.py`（桥接新记忆系统，返回低优先级证据块） |
| Message context building | `utils/chat_message_builder.py` |
| LLM usage stats / HTML report | `utils/statistic.py` (900-line inline HTML template) |

## PFC COMPONENT MAP (brain metaphor)
| Component | Cognitive role | File |
|-----------|---------------|------|
| ChatObserver | Sensory cortex | `PFC/chat_observer.py` |
| ObservationInfo | Working memory | `PFC/observation_info.py` |
| GoalAnalyzer | dlPFC (planning) | `PFC/pfc.py` |
| ActionPlanner | Premotor cortex | `PFC/action_planner.py` |
| ReplyGenerator | Broca's area | `PFC/reply_generator.py` |
| ReplyChecker | ACC (error monitor) | `PFC/reply_checker.py` |
| KnowledgeFetcher | Memory evidence bridge | `PFC/pfc_KnowledgeFetcher.py`（返回低优先级候选证据） |
| Waiter | Attention | `PFC/waiter.py` (300s timeout, 5s poll) |
| Conversation | Global coordinator | `PFC/conversation.py` (701 lines) |

Active private flow: inbound → pure-code TurnGate → native-tool Planner → plugin tools or built-in `reply` → Replyer → outbound.

The old `BrainPlanner`/Action chain remains only as the `experimental.private_tool_pipeline = false` rollback path. PFC is not the active private runtime.

## CONVENTIONS
- **Logger prefixes**: `"bc"` (BrainChat), `"hfc"` (HeartFChat), `"pfc"`, `"planner"`, `"replyer"`, `"emoji"`.
- **Singletons**: `PFCManager`, `ChatManager`, `EmojiManager` — explicit `_instance` attr.
- **Tight coupling** with `bw_learner` (expression learning) and `memory_system`.
- **Two active planner systems coexist**: `planner_actions/` (group JSON actions) vs `brain_chat/private_tool_pipeline.py` (private native tools).

## ANTI-PATTERNS
- **DO NOT import** `knowledge/mem_active_manager.py` — crashes with DeprecationWarning.
- **`listening` action renamed to `wait`** — backward-compat conversion in `brain_planner.py:205`.
- **`conversation.py:698`** has literal `"TODO:超时消息"` placeholder string.
- **`qa_manager.py:63`** — LLM triplet filter is a stub (TODO).
