import base64
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from src.config.api_ada_configs import APIProvider, ModelInfo, TaskConfig
from src.llm_models import exceptions
from src.llm_models.model_client.base_client import APIResponse, UsageRecord
from src.llm_models.payload_content.message import MessageBuilder
from src.llm_models.payload_content.tool_option import ToolParamType
from src.llm_models.utils import LLMUsageRecorder, compress_messages
from src.llm_models import utils as llm_utils
from src.llm_models.exceptions import EmptyResponseException, ModelAttemptFailed, RespNotOkException
from src.llm_models.utils_model import LLMRequest, RequestType


def _png_base64() -> str:
    buffer = io.BytesIO()
    Image.new("RGBA", (16, 16), (255, 0, 0, 128)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class LLMExceptionsTest(unittest.TestCase):
    def test_exceptions_format_defaults_mapped_codes_custom_messages_and_original_errors(self) -> None:
        self.assertEqual(str(exceptions.NetworkConnectionError()), "连接异常，请检查网络连接状态或URL是否正确")
        self.assertEqual(str(exceptions.ReqAbortException()), "请求因未知原因异常终止")
        self.assertEqual(str(exceptions.RespNotOkException(401)), exceptions.error_code_mapping[401])
        self.assertEqual(str(exceptions.RespNotOkException(418, "teapot")), "teapot")
        self.assertEqual(str(exceptions.RespNotOkException(499)), "未知的异常响应代码：499")
        self.assertEqual(
            str(exceptions.RespParseException({"raw": "bad"})),
            "解析响应内容时发生未知错误，请检查是否配置了正确的解析方法",
        )
        self.assertEqual(str(exceptions.EmptyResponseException()), "响应内容为空，这可能是一个临时性问题")

        original = RuntimeError("network down")
        failed = exceptions.ModelAttemptFailed("failed", original_exception=original)

        self.assertEqual(str(failed), "failed")
        self.assertIs(failed.original_exception, original)


class LLMCompressMessagesTest(unittest.TestCase):
    def test_compress_messages_reformats_static_images_and_keeps_text_order(self) -> None:
        image_base64 = _png_base64()
        message = MessageBuilder().add_text_content("look").add_image_content("png", image_base64).build()

        compressed = compress_messages([message], img_target_size=10_000_000)[0]

        self.assertEqual(compressed.content[0], "look")
        self.assertEqual(compressed.content[1][0], "png")
        self.assertTrue(base64.b64decode(compressed.content[1][1]).startswith(b"\xff\xd8"))

    def test_compress_messages_leaves_non_multimodal_messages_unchanged(self) -> None:
        text_message = MessageBuilder().add_text_content("hello").build()

        compressed = compress_messages([text_message])

        self.assertIs(compressed[0], text_message)


class LLMUsageRecorderTest(unittest.TestCase):
    def test_record_usage_calculates_costs_and_persists_rounded_fields(self) -> None:
        recorder = LLMUsageRecorder.__new__(LLMUsageRecorder)
        model = ModelInfo(
            model_identifier="provider-model",
            name="model-a",
            api_provider="provider-a",
            price_in=2.0,
            price_out=4.0,
        )
        usage = UsageRecord(
            model_name="model-a",
            provider_name="provider-a",
            prompt_tokens=500_000,
            completion_tokens=250_000,
            total_tokens=750_000,
        )

        with patch.object(llm_utils.LLMUsage, "create") as create:
            recorder.record_usage_to_database(
                model_info=model,
                model_usage=usage,
                user_id="user-1",
                request_type="reply",
                endpoint="/chat/completions",
                time_cost=1.23456,
            )

        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["model_name"], "provider-model")
        self.assertEqual(kwargs["model_assign_name"], "model-a")
        self.assertEqual(kwargs["prompt_tokens"], 500_000)
        self.assertEqual(kwargs["completion_tokens"], 250_000)
        self.assertEqual(kwargs["total_tokens"], 750_000)
        self.assertEqual(kwargs["cost"], 2.0)
        self.assertEqual(kwargs["time_cost"], 1.235)
        self.assertEqual(kwargs["status"], "success")


class CapturingClient:
    def __init__(self, response: APIResponse | None = None):
        self.calls = []
        self.response = response or APIResponse(content="ok")

    async def get_response(self, **kwargs):
        self.calls.append(("response", kwargs))
        return self.response

    async def get_embedding(self, **kwargs):
        self.calls.append(("embedding", kwargs))
        return self.response

    async def get_audio_transcriptions(self, **kwargs):
        self.calls.append(("audio", kwargs))
        return self.response


class RequestTooLargeThenSuccessClient(CapturingClient):
    async def get_response(self, **kwargs):
        self.calls.append(("response", kwargs))
        if len(self.calls) == 1:
            raise RespNotOkException(413)
        return self.response


class LLMRequestHelpersTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.task = TaskConfig(
            model_list=["model-a", "model-b"],
            max_tokens=64,
            temperature=0.2,
            selection_strategy="balance",
        )

    def test_build_tool_options_keeps_valid_tools_and_skips_invalid_parameter_definitions(self) -> None:
        request = LLMRequest(self.task, request_type="reply")

        options = request._build_tool_options(
            [
                {
                    "name": "search",
                    "description": "Search docs",
                    "parameters": [("query", ToolParamType.STRING, "Query", True, ["docs", "web"])],
                },
                {
                    "name": "broken",
                    "description": "Broken tool",
                    "parameters": [("count", "integer", "Count", False, None)],
                },
            ]
        )

        self.assertEqual(len(options), 1)
        self.assertEqual(options[0].name, "search")
        self.assertEqual(options[0].params[0].enum_values, ["docs", "web"])

    def test_extract_reasoning_removes_first_think_block_and_reports_original_exception_info(self) -> None:
        content, reasoning = LLMRequest._extract_reasoning("<think>hidden</think>\nanswer</think>")

        self.assertEqual(content, "answer</think>")
        self.assertEqual(reasoning, "hidden")

        try:
            try:
                raise KeyError("root")
            except KeyError as exc:
                raise RuntimeError("wrapped") from exc
        except RuntimeError as exc:
            original_info = LLMRequest._get_original_error_info(exc)

        self.assertIn("底层异常类型: KeyError", original_info)
        self.assertIn("底层异常信息: 'root'", original_info)

    def test_select_model_uses_balance_scores_exclusions_and_embedding_force_new_clients(self) -> None:
        request = LLMRequest(self.task, request_type="embedding")
        request.model_usage = {"model-a": (200, 0, 0), "model-b": (10, 0, 0)}
        provider = APIProvider(name="provider-a", base_url="https://api.example.test", api_key="secret")
        models = {
            "model-a": ModelInfo(model_identifier="a", name="model-a", api_provider="provider-a"),
            "model-b": ModelInfo(model_identifier="b", name="model-b", api_provider="provider-a"),
        }
        fake_model_config = SimpleNamespace(
            get_model_info=lambda name: models[name],
            get_provider=lambda name: provider,
        )
        fake_client = object()

        with (
            patch("src.llm_models.utils_model.model_config", fake_model_config),
            patch(
                "src.llm_models.utils_model.client_registry.get_client_class_instance", return_value=fake_client
            ) as get_client,
        ):
            model_info, api_provider, client = request._select_model(exclude_models={"model-a"})

        self.assertEqual(model_info.name, "model-b")
        self.assertIs(api_provider, provider)
        self.assertIs(client, fake_client)
        get_client.assert_called_once_with(provider, force_new=True)
        self.assertEqual(request.model_usage["model-b"], (10, 0, 1))

    async def test_attempt_response_uses_request_then_model_then_task_generation_defaults(self) -> None:
        request = LLMRequest(self.task, request_type="reply")
        provider = APIProvider(
            name="provider-a",
            base_url="https://api.example.test",
            api_key="secret",
            max_retry=1,
            retry_interval=0,
        )
        model = ModelInfo(
            model_identifier="a",
            name="model-a",
            api_provider="provider-a",
            extra_params={"temperature": 0.7, "max_tokens": 33},
        )
        client = CapturingClient()
        message = MessageBuilder().add_text_content("hello").build()

        response = await request._attempt_request_on_model(
            model,
            provider,
            client,
            RequestType.RESPONSE,
            message_list=[message],
            tool_options=None,
            response_format=None,
            stream_response_handler=None,
            async_response_parser=None,
            temperature=None,
            max_tokens=None,
            embedding_input=None,
            audio_base64=None,
        )

        self.assertEqual(response.content, "ok")
        kwargs = client.calls[0][1]
        self.assertEqual(kwargs["temperature"], 0.7)
        self.assertEqual(kwargs["max_tokens"], 33)
        self.assertEqual(kwargs["extra_params"], {"temperature": 0.7, "max_tokens": 33})

    async def test_attempt_response_retries_413_after_compressing_messages_without_consuming_retry(self) -> None:
        request = LLMRequest(self.task, request_type="reply")
        provider = APIProvider(
            name="provider-a",
            base_url="https://api.example.test",
            api_key="secret",
            max_retry=1,
            retry_interval=0,
        )
        model = ModelInfo(model_identifier="a", name="model-a", api_provider="provider-a")
        client = RequestTooLargeThenSuccessClient()
        message = MessageBuilder().add_text_content("look").add_image_content("png", _png_base64()).build()

        response = await request._attempt_request_on_model(
            model,
            provider,
            client,
            RequestType.RESPONSE,
            message_list=[message],
            tool_options=None,
            response_format=None,
            stream_response_handler=None,
            async_response_parser=None,
            temperature=0.4,
            max_tokens=12,
            embedding_input=None,
            audio_base64=None,
        )

        self.assertEqual(response.content, "ok")
        self.assertEqual(len(client.calls), 2)
        first_call_messages = client.calls[0][1]["message_list"]
        second_call_messages = client.calls[1][1]["message_list"]
        self.assertIs(first_call_messages[0], message)
        self.assertIsNot(second_call_messages[0], message)
        self.assertTrue(base64.b64decode(second_call_messages[0].content[1][1]).startswith(b"\xff\xd8"))

    async def test_attempt_request_wraps_exhausted_empty_responses_in_model_attempt_failed(self) -> None:
        class EmptyClient(CapturingClient):
            async def get_response(self, **kwargs):
                raise EmptyResponseException("empty")

        request = LLMRequest(self.task, request_type="reply")
        provider = APIProvider(
            name="provider-a",
            base_url="https://api.example.test",
            api_key="secret",
            max_retry=1,
            retry_interval=0,
        )
        model = ModelInfo(model_identifier="a", name="model-a", api_provider="provider-a")

        with self.assertRaises(ModelAttemptFailed) as raised:
            await request._attempt_request_on_model(
                model,
                provider,
                EmptyClient(),
                RequestType.RESPONSE,
                message_list=[MessageBuilder().add_text_content("hello").build()],
                tool_options=None,
                response_format=None,
                stream_response_handler=None,
                async_response_parser=None,
                temperature=None,
                max_tokens=None,
                embedding_input=None,
                audio_base64=None,
            )

        self.assertIsInstance(raised.exception.original_exception, EmptyResponseException)


if __name__ == "__main__":
    unittest.main()
