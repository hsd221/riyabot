import datetime
import types
import unittest
from unittest.mock import patch

from peewee import SqliteDatabase

from src.common.database.database_model import (
    ActionRecords,
    BaseModel,
    ChatStreams,
    Emoji,
    Expression,
    Jargon,
    LLMUsage,
    Messages,
    OnlineTime,
)
from src.webui import annual_report_routes


TEST_MODELS = [LLMUsage, OnlineTime, Messages, ChatStreams, Emoji, Expression, ActionRecords, Jargon]


class AnnualReportRoutesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.test_db = SqliteDatabase(":memory:")
        self.original_dbs = {model: model._meta.database for model in [BaseModel, *TEST_MODELS]}
        self.test_db.bind(TEST_MODELS, bind_refs=False, bind_backrefs=False)
        self.test_db.connect()
        self.test_db.create_tables(TEST_MODELS)
        self.year = 2025

    def tearDown(self) -> None:
        self.test_db.drop_tables(TEST_MODELS)
        self.test_db.close()
        for model, database in self.original_dbs.items():
            model._meta.set_database(database)

    def ts(self, month: int, day: int, hour: int = 12, minute: int = 0) -> float:
        return datetime.datetime(self.year, month, day, hour, minute, 0).timestamp()

    def dt(self, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime.datetime:
        return datetime.datetime(self.year, month, day, hour, minute, 0)

    def create_usage(
        self,
        *,
        model_name: str = "gpt",
        model_assign_name: str | None = "replyer",
        user_id: str = "user-1",
        prompt_tokens: int = 10,
        completion_tokens: int = 5,
        cost: float = 0.2,
        time_cost: float = 1.0,
        timestamp: datetime.datetime | None = None,
    ) -> LLMUsage:
        total_tokens = prompt_tokens + completion_tokens
        return LLMUsage.create(
            model_name=model_name,
            model_assign_name=model_assign_name,
            model_api_provider="provider",
            user_id=user_id,
            request_type="chat",
            endpoint="/v1/chat",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost=cost,
            time_cost=time_cost,
            status="success",
            timestamp=timestamp or self.dt(6, 1),
        )

    def create_message(
        self,
        message_id: str,
        *,
        timestamp: float | None = None,
        user_id: str = "user-1",
        user_nickname: str = "Alice",
        group_id: str = "group-1",
        group_name: str = "一群",
        content: str = "hello",
        reply_to: str | None = None,
        is_at: bool = False,
        is_mentioned: bool = False,
        is_picid: bool = False,
        interest_value: float | None = None,
    ) -> Messages:
        msg_time = timestamp if timestamp is not None else self.ts(6, 1)
        return Messages.create(
            message_id=message_id,
            time=msg_time,
            chat_id=group_id,
            reply_to=reply_to,
            interest_value=interest_value,
            is_at=is_at,
            is_mentioned=is_mentioned,
            chat_info_stream_id=group_id,
            chat_info_platform="qq",
            chat_info_user_platform="qq",
            chat_info_user_id=user_id,
            chat_info_user_nickname=user_nickname,
            chat_info_user_cardname=None,
            chat_info_group_platform="qq",
            chat_info_group_id=group_id,
            chat_info_group_name=group_name,
            chat_info_create_time=1.0,
            chat_info_last_active_time=msg_time,
            user_platform="qq",
            user_id=user_id,
            user_nickname=user_nickname,
            user_cardname=None,
            processed_plain_text=content,
            display_message=content,
            is_picid=is_picid,
        )

    def create_action(
        self,
        action_id: str,
        *,
        action_name: str,
        timestamp: float | None = None,
        action_data: str = "{}",
        reasoning: str | None = None,
    ) -> ActionRecords:
        return ActionRecords.create(
            action_id=action_id,
            time=timestamp if timestamp is not None else self.ts(6, 1),
            action_reasoning=reasoning,
            action_name=action_name,
            action_data=action_data,
            action_done=True,
            action_build_into_prompt=False,
            action_prompt_display="prompt",
            chat_id="stream-1",
            chat_info_stream_id="stream-1",
            chat_info_platform="qq",
        )

    def seed_report_data(self) -> None:
        ChatStreams.create(
            stream_id="stream-1",
            create_time=self.ts(1, 1),
            group_platform="qq",
            group_id="group-1",
            group_name="一群",
            last_active_time=self.ts(6, 1),
            platform="qq",
            user_platform="qq",
            user_id="user-1",
            user_nickname="Alice",
            user_cardname=None,
        )
        ChatStreams.create(
            stream_id="stream-2",
            create_time=self.ts(1, 1),
            group_platform="qq",
            group_id="group-2",
            group_name="二群",
            last_active_time=self.ts(1, 4),
            platform="qq",
            user_platform="qq",
            user_id="bot-qq",
            user_nickname="Bot",
            user_cardname=None,
        )

        self.create_message(
            "m1",
            timestamp=self.ts(1, 2, 12),
            user_id="user-1",
            user_nickname="Alice",
            group_id="group-1",
            group_name="一群",
            content="a" * 60,
            is_at=True,
            interest_value=0.3,
        )
        self.create_message(
            "m2",
            timestamp=self.ts(1, 2, 13),
            user_id="user-1",
            user_nickname="Alice",
            group_id="group-1",
            group_name="一群",
            content="reply",
            reply_to="m1",
            is_mentioned=True,
            is_picid=True,
            interest_value=0.9,
        )
        self.create_message(
            "m3",
            timestamp=self.ts(6, 3, 1, 30),
            user_id="bot-qq",
            user_nickname="Bot",
            group_id="group-2",
            group_name="二群",
            content="[回复<1:2> 的消息：old] 深夜回复内容",
        )
        self.create_message(
            "old",
            timestamp=datetime.datetime(2024, 12, 31, 12).timestamp(),
            user_id="user-old",
            user_nickname="Old",
            group_id="group-old",
            group_name="旧群",
        )

        self.create_usage(
            model_name="gpt-4",
            model_assign_name="replyer-main",
            user_id="user-1",
            prompt_tokens=20,
            completion_tokens=10,
            cost=0.5,
            timestamp=self.dt(1, 2, 12),
        )
        self.create_usage(
            model_name="gpt-3.5",
            model_assign_name=None,
            user_id="system",
            prompt_tokens=5,
            completion_tokens=5,
            cost=0.2,
            timestamp=self.dt(1, 2, 13),
        )
        self.create_usage(
            model_name="old",
            model_assign_name="old",
            user_id="user-old",
            prompt_tokens=100,
            completion_tokens=100,
            cost=5.0,
            timestamp=datetime.datetime(2024, 12, 31, 12),
        )

        OnlineTime.create(
            duration=60,
            start_timestamp=self.dt(1, 2, 11),
            end_timestamp=self.dt(1, 2, 12),
        )

        Emoji.create(
            full_path="/tmp/top.png",
            format="png",
            emoji_hash="hash-top",
            description="top emoji",
            record_time=self.ts(1, 1),
            is_registered=True,
            usage_count=5,
        )
        Emoji.create(
            full_path="/tmp/low.png",
            format="png",
            emoji_hash="hash-low",
            description="low emoji",
            record_time=self.ts(1, 1),
            is_registered=True,
            usage_count=2,
        )

        Expression.create(
            situation="问候",
            style="轻松",
            chat_id="group-1",
            count=3,
            last_active_time=self.ts(1, 2, 12),
            checked=True,
            rejected=False,
        )
        Expression.create(
            situation="吐槽",
            style="犀利",
            chat_id="group-1",
            count=2,
            last_active_time=self.ts(1, 2, 13),
            checked=True,
            rejected=True,
        )

        self.create_action("a1", action_name="no_reply", timestamp=self.ts(1, 2, 12), reasoning="短")
        self.create_action("a2", action_name="poke", timestamp=self.ts(1, 2, 13), reasoning="很长的推理")
        self.create_action(
            "a3",
            action_name="reply",
            timestamp=self.ts(1, 2, 14),
            action_data='{"reply_text": "常用回复"}',
        )
        self.create_action(
            "a4",
            action_name="reply",
            timestamp=self.ts(1, 2, 15),
            action_data="{'reply_text': '常用回复'}",
        )

        Jargon.create(content="黑话1", meaning="意思1", chat_id="group-1", count=8, is_jargon=True)
        Jargon.create(content="黑话2", meaning="意思2", chat_id="group-1", count=3, is_jargon=True)
        Jargon.create(content="普通词", meaning="不是", chat_id="group-1", count=10, is_jargon=False)

    def fake_config(self):
        return types.SimpleNamespace(bot=types.SimpleNamespace(qq_account="bot-qq", nickname="测试Bot"))

    def test_year_range_helpers_return_full_year_boundaries(self) -> None:
        start_ts, end_ts = annual_report_routes.get_year_time_range(2025)
        start_dt, end_dt = annual_report_routes.get_year_datetime_range(2025)

        self.assertEqual(datetime.datetime.fromtimestamp(start_ts), datetime.datetime(2025, 1, 1, 0, 0, 0))
        self.assertEqual(datetime.datetime.fromtimestamp(end_ts), datetime.datetime(2025, 12, 31, 23, 59, 59))
        self.assertEqual(start_dt, datetime.datetime(2025, 1, 1, 0, 0, 0))
        self.assertEqual(end_dt, datetime.datetime(2025, 12, 31, 23, 59, 59))

    async def test_time_footprint_counts_overlapping_online_records_and_message_activity(self) -> None:
        OnlineTime.create(
            duration=999,
            start_timestamp=datetime.datetime(2024, 12, 31, 23, 0, 0),
            end_timestamp=datetime.datetime(2026, 1, 1, 1, 0, 0),
        )
        self.create_message("first", timestamp=self.ts(1, 2, 12), content="hello" * 20)
        self.create_message("second", timestamp=self.ts(1, 2, 13), content="busy")

        data = await annual_report_routes.get_time_footprint(2025)

        self.assertEqual(data.total_online_hours, 8760.0)
        self.assertEqual(data.first_message_user, "Alice")
        self.assertTrue(data.first_message_content.endswith("..."))
        self.assertEqual(data.busiest_day_count, 2)

    async def test_social_network_filters_bot_user_and_counts_groups_mentions_and_companion(self) -> None:
        self.seed_report_data()

        with patch("src.config.config.global_config", self.fake_config()):
            data = await annual_report_routes.get_social_network(2025)

        self.assertEqual(data.total_groups, 2)
        self.assertEqual(data.top_groups[0]["group_id"], "group-1")
        self.assertEqual(data.top_groups[0]["message_count"], 2)
        self.assertEqual(data.top_users[0]["user_id"], "user-1")
        self.assertTrue(all(user["user_id"] != "bot-qq" for user in data.top_users))
        self.assertEqual(data.at_count, 1)
        self.assertEqual(data.mentioned_count, 1)
        self.assertEqual(data.longest_companion_user, "Alice")
        self.assertGreaterEqual(data.longest_companion_days, 100)

    async def test_brain_power_aggregates_llm_costs_models_actions_interest_and_reasoning(self) -> None:
        self.seed_report_data()

        data = await annual_report_routes.get_brain_power(2025)

        self.assertEqual(data.total_tokens, 40)
        self.assertEqual(data.total_cost, 0.7)
        self.assertEqual(data.favorite_model, "replyer-main")
        self.assertEqual(data.favorite_model_count, 1)
        self.assertEqual(data.most_expensive_cost, 0.5)
        self.assertEqual(data.top_token_consumers, [{"user_id": "user-1", "cost": 0.5, "tokens": 30}])
        self.assertIn({"model": "replyer-main", "count": 1}, data.top_reply_models)
        self.assertEqual(data.total_actions, 4)
        self.assertEqual(data.no_reply_count, 1)
        self.assertEqual(data.silence_rate, 25.0)
        self.assertEqual(data.avg_interest_value, 0.6)
        self.assertEqual(data.max_interest_value, 0.9)
        self.assertEqual(data.avg_reasoning_length, 3.0)
        self.assertEqual(data.max_reasoning_length, 5)

    async def test_expression_vibe_collects_emoji_expression_action_image_and_reply_highlights(self) -> None:
        self.seed_report_data()

        with (
            patch("src.config.config.global_config", self.fake_config()),
            patch("random.choice", side_effect=lambda items: items[0]),
        ):
            data = await annual_report_routes.get_expression_vibe(2025)

        self.assertEqual(data.top_emoji["description"], "top emoji")
        self.assertEqual([emoji["usage_count"] for emoji in data.top_emojis], [5, 2])
        self.assertEqual(data.top_expressions[0], {"style": "轻松", "count": 3})
        self.assertEqual(data.rejected_expression_count, 1)
        self.assertEqual(data.checked_expression_count, 2)
        self.assertEqual(data.total_expressions, 2)
        self.assertEqual(data.action_types, [{"action": "poke", "count": 1}])
        self.assertEqual(data.image_processed_count, 1)
        self.assertEqual(data.late_night_reply, {"time": "01:30", "content": "深夜回复内容"})
        self.assertEqual(data.favorite_reply, {"content": "常用回复", "count": 2})

    async def test_achievements_count_confirmed_jargons_messages_and_replies(self) -> None:
        self.seed_report_data()

        data = await annual_report_routes.get_achievements(2025)

        self.assertEqual(data.new_jargon_count, 2)
        self.assertEqual(data.sample_jargons[0], {"content": "黑话1", "meaning": "意思1", "count": 8})
        self.assertEqual(data.total_messages, 3)
        self.assertEqual(data.total_replies, 1)

    async def test_api_wrappers_and_full_report_return_dimension_models(self) -> None:
        self.seed_report_data()

        with (
            patch("src.config.config.global_config", self.fake_config()),
            patch("random.choice", side_effect=lambda items: items[0]),
        ):
            report = await annual_report_routes.get_full_annual_report(year=2025, _auth=True)
            time_footprint = await annual_report_routes.get_time_footprint_api(year=2025, _auth=True)
            social_network = await annual_report_routes.get_social_network_api(year=2025, _auth=True)
            brain_power = await annual_report_routes.get_brain_power_api(year=2025, _auth=True)
            expression_vibe = await annual_report_routes.get_expression_vibe_api(year=2025, _auth=True)
            achievements = await annual_report_routes.get_achievements_api(year=2025, _auth=True)

        self.assertEqual(report.year, 2025)
        self.assertEqual(report.bot_name, "测试Bot")
        self.assertEqual(report.brain_power.total_tokens, 40)
        self.assertEqual(time_footprint.busiest_day_count, 2)
        self.assertEqual(social_network.total_groups, 2)
        self.assertEqual(brain_power.total_cost, 0.7)
        self.assertEqual(expression_vibe.favorite_reply["count"], 2)
        self.assertEqual(achievements.new_jargon_count, 2)

    def test_require_auth_delegates_to_shared_auth_checker(self) -> None:
        with patch.object(annual_report_routes, "verify_auth_token_from_cookie_or_header", return_value=True) as verify:
            self.assertTrue(annual_report_routes.require_auth("cookie", "Bearer token"))

        verify.assert_called_once_with("cookie", "Bearer token")


if __name__ == "__main__":
    unittest.main()
