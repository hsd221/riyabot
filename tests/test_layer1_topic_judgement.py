from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from src.memory.layer1_summarizer import GroupTopicSummarizer, JudgedTopicSegment, UnclosedTopicBridge


def _msg(message_id: str, text: str, user_id: str = "user-1", timestamp: float = 1.0) -> dict:
    return {
        "message_id": message_id,
        "text": text,
        "user_id": user_id,
        "speaker": user_id,
        "timestamp": timestamp,
    }


class FakeTopicJudge:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def judge(self, messages):
        message_ids = [msg.message_id for msg in messages]
        self.calls.append(message_ids)
        if len(self.calls) == 1:
            return [
                JudgedTopicSegment(
                    topic_title="dinner plan",
                    start_message_id="m1",
                    end_message_id="m2",
                    is_closed=True,
                    summary="Users finished discussing dinner.",
                ),
                JudgedTopicSegment(
                    topic_title="exam schedule",
                    start_message_id="m3",
                    end_message_id="m3",
                    is_closed=False,
                    summary="The exam schedule topic is still continuing.",
                ),
            ]
        return [
            JudgedTopicSegment(
                topic_title="exam schedule",
                start_message_id="m3",
                end_message_id="m4",
                is_closed=True,
                summary="The exam schedule discussion has ended.",
            ),
            JudgedTopicSegment(
                topic_title="lunch",
                start_message_id="m5",
                end_message_id="m6",
                is_closed=False,
                summary="Users are still discussing lunch.",
            ),
        ]


class GroupTopicJudgementTest(unittest.IsolatedAsyncioTestCase):
    async def test_unclosed_tail_is_rejudged_with_the_next_batch(self) -> None:
        judge = FakeTopicJudge()
        summarizer = GroupTopicSummarizer(judge_trigger_count=3, topic_judge=judge)

        await summarizer.add_messages(
            "group-1",
            [
                _msg("m1", "pizza or noodles", "alice", 1.0),
                _msg("m2", "pizza is fine", "bob", 2.0),
                _msg("m3", "when is tomorrow exam", "alice", 3.0),
            ],
        )

        self.assertEqual(judge.calls, [["m1", "m2", "m3"]])
        summaries = summarizer.get_topic_summaries("group-1")
        self.assertEqual(
            [
                (item["topic_title"], item["start_message_id"], item["end_message_id"], item["is_closed"])
                for item in summaries
            ],
            [
                ("dinner plan", "m1", "m2", True),
                ("exam schedule", "m3", "m3", False),
            ],
        )
        self.assertEqual(
            [item["message_id"] for item in summarizer.get_open_topic_messages("group-1")],
            ["m3"],
        )

        await summarizer.add_messages(
            "group-1",
            [
                _msg("m4", "the exam starts at nine", "bob", 4.0),
                _msg("m5", "what do we eat for lunch", "carol", 5.0),
                _msg("m6", "maybe sandwiches", "alice", 6.0),
            ],
        )

        self.assertEqual(judge.calls[1], ["m3", "m4", "m5", "m6"])
        summaries = summarizer.get_topic_summaries("group-1")
        self.assertEqual(
            [
                (item["topic_title"], item["start_message_id"], item["end_message_id"], item["is_closed"])
                for item in summaries
            ],
            [
                ("dinner plan", "m1", "m2", True),
                ("exam schedule", "m3", "m4", True),
                ("lunch", "m5", "m6", False),
            ],
        )
        self.assertEqual(
            [item["message_id"] for item in summarizer.get_open_topic_messages("group-1")],
            ["m5", "m6"],
        )

    async def test_batch_judge_waits_until_trigger_count(self) -> None:
        judge = FakeTopicJudge()
        summarizer = GroupTopicSummarizer(judge_trigger_count=3, topic_judge=judge)

        await summarizer.add_messages(
            "group-1",
            [
                _msg("m1", "one pending message", "alice", 1.0),
                _msg("m2", "two pending messages", "bob", 2.0),
            ],
        )

        self.assertEqual(judge.calls, [])
        self.assertEqual(summarizer.get_topic_summaries("group-1"), [])

    async def test_bridge_restores_unclosed_tail_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            old_data_dir = UnclosedTopicBridge._DATA_DIR
            old_file_path = UnclosedTopicBridge._FILE_PATH
            UnclosedTopicBridge._DATA_DIR = tmpdir
            UnclosedTopicBridge._FILE_PATH = str(Path(tmpdir) / "topic_bridge.json")
            try:
                judge = FakeTopicJudge()
                summarizer = GroupTopicSummarizer(judge_trigger_count=3, topic_judge=judge)
                now = time.time()
                await summarizer.add_messages(
                    "group-1",
                    [
                        _msg("m1", "pizza or noodles", "alice", now - 2),
                        _msg("m2", "pizza is fine", "bob", now - 1),
                        _msg("m3", "when is tomorrow exam", "alice", now),
                    ],
                )

                bridge = UnclosedTopicBridge()
                bridge.save_unclosed_topics("group-1", summarizer.get_topic_summaries("group-1"))
                restored = UnclosedTopicBridge().restore_topics("group-1")

                restored_summarizer = GroupTopicSummarizer(judge_trigger_count=3, topic_judge=FakeTopicJudge())
                restored_summarizer.restore_unclosed_topics("group-1", restored)

                self.assertEqual(
                    [item["message_id"] for item in restored_summarizer.get_open_topic_messages("group-1")],
                    ["m3"],
                )
            finally:
                UnclosedTopicBridge._DATA_DIR = old_data_dir
                UnclosedTopicBridge._FILE_PATH = old_file_path


if __name__ == "__main__":
    unittest.main()
