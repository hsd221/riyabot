from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from src.chat.logger.plan_reply_logger import PlanReplyLogger
from src.chat.message_receive.chat_stream import get_chat_manager
from src.chat.utils.chat_message_builder import build_readable_messages_with_id, get_raw_msg_before_timestamp_with_chat
from src.chat.utils.utils import get_chat_type_and_target_info
from src.common.logger import get_logger
from src.common.prompt_manager import prompt_manager
from src.config.config import global_config, model_config
from src.llm_models.utils_model import LLMRequest
from src.llm_models.payload_content import ToolCall
from src.llm_models.payload_content.tool_option import ToolParamType
from src.plugin_system.base.component_types import EventType
from src.plugin_system.apis.tool_api import get_llm_available_tool_definitions
from src.plugin_system.core.events_manager import events_manager
from src.plugin_system.core.global_announcement_manager import global_announcement_manager
from src.plugin_system.core.tool_use import ToolExecutor

if TYPE_CHECKING:
    from src.common.data_models.database_data_model import DatabaseMessages


REPLY_TOOL_NAME = "reply"
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


@dataclass(slots=True)
class ToolExecutionResult:
    call_id: str
    tool_name: str
    success: bool
    content: str
    terminal: bool = False
    reply_text: str = ""
    loop_info: dict[str, Any] | None = None
    should_continue: bool = False

    def to_prompt_data(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.call_id,
            "tool_name": self.tool_name,
            "success": self.success,
            "content": self.content,
        }


@dataclass(slots=True)
class PrivateTurnResult:
    should_continue: bool = False
    reply_sent: bool = False
    reply_text: str = ""
    loop_info: dict[str, Any] | None = None
    decisions: list[PlannerDecision] = field(default_factory=list)
    tool_results: list[ToolExecutionResult] = field(default_factory=list)


class PrivateToolRegistry:
    """私聊 Planner 的工具目录，统一内置 reply 与插件 Tool。"""

    def __init__(self, chat_id: str, executor: ToolExecutor | None = None):
        self.chat_id = chat_id
        self.executor = executor or ToolExecutor(chat_id=chat_id, enable_cache=False)

    @staticmethod
    def _reply_definition() -> dict[str, Any]:
        return {
            "name": REPLY_TOOL_NAME,
            "description": "仅在当前私聊确实需要发送消息时调用；实际文本由 Replyer 生成。",
            "parameters": [
                (
                    "target_message_id",
                    ToolParamType.STRING,
                    "要回应的真实消息 ID，必须来自当前聊天记录中的 m+数字标识。",
                    True,
                    None,
                ),
                (
                    "reply_reason",
                    ToolParamType.STRING,
                    "需要回复的原因和应覆盖的要点，不要在这里撰写最终回复文本。",
                    True,
                    None,
                ),
            ],
        }

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        disabled_tools = set(global_announcement_manager.get_disabled_chat_tools(self.chat_id))
        definitions = [self._reply_definition()]
        for tool_name, definition in get_llm_available_tool_definitions():
            if tool_name == REPLY_TOOL_NAME or tool_name in disabled_tools:
                continue
            definitions.append(dict(definition))
        return definitions

    async def execute_plugin(self, tool_call: ToolCall) -> ToolExecutionResult:
        if tool_call.func_name == REPLY_TOOL_NAME:
            return ToolExecutionResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.func_name,
                success=False,
                content="reply 是内置终止工具，不能按插件工具执行。",
            )

        safe_call = ToolCall(
            call_id=tool_call.call_id,
            func_name=tool_call.func_name,
            args=dict(tool_call.args) if isinstance(tool_call.args, dict) else {},
        )
        try:
            result = await self.executor.execute_tool_call(safe_call)
        except Exception as exc:
            return ToolExecutionResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.func_name,
                success=False,
                content=f"工具执行失败: {exc}",
            )

        if not result:
            return ToolExecutionResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.func_name,
                success=False,
                content=f"工具 {tool_call.func_name} 不可用或没有返回结果。",
            )

        content = result.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        return ToolExecutionResult(
            call_id=tool_call.call_id,
            tool_name=tool_call.func_name,
            success=True,
            content=content,
        )


class PrivateToolPlanner:
    """用原生工具调用决定私聊本轮是否执行工具或回复。"""

    def __init__(self, chat_id: str, tool_registry: PrivateToolRegistry):
        self.chat_id = chat_id
        self.log_prefix = f"[{get_chat_manager().get_stream_name(chat_id) or chat_id}]"
        self.tool_registry = tool_registry
        self.planner_llm = LLMRequest(model_set=model_config.model_task_config.planner, request_type="planner")
        self.last_obs_time_mark = 0.0

    def _load_context(self) -> tuple[str, dict[str, "DatabaseMessages"], str]:
        messages = get_raw_msg_before_timestamp_with_chat(
            chat_id=self.chat_id,
            timestamp=time.time(),
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
        return chat_content, dict(message_id_list), chat_target

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
            "chat.private.tool_planner",
            time_block=f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            name_block=f"你的名字是{bot_name}{bot_aliases}，请注意哪些是你自己的发言。",
            chat_target=chat_target,
            chat_content=chat_content,
            tool_results_block=tool_results_block,
            plan_style=global_config.experimental.private_plan_style,
            moderation_prompt=prompt_manager.format_prompt("shared.moderation.standard"),
        )

    async def plan(
        self,
        *,
        tool_results: list[ToolExecutionResult] | None = None,
        loop_start_time: float = 0.0,
    ) -> PlannerDecision:
        started_at = time.time()
        tool_results = tool_results or []
        chat_content, messages_by_id, chat_target = self._load_context()
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
            )
        if modified_message and modified_message._modify_flags.modify_llm_prompt:
            prompt = str(modified_message.llm_prompt)

        tool_definitions = self.tool_registry.get_tool_definitions()
        try:
            llm_started_at = time.perf_counter()
            content, (reasoning, model_name, tool_calls) = await self.planner_llm.generate_response_async(
                prompt=prompt,
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
            )

        normalized_calls = list(tool_calls or [])
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
        )


class PrivateToolPipeline:
    """执行一次私聊 Planner 工具循环，reply 成功或无工具调用时结束。"""

    def __init__(
        self,
        planner: PrivateToolPlanner,
        tool_registry: PrivateToolRegistry,
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
    ) -> PrivateTurnResult:
        decisions: list[PlannerDecision] = []
        tool_results: list[ToolExecutionResult] = []
        last_result: ToolExecutionResult | None = None

        for _ in range(self.max_rounds):
            decision = await self.planner.plan(
                tool_results=list(tool_results),
                loop_start_time=loop_start_time,
            )
            decisions.append(decision)
            if not decision.tool_calls:
                return PrivateTurnResult(decisions=decisions, tool_results=tool_results)

            plugin_calls = [call for call in decision.tool_calls if call.func_name != REPLY_TOOL_NAME]
            reply_calls = [call for call in decision.tool_calls if call.func_name == REPLY_TOOL_NAME]

            if plugin_calls:
                for tool_call in plugin_calls:
                    last_result = await self.tool_registry.execute_plugin(tool_call)
                    tool_results.append(last_result)
                if reply_calls:
                    deferred_reply = reply_calls[0]
                    tool_results.append(
                        ToolExecutionResult(
                            call_id=deferred_reply.call_id,
                            tool_name=REPLY_TOOL_NAME,
                            success=False,
                            content="同一轮包含信息工具，reply 已延后；请根据工具结果重新决定是否回复。",
                        )
                    )
                continue

            reply_call = reply_calls[0]
            last_result = await reply_handler(reply_call, decision)
            tool_results.append(last_result)
            if last_result.terminal:
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
