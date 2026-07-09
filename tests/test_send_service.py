import unittest
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from maim_message import GroupInfo, Seg, UserInfo

from src.chat.message_receive.chat_stream import ChatStream
from src.common.data_models.database_data_model import DatabaseMessages
from src.common.data_models.message_component_model import MessageComponentSequence, TextComponent
from src.services import send_service


class FakeChatManager:
    def __init__(self, stream=None):
        self.stream = stream
        self.requested_stream_ids = []

    def get_stream(self, stream_id: str):
        self.requested_stream_ids.append(stream_id)
        return self.stream


class SendServiceTestCase(unittest.IsolatedAsyncioTestCase):
    def make_stream(self) -> ChatStream:
        return ChatStream(
            stream_id="stream-1",
            platform="qq",
            user_info=UserInfo(platform="qq", user_id="sender", user_nickname="Sender"),
            group_info=GroupInfo(platform="qq", group_id="group-1", group_name="Group"),
        )

    def make_db_message(self, *, additional_config='{"at_bot": true}') -> DatabaseMessages:
        return DatabaseMessages(
            message_id="reply-1",
            time=12.5,
            processed_plain_text="quoted text",
            additional_config=additional_config,
            user_id="user-1",
            user_nickname="Alice",
            user_cardname="Ali",
            user_platform="qq",
            chat_info_group_id="group-1",
            chat_info_group_name="Group",
            chat_info_group_platform="qq",
            chat_info_user_id="user-1",
            chat_info_user_nickname="Alice",
            chat_info_user_platform="qq",
            chat_info_stream_id="stream-1",
            chat_info_platform="qq",
        )

    def patch_runtime(self, stream=None):
        bot = SimpleNamespace(qq_account="bot-id", nickname="Mai")
        return (
            patch.object(send_service, "get_chat_manager", return_value=FakeChatManager(stream)),
            patch.object(send_service.global_config, "bot", bot),
        )

    def test_normalize_additional_config_accepts_mappings_json_and_ignores_invalid_values(self) -> None:
        self.assertEqual(send_service._normalize_additional_config({"x": 1}), {"x": 1})
        self.assertEqual(send_service._normalize_additional_config('{"x": 1}'), {"x": 1})
        self.assertEqual(send_service._normalize_additional_config("[1, 2]"), {})
        self.assertEqual(send_service._normalize_additional_config("{bad json"), {})
        self.assertEqual(send_service._normalize_additional_config(None), {})

    def test_db_message_to_message_recv_rebuilds_anchor_metadata_and_plain_text_segment(self) -> None:
        message = send_service.db_message_to_message_recv(self.make_db_message())

        self.assertEqual(message.message_info.message_id, "reply-1")
        self.assertEqual(message.message_info.group_info.group_id, "group-1")
        self.assertEqual(message.message_info.user_info.user_nickname, "Alice")
        self.assertEqual(message.message_segment.type, "text")
        self.assertEqual(message.message_segment.data, "quoted text")
        self.assertEqual(message.processed_plain_text, "quoted text")
        self.assertEqual(message.message_info.additional_config, {"at_bot": True})
        self.assertTrue(message.is_mentioned)

    def test_build_message_to_stream_returns_none_for_missing_stream(self) -> None:
        manager_patch, bot_patch = self.patch_runtime(stream=None)

        with manager_patch, bot_patch:
            message = send_service.build_message_to_stream(Seg(type="text", data="hello"), "missing")

        self.assertIsNone(message)

    def test_build_message_to_stream_creates_bot_message_with_reply_anchor_and_preserved_components(self) -> None:
        stream = self.make_stream()
        manager_patch, bot_patch = self.patch_runtime(stream=stream)
        components = MessageComponentSequence([TextComponent("hello")])

        with manager_patch, bot_patch:
            message = send_service.build_message_to_stream(
                Seg(type="text", data="hello"),
                "stream-1",
                display_message="shown",
                reply_message=self.make_db_message(),
                selected_expressions=[1, 2],
                message_components=components,
            )

        self.assertIsNotNone(message)
        self.assertEqual(message.message_segment.type, "text")
        self.assertEqual(message.display_message, "shown")
        self.assertEqual(message.message_info.user_info.user_id, "bot-id")
        self.assertEqual(message.reply.message_info.message_id, "reply-1")
        self.assertIs(message.reply.chat_stream, stream)
        self.assertEqual(message.reply_to, "qq:user-1")
        self.assertEqual(message.selected_expressions, [1, 2])
        self.assertIs(message.message_components, components)
        self.assertTrue(message.preserve_message_components)

    async def test_message_to_stream_with_message_requires_reply_anchor_when_set_reply_is_true(self) -> None:
        message = await send_service.message_to_stream_with_message(
            Seg(type="text", data="hello"),
            "stream-1",
            set_reply=True,
        )

        self.assertIsNone(message)

    async def test_message_to_stream_with_message_stops_when_after_build_event_cancels(self) -> None:
        stream = self.make_stream()
        manager_patch, bot_patch = self.patch_runtime(stream=stream)
        fake_sender = SimpleNamespace(send_message=AsyncMock(return_value=object()))
        fake_events = SimpleNamespace(handle_mai_events=AsyncMock(return_value=(False, None)))

        events_module = importlib.import_module("src.plugin_system.core.events_manager")

        with (
            manager_patch,
            bot_patch,
            patch.object(events_module, "events_manager", fake_events),
            patch.object(send_service, "UniversalMessageSender", return_value=fake_sender),
        ):
            message = await send_service.message_to_stream_with_message(
                Seg(type="text", data="hello"),
                "stream-1",
            )

        self.assertIsNone(message)
        fake_events.handle_mai_events.assert_awaited_once()
        fake_sender.send_message.assert_not_awaited()

    async def test_message_to_stream_with_message_sends_built_message_and_wrappers_return_bool(self) -> None:
        stream = self.make_stream()
        manager_patch, bot_patch = self.patch_runtime(stream=stream)
        fake_sender = SimpleNamespace(send_message=AsyncMock(return_value=object()))
        fake_events = SimpleNamespace(handle_mai_events=AsyncMock(return_value=(True, None)))

        events_module = importlib.import_module("src.plugin_system.core.events_manager")

        with (
            manager_patch,
            bot_patch,
            patch.object(events_module, "events_manager", fake_events),
            patch.object(send_service, "UniversalMessageSender", return_value=fake_sender),
        ):
            message = await send_service.message_to_stream_with_message(
                Seg(type="text", data="hello"),
                "stream-1",
                display_message="shown",
                typing=True,
                storage_message=False,
                selected_expressions=[3],
            )

        self.assertIsNotNone(message)
        self.assertEqual(message.display_message, "shown")
        self.assertEqual(message.selected_expressions, [3])
        fake_sender.send_message.assert_awaited_once()
        sent_message = fake_sender.send_message.await_args.args[0]
        sent_kwargs = fake_sender.send_message.await_args.kwargs
        self.assertIs(sent_message, message)
        self.assertEqual(sent_kwargs["typing"], True)
        self.assertEqual(sent_kwargs["storage_message"], False)

    async def test_components_to_stream_preserves_components_when_segment_is_not_modified(self) -> None:
        stream = self.make_stream()
        manager_patch, bot_patch = self.patch_runtime(stream=stream)
        fake_sender = SimpleNamespace(send_message=AsyncMock(return_value=object()))
        fake_events = SimpleNamespace(handle_mai_events=AsyncMock(return_value=(True, None)))
        components = MessageComponentSequence([TextComponent("hello")])

        events_module = importlib.import_module("src.plugin_system.core.events_manager")

        with (
            manager_patch,
            bot_patch,
            patch.object(events_module, "events_manager", fake_events),
            patch.object(send_service, "UniversalMessageSender", return_value=fake_sender),
        ):
            message = await send_service.components_to_stream_with_message(components, "stream-1")

        self.assertIsNotNone(message)
        self.assertIs(message.message_components, components)
        self.assertTrue(message.preserve_message_components)


if __name__ == "__main__":
    unittest.main()
