import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.chat.brain_chat.PFC import action_planner, pfc, reply_checker, reply_generator
from src.chat.brain_chat.PFC.conversation_info import ConversationInfo
from src.chat.brain_chat.PFC.observation_info import ObservationInfo


class FakeLLM:
    def __init__(self, *responses):
        self.generate_response_async = AsyncMock(side_effect=list(responses))


def make_observation() -> ObservationInfo:
    observation = ObservationInfo("Alice")
    observation.chat_history = [
        {
            "message_id": "bot-1",
            "processed_plain_text": "上一句",
            "user_info": {"platform": "qq", "user_id": "bot", "user_nickname": "Mai"},
            "time": 90.0,
        }
    ]
    observation.chat_history_str = "Mai: 上一句"
    observation.unprocessed_messages = [
        {
            "message_id": "user-1",
            "processed_plain_text": "你好",
            "user_info": {"platform": "qq", "user_id": "user-1", "user_nickname": "Alice"},
            "time": 100.0,
        }
    ]
    observation.new_messages_count = 1
    return observation


def make_conversation() -> ConversationInfo:
    conversation = ConversationInfo()
    conversation.goal_list = [{"goal": "继续聊天", "reasoning": "用户刚发来消息"}]
    conversation.done_action = [
        {"action": "wait", "plan_reason": "等用户回复", "status": "done", "time": "09:00"},
        ("direct_reply", "成功发送", "done"),
    ]
    conversation.knowledge_list = []
    return conversation


class GoalAnalyzerTest(unittest.IsolatedAsyncioTestCase):
    def make_analyzer(self, *responses):
        analyzer = pfc.GoalAnalyzer.__new__(pfc.GoalAnalyzer)
        analyzer.llm = FakeLLM(*responses)
        analyzer.personality_info = "你的名字是Mai,你温和;"
        analyzer.name = "Mai"
        analyzer.private_name = "Alice"
        analyzer.chat_observer = SimpleNamespace(get_cached_messages=Mock(return_value=[]))
        analyzer.goals = []
        analyzer.max_goals = 3
        return analyzer

    def test_similarity_personality_and_goal_list_helpers(self) -> None:
        self.assertEqual(pfc._calculate_similarity("", ""), 0)
        self.assertEqual(pfc._calculate_similarity("abc", "abc"), 1.0)
        self.assertGreater(pfc._calculate_similarity("聊天目标", "聊天计划"), 0.2)

        fake_config = SimpleNamespace(
            personality=SimpleNamespace(personality="温和", states=["困倦"], state_probability=1.0),
            bot=SimpleNamespace(nickname="Mai"),
        )
        analyzer = pfc.GoalAnalyzer.__new__(pfc.GoalAnalyzer)
        with (
            patch.object(pfc, "global_config", fake_config),
            patch.object(pfc.random, "random", return_value=0.0),
            patch.object(pfc.random, "choice", return_value="困倦"),
        ):
            self.assertEqual(analyzer._get_personality_prompt(), "你的名字是Mai,你困倦;")

    async def test_update_goals_moves_similar_goal_to_front_and_limits_total(self) -> None:
        analyzer = self.make_analyzer()
        analyzer.goals = [("聊猫", "方法1", "原因1"), ("聊音乐", "方法2", "原因2"), ("聊电影", "方法3", "原因3")]

        await analyzer._update_goals("聊猫", "新方法", "新原因")
        self.assertEqual(analyzer.goals[0], ("聊猫", "新方法", "新原因"))
        self.assertEqual(len(analyzer.goals), 3)

        await analyzer._update_goals("完全不同的新目标", "方法4", "原因4")
        self.assertEqual(analyzer.goals[0], ("完全不同的新目标", "方法4", "原因4"))
        self.assertEqual(len(analyzer.goals), 3)
        self.assertNotIn(("聊电影", "方法3", "原因3"), analyzer.goals)
        self.assertEqual(await analyzer.get_all_goals(), analyzer.goals)
        self.assertEqual(await analyzer.get_alternative_goals(), analyzer.goals[1:])

    async def test_analyze_goal_replaces_goal_list_for_array_and_appends_single_goal(self) -> None:
        conversation = make_conversation()
        observation = make_observation()
        analyzer = self.make_analyzer(
            ('[{"goal": "目标一", "reasoning": "原因一"}, {"goal": "目标二", "reasoning": "原因二"}]', None)
        )

        with (
            patch.object(pfc, "load_prompt", return_value="goal prompt") as load_prompt,
            patch.object(pfc, "format_pfc_chat_history", return_value="新消息文本"),
        ):
            result = await analyzer.analyze_goal(conversation, observation)

        self.assertEqual(result, ("目标一", "", "原因一"))
        self.assertEqual(
            conversation.goal_list,
            [{"goal": "目标一", "reasoning": "原因一"}, {"goal": "目标二", "reasoning": "原因二"}],
        )
        load_prompt.assert_called_once()

        conversation = ConversationInfo()
        analyzer = self.make_analyzer(('{"goal": "单个目标", "reasoning": "单个原因"}', None))
        with patch.object(pfc, "load_prompt", return_value="goal prompt"):
            result = await analyzer.analyze_goal(conversation, ObservationInfo("Alice"))

        self.assertEqual(result, ("单个目标", "", "单个原因"))
        self.assertEqual(conversation.goal_list, [{"goal": "单个目标", "reasoning": "单个原因"}])

    async def test_analyze_goal_and_conversation_fallbacks_are_structured(self) -> None:
        conversation = ConversationInfo()
        analyzer = self.make_analyzer(("not json", None))
        with patch.object(pfc, "load_prompt", return_value="goal prompt"):
            self.assertEqual(await analyzer.analyze_goal(conversation, ObservationInfo("Alice")), ("", "", ""))

        analyzer = self.make_analyzer(('{"goal_achieved": true, "stop_conversation": false, "reason": "达成"}', None))
        analyzer.chat_observer = SimpleNamespace(get_cached_messages=Mock(return_value=[{"message_id": "m1"}]))
        with (
            patch.object(pfc, "load_prompt", return_value="assess prompt"),
            patch.object(pfc, "format_pfc_chat_history", return_value="history"),
        ):
            self.assertEqual(await analyzer.analyze_conversation("目标", "原因"), (True, False, "达成"))

        analyzer = self.make_analyzer(("not json", None))
        with patch.object(pfc, "load_prompt", return_value="assess prompt"):
            self.assertEqual(await analyzer.analyze_conversation("目标", "原因"), (False, False, "解析结果失败"))


class ActionPlannerTest(unittest.IsolatedAsyncioTestCase):
    def make_planner(self, *responses):
        planner = action_planner.ActionPlanner.__new__(action_planner.ActionPlanner)
        planner.llm = FakeLLM(*responses)
        planner.personality_info = "你的名字是Mai,你温和;"
        planner.name = "Mai"
        planner.private_name = "Alice"
        planner.chat_observer = SimpleNamespace()
        return planner

    async def test_plan_returns_valid_action_and_uses_follow_up_section_after_successful_reply(self) -> None:
        planner = self.make_planner(('{"action": "direct_reply", "reason": "该回复了"}', None))
        fake_config = SimpleNamespace(BOT_QQ="bot")

        def fake_prompt(prompt_name, section_name, **kwargs):
            self.assertEqual(prompt_name, "pfc_action_decision")
            self.assertEqual(section_name, "follow_up")
            self.assertIn("上一条成功发送的消息", kwargs["time_since_last_bot_message_info"])
            return f"prompt:{section_name}"

        with (
            patch.object(action_planner, "global_config", fake_config),
            patch.object(action_planner, "load_prompt_section", side_effect=fake_prompt),
            patch.object(action_planner.time, "time", return_value=100.0),
        ):
            self.assertEqual(
                await planner.plan(make_observation(), make_conversation(), "direct_reply"),
                ("direct_reply", "该回复了"),
            )

    async def test_plan_normalizes_invalid_action_and_handles_llm_exceptions(self) -> None:
        planner = self.make_planner(('{"action": "dance", "reason": "想跳舞"}', None))
        with (
            patch.object(action_planner, "global_config", SimpleNamespace(BOT_QQ="bot")),
            patch.object(action_planner, "load_prompt_section", return_value="prompt"),
        ):
            action, reason = await planner.plan(make_observation(), make_conversation(), None)

        self.assertEqual(action, "wait")
        self.assertIn("原始行动'dance'无效", reason)

        planner = self.make_planner(RuntimeError("llm down"))
        with (
            patch.object(action_planner, "global_config", SimpleNamespace(BOT_QQ="bot")),
            patch.object(action_planner, "load_prompt_section", return_value="prompt"),
        ):
            action, reason = await planner.plan(make_observation(), make_conversation(), None)

        self.assertEqual(action, "wait")
        self.assertIn("行动规划处理中发生错误", reason)

    async def test_plan_runs_second_end_decision_before_saying_goodbye(self) -> None:
        planner = self.make_planner(
            ('{"action": "end_conversation", "reason": "该结束了"}', None),
            ('{"say_bye": "yes", "reason": "礼貌告别"}', None),
        )

        with (
            patch.object(action_planner, "global_config", SimpleNamespace(BOT_QQ="bot")),
            patch.object(action_planner, "load_prompt_section", return_value="prompt") as load_prompt_section,
        ):
            action, reason = await planner.plan(make_observation(), make_conversation(), None)

        self.assertEqual(action, "say_goodbye")
        self.assertIn("礼貌告别", reason)
        self.assertEqual(planner.llm.generate_response_async.await_count, 2)
        self.assertEqual(load_prompt_section.call_args_list[1].args[:2], ("pfc_action_decision", "end_decision"))


class ReplyCheckerTest(unittest.IsolatedAsyncioTestCase):
    def make_checker(self, *responses):
        checker = reply_checker.ReplyChecker.__new__(reply_checker.ReplyChecker)
        checker.llm = FakeLLM(*responses)
        checker.name = "Mai"
        checker.private_name = "Alice"
        checker.chat_observer = SimpleNamespace()
        checker.max_retries = 3
        return checker

    async def test_check_rejects_duplicate_and_highly_similar_bot_replies_before_llm(self) -> None:
        history = [{"user_info": {"user_id": "bot"}, "processed_plain_text": "你好，今天聊猫吗？"}]
        checker = self.make_checker(('{"suitable": true, "reason": "ok"}', None))

        with patch.object(reply_checker, "global_config", SimpleNamespace(BOT_QQ="bot")):
            duplicate = await checker.check("你好，今天聊猫吗？", "goal", history, "history")
            similar = await checker.check("你好，今天聊猫吗？！", "goal", history, "history")

        self.assertEqual(duplicate[0], False)
        self.assertTrue(duplicate[2])
        self.assertIn("完全相同", duplicate[1])
        self.assertEqual(similar[0], False)
        self.assertTrue(similar[2])
        self.assertIn("高度相似", similar[1])
        checker.llm.generate_response_async.assert_not_awaited()

    async def test_check_parses_json_string_booleans_retry_and_text_fallbacks(self) -> None:
        checker = self.make_checker(('{"suitable": "true", "reason": "可以", "need_replan": true}', None))
        with (
            patch.object(reply_checker, "global_config", SimpleNamespace(BOT_QQ="bot")),
            patch.object(reply_checker, "load_prompt", return_value="check prompt"),
        ):
            self.assertEqual(await checker.check("新回复", "goal", [], "history"), (True, "可以", True))

        checker = self.make_checker(('{"suitable": false, "reason": "不够好"}', None))
        with (
            patch.object(reply_checker, "global_config", SimpleNamespace(BOT_QQ="bot")),
            patch.object(reply_checker, "load_prompt", return_value="check prompt"),
        ):
            self.assertEqual(
                await checker.check("新回复", "goal", [], "history", retry_count=0), (False, "不够好", False)
            )

        checker = self.make_checker(('{"suitable": false, "reason": "不够好"}', None))
        with (
            patch.object(reply_checker, "global_config", SimpleNamespace(BOT_QQ="bot")),
            patch.object(reply_checker, "load_prompt", return_value="check prompt"),
        ):
            self.assertEqual(
                await checker.check("新回复", "goal", [], "history", retry_count=3),
                (False, "多次重试后仍不合适: 不够好", True),
            )

        checker = self.make_checker(("这段回复不合适，需要重新规划", None))
        with (
            patch.object(reply_checker, "global_config", SimpleNamespace(BOT_QQ="bot")),
            patch.object(reply_checker, "load_prompt", return_value="check prompt"),
        ):
            self.assertEqual(
                await checker.check("新回复", "goal", [], "history"),
                (False, "这段回复不合适，需要重新规划", True),
            )

    async def test_check_reports_exceptions_as_retry_or_replan_by_retry_count(self) -> None:
        checker = self.make_checker(RuntimeError("llm down"))
        with (
            patch.object(reply_checker, "global_config", SimpleNamespace(BOT_QQ="bot")),
            patch.object(reply_checker, "load_prompt", return_value="check prompt"),
        ):
            retry = await checker.check("新回复", "goal", [], "history", retry_count=0)

        self.assertEqual(retry, (False, "检查过程出错，建议重试: llm down", False))

        checker = self.make_checker(RuntimeError("llm down"))
        with (
            patch.object(reply_checker, "global_config", SimpleNamespace(BOT_QQ="bot")),
            patch.object(reply_checker, "load_prompt", return_value="check prompt"),
        ):
            replan = await checker.check("新回复", "goal", [], "history", retry_count=3)

        self.assertEqual(replan, (False, "多次检查失败，建议重新规划", True))


class ReplyGeneratorTest(unittest.IsolatedAsyncioTestCase):
    def make_generator(self, *responses):
        generator = reply_generator.ReplyGenerator.__new__(reply_generator.ReplyGenerator)
        generator.llm = FakeLLM(*responses)
        generator.personality_info = "你的名字是Mai,你温和;"
        generator.name = "Mai"
        generator.private_name = "Alice"
        generator.chat_observer = SimpleNamespace()
        generator.reply_checker = SimpleNamespace(check=AsyncMock(return_value=(True, "ok", False)))
        return generator

    async def test_generate_uses_action_specific_prompt_sections_and_returns_llm_content(self) -> None:
        sections = []

        def fake_prompt(prompt_name, section_name, **kwargs):
            self.assertEqual(prompt_name, "pfc_reply_generation")
            self.assertIn("继续聊天", kwargs["goals_str"])
            self.assertIn("以下是 1 条新消息", kwargs["chat_history_text"])
            sections.append(section_name)
            return f"prompt:{section_name}"

        for action_type, expected_section in [
            ("send_new_message", "send_new_message"),
            ("say_goodbye", "farewell"),
            ("direct_reply", "direct_reply"),
            ("unknown", "direct_reply"),
        ]:
            generator = self.make_generator((f"reply:{expected_section}", None))
            with patch.object(reply_generator, "load_prompt_section", side_effect=fake_prompt):
                self.assertEqual(
                    await generator.generate(make_observation(), make_conversation(), action_type),
                    f"reply:{expected_section}",
                )

        self.assertEqual(sections, ["send_new_message", "farewell", "direct_reply", "direct_reply"])

    async def test_generate_error_fallback_and_check_reply_delegation(self) -> None:
        generator = self.make_generator(RuntimeError("llm down"))
        with patch.object(reply_generator, "load_prompt_section", return_value="prompt"):
            self.assertEqual(
                await generator.generate(make_observation(), make_conversation(), "direct_reply"),
                "抱歉，我现在有点混乱，让我重新思考一下...",
            )

        self.assertEqual(
            await generator.check_reply("reply", "goal", [], "history", retry_count=2), (True, "ok", False)
        )
        generator.reply_checker.check.assert_awaited_once_with("reply", "goal", [], "history", 2)


if __name__ == "__main__":
    unittest.main()
