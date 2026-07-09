import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from src.webui.api import planner, replier


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def write_bad_json(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{bad json", encoding="utf-8")


class PlannerApiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plan_dir = Path(self.tmp.name) / "plan"
        self.plan_patcher = patch.object(planner, "PLAN_LOG_DIR", self.plan_dir)
        self.plan_patcher.start()
        self.addCleanup(self.plan_patcher.stop)

    def seed_plan_logs(self) -> None:
        write_json(
            self.plan_dir / "chat-a" / "2000000000000_new.json",
            {
                "type": "plan",
                "chat_id": "chat-a",
                "timestamp": 2000.0,
                "prompt": "please find keyword",
                "reasoning": "reasoning-new" * 20,
                "raw_output": "{}",
                "actions": [{"action_type": "reply"}, {"action_type": "wait"}, {"ignored": True}],
                "timing": {"total_plan_ms": 12.5, "llm_duration_ms": 9.0},
                "extra": {"trace": "new"},
            },
        )
        write_bad_json(self.plan_dir / "chat-a" / "1500000000000_bad.json")
        write_json(
            self.plan_dir / "chat-a" / "1000000000000_old.json",
            {
                "type": "plan",
                "chat_id": "chat-a",
                "timestamp": 1000.0,
                "prompt": "old prompt",
                "reasoning": "old",
                "raw_output": "{}",
                "actions": [],
                "timing": {"total_plan_ms": 3.0, "llm_duration_ms": 2.0},
            },
        )
        write_json(
            self.plan_dir / "chat-b" / "3000000000000_latest.json",
            {
                "type": "plan",
                "chat_id": "chat-b",
                "timestamp": 3000.0,
                "prompt": "chat b",
                "reasoning": "b",
                "raw_output": "{}",
                "actions": [{"action_type": "observe"}],
                "timing": {"total_plan_ms": 4.0, "llm_duration_ms": 1.0},
            },
        )
        (self.plan_dir / "chat-empty").mkdir(parents=True, exist_ok=True)
        (self.plan_dir / "not-a-chat.txt").write_text("ignored", encoding="utf-8")

    async def test_planner_overview_lists_chats_by_latest_timestamp(self) -> None:
        self.assertEqual(planner.parse_timestamp_from_filename("bad.json"), 0)
        empty = await planner.get_planner_overview()
        self.assertEqual(empty.total_chats, 0)
        self.assertEqual(empty.total_plans, 0)

        self.seed_plan_logs()
        overview = await planner.get_planner_overview()

        self.assertEqual(overview.total_chats, 2)
        self.assertEqual(overview.total_plans, 4)
        self.assertEqual([chat.chat_id for chat in overview.chats], ["chat-b", "chat-a"])
        self.assertEqual(overview.chats[0].latest_filename, "3000000000000_latest.json")
        self.assertEqual(overview.chats[0].latest_timestamp, 3000000000.0)

    async def test_planner_log_list_search_detail_and_compat_routes(self) -> None:
        self.seed_plan_logs()

        logs = await planner.get_chat_plan_logs("chat-a", page=1, page_size=2, search=None)
        searched = await planner.get_chat_plan_logs("chat-a", page=1, page_size=10, search="KEYWORD")
        missing_chat = await planner.get_chat_plan_logs("missing", page=1, page_size=10, search=None)
        detail = await planner.get_log_detail("chat-a", "2000000000000_new.json")
        stats = await planner.get_planner_stats()
        chat_ids = await planner.get_chat_list()
        all_logs = await planner.get_all_logs(page=1, page_size=10)

        self.assertEqual(logs.total, 3)
        self.assertEqual([item.filename for item in logs.data], ["2000000000000_new.json", "1500000000000_bad.json"])
        self.assertEqual(logs.data[0].action_count, 3)
        self.assertEqual(logs.data[0].action_types, ["reply", "wait"])
        self.assertEqual(logs.data[0].total_plan_ms, 12.5)
        self.assertTrue(logs.data[0].reasoning_preview.startswith("reasoning-new"))
        self.assertEqual(logs.data[1].reasoning_preview, "[读取失败]")
        self.assertEqual([item.filename for item in searched.data], ["2000000000000_new.json"])
        self.assertEqual(missing_chat.total, 0)
        self.assertEqual(detail.extra, {"trace": "new"})
        self.assertEqual(stats["total_chats"], 2)
        self.assertEqual(stats["total_plans"], 4)
        self.assertEqual(chat_ids, ["chat-b", "chat-a"])
        self.assertEqual(all_logs["total"], 4)
        self.assertEqual([item["chat_id"] for item in all_logs["data"]], ["chat-b", "chat-a", "chat-a"])

        with self.assertRaises(HTTPException) as missing_detail:
            await planner.get_log_detail("chat-a", "missing.json")
        self.assertEqual(missing_detail.exception.status_code, 404)

        with self.assertRaises(HTTPException) as bad_detail:
            await planner.get_log_detail("chat-a", "1500000000000_bad.json")
        self.assertEqual(bad_detail.exception.status_code, 500)


class ReplierApiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.reply_dir = Path(self.tmp.name) / "reply"
        self.reply_patcher = patch.object(replier, "REPLY_LOG_DIR", self.reply_dir)
        self.reply_patcher.start()
        self.addCleanup(self.reply_patcher.stop)

    def seed_reply_logs(self) -> None:
        write_json(
            self.reply_dir / "chat-a" / "2000000000000_new.json",
            {
                "type": "reply",
                "chat_id": "chat-a",
                "timestamp": 2000.0,
                "prompt": "please answer keyword",
                "output": "output-new" * 20,
                "processed_output": ["output-new"],
                "model": "gpt-test",
                "reasoning": "reasoning",
                "think_level": 2,
                "timing": {"llm_ms": 11.0, "overall_ms": 14.0},
                "success": True,
            },
        )
        write_bad_json(self.reply_dir / "chat-a" / "1500000000000_bad.json")
        write_json(
            self.reply_dir / "chat-a" / "1000000000000_old.json",
            {
                "type": "reply",
                "chat_id": "chat-a",
                "timestamp": 1000.0,
                "prompt": "old prompt",
                "output": "old",
                "processed_output": ["old"],
                "model": "gpt-old",
                "reasoning": "",
                "think_level": 1,
                "timing": {"llm_ms": 1.0, "overall_ms": 2.0},
                "success": False,
                "error": "failed",
            },
        )
        write_json(
            self.reply_dir / "chat-b" / "3000000000000_latest.json",
            {
                "type": "reply",
                "chat_id": "chat-b",
                "timestamp": 3000.0,
                "prompt": "chat b",
                "output": "b",
                "processed_output": ["b"],
                "model": "gpt-b",
                "reasoning": "",
                "think_level": 0,
                "timing": {"llm_ms": 3.0, "overall_ms": 4.0},
                "success": True,
            },
        )

    async def test_replier_overview_lists_chats_by_latest_timestamp(self) -> None:
        self.assertEqual(replier.parse_timestamp_from_filename("bad.json"), 0)
        empty = await replier.get_replier_overview()
        self.assertEqual(empty.total_chats, 0)
        self.assertEqual(empty.total_replies, 0)

        self.seed_reply_logs()
        overview = await replier.get_replier_overview()

        self.assertEqual(overview.total_chats, 2)
        self.assertEqual(overview.total_replies, 4)
        self.assertEqual([chat.chat_id for chat in overview.chats], ["chat-b", "chat-a"])
        self.assertEqual(overview.chats[1].reply_count, 3)

    async def test_replier_log_list_search_detail_and_compat_routes(self) -> None:
        self.seed_reply_logs()

        logs = await replier.get_chat_reply_logs("chat-a", page=1, page_size=2, search=None)
        searched = await replier.get_chat_reply_logs("chat-a", page=1, page_size=10, search="KEYWORD")
        missing_chat = await replier.get_chat_reply_logs("missing", page=1, page_size=10, search=None)
        detail = await replier.get_reply_log_detail("chat-a", "2000000000000_new.json")
        stats = await replier.get_replier_stats()
        chat_ids = await replier.get_replier_chat_list()

        self.assertEqual(logs.total, 3)
        self.assertEqual([item.filename for item in logs.data], ["2000000000000_new.json", "1500000000000_bad.json"])
        self.assertEqual(logs.data[0].model, "gpt-test")
        self.assertEqual(logs.data[0].llm_ms, 11.0)
        self.assertTrue(logs.data[0].output_preview.startswith("output-new"))
        self.assertFalse(logs.data[1].success)
        self.assertEqual(logs.data[1].output_preview, "[读取失败]")
        self.assertEqual([item.filename for item in searched.data], ["2000000000000_new.json"])
        self.assertEqual(missing_chat.total, 0)
        self.assertEqual(detail.processed_output, ["output-new"])
        self.assertEqual(detail.think_level, 2)
        self.assertTrue(detail.success)
        self.assertEqual(stats["total_chats"], 2)
        self.assertEqual(stats["total_replies"], 4)
        self.assertEqual(chat_ids, ["chat-b", "chat-a"])

        with self.assertRaises(HTTPException) as missing_detail:
            await replier.get_reply_log_detail("chat-a", "missing.json")
        self.assertEqual(missing_detail.exception.status_code, 404)

        with self.assertRaises(HTTPException) as bad_detail:
            await replier.get_reply_log_detail("chat-a", "1500000000000_bad.json")
        self.assertEqual(bad_detail.exception.status_code, 500)
