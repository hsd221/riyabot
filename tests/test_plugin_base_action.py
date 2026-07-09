import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.common.data_models.message_data_model import ReplyContentType
from src.plugin_system.base import base_action
from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.component_types import ActionActivationType


class ConcreteAction(BaseAction):
    action_name = "sample"
    action_description = "Sample action"
    activation_type = ActionActivationType.ALWAYS
    activation_keywords = ["hello"]
    action_parameters = {"text": "str"}
    action_require = ["text"]
    associated_types = ["text"]

    async def execute(self):
        return True, "ok"


def make_chat_stream(stream_id: str = "stream-1"):
    return SimpleNamespace(stream_id=stream_id, platform="qq")


def make_action_message(*, group: bool = True):
    group_info = SimpleNamespace(group_id="group-1", group_name="Group") if group else None
    return SimpleNamespace(
        chat_info=SimpleNamespace(group_info=group_info),
        user_info=SimpleNamespace(user_id="user-1", user_nickname="Alice"),
    )


def make_action(*, stream_id: str = "stream-1", plugin_config: dict | None = None) -> ConcreteAction:
    return ConcreteAction(
        action_data={"loop_start_time": 100.0},
        action_reasoning="because",
        cycle_timers={},
        thinking_id="thinking-1",
        chat_stream=make_chat_stream(stream_id),
        plugin_config=plugin_config,
        action_message=make_action_message(),
    )


class BaseActionLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_base_execute_default_and_empty_config_lookup_are_stable(self) -> None:
        action = make_action(plugin_config=None)

        self.assertIsNone(await BaseAction.execute(action))
        self.assertEqual(action.get_config("section.value", default="fallback"), "fallback")


class BaseActionSendWrapperTest(unittest.IsolatedAsyncioTestCase):
    async def test_media_and_command_wrappers_delegate_all_options(self) -> None:
        action = make_action(plugin_config={"section": {"value": 3}})
        reply_message = object()

        with (
            patch.object(base_action.send_api, "emoji_to_stream", new=AsyncMock(return_value=True)) as emoji_to_stream,
            patch.object(base_action.send_api, "image_to_stream", new=AsyncMock(return_value=True)) as image_to_stream,
            patch.object(
                base_action.send_api, "command_to_stream", new=AsyncMock(return_value=True)
            ) as command_to_stream,
        ):
            self.assertTrue(
                await action.send_emoji("emoji64", set_reply=True, reply_message=reply_message, storage_message=False)
            )
            self.assertTrue(
                await action.send_image("image64", set_reply=True, reply_message=reply_message, storage_message=False)
            )
            self.assertTrue(
                await action.send_command("ping", args={"x": 1}, display_message="/ping", storage_message=False)
            )

        self.assertEqual(action.get_config("section.value"), 3)
        emoji_to_stream.assert_awaited_once_with(
            "emoji64", "stream-1", set_reply=True, reply_message=reply_message, storage_message=False
        )
        image_to_stream.assert_awaited_once_with(
            "image64", "stream-1", set_reply=True, reply_message=reply_message, storage_message=False
        )
        command_to_stream.assert_awaited_once_with(
            command={"name": "ping", "args": {"x": 1}},
            stream_id="stream-1",
            storage_message=False,
            display_message="/ping",
        )

    async def test_missing_chat_id_short_circuits_send_wrappers_without_calling_send_api(self) -> None:
        action = make_action(stream_id="")

        with (
            patch.object(base_action.send_api, "emoji_to_stream", new=AsyncMock()) as emoji_to_stream,
            patch.object(base_action.send_api, "image_to_stream", new=AsyncMock()) as image_to_stream,
            patch.object(base_action.send_api, "command_to_stream", new=AsyncMock()) as command_to_stream,
            patch.object(base_action.send_api, "custom_to_stream", new=AsyncMock()) as custom_to_stream,
            patch.object(base_action.send_api, "custom_reply_set_to_stream", new=AsyncMock()) as reply_set_to_stream,
        ):
            self.assertFalse(await action.send_emoji("emoji64"))
            self.assertFalse(await action.send_image("image64"))
            self.assertFalse(await action.send_command("ping"))
            self.assertFalse(await action.send_custom("notice", {"payload": 1}))
            self.assertFalse(await action.send_hybrid([(ReplyContentType.TEXT, "hello")]))
            self.assertFalse(await action.send_forward(["message-id"]))

        emoji_to_stream.assert_not_awaited()
        image_to_stream.assert_not_awaited()
        command_to_stream.assert_not_awaited()
        custom_to_stream.assert_not_awaited()
        reply_set_to_stream.assert_not_awaited()

    async def test_hybrid_forward_and_voice_wrappers_build_reply_sets(self) -> None:
        action = make_action()
        reply_message = object()

        with patch.object(
            base_action.send_api, "custom_reply_set_to_stream", new=AsyncMock(return_value=True)
        ) as reply_set_to_stream:
            self.assertTrue(
                await action.send_hybrid(
                    [(ReplyContentType.TEXT, "hello"), ("image", "image64")],
                    typing=True,
                    set_reply=True,
                    reply_message=reply_message,
                    storage_message=False,
                )
            )
            self.assertTrue(
                await action.send_forward(
                    [
                        "message-id",
                        ("user-1", "Alice", [(ReplyContentType.TEXT, "hello"), ("emoji", "emoji64")]),
                        {"bad": "shape"},
                    ],
                    storage_message=False,
                )
            )
            self.assertTrue(await action.send_voice("voice64"))

        hybrid_reply_set = reply_set_to_stream.await_args_list[0].kwargs["reply_set"]
        hybrid_content = hybrid_reply_set.reply_data[0]
        self.assertEqual(hybrid_content.content_type, ReplyContentType.HYBRID)
        self.assertEqual(
            [(item.content_type, item.content) for item in hybrid_content.content],
            [(ReplyContentType.TEXT, "hello"), ("image", "image64")],
        )
        self.assertEqual(
            reply_set_to_stream.await_args_list[0].kwargs,
            {
                "reply_set": hybrid_reply_set,
                "stream_id": "stream-1",
                "typing": True,
                "set_reply": True,
                "reply_message": reply_message,
                "storage_message": False,
            },
        )

        forward_reply_set = reply_set_to_stream.await_args_list[1].kwargs["reply_set"]
        forward_content = forward_reply_set.reply_data[0]
        self.assertEqual(forward_content.content_type, ReplyContentType.FORWARD)
        self.assertEqual(len(forward_content.content), 2)
        id_reference, created_node = forward_content.content
        self.assertEqual(id_reference.content, "message-id")
        self.assertEqual(created_node.user_id, "user-1")
        self.assertEqual(
            [(item.content_type, item.content) for item in created_node.content],
            [(ReplyContentType.TEXT, "hello"), ("emoji", "emoji64")],
        )
        self.assertEqual(
            reply_set_to_stream.await_args_list[1].kwargs,
            {
                "reply_set": forward_reply_set,
                "stream_id": "stream-1",
                "storage_message": False,
                "set_reply": False,
                "reply_message": None,
            },
        )

        voice_reply_set = reply_set_to_stream.await_args_list[2].kwargs["reply_set"]
        self.assertEqual(voice_reply_set.reply_data[0].content_type, ReplyContentType.VOICE)
        self.assertEqual(voice_reply_set.reply_data[0].content, "voice64")
        self.assertEqual(
            reply_set_to_stream.await_args_list[2].kwargs,
            {"reply_set": voice_reply_set, "stream_id": "stream-1", "storage_message": False},
        )


class BaseActionWaitForNewMessageTest(unittest.IsolatedAsyncioTestCase):
    async def test_wait_for_new_message_requires_chat_id(self) -> None:
        action = make_action(stream_id="")

        self.assertEqual(await action.wait_for_new_message(timeout=1), (False, "没有有效的chat_id"))

    async def test_wait_for_new_message_returns_timeout_after_polling(self) -> None:
        action = make_action()
        loop_times = iter([0.0, 15.0, 16.0])
        sleep_calls: list[float] = []

        async def fake_sleep(delay):
            sleep_calls.append(delay)

        with (
            patch.object(
                base_action.asyncio, "get_event_loop", return_value=SimpleNamespace(time=lambda: next(loop_times))
            ),
            patch.object(base_action.message_api, "count_new_messages", return_value=0) as count_new_messages,
            patch.object(base_action.asyncio, "sleep", side_effect=fake_sleep),
        ):
            self.assertEqual(await action.wait_for_new_message(timeout=15), (False, ""))

        self.assertEqual(sleep_calls, [0.5])
        self.assertEqual(count_new_messages.call_count, 2)
        self.assertEqual(
            [call.kwargs["start_time"] for call in count_new_messages.call_args_list],
            [100.0, 100.0],
        )

    async def test_wait_for_new_message_handles_cancellation_and_count_errors(self) -> None:
        action = make_action()

        with patch.object(base_action.message_api, "count_new_messages", side_effect=asyncio.CancelledError):
            self.assertEqual(await action.wait_for_new_message(timeout=1), (False, ""))

        with patch.object(base_action.message_api, "count_new_messages", side_effect=RuntimeError("counter down")):
            self.assertEqual(await action.wait_for_new_message(timeout=1), (False, "等待新消息失败: counter down"))


if __name__ == "__main__":
    unittest.main()
