# 提示词目录

提示词按业务领域存放，文件路径就是正式 ID。不要在 `prompts/` 根目录新增 `.prompt` 文件。

例如：

- `prompts/chat/group/planner.prompt` 对应 `chat.group.planner`
- `prompts/media/vision/static.prompt` 对应 `media.vision.static`

## 层级模型

提示词按五个维度定位，阅读时不要只看文件名：

1. **领域（目录）**：`chat`、`learning`、`media`、`memory`、`shared` 表示业务归属。
2. **形态（`kind`）**：`template` 表示完整模型任务；存在 `variants` 时，每个命名分段分别是一份完整任务。`fragment` 只能注入其他模板，不能独立代表一次模型任务。
3. **阶段（`stage`）**：说明该提示词处于规划、生成、评估、学习、感知、记忆等哪一环。
4. **生命周期（`status`）**：`active` 仍在正式运行；`fallback` 只服务配置回退；`legacy` 仅保留旧架构兼容，不应作为新代码范例。
5. **变体（`variants` / `###SECTION`）**：同一任务的固定变体使用文件内命名分段；运行时 ID 为“文件 ID + 分段名”。

当前消息主链路恰好由四个文件承担：

- 群聊规划：`chat.group.planner`。Planner 可调用原生插件 Tool、由 legacy Action 适配的 Tool 或内置 `reply`；无 Tool Call 即保持静默并结束本轮。
- 群聊回复：`chat.group.reply.*`。只有 Planner 调用 `reply` 时才进入 `light` 或 `standard` 分段。
- 私聊规划：`chat.private.planner`。Planner 可先执行原生插件 Tool 或由 legacy Action 适配的 Tool 并读取结果，再决定是否调用内置 `reply`；无 Tool Call 即结束本轮。
- 私聊回复：`chat.private.reply.default`。`chat.private.reply.self` 与它同属一个文件，只保留给显式续写兼容调用，不属于 Planner 自动消息主链。

两个 Planner 的可用工具定义、参数 schema 和使用说明通过模型请求的原生 `tools` 参数传入，正文不再拼接 Action JSON fragment。legacy `BaseAction` 在模型侧也只是 Tool，仅在执行边界通过 `ActionManager.create_action(...).execute()` 保留旧插件兼容。`reply` 也是内置 Tool；模型普通文本不会发送给用户，所有实际行为都以 Tool Call 表达。

- `chat.shared.expressor` 只由 `GeneratorAPI.rewrite_reply()` 显式调用，不是消息主链路的自动后处理。
- `shared.tool_executor` 只由 `ToolExecutor.execute_from_chat_message()` 等显式工具判断 API 调用，不是四文件主链中的 Planner 或 Replyer。
- `chat.private.pfc.*` 是旧 PFC 状态机模板，不属于当前私聊主链路。

## 目录职责

| 目录 | 用途 |
| --- | --- |
| `chat/` | 群聊、私聊、PFC、回复与表达器 |
| `learning/` | 行为、表达方式和黑话学习 |
| `media/` | 静态/动态图像识别、音频转写与表情包下游处理 |
| `memory/` | 记忆抽取、检索、判断与知识查询 |
| `shared/` | 多条业务链共用的审核和工具提示词 |

## 文件契约

每个仓库内 `.prompt` 文件必须以维护元数据开头。元数据只供加载器、测试和维护者读取，加载时会被剥离，不会发送给模型。

```text
###PROMPT_META###
id: chat.group.reply
kind: template
stage: generation
status: active
summary: 根据规划目标与聊天证据生成群聊回复
output: plain_text
variants: light, standard
###END_PROMPT_META###
```

- `id` 必须与文件路径完全一致。
- `kind` 只能是 `template` 或 `fragment`。
- `status` 只能是 `active`、`fallback` 或 `legacy`。
- `stage`、`summary`、`output` 必须准确描述实际调用职责和输出协议。
- 存在 `###SECTION` 时，`variants` 必须与实际分段一一对应；无分段时不得声明 `variants`。

各分段继承所属文件的同一份元数据。`PromptManager.get_prompt_metadata()` 可使用正式分段 ID 或旧别名查询；聊天上下文覆盖只替换运行时正文，不改变规范文件元数据。

当前 `stage` 约定：`planning` 负责动作或工具决策，`generation` 负责文本生成或改写，`evaluation` 负责判断与选择，`learning` 负责规律提取，`memory` 负责记忆处理，`perception` 负责视觉理解，`transcription` 负责音频转写，`policy` 负责可注入的内容边界。

| `output` | 输出契约 |
| --- | --- |
| `fragment` | 只作为其他模板的一部分，不单独调用模型。 |
| `plain_text` | 只返回自然语言正文，不附加结构化包裹。 |
| `strict_json` | 只返回合法 JSON 对象或数组。 |
| `reasoned_jsonl` | 先给简短理由，再在 JSON 代码块中逐行输出对象。 |
| `native_tool` | 主要结果通过模型原生 Tool Call 表达；工具定义与参数 schema 由请求的 `tools` 参数提供，无调用时按正文约定结束或静默。 |
| `label` | 只返回模板列出的单个标签或短决策值。 |
| `transcript` | 只返回忠实音频转写。 |
| `mixed` | 同一文件的不同 `variants` 使用不同输出协议，必须查看具体分段。 |

当前聊天主链路的完整规划、生成模板会在最终模型调用边界拆成两条有角色的消息。Prompt hook 和日志仍看到完整渲染文本，因此现有插件无需改写接口：

1. `system` 消息使用单一 `<instructions>` 根节点，依次包含 `<task>`、`<runtime_constraints>` 和 `<output_protocol>`，用于稳定身份、决策规则、内容边界及唯一输出格式。
2. `<!-- RIYABOT_DYNAMIC_CONTEXT -->` 是唯一的角色分界标记；每个主链模板及其每个 `###SECTION` 必须恰好出现一次。
3. `user` 消息使用单一 `<input_data>` 根节点，包含时间、聊天记录、记忆、工具结果等本轮动态且不可信的数据。
4. 动态消息以 `<decision_focus>` 或 `<reply_focus>` 结束，把当前目标放在最接近模型输出的位置，避免被较早的候选资料淹没。

主链聊天记录使用 XML 容器包裹 JSONL。每条消息固定包含 `msg_id`、`group_name`、`user_name`、`uid`、`time`、`content`；已读和未读记录分别放入 `<read_messages>` 与 `<unread_messages>`，普通记录放入 `<messages>`。JSON 字符串中的 `<`、`>`、`&` 会编码为 Unicode 转义，防止消息正文伪造或提前闭合 XML 边界。

不要把聊天记录、检索结果、工具返回或关键词捕获文本放到分界标记之前；不要在动态输入之后重复或改写输出协议。若插件完整替换 Prompt、移除标记或产生畸形标记，调用层会兼容回退为旧的单条 `user` 消息，不会猜测插件文本的可信边界。

## 占位符说明

正文中的 `{name}` 是 Python 命名格式化占位符，由调用方在运行时填入；`{{` 和 `}}` 表示要保留到最终提示词里的 JSON 花括号，不是占位符。名称以 `_block`、`_str`、`_text`、`_prompt` 或 `_section` 结尾的值通常已经由上游格式化成完整文本块，可能为空，不要在模板里猜测其内部结构。

### 公共身份、时间与策略

| 占位符 | 含义与来源 |
| --- | --- |
| `bot_name` | 机器人主昵称，通常来自 `global_config.bot.nickname`。 |
| `bot_nickname` | 面向自然语言展示的机器人昵称，用于表情包容量决策等场景。 |
| `time_block` | 已带说明文字的当前时间块，例如“当前时间：2026-07-15 17:30:00”。 |
| `time_now` | 仅包含格式化后当前时间的字符串，由模板自行添加标签。 |
| `name_block` | 机器人主昵称、别名以及“区分自己发言”的完整身份提示块。 |
| `identity` | 当前人格与身份说明，来自回复器构建的人设文本。 |
| `persona_text` | 旧 PFC 链路使用的人格说明；语义接近 `identity`，但由 PFC 组件独立构建。 |
| `chat_prompt` | 针对当前聊天配置的附加人设或说话规则；未配置时为空。 |
| `reply_style` | 当前回复风格，来自 `personality.reply_style`。 |
| `moderation_prompt` | 从 `shared.moderation.*` 注入的内容边界片段。 |
| `keywords_reaction_prompt` | 回复器根据配置命中结果生成的候选反应提示，可能含目标消息的正则捕获文本；没有匹配规则时为空，并始终放在不可信输入层。 |
| `expression_habits_block` | 表达学习器选出的候选表达习惯与行为参考，只是低优先级参考数据。 |

### 聊天对象、记录与回复目标

| 占位符 | 含义与来源 |
| --- | --- |
| `sender` | 当前目标消息的发送者显示名，常与 `target_message` 一起使用。 |
| `sender_name` | 私聊对象的显示名，用于区分机器人与对方的发言。 |
| `chat_target` | 当前聊天对象或由调用方拼好的聊天场景引导文本；具体形式由模板调用点决定。 |
| `chat_target_2` | `chat.shared.expressor` 使用的简短场景短语，例如“正在群里聊天”或“和某人聊天”。 |
| `chat_content` | 私聊原生 Tool Planner 读取的 XML + JSONL 聊天记录，消息 ID 位于每条对象的 `msg_id` 字段。 |
| `chat_content_block` | 群聊原生 Tool Planner 使用的 XML + JSONL 完整聊天块，可含已读/未读分区和动作记录。 |
| `chat_history` | 供工具或记忆判断使用的最近聊天历史；是否预先做边界转义由调用方决定，模板始终把它视为不可信数据。 |
| `chat_history_text` | 旧 PFC 组件使用的可读聊天历史，可能附带“新消息”分隔说明。 |
| `chat_info` | Expressor 重写时使用的较短聊天上下文。 |
| `chat_str` | 学习器使用的带行号聊天文本，行号可被输出字段引用。 |
| `dialogue_prompt` | 回复生成器使用的 XML + JSONL 完整对话记录。 |
| `message_block` | 记忆 L1 话题切分器使用的、带 `message_id` 的连续消息块。 |
| `messages_text` | 表情情感标签选择器使用的最近聊天文本。 |
| `conversation_text` | 记忆原子提取器边界内的原始对话消息。 |
| `context_block` | 表达反馈判定器读取的后续对话片段。 |
| `chat_context` | 黑话解释整理器使用的当前聊天上下文。 |
| `chat_observe_info` | 表达情境选择器使用的当前聊天观察摘要。 |
| `target` | `chat.private.reply.self` 中机器人自己刚发送、需要续接的消息。 |
| `target_message` | 当前要处理的目标消息正文；工具和记忆判断模板会与 `sender` 配对展示。 |
| `reply_target_block` | 回复器根据发送者、文字和图片内容构建的完整“本轮回复目标”说明。 |
| `planner_reasoning` | Planner 传给 Replyer 的回复原因或回答重点，不是最终回复文本。 |
| `reply_reason_block` | 表达情境选择器使用的、已格式化的回复理由块；没有理由时可为空。 |
| `reason` | 当前任务的直接原因；按模板分别表示续写原因、改写原因或表情发送原因。 |
| `reasoning` | 旧 PFC 目标的设定依据，与 `goal` 配套使用。 |
| `raw_reply` | Expressor 要改写的候选原句。 |
| `reply` | 旧 PFC 回复检查器要审核的待发送文本。 |

### 候选资料、工具结果与记忆证据

| 占位符 | 含义与来源 |
| --- | --- |
| `extra_info_block` | Planner 已完成的查询结果、插件、事件或调用方提供的额外参考信息；没有额外信息时为空。 |
| `tool_info_block` | 显式 ToolExecutor API 提供给 Replyer 的兼容工具结果；四文件主链关闭 Replyer 二次工具调度时通常为空。 |
| `tool_results_block` | 私聊原生 Tool Planner 循环中本轮已执行工具的 JSON 结果列表；首轮为“无”。 |
| `knowledge_prompt` | 旧知识查询接口返回并格式化后的候选知识文本。 |
| `knowledge_info_str` | 旧 PFC 链路使用的低优先级记忆证据块。 |
| `memory_context_block` | 群聊 Planner 使用的短记忆候选证据。 |
| `memory_retrieval` | Replyer 使用的新记忆系统证据块，通常包含 `<CONTEXT_EVIDENCE>` 边界。 |
| `jargon_explanation` | 针对当前目标整理后的黑话解释文本。 |
| `jargon_explanations` | 黑话解释整理器收到的多个词条及已有释义。 |
| `topic_summary` | 记忆 L1 生成的话题摘要，只用于帮助理解，不是新增事实来源。 |
| `scene_profile` | 行为学习器使用的场景画像，只帮助定位互动场景。 |

### 工具、规划历史与旧 PFC 状态

| 占位符 | 含义与来源 |
| --- | --- |
| `actions_before_now_block` | 群聊 Planner 最近的工具选择、执行结果或思考记录，用于防止重复动作。 |
| `action_history_summary` | 旧 PFC ActionPlanner 使用的近期行动状态摘要。 |
| `action_history_text` | 旧 PFC GoalAnalyzer 使用的既往行动可读文本。 |
| `last_action_context` | 旧 PFC 最近一次行动的详细规划、执行状态与失败原因。 |
| `time_since_last_bot_message_info` | 旧 PFC 中距离机器人上次发言的时间说明。 |
| `timeout_context` | 旧 PFC 等待超时或会话超时的补充提示。 |
| `goal` | 旧 PFC 当前正在评估的单个对话目标。 |
| `goals_str` | 旧 PFC 当前目标列表的格式化文本。 |

### 表达学习与黑话学习

| 占位符 | 含义与来源 |
| --- | --- |
| `criteria_list` | 表达自动审核必须逐项满足的标准列表。 |
| `situation` | 单个表达方式的适用情境。 |
| `situations` | 待归纳的多个聊天情境文本。 |
| `style` | 单个待审核、反馈或学习的表达方式描述。 |
| `all_situations` | 表达选择器当前可选的、带从 1 开始编号的情境列表。 |
| `max_num` | 当前任务允许选择或容纳的最大数量；在表达选择器和表情库模板中语义由上下文分别限定。 |
| `target_message_extra_block` | 有明确目标消息时追加的选择限制；无目标时可为空。 |
| `content` | 当前待推断的黑话或词条原文。 |
| `raw_content_list` | 该词条在真实聊天中出现的多条上下文。 |
| `previous_meaning` | 数据库中保存的上一次词义推断，必须由新上下文重新核验。 |
| `previous_meaning_section` | 包含 `previous_meaning` 的完整可选上下文分段；无旧释义时为空。 |
| `previous_meaning_instruction` | 旧释义存在时注入的使用约束分段；无旧释义时为空。 |
| `inference1` | 结合真实聊天上下文得到的词义推断 JSON。 |
| `inference2` | 仅根据词条字面和通用语言知识得到的词义推断 JSON。 |

### 图像、音频与表情包

| 占位符 | 含义与来源 |
| --- | --- |
| `filtration_prompt` | 配置中追加的表情包入库过滤规则。 |
| `current_num` | 当前已存储的表情包数量。 |
| `new_description` | 准备入库的新表情包语义描述。 |
| `emoji_list` | 为替换决策抽样出的旧表情包编号、描述和使用信息列表。 |
| `emoji_candidates` | 本轮允许选择的表情包候选列表；每行包含临时候选 ID 和完整语义描述。 |
| `description` | 视觉模型生成的原始表情包描述，供多维语义压缩器整理。 |
| `frame_count` | 动态图像的总帧数。 |
| `frame_start` | 当前批次第一帧的全局序号。 |
| `frame_end` | 当前批次最后一帧的全局序号。 |
| `previous_batch_description` | 上一批动态画面的原始视觉描述，只用于衔接当前批次首帧。 |

### 记忆检索与噪声审阅

| 占位符 | 含义与来源 |
| --- | --- |
| `recent_query_history` | 同一上下文最近执行过的记忆问题及结果，用于避免重复检索。 |
| `question` | 当前唯一的记忆检索问题。 |
| `collected_info` | 记忆检索代理迄今从工具获得的候选证据集合。 |
| `entries_text` | NoisePool 中待共同审阅的、带编号噪声片段。 |

## 维护规则

1. 业务代码统一通过 `src.common.prompt_manager.prompt_manager` 获取或格式化提示词。
2. 同一任务的固定变体放在一个文件的 `###SECTION: name` 分段中，不复制整份文件。
3. 新文件使用简短的任务名，领域信息由目录表达，避免 `*_prompt`、`default_*_prompt` 之类重复前后缀。
4. 删除模板前先确认没有运行时引用，并同步更新 `tests/test_prompt_template_contracts.py`。
5. 旧 ID 的兼容只维护在 `LEGACY_PROMPT_ALIASES`，不要为兼容复制旧路径文件。
6. 分段必须显式使用 `###END_SECTION###` 结束。禁止重复、嵌套、空分段、非法分段名或分段外正文。
7. 四个消息主链模板必须保持唯一 `RIYABOT_DYNAMIC_CONTEXT` 分界，并把当前决策或回复焦点留在动态上下文末尾。
8. 修改后运行 `uv run python -m unittest tests.test_prompt_template_contracts tests.test_unified_prompt_manager`。
