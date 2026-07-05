# 统一发送服务第 3 步

## 目标

把出站发送相关逻辑从 `send_api` 和 `UniversalMessageSender` 中收敛到一个服务层，形成单一入口：

```text
调用方 -> send_service -> UniversalMessageSender/maim_message/WebUI fallback -> 写库/事件/日志
```

第一阶段不需要完整引入上游 `PlatformIOManager`，只先把本地发送边界理清。

## 当前问题

本地发送链路分散在：

- `src/plugin_system/apis/send_api.py`
- `src/chat/message_receive/uni_message_sender.py`
- `src/chat/message_receive/storage.py`
- `src/webui/chat_routes.py`

现在 `_send_to_target()` 同时负责：

- 找聊天流。
- 构造机器人消息。
- 处理引用回复。
- 创建 `UniversalMessageSender`。
- 调用发送。
- 返回 bool。

`UniversalMessageSender.send_message()` 又负责：

- 发送前事件。
- `message.process()`。
- typing 等待。
- 实际发送。
- 发送后事件。
- 写库。

边界不清时，后续改消息 ID 回填、WebUI 虚拟群、多平台发送、发送后同步历史都会变得难维护。

## 建议落点

新增：

- `src/services/send_service.py`

保留兼容：

- `src/plugin_system/apis/send_api.py` 继续作为插件 API 外观。
- 内部调用逐步转发到 `send_service`。

## 建议接口

先提供最小接口：

```python
async def text_to_stream(
    text: str,
    stream_id: str,
    *,
    typing: bool = False,
    set_reply: bool = False,
    reply_message=None,
    storage_message: bool = True,
    selected_expressions: list[int] | None = None,
) -> bool:
    ...
```

再提供能返回最终消息对象的内部接口：

```python
async def text_to_stream_with_message(...) -> MessageSending | None:
    ...
```

这样后续 replyer 想同步历史或拿平台 message_id 时，不必再解析日志或重新查库。

## 拆分职责

`send_service` 负责：

- 根据 `stream_id` 找目标聊天流。
- 构造 `MessageSending`。
- 补引用回复。
- 调用发送前 hook。
- 调用 `UniversalMessageSender` 或当前底层发送器。
- 发送成功后写库。
- 调用发送后 hook。
- 返回 bool 或发送后的消息对象。

`send_api` 负责：

- 保持插件侧 API 不变。
- 参数转换。
- 调用 `send_service`。

`UniversalMessageSender` 后续应逐步变薄：

- 只负责把 `MessageSending` 发到当前 maim_message/WebUI。
- 不再负责业务级构造和编排。

## 迁移顺序

1. 新增 `src/services/send_service.py`，复制当前 `_send_to_target()` 的核心逻辑。
2. 让 `send_api.text_to_stream()` 先转发到 `send_service.text_to_stream()`。
3. 保留旧 `send_api` 其他函数，逐个迁移 emoji/image/custom。
4. 验证插件和 replyer 发送不变。
5. 再考虑把 `UniversalMessageSender.send_message()` 中的事件和写库上移。

## 风险点

- 不要一次性删除旧 `send_api`，插件依赖它。
- 引用回复的 `reply_message` 类型目前是数据库消息，要保留兼容。
- WebUI 虚拟群逻辑不能丢。
- 发送成功后写库只能写一次，避免重复记录。

## 验证点

- 普通文本发送成功。
- 引用回复发送成功。
- 表情、图片、自定义消息发送成功。
- WebUI 虚拟群发送成功。
- 发送前、发送后插件事件仍能触发。
- 数据库消息记录没有重复。
