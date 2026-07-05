# 内部消息组件化第 6 步

## 目标

逐步把内部消息内容从到处传 `maim_message.Seg`，过渡到更稳定的组件模型。

第一阶段不要求替换所有消息类，只先建立本地内部组件类型和转换函数，减少 `if segment.type == ...` 分散在各处。

## 当前问题

本地大量逻辑直接判断：

```python
if segment.type == "text":
    ...
elif segment.type == "image":
    ...
elif segment.type == "emoji":
    ...
```

这些判断分布在：

- `src/chat/message_receive/message.py`
- `src/chat/message_receive/uni_message_sender.py`
- `src/plugin_system/apis/send_api.py`
- WebUI 聊天相关代码

后续要支持文件、回复、at、合并转发、多图、图片描述回填时，重复分支会越来越多。

## 建议新增模型

新增：

- `src/common/data_models/message_component_model.py`

先定义最小组件：

```python
class TextComponent:
    text: str

class ImageComponent:
    base64_data: str | None
    image_hash: str | None
    description: str | None

class EmojiComponent:
    base64_data: str | None
    emoji_hash: str | None
    description: str | None

class VoiceComponent:
    base64_data: str | None
    voice_hash: str | None
    transcript: str | None

class AtComponent:
    target_user_id: str
    target_name: str | None

class ReplyComponent:
    target_message_id: str
    target_text: str | None

class FileComponent:
    name: str
    size: str | None
    url: str | None
```

再定义容器：

```python
class MessageComponentSequence:
    components: list[MessageComponent]
```

## 转换函数

第一阶段重点是转换，不强迫所有调用方立刻换模型：

```python
def from_seg_to_components(seg: Seg) -> MessageComponentSequence:
    ...

async def from_components_to_seg(seq: MessageComponentSequence) -> Seg:
    ...

def components_to_plain_text(seq: MessageComponentSequence) -> str:
    ...
```

## 迁移顺序

1. 新增组件模型和转换函数。
2. `MessageRecv.process()` 内部先把 `Seg` 转成组件，再生成纯文本。
3. `send_service` 构造发送消息时优先使用组件，再转回 `Seg` 发送。
4. WebUI 展示层逐步用组件信息生成富文本。
5. 最后再考虑让数据库保存组件序列。

## 不建议第一阶段做的事

- 不要立刻替换 `MessageRecv` 构造函数。
- 不要立刻改数据库 raw_content 格式。
- 不要立刻改所有插件 API。
- 不要直接照搬上游 `SessionMessage` 全套模型。

## 收益

- 图片/表情/语音描述回填更自然。
- 引用回复能保存目标消息预览。
- 发送和接收共用同一套内容表达。
- WebUI 富文本展示更容易。
- 后续迁移到新版 `SessionMessage` 成本更低。

## 风险点

- `Seg` 和组件之间要保证可逆。
- 未知类型必须保留原始 payload，不能丢消息。
- 合并转发要保留层级，不要只拼纯文本。
- 插件侧仍可能依赖旧 `Seg`。

## 验证点

- 文本、图片、表情、语音、at、reply、file 都能从 `Seg` 转组件。
- 组件能再转回 `Seg` 并发送。
- 未知消息类型不会丢失。
- 旧插件 API 行为不变。
