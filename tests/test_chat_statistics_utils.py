import unittest
from collections import defaultdict
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from src.chat.utils import statistic


class FakeQuery(list):
    def where(self, *_args, **_kwargs):
        return self


def make_task() -> statistic.StatisticOutputTask:
    task = object.__new__(statistic.StatisticOutputTask)
    task.name_mapping = {}
    task.stat_period = []
    return task


def make_stats() -> dict:
    stats = {
        statistic.TOTAL_REQ_CNT: 2,
        statistic.TOTAL_COST: 3.0,
        statistic.TOTAL_MSG_CNT: 4,
        statistic.TOTAL_REPLY_CNT: 2,
        statistic.ONLINE_TIME: 3600,
        statistic.REQ_CNT_BY_MODEL: {"model-a": 2},
        statistic.REQ_CNT_BY_MODULE: {"replyer": 2},
        statistic.IN_TOK_BY_MODEL: {"model-a": 10000},
        statistic.IN_TOK_BY_MODULE: {"replyer": 10000},
        statistic.OUT_TOK_BY_MODEL: {"model-a": 5000},
        statistic.OUT_TOK_BY_MODULE: {"replyer": 5000},
        statistic.TOTAL_TOK_BY_MODEL: {"model-a": 15000},
        statistic.TOTAL_TOK_BY_MODULE: {"replyer": 15000},
        statistic.COST_BY_MODEL: {"model-a": 3.0},
        statistic.COST_BY_MODULE: {"replyer": 3.0},
        statistic.AVG_TIME_COST_BY_MODEL: {"model-a": 1.25},
        statistic.AVG_TIME_COST_BY_MODULE: {"replyer": 1.25},
        statistic.STD_TIME_COST_BY_MODEL: {"model-a": 0.25},
        statistic.STD_TIME_COST_BY_MODULE: {"replyer": 0.25},
        statistic.MSG_CNT_BY_CHAT: {"g1": 3, "u2": 1},
    }
    return stats


class StatisticFormattingTest(unittest.TestCase):
    def test_legacy_static_html_report_generator_is_removed(self) -> None:
        html_report_methods = (
            "_generate_html_report",
            "_generate_chart_data",
            "_collect_interval_data",
            "_generate_chart_tab",
            "_generate_metrics_data",
            "_collect_metrics_interval_data",
            "_generate_metrics_tab",
            "_get_chat_display_name_from_id",
        )

        for task_type in (statistic.StatisticOutputTask, statistic.AsyncStatisticOutputTask):
            for method_name in html_report_methods:
                self.assertFalse(hasattr(task_type, method_name), method_name)

    def test_statistics_task_outputs_console_summary(self) -> None:
        task = make_task()
        collected = {"last_hour": make_stats()}

        with (
            patch.object(task, "_collect_all_statistics", return_value=collected),
            patch.object(task, "_statistic_console_output") as console_output,
        ):
            import asyncio

            asyncio.run(task.run())

        console_output.assert_called_once()

    def test_online_time_large_number_and_stat_formatters_cover_non_empty_and_empty_paths(self) -> None:
        self.assertEqual(statistic._format_online_time(59), "0分钟59秒")
        self.assertEqual(statistic._format_online_time(3661), "1小时1分钟1秒")
        self.assertEqual(statistic._format_online_time(90061), "1天1小时1分钟1秒")
        self.assertEqual(statistic._format_large_number(9999), "9999")
        self.assertEqual(statistic._format_large_number(10000), "10K")
        self.assertEqual(statistic._format_large_number(12345), "12K")
        self.assertEqual(statistic._format_large_number(12.5), "12.5")
        self.assertEqual(statistic._format_large_number(12.0), "12")

        task = make_task()
        task.name_mapping = {"g1": ("群聊", 100.0), "u2": ("Alice", 101.0)}
        stats = make_stats()

        total = task._format_total_stat(stats)
        self.assertIn("总在线时间: 1小时0分钟0秒", total)
        self.assertIn("总Token数: 15K", total)
        self.assertIn("花费/回复消息数量: 150.0000¥/100条", total)

        model_text = task._format_model_classified_stat(stats)
        module_text = task._format_module_classified_stat(stats)
        chat_text = task._format_chat_stat(stats)

        self.assertIn("按模型分类统计", model_text)
        self.assertIn("model-a", model_text)
        self.assertIn("按模块分类统计", module_text)
        self.assertIn("replyer", module_text)
        self.assertIn("群聊", chat_text)
        self.assertIn("Alice", chat_text)

        empty = make_stats()
        empty[statistic.TOTAL_REQ_CNT] = 0
        empty[statistic.TOTAL_MSG_CNT] = 0
        self.assertEqual(task._format_model_classified_stat(empty), "")
        self.assertEqual(task._format_module_classified_stat(empty), "")
        self.assertEqual(task._format_chat_stat(empty), "")

    def test_convert_defaultdict_to_dict_recursively(self) -> None:
        task = make_task()
        nested = defaultdict(lambda: defaultdict(int))
        nested["outer"]["inner"] = 2
        self.assertEqual(task._convert_defaultdict_to_dict(nested), {"outer": {"inner": 2}})


class StatisticCollectionTest(unittest.TestCase):
    def test_collect_model_request_for_period_aggregates_counts_tokens_costs_and_time_stats(self) -> None:
        now = datetime(2026, 1, 2, 12, 0, 0)
        periods = [
            ("last_day", now - timedelta(days=1)),
            ("last_hour", now - timedelta(hours=1)),
        ]
        records = FakeQuery(
            [
                SimpleNamespace(
                    timestamp=now - timedelta(minutes=30),
                    request_type="replyer.main",
                    user_id="user-1",
                    model_assign_name="alias-a",
                    model_name="model-a",
                    prompt_tokens=10,
                    completion_tokens=5,
                    cost=0.5,
                    time_cost=1.0,
                ),
                SimpleNamespace(
                    timestamp=now - timedelta(minutes=90),
                    request_type="planner",
                    user_id="user-2",
                    model_assign_name="",
                    model_name="model-b",
                    prompt_tokens=20,
                    completion_tokens=10,
                    cost=1.0,
                    time_cost=3.0,
                ),
                SimpleNamespace(
                    timestamp=now - timedelta(minutes=20),
                    request_type="replyer.main",
                    user_id="user-1",
                    model_assign_name="alias-a",
                    model_name="model-a",
                    prompt_tokens=30,
                    completion_tokens=15,
                    cost=1.5,
                    time_cost=2.0,
                ),
            ]
        )

        with patch.object(statistic.LLMUsage, "select", return_value=records):
            collected = statistic.StatisticOutputTask._collect_model_request_for_period(periods)

        self.assertEqual(collected["last_hour"][statistic.TOTAL_REQ_CNT], 2)
        self.assertEqual(collected["last_day"][statistic.TOTAL_REQ_CNT], 3)
        self.assertEqual(collected["last_hour"][statistic.REQ_CNT_BY_MODULE]["replyer"], 2)
        self.assertEqual(collected["last_day"][statistic.REQ_CNT_BY_MODULE]["planner"], 1)
        self.assertEqual(collected["last_hour"][statistic.TOTAL_TOK_BY_MODEL]["alias-a"], 60)
        self.assertEqual(collected["last_day"][statistic.TOTAL_COST], 3.0)
        self.assertEqual(collected["last_hour"][statistic.AVG_TIME_COST_BY_MODEL]["alias-a"], 1.5)
        self.assertEqual(collected["last_hour"][statistic.STD_TIME_COST_BY_MODEL]["alias-a"], 0.5)

    def test_collect_online_time_counts_only_period_overlap(self) -> None:
        now = datetime(2026, 1, 2, 12, 0, 0)
        periods = [
            ("last_day", now - timedelta(days=1)),
            ("last_hour", now - timedelta(hours=1)),
        ]
        records = FakeQuery(
            [
                SimpleNamespace(
                    start_timestamp=now - timedelta(minutes=90),
                    end_timestamp=now - timedelta(minutes=30),
                ),
                SimpleNamespace(
                    start_timestamp=now - timedelta(minutes=10),
                    end_timestamp=now + timedelta(minutes=10),
                ),
            ]
        )

        with patch.object(statistic.OnlineTime, "select", return_value=records):
            collected = statistic.StatisticOutputTask._collect_online_time_for_period(periods, now)

        self.assertEqual(collected["last_hour"][statistic.ONLINE_TIME], 40 * 60)
        self.assertEqual(collected["last_day"][statistic.ONLINE_TIME], 70 * 60)

    def test_collect_message_counts_updates_names_and_counts_reply_actions(self) -> None:
        now = datetime(2026, 1, 2, 12, 0, 0)
        periods = [
            ("last_day", now - timedelta(days=1)),
            ("last_hour", now - timedelta(hours=1)),
        ]
        messages = FakeQuery(
            [
                SimpleNamespace(
                    time=(now - timedelta(minutes=30)).timestamp(),
                    chat_info_group_id="100",
                    chat_info_group_name="Group",
                    user_id="user-1",
                    user_nickname="Alice",
                ),
                SimpleNamespace(
                    time=(now - timedelta(hours=2)).timestamp(),
                    chat_info_group_id=None,
                    chat_info_group_name=None,
                    user_id="user-2",
                    user_nickname="Bob",
                ),
                SimpleNamespace(
                    id=3,
                    time=(now - timedelta(minutes=10)).timestamp(),
                    chat_info_group_id=None,
                    chat_info_group_name=None,
                    user_id="",
                    user_nickname="",
                ),
            ]
        )
        actions = FakeQuery(
            [
                SimpleNamespace(
                    time=(now - timedelta(minutes=20)).timestamp(),
                    action_name="reply",
                    action_done=True,
                ),
                SimpleNamespace(
                    time=(now - timedelta(minutes=10)).timestamp(),
                    action_name="reply",
                    action_done=False,
                ),
                SimpleNamespace(
                    time=(now - timedelta(minutes=10)).timestamp(),
                    action_name="emoji",
                    action_done=True,
                ),
            ]
        )
        task = make_task()

        with (
            patch.object(statistic.Messages, "select", return_value=messages),
            patch.object(statistic.ActionRecords, "select", return_value=actions),
        ):
            collected = task._collect_message_count_for_period(periods)

        self.assertEqual(collected["last_hour"][statistic.TOTAL_MSG_CNT], 1)
        self.assertEqual(collected["last_day"][statistic.TOTAL_MSG_CNT], 2)
        self.assertEqual(collected["last_day"][statistic.MSG_CNT_BY_CHAT]["g100"], 1)
        self.assertEqual(collected["last_day"][statistic.MSG_CNT_BY_CHAT]["uuser-2"], 1)
        self.assertEqual(collected["last_hour"][statistic.TOTAL_REPLY_CNT], 1)
        self.assertEqual(task.name_mapping["g100"][0], "Group")
        self.assertEqual(task.name_mapping["uuser-2"][0], "Bob")


if __name__ == "__main__":
    unittest.main()
