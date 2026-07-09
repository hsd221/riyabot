import unittest

from pydantic import BaseModel

from src.config.api_ada_configs import APIProvider, ModelInfo
from src.llm_models.model_client.base_client import APIResponse, BaseClient, ClientRegistry, UsageRecord
from src.llm_models.payload_content.message import MessageBuilder, RoleType
from src.llm_models.payload_content.resp_format import RespFormat, RespFormatType
from src.llm_models.payload_content.tool_option import ToolCall, ToolOptionBuilder, ToolParamType


class FakeClient(BaseClient):
    async def get_response(self, model_info, message_list, **kwargs):
        return APIResponse(content=f"{model_info.name}:{len(message_list)}")

    async def get_embedding(self, model_info, embedding_input, extra_params=None):
        return APIResponse(embedding=[1.0, 2.0], raw_data={"input": embedding_input})

    async def get_audio_transcriptions(self, model_info, audio_base64, max_tokens=None, extra_params=None):
        return APIResponse(content="transcript", raw_data={"audio": audio_base64})

    def get_support_image_formats(self):
        return ["png"]


class ToolOptionBuilderTest(unittest.TestCase):
    def test_builder_requires_name_description_and_preserves_param_metadata(self) -> None:
        option = (
            ToolOptionBuilder()
            .set_name("search")
            .set_description("Search documents")
            .add_param(
                "query",
                ToolParamType.STRING,
                "Search query",
                required=True,
                enum_values=["docs", "web"],
            )
            .build()
        )

        self.assertEqual(option.name, "search")
        self.assertEqual(option.description, "Search documents")
        self.assertEqual(len(option.params), 1)
        self.assertEqual(option.params[0].name, "query")
        self.assertEqual(option.params[0].param_type, ToolParamType.STRING)
        self.assertTrue(option.params[0].required)
        self.assertEqual(option.params[0].enum_values, ["docs", "web"])

        with self.assertRaisesRegex(ValueError, "工具名称不能为空"):
            ToolOptionBuilder().set_name("")
        with self.assertRaisesRegex(ValueError, "工具名称/描述不能为空"):
            ToolOptionBuilder().set_name("search").build()
        with self.assertRaisesRegex(ValueError, "参数名称/描述不能为空"):
            ToolOptionBuilder().set_name("search").set_description("desc").add_param(
                "",
                ToolParamType.STRING,
                "desc",
            )

    def test_builder_without_params_returns_none_params(self) -> None:
        option = ToolOptionBuilder().set_name("ping").set_description("Ping").build()

        self.assertIsNone(option.params)


class MessageBuilderTest(unittest.TestCase):
    def test_text_only_message_collapses_single_string_content(self) -> None:
        message = MessageBuilder().set_role(RoleType.System).add_text_content("be concise").build()

        self.assertEqual(message.role, RoleType.System)
        self.assertEqual(message.content, "be concise")
        self.assertIn("Role: RoleType.System", str(message))

    def test_multimodal_message_keeps_ordered_content_list_and_validates_images(self) -> None:
        message = (
            MessageBuilder()
            .set_role(RoleType.User)
            .add_text_content("look")
            .add_image_content("PNG", "base64-image")
            .build()
        )

        self.assertEqual(message.content, ["look", ("PNG", "base64-image")])
        with self.assertRaisesRegex(ValueError, "不受支持的图片格式"):
            MessageBuilder().add_image_content("bmp", "base64-image")
        with self.assertRaisesRegex(ValueError, "图片的base64编码不能为空"):
            MessageBuilder().add_image_content("png", "")

    def test_tool_message_requires_tool_call_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "Tool角色的工具调用ID不能为空"):
            MessageBuilder().set_role(RoleType.Tool).add_text_content("tool result").build()

        message = (
            MessageBuilder().set_role(RoleType.Tool).add_text_content("tool result").add_tool_call("call-1").build()
        )

        self.assertEqual(message.tool_call_id, "call-1")
        with self.assertRaisesRegex(ValueError, "仅当角色为Tool时才能添加工具调用ID"):
            MessageBuilder().set_role(RoleType.User).add_tool_call("call-1")

    def test_assistant_message_can_carry_tool_calls_without_content(self) -> None:
        tool_call = ToolCall("call-1", "search", {"query": "MaiBot"})
        message = MessageBuilder().set_role(RoleType.Assistant).set_tool_calls([tool_call]).build()

        self.assertEqual(message.content, [])
        self.assertEqual(message.tool_calls, [tool_call])
        with self.assertRaisesRegex(ValueError, "仅当角色为Assistant时才能设置工具调用列表"):
            MessageBuilder().set_role(RoleType.User).set_tool_calls([tool_call])
        with self.assertRaisesRegex(ValueError, "工具调用列表不能为空"):
            MessageBuilder().set_role(RoleType.Assistant).set_tool_calls([])

    def test_empty_non_tool_message_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "内容不能为空"):
            MessageBuilder().set_role(RoleType.User).build()


class RespFormatTest(unittest.TestCase):
    def test_text_and_json_object_formats_serialize_without_schema(self) -> None:
        self.assertEqual(RespFormat().to_dict(), {"format_type": "text"})
        self.assertEqual(RespFormat(RespFormatType.JSON_OBJ).to_dict(), {"format_type": "json_object"})

    def test_json_schema_dict_is_validated_and_preserved(self) -> None:
        schema = {
            "name": "reply_schema",
            "description": "Reply schema",
            "schema": {"type": "object", "properties": {"reply": {"type": "string"}}},
            "strict": True,
        }
        response_format = RespFormat(RespFormatType.JSON_SCHEMA, schema=schema)

        self.assertEqual(response_format.to_dict(), {"format_type": "json_schema", "schema": schema})

        invalid_cases = [
            ({}, "schema必须包含'name'字段"),
            ({"name": "", "schema": {}}, "schema的'name'字段必须是非空字符串"),
            ({"name": "x", "description": "", "schema": {}}, "schema的'description'字段只能填入非空字符串"),
            ({"name": "x"}, "schema必须包含'schema'字段"),
            ({"name": "x", "schema": []}, "schema的'schema'字段必须是字典"),
            ({"name": "x", "schema": {}, "strict": "yes"}, "schema的'strict'字段只能填入布尔值"),
        ]
        for invalid_schema, message in invalid_cases:
            with self.subTest(invalid_schema=invalid_schema):
                with self.assertRaisesRegex(ValueError, message):
                    RespFormat(RespFormatType.JSON_SCHEMA, schema=invalid_schema)

    def test_json_schema_can_be_generated_from_pydantic_model_without_titles_or_defs(self) -> None:
        class InnerModel(BaseModel):
            value: int

        class OuterModel(BaseModel):
            """Outer response."""

            item: InnerModel
            label: str

        response_format = RespFormat(RespFormatType.JSON_SCHEMA, schema=OuterModel).to_dict()
        schema = response_format["schema"]["schema"]

        self.assertEqual(response_format["format_type"], "json_schema")
        self.assertEqual(response_format["schema"]["name"], "OuterModel")
        self.assertEqual(response_format["schema"]["description"], "Outer response.")
        self.assertNotIn("title", str(schema))
        self.assertNotIn("$defs", str(schema))
        self.assertEqual(schema["properties"]["item"]["type"], "object")
        self.assertEqual(schema["properties"]["item"]["properties"]["value"]["type"], "integer")

    def test_json_schema_requires_schema_for_schema_format(self) -> None:
        with self.assertRaisesRegex(ValueError, "schema不能为空"):
            RespFormat(RespFormatType.JSON_SCHEMA)


class BaseClientRegistryTest(unittest.IsolatedAsyncioTestCase):
    async def test_api_response_and_usage_record_are_plain_data_containers(self) -> None:
        tool_call = ToolCall("call-1", "search", {"query": "x"})
        usage = UsageRecord("model-a", "provider-a", prompt_tokens=3, completion_tokens=4, total_tokens=7)
        response = APIResponse(
            content="ok", tool_calls=[tool_call], embedding=[0.1], usage=usage, raw_data={"id": "r1"}
        )

        self.assertEqual(response.content, "ok")
        self.assertEqual(response.tool_calls[0].func_name, "search")
        self.assertEqual(response.embedding, [0.1])
        self.assertEqual(response.usage.total_tokens, 7)
        self.assertEqual(response.raw_data, {"id": "r1"})

    async def test_client_registry_registers_caches_forces_new_and_reports_unknown_types(self) -> None:
        registry = ClientRegistry()
        provider = APIProvider(
            name="fake-provider",
            base_url="https://api.example.test",
            api_key="secret",
            client_type="fake",
        )
        model = ModelInfo(model_identifier="fake-model", name="fake-model", api_provider="fake-provider")

        returned_class = registry.register_client_class("fake")(FakeClient)
        first = registry.get_client_class_instance(provider)
        second = registry.get_client_class_instance(provider)
        forced = registry.get_client_class_instance(provider, force_new=True)
        response = await first.get_response(model, [MessageBuilder().add_text_content("hello").build()])

        self.assertIs(returned_class, FakeClient)
        self.assertIs(first, second)
        self.assertIsNot(first, forced)
        self.assertEqual(response.content, "fake-model:1")

        unknown_provider = APIProvider(
            name="unknown-provider",
            base_url="https://api.example.test",
            api_key="secret",
            client_type="unknown",
        )
        with self.assertRaisesRegex(KeyError, "'unknown' 类型的 Client 未注册"):
            registry.get_client_class_instance(unknown_provider)
        with self.assertRaises(TypeError):
            registry.register_client_class("bad")(object)


if __name__ == "__main__":
    unittest.main()
