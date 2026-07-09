import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.chat.heart_flow import hfc_utils
from src.chat.heart_flow.hfc_utils import CycleDetail


class SerializableObject:
    def to_dict(self) -> dict:
        return {"serialized": True}


class FakeChatManager:
    def __init__(self) -> None:
        self.calls = []
        self.stream = SimpleNamespace(stream_id="inner-stream")

    async def get_or_create_stream(self, *, platform, user_info, group_info):
        self.calls.append({"platform": platform, "user_info": user_info, "group_info": group_info})
        return self.stream


class CycleDetailTest(unittest.TestCase):
    def test_cycle_detail_serializes_basic_fields_custom_objects_and_recursive_values(self) -> None:
        recursive = {}
        recursive["self"] = recursive

        with patch.object(hfc_utils.time, "time", return_value=100.0):
            detail = CycleDetail(cycle_id=7)
        detail.thinking_id = "tid100"
        detail.end_time = 105.0
        detail.timers = {"observe": 0.2}
        detail.set_loop_info(
            {
                "loop_plan_info": {
                    "custom": SerializableObject(),
                    "recursive": recursive,
                    "ignored_key": {"nested": [{"drop": "nested dict in list"}, "keep"]},
                    ("tuple", "key"): "ignored",
                },
                "loop_action_info": {"actions": ["reply", 3, None], "object": object()},
            }
        )

        data = detail.to_dict()

        self.assertEqual(data["cycle_id"], 7)
        self.assertEqual(data["start_time"], 100.0)
        self.assertEqual(data["end_time"], 105.0)
        self.assertEqual(data["timers"], {"observe": 0.2})
        self.assertEqual(data["thinking_id"], "tid100")
        self.assertEqual(data["loop_plan_info"]["custom"], {"serialized": True})
        self.assertIn("self", data["loop_plan_info"]["recursive"])
        self.assertNotIn(("tuple", "key"), data["loop_plan_info"])
        self.assertEqual(data["loop_plan_info"]["ignored_key"]["nested"], ["keep"])
        self.assertEqual(data["loop_action_info"]["actions"], ["reply", 3, None])
        self.assertIsInstance(data["loop_action_info"]["object"], str)


class HfcUtilsBoundaryTest(unittest.IsolatedAsyncioTestCase):
    def test_get_recent_message_stats_counts_total_and_bot_messages_with_optional_chat_filter(self) -> None:
        count_messages = Mock(side_effect=[12, 3, 7, 2])
        fake_config = SimpleNamespace(bot=SimpleNamespace(qq_account="bot-1"))

        with (
            patch.object(hfc_utils.time, "time", return_value=1000.0),
            patch.object(hfc_utils, "global_config", fake_config),
            patch.object(hfc_utils, "count_messages", count_messages),
        ):
            all_stats = hfc_utils.get_recent_message_stats(minutes=5)
            chat_stats = hfc_utils.get_recent_message_stats(minutes=2, chat_id="stream-1")

        self.assertEqual(all_stats, {"bot_reply_count": 3, "total_message_count": 12})
        self.assertEqual(chat_stats, {"bot_reply_count": 2, "total_message_count": 7})
        self.assertEqual(
            count_messages.call_args_list[0].args[0],
            {"time": {"$gte": 700.0}},
        )
        self.assertEqual(
            count_messages.call_args_list[1].args[0],
            {"time": {"$gte": 700.0}, "user_id": "bot-1"},
        )
        self.assertEqual(
            count_messages.call_args_list[2].args[0],
            {"time": {"$gte": 880.0}, "chat_id": "stream-1"},
        )
        self.assertEqual(
            count_messages.call_args_list[3].args[0],
            {"time": {"$gte": 880.0}, "chat_id": "stream-1", "user_id": "bot-1"},
        )

    async def test_send_typing_and_stop_typing_use_inner_group_stream_and_custom_state_messages(self) -> None:
        fake_manager = FakeChatManager()

        with (
            patch.object(hfc_utils, "get_chat_manager", return_value=fake_manager),
            patch.object(hfc_utils.send_api, "custom_to_stream", new=AsyncMock()) as custom_to_stream,
        ):
            await hfc_utils.send_typing()
            await hfc_utils.stop_typing()

        self.assertEqual(len(fake_manager.calls), 2)
        first_group = fake_manager.calls[0]["group_info"]
        self.assertEqual(first_group.platform, "amaidesu_default")
        self.assertEqual(first_group.group_id, "114514")
        self.assertIsNone(fake_manager.calls[0]["user_info"])
        self.assertEqual(custom_to_stream.await_count, 2)
        self.assertEqual(
            custom_to_stream.await_args_list[0].kwargs,
            {
                "message_type": "state",
                "content": "typing",
                "stream_id": "inner-stream",
                "storage_message": False,
            },
        )
        self.assertEqual(
            custom_to_stream.await_args_list[1].kwargs,
            {
                "message_type": "state",
                "content": "stop_typing",
                "stream_id": "inner-stream",
                "storage_message": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
