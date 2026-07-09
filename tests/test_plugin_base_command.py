import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.common.data_models.message_data_model import ReplyContentType
from src.plugin_system.base import base_command
from src.plugin_system.base.base_command import BaseCommand


class ConcreteCommand(BaseCommand):
    command_name = "sample"
    command_description = "Sample command"
    command_pattern = r"^/sample$"

    async def execute(self):
        return True, "ok", 0


def make_command(stream_id: str | None = "stream-1", *, plugin_config: dict | None = None) -> ConcreteCommand:
    chat_stream = SimpleNamespace(stream_id=stream_id) if stream_id is not None else None
    return ConcreteCommand(message=SimpleNamespace(chat_stream=chat_stream), plugin_config=plugin_config)


class BaseCommandLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_base_execute_default_and_empty_config_lookup_are_stable(self) -> None:
        command = make_command(plugin_config=None)

        self.assertIsNone(await BaseCommand.execute(command))
        self.assertEqual(command.get_config("section.value", default="fallback"), "fallback")


class BaseCommandSendWrapperTest(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_chat_stream_returns_false_without_calling_send_api(self) -> None:
        command = make_command(stream_id=None)

        with (
            patch.object(base_command.send_api, "image_to_stream", new=AsyncMock()) as image_to_stream,
            patch.object(base_command.send_api, "emoji_to_stream", new=AsyncMock()) as emoji_to_stream,
            patch.object(base_command.send_api, "custom_to_stream", new=AsyncMock()) as custom_to_stream,
            patch.object(base_command.send_api, "custom_reply_set_to_stream", new=AsyncMock()) as reply_set_to_stream,
        ):
            self.assertFalse(await command.send_image("image64"))
            self.assertFalse(await command.send_emoji("emoji64"))
            self.assertFalse(await command.send_voice("voice64"))
            self.assertFalse(await command.send_hybrid([(ReplyContentType.TEXT, "hello")]))
            self.assertFalse(await command.send_forward(["message-id"]))
            self.assertFalse(await command.send_custom("notice", {"payload": 1}))

        image_to_stream.assert_not_awaited()
        emoji_to_stream.assert_not_awaited()
        custom_to_stream.assert_not_awaited()
        reply_set_to_stream.assert_not_awaited()

    async def test_emoji_voice_and_custom_wrappers_delegate_to_send_api(self) -> None:
        command = make_command()
        reply_message = object()

        with (
            patch.object(base_command.send_api, "emoji_to_stream", new=AsyncMock(return_value=True)) as emoji_to_stream,
            patch.object(
                base_command.send_api, "custom_to_stream", new=AsyncMock(return_value=True)
            ) as custom_to_stream,
        ):
            self.assertTrue(
                await command.send_emoji("emoji64", set_reply=True, reply_message=reply_message, storage_message=False)
            )
            self.assertTrue(await command.send_voice("voice64"))
            self.assertTrue(
                await command.send_custom(
                    "notice",
                    {"payload": 1},
                    display_message="visible",
                    typing=True,
                    set_reply=True,
                    reply_message=reply_message,
                    storage_message=False,
                )
            )

        emoji_to_stream.assert_awaited_once_with("emoji64", "stream-1", set_reply=True, reply_message=reply_message)
        self.assertEqual(
            custom_to_stream.await_args_list[0].kwargs,
            {
                "message_type": "voice",
                "content": "voice64",
                "stream_id": "stream-1",
                "typing": False,
                "set_reply": False,
                "reply_message": None,
                "storage_message": False,
            },
        )
        self.assertEqual(
            custom_to_stream.await_args_list[1].kwargs,
            {
                "message_type": "notice",
                "content": {"payload": 1},
                "stream_id": "stream-1",
                "display_message": "visible",
                "typing": True,
                "set_reply": True,
                "reply_message": reply_message,
                "storage_message": False,
            },
        )

    async def test_send_command_reports_false_for_send_failures_and_exceptions(self) -> None:
        command = make_command()

        with patch.object(base_command.send_api, "command_to_stream", new=AsyncMock(return_value=False)) as send:
            self.assertFalse(await command.send_command("ping", args={"x": 1}, display_message="/ping"))
        send.assert_awaited_once_with(
            command={"name": "ping", "args": {"x": 1}},
            stream_id="stream-1",
            storage_message=True,
            display_message="/ping",
        )

        with patch.object(base_command.send_api, "command_to_stream", new=AsyncMock(side_effect=RuntimeError("boom"))):
            self.assertFalse(await command.send_command("boom"))

    async def test_hybrid_wrapper_builds_reply_set_and_forwards_options(self) -> None:
        command = make_command()
        reply_message = object()

        with patch.object(
            base_command.send_api, "custom_reply_set_to_stream", new=AsyncMock(return_value=True)
        ) as reply_set_to_stream:
            self.assertTrue(
                await command.send_hybrid(
                    [(ReplyContentType.TEXT, "hello"), ("image", "image64")],
                    typing=True,
                    set_reply=True,
                    reply_message=reply_message,
                    storage_message=False,
                )
            )

        reply_set = reply_set_to_stream.await_args.kwargs["reply_set"]
        hybrid_content = reply_set.reply_data[0]
        self.assertEqual(hybrid_content.content_type, ReplyContentType.HYBRID)
        self.assertEqual(
            [(item.content_type, item.content) for item in hybrid_content.content],
            [(ReplyContentType.TEXT, "hello"), ("image", "image64")],
        )
        reply_set_to_stream.assert_awaited_once_with(
            reply_set=reply_set,
            stream_id="stream-1",
            typing=True,
            set_reply=True,
            reply_message=reply_message,
            storage_message=False,
        )

    async def test_forward_wrapper_builds_reference_and_created_nodes_and_skips_invalid_items(self) -> None:
        command = make_command()

        with patch.object(
            base_command.send_api, "custom_reply_set_to_stream", new=AsyncMock(return_value=True)
        ) as reply_set_to_stream:
            self.assertTrue(
                await command.send_forward(
                    [
                        "message-id",
                        ("user-1", "Alice", [(ReplyContentType.TEXT, "hello"), ("emoji", "emoji64")]),
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
            [(ReplyContentType.TEXT, "hello"), ("emoji", "emoji64")],
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
