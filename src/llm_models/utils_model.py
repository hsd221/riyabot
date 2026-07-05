import re
import asyncio
import time
import random

from enum import Enum
from rich.traceback import install
from typing import Tuple, List, Dict, Optional, Callable, Any, Set

from src.common.logger import get_logger
from src.config.config import model_config
from src.config.api_ada_configs import APIProvider, ModelInfo, TaskConfig
from .payload_content.message import MessageBuilder, Message
from .payload_content.resp_format import RespFormat
from .payload_content.tool_option import ToolOption, ToolCall, ToolOptionBuilder, ToolParamType
from .model_client.base_client import BaseClient, APIResponse, client_registry
from .utils import compress_messages, llm_usage_recorder
from .exceptions import (
    NetworkConnectionError,
    RespNotOkException,
    EmptyResponseException,
    ModelAttemptFailed,
)

install(extra_lines=3)

logger = get_logger("model_utils")


class RequestType(Enum):
    """请求类型枚举"""

    RESPONSE = "response"
    EMBEDDING = "embedding"
    AUDIO = "audio"


class LLMRequest:
    """LLM请求类"""

    def __init__(self, model_set: TaskConfig, request_type: str = "") -> None:
        self.task_name = request_type
        self.model_for_task = model_set
        self.request_type = request_type
        self.model_usage: Dict[str, Tuple[int, int, int]] = {
            model: (0, 0, 0) for model in self.model_for_task.model_list
        }
        """模型使用量记录，用于进行负载均衡，对应为(total_tokens, penalty, usage_penalty)，惩罚值是为了能在某个模型请求不给力或正在被使用的时候进行调整"""

    def _check_slow_request(self, time_cost: float, model_name: str) -> None:
        """检查请求是否过慢并输出警告日志

        Args:
            time_cost: 请求耗时（秒）
            model_name: 使用的模型名称
        """
        threshold = self.model_for_task.slow_threshold
        if time_cost > threshold:
            request_type_display = self.request_type or "未知任务"
            logger.warning(
                "LLM 请求耗时超过阈值",
                event_code="llm.request.slow",
                request_type=request_type_display,
                model_name=model_name,
                duration_seconds=round(time_cost, 3),
                threshold_seconds=threshold,
                remediation="可调整 model_config.toml 中对应任务的 slow_threshold 或使用更快模型",
            )

    def _log_response_debug(self, response: APIResponse, model_info: ModelInfo, duration_seconds: float) -> None:
        usage = response.usage
        logger.debug(
            "LLM 响应完成",
            event_code="llm.response.completed",
            request_type=self.request_type,
            model_name=model_info.name,
            provider_name=model_info.api_provider,
            duration_seconds=round(duration_seconds, 3),
            content_length=len(response.content or ""),
            reasoning_length=len(response.reasoning_content or ""),
            tool_call_count=len(response.tool_calls or []),
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
            llm_response_content=response.content,
            llm_response_reasoning=response.reasoning_content,
        )

    async def generate_response_for_image(
        self,
        prompt: str,
        image_base64: str,
        image_format: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Tuple[str, Tuple[str, str, Optional[List[ToolCall]]]]:
        """
        为图像生成响应
        Args:
            prompt (str): 提示词
            image_base64 (str): 图像的Base64编码字符串
            image_format (str): 图像格式（如 'png', 'jpeg' 等）
        Returns:
            (Tuple[str, str, str, Optional[List[ToolCall]]]): 响应内容、推理内容、模型名称、工具调用列表
        """
        start_time = time.time()

        def message_factory(client: BaseClient) -> List[Message]:
            message_builder = MessageBuilder()
            message_builder.add_text_content(prompt)
            message_builder.add_image_content(
                image_base64=image_base64, image_format=image_format, support_formats=client.get_support_image_formats()
            )
            return [message_builder.build()]

        response, model_info = await self._execute_request(
            request_type=RequestType.RESPONSE,
            message_factory=message_factory,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.content or ""
        reasoning_content = response.reasoning_content or ""
        tool_calls = response.tool_calls
        if not reasoning_content and content:
            content, extracted_reasoning = self._extract_reasoning(content)
            reasoning_content = extracted_reasoning
        time_cost = time.time() - start_time
        self._check_slow_request(time_cost, model_info.name)
        if usage := response.usage:
            llm_usage_recorder.record_usage_to_database(
                model_info=model_info,
                model_usage=usage,
                user_id="system",
                request_type=self.request_type,
                endpoint="/chat/completions",
                time_cost=time_cost,
            )
        return content, (reasoning_content, model_info.name, tool_calls)

    async def generate_response_for_voice(self, voice_base64: str) -> Optional[str]:
        """
        为语音生成响应
        Args:
            voice_base64 (str): 语音的Base64编码字符串
        Returns:
            (Optional[str]): 生成的文本描述或None
        """
        response, _ = await self._execute_request(
            request_type=RequestType.AUDIO,
            audio_base64=voice_base64,
        )
        return response.content or None

    async def generate_response_async(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        raise_when_empty: bool = True,
    ) -> Tuple[str, Tuple[str, str, Optional[List[ToolCall]]]]:
        """
        异步生成响应
        Args:
            prompt (str): 提示词
            temperature (float, optional): 温度参数
            max_tokens (int, optional): 最大token数
            tools (Optional[List[Dict[str, Any]]]): 工具列表
            raise_when_empty (bool): 当响应为空时是否抛出异常
        Returns:
            (Tuple[str, str, str, Optional[List[ToolCall]]]): 响应内容、推理内容、模型名称、工具调用列表
        """
        start_time = time.time()

        def message_factory(client: BaseClient) -> List[Message]:
            message_builder = MessageBuilder()
            message_builder.add_text_content(prompt)
            return [message_builder.build()]

        tool_built = self._build_tool_options(tools)

        response, model_info = await self._execute_request(
            request_type=RequestType.RESPONSE,
            message_factory=message_factory,
            temperature=temperature,
            max_tokens=max_tokens,
            tool_options=tool_built,
        )

        self._log_response_debug(response, model_info, time.time() - start_time)

        content = response.content
        reasoning_content = response.reasoning_content or ""
        tool_calls = response.tool_calls
        if not reasoning_content and content:
            content, extracted_reasoning = self._extract_reasoning(content)
            reasoning_content = extracted_reasoning
        if usage := response.usage:
            llm_usage_recorder.record_usage_to_database(
                model_info=model_info,
                model_usage=usage,
                user_id="system",
                request_type=self.request_type,
                endpoint="/chat/completions",
                time_cost=time.time() - start_time,
            )
        return content or "", (reasoning_content, model_info.name, tool_calls)

    async def generate_response_with_message_async(
        self,
        message_factory: Callable[[BaseClient], List[Message]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        raise_when_empty: bool = True,
    ) -> Tuple[str, Tuple[str, str, Optional[List[ToolCall]]]]:
        """
        异步生成响应
        Args:
            message_factory (Callable[[BaseClient], List[Message]]): 已构建好的消息工厂
            temperature (float, optional): 温度参数
            max_tokens (int, optional): 最大token数
            tools (Optional[List[Dict[str, Any]]]): 工具列表
            raise_when_empty (bool): 当响应为空时是否抛出异常
        Returns:
            (Tuple[str, str, str, Optional[List[ToolCall]]]): 响应内容、推理内容、模型名称、工具调用列表
        """
        start_time = time.time()

        tool_built = self._build_tool_options(tools)

        response, model_info = await self._execute_request(
            request_type=RequestType.RESPONSE,
            message_factory=message_factory,
            temperature=temperature,
            max_tokens=max_tokens,
            tool_options=tool_built,
        )

        time_cost = time.time() - start_time
        self._log_response_debug(response, model_info, time_cost)

        content = response.content
        reasoning_content = response.reasoning_content or ""
        tool_calls = response.tool_calls
        if not reasoning_content and content:
            content, extracted_reasoning = self._extract_reasoning(content)
            reasoning_content = extracted_reasoning
        self._check_slow_request(time_cost, model_info.name)
        if usage := response.usage:
            llm_usage_recorder.record_usage_to_database(
                model_info=model_info,
                model_usage=usage,
                user_id="system",
                request_type=self.request_type,
                endpoint="/chat/completions",
                time_cost=time_cost,
            )
        return content or "", (reasoning_content, model_info.name, tool_calls)

    async def get_embedding(self, embedding_input: str) -> Tuple[List[float], str]:
        """
        获取嵌入向量
        Args:
            embedding_input (str): 获取嵌入的目标
        Returns:
            (Tuple[List[float], str]): (嵌入向量，使用的模型名称)
        """
        start_time = time.time()
        response, model_info = await self._execute_request(
            request_type=RequestType.EMBEDDING,
            embedding_input=embedding_input,
        )
        embedding = response.embedding
        if usage := response.usage:
            llm_usage_recorder.record_usage_to_database(
                model_info=model_info,
                model_usage=usage,
                user_id="system",
                request_type=self.request_type,
                endpoint="/embeddings",
                time_cost=time.time() - start_time,
            )
        if not embedding:
            raise RuntimeError("获取embedding失败")
        return embedding, model_info.name

    def _select_model(self, exclude_models: Optional[Set[str]] = None) -> Tuple[ModelInfo, APIProvider, BaseClient]:
        """
        根据配置的策略选择模型：balance（负载均衡）或 random（随机选择）
        """
        available_models = {
            model: scores
            for model, scores in self.model_usage.items()
            if not exclude_models or model not in exclude_models
        }
        if not available_models:
            raise RuntimeError("没有可用的模型可供选择。所有模型均已尝试失败。")

        strategy = self.model_for_task.selection_strategy.lower()

        if strategy == "random":
            # 随机选择策略
            selected_model_name = random.choice(list(available_models.keys()))
        elif strategy == "balance":
            # 负载均衡策略：根据总tokens和惩罚值选择
            selected_model_name = min(
                available_models,
                key=lambda k: available_models[k][0] + available_models[k][1] * 300 + available_models[k][2] * 1000,
            )
        else:
            # 默认使用负载均衡策略
            logger.warning(
                "未知模型选择策略，使用默认负载均衡策略",
                event_code="llm.model_selection.unknown_strategy",
                strategy=strategy,
                fallback_strategy="balance",
            )
            selected_model_name = min(
                available_models,
                key=lambda k: available_models[k][0] + available_models[k][1] * 300 + available_models[k][2] * 1000,
            )

        model_info = model_config.get_model_info(selected_model_name)
        api_provider = model_config.get_provider(model_info.api_provider)
        force_new_client = self.request_type == "embedding"
        client = client_registry.get_client_class_instance(api_provider, force_new=force_new_client)
        logger.debug(
            "LLM 请求模型已选择",
            event_code="llm.model.selected",
            model_name=model_info.name,
            provider_name=model_info.api_provider,
            strategy=strategy,
            request_type=self.request_type,
        )
        total_tokens, penalty, usage_penalty = self.model_usage[model_info.name]
        self.model_usage[model_info.name] = (total_tokens, penalty, usage_penalty + 1)
        return model_info, api_provider, client

    async def _attempt_request_on_model(
        self,
        model_info: ModelInfo,
        api_provider: APIProvider,
        client: BaseClient,
        request_type: RequestType,
        message_list: List[Message],
        tool_options: list[ToolOption] | None,
        response_format: RespFormat | None,
        stream_response_handler: Optional[Callable],
        async_response_parser: Optional[Callable],
        temperature: Optional[float],
        max_tokens: Optional[int],
        embedding_input: str | None,
        audio_base64: str | None,
    ) -> APIResponse:
        """
        在单个模型上执行请求，包含针对临时错误的重试逻辑。
        如果成功，返回APIResponse。如果失败（重试耗尽或硬错误），则抛出ModelAttemptFailed异常。
        """
        retry_remain = api_provider.max_retry
        compressed_messages: Optional[List[Message]] = None

        while retry_remain > 0:
            try:
                if request_type == RequestType.RESPONSE:
                    # 温度优先级：参数传入 > 模型级别配置 > extra_params > 任务配置
                    effective_temperature = temperature
                    if effective_temperature is None:
                        effective_temperature = model_info.temperature
                    if effective_temperature is None:
                        effective_temperature = (model_info.extra_params or {}).get("temperature")
                    if effective_temperature is None:
                        effective_temperature = self.model_for_task.temperature

                    # max_tokens 优先级：参数传入 > 模型级别配置 > extra_params > 任务配置
                    effective_max_tokens = max_tokens
                    if effective_max_tokens is None:
                        effective_max_tokens = model_info.max_tokens
                    if effective_max_tokens is None:
                        effective_max_tokens = (model_info.extra_params or {}).get("max_tokens")
                    if effective_max_tokens is None:
                        effective_max_tokens = self.model_for_task.max_tokens

                    return await client.get_response(
                        model_info=model_info,
                        message_list=(compressed_messages or message_list),
                        tool_options=tool_options,
                        max_tokens=effective_max_tokens,
                        temperature=effective_temperature,
                        response_format=response_format,
                        stream_response_handler=stream_response_handler,
                        async_response_parser=async_response_parser,
                        extra_params=model_info.extra_params,
                    )
                elif request_type == RequestType.EMBEDDING:
                    assert embedding_input is not None, "嵌入输入不能为空"
                    return await client.get_embedding(
                        model_info=model_info,
                        embedding_input=embedding_input,
                        extra_params=model_info.extra_params,
                    )
                elif request_type == RequestType.AUDIO:
                    assert audio_base64 is not None, "音频Base64不能为空"
                    return await client.get_audio_transcriptions(
                        model_info=model_info,
                        audio_base64=audio_base64,
                        extra_params=model_info.extra_params,
                    )
            except EmptyResponseException as e:
                # 空回复：通常为临时问题，单独记录并重试
                original_error_info = self._get_original_error_info(e)
                retry_remain -= 1
                if retry_remain <= 0:
                    logger.error(
                        "LLM 模型空回复重试耗尽",
                        event_code="llm.model.empty_response_retries_exhausted",
                        model_name=model_info.name,
                        provider_name=api_provider.name,
                        original_error_info=original_error_info,
                    )
                    raise ModelAttemptFailed(f"模型 '{model_info.name}' 重试耗尽", original_exception=e) from e

                logger.warning(
                    "LLM 模型返回空回复，准备重试",
                    event_code="llm.model.empty_response_retry",
                    model_name=model_info.name,
                    provider_name=api_provider.name,
                    retry_remaining=retry_remain,
                    original_error_info=original_error_info,
                )
                await asyncio.sleep(api_provider.retry_interval)

            except NetworkConnectionError as e:
                # 网络错误：单独记录并重试
                # 尝试从链式异常中获取原始错误信息以诊断具体原因
                original_error_info = self._get_original_error_info(e)

                retry_remain -= 1
                if retry_remain <= 0:
                    logger.error(
                        "LLM 模型网络错误重试耗尽",
                        event_code="llm.model.network_retries_exhausted",
                        model_name=model_info.name,
                        provider_name=api_provider.name,
                        original_error_info=original_error_info,
                    )
                    raise ModelAttemptFailed(f"模型 '{model_info.name}' 重试耗尽", original_exception=e) from e

                logger.warning(
                    "LLM 模型网络错误，准备重试",
                    event_code="llm.model.network_retry",
                    model_name=model_info.name,
                    provider_name=api_provider.name,
                    retry_remaining=retry_remain,
                    error=str(e),
                    original_error_info=original_error_info,
                    remediation="如请求 API 正常但超时频繁，可调整对应 API Provider 的 timeout",
                )
                await asyncio.sleep(api_provider.retry_interval)

            except RespNotOkException as e:
                original_error_info = self._get_original_error_info(e)

                # 可重试的HTTP错误
                if e.status_code == 429 or e.status_code >= 500:
                    retry_remain -= 1
                    if retry_remain <= 0:
                        logger.error(
                            "LLM 模型 HTTP 错误重试耗尽",
                            event_code="llm.model.http_retries_exhausted",
                            model_name=model_info.name,
                            provider_name=api_provider.name,
                            status_code=e.status_code,
                            original_error_info=original_error_info,
                        )
                        raise ModelAttemptFailed(f"模型 '{model_info.name}' 重试耗尽", original_exception=e) from e

                    logger.warning(
                        "LLM 模型 HTTP 错误，准备重试",
                        event_code="llm.model.http_retry",
                        model_name=model_info.name,
                        provider_name=api_provider.name,
                        status_code=e.status_code,
                        retry_remaining=retry_remain,
                        error=str(e),
                        original_error_info=original_error_info,
                    )
                    await asyncio.sleep(api_provider.retry_interval)
                    continue

                # 特殊处理413，尝试压缩
                if e.status_code == 413 and message_list and not compressed_messages:
                    logger.warning(
                        "LLM 请求体过大，尝试压缩消息后重试",
                        event_code="llm.model.request_too_large_compressing",
                        model_name=model_info.name,
                        provider_name=api_provider.name,
                        status_code=e.status_code,
                        message_count=len(message_list),
                    )
                    # 压缩消息本身不消耗重试次数
                    compressed_messages = compress_messages(message_list)
                    continue

                # 不可重试的HTTP错误
                logger.warning(
                    "LLM 模型 HTTP 错误不可重试",
                    event_code="llm.model.http_non_retryable",
                    model_name=model_info.name,
                    provider_name=api_provider.name,
                    status_code=e.status_code,
                    error=str(e),
                    original_error_info=original_error_info,
                )
                raise ModelAttemptFailed(f"模型 '{model_info.name}' 遇到硬错误", original_exception=e) from e

            except Exception as e:
                original_error_info = self._get_original_error_info(e)

                logger.exception(
                    "LLM 模型请求出现不可重试异常",
                    event_code="llm.model.non_retryable_exception",
                    model_name=model_info.name,
                    provider_name=api_provider.name,
                    original_error_info=original_error_info,
                )
                raise ModelAttemptFailed(f"模型 '{model_info.name}' 遇到硬错误", original_exception=e) from e

        raise ModelAttemptFailed(f"模型 '{model_info.name}' 未被尝试，因为重试次数已配置为0或更少。")

    async def _execute_request(
        self,
        request_type: RequestType,
        message_factory: Optional[Callable[[BaseClient], List[Message]]] = None,
        tool_options: list[ToolOption] | None = None,
        response_format: RespFormat | None = None,
        stream_response_handler: Optional[Callable] = None,
        async_response_parser: Optional[Callable] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        embedding_input: str | None = None,
        audio_base64: str | None = None,
    ) -> Tuple[APIResponse, ModelInfo]:
        """
        调度器函数，负责模型选择、故障切换。
        """
        failed_models_this_request: Set[str] = set()
        max_attempts = len(self.model_for_task.model_list)
        last_exception: Optional[Exception] = None

        for _ in range(max_attempts):
            model_info, api_provider, client = self._select_model(exclude_models=failed_models_this_request)

            message_list = []
            if message_factory:
                message_list = message_factory(client)

            try:
                response = await self._attempt_request_on_model(
                    model_info,
                    api_provider,
                    client,
                    request_type,
                    message_list=message_list,
                    tool_options=tool_options,
                    response_format=response_format,
                    stream_response_handler=stream_response_handler,
                    async_response_parser=async_response_parser,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    embedding_input=embedding_input,
                    audio_base64=audio_base64,
                )
                total_tokens, penalty, usage_penalty = self.model_usage[model_info.name]
                if response_usage := response.usage:
                    total_tokens += response_usage.total_tokens
                self.model_usage[model_info.name] = (total_tokens, penalty, usage_penalty - 1)
                return response, model_info

            except ModelAttemptFailed as e:
                last_exception = e.original_exception or e
                logger.warning(
                    "LLM 模型尝试失败，切换到下一个模型",
                    event_code="llm.model.attempt_failed",
                    model_name=model_info.name,
                    request_type=request_type.value,
                    error=str(e),
                )
                total_tokens, penalty, usage_penalty = self.model_usage[model_info.name]
                self.model_usage[model_info.name] = (total_tokens, penalty + 1, usage_penalty - 1)
                failed_models_this_request.add(model_info.name)

                if isinstance(last_exception, RespNotOkException) and last_exception.status_code == 400:
                    logger.warning(
                        "LLM 收到客户端错误，跳过当前模型",
                        event_code="llm.model.client_error_skipped",
                        model_name=model_info.name,
                        status_code=400,
                    )
                    continue

        logger.error(
            "LLM 请求所有模型均尝试失败",
            event_code="llm.request.all_models_failed",
            request_type=request_type.value,
            max_attempts=max_attempts,
            failed_models=list(failed_models_this_request),
        )
        if last_exception:
            raise last_exception
        raise RuntimeError("请求失败，所有可用模型均已尝试失败。")

    def _build_tool_options(self, tools: Optional[List[Dict[str, Any]]]) -> Optional[List[ToolOption]]:
        # sourcery skip: extract-method
        """构建工具选项列表"""
        if not tools:
            return None
        tool_options: List[ToolOption] = []
        for tool in tools:
            tool_legal = True
            tool_options_builder = ToolOptionBuilder()
            tool_options_builder.set_name(tool.get("name", ""))
            tool_options_builder.set_description(tool.get("description", ""))
            parameters: List[Tuple[str, str, str, bool, List[str] | None]] = tool.get("parameters", [])
            for param in parameters:
                try:
                    assert isinstance(param, tuple) and len(param) == 5, "参数必须是包含5个元素的元组"
                    assert isinstance(param[0], str), "参数名称必须是字符串"
                    assert isinstance(param[1], ToolParamType), "参数类型必须是ToolParamType枚举"
                    assert isinstance(param[2], str), "参数描述必须是字符串"
                    assert isinstance(param[3], bool), "参数是否必填必须是布尔值"
                    assert isinstance(param[4], list) or param[4] is None, "参数枚举值必须是列表或None"
                    tool_options_builder.add_param(
                        name=param[0],
                        param_type=param[1],
                        description=param[2],
                        required=param[3],
                        enum_values=param[4],
                    )
                except AssertionError as ae:
                    tool_legal = False
                    logger.error(
                        "工具参数定义错误", event_code="llm.tool_param.invalid", param_name=param[0], error=str(ae)
                    )
                except Exception:
                    tool_legal = False
                    logger.exception("工具参数构建失败", event_code="llm.tool_param.build_failed")
            if tool_legal:
                tool_options.append(tool_options_builder.build())
        return tool_options or None

    @staticmethod
    def _extract_reasoning(content: str) -> Tuple[str, str]:
        """CoT思维链提取，向后兼容"""
        match = re.search(r"(?:<think>)?(.*?)</think>", content, re.DOTALL)
        content = re.sub(r"(?:<think>)?.*?</think>", "", content, flags=re.DOTALL, count=1).strip()
        reasoning = match[1].strip() if match else ""
        return content, reasoning

    @staticmethod
    def _get_original_error_info(e: Exception) -> str:
        """获取原始错误信息"""
        if e.__cause__:
            original_error_type = type(e.__cause__).__name__
            original_error_msg = str(e.__cause__)
            return f"\n  底层异常类型: {original_error_type}\n  底层异常信息: {original_error_msg}"
        return ""
