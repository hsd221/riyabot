from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from src.chat.chat_tool_registry import (
    ChatToolRegistry,
    MAX_TOOL_CALLS_PER_ROUND,
    REPLY_TOOL_NAME,
    ToolExecutionResult,
    ToolSource,
    append_bounded_tool_result,
    has_tool_result_capacity,
)
from src.chat.logger.plan_reply_logger import PlanReplyLogger
from src.chat.message_receive.chat_stream import get_chat_manager
from src.chat.utils.chat_message_builder import build_readable_messages_with_id, get_raw_msg_before_timestamp_with_chat
from src.chat.utils.structured_prompt import split_chat_prompt
from src.chat.utils.utils import get_chat_type_and_target_info
from src.common.logger import get_logger
from src.common.prompt_manager import prompt_manager
from src.config.config import global_config, model_config
from src.llm_models.payload_content import ToolCall
from src.llm_models.utils_model import LLMRequest
from src.plugin_system.base.component_types import EventType
from src.plugin_system.core.events_manager import events_manager

if TYPE_CHECKING:
    from src.chat.planner_actions.action_manager import ActionManager
    from src.common.data_models.database_data_model import DatabaseMessages


logger = get_logger("planner")


@dataclass(slots=True)
class PlannerDecision:
    prompt: str
    content: str
    reasoning: str
    model_name: str
    tool_calls: list[ToolCall]
    messages_by_id: dict[str, "DatabaseMessages"]
    started_at: float
    duration_ms: float | None = None
    tool_results: list[ToolExecutionResult] = field(default_factory=list)


@dataclass(slots=True)
class PrivateTurnResult:
    should_continue: bool = False
    reply_sent: bool = False
    reply_text: str = ""
    loop_info: dict[str, Any] | None = None
    decisions: list[PlannerDecision] = field(default_factory=list)
    tool_results: list[ToolExecutionResult] = field(default_factory=list)


class PrivateToolPlanner:
    """用原生工具调用决定私聊本轮是否执行工具或回复。"""

    def __init__(
        self,
        chat_id: str,
        tool_registry: ChatToolRegistry,
        action_manager: ActionManager,
    ):
        self.chat_id = chat_id
        self.log_prefix = f"[{get_chat_manager().get_stream_name(chat_id) or chat_id}]"
        self.tool_registry = tool_registry
        self.action_manager = action_manager
        self.planner_llm = LLMRequest(model_set=model_config.model_task_config.planner, request_type="planner")
        self.last_obs_time_mark = 0.0

    def _load_context(
        self,
        context_end_time: float | None = None,
    ) -> tuple[str, dict[str, "DatabaseMessages"], str, float]:
        snapshot_at = context_end_time if context_end_time is not None else time.time()
        messages = get_raw_msg_before_timestamp_with_chat(
            chat_id=self.chat_id,
            timestamp=snapshot_at,
            limit=int(global_config.chat.max_context_size * 0.6),
            filter_intercept_message_level=1,
        )
        chat_content, message_id_list = build_readable_messages_with_id(
            messages=messages,
            timestamp_mode="normal_no_YMD",
            read_mark=self.last_obs_time_mark,
            truncate=True,
            show_actions=True,
        )
        _, chat_target_info = get_chat_type_and_target_info(self.chat_id)
        chat_target = "对方"
        if chat_target_info:
            chat_target = chat_target_info.person_name or chat_target_info.user_nickname or chat_target
        return chat_content, dict(message_id_list), chat_target, snapshot_at

    def _build_prompt(
        self,
        *,
        chat_content: str,
        chat_target: str,
        tool_results: list[ToolExecutionResult],
    ) -> str:
        tool_results_block = "无，本轮尚未执行工具。"
        if tool_results:
            tool_results_block = json.dumps(
                [result.to_prompt_data() for result in tool_results],
                ensure_ascii=False,
                indent=2,
            )

        bot_name = global_config.bot.nickname
        bot_aliases = f"，也可以叫你{','.join(global_config.bot.alias_names)}" if global_config.bot.alias_names else ""
        return prompt_manager.format_prompt(
            "chat.private.planner",
            time_block=f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            name_block=f"你的名字是{bot_name}{bot_aliases}，请注意哪些是你自己的发言。",
            chat_target=chat_target,
            chat_content=chat_content,
            tool_results_block=tool_results_block,
            moderation_prompt=prompt_manager.format_prompt("shared.moderation.standard"),
        )

    async def plan(
        self,
        *,
        tool_results: list[ToolExecutionResult] | None = None,
        loop_start_time: float = 0.0,
        context_end_time: float | None = None,
        refresh_actions: bool = True,
    ) -> PlannerDecision:
        tool_results = tool_results or []
        chat_content, messages_by_id, chat_target, started_at = self._load_context(context_end_time=context_end_time)
        prompt = self._build_prompt(
            chat_content=chat_content,
            chat_target=chat_target,
            tool_results=tool_results,
        )

        continue_flag, modified_message = await events_manager.handle_mai_events(
            EventType.ON_PLAN,
            None,
            prompt,
            None,
            self.chat_id,
        )
        if not continue_flag:
            return PlannerDecision(
                prompt=prompt,
                content="规划 hook 取消本轮规划",
                reasoning="",
                model_name="",
                tool_calls=[],
                messages_by_id=messages_by_id,
                started_at=started_at,
                tool_results=list(tool_results),
            )
        if modified_message and modified_message._modify_flags.modify_llm_prompt:
            prompt = str(modified_message.llm_prompt)

        if refresh_actions:
            if self.action_manager is None:
                self.tool_registry.set_available_actions({})
            else:
                self.action_manager.restore_actions()
                self.tool_registry.refresh_available_actions(
                    self.action_manager.get_using_actions(),
                    chat_content=chat_content,
                )
        tool_definitions = self.tool_registry.get_tool_definitions()
        try:
            llm_started_at = time.perf_counter()
            request_kwargs = split_chat_prompt(prompt).as_request_kwargs()
            content, (reasoning, model_name, tool_calls) = await self.planner_llm.generate_response_async(
                **request_kwargs,
                tools=tool_definitions,
                raise_when_empty=False,
            )
            duration_ms = (time.perf_counter() - llm_started_at) * 1000
        except Exception as exc:
            logger.error(f"{self.log_prefix} 原生工具 Planner 调用失败: {exc}")
            return PlannerDecision(
                prompt=prompt,
                content=f"Planner 调用失败: {exc}",
                reasoning="",
                model_name="",
                tool_calls=[],
                messages_by_id=messages_by_id,
                started_at=started_at,
                tool_results=list(tool_results),
            )

        all_calls = list(tool_calls or [])
        normalized_calls = all_calls[:MAX_TOOL_CALLS_PER_ROUND]
        if len(all_calls) > MAX_TOOL_CALLS_PER_ROUND:
            logger.warning(
                f"{self.log_prefix} Planner 单轮返回 {len(all_calls)} 个 Tool Call，"
                f"仅处理前 {MAX_TOOL_CALLS_PER_ROUND} 个"
            )
        self.last_obs_time_mark = time.time()
        logger.info(
            f"{self.log_prefix} Planner 选择工具: "
            f"{', '.join(call.func_name for call in normalized_calls) if normalized_calls else '无（结束本轮）'}"
        )
        try:
            PlanReplyLogger.log_plan(
                chat_id=self.chat_id,
                prompt=prompt,
                reasoning=reasoning or content,
                raw_output=content,
                raw_reasoning=reasoning,
                actions=[],
                timing={
                    "llm_duration_ms": round(duration_ms, 2),
                    "loop_start_time": loop_start_time,
                },
                extra={
                    "tool_calls": [
                        {
                            "call_id": call.call_id,
                            "name": call.func_name,
                            "arguments": call.args or {},
                        }
                        for call in normalized_calls
                    ]
                },
            )
        except Exception:
            logger.exception(f"{self.log_prefix} 记录原生工具 Planner 日志失败")

        return PlannerDecision(
            prompt=prompt,
            content=content,
            reasoning=reasoning,
            model_name=model_name,
            tool_calls=normalized_calls,
            messages_by_id=messages_by_id,
            started_at=started_at,
            duration_ms=duration_ms,
            tool_results=list(tool_results),
        )


class PrivateToolPipeline:
    """执行一次私聊 Planner 工具循环，reply 成功或无工具调用时结束。"""

    def __init__(
        self,
        planner: PrivateToolPlanner,
        tool_registry: ChatToolRegistry,
        max_rounds: int = 3,
    ):
        if max_rounds < 1:
            raise ValueError("max_rounds 必须大于 0")
        self.planner = planner
        self.tool_registry = tool_registry
        self.max_rounds = max_rounds

    async def run(
        self,
        *,
        reply_handler: Callable[[ToolCall, PlannerDecision], Awaitable[ToolExecutionResult]],
        loop_start_time: float = 0.0,
        context_end_time: float | None = None,
        cycle_timers: dict[str, float] | None = None,
        thinking_id: str = "",
    ) -> PrivateTurnResult:
        decisions: list[PlannerDecision] = []
        tool_results: list[ToolExecutionResult] = []
        last_result: ToolExecutionResult | None = None

        for round_index in range(self.max_rounds):
            decision = await self.planner.plan(
                tool_results=list(tool_results),
                loop_start_time=loop_start_time,
                context_end_time=context_end_time,
                refresh_actions=round_index == 0,
            )
            decisions.append(decision)
            if not decision.tool_calls:
                return PrivateTurnResult(decisions=decisions, tool_results=tool_results)

            bounded_calls = decision.tool_calls[:MAX_TOOL_CALLS_PER_ROUND]
            if len(decision.tool_calls) > MAX_TOOL_CALLS_PER_ROUND:
                logger.warning(
                    f"Planner 单轮返回 {len(decision.tool_calls)} 个 Tool Call，仅执行前 {MAX_TOOL_CALLS_PER_ROUND} 个"
                )
            plugin_calls = [call for call in bounded_calls if call.func_name != REPLY_TOOL_NAME]
            reply_calls = [call for call in bounded_calls if call.func_name == REPLY_TOOL_NAME]

            exclusive_call = next(
                (
                    call
                    for call in plugin_calls
                    if self.tool_registry.get_source(call.func_name) == ToolSource.ACTION
                    and not self.tool_registry.allows_parallel(call.func_name)
                ),
                None,
            )
            if exclusive_call is not None:
                plugin_calls = [exclusive_call]

            if plugin_calls:
                for tool_call in plugin_calls:
                    if not has_tool_result_capacity(tool_results):
                        logger.warning("私聊 Planner 工具结果回灌达到大小上限，停止执行后续工具")
                        break
                    last_result = await self.tool_registry.execute(
                        tool_call,
                        messages_by_id=decision.messages_by_id,
                        reasoning=decision.reasoning or decision.content,
                        cycle_timers=cycle_timers or {},
                        thinking_id=thinking_id,
                        loop_start_time=loop_start_time,
                    )
                    append_bounded_tool_result(tool_results, last_result)
                if reply_calls:
                    deferred_reply = reply_calls[0]
                    append_bounded_tool_result(
                        tool_results,
                        ToolExecutionResult(
                            call_id=deferred_reply.call_id,
                            tool_name=REPLY_TOOL_NAME,
                            success=False,
                            content="同一轮包含信息工具，reply 已延后；请根据工具结果重新决定是否回复。",
                        ),
                    )
                continue

            reply_call = reply_calls[0]
            last_result = await reply_handler(reply_call, decision)
            append_bounded_tool_result(tool_results, last_result)
            if last_result.terminal or last_result.should_continue:
                return PrivateTurnResult(
                    should_continue=last_result.should_continue,
                    reply_sent=last_result.success,
                    reply_text=last_result.reply_text,
                    loop_info=last_result.loop_info,
                    decisions=decisions,
                    tool_results=tool_results,
                )

        return PrivateTurnResult(
            should_continue=last_result.should_continue if last_result else False,
            decisions=decisions,
            tool_results=tool_results,
        )
