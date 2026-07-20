import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.chat.chat_tool_registry import action_info_to_tool_definition
from src.plugin_system.apis.emoji_api import EmojiSelectionCandidate
from src.plugins.built_in.emoji_plugin import emoji as emoji_action_module
from src.plugins.built_in.emoji_plugin.emoji import EmojiAction


def make_action(action_data: dict[str, str] | None = None) -> EmojiAction:
    action = EmojiAction(
        action_data=action_data or {},
        action_reasoning="对方在自嘲，适合轻松回应",
        cycle_timers={},
        thinking_id="thinking-1",
        chat_stream=SimpleNamespace(stream_id="stream-1", platform="qq"),
        action_message=SimpleNamespace(
            chat_info=SimpleNamespace(group_info=SimpleNamespace(group_id="group-1", group_name="Group")),
            user_info=SimpleNamespace(user_id="user-1", user_nickname="Alice"),
        ),
    )
    action.send_emoji = AsyncMock(return_value=True)
    action.send_text = AsyncMock()
    action.store_action_info = AsyncMock()
    return action


def make_candidate(
    emoji_hash: str,
    emoji_base64: str,
    description: str,
    emotion: str,
    *,
    usage_scenes: tuple[str, ...] = (),
) -> EmojiSelectionCandidate:
    return EmojiSelectionCandidate(
        emoji_hash=emoji_hash,
        emoji_base64=emoji_base64,
        description=description,
        matched_emotion=emotion,
        usage_scenes=usage_scenes,
        emotion_score=0.8,
        scene_score=0.9 if usage_scenes else None,
        combined_score=0.86 if usage_scenes else 0.32,
    )


class EmojiActionSelectionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.emoji_config_patch = patch.multiple(
            emoji_action_module.global_config.emoji,
            selection_candidate_count=8,
            usage_scene_weight=0.6,
            usage_scene_enabled=True,
        )
        self.emoji_config_patch.start()
        self.addCleanup(self.emoji_config_patch.stop)

    def test_tool_schema_requires_short_emotion_and_current_scene(self) -> None:
        tool_definition = action_info_to_tool_definition(EmojiAction.get_action_info())
        parameters = {parameter[0]: parameter for parameter in tool_definition["parameters"]}

        self.assertIn("emotion", parameters)
        self.assertTrue(parameters["emotion"][3])
        self.assertIn("简短", parameters["emotion"][2])
        self.assertIn("scene", parameters)
        self.assertTrue(parameters["scene"][3])
        self.assertIn("场景", parameters["scene"][2])

    async def test_vector_candidates_are_sent_to_llm_without_random_sampling(self) -> None:
        action = make_action({"emotion": "轻松调侃", "scene": "对方自嘲代码又写崩了，准备轻松接梗"})
        vector_candidates = [
            make_candidate(
                "hash-vector",
                "base64-vector",
                "情感：轻松调侃；适用场景：接住自嘲；表达意图：幽默回应；画面内容：熊猫偷笑；"
                "画面文字：又写崩了；风格/梗：程序员梗",
                "轻松调侃",
                usage_scenes=("对方自嘲或吐槽失败时，用于轻松接梗",),
            )
        ]

        with (
            patch.object(
                emoji_action_module.emoji_api,
                "get_ranked_candidates",
                new=AsyncMock(return_value=vector_candidates),
            ) as get_ranked_candidates,
            patch.object(emoji_action_module.emoji_api, "get_random_candidates", new=AsyncMock()) as get_random,
            patch.object(emoji_action_module.emoji_api, "record_usage") as record_usage,
            patch.object(emoji_action_module.message_api, "get_recent_messages", return_value=[]),
            patch.object(emoji_action_module.llm_api, "get_available_models", return_value={"utils": object()}),
            patch.object(
                emoji_action_module.llm_api,
                "generate_with_model",
                new=AsyncMock(return_value=(True, "emoji_001", "", "model")),
            ) as generate_with_model,
        ):
            success, _ = await action.execute()

        self.assertTrue(success)
        get_ranked_candidates.assert_awaited_once_with(
            "轻松调侃",
            "对方自嘲代码又写崩了，准备轻松接梗",
            count=8,
            scene_weight=0.6,
        )
        get_random.assert_not_awaited()
        action.send_emoji.assert_awaited_once_with("base64-vector")
        record_usage.assert_called_once_with("hash-vector")
        prompt = generate_with_model.await_args.args[0]
        self.assertIn("熊猫偷笑", prompt)
        self.assertIn("对方自嘲或吐槽失败时，用于轻松接梗", prompt)
        self.assertIn("对方自嘲代码又写崩了，准备轻松接梗", prompt)

    async def test_vector_unavailable_falls_back_to_random_candidates(self) -> None:
        action = make_action({"emotion": "温柔安慰"})
        random_candidates = [make_candidate("hash-random", "base64-random", "温柔递纸安慰", "温柔")]

        with (
            patch.object(
                emoji_action_module.emoji_api,
                "get_ranked_candidates",
                new=AsyncMock(return_value=None),
            ) as get_ranked_candidates,
            patch.object(
                emoji_action_module.emoji_api,
                "get_random_candidates",
                new=AsyncMock(return_value=random_candidates),
            ) as get_random,
            patch.object(emoji_action_module.emoji_api, "record_usage"),
            patch.object(emoji_action_module.message_api, "get_recent_messages", return_value=[]),
            patch.object(emoji_action_module.llm_api, "get_available_models", return_value={"utils": object()}),
            patch.object(
                emoji_action_module.llm_api,
                "generate_with_model",
                new=AsyncMock(return_value=(True, "emoji_001", "", "model")),
            ),
        ):
            success, _ = await action.execute()

        self.assertTrue(success)
        get_ranked_candidates.assert_awaited_once_with(
            "温柔安慰",
            "对方在自嘲，适合轻松回应",
            count=8,
            scene_weight=0.6,
        )
        get_random.assert_awaited_once_with(8)
        action.send_emoji.assert_awaited_once_with("base64-random")

    async def test_vector_search_with_no_threshold_match_does_not_use_random_candidates(self) -> None:
        action = make_action({"emotion": "愤怒反驳"})

        with (
            patch.object(
                emoji_action_module.emoji_api,
                "get_ranked_candidates",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(emoji_action_module.emoji_api, "get_random_candidates", new=AsyncMock()) as get_random,
        ):
            success, result = await action.execute()

        self.assertFalse(success)
        self.assertIn("相似度阈值", result)
        get_random.assert_not_awaited()
        action.send_emoji.assert_not_awaited()

    async def test_llm_selects_specific_emoji_by_candidate_id_and_description(self) -> None:
        action = make_action()
        sampled_emojis = [
            make_candidate(
                "hash-a",
                "base64-a",
                "核心情绪：温柔；表达意图：安慰对方；画面内容：小猫递纸；画面文字：别难过",
                "温柔",
            ),
            make_candidate(
                "hash-b",
                "base64-b",
                "核心情绪：调侃；表达意图：接住自嘲；画面内容：熊猫捂嘴笑；画面文字：这也能写崩",
                "调侃",
            ),
        ]

        with (
            patch.object(
                emoji_action_module.emoji_api,
                "get_random_candidates",
                new=AsyncMock(return_value=sampled_emojis),
            ),
            patch.object(emoji_action_module.emoji_api, "record_usage") as record_usage,
            patch.object(emoji_action_module.message_api, "get_recent_messages", return_value=[object()]),
            patch.object(
                emoji_action_module.message_api,
                "build_readable_messages",
                return_value="12:30 Alice：我又把代码写崩了",
            ),
            patch.object(emoji_action_module.llm_api, "get_available_models", return_value={"utils": object()}),
            patch.object(
                emoji_action_module.llm_api,
                "generate_with_model",
                new=AsyncMock(return_value=(True, "emoji_002", "", "model")),
            ) as generate_with_model,
        ):
            success, _ = await action.execute()

        self.assertTrue(success)
        action.send_emoji.assert_awaited_once_with("base64-b")
        record_usage.assert_called_once_with("hash-b")
        prompt = generate_with_model.await_args.args[0]
        self.assertIn('"id": "emoji_001"', prompt)
        self.assertIn('"description": "核心情绪：温柔；表达意图：安慰对方', prompt)
        self.assertIn('"id": "emoji_002"', prompt)
        self.assertIn('"description": "核心情绪：调侃；表达意图：接住自嘲', prompt)
        self.assertIn("只输出候选 ID", prompt)

    async def test_unknown_candidate_id_does_not_send_a_random_emoji(self) -> None:
        action = make_action()
        sampled_emojis = [
            make_candidate("hash-a", "base64-a", "描述 A", "开心"),
            make_candidate("hash-b", "base64-b", "描述 B", "无奈"),
        ]

        with (
            patch.object(
                emoji_action_module.emoji_api,
                "get_random_candidates",
                new=AsyncMock(return_value=sampled_emojis),
            ),
            patch.object(emoji_action_module.emoji_api, "record_usage") as record_usage,
            patch.object(emoji_action_module.message_api, "get_recent_messages", return_value=[]),
            patch.object(emoji_action_module.llm_api, "get_available_models", return_value={"utils": object()}),
            patch.object(
                emoji_action_module.llm_api,
                "generate_with_model",
                new=AsyncMock(return_value=(True, "emoji_999", "", "model")),
            ),
        ):
            success, result = await action.execute()

        self.assertFalse(success)
        self.assertIn("候选 ID 无效", result)
        action.send_emoji.assert_not_awaited()
        record_usage.assert_not_called()

    async def test_candidate_descriptions_are_passed_to_llm_without_truncation(self) -> None:
        action = make_action()
        long_description = "长" * 700 + "尾部不可见"

        with (
            patch.object(
                emoji_action_module.emoji_api,
                "get_random_candidates",
                new=AsyncMock(return_value=[make_candidate("hash-a", "base64-a", long_description, "开心")]),
            ),
            patch.object(emoji_action_module.emoji_api, "record_usage"),
            patch.object(emoji_action_module.message_api, "get_recent_messages", return_value=[]),
            patch.object(emoji_action_module.llm_api, "get_available_models", return_value={"utils": object()}),
            patch.object(
                emoji_action_module.llm_api,
                "generate_with_model",
                new=AsyncMock(return_value=(True, "emoji_001", "", "model")),
            ) as generate_with_model,
        ):
            success, _ = await action.execute()

        self.assertTrue(success)
        prompt = generate_with_model.await_args.args[0]
        candidate_line = next(line for line in prompt.splitlines() if line.startswith('{"id": "emoji_001"'))
        candidate = json.loads(candidate_line)
        self.assertEqual(candidate["description"], long_description)
        self.assertIn("尾部不可见", candidate["description"])

    async def test_failed_send_does_not_record_candidate_usage(self) -> None:
        action = make_action()
        action.send_emoji = AsyncMock(return_value=False)
        candidate = make_candidate("hash-a", "base64-a", "描述 A", "开心")

        with (
            patch.object(
                emoji_action_module.emoji_api,
                "get_random_candidates",
                new=AsyncMock(return_value=[candidate]),
            ),
            patch.object(emoji_action_module.emoji_api, "record_usage") as record_usage,
            patch.object(emoji_action_module.message_api, "get_recent_messages", return_value=[]),
            patch.object(emoji_action_module.llm_api, "get_available_models", return_value={"utils": object()}),
            patch.object(
                emoji_action_module.llm_api,
                "generate_with_model",
                new=AsyncMock(return_value=(True, "emoji_001", "", "model")),
            ),
        ):
            success, _ = await action.execute()

        self.assertFalse(success)
        record_usage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
