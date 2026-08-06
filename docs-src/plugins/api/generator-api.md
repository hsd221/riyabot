# 回复生成器API

回复生成器 API 让插件调用系统的 Replyer，生成符合当前聊天上下文的回复内容。它负责生成和处理回复，不负责注册插件组件。

## 先确认 Tool 与 Action 的边界

新插件需要让模型按结构化参数调用能力时，应继承 `BaseTool` 并通过插件组件注册。Tool 的定义和执行由聊天层的统一 Tool Call 管线处理，详见 [Tool 组件](../tool-components.md) 和 [工具 API](tool-api.md)。

`BaseAction` 仍作为兼容组件保留。聊天层会把满足激活条件的 Action 转换为 Tool schema，再交给 `ActionManager` 创建并执行；这不等于 `BaseAction` 已经变成 `BaseTool`。Action 的迁移说明见 [Action 组件（兼容层）](../action-components.md)。

本页的 `generate_reply()` 是 Replyer 调用接口。它不是注册 Tool 或执行 Action 的入口；`enable_tool` 只控制本次 Replyer 生成中的工具处理开关。

## 导入方式

```python
from src.plugin_system.apis import generator_api
# 或者
from src.plugin_system import generator_api
```

## 主要功能

### 1. 回复器获取
```python
def get_replyer(
    chat_stream: Optional[ChatStream] = None,
    chat_id: Optional[str] = None,
    request_type: str = "replyer",
) -> Optional[DefaultReplyer | PrivateReplyer]:
```
获取回复器对象。

优先使用chat_stream，如果没有则使用chat_id直接查找。使用 ReplyerManager 来管理实例，避免重复创建。

**Args:**
- `chat_stream`: 聊天流对象
- `chat_id`: 聊天ID（实际上就是`stream_id`）
- `request_type`: 请求类型，用于记录LLM使用情况，可以不写

**Returns:**
- `Optional[DefaultReplyer | PrivateReplyer]`: 回复器对象（群聊为 `DefaultReplyer`，私聊为 `PrivateReplyer`），获取失败则返回 `None`

> `chat_stream` 与 `chat_id` 不能同时为空，否则抛出 `ValueError`。

#### 示例
```python
# 使用聊天流获取回复器
replyer = generator_api.get_replyer(chat_stream=chat_stream)

# 使用 chat_id 获取回复器
replyer = generator_api.get_replyer(chat_id="123456789")
```

### 2. 回复生成
```python
async def generate_reply(
    chat_stream: Optional[ChatStream] = None,
    chat_id: Optional[str] = None,
    action_data: Optional[Dict[str, Any]] = None,
    reply_message: Optional["DatabaseMessages"] = None,
    think_level: int = 1,
    extra_info: str = "",
    reply_reason: str = "",
    available_actions: Optional[Dict[str, ActionInfo]] = None,
    chosen_actions: Optional[List["ActionPlannerInfo"]] = None,
    unknown_words: Optional[List[str]] = None,
    enable_tool: bool = False,
    enable_splitter: bool = True,
    enable_chinese_typo: bool = True,
    request_type: str = "generator_api",
    from_plugin: bool = True,
    reply_time_point: Optional[float] = None,
) -> Tuple[bool, Optional["LLMGenerationDataModel"]]:
```
生成回复。

优先使用chat_stream，如果没有则使用chat_id直接查找。

**Args:**
- `chat_stream`: 聊天流对象
- `chat_id`: 聊天ID（实际上就是`stream_id`）
- `action_data`: 旧回复流程的兼容上下文。若对应参数没有显式传入，会从中读取 `extra_info`、`reason` 和 `unknown_words`；它不会注册或执行 Tool/Action
- `reply_message`: 被回复的消息对象（`DatabaseMessages`）
- `think_level`: 思考等级
- `extra_info`: 附加信息，用于补充上下文
- `reply_reason`: 回复原因
- `available_actions`: 旧回复流程使用的可用 Action 信息，格式为 `{"action_name": ActionInfo}`；不是 `BaseTool` 的注册入口
- `chosen_actions`: 旧 Planner 传给 Replyer 的已选 Action 记录
- `unknown_words`: 未知词语列表，用于黑话检索
- `enable_tool`: 是否启用本次 Replyer 生成中的工具处理；不会注册插件 Tool
- `enable_splitter`: 是否启用消息分割器
- `enable_chinese_typo`: 是否启用中文错别字
- `request_type`: 请求类型（可选，记录LLM使用）
- `from_plugin`: 是否来自插件
- `reply_time_point`: 回复时间点

**Returns:**
- `Tuple[bool, Optional[LLMGenerationDataModel]]`: (是否成功, 生成结果对象)

生成结果 `LLMGenerationDataModel` 中，`content` 为原始文本，`processed_output` 为分割处理后的文本列表，`reply_set` 为可直接发送的 `ReplySetModel`。

#### 示例
```python
success, llm_response = await generator_api.generate_reply(
    chat_stream=chat_stream,
    reply_message=source_message,
    extra_info="补充给 Replyer 的上下文",
    reply_reason="需要回应当前消息",
)
if success and llm_response:
    print(f"生成内容: {llm_response.content}")
    if llm_response.reply_set:
        # 可配合 send_api.custom_reply_set_to_stream 发送
        ...
```

### 3. 回复重写
```python
async def rewrite_reply(
    chat_stream: Optional[ChatStream] = None,
    reply_data: Optional[Dict[str, Any]] = None,
    chat_id: Optional[str] = None,
    enable_splitter: bool = True,
    enable_chinese_typo: bool = True,
    raw_reply: str = "",
    reason: str = "",
    reply_to: str = "",
    request_type: str = "generator_api",
) -> Tuple[bool, Optional["LLMGenerationDataModel"]]:
```
重写回复，使用新的内容替换旧的回复内容。

优先使用chat_stream，如果没有则使用chat_id直接查找。

**Args:**
- `chat_stream`: 聊天流对象
- `reply_data`: 回复数据，包含 `raw_reply`、`reason` 和 `reply_to`（向下兼容备用，当其他参数缺失时从此获取）
- `chat_id`: 聊天ID（实际上就是`stream_id`）
- `enable_splitter`: 是否启用消息分割器
- `enable_chinese_typo`: 是否启用中文错别字
- `raw_reply`: 原始回复内容
- `reason`: 重写原因
- `reply_to`: 回复对象
- `request_type`: 请求类型

**Returns:**
- `Tuple[bool, Optional[LLMGenerationDataModel]]`: (是否成功, 生成结果对象)

#### 示例
```python
success, llm_response = await generator_api.rewrite_reply(
    chat_stream=chat_stream,
    raw_reply="原始回复内容",
    reason="重写原因",
)
if success and llm_response:
    print(f"重写结果: {llm_response.content}")
```

### 4. 自定义提示词回复
```python
async def generate_response_custom(
    chat_stream: Optional[ChatStream] = None,
    chat_id: Optional[str] = None,
    request_type: str = "generator_api",
    prompt: str = "",
) -> Optional[str]:
```
生成自定义提示词回复。

优先使用chat_stream，如果没有则使用chat_id直接查找。

**Args:**
- `chat_stream`: 聊天流对象
- `chat_id`: 聊天ID（备用）
- `request_type`: 请求类型
- `prompt`: 自定义提示词

**Returns:**
- `Optional[str]`: 生成的自定义回复内容，如果生成失败则返回None

## 注意事项

1. **异步操作**：除 `get_replyer` 外的函数都是异步的，须使用`await`
2. **聊天流依赖**：需要有效的聊天流对象或 `chat_id` 才能正常工作
3. **性能考虑**：回复生成可能需要一些时间，特别是使用LLM时
4. **上下文感知**：生成器会考虑聊天上下文和历史消息，除非你用的是自定义提示词
