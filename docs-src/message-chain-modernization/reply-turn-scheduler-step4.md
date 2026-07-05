# 回复触发调度器第 4 步

## 目标

把“什么时候进入一轮思考/回复”的判断从 `HeartFChatting._loopbody()` 和 `BrainChatting._loopbody()` 中抽出来，形成一个独立调度器。

第一阶段不改 planner，不改 action，只改触发判断的组织方式。

## 当前问题

群聊逻辑主要在：

- `src/chat/heart_flow/heartFC_chat.py`

私聊逻辑主要在：

- `src/chat/brain_chat/brain_chat.py`

两边现在各自处理：

- 最近消息查询。
- 是否有 @ 或提及。
- 回复频率。
- wait / complete_talk。
- 连续 no_reply。
- 睡眠间隔。

这些规则散在循环体里，导致群聊和私聊行为难以对齐，也不方便后续加入“回复必要性评分”或“低频空窗补偿”。

## 建议落点

新增：

- `src/chat/heart_flow/turn_scheduler.py`

或者更通用一点：

- `src/chat/message_receive/turn_scheduler.py`

建议第一阶段放在 `heart_flow` 下，减少跨模块影响。

## 建议模型

定义调度结果：

```python
class TurnDecision:
    should_observe: bool
    force_reply_message: object | None
    sleep_seconds: float
    reason: str
```

定义调度器：

```python
class ReplyTurnScheduler:
    def decide_group_turn(
        self,
        *,
        stream_id: str,
        recent_messages: list,
        consecutive_no_reply_count: int,
    ) -> TurnDecision:
        ...

    def decide_private_turn(
        self,
        *,
        stream_id: str,
        recent_messages: list,
        waiting_after_complete: bool,
    ) -> TurnDecision:
        ...
```

第一阶段可以只搬判断，不改变行为。

## 群聊迁移点

从 `HeartFChatting._loopbody()` 中抽出：

- 最近消息数量阈值。
- 连续 no_reply 后提高阈值。
- @ 或提及时强制回复。
- `talk_value * frequency_adjust` 概率触发。
- 没触发时 sleep。

抽出后 `_loopbody()` 只保留：

```python
recent_messages = ...
decision = scheduler.decide_group_turn(...)
if not decision.should_observe:
    await asyncio.sleep(decision.sleep_seconds)
    return True
await self._observe(
    recent_messages_list=recent_messages,
    force_reply_message=decision.force_reply_message,
)
return True
```

## 私聊迁移点

从 `BrainChatting._loopbody()` 中抽出：

- 是否有新消息。
- 是否打断 wait。
- 是否继续思考。
- complete_talk 后等待新消息。

私聊第一阶段可以只做薄封装，避免破坏现有状态机。

## 后续可加入的能力

第二阶段再考虑：

- 回复必要性评分。
- 低活跃群聊的空窗补偿。
- 静默接收模式。
- planner 运行中收到新消息时的打断。
- 每个聊天流独立调度状态。

## 风险点

- 第一阶段不要改变概率公式。
- 不要改变 `last_read_time` 更新时机。
- 不要改变 `complete_talk` 的等待行为。
- 群聊和私聊要分别验证。

## 验证点

- 群聊普通消息仍按原概率触发。
- @ 或提及仍能强制回复。
- 连续 no_reply 后阈值变化保持一致。
- 私聊 complete_talk 后仍等待新消息。
- 没消息时 CPU 占用不升高。
