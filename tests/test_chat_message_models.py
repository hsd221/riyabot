import unittest
from types import SimpleNamespace
from unittest.mock import patch

from maim_message import BaseMessageInfo, GroupInfo, MessageBase, Seg, UserInfo

from src.chat.message_receive.chat_stream import ChatManager, ChatMessageContext, ChatStream
from src.chat.message_receive.message import MessageRecv, MessageSending
from src.common.data_models.message_component_model import MessageComponentSequence, TextComponent


def make_stream(group: bool = True) -> ChatStream:
    group_info = GroupInfo(platform="qq", group_id="group-1", group_name="Group") if group else None
    return ChatStream(
        stream_id="stream-1",
        platform="qq",
        user_info=UserInfo(platform="qq", user_id="user-1", user_nickname="Alice", user_cardname="Ali"),
        group_info=group_info,
        data={"create_time": 1.0, "last_active_time": 2.0},
    )


def make_recv(segment: Seg, *, processed_plain_text: str = "", stream: ChatStream | None = None) -> MessageRecv:
    message = MessageRecv(
        {
            "message_info": {
                "platform": "qq",
                "message_id": "msg-1",
                "time": 10.0,
                "group_info": {"platform": "qq", "group_id": "group-1", "group_name": "Group"},
                "user_info": {
                    "platform": "qq",
                    "user_id": "user-1",
                    "user_nickname": "Alice",
                    "user_cardname": "Ali",
                },
                "additional_config": '{"at_bot": true}',
                "format_info": {"content_format": "seglist", "accept_format": ["text", "image"]},
                "template_info": {"template_items": {}},
            },
            "message_segment": segment.to_dict(),
            "raw_message": processed_plain_text,
            "processed_plain_text": processed_plain_text,
        }
    )
    message.priority_mode = "priority"
    message.priority_info = {"score": 1}
    if stream:
        message.update_chat_stream(stream)
    return message


class ChatStreamModelTest(unittest.TestCase):
    def test_chat_stream_round_trip_active_time_and_stream_ids_are_stable(self) -> None:
        stream = make_stream()
        restored = ChatStream.from_dict(stream.to_dict())

        self.assertEqual(restored.stream_id, "stream-1")
        self.assertEqual(restored.user_info.user_nickname, "Alice")
        self.assertEqual(restored.group_info.group_name, "Group")
        self.assertEqual(restored.create_time, 1.0)
        self.assertEqual(restored.last_active_time, 2.0)

        with patch("src.chat.message_receive.chat_stream.time.time", return_value=20.0):
            restored.update_active_time()

        self.assertEqual(restored.last_active_time, 20.0)
        self.assertFalse(restored.saved)
        self.assertEqual(
            ChatManager._generate_stream_id("qq", restored.user_info, restored.group_info),
            ChatManager().get_stream_id("qq", "group-1", is_group=True),
        )
        self.assertEqual(
            ChatManager._generate_stream_id("qq", restored.user_info, None),
            ChatManager().get_stream_id("qq", "user-1", is_group=False),
        )

    def test_chat_message_context_exposes_template_format_priority_and_last_message(self) -> None:
        message = make_recv(Seg(type="text", data="hello"), stream=make_stream())
        message.message_info.template_info = SimpleNamespace(template_default=False, template_name="custom")
        context = ChatMessageContext(message)

        self.assertIs(context.get_last_message(), message)
        self.assertEqual(context.get_template_name(), "custom")
        self.assertTrue(context.check_types(["text"]))
        self.assertFalse(context.check_types(["voice"]))
        self.assertEqual(context.get_priority_mode(), "priority")
        self.assertEqual(context.get_priority_info(), {"score": 1})


class MessageRecvProcessingTest(unittest.IsolatedAsyncioTestCase):
    async def test_recv_processes_text_seglist_cards_and_priority_info_without_heavy_media(self) -> None:
        message = make_recv(
            Seg(
                type="seglist",
                data=[
                    Seg(type="text", data="hello"),
                    Seg(type="video_card", data={"file": "clip.mp4", "file_size": "123", "url": "https://v.test"}),
                    Seg(type="miniapp_card", data={"title": "App", "desc": "desc", "source_url": "https://app.test"}),
                    Seg(type="priority_info", data={"message_type": "vip", "message_priority": 2.0}),
                ],
            ),
            stream=make_stream(),
        )

        await message.process(enable_heavy_media_analysis=False, enable_voice_transcription=False)

        self.assertEqual(
            message.processed_plain_text,
            "hello [视频: clip.mp4, 大小: 123字节] 链接: https://v.test [小程序分享 - App] desc 链接: https://app.test",
        )
        self.assertEqual(message.priority_mode, "priority")
        self.assertEqual(message.priority_info, {"message_type": "vip", "message_priority": 2.0})
        self.assertTrue(message.is_mentioned)
        self.assertEqual(message.message_info.additional_config, {"at_bot": True})

    async def test_recv_processes_forward_nodes_recursively(self) -> None:
        forward_node = MessageBase(
            message_info=BaseMessageInfo(
                platform="qq",
                message_id="forward-1",
                user_info=UserInfo(platform="qq", user_id="user-2", user_nickname="Bob"),
            ),
            message_segment=Seg(type="text", data="forward text"),
            raw_message="forward text",
        ).to_dict()
        message = make_recv(Seg(type="forward", data=[forward_node]), stream=make_stream())

        await message.process(enable_heavy_media_analysis=False, enable_voice_transcription=False)

        self.assertIn("[合并消息]:", message.processed_plain_text)
        self.assertIn("forward text", message.processed_plain_text)


class MessageSendingTest(unittest.IsolatedAsyncioTestCase):
    async def test_message_sending_build_reply_prepends_reply_segment_and_preserves_components(self) -> None:
        stream = make_stream()
        reply = make_recv(Seg(type="text", data="quoted"), processed_plain_text="quoted", stream=stream)
        components = MessageComponentSequence([TextComponent("answer")])
        message = MessageSending(
            message_id="send-1",
            chat_stream=stream,
            bot_user_info=UserInfo(platform="qq", user_id="bot", user_nickname="Mai"),
            sender_info=stream.user_info,
            message_segment=Seg(type="text", data="answer"),
            reply=reply,
            thinking_start_time=5.0,
        )
        message.message_components = components
        message.preserve_message_components = True

        message.build_reply()
        await message.process()

        self.assertEqual(message.reply_to_message_id, "msg-1")
        self.assertEqual(message.message_segment.type, "seglist")
        self.assertEqual(message.message_segment.data[0].type, "reply")
        self.assertEqual(message.message_components.components[0].target_message_id, "msg-1")
        self.assertEqual(message.processed_plain_text, "[回复：quoted] answer")

    async def test_message_sending_process_uses_preserved_components_when_segment_matches(self) -> None:
        stream = make_stream()
        components = MessageComponentSequence([TextComponent("answer")])
        message = MessageSending(
            message_id="send-2",
            chat_stream=stream,
            bot_user_info=UserInfo(platform="qq", user_id="bot", user_nickname="Mai"),
            sender_info=stream.user_info,
            message_segment=Seg(type="text", data="answer"),
            thinking_start_time=5.0,
        )
        message.message_components = components
        message.preserve_message_components = True

        with patch("src.chat.message_receive.message.time.time", return_value=7.25):
            await message.process()
            thinking_time = message.update_thinking_time()

        self.assertEqual(message.processed_plain_text, "answer")
        self.assertEqual(thinking_time, 2.25)


if __name__ == "__main__":
    unittest.main()
