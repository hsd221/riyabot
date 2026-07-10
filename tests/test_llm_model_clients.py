import base64
import io
import json
import unittest
from types import SimpleNamespace

from src.llm_models.exceptions import EmptyResponseException, RespParseException
from src.llm_models.model_client import gemini_client, openai_client
from src.llm_models.payload_content.message import MessageBuilder, RoleType
from src.llm_models.payload_content.tool_option import ToolCall, ToolOptionBuilder, ToolParamType


def written_buffer(content: str) -> io.StringIO:
    buffer = io.StringIO()
    buffer.write(content)
    return buffer


def make_tool_option():
    return (
        ToolOptionBuilder()
        .set_name("search")
        .set_description("Search docs")
        .add_param("query", ToolParamType.STRING, "Query", required=True, enum_values=["docs", "web"])
        .add_param("limit", ToolParamType.INTEGER, "Limit")
        .add_param("score", ToolParamType.FLOAT, "Score")
        .add_param("exact", ToolParamType.BOOLEAN, "Exact")
        .build()
    )


class OpenAIClientAdapterTest(unittest.TestCase):
    def test_convert_messages_preserves_roles_images_tool_calls_and_tool_results(self) -> None:
        messages = [
            MessageBuilder().set_role(RoleType.System).add_text_content("system").build(),
            MessageBuilder()
            .set_role(RoleType.User)
            .add_text_content("look")
            .add_text_content("第 1 帧：")
            .add_image_content("png", "frame1")
            .add_text_content("第 2 帧：")
            .add_image_content("png", "frame2")
            .build(),
            MessageBuilder()
            .set_role(RoleType.Assistant)
            .set_tool_calls([ToolCall("call-1", "search", {"query": "MaiBot"})])
            .build(),
            MessageBuilder().set_role(RoleType.Tool).add_text_content("tool result").add_tool_call("call-1").build(),
        ]

        converted = openai_client._convert_messages(messages)

        self.assertEqual(converted[0], {"role": "system", "content": "system"})
        self.assertEqual(converted[1]["role"], "user")
        self.assertEqual(converted[1]["content"][0], {"type": "text", "text": "look"})
        self.assertEqual(converted[1]["content"][1], {"type": "text", "text": "第 1 帧："})
        self.assertEqual(converted[1]["content"][2]["image_url"]["url"], "data:image/png;base64,frame1")
        self.assertEqual(converted[1]["content"][3], {"type": "text", "text": "第 2 帧："})
        self.assertEqual(converted[1]["content"][4]["image_url"]["url"], "data:image/png;base64,frame2")
        self.assertEqual(converted[2]["content"], "")
        self.assertEqual(converted[2]["tool_calls"][0]["function"]["name"], "search")
        self.assertEqual(json.loads(converted[2]["tool_calls"][0]["function"]["arguments"]), {"query": "MaiBot"})
        self.assertEqual(converted[3]["tool_call_id"], "call-1")

        jpeg_message = MessageBuilder().add_image_content("jpeg", "img64").build()
        jpeg_content = openai_client._convert_messages([jpeg_message])[0]["content"]
        self.assertEqual(jpeg_content[0]["image_url"]["url"], "data:image/jpeg;base64,img64")

    def test_convert_tool_options_maps_json_schema_types_and_required_fields(self) -> None:
        converted = openai_client._convert_tool_options([make_tool_option()])
        function = converted[0]["function"]
        properties = function["parameters"]["properties"]

        self.assertEqual(function["name"], "search")
        self.assertEqual(function["parameters"]["required"], ["query"])
        self.assertEqual(properties["query"]["enum"], ["docs", "web"])
        self.assertEqual(properties["score"]["type"], "number")
        self.assertEqual(properties["exact"]["type"], "boolean")

    def test_stream_response_builder_collects_content_reasoning_and_tool_calls_or_raises_empty(self) -> None:
        content_buffer = written_buffer("answer")
        reasoning_buffer = written_buffer("hidden")
        arguments_buffer = written_buffer('{"query": "MaiBot"}')

        response = openai_client._build_stream_api_resp(
            content_buffer,
            reasoning_buffer,
            [("call-1", "search", arguments_buffer)],
        )

        self.assertEqual(response.content, "answer")
        self.assertEqual(response.reasoning_content, "hidden")
        self.assertEqual(response.tool_calls[0].args, {"query": "MaiBot"})

        with self.assertRaises(EmptyResponseException):
            openai_client._build_stream_api_resp(io.StringIO(), io.StringIO(), [])

        with self.assertRaises(RespParseException):
            openai_client._build_stream_api_resp(
                io.StringIO(), io.StringIO(), [("call-1", "search", written_buffer("[1]"))]
            )

    def test_normal_response_parser_extracts_think_blocks_tool_calls_usage_and_empty_choices(self) -> None:
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="<think>hidden</think>\nanswer", reasoning_content=None, tool_calls=None
                    ),
                    finish_reason=None,
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
            model="model-a",
            id="resp-1",
        )

        parsed, usage = openai_client._default_normal_response_parser(response)

        self.assertEqual(parsed.content, "answer")
        self.assertEqual(parsed.reasoning_content, "hidden")
        self.assertEqual(usage, (1, 2, 3))
        self.assertIs(parsed.raw_data, response)

        tool_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        reasoning_content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call-1",
                                function=SimpleNamespace(name="search", arguments=json.dumps({"query": "MaiBot"})),
                            )
                        ],
                    ),
                    finish_reason=None,
                )
            ],
            usage=None,
            model="model-a",
            id="resp-2",
        )
        parsed_tool, usage = openai_client._default_normal_response_parser(tool_response)
        self.assertIsNone(usage)
        self.assertEqual(parsed_tool.tool_calls[0].func_name, "search")
        self.assertEqual(parsed_tool.tool_calls[0].args, {"query": "MaiBot"})

        with self.assertRaises(EmptyResponseException):
            openai_client._default_normal_response_parser(
                SimpleNamespace(choices=[], usage=None, model="model-a", id="empty")
            )

    def test_support_image_formats_are_declared_without_client_initialization(self) -> None:
        client = openai_client.OpenaiClient.__new__(openai_client.OpenaiClient)

        self.assertEqual(client.get_support_image_formats(), ["jpg", "jpeg", "png", "webp", "gif"])


class GeminiClientAdapterTest(unittest.TestCase):
    def test_convert_messages_splits_system_instructions_and_converts_user_model_content(self) -> None:
        first_image_base64 = base64.b64encode(b"first-image").decode("ascii")
        second_image_base64 = base64.b64encode(b"second-image").decode("ascii")
        messages = [
            MessageBuilder().set_role(RoleType.System).add_text_content("system").build(),
            MessageBuilder()
            .set_role(RoleType.User)
            .add_text_content("look")
            .add_text_content("第 1 帧：")
            .add_image_content("png", first_image_base64)
            .add_text_content("第 2 帧：")
            .add_image_content("png", second_image_base64)
            .build(),
            MessageBuilder().set_role(RoleType.Assistant).add_text_content("answer").build(),
            MessageBuilder().set_role(RoleType.Tool).add_text_content("tool result").add_tool_call("call-1").build(),
        ]

        contents, system_instructions = gemini_client._convert_messages(messages)

        self.assertEqual(system_instructions, ["system"])
        self.assertEqual(contents[0].role, "user")
        self.assertEqual(contents[0].parts[0].text, "look")
        self.assertEqual(contents[0].parts[1].text, "第 1 帧：")
        self.assertEqual(contents[0].parts[2].inline_data.mime_type, "image/png")
        self.assertEqual(contents[0].parts[2].inline_data.data, b"first-image")
        self.assertEqual(contents[0].parts[3].text, "第 2 帧：")
        self.assertEqual(contents[0].parts[4].inline_data.mime_type, "image/png")
        self.assertEqual(contents[0].parts[4].inline_data.data, b"second-image")
        self.assertEqual(contents[1].role, "model")

        system_with_image = (
            MessageBuilder().set_role(RoleType.System).add_image_content("png", first_image_base64).build()
        )
        with self.assertRaises(ValueError):
            gemini_client._convert_messages([system_with_image])

    def test_convert_tool_options_maps_float_bool_and_required_metadata(self) -> None:
        converted = gemini_client._convert_tool_options([make_tool_option()])
        declaration = converted[0]
        parameters = declaration.parameters

        self.assertEqual(declaration.name, "search")
        self.assertEqual(parameters.required, ["query"])
        self.assertEqual(parameters.properties["score"].type.value, "NUMBER")
        self.assertEqual(parameters.properties["exact"].type.value, "BOOLEAN")

    def test_stream_builder_delta_parser_and_normal_parser_handle_text_thought_tools_and_usage(self) -> None:
        response = gemini_client.APIResponse(reasoning_content="thinking")
        built = gemini_client._build_stream_api_resp(
            written_buffer("answer"), [("call-1", "search", {"query": "x"})], resp=response
        )

        self.assertEqual(built.content, "answer")
        self.assertEqual(built.reasoning_content, "thinking")
        self.assertEqual(built.tool_calls[0].args, {"query": "x"})

        with self.assertRaises(EmptyResponseException):
            gemini_client._build_stream_api_resp(io.StringIO(), [])

        with self.assertRaises(RespParseException):
            gemini_client._process_delta(SimpleNamespace(candidates=[]), io.StringIO(), [])

        normal_response = SimpleNamespace(
            text="visible",
            function_calls=[SimpleNamespace(id=None, name="search", args={"query": "MaiBot"})],
            usage_metadata=SimpleNamespace(
                prompt_token_count=2,
                candidates_token_count=3,
                thoughts_token_count=4,
                total_token_count=9,
            ),
            candidates=[
                SimpleNamespace(
                    finish_reason=None,
                    content=SimpleNamespace(
                        parts=[
                            SimpleNamespace(text="thought", thought=True),
                            SimpleNamespace(text="visible", thought=False),
                        ]
                    ),
                )
            ],
        )
        parsed, usage = gemini_client._default_normal_response_parser(normal_response)

        self.assertEqual(parsed.content, "visible")
        self.assertEqual(parsed.reasoning_content, "thought")
        self.assertEqual(parsed.tool_calls[0].call_id, "gemini-tool_call")
        self.assertEqual(parsed.tool_calls[0].args, {"query": "MaiBot"})
        self.assertEqual(usage, (2, 7, 9))

    def test_clamp_thinking_budget_handles_auto_disable_bounds_unknown_and_invalid_values(self) -> None:
        self.assertEqual(gemini_client.GeminiClient.clamp_thinking_budget(None, "gemini-2.5-flash"), -1)
        self.assertEqual(
            gemini_client.GeminiClient.clamp_thinking_budget({"thinking_budget": 0}, "gemini-2.5-flash"),
            0,
        )
        self.assertEqual(
            gemini_client.GeminiClient.clamp_thinking_budget({"thinking_budget": 0}, "gemini-2.5-pro"),
            128,
        )
        self.assertEqual(
            gemini_client.GeminiClient.clamp_thinking_budget({"thinking_budget": 1}, "gemini-2.5-flash-lite-001"),
            512,
        )
        self.assertEqual(
            gemini_client.GeminiClient.clamp_thinking_budget({"thinking_budget": 999999}, "gemini-2.5-flash"),
            24576,
        )
        self.assertEqual(
            gemini_client.GeminiClient.clamp_thinking_budget({"thinking_budget": 100}, "unknown-model"),
            -1,
        )
        self.assertEqual(
            gemini_client.GeminiClient.clamp_thinking_budget({"thinking_budget": "bad"}, "gemini-2.5-flash"),
            -1,
        )

    def test_support_image_formats_are_declared_without_client_initialization(self) -> None:
        client = gemini_client.GeminiClient.__new__(gemini_client.GeminiClient)

        self.assertEqual(client.get_support_image_formats(), ["png", "jpg", "jpeg", "webp", "heic", "heif"])


if __name__ == "__main__":
    unittest.main()
