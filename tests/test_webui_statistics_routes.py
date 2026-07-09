import datetime
import unittest
from unittest.mock import patch

from peewee import SqliteDatabase

from src.common.database.database_model import BaseModel, LLMUsage, Messages, OnlineTime
from src.webui import statistics_routes


TEST_MODELS = [LLMUsage, OnlineTime, Messages]


class WebUIStatisticsRoutesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.test_db = SqliteDatabase(":memory:")
        self.original_dbs = {model: model._meta.database for model in [BaseModel, *TEST_MODELS]}
        self.test_db.bind(TEST_MODELS, bind_refs=False, bind_backrefs=False)
        self.test_db.connect()
        self.test_db.create_tables(TEST_MODELS)
        self.now = datetime.datetime(2026, 1, 2, 12, 30, 0)
        self.start = self.now - datetime.timedelta(hours=2)

    def tearDown(self) -> None:
        self.test_db.drop_tables(TEST_MODELS)
        self.test_db.close()
        for model, database in self.original_dbs.items():
            model._meta.set_database(database)

    def create_usage(
        self,
        timestamp: datetime.datetime,
        *,
        model_name: str,
        model_assign_name: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float,
        time_cost: float | None,
        status: str = "success",
        request_type: str = "chat",
    ) -> LLMUsage:
        return LLMUsage.create(
            model_name=model_name,
            model_assign_name=model_assign_name,
            model_api_provider="provider",
            user_id="user-1",
            request_type=request_type,
            endpoint="/v1/chat",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost=cost,
            time_cost=time_cost,
            status=status,
            timestamp=timestamp,
        )

    def create_message(self, message_id: str, timestamp: datetime.datetime, *, reply_to: str | None = None) -> Messages:
        return Messages.create(
            message_id=message_id,
            time=timestamp.timestamp(),
            chat_id="stream-1",
            reply_to=reply_to,
            chat_info_stream_id="stream-1",
            chat_info_platform="qq",
            chat_info_user_platform="qq",
            chat_info_user_id="user-1",
            chat_info_user_nickname="Alice",
            chat_info_user_cardname=None,
            chat_info_group_platform="qq",
            chat_info_group_id="group-1",
            chat_info_group_name="群",
            chat_info_create_time=1.0,
            chat_info_last_active_time=timestamp.timestamp(),
            user_platform="qq",
            user_id="user-1",
            user_nickname="Alice",
            user_cardname=None,
            processed_plain_text="hello",
            display_message="hello",
        )

    def seed_statistics_data(self) -> None:
        self.create_usage(
            self.now - datetime.timedelta(hours=1, minutes=20),
            model_name="gpt-4",
            model_assign_name="replyer",
            prompt_tokens=10,
            completion_tokens=5,
            cost=0.2,
            time_cost=0.5,
        )
        self.create_usage(
            self.now - datetime.timedelta(minutes=25),
            model_name="gpt-3.5",
            model_assign_name=None,
            prompt_tokens=3,
            completion_tokens=4,
            cost=0.3,
            time_cost=1.5,
            request_type="embedding",
        )
        self.create_usage(
            self.now - datetime.timedelta(hours=4),
            model_name="old-model",
            model_assign_name="old",
            prompt_tokens=100,
            completion_tokens=100,
            cost=9.0,
            time_cost=9.0,
        )

        OnlineTime.create(
            duration=60,
            start_timestamp=self.start - datetime.timedelta(minutes=30),
            end_timestamp=self.start + datetime.timedelta(minutes=30),
        )
        OnlineTime.create(
            duration=30,
            start_timestamp=self.now - datetime.timedelta(minutes=15),
            end_timestamp=self.now + datetime.timedelta(minutes=15),
        )

        self.create_message("m1", self.now - datetime.timedelta(hours=1), reply_to=None)
        self.create_message("m2", self.now - datetime.timedelta(minutes=20), reply_to="m1")
        self.create_message("old", self.now - datetime.timedelta(hours=5), reply_to=None)

    async def test_summary_statistics_aggregate_usage_online_time_messages_and_derived_rates(self) -> None:
        self.seed_statistics_data()

        summary = await statistics_routes._get_summary_statistics(self.start, self.now)

        self.assertEqual(summary.total_requests, 2)
        self.assertAlmostEqual(summary.total_cost, 0.5)
        self.assertEqual(summary.total_tokens, 22)
        self.assertAlmostEqual(summary.avg_response_time, 1.0)
        self.assertEqual(summary.total_messages, 2)
        self.assertEqual(summary.total_replies, 1)
        self.assertEqual(summary.online_time, 2700.0)
        self.assertAlmostEqual(summary.cost_per_hour, 0.5 / 0.75)
        self.assertAlmostEqual(summary.tokens_per_hour, 22 / 0.75)

    async def test_model_time_series_and_recent_activity_statistics_use_database_ordering(self) -> None:
        self.seed_statistics_data()

        model_stats = await statistics_routes._get_model_statistics(self.start)
        hourly = await statistics_routes._get_hourly_statistics(self.start, self.now)
        daily = await statistics_routes._get_daily_statistics(self.now - datetime.timedelta(days=1), self.now)
        recent = await statistics_routes._get_recent_activity(limit=2)

        stats_by_name = {item.model_name: item for item in model_stats}
        self.assertEqual(stats_by_name["replyer"].request_count, 1)
        self.assertEqual(stats_by_name["replyer"].total_tokens, 15)
        self.assertEqual(stats_by_name["gpt-3.5"].request_count, 1)
        self.assertEqual(stats_by_name["gpt-3.5"].total_cost, 0.3)

        hourly_by_timestamp = {item.timestamp: item for item in hourly}
        self.assertEqual(hourly_by_timestamp["2026-01-02T10:00:00"].requests, 0)
        self.assertEqual(hourly_by_timestamp["2026-01-02T11:00:00"].requests, 1)
        self.assertEqual(hourly_by_timestamp["2026-01-02T11:00:00"].tokens, 15)
        self.assertEqual(hourly_by_timestamp["2026-01-02T12:00:00"].requests, 1)

        daily_by_timestamp = {item.timestamp: item for item in daily}
        self.assertEqual(daily_by_timestamp["2026-01-01T00:00:00"].requests, 0)
        self.assertEqual(daily_by_timestamp["2026-01-02T00:00:00"].requests, 3)

        self.assertEqual([item["model"] for item in recent], ["gpt-3.5", "replyer"])
        self.assertEqual(recent[0]["request_type"], "embedding")
        self.assertEqual(recent[0]["tokens"], 7)

    async def test_route_wrappers_use_current_time_and_return_dashboard_summary_and_model_stats(self) -> None:
        self.seed_statistics_data()

        class FixedDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return self.now

        with patch.object(statistics_routes, "datetime", FixedDateTime):
            summary = await statistics_routes.get_summary(hours=2, _auth=True)
            model_stats = await statistics_routes.get_model_stats(hours=2, _auth=True)
            dashboard = await statistics_routes.get_dashboard_data(hours=2, _auth=True)

        self.assertEqual(summary.total_requests, 2)
        self.assertEqual({item.model_name for item in model_stats}, {"replyer", "gpt-3.5"})
        self.assertEqual(dashboard.summary.total_messages, 2)
        self.assertEqual(len(dashboard.recent_activity), 3)
        self.assertGreaterEqual(len(dashboard.hourly_data), 3)
        self.assertGreaterEqual(len(dashboard.daily_data), 7)

    def test_require_auth_delegates_to_shared_auth_checker(self) -> None:
        with patch.object(statistics_routes, "verify_auth_token_from_cookie_or_header", return_value=True) as verify:
            self.assertTrue(statistics_routes.require_auth("cookie", "Bearer token"))

        verify.assert_called_once_with("cookie", "Bearer token")


if __name__ == "__main__":
    unittest.main()
