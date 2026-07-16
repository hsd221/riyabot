import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from src.chat.brain_chat import brain_chat
from src.chat.message_receive.chat_stream import ChatStream
from src.common.data_models.database_data_model import DatabaseMessages
from src.common.data_models.message_data_model import ReplyContent, ReplySetModel
from src.common.data_models.message_data_model import ReplyContentType
from maim_message import GroupInfo, UserInfo


def make_db_message(message_id: str = "msg-1", *, text: str = "hello") -> DatabaseMessages:
    return DatabaseMessages(
        message_id=message_id,
        time=10.0,
        chat_id="stream-1",
        processed_plain_text=text,
        user_id="user-1",
        user_nickname="Alice",
        user_platform="qq",
        chat_info_stream_id="stream-1",
        chat_info_platform="qq",
        chat_info_user_id="user-1",
        chat_info_user_nickname="Alice",
        chat_info_user_platform="qq",
    )


def make_stream() -> ChatStream:
    return ChatStream(
        stream_id="stream-1",
        platform="qq",
        user_info=UserInfo(platform="qq", user_id="user-1", user_nickname="Alice"),
        group_info=GroupInfo(platform="qq", group_id="group-1", group_name="Group"),
    )


class BrainChattingUnitTest(unittest.IsolatedAsyncioTestCase):
    def make_chat(self) -> brain_chat.BrainChatting:
        chat = brain_chat.BrainChatting.__new__(brain_chat.BrainChatting)
        chat.stream_id = "stream-1"
        chat.chat_stream = make_stream()
        chat.log_prefix = "[stream-1]"
        chat.running = False
        chat._loop_task = None
        chat._new_message_event = asyncio.Event()
        chat.history_loop = []
        chat._cycle_counter = 0
        chat._current_cycle_detail = None
        chat.last_read_time = 1.0
        chat.message_archiver = None
        chat.topic_summarizer = None
        return chat

    async def test_start_cycle_end_cycle_and_loop_completion_are_stable(self) -> None:
        chat = self.make_chat()
        loop_info = {
            "loop_plan_info": {"ok": True},
            "loop_action_info": {"action_taken": False},
        }
        with patch.object(brain_chat.time, "time", return_value=10.25):
            timers, thinking_id = chat.start_cycle()
            chat.end_cycle(loop_info, {"step": 0.5})

        self.assertEqual(timers, {})
        self.assertEqual(thinking_id, "tid10.25")
        self.assertEqual(len(chat.history_loop), 1)
        self.assertEqual(chat.history_loop[0].loop_plan_info, {"ok": True})
        self.assertEqual(chat.history_loop[0].loop_action_info, {"action_taken": False})
        self.assertEqual(chat.history_loop[0].timers, {"step": 0.5})

        done_task = asyncio.Future()
        done_task.set_result(None)
        chat._handle_loop_completion(done_task)

        failed_task = asyncio.Future()
        failed_task.set_exception(RuntimeError("boom"))
        chat._handle_loop_completion(failed_task)

    async def test_send_response_sends_only_text_parts_and_uses_reply_for_first_message_when_needed(self) -> None:
        chat = self.make_chat()
        reply_set = ReplySetModel(
            reply_data=[
                ReplyContent(content_type=ReplyContentType.TEXT, content="第一句"),
                ReplyContent(content_type=ReplyContentType.EMOJI, content="ignored"),
                ReplyContent(content_type=ReplyContentType.TEXT, content="第二句"),
            ]
        )
        action_message = make_db_message()

        with (
            patch.object(brain_chat.message_api, "count_new_messages", return_value=3),
            patch.object(brain_chat.random, "randint", return_value=3),
            patch.object(brain_chat.send_api, "text_to_stream", new=AsyncMock()) as text_to_stream,
        ):
            reply_text = await chat._send_response(reply_set, action_message, selected_expressions=[1])

        self.assertEqual(reply_text, "第一句第二句")
        self.assertEqual(text_to_stream.await_count, 2)
        first_kwargs = text_to_stream.await_args_list[0].kwargs
        second_kwargs = text_to_stream.await_args_list[1].kwargs
        self.assertTrue(first_kwargs["set_reply"])
        self.assertFalse(first_kwargs["typing"])
        self.assertFalse(second_kwargs["set_reply"])
        self.assertTrue(second_kwargs["typing"])
        self.assertEqual(first_kwargs["selected_expressions"], [1])


if __name__ == "__main__":
    unittest.main()
