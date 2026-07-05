# 入站媒体后台识别第 2 步

## 目标

在第 1 步轻量入站之后，补上后台媒体识别能力：入站阶段仍然快速返回 `[图片]`、`[表情包]`、`[语音消息]`，后台再处理图片描述、表情描述和语音转写。

这一阶段的重点是缓存和回填，不改变主聊天循环架构。

## 前置条件

已完成 `inbound-lightweight-step1.md`：

- `MessageRecv.process()` 支持轻量模式参数。
- 主入站链路默认不等待 VLM 或 ASR。
- 图片/表情/语音在轻量模式下能返回占位文本。

## 建议落点

主要涉及：

- `src/chat/message_receive/message.py`
- `src/chat/message_receive/bot.py`
- `src/chat/utils/utils_image.py`
- `src/chat/emoji_system/emoji_manager.py`
- `src/common/database/database_model.py`
- `src/chat/message_receive/storage.py`

如果第一阶段暂时不想改数据库，可以先只做内存缓存和现有图片表复用。

## 建议设计

### 1. 轻量处理时调度后台任务

图片分支轻量返回占位前，记录必要信息并调度后台任务：

```python
if not enable_heavy_media_analysis:
    self.has_picid = True
    self.is_picid = True
    schedule_image_description_task(segment.data, self.message_info.message_id)
    return "[图片]"
```

表情包和语音同理：

```python
schedule_emoji_description_task(segment.data, self.message_info.message_id)
schedule_voice_transcription_task(segment.data, self.message_info.message_id)
```

后台任务必须 fire-and-forget，不允许影响入站链路。

### 2. 任务去重

图片和表情包应按 hash 去重：

```text
media_hash -> processing / done / failed
```

如果同一张图正在识别，后续消息只复用同一个任务，不重复调用 VLM。

### 3. 结果缓存

建议先做三层读取顺序：

1. 内存缓存：最快，进程内可用。
2. 现有数据库图片/表情记录：重启后可复用。
3. 没有命中时保留占位。

不建议第二步就新增复杂迁移。如果必须新增字段，先单独写迁移文档。

### 4. prompt 构建时补描述

第一阶段入库的 `processed_plain_text` 可能只有 `[图片]`。后台识别完成后，prompt 构建可以在读取消息时做二次增强：

```text
[图片] -> [图片：识别出的描述]
[表情包] -> [表情包：识别出的描述]
[语音消息] -> [语音：转写文本]
```

优先在消息上下文构建层做这个增强，而不是直接依赖入站时必须写回原消息文本。

本地相关位置：

- `src/chat/utils/chat_message_builder.py`
- `src/plugin_system/apis/message_api.py`

## 风险点

- 后台任务异常不能污染主消息链路。
- 同一消息里多张图时要限制并发。
- 图片 base64 很大时不要长期放在内存里。
- 识别结果写库时要避免覆盖用户真实文本。
- 语音转写失败应保留 `[语音消息]`，不要返回空字符串。

## 验证点

- 连续发送多张图片，入站日志能快速出现。
- VLM 慢或失败时主链路不受影响。
- 同一张图重复发送时不会重复识别。
- prompt 上下文能在识别完成后显示更完整描述。
- 重启后已识别的图片/表情能复用缓存。
