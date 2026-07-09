import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.plugins.built_in.knowledge.lpmm_get_knowledge import SearchKnowledgeFromLPMMTool


class SearchKnowledgeFromLPMMToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_execute_returns_empty_info_for_blank_query_or_missing_chat_stream(self) -> None:
        tool = SearchKnowledgeFromLPMMTool()

        self.assertEqual(await tool.execute({"query": "   "}), {"type": "info", "id": "", "content": ""})
        self.assertEqual(
            await tool.execute({"query": "  最近聊了什么  "}),
            {"type": "info", "id": "最近聊了什么", "content": ""},
        )

    async def test_execute_clamps_limit_and_forwards_context_to_memory_retrieval(self) -> None:
        chat_stream = SimpleNamespace(stream_id="stream-1", platform="qq", user_info=SimpleNamespace(user_id="user-1"))
        tool = SearchKnowledgeFromLPMMTool(
            chat_stream=chat_stream,
            chat_history="Alice: 之前说过喜欢蓝色",
            sender="Alice",
            target="Bob",
        )
        build_prompt = AsyncMock(return_value=("memory evidence", ["atom-1", "atom-2"]))

        with patch("src.memory.prompt_integration.build_memory_retrieval_prompt", new=build_prompt):
            result = await tool.execute({"query": "  喜欢什么颜色  ", "limit": "99"})

        self.assertEqual(
            result,
            {
                "type": "info",
                "id": "喜欢什么颜色",
                "content": "memory evidence",
                "source": "memory",
                "atom_ids": ["atom-1", "atom-2"],
            },
        )
        build_prompt.assert_awaited_once_with(
            chat_talking_prompt_short="Alice: 之前说过喜欢蓝色",
            sender="Alice",
            target="Bob",
            chat_stream=chat_stream,
            think_level=2,
            question="喜欢什么颜色",
            user_id="user-1",
            max_atoms=6,
            max_chars=900,
            include_cross_scene=True,
            question_from_planner=False,
        )

    async def test_execute_uses_default_limit_for_invalid_values_and_swallows_memory_errors(self) -> None:
        chat_stream = SimpleNamespace(stream_id="stream-1", platform="qq", user_info=None)
        tool = SearchKnowledgeFromLPMMTool(chat_stream=chat_stream)
        build_prompt = AsyncMock(side_effect=[("evidence", []), RuntimeError("memory down")])

        with patch("src.memory.prompt_integration.build_memory_retrieval_prompt", new=build_prompt):
            self.assertEqual(
                await tool.execute({"query": "first", "limit": "not-a-number"}),
                {"type": "info", "id": "first", "content": "evidence", "source": "memory", "atom_ids": []},
            )
            self.assertEqual(
                await tool.execute({"query": "second", "limit": -3}),
                {"type": "info", "id": "second", "content": ""},
            )

        self.assertEqual(build_prompt.await_args_list[0].kwargs["max_atoms"], 5)
        self.assertEqual(build_prompt.await_args_list[0].kwargs["user_id"], None)
        self.assertEqual(build_prompt.await_args_list[1].kwargs["max_atoms"], 1)


if __name__ == "__main__":
    unittest.main()
