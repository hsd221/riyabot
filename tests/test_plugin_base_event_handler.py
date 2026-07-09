import unittest
from unittest.mock import AsyncMock, patch

from src.common.data_models.message_data_model import ReplyContentType
from src.plugin_system.base import base_events_handler
from src.plugin_system.base.base_events_handler import BaseEventHandler
from src.plugin_system.base.component_types import EventType


class ConcreteEventHandler(BaseEventHandler):
    event_type: EventType | str = "custom_test_event"
    handler_name = "helper"
    handler_description = "Helper event handler"
    weight = 5
    intercept_message = True

    async def execute(self, message):
        return True, True, "ok", None, message


class DefaultNameEventHandler(BaseEventHandler):
    event_type: EventType | str = EventType.ON_MESSAGE
    handler_description = "Default name handler"

    async def execute(self, message):
        return True, True, None, None, message


class DotNameEventHandler(BaseEventHandler):
    event_type: EventType | str = EventType.ON_MESSAGE
    handler_name = "bad.name"

    async def execute(self, message):
        return True, True, None, None, message


class MissingEventTypeHandler(BaseEventHandler):
    async def execute(self, message):
        return True, True, None, None, message


class BaseEventHandlerLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_event_type_and_base_execute_are_explicit_errors(self) -> None:
        with self.assertRaisesRegex(NotImplementedError, "必须指定 event_type"):
            MissingEventTypeHandler()

        handler = ConcreteEventHandler()
        with self.assertRaisesRegex(NotImplementedError, "子类必须实现 execute"):
            await BaseEventHandler.execute(handler, None)

    def test_config_lookup_supports_empty_missing_nested_and_leaf_values(self) -> None:
        handler = ConcreteEventHandler()

        self.assertEqual(handler.get_config("section.enabled", default="fallback"), "fallback")

        handler.set_plugin_name("plugin-a")
        handler.set_plugin_config({"section": {"enabled": False, "limit": 0}, "leaf": "value"})

        self.assertEqual(handler.plugin_name, "plugin-a")
        self.assertFalse(handler.get_config("section.enabled", default=True))
        self.assertEqual(handler.get_config("section.limit", default=10), 0)
        self.assertEqual(handler.get_config("leaf", default="fallback"), "value")
        self.assertEqual(handler.get_config("leaf.child", default="fallback"), "fallback")
        self.assertEqual(handler.get_config("missing", default="fallback"), "fallback")

    def test_handler_info_uses_explicit_or_default_names_and_rejects_dotted_names(self) -> None:
        explicit_info = ConcreteEventHandler.get_handler_info()
        default_info = DefaultNameEventHandler.get_handler_info()

        self.assertEqual(explicit_info.name, "helper")
        self.assertEqual(explicit_info.description, "Helper event handler")
        self.assertEqual(explicit_info.event_type, "custom_test_event")
        self.assertEqual(explicit_info.weight, 5)
        self.assertTrue(explicit_info.intercept_message)
        self.assertEqual(default_info.name, "")
        self.assertEqual(default_info.description, "Default name handler")

        with self.assertRaisesRegex(ValueError, "包含非法字符"):
            DotNameEventHandler.get_handler_info()


class BaseEventHandlerSendWrapperTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_wrappers_return_false_without_stream_id_and_do_not_call_send_api(self) -> None:
        handler = ConcreteEventHandler()

        with (
            patch.object(base_events_handler.send_api, "text_to_stream", new=AsyncMock()) as text_to_stream,
            patch.object(base_events_handler.send_api, "emoji_to_stream", new=AsyncMock()) as emoji_to_stream,
            patch.object(base_events_handler.send_api, "image_to_stream", new=AsyncMock()) as image_to_stream,
            patch.object(base_events_handler.send_api, "command_to_stream", new=AsyncMock()) as command_to_stream,
            patch.object(base_events_handler.send_api, "custom_to_stream", new=AsyncMock()) as custom_to_stream,
            patch.object(
                base_events_handler.send_api, "custom_reply_set_to_stream", new=AsyncMock()
            ) as reply_set_to_stream,
        ):
            self.assertFalse(await handler.send_text("", "hello"))
            self.assertFalse(await handler.send_emoji("", "emoji64"))
            self.assertFalse(await handler.send_image("", "image64"))
            self.assertFalse(await handler.send_voice("", "voice64"))
            self.assertFalse(await handler.send_command("", "ping"))
            self.assertFalse(await handler.send_custom("", "notice", {"payload": 1}))
            self.assertFalse(await handler.send_hybrid("", [(ReplyContentType.TEXT, "hello")]))
            self.assertFalse(await handler.send_forward("", ["message-id"]))

        text_to_stream.assert_not_awaited()
        emoji_to_stream.assert_not_awaited()
        image_to_stream.assert_not_awaited()
        command_to_stream.assert_not_awaited()
        custom_to_stream.assert_not_awaited()
        reply_set_to_stream.assert_not_awaited()

    async def test_simple_send_wrappers_delegate_all_options_to_send_api(self) -> None:
        handler = ConcreteEventHandler()
        reply_message = object()

        with (
            patch.object(
                base_events_handler.send_api, "text_to_stream", new=AsyncMock(return_value=True)
            ) as text_to_stream,
            patch.object(
                base_events_handler.send_api, "emoji_to_stream", new=AsyncMock(return_value=True)
            ) as emoji_to_stream,
            patch.object(
                base_events_handler.send_api, "image_to_stream", new=AsyncMock(return_value=True)
            ) as image_to_stream,
            patch.object(
                base_events_handler.send_api, "command_to_stream", new=AsyncMock(return_value=True)
            ) as command_to_stream,
            patch.object(
                base_events_handler.send_api, "custom_to_stream", new=AsyncMock(return_value=True)
            ) as custom_to_stream,
        ):
            self.assertTrue(
                await handler.send_text(
                    "stream-1",
                    "hello",
                    set_reply=True,
                    reply_message=reply_message,
                    typing=True,
                    storage_message=False,
                )
            )
            self.assertTrue(
                await handler.send_emoji(
                    "stream-1", "emoji64", set_reply=True, reply_message=reply_message, storage_message=False
                )
            )
            self.assertTrue(
                await handler.send_image(
                    "stream-1", "image64", set_reply=True, reply_message=reply_message, storage_message=False
                )
            )
            self.assertTrue(
                await handler.send_command(
                    "stream-1", "ping", command_args={"x": 1}, display_message="/ping", storage_message=False
                )
            )
            self.assertTrue(
                await handler.send_custom(
                    "stream-1",
                    "notice",
                    {"payload": 1},
                    typing=True,
                    set_reply=True,
                    reply_message=reply_message,
                    storage_message=False,
                )
            )

        text_to_stream.assert_awaited_once_with(
            text="hello",
            stream_id="stream-1",
            set_reply=True,
            reply_message=reply_message,
            typing=True,
            storage_message=False,
        )
        emoji_to_stream.assert_awaited_once_with(
            emoji_base64="emoji64",
            stream_id="stream-1",
            set_reply=True,
            reply_message=reply_message,
            storage_message=False,
        )
        image_to_stream.assert_awaited_once_with(
            image_base64="image64",
            stream_id="stream-1",
            set_reply=True,
            reply_message=reply_message,
            storage_message=False,
        )
        command_to_stream.assert_awaited_once_with(
            command={"name": "ping", "args": {"x": 1}},
            stream_id="stream-1",
            storage_message=False,
            display_message="/ping",
        )
        custom_to_stream.assert_awaited_once_with(
            message_type="notice",
            content={"payload": 1},
            stream_id="stream-1",
            typing=True,
            set_reply=True,
            reply_message=reply_message,
            storage_message=False,
        )

    async def test_voice_and_hybrid_wrappers_build_reply_sets_before_sending(self) -> None:
        handler = ConcreteEventHandler()
        reply_message = object()

        with patch.object(
            base_events_handler.send_api, "custom_reply_set_to_stream", new=AsyncMock(return_value=True)
        ) as reply_set_to_stream:
            self.assertTrue(await handler.send_voice("stream-1", "voice64"))
            self.assertTrue(
                await handler.send_hybrid(
                    "stream-1",
                    [(ReplyContentType.TEXT, "hello"), ("emoji", "emoji64")],
                    typing=True,
                    set_reply=True,
                    reply_message=reply_message,
                    storage_message=False,
                )
            )

        voice_reply_set = reply_set_to_stream.await_args_list[0].kwargs["reply_set"]
        self.assertEqual(voice_reply_set.reply_data[0].content_type, ReplyContentType.VOICE)
        self.assertEqual(voice_reply_set.reply_data[0].content, "voice64")
        self.assertEqual(
            reply_set_to_stream.await_args_list[0].kwargs,
            {"reply_set": voice_reply_set, "stream_id": "stream-1", "storage_message": False},
        )

        hybrid_reply_set = reply_set_to_stream.await_args_list[1].kwargs["reply_set"]
        hybrid_content = hybrid_reply_set.reply_data[0]
        self.assertEqual(hybrid_content.content_type, ReplyContentType.HYBRID)
        self.assertEqual(
            [(item.content_type, item.content) for item in hybrid_content.content],
            [(ReplyContentType.TEXT, "hello"), ("emoji", "emoji64")],
        )
        self.assertEqual(
            reply_set_to_stream.await_args_list[1].kwargs,
            {
                "reply_set": hybrid_reply_set,
                "stream_id": "stream-1",
                "typing": True,
                "set_reply": True,
                "reply_message": reply_message,
                "storage_message": False,
            },
        )

    async def test_forward_wrapper_builds_reference_and_created_nodes_and_skips_invalid_items(self) -> None:
        handler = ConcreteEventHandler()

        with patch.object(
            base_events_handler.send_api, "custom_reply_set_to_stream", new=AsyncMock(return_value=True)
        ) as reply_set_to_stream:
            self.assertTrue(
                await handler.send_forward(
                    "stream-1",
                    [
                        "message-id",
                        ("user-1", "Alice", [(ReplyContentType.TEXT, "hello"), ("image", "image64")]),
                        {"bad": "shape"},
                    ],
                    storage_message=False,
                )
            )

        reply_set = reply_set_to_stream.await_args.kwargs["reply_set"]
        forward_content = reply_set.reply_data[0]
        self.assertEqual(forward_content.content_type, ReplyContentType.FORWARD)
        self.assertEqual(len(forward_content.content), 2)

        id_reference, created_node = forward_content.content
        self.assertEqual(id_reference.user_id, "")
        self.assertEqual(id_reference.user_nickname, "")
        self.assertEqual(id_reference.content, "message-id")
        self.assertEqual(created_node.user_id, "user-1")
        self.assertEqual(created_node.user_nickname, "Alice")
        self.assertEqual(
            [(item.content_type, item.content) for item in created_node.content],
            [(ReplyContentType.TEXT, "hello"), ("image", "image64")],
        )
        reply_set_to_stream.assert_awaited_once_with(
            reply_set=reply_set,
            stream_id="stream-1",
            storage_message=False,
            set_reply=False,
            reply_message=None,
        )


if __name__ == "__main__":
    unittest.main()
