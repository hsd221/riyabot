import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.plugins.built_in.emoji_plugin import emoji as emoji_action_module
from src.plugins.built_in.emoji_plugin.emoji import EmojiAction


def make_action() -> EmojiAction:
    action = EmojiAction(
        action_data={},
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
    action.store_action_info = AsyncMock()
    return action


class EmojiActionSelectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_llm_selects_specific_emoji_by_candidate_id_and_description(self) -> None:
        action = make_action()
        sampled_emojis = [
            (
                "base64-a",
                "核心情绪：温柔；表达意图：安慰对方；画面内容：小猫递纸；画面文字：别难过",
                "温柔",
            ),
            (
                "base64-b",
                "核心情绪：调侃；表达意图：接住自嘲；画面内容：熊猫捂嘴笑；画面文字：这也能写崩",
                "调侃",
            ),
        ]

        with (
            patch.object(emoji_action_module.emoji_api, "get_random", new=AsyncMock(return_value=sampled_emojis)),
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
        prompt = generate_with_model.await_args.args[0]
        self.assertIn('"id": "emoji_001"', prompt)
        self.assertIn('"description": "核心情绪：温柔；表达意图：安慰对方', prompt)
        self.assertIn('"id": "emoji_002"', prompt)
        self.assertIn('"description": "核心情绪：调侃；表达意图：接住自嘲', prompt)
        self.assertIn("只输出候选 ID", prompt)

    async def test_unknown_candidate_id_does_not_send_a_random_emoji(self) -> None:
        action = make_action()
        sampled_emojis = [("base64-a", "描述 A", "开心"), ("base64-b", "描述 B", "无奈")]

        with (
            patch.object(emoji_action_module.emoji_api, "get_random", new=AsyncMock(return_value=sampled_emojis)),
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

    async def test_candidate_descriptions_are_passed_to_llm_without_truncation(self) -> None:
        action = make_action()
        long_description = "长" * 700 + "尾部不可见"

        with (
            patch.object(
                emoji_action_module.emoji_api,
                "get_random",
                new=AsyncMock(return_value=[("base64-a", long_description, "开心")]),
            ),
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


if __name__ == "__main__":
    unittest.main()
