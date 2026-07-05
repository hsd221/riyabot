# 消息链路 Hook 点第 5 步

## 目标

在不替换插件系统的前提下，给入站、命令、规划、发送补齐稳定 hook 点，方便后续插件或本地逻辑观察、拦截和改写消息链路。

这一阶段继续使用本地 `src/plugin_system`，不引入上游 `plugin_runtime` 子进程架构。

## 当前已有能力

本地已有事件系统：

- `src/plugin_system/core/events_manager.py`
- `src/plugin_system/base/component_types.py`

当前主要事件包括：

- `ON_MESSAGE_PRE_PROCESS`
- `ON_MESSAGE`
- `ON_PLAN`
- `POST_SEND_PRE_PROCESS`
- `POST_SEND`
- `AFTER_SEND`

问题是部分关键点语义不够细，命令执行前后、入站 process 前后、发送构建后等场景没有稳定专用入口。

## 建议新增 Hook 点

### 1. 入站 process 前

位置：`src/chat/message_receive/bot.py`

建议名称：

```text
ON_MESSAGE_BEFORE_PROCESS
```

触发时机：

```text
MessageRecv 创建后，message.process() 前。
```

用途：

- 丢弃某些平台消息。
- 修改 raw segment。
- 注入 additional_config。

### 2. 入站 process 后

建议名称：

```text
ON_MESSAGE_AFTER_PROCESS
```

触发时机：

```text
message.process() 后，过滤词和命令处理前。
```

用途：

- 修改 `processed_plain_text`。
- 针对轻量媒体占位做替换。
- 追加标记。

### 3. 命令执行前

建议名称：

```text
ON_COMMAND_BEFORE_EXECUTE
```

触发时机：

```text
命令匹配成功后，BaseCommand.execute() 前。
```

携带信息：

- message
- command_name
- plugin_name
- matched_groups

用途：

- 禁用特定命令。
- 改写命令参数。
- 做权限判断。

### 4. 命令执行后

建议名称：

```text
ON_COMMAND_AFTER_EXECUTE
```

触发时机：

```text
命令 execute() 完成后，决定是否继续主链前。
```

携带信息：

- success
- response
- intercept_message_level
- continue_process

用途：

- 记录命令审计。
- 修改是否继续主消息链。
- 修改响应文本。

### 5. 发送消息构建后

建议名称：

```text
ON_SEND_AFTER_BUILD_MESSAGE
```

触发时机：

```text
send_service 构建 MessageSending 后，真正发送前。
```

用途：

- 改写消息段。
- 注入 selected_expressions。
- 取消发送。

## 实现建议

第一阶段可以继续复用 `events_manager.handle_mai_events(...)`。

需要改：

- `src/plugin_system/base/component_types.py` 增加事件枚举。
- `src/plugin_system/core/events_manager.py` 确认可注册和分发。
- `src/chat/message_receive/bot.py` 增加入站/命令 hook 调用。
- `src/services/send_service.py` 或当前 `UniversalMessageSender` 增加发送构建后 hook。

## 风险点

- hook 修改消息时要明确哪些字段允许改。
- 命令 hook 不应吞异常导致主链崩溃。
- 发送 hook 取消发送时要有清晰日志。
- 不要让非拦截型 hook 阻塞主链。

## 验证点

- 插件能在入站 process 前取消消息。
- 插件能在 process 后修改纯文本。
- 插件能在命令执行前阻止命令。
- 插件能在命令执行后修改 continue_process。
- 插件能在发送前改写文本或取消发送。
