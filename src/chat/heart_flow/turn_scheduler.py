import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from src.chat.heart_flow.frequency_control import frequency_control_manager
from src.config.config import global_config

if TYPE_CHECKING:
    from src.common.data_models.database_data_model import DatabaseMessages


@dataclass
class TurnDecision:
    should_observe: bool
    force_reply_message: Optional["DatabaseMessages"] = None
    sleep_seconds: float = 0.0
    reason: str = ""
    should_update_last_read_time: bool = False
    should_set_new_message_event: bool = False


class ReplyTurnScheduler:
    def decide_group_turn(
        self,
        *,
        stream_id: str,
        recent_messages: list["DatabaseMessages"],
        consecutive_no_reply_count: int,
    ) -> TurnDecision:
        threshold = self._group_message_threshold(consecutive_no_reply_count)
        if len(recent_messages) < threshold:
            return TurnDecision(
                should_observe=False,
                sleep_seconds=0.2,
                reason="insufficient_recent_messages",
            )

        mentioned_message = self._find_mentioned_message(recent_messages)
        if mentioned_message:
            return TurnDecision(
                should_observe=True,
                force_reply_message=mentioned_message,
                reason="mentioned_bot",
                should_update_last_read_time=True,
            )

        talk_probability = (
            global_config.chat.get_talk_value(stream_id)
            * frequency_control_manager.get_or_create_frequency_control(stream_id).get_talk_frequency_adjust()
        )
        if random.random() < talk_probability:
            return TurnDecision(
                should_observe=True,
                reason="frequency_probability_hit",
                should_update_last_read_time=True,
            )

        return TurnDecision(
            should_observe=False,
            sleep_seconds=10,
            reason="frequency_probability_miss",
            should_update_last_read_time=True,
        )

    def decide_private_turn(
        self,
        *,
        recent_messages: list["DatabaseMessages"],
    ) -> TurnDecision:
        has_new_message = len(recent_messages) >= 1
        return TurnDecision(
            should_observe=True,
            sleep_seconds=0.1,
            reason="private_iteration",
            should_update_last_read_time=has_new_message,
            should_set_new_message_event=has_new_message,
        )

    @staticmethod
    def _group_message_threshold(consecutive_no_reply_count: int) -> int:
        if consecutive_no_reply_count >= 5:
            return 2
        if consecutive_no_reply_count >= 3:
            return 2 if random.random() < 0.5 else 1
        return 1

    @staticmethod
    def _find_mentioned_message(recent_messages: list["DatabaseMessages"]) -> Optional["DatabaseMessages"]:
        if not global_config.chat.mentioned_bot_reply:
            return None
        mentioned_message = None
        for message in recent_messages:
            if message.is_mentioned or message.is_at:
                mentioned_message = message
        return mentioned_message
