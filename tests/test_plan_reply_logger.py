import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.chat.logger import plan_reply_logger
from src.chat.logger.plan_reply_logger import PlanReplyLogger


class PlanReplyLoggerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base_dir = Path(self.tmp.name)
        self.plan_dir = self.base_dir / "plan"
        self.reply_dir = self.base_dir / "reply"

        self.patchers = [
            patch.object(PlanReplyLogger, "_BASE_DIR", self.base_dir),
            patch.object(PlanReplyLogger, "_PLAN_DIR", self.plan_dir),
            patch.object(PlanReplyLogger, "_REPLY_DIR", self.reply_dir),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def read_single_json(self, directory: Path) -> dict:
        files = list(directory.glob("*.json"))
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text(encoding="utf-8"))

    def test_log_plan_writes_serialized_action_payload_and_safe_extra_data(self) -> None:
        user_info = SimpleNamespace(user_id="user-1", platform="qq")
        action_message = SimpleNamespace(
            message_id="msg-1",
            user_info=user_info,
            processed_plain_text="hello",
        )
        action = SimpleNamespace(
            action_type="reply",
            reasoning="because",
            action_data={"path": Path("data/file.txt"), "tags": {"a", "b"}},
            action_message=action_message,
            available_actions=("reply", "wait"),
            action_reasoning="chosen",
        )

        with (
            patch.object(plan_reply_logger.time, "time", return_value=1234.567),
            patch.object(plan_reply_logger, "uuid4", return_value=SimpleNamespace(hex="abcdef1234567890")),
            patch.object(PlanReplyLogger, "_get_max_per_chat", return_value=1000),
        ):
            PlanReplyLogger.log_plan(
                chat_id="stream-1",
                prompt="prompt",
                reasoning="reasoning",
                raw_output="{raw}",
                raw_reasoning="raw reasoning",
                actions=[action],
                timing={"total_plan_ms": 12.5},
                extra={"complex": object()},
            )

        payload = self.read_single_json(self.plan_dir / "stream-1")

        self.assertEqual(payload["type"], "plan")
        self.assertEqual(payload["chat_id"], "stream-1")
        self.assertEqual(payload["timestamp"], 1234.567)
        self.assertEqual(payload["prompt"], "prompt")
        self.assertEqual(payload["timing"], {"total_plan_ms": 12.5})
        self.assertIn("complex", payload["extra"])
        self.assertEqual(payload["actions"][0]["action_type"], "reply")
        self.assertEqual(payload["actions"][0]["action_data"]["path"], "data/file.txt")
        self.assertEqual(sorted(payload["actions"][0]["action_data"]["tags"]), ["a", "b"])
        self.assertEqual(
            payload["actions"][0]["action_message"],
            {"message_id": "msg-1", "user_id": "user-1", "platform": "qq", "text": "hello"},
        )
        self.assertEqual(payload["actions"][0]["available_actions"], ["reply", "wait"])

        written_file = next((self.plan_dir / "stream-1").glob("*.json"))
        self.assertEqual(written_file.name, "1234567_abcdef12.json")

    def test_log_reply_writes_success_and_failure_payloads(self) -> None:
        with (
            patch.object(plan_reply_logger.time, "time", side_effect=[2000.0, 2000.0, 2001.0, 2001.0]),
            patch.object(
                plan_reply_logger,
                "uuid4",
                side_effect=[
                    SimpleNamespace(hex="11111111aaaaaaaa"),
                    SimpleNamespace(hex="22222222bbbbbbbb"),
                ],
            ),
            patch.object(PlanReplyLogger, "_get_max_per_chat", return_value=1000),
        ):
            PlanReplyLogger.log_reply(
                chat_id="stream-1",
                prompt="prompt",
                output="hello",
                processed_output=["hello", Path("asset.png")],
                model="model-a",
                timing={"llm_ms": 3.0},
                reasoning="reason",
                think_level=2,
                error="ignored",
                success=True,
            )
            PlanReplyLogger.log_reply(
                chat_id="stream-1",
                prompt="prompt",
                output=None,
                processed_output=None,
                model=None,
                error="failed",
                success=False,
            )

        files = sorted((self.reply_dir / "stream-1").glob("*.json"))
        success_payload = json.loads(files[0].read_text(encoding="utf-8"))
        failure_payload = json.loads(files[1].read_text(encoding="utf-8"))

        self.assertEqual(success_payload["type"], "reply")
        self.assertEqual(success_payload["error"], None)
        self.assertTrue(success_payload["success"])
        self.assertEqual(success_payload["processed_output"], ["hello", "asset.png"])
        self.assertEqual(success_payload["model"], "model-a")
        self.assertEqual(success_payload["think_level"], 2)
        self.assertEqual(failure_payload["error"], "failed")
        self.assertFalse(failure_payload["success"])
        self.assertIsNone(failure_payload["processed_output"])

    def test_trim_overflow_removes_oldest_trim_count_files_when_limit_is_exceeded(self) -> None:
        chat_dir = self.plan_dir / "stream-1"
        chat_dir.mkdir(parents=True)
        files = []
        for index in range(5):
            path = chat_dir / f"{index}.json"
            path.write_text("{}", encoding="utf-8")
            os.utime(path, (index, index))
            files.append(path)

        with (
            patch.object(PlanReplyLogger, "_get_max_per_chat", return_value=3),
            patch.object(PlanReplyLogger, "_TRIM_COUNT", 2),
        ):
            PlanReplyLogger._trim_overflow(chat_dir)

        self.assertFalse(files[0].exists())
        self.assertFalse(files[1].exists())
        self.assertEqual(sorted(path.name for path in chat_dir.glob("*.json")), ["2.json", "3.json", "4.json"])

    def test_safe_data_converts_nested_complex_values_to_json_compatible_shapes(self) -> None:
        value = {
            Path("key"): {
                "tuple": (Path("a"), object()),
                "set": {"x", "y"},
                "none": None,
            }
        }

        safe = PlanReplyLogger._safe_data(value)

        self.assertEqual(list(safe.keys()), ["key"])
        self.assertEqual(safe["key"]["tuple"][0], "a")
        self.assertEqual(sorted(safe["key"]["set"]), ["x", "y"])
        self.assertIsNone(safe["key"]["none"])
        self.assertIsInstance(safe["key"]["tuple"][1], str)


if __name__ == "__main__":
    unittest.main()
