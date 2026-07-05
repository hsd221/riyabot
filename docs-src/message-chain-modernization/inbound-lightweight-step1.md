# 入站消息轻量化第 1 步

## 目标

让图片、表情包、语音消息在进入主消息链路时不等待 VLM 或 ASR 这类耗时处理，先快速进入聊天流和存储链路。

第一步只做轻量模式开关，不做后台识别回填、不改数据库结构、不重写消息模型。

## 当前问题

本地入站链路在 `src/chat/message_receive/bot.py` 中调用：

```python
await message.process()
```

`MessageRecv.process()` 会进入 `src/chat/message_receive/message.py`，其中图片、表情包、语音分支会同步等待：

- `image_manager.process_image(...)`
- `get_image_manager().get_emoji_description(...)`
- `get_voice_text(...)`

这些调用慢时，会堵住整个入站消息处理。

## 建议改动

给 `MessageRecv.process()` 增加两个参数：

```python
async def process(
    self,
    *,
    enable_heavy_media_analysis: bool = True,
    enable_voice_transcription: bool = True,
) -> None:
```

参数继续传给 `_process_message_segments()` 和 `_process_single_segment()`。

然后在 `src/chat/message_receive/bot.py` 的主入站链路中改成：

```python
await message.process(
    enable_heavy_media_analysis=False,
    enable_voice_transcription=False,
)
```

## 第一阶段分支行为

图片：

```python
elif segment.type == "image":
    self.has_picid = True
    self.is_picid = True
    self.is_emoji = False
    if not enable_heavy_media_analysis:
        return "[图片]"
    # 保留原来的 image_manager.process_image 逻辑
```

表情包：

```python
elif segment.type == "emoji":
    self.has_emoji = True
    self.is_emoji = True
    self.is_picid = False
    self.is_voice = False
    if not enable_heavy_media_analysis:
        return "[表情包]"
    # 保留原来的 get_emoji_description 逻辑
```

语音：

```python
elif segment.type == "voice":
    self.is_picid = False
    self.is_emoji = False
    self.is_voice = True
    if not enable_voice_transcription:
        return "[语音消息]"
    # 保留原来的 get_voice_text 逻辑
```

## 验证点

发送图片、表情包、语音后确认：

- 入站处理不会等待 VLM 或 ASR。
- 日志里能快速出现 `[图片]`、`[表情包]`、`[语音消息]`。
- 文本消息行为不变。
- 命令处理、消息存储、心流启动不受影响。

## 后续再做

第二步再考虑后台识别和回填：

- 按图片 hash 缓存描述。
- 后台任务识别完成后更新图片/表情描述。
- prompt 构建时优先读取已完成描述，没有则保留占位。

后续文档：

- `README.md`
- `inbound-media-background-step2.md`
- `send-service-step3.md`
- `reply-turn-scheduler-step4.md`
- `message-hooks-step5.md`
- `message-components-step6.md`
