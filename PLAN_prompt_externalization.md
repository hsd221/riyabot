# Prompt 外部化重构计划

## 概述

将所有硬编码的 LLM Prompt 从 Python 源码中提取到 `prompts/` 目录下的 `.prompt` 文件中，遵循上游 MaiBot v1.0.7 的架构（去除多语种子目录，单一简体中文）。保留 `global_prompt_manager.format_prompt()` API 不变以保证向后兼容。

---

## 1. 目录结构设计

```
prompts/
  # === replyer/prompt/ (4个现有文件 → 6个 .prompt 文件) ===
  replyer_group.prompt              # replyer_prompt_0 + replyer_prompt 合并
  replyer_private.prompt            # private_replyer_prompt
  replyer_private_self.prompt       # private_replyer_self_prompt
  lpmm_get_knowledge.prompt         # lpmm_get_knowledge_prompt
  default_expressor.prompt          # default_expressor_prompt
  # (chat_target_group1/2, chat_target_private1/2 是极短片段，保持 inline 或直接删除)

  # === planner_actions/ + brain_chat/ (4个命名 + 6个常量) ===
  planner_group.prompt              # planner_prompt
  action_template.prompt            # action_prompt
  brain_planner_react.prompt        # brain_planner_prompt_react
  brain_action_template.prompt      # brain_action_prompt
  pfc_action_decision.prompt         # PROMPT_INITIAL_REPLY + FOLLOW_UP + END_DECISION 合并
  pfc_reply_generation.prompt       # PROMPT_DIRECT_REPLY + SEND_NEW_MESSAGE + FAREWELL 合并
  pfc_reply_check.prompt            # reply_checker inline prompt

  # === emoji_system/ ===
  emoji_vlm_description.prompt      # GIF + 静态图描述 prompt 合并
  emoji_content_filter.prompt       # 内容审核 prompt
  emoji_emotion_analysis.prompt     # 情感分析 prompt
  emoji_replace_decision.prompt     # 替换决策 prompt

  # === knowledge/ ===
  entity_extract_system.prompt      # entity_extract_system_prompt
  rdf_triple_extract_system.prompt  # rdf_triple_extract_system_prompt
  qa_system.prompt                  # qa_system_prompt

  # === memory_system/ ===
  memory_retrieval.prompt           # memory_retrieval question + react_head + final 合并
  hippo_topic_analysis.prompt       # hippo_topic_analysis_prompt
  hippo_topic_summary.prompt        # hippo_topic_summary_prompt

  # === bw_learner/ ===
  learn_style.prompt                # learn_style_prompt
  expression_evaluation.prompt      # expression_evaluation_prompt
  expression_auto_check.prompt      # create_evaluation_prompt() 模板
  reflect_judge.prompt              # reflect_judge_prompt
  jargon_inference_with_context.prompt   # jargon_inference_with_context_prompt
  jargon_inference_content_only.prompt   # jargon_inference_content_only_prompt
  jargon_compare_inference.prompt        # jargon_compare_inference_prompt
  jargon_explainer_summarize.prompt      # jargon_explainer_summarize_prompt

  # === dream/ ===
  dream_react_head.prompt           # dream_react_head_prompt
  dream_summary.prompt              # dream_summary_prompt

  # === person_info/ ===
  person_nickname.prompt            # qv_name_prompt 字符串拼接 → 单文件

  # === plugin_system/ ===
  tool_executor.prompt              # tool_executor_prompt

  # === llm_models/ ===
  audio_transcription.prompt        # Gemini转录 prompt

  # === PFC GoalAnalyzer (2个inline f-string) ===
  pfc_goal_analyzer.prompt          # pfc.py 中 GoalAnalyzer 的 analyze_goal f-string
  pfc_goal_analyzer_assess.prompt   # pfc.py 中 analyze_conversation f-string
```

**总计：约 30 个 `.prompt` 文件**（覆盖全部 ~42 个命名 prompt + ~15 个 inline/constant prompt，通过合并 PFC action 3→1、PFC reply 3→1、emoji VLM 2→1、memory_retrieval 3→1 减少过细拆分，接近上游 v1.0.7 的 22 个规模）。

---

## 2. 文件内容设计

### 2.1 设计原则

| 原则 | 说明 |
|------|------|
| **占位符** | 仅使用 `{variable_name}` 格式，兼容 Python `str.format()` |
| **字面花括号** | `{{` / `}}` (如 JSON 示例) |
| **分段模板** | 子块保留为 `{sub_block}` 变量，运行时注入（如 `{expression_habits_block}`） |
| **合并拼接** | 多段拼接的 prompt（如 `qs_name_prompt`）整合为单一文件 |
| **保留说明** | 关键逻辑注释保留为文件内容中的普通文本 |

### 2.2 典型文件设计示例

#### `prompts/zh-CN/replyer_group.prompt`
```prompt
{knowledge_prompt}{tool_info_block}{extra_info_block}
{expression_habits_block}{memory_retrieval}{jargon_explanation}

你正在qq群里聊天，下面是群里正在聊的内容，其中包含聊天记录和聊天中的图片
其中标注 {bot_name}(你) 的发言是你自己的发言，请注意区分:
{time_block}
{dialogue_prompt}

{reply_target_block}。
{planner_reasoning}
{identity}
{chat_prompt}你正在群里聊天,现在请你读读之前的聊天记录，然后给出日常且口语化的回复，
尽量简短一些。{keywords_reaction_prompt}
请注意把握聊天内容，不要回复的太有条理。
{reply_style}
请注意不要输出多余内容(包括不必要的前后缀，冒号，括号，表情包，at或 @等 )，只输出发言内容就好。
最好一次对一个话题进行回复，免得啰嗦或者回复内容太乱。
现在，你说：
```

**说明**：`replyer_prompt_0` 和 `replyer_prompt` 仅微小差异（"尽量简短/不要太有条理" vs "把握当前话题"），实际 `replyer_prompt`（第二个注册的）覆盖前一个。故只保留一个 `.prompt` 文件，在 `build_group_reply_prompt()` 中通过 `chat_prompt` 或 `reply_style` 变量注入差异。

#### `prompts/zh-CN/pfc_action_initial_reply.prompt`
```prompt
{persona_text}。现在你在参与一场QQ私聊，请根据以下【所有信息】审慎且灵活的决策下一步行动，可以回复，可以倾听，可以调取知识，甚至可以屏蔽对方：

【当前对话目标】
{goals_str}
{knowledge_info_str}

【最近行动历史概要】
{action_history_summary}
【上一次行动的详细情况和结果】
{last_action_context}
【时间和超时提示】
{time_since_last_bot_message_info}{timeout_context}
【最近的对话记录】(包括你已成功发送的消息 和 新收到的消息)
{chat_history_text}

------
可选行动类型以及解释：
fetch_knowledge: 需要调取知识或记忆，当需要专业知识或特定信息时选择，对方若提到你不太认识的人名或实体也可以尝试选择
listening: 倾听对方发言，当你认为对方话才说到一半，发言明显未结束时选择
direct_reply: 直接回复对方
rethink_goal: 思考一个对话目标，当你觉得目前对话需要目标，或当前目标不再适用，或话题卡住时选择。注意私聊的环境是灵活的，有可能需要经常选择
end_conversation: 结束对话，对方长时间没回复或者当你觉得对话告一段落时可以选择
block_and_ignore: 更加极端的结束对话方式，直接结束对话并在一段时间内无视对方所有发言（屏蔽），当对话让你感到十分不适，或你遭到各类骚扰时选择

请以JSON格式输出你的决策：
{{
    "action": "选择的行动类型 (必须是上面列表中的一个)",
    "reason": "选择该行动的详细原因 (必须有解释你是如何根据"上一次行动结果"、"对话记录"和自身设定人设做出合理判断的)"
}}

注意：请严格按照JSON格式输出，不要包含任何其他内容。
```

**注意**：`{persona_text}` 包含 `你的名字是{bot_name},{personality};`，但不要在 `.prompt` 中写两者混合——`persona_text` 本身已经是一个独立的运行时构建块，注入即可。如果 `persona_text` 也是外部化的，则需要另一个 `.prompt`，但为了最小化侵入，`persona_text` 建议保持 inline。

#### `prompts/zh-CN/person_nickname.prompt`
```prompt
你是{bot_name}，一个伪装成人类的AI，你不能让别人发现这一点，
现在你想给一个用户取一个昵称，用户的qq昵称是{user_nickname}，
用户的qq群昵称名是{user_cardname}，
{user_avatar_line}
{old_name_line}
其他取名的要求是：{request}，不要太浮夸，简短，
请根据以上用户信息，想想你叫他什么比较好，不要太浮夸，请最好使用用户的qq昵称或群昵称原文，可以稍作修改，优先使用原文。优先使用用户的qq昵称或者群昵称原文。
{existing_names_block}
{known_nicknames_block}
请用json给出你的想法，并给出理由，示例如下：
{{
    "nickname": "昵称",
    "reason": "理由"
}}
```

**说明**：将原有的字符串拼接 `+=` 逻辑转为条件构造的模板变量：
- `{user_avatar_line}`：如果有头像则填入，否则空字符串
- `{old_name_line}`：如果有旧名则填入，否则空字符串
- `{existing_names_block}`：如果有已尝试名称则填入，否则空字符串
- `{known_nicknames_block}`：如果已知昵称不多则填入，否则空字符串

#### `prompts/zh-CN/planner_group.prompt`
```prompt
{time_block}
{name_block}
{chat_context_description}，以下是具体的聊天内容
**聊天内容**
{chat_content_block}

**可选的action**
reply
动作描述：
1.你可以选择呼叫了你的名字，但是你没有做出回应的消息进行回复
2.你可以自然的顺着正在进行的聊天内容进行回复或自然的提出一个问题
3.最好一次对一个话题进行回复，免得啰嗦或者回复内容太乱。
4.不要选择回复你自己发送的消息
5.不要单独对表情包进行回复
6.将上下文中所有含义不明的，疑似黑话的，缩写词均写入unknown_words中
7.如果你对上下文存在疑问，有需要查询的问题，写入question中
{reply_action_example}

no_reply
动作描述：
保持沉默，不回复直到有新消息
控制聊天频率，不要太过频繁的发言
{{"action":"no_reply"}}

{action_options_text}

**你之前的action执行和思考记录**
{actions_before_now_block}

请选择**可选的**且符合使用条件的action，并说明触发action的消息id(消息id格式:m+数字)
先输出你的简短的选择思考理由，再输出你选择的action，理由不要分点，精简。
**动作选择要求**
请你根据聊天内容,用户的最新消息和以下标准选择合适的动作:
{plan_style}
{moderation_prompt}

target_message_id为必填，表示触发消息的id
请选择所有符合使用要求的action，每个动作最多选择一次，但是可以选择多个动作；
动作用json格式输出，用```json包裹，如果输出多个json，每个json都要单独一行放在同一个```json代码块内:
**示例**
// 理由文本（简短）
```json
{{"action":"动作名", "target_message_id":"m123", .....}}
{{"action":"动作名", "target_message_id":"m456", .....}}
```
```

**说明**：`{{"action":"..."}}` 中的双花括号在 `str.format()` 中会被转义为单花括号，符合原有设计。

#### `prompts/zh-CN/pfc_goal_analyzer.prompt`
```prompt
{persona_text}。现在你在参与一场QQ聊天，请分析以下聊天记录，并根据你的性格特征确定多个明确的对话目标。
这些目标应该反映出对话的不同方面和意图。

{action_history_text}
当前对话目标：
{goals_str}

聊天记录：
{chat_history_text}

请分析当前对话并确定最适合的对话目标。你可以：
1. 保持现有目标不变
2. 修改现有目标
3. 添加新目标
4. 删除不再相关的目标
5. 如果你想结束对话，请设置一个目标，目标goal为"结束对话"，原因reasoning为你希望结束对话

请以JSON数组格式输出当前的所有对话目标，每个目标包含以下字段：
1. goal: 对话目标（简短的一句话）
2. reasoning: 对话原因，为什么设定这个目标（简要解释）

输出格式示例：
[
{{
    "goal": "回答用户关于Python编程的具体问题",
    "reasoning": "用户提出了关于Python的技术问题，需要专业且准确的解答"
}},
{{
    "goal": "回答用户关于python安装的具体问题",
    "reasoning": "用户提出了关于Python的技术问题，需要专业且准确的解答"
}}
]
```

---

### 2.3 特殊处理

| 特殊情况 | 处理方式 |
|-----------|----------|
| **极短 fragment** (chat_target_group1/2, private1/2) | 删除 `.prompt` 文件；将内联文本直接写在调用处 |
| **`{reply_action_example}`** 在 `planner.py` 中条件构造 | 保留为运行时变量注入，`think_mode` 条件逻辑不变 |
| **`persona_text`** (`你的名字是{bot_name}，{personality}；`) | 保持 inline，在 `_get_personality_prompt()` 中构建（包含随机状态切换逻辑） |
| **`expression_auto_check_task.py`** 的 `create_evaluation_prompt()` | 模板固定部分 → `.prompt`，`criteria_list` 仍由代码动态构建后注入为 `{criteria_list}` |
| **`person_nickname.prompt`** 的条件行 | 改为由代码判断后传入空字符串或对应变量 |
| **`emoji_content_filter.prompt`** 中的 `{filtration_prompt}` | 从 `global_config.emoji.filtration_prompt` 注入 |

---

## 3. Loader 实现

### 3.1 `src/common/prompt_i18n.py` — 复制自 v1.0.7

从上游 `Mai-with-u/MaiBot` tag v1.0.7 复制 `src/common/prompt_i18n.py` (~415 行) 并适配：

```python
# src/common/prompt_i18n.py 核心 API
def load_prompt(name: str, locale: str = "zh-CN", **kwargs) -> str:
    """One-shot 加载 + 替换占位符
    
    优先级: data/custom_prompts/{locale}/{name}.prompt
          → data/custom_prompts/{name}.prompt
          → prompts/{locale}/{name}.prompt
          → prompts/{default_locale}/{name}.prompt (en-US fallback)
    """
    ...

def load_prompt_template(name: str, locale: str = "zh-CN") -> PromptTemplate:
    """返回未替换的模板对象"""
    ...

def clear_prompt_cache() -> None:
    """递增版本号，使所有缓存失效"""
    ...
```

**适配修改**：
1. 路径：`data/custom_prompts/` → 保留；`prompts/` → 当前项目根目录
2. 移除旧项目中与 MaiBot 旧架构耦合的代码（如 locale 推导、特殊 prompt 名称映射）
3. 保持 LRU 缓存和版本号失效机制
4. 缓存大小：默认 128 条目

### 3.2 `src/common/prompt_manager.py` — 复制自 v1.0.7

从上游复制 `src/prompt/prompt_manager.py` (~440 行) 并适配：

```python
# src/common/prompt_manager.py 核心 API
class Prompt:
    name: str
    template: str
    render_context: dict

class PromptManager:
    singleton
    
    def load_prompts(self, locale: str = "zh-CN") -> None:
        """扫描 prompts/{locale}/ 目录加载所有 .prompt 文件"""
        ...
    
    def get_prompt(self, name: str) -> Prompt:
        """获取 Prompt 对象"""
        ...
    
    def add_context(self, prompt: Prompt, key: str, value: Any) -> None:
        """向 Prompt 添加上下文（支持函数延迟求值）"""
        ...
    
    async def render_prompt(self, prompt: Prompt) -> str:
        """渲染最终字符串"""
        ...
```

**适配修改**：
1. 提取以 `.prompt` 扩展名结尾的文件名（不含扩展名作为 name）
2. 保留递归嵌套引用 `{prompt_name}`（一个 prompt 引用另一个）
3. 移除与旧 MaiBot 特定逻辑（如 MidTermMemory、PersonalityPrompt）
4. 检查 revision 实现热加载

### 3.3 集成到现有 PromptBuilder 系统

```
现有系统：                               新系统：
Prompt("""...""", "name")  ───►  prompts/zh-CN/name.prompt
global_prompt_manager.register() ───► prompt_manager.load_prompts() 替代
global_prompt_manager.format_prompt() ───► 保持 API 不变

兼容策略：
1. PromptBuilder 的 PromptManager.register() 仍保留
2. 注册的 prompt 优先于文件加载（逐步迁移）
3. 迁移完成后移除 register() 调用，只保留 load_prompts()
```

---

## 4. 代码修改清单

### 4.1 模块修改汇总

| # | 文件 | 修改内容 | 风险 |
|---|------|---------|------|
| A1 | `src/common/prompt_i18n.py` | **新建** — 复制上游 `load_prompt()` | 低 |
| A2 | `src/common/prompt_manager.py` | **新建** — 复制上游 `PromptManager` | 低 |
| A3 | `src/main.py` | 在 `_init_components()` 末尾添加 `prompt_manager.load_prompts()` | 低 |
| A4 | `src/chat/utils/prompt_builder.py` | `Prompt.__new__()` 修改 `should_register` 默认值；`PromptManager` 保留 `format_prompt` API | 中 |
| B1 | `src/chat/replyer/prompt/replyer_prompt.py` | **删除** `init_replyer_prompt()`；用 `load_prompt("replyer_group", ...)` 替代 | 低 |
| B2 | `src/chat/replyer/prompt/replyer_private_prompt.py` | **删除** `init_replyer_private_prompt()` | 低 |
| B3 | `src/chat/replyer/prompt/lpmm_prompt.py` | **删除** `init_lpmm_prompt()` | 低 |
| B4 | `src/chat/replyer/prompt/rewrite_prompt.py` | **删除** `init_rewrite_prompt()`（chat_target_* 片段 inline） | 低 |
| B5 | `src/chat/replyer/group_generator.py` | 删除4个init调用；改用 `load_prompt("replyer_group")` 等 | 低 |
| B6 | `src/chat/replyer/private_generator.py` | 同上 | 低 |
| C1 | `src/chat/planner_actions/planner.py` | 删除 `init_prompt()`；`build_planner_prompt` 中 `get_prompt_async("planner_prompt")` → `load_prompt_template("planner_group")` | 中 |
| C2 | `src/chat/brain_chat/brain_planner.py` | 同上 | 中 |
| D1 | `src/chat/brain_chat/PFC/action_planner.py` | 删除3个 `PROMPT_*` 常量；改用 `load_prompt_template("pfc_action_initial_reply")` | 高 |
| D2 | `src/chat/brain_chat/PFC/reply_generator.py` | 删除3个 `PROMPT_*` 常量；改用 `load_prompt_template("pfc_reply_direct")` 等 | 高 |
| D3 | `src/chat/brain_chat/PFC/reply_checker.py` | 提取 inline f-string 为 `load_prompt("pfc_reply_check")` | 中 |
| D4 | `src/chat/brain_chat/PFC/pfc.py` | 提取 GoalAnalyzer 的2个 f-string prompt 到文件 | 高 |
| E1 | `src/chat/emoji_system/emoji_manager.py` | 提取5个 inline prompt 到文件 | 中 |
| F1 | `src/chat/knowledge/prompt_template.py` | 修改常量读取方式，保留 `build_*_context()` 函数签名 | 低 |
| G1 | `src/memory_system/memory_retrieval.py` | 删除 `init_memory_retrieval_prompt()` | 低 |
| G2 | `src/memory_system/chat_history_summarizer.py` | 删除 `init_prompt()` | 低 |
| H1 | `src/bw_learner/expression_learner.py` | 删除 `init_prompt()` | 低 |
| H2 | `src/bw_learner/expression_selector.py` | 删除 `init_prompt()` | 低 |
| H3 | `src/bw_learner/reflect_tracker.py` | 删除 `_init_prompts()` | 低 |
| H4 | `src/bw_learner/jargon_miner.py` | 删除 `_init_inference_prompts()` | 低 |
| H5 | `src/bw_learner/jargon_explainer.py` | 删除 `_init_explainer_prompts()` | 低 |
| H6 | `src/bw_learner/expression_auto_check_task.py` | 修改 `create_evaluation_prompt()` | 低 |
| I1 | `src/dream/dream_agent.py` | 删除 `init_dream_prompts()` | 低 |
| I2 | `src/dream/dream_generator.py` | 删除 `init_dream_summary_prompt()` | 低 |
| J1 | `src/person_info/person_info.py` | 将 `qv_name_prompt` 拼接改为 `load_prompt("person_nickname", ...)` | 中 |
| K1 | `src/plugin_system/core/tool_use.py` | 删除 `init_tool_executor_prompt()` inine | 低 |
| L1 | `src/llm_models/model_client/gemini_client.py` | 将 inline prompt 改为文件读取 | 低 |

### 4.2 具体变更示例

#### 示例 B5: `src/chat/replyer/group_generator.py`

**当前代码 (lines 35-44)**:
```python
from src.chat.replyer.prompt.lpmm_prompt import init_lpmm_prompt
from src.chat.replyer.prompt.replyer_prompt import init_replyer_prompt
from src.chat.replyer.prompt.rewrite_prompt import init_rewrite_prompt
from src.memory_system.memory_retrieval import init_memory_retrieval_prompt

init_lpmm_prompt()
init_replyer_prompt()
init_rewrite_prompt()
init_memory_retrieval_prompt()
```

**替换为**:
```python
# 删除所有 import + init 调用
# 在需要用到模板的地方使用：
# from src.common.prompt_i18n import load_prompt
# 或保持现有 global_prompt_manager.format_prompt()
# 
# 因为 format_prompt API 兼容，只需确保 prompt 名称匹配 .prompt 文件名
# prompt_builder 的 PromptManager 仍然持有这些 prompt（通过初始化时加载）
# 变更只影响注册方式
```

#### 示例 D1: `src/chat/brain_chat/PFC/action_planner.py`

**当前代码 (lines 17-50)**:
```python
PROMPT_INITIAL_REPLY = """{persona_text}。现在你在参与一场QQ私聊...
```
**替换为**:
```python
from src.common.prompt_i18n import load_prompt_template
# plan() 方法中使用：
prompt_template = load_prompt_template("pfc_action_initial_reply")
prompt = prompt_template.template.format(
    persona_text=persona_text,
    ...
)
# 注意：PROMPT_INITIAL_REPLY, PROMPT_FOLLOW_UP, PROMPT_END_DECISION 三个常量都移除
```

#### 示例 J1: `src/person_info/person_info.py`

**当前代码 (lines 707-728)**:
```python
qv_name_prompt = f"你是{bot_name}，一个伪装成人类的AI..."
qv_name_prompt += f"现在你想给一个用户取一个昵称..."
...
```
**替换为**:
```python
from src.common.prompt_i18n import load_prompt
qv_name_prompt = load_prompt("person_nickname",
    bot_name=bot_name,
    user_nickname=user_nickname,
    user_cardname=user_cardname,
    user_avatar_line=f"用户的qq头像是{user_avatar}，" if user_avatar else "",
    old_name_line=f"你之前叫他{old_name}，是因为{old_reason}，" if old_name else "",
    request=request,
    existing_names_block=...,
    known_nicknames_block=...,
)
```

---

## 5. 执行顺序

### 阶段 0：基础设施（1 步，无依赖）

```
Step 0.1: 创建 src/common/prompt_i18n.py 和 src/common/prompt_manager.py
          └── 验证：能加载 prompts/zh-CN/ 下文件
```

### 阶段 1：核心 chat 模块（依赖阶段 0）

```
Step 1.1: 创建所有 38 个 .prompt 文件到 prompts/zh-CN/
Step 1.2: 在 src/main.py 添加 prompt_manager.load_prompts()
Step 1.3: 迁移 replyer/prompt/ 4个文件 + group_generator/private_generator
          └── 测试：启动后 group reply 正常
Step 1.4: 迁移 planner_actions/planner.py + brain_chat/brain_planner.py
          └── 测试：group/private planner 正常
Step 1.5: 迁移 PFC/ 子系统 (action_planner, reply_generator, reply_checker, pfc)
          └── 测试：私聊对话完整流程
```

### 阶段 2：外围模块（依赖阶段 0-1）

```
Step 2.1: 迁移 memory_system/ (memory_retrieval, chat_history_summarizer)
Step 2.2: 迁移 bw_learner/ (expression_learner, selector, reflect_tracker, jargon_*)
Step 2.3: 迁移 dream/ (dream_agent, dream_generator)
Step 2.4: 迁移 emoji_system/emoji_manager.py
Step 2.5: 迁移 knowledge/prompt_template.py
```

### 阶段 3：轻量模块（独立）

```
Step 3.1: 迁移 person_info/person_info.py
Step 3.2: 迁移 plugin_system/core/tool_use.py
Step 3.3: 迁移 llm_models/model_client/gemini_client.py
Step 3.4: 迁移 expression_auto_check_task.py
```

### 阶段 4：清理（依赖所有前阶段）

```
Step 4.1: 删除 src/chat/replyer/prompt/ 目录
Step 4.2: 清理所有 init_*_prompt() 函数和调用
Step 4.3: 验证 lint 通过：ruff check --fix . && ruff format .
Step 4.4: 全面功能测试
```

---

## 6. 风险与回滚

### 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| PFC 子系统常量改为文件加载后格式错误 | 中 | 高 | 保留原常量文件作为 fallback，加 try/except |
| 双花括号 `{{` 转义错误导致 JSON 输出格式损坏 | 中 | 高 | 编写自动化测试检查每个 .prompt 文件格式完整性 |
| `prompt_i18n.py` 与现有 `prompt_builder.py` API 冲突 | 低 | 中 | 明确 API 边界；`prompt_i18n` 用于文件 I/O，`prompt_builder` 用于运行时格式化 |
| 文件编码或路径问题 | 低 | 中 | 统一使用 UTF-8；路径使用 `pathlib` |
| 热加载引入竞态条件 | 低 | 中 | 使用 RLock（上游已有） |
| `.prompt` 文件名与注册名不一致 | 中 | 高 | 命名规范表 + 启动时校验所有 prompt 是否加载成功 |

### 回滚策略

1. **不删除原有代码**：所有 `init_*_prompt()` 函数保留至少一个发布周期，仅在加载 `.prompt` 文件失败时继续使用旧的 `Prompt()` 注册
2. **git 分支**：在 `main` 或专用分支 `refactor/prompt-externalization` 上进行
3. **回滚命令**：
   ```bash
   git revert HEAD --no-commit  # 反转所有未提交的更改
   # 或
   git checkout -- prompts/  # 只删除 prompt 目录
   git checkout -- src/common/prompt_i18n.py src/common/prompt_manager.py
   ```
4. **快速回滚特定模块**：任何模块的 `.prompt` 文件加载失败时，保留一个 `if load_fails: use_old_inline_template()` 路径
5. **监控点**：所有 `load_prompt()` 调用包装在 try/except 中，失败使用硬编码 fallback 字符串

### 兼容性 Fallback 示例

```python
def safe_get_prompt(name: str, **kwargs) -> str:
    """安全加载 prompt，失败时使用旧模板"""
    try:
        from src.common.prompt_i18n import load_prompt
        return load_prompt(name, **kwargs)
    except (FileNotFoundError, KeyError, ValueError) as e:
        logger.warning(f"加载 prompt '{name}' 失败 ({e})，使用旧模板")
        # 旧模板 Registry 中的 prompt
        return global_prompt_manager.format_prompt(name, **kwargs)
```

---

## 附录 A：完整 `.prompt` 文件 → 模块映射表

| .prompt 文件名 | 源模块 | 源变量名 | 使用模式 | 迁移优先级 |
|---------------|--------|---------|---------|-----------|
| replyer_group | replyer/replyer_prompt.py | `replyer_prompt` | A (load_prompt) | P1 |
| replyer_private | replyer/replyer_private_prompt.py | `private_replyer_prompt` | A | P1 |
| replyer_private_self | replyer/replyer_private_prompt.py | `private_replyer_self_prompt` | A | P1 |
| lpmm_get_knowledge | replyer/lpmm_prompt.py | `lpmm_get_knowledge_prompt` | A | P1 |
| default_expressor | replyer/rewrite_prompt.py | `default_expressor_prompt` | A | P1 |
| planner_group | planner_actions/planner.py | `planner_prompt` | A | P1 |
| action_template | planner_actions/planner.py | `action_prompt` | A | P1 |
| brain_planner_react | brain_chat/brain_planner.py | `brain_planner_prompt_react` | A | P1 |
| brain_action_template | brain_chat/brain_planner.py | `brain_action_prompt` | A | P1 |
| pfc_action_decision | PFC/action_planner.py | `PROMPT_INITIAL_REPLY` + `FOLLOW_UP` + `END_DECISION` | A | P1 |
| pfc_reply_generation | PFC/reply_generator.py | `PROMPT_DIRECT_REPLY` + `SEND_NEW_MESSAGE` + `FAREWELL` | A | P1 |
| pfc_reply_check | PFC/reply_checker.py | inline f-string | A | P1 |
| pfc_goal_analyzer | PFC/pfc.py | inline f-string | A | P1 |
| pfc_goal_analyzer_assess | PFC/pfc.py | inline f-string | A | P1 |
| emoji_vlm_description | emoji_system/emoji_manager.py | inline (GIF + 静态图描述合并) | A | P2 |
| emoji_content_filter | emoji_system/emoji_manager.py | inline | A | P2 |
| emoji_emotion_analysis | emoji_system/emoji_manager.py | inline | A | P2 |
| emoji_replace_decision | emoji_system/emoji_manager.py | inline | A | P2 |
| entity_extract_system | knowledge/prompt_template.py | `entity_extract_system_prompt` | A+C | P2 |
| rdf_triple_extract_system | knowledge/prompt_template.py | `rdf_triple_extract_system_prompt` | A+C | P2 |
| qa_system | knowledge/prompt_template.py | `qa_system_prompt` | A+C | P2 |
| memory_retrieval | memory_system/memory_retrieval.py | `memory_retrieval_question_prompt` + `react_head` + `final` 合并 | A | P2 |
| hippo_topic_analysis | memory_system/chat_history_summarizer.py | `hippo_topic_analysis_prompt` | A | P2 |
| hippo_topic_summary | memory_system/chat_history_summarizer.py | `hippo_topic_summary_prompt` | A | P2 |
| learn_style | bw_learner/expression_learner.py | `learn_style_prompt` | A | P2 |
| expression_evaluation | bw_learner/expression_selector.py | `expression_evaluation_prompt` | A | P2 |
| expression_auto_check | bw_learner/expression_auto_check_task.py | inline f-string | A | P2 |
| reflect_judge | bw_learner/reflect_tracker.py | `reflect_judge_prompt` | A | P2 |
| jargon_inference_with_context | bw_learner/jargon_miner.py | `jargon_inference_with_context_prompt` | A | P2 |
| jargon_inference_content_only | bw_learner/jargon_miner.py | `jargon_inference_content_only_prompt` | A | P2 |
| jargon_compare_inference | bw_learner/jargon_miner.py | `jargon_compare_inference_prompt` | A | P2 |
| jargon_explainer_summarize | bw_learner/jargon_explainer.py | `jargon_explainer_summarize_prompt` | A | P2 |
| dream_react_head | dream/dream_agent.py | `dream_react_head_prompt` | A | P2 |
| dream_summary | dream/dream_generator.py | `dream_summary_prompt` | A | P2 |
| person_nickname | person_info/person_info.py | inline concatenated | A | P3 |
| tool_executor | plugin_system/core/tool_use.py | `tool_executor_prompt` | A | P3 |
| audio_transcription | llm_models/gemini_client.py | inline | A | P3 |

**使用模式说明**：
- `A` = 使用 `load_prompt("name", **kwargs)` 或 `global_prompt_manager.format_prompt("name", ...)` 消费
- `B` = 使用 `prompt_manager.get_prompt()` + `add_context()` + `render_prompt()` 消费
- `C` = 同时作为常量引用（`from module import CONST`）

---

## 附录 B：工作量评估

| 阶段 | 文件数 | 预估时间 | 可并行 |
|------|--------|---------|-------|
| 阶段 0：infrastructure | 2 个 Python 文件 | 1 小时 | 否 |
| 阶段 1-1：30 个 .prompt 文件 | 30 个文本文件 | 1.5 小时 | 是 |
| 阶段 1-2~1-3：replyer + planner + main.py | 6 个 Python 文件 | 1.5 小时 | 部分 |
| 阶段 1-4：PFC 子系统 | 4 个 Python 文件 | 2 小时 | 否 |
| 阶段 2：外围模块 | 10+ 个 Python 文件 | 2 小时 | 是 |
| 阶段 3：轻量模块 | 4 个 Python 文件 | 0.5 小时 | 是 |
| 阶段 4：清理验证 | 2 步 | 0.5 小时 | 否 |
| **总计** | **~52 个文件** | **~8.5 小时** | |

**关键路径**：阶段 0 → 阶段 1 (replyer+planner) → 阶段 1 (PFC) → 阶段 2/3/4
