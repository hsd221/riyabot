import unittest
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

from src.memory.expression_bridge import ExpressionBridge, ExpressionProfile


class FakeProfileStore:
    def __init__(self, profiles: dict[str, SimpleNamespace] | None = None) -> None:
        self.profiles = profiles or {}
        self.saved_profiles: list[SimpleNamespace] = []

    def get_profile(self, user_id: str):
        return self.profiles.get(user_id)

    def save_profile(self, profile: SimpleNamespace) -> None:
        self.saved_profiles.append(profile)


class ExpressionBridgeTest(unittest.TestCase):
    def test_expression_profile_dataclass_has_stable_defaults(self) -> None:
        profile = ExpressionProfile(user_id="user-1")

        self.assertEqual(
            asdict(profile),
            {
                "user_id": "user-1",
                "favorite_expressions": [],
                "jargon_terms": [],
                "expression_style": "",
                "emoji_preferences": [],
                "average_message_length": 0.0,
                "updated_at": 0.0,
            },
        )

    def test_update_expression_profile_extracts_keywords_stats_style_and_saves_profile(self) -> None:
        profile = SimpleNamespace(user_id="user-1", stats={})
        store = FakeProfileStore({"user-1": profile})
        bridge = ExpressionBridge(store)

        with (
            patch("src.memory.layer1_summarizer.extract_keywords", return_value=["好耶", "冲鸭"]) as extract_keywords,
            patch("src.memory.expression_bridge.time.time", return_value=1234.5),
        ):
            bridge.update_expression_profile("user-1", ["好耶😀", "冲鸭😀", "开心😀"])

        extract_keywords.assert_called_once_with("好耶😀 冲鸭😀 开心😀", max_keywords=8)
        self.assertEqual(store.saved_profiles, [profile])
        self.assertEqual(profile.stats["_expression_style"], "活泼")
        patterns = profile.stats["_expression_patterns"]
        self.assertEqual(patterns["favorite_expressions"], ["好耶", "冲鸭"])
        self.assertEqual(patterns["avg_message_length"], 3.0)
        self.assertEqual(patterns["emoji_preferences"], ["😀"])
        self.assertGreater(patterns["emoji_ratio"], 0.15)
        self.assertEqual(patterns["question_ratio"], 0.0)
        self.assertEqual(patterns["analyzed_message_count"], 3)
        self.assertEqual(patterns["updated_at"], 1234.5)

    def test_update_expression_profile_skips_empty_messages_missing_profiles_and_swallows_extractor_errors(
        self,
    ) -> None:
        missing_store = FakeProfileStore()
        bridge = ExpressionBridge(missing_store)

        bridge.update_expression_profile("missing", [])
        self.assertEqual(missing_store.saved_profiles, [])

        with patch("src.memory.layer1_summarizer.extract_keywords", return_value=["关键词"]):
            bridge.update_expression_profile("missing", ["hello"])
        self.assertEqual(missing_store.saved_profiles, [])

        profile = SimpleNamespace(user_id="user-1", stats={})
        failing_store = FakeProfileStore({"user-1": profile})
        failing_bridge = ExpressionBridge(failing_store)
        with patch("src.memory.layer1_summarizer.extract_keywords", side_effect=RuntimeError("broken tokenizer")):
            failing_bridge.update_expression_profile("user-1", ["hello"])

        self.assertEqual(profile.stats, {})
        self.assertEqual(failing_store.saved_profiles, [])

    def test_get_expression_context_formats_parts_and_truncates_to_requested_length(self) -> None:
        profile = SimpleNamespace(
            user_id="user-1",
            stats={
                "_expression_style": "活泼",
                "_expression_patterns": {
                    "favorite_expressions": ["好耶", "冲鸭", "收到", "可以", "超出"],
                    "emoji_preferences": ["😀", "😆", "✨", "🔥"],
                    "avg_message_length": 12.6,
                },
            },
        )
        bridge = ExpressionBridge(FakeProfileStore({"user-1": profile}))

        context = bridge.get_expression_context("user-1", max_chars=200)

        self.assertEqual(
            context,
            "【表达特征】表达风格: 活泼 | 高频词: 好耶、冲鸭、收到、可以 | 常用表情: 😀 😆 ✨ | 平均消息长度: 13字",
        )
        truncated = bridge.get_expression_context("user-1", max_chars=30)
        self.assertLessEqual(len(truncated), 30)
        self.assertTrue(truncated.endswith("..."))

        self.assertEqual(ExpressionBridge(FakeProfileStore()).get_expression_context("missing"), "")
        empty = SimpleNamespace(user_id="empty", stats={})
        self.assertEqual(ExpressionBridge(FakeProfileStore({"empty": empty})).get_expression_context("empty"), "")

    def test_detect_jargon_matches_case_insensitively_in_configured_order(self) -> None:
        bridge = ExpressionBridge(FakeProfileStore())

        self.assertEqual(bridge.detect_jargon("今天 YYDS，也有 CPU 话题", ["yyds", "cpu", "gpu"]), ["yyds", "cpu"])
        self.assertEqual(bridge.detect_jargon("", ["yyds"]), [])
        self.assertEqual(bridge.detect_jargon("hello", []), [])

    def test_extract_emojis_and_style_inference_cover_priority_branches(self) -> None:
        bridge = ExpressionBridge(FakeProfileStore())

        self.assertEqual(bridge._extract_emojis("ok😀✨ text"), ["😀✨"])
        self.assertEqual(
            bridge._infer_expression_style(
                avg_len=80,
                emoji_ratio=0.5,
                question_ratio=0.5,
                msg_count=80,
                text="因此 综上所述 值得注意的是 " + "长句" * 40,
            ),
            "严谨",
        )
        self.assertEqual(bridge._infer_expression_style(10, 0.2, 0.0, 3, "😀"), "活泼")
        self.assertEqual(bridge._infer_expression_style(40, 0.0, 0.25, 3, "真的?"), "阴阳怪气")
        self.assertEqual(bridge._infer_expression_style(40, 0.0, 0.0, 50, "很多消息"), "话痨")
        self.assertEqual(bridge._infer_expression_style(10, 0.0, 0.0, 3, "短"), "简洁")
        self.assertEqual(bridge._infer_expression_style(40, 0.0, 0.0, 3, "普通文本"), "中性")


if __name__ == "__main__":
    unittest.main()
