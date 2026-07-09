import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.chat.heart_flow import turn_scheduler
from src.chat.heart_flow.frequency_control import FrequencyControl, FrequencyControlManager
from src.chat.heart_flow.turn_scheduler import ReplyTurnScheduler


def message(*, mentioned: bool = False, at: bool = False):
    return SimpleNamespace(is_mentioned=mentioned, is_at=at)


class FakeChatConfig:
    def __init__(self, *, mentioned_bot_reply: bool = True, talk_value: float = 0.5) -> None:
        self.mentioned_bot_reply = mentioned_bot_reply
        self.talk_value = talk_value
        self.requested_streams = []

    def get_talk_value(self, stream_id: str) -> float:
        self.requested_streams.append(stream_id)
        return self.talk_value


class FakeFrequencyControl:
    def __init__(self, adjust: float) -> None:
        self.adjust = adjust

    def get_talk_frequency_adjust(self) -> float:
        return self.adjust


class FakeFrequencyControlManager:
    def __init__(self, adjust: float) -> None:
        self.adjust = adjust
        self.requested_streams = []

    def get_or_create_frequency_control(self, stream_id: str) -> FakeFrequencyControl:
        self.requested_streams.append(stream_id)
        return FakeFrequencyControl(self.adjust)


class ReplyTurnSchedulerTest(unittest.TestCase):
    def test_group_turn_waits_when_recent_messages_are_below_adaptive_threshold(self) -> None:
        scheduler = ReplyTurnScheduler()
        chat_config = FakeChatConfig(mentioned_bot_reply=True, talk_value=1.0)
        fake_global_config = SimpleNamespace(chat=chat_config)

        with patch.object(turn_scheduler, "global_config", fake_global_config):
            decision = scheduler.decide_group_turn(
                stream_id="stream-1",
                recent_messages=[message()],
                consecutive_no_reply_count=5,
            )

        self.assertFalse(decision.should_observe)
        self.assertEqual(decision.sleep_seconds, 0.2)
        self.assertEqual(decision.reason, "insufficient_recent_messages")
        self.assertFalse(decision.should_update_last_read_time)

    def test_group_turn_prioritizes_latest_mentioned_message_when_mention_reply_is_enabled(self) -> None:
        scheduler = ReplyTurnScheduler()
        chat_config = FakeChatConfig(mentioned_bot_reply=True, talk_value=0.0)
        fake_global_config = SimpleNamespace(chat=chat_config)
        first = message(mentioned=True)
        last = message(at=True)

        with patch.object(turn_scheduler, "global_config", fake_global_config):
            decision = scheduler.decide_group_turn(
                stream_id="stream-1",
                recent_messages=[first, message(), last],
                consecutive_no_reply_count=0,
            )

        self.assertTrue(decision.should_observe)
        self.assertIs(decision.force_reply_message, last)
        self.assertEqual(decision.reason, "mentioned_bot")
        self.assertTrue(decision.should_update_last_read_time)

    def test_group_turn_uses_talk_probability_when_mentions_are_disabled_or_absent(self) -> None:
        scheduler = ReplyTurnScheduler()
        chat_config = FakeChatConfig(mentioned_bot_reply=False, talk_value=0.4)
        fake_frequency_manager = FakeFrequencyControlManager(adjust=0.5)
        fake_global_config = SimpleNamespace(chat=chat_config)

        with (
            patch.object(turn_scheduler, "global_config", fake_global_config),
            patch.object(turn_scheduler, "frequency_control_manager", fake_frequency_manager),
            patch.object(turn_scheduler.random, "random", return_value=0.19),
        ):
            hit = scheduler.decide_group_turn(
                stream_id="stream-1",
                recent_messages=[message(mentioned=True)],
                consecutive_no_reply_count=0,
            )

        self.assertTrue(hit.should_observe)
        self.assertEqual(hit.reason, "frequency_probability_hit")
        self.assertTrue(hit.should_update_last_read_time)
        self.assertEqual(chat_config.requested_streams, ["stream-1"])
        self.assertEqual(fake_frequency_manager.requested_streams, ["stream-1"])

        with (
            patch.object(turn_scheduler, "global_config", fake_global_config),
            patch.object(turn_scheduler, "frequency_control_manager", fake_frequency_manager),
            patch.object(turn_scheduler.random, "random", return_value=0.21),
        ):
            miss = scheduler.decide_group_turn(
                stream_id="stream-2",
                recent_messages=[message()],
                consecutive_no_reply_count=0,
            )

        self.assertFalse(miss.should_observe)
        self.assertEqual(miss.sleep_seconds, 10)
        self.assertEqual(miss.reason, "frequency_probability_miss")
        self.assertTrue(miss.should_update_last_read_time)

    def test_group_threshold_randomizes_after_repeated_no_reply_and_private_turn_flags_new_messages(self) -> None:
        scheduler = ReplyTurnScheduler()

        self.assertEqual(scheduler._group_message_threshold(0), 1)
        self.assertEqual(scheduler._group_message_threshold(5), 2)
        with patch.object(turn_scheduler.random, "random", return_value=0.49):
            self.assertEqual(scheduler._group_message_threshold(3), 2)
        with patch.object(turn_scheduler.random, "random", return_value=0.5):
            self.assertEqual(scheduler._group_message_threshold(3), 1)

        empty_private = scheduler.decide_private_turn(recent_messages=[])
        new_private = scheduler.decide_private_turn(recent_messages=[object()])

        self.assertTrue(empty_private.should_observe)
        self.assertEqual(empty_private.sleep_seconds, 0.1)
        self.assertFalse(empty_private.should_update_last_read_time)
        self.assertFalse(empty_private.should_set_new_message_event)
        self.assertTrue(new_private.should_update_last_read_time)
        self.assertTrue(new_private.should_set_new_message_event)


class FrequencyControlTest(unittest.TestCase):
    def test_frequency_control_clamps_adjustment_and_manager_reuses_removes_instances(self) -> None:
        control = FrequencyControl("stream-1")

        control.set_talk_frequency_adjust(0.0)
        self.assertEqual(control.get_talk_frequency_adjust(), 0.1)
        control.set_talk_frequency_adjust(10.0)
        self.assertEqual(control.get_talk_frequency_adjust(), 5.0)
        control.set_talk_frequency_adjust(2.5)
        self.assertEqual(control.get_talk_frequency_adjust(), 2.5)

        manager = FrequencyControlManager()
        first = manager.get_or_create_frequency_control("stream-1")
        second = manager.get_or_create_frequency_control("stream-1")
        other = manager.get_or_create_frequency_control("stream-2")

        self.assertIs(first, second)
        self.assertIsNot(first, other)
        self.assertEqual(set(manager.get_all_chat_ids()), {"stream-1", "stream-2"})
        self.assertTrue(manager.remove_frequency_control("stream-1"))
        self.assertFalse(manager.remove_frequency_control("stream-1"))
        self.assertEqual(manager.get_all_chat_ids(), ["stream-2"])


if __name__ == "__main__":
    unittest.main()
