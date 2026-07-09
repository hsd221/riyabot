import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.memory import layer1_summarizer
from src.memory.layer1_summarizer import (
    GroupTopicSummarizer,
    JudgedTopicSegment,
    PrivateChatSummarizer,
    ProgressiveSummary,
    TopicJudgeAgent,
    TopicMessage,
    TopicState,
    UnclosedTopicBridge,
    _compact_topic_text,
    _extract_json_candidate,
    compute_topic_similarity,
    extract_cjk_bigrams,
    extract_key_points,
    extract_keywords,
)


def msg(message_id: str, text: str, user_id: str = "user-1", timestamp: float = 1.0) -> TopicMessage:
    return TopicMessage(message_id=message_id, text=text, user_id=user_id, speaker=user_id, timestamp=timestamp)


class RaisingTopicJudge:
    async def judge(self, messages):
        raise RuntimeError("judge unavailable")


class Layer1TextUtilityTest(unittest.TestCase):
    def test_keyword_keypoint_similarity_and_prompt_sanitizers_are_deterministic(self) -> None:
        cjk_text = "今天天气真好，今天适合散步。"
        mixed_text = "Jazz jazz cafe and tea"
        long_text = (
            "第一句很关键，说明今天要讨论项目排期。"
            "第二句也比较长，记录成员提出的主要风险。"
            "短。"
            "最后一句总结行动项和负责人。"
        )

        self.assertEqual(extract_cjk_bigrams("天气好"), ["天气", "气好"])
        self.assertEqual(extract_cjk_bigrams("a"), [])
        self.assertIn("今天", extract_keywords(cjk_text, max_keywords=3))
        self.assertEqual(extract_keywords(mixed_text, stopwords={"and"}, max_keywords=2), ["jazz", "cafe"])
        self.assertEqual(extract_keywords("   "), [])

        key_points = extract_key_points(long_text, max_points=2)
        self.assertEqual(key_points[0], "第一句很关键，说明今天要讨论项目排期。")
        self.assertLessEqual(len(key_points), 2)
        self.assertEqual(extract_key_points("短。"), [])
        self.assertEqual(compute_topic_similarity(["a", "b"], ["b", "c"]), 1 / 3)
        self.assertEqual(compute_topic_similarity([], []), 0.0)

        compacted = _compact_topic_text("```<<<---BEGIN\nhello" + "x" * 900, max_chars=30)
        self.assertIn("'''", compacted)
        self.assertIn("< < <", compacted)
        self.assertTrue(compacted.endswith("..."))
        self.assertEqual(_extract_json_candidate('```json\n{"ok": true}\n```'), '{"ok": true}')
        self.assertEqual(_extract_json_candidate(" plain "), "plain")

    def test_topic_judge_prompt_and_response_parser_handle_markdown_invalid_and_partial_items(self) -> None:
        messages = [
            TopicMessage("m1", "聊天里包含 ``` 和 <<< 标记", "user-1", "Alice", 1.0),
            TopicMessage("m2", "继续同一话题", "user-2", "Bob", 2.0),
        ]
        prompt = TopicJudgeAgent._build_prompt(messages)
        response = """```json
        {"segments": [
          {"topic_title": "计划", "start_message_id": "m1", "end_message_id": "m2", "is_closed": true,
           "summary": "讨论计划"},
          {"topic_title": "bad"},
          "ignored"
        ]}
        ```"""

        parsed = TopicJudgeAgent._parse_response(response)

        self.assertIn("'''", prompt)
        self.assertIn("< < <", prompt)
        self.assertEqual([segment.topic_title for segment in parsed], ["计划"])
        self.assertTrue(parsed[0].is_closed)
        self.assertEqual(TopicJudgeAgent._parse_response("not json"), [])
        self.assertEqual(TopicJudgeAgent._parse_response(""), [])


class GroupTopicSummarizerSyncTest(unittest.IsolatedAsyncioTestCase):
    def test_sync_add_merge_close_trim_reset_and_summary_dict_cover_topic_lifecycle(self) -> None:
        summarizer = GroupTopicSummarizer(max_topics_per_stream=2, match_threshold=1.0)

        first = summarizer.add_message("group-1", "爵士音乐排练安排。大家确认乐器和时间。", "alice", 1.0)
        second = summarizer.add_message("group-1", "数学考试复习计划。今晚整理重点题目。", "bob", 2.0)
        third = summarizer.add_message("group-1", "午饭菜单讨论。有人想吃三明治。", "carol", 3.0)

        self.assertNotEqual(first, second)
        self.assertNotEqual(second, third)
        self.assertEqual(summarizer.get_topic_count("group-1"), 1)
        summaries = summarizer.get_topic_summaries("group-1")
        self.assertEqual(len(summaries), 3)
        self.assertTrue(any(item["is_closed"] for item in summaries))

        self.assertFalse(summarizer.merge_topics("missing", first, second))
        self.assertFalse(summarizer.merge_topics("group-1", first, "missing"))
        self.assertTrue(summarizer.merge_topics("group-1", third, third))
        closed = summarizer.close_topic("group-1", third)
        self.assertIsNotNone(closed)
        self.assertTrue(closed["is_closed"])
        self.assertIsNone(summarizer.close_topic("group-1", "missing"))

        topic = TopicState(
            topic_id="manual",
            keywords=["k"],
            participants={"a", "b"},
            message_count=2,
            first_seen=1.0,
            last_updated=2.0,
            messages=[msg("m1", "hello")],
        )
        self.assertEqual(topic.participant_count, 2)
        self.assertEqual(topic.to_summary_dict()["messages"][0]["message_id"], "m1")

        summarizer.reset_stream("group-1")
        self.assertEqual(summarizer.get_topic_count("group-1"), 0)
        self.assertEqual(summarizer.get_topic_summaries("group-1"), [])

    async def test_async_batch_judging_falls_back_to_heuristic_and_restores_open_topics(self) -> None:
        summarizer = GroupTopicSummarizer(judge_trigger_count=10, topic_judge=RaisingTopicJudge())
        first_batch = [
            {
                "id": "m1",
                "content": "火锅聚餐安排很明确。大家讨论晚上去哪家火锅店。",
                "sender_id": "alice",
                "time": 1.0,
            },
            {
                "message_id": "m2",
                "text": "考试复习计划很紧张。需要整理数学重点题目。",
                "user_id": "bob",
                "timestamp": 2.0,
            },
        ]

        summaries = await summarizer.add_messages("group-1", first_batch, force=True)

        self.assertEqual(len(summaries), 2)
        self.assertEqual([item["message_id"] for item in summarizer.get_open_topic_messages("group-1")], ["m2"])
        self.assertTrue(summaries[0]["is_closed"])
        self.assertFalse(summaries[1]["is_closed"])

        restored = GroupTopicSummarizer()
        restored.restore_unclosed_topics("group-1", summaries)
        self.assertEqual([item["message_id"] for item in restored.get_open_topic_messages("group-1")], ["m2"])
        restored.restore_unclosed_topics("group-1", [])
        self.assertEqual([item["message_id"] for item in restored.get_open_topic_messages("group-1")], ["m2"])

        normalized = GroupTopicSummarizer._normalize_judged_segments(
            {
                "segments": [
                    {"topic_title": "A", "start_message_id": "m1", "end_message_id": "m1", "is_closed": False},
                    JudgedTopicSegment("B", "m2", "m2", False, "summary"),
                    {"bad": "shape"},
                    "ignored",
                ]
            }
        )
        self.assertEqual([segment.topic_title for segment in normalized], ["A", "B"])
        self.assertTrue(GroupTopicSummarizer._segments_are_valid(normalized[:2], [msg("m1", "a"), msg("m2", "b")]))
        self.assertFalse(GroupTopicSummarizer._segments_are_valid(normalized[:1], [msg("m1", "a"), msg("m2", "b")]))


class PrivateChatSummarizerTest(unittest.TestCase):
    def test_append_exchange_compresses_old_sentences_tracks_topics_and_reset(self) -> None:
        summarizer = PrivateChatSummarizer(max_summary_sentences=2)

        summarizer.append_exchange("private-1", "Alice", "今天讨论爵士音乐。Alice 想周末去听演出。", 1.0)
        summarizer.append_exchange("private-1", "Bob", "Bob 说考试复习很紧张，需要整理数学重点。", 2.0)
        summarizer.append_exchange("private-1", "Alice", "最后确认明天晚上八点集合。", 3.0)

        summary = summarizer.get_summary("private-1")
        data = summarizer.get_summary_data("private-1")

        self.assertLessEqual(len(summarizer.summaries["private-1"].sentences), 2)
        self.assertIn("；", summary)
        self.assertEqual(summarizer.get_exchange_count("private-1"), 3)
        self.assertGreater(len(summarizer.get_key_topics("private-1")), 0)
        self.assertEqual(data["atom_type"], "episodic")
        self.assertEqual(data["source_scene"], "summary")
        self.assertEqual(data["exchange_count"], 3)
        self.assertEqual(summarizer.get_summary("missing"), "")
        self.assertEqual(summarizer.get_key_topics("missing"), [])
        self.assertEqual(summarizer.get_exchange_count("missing"), 0)
        self.assertIsNone(summarizer.get_summary_data("missing"))

        one_sentence = ProgressiveSummary(sentences=["only one"])
        PrivateChatSummarizer._merge_oldest_two(one_sentence)
        self.assertEqual(one_sentence.sentences, ["only one"])
        two_sentences = ProgressiveSummary(sentences=["first", "second"])
        PrivateChatSummarizer._merge_last_two(two_sentences)
        self.assertEqual(two_sentences.sentences, ["first；second"])

        summarizer.reset("private-1")
        self.assertEqual(summarizer.get_summary("private-1"), "")


class UnclosedTopicBridgeTest(unittest.TestCase):
    def test_bridge_save_restore_cleanup_and_load_guards_use_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            old_data_dir = UnclosedTopicBridge._DATA_DIR
            old_file_path = UnclosedTopicBridge._FILE_PATH
            old_max_size = UnclosedTopicBridge.MAX_FILE_SIZE
            UnclosedTopicBridge._DATA_DIR = tmpdir
            UnclosedTopicBridge._FILE_PATH = str(Path(tmpdir) / "topic_bridge.json")
            try:
                with patch.object(layer1_summarizer.time, "time", return_value=1_000.0):
                    bridge = UnclosedTopicBridge()
                    bridge.save_unclosed_topics(
                        "group-1",
                        [
                            {
                                "topic_id": "open",
                                "topic_title": "持续话题",
                                "keywords": ["持续"],
                                "key_points": ["仍在讨论"],
                                "last_updated": 990.0,
                                "participant_count": 2,
                                "message_count": 2,
                                "is_closed": False,
                                "start_message_id": "m1",
                                "end_message_id": "m2",
                                "messages": [
                                    {
                                        "message_id": "m1",
                                        "text": "x" * 900,
                                        "user_id": "u1",
                                        "speaker": "Alice",
                                        "timestamp": 990.0,
                                    }
                                ],
                            },
                            {"topic_id": "closed", "is_closed": True, "last_updated": 995.0},
                            {"topic_id": "stale", "is_closed": False, "last_updated": -1_000.0},
                        ],
                    )

                saved = json.loads(Path(UnclosedTopicBridge._FILE_PATH).read_text(encoding="utf-8"))
                self.assertEqual(list(saved), ["group-1"])
                self.assertEqual(len(saved["group-1"]), 1)
                self.assertLessEqual(len(saved["group-1"][0]["messages"][0]["text"]), 803)

                restored = UnclosedTopicBridge().restore_topics("group-1")
                self.assertEqual(restored[0]["topic_id"], "open")
                self.assertEqual(UnclosedTopicBridge().restore_topics("group-1"), [])

                bridge = UnclosedTopicBridge()
                bridge._data = {
                    "fresh": [{"topic_id": "fresh", "last_active": 4_900.0}],
                    "old": [{"topic_id": "old", "last_active": 0.0}],
                }
                with patch.object(layer1_summarizer.time, "time", return_value=5_000.0):
                    bridge.cleanup_stale(max_age_hours=1)
                self.assertEqual(set(bridge._data), {"fresh"})

                Path(UnclosedTopicBridge._FILE_PATH).write_text("{bad json", encoding="utf-8")
                self.assertEqual(UnclosedTopicBridge()._data, {})
                Path(UnclosedTopicBridge._FILE_PATH).write_text("too large", encoding="utf-8")
                UnclosedTopicBridge.MAX_FILE_SIZE = 1
                self.assertEqual(UnclosedTopicBridge()._data, {})

                bridge = UnclosedTopicBridge()
                bridge._data = {"group-2": [{"topic_id": "open", "is_closed": False, "last_active": 999.0}]}
                with patch.object(layer1_summarizer.time, "time", return_value=3_000.0):
                    bridge.save_unclosed_topics("group-2", [])
                self.assertNotIn("group-2", bridge._data)
            finally:
                UnclosedTopicBridge._DATA_DIR = old_data_dir
                UnclosedTopicBridge._FILE_PATH = old_file_path
                UnclosedTopicBridge.MAX_FILE_SIZE = old_max_size


if __name__ == "__main__":
    unittest.main()
