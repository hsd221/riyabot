import unittest
from unittest.mock import AsyncMock, Mock

from src.bw_learner.expression_selector import ExpressionSelector


class ExpressionSelectorVectorFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_uses_vector_result_when_available(self):
        selector = object.__new__(ExpressionSelector)
        selector.can_use_expression_for_chat = Mock(return_value=True)
        selector._select_expressions_vector = AsyncMock(return_value=([{"id": 1, "style": "x"}], [1]))
        selector._select_expressions_classic = AsyncMock(return_value=([{"id": 2, "style": "y"}], [2]))

        result = await selector.select_suitable_expressions("chat-a", "hello", reply_reason="reply")

        self.assertEqual(result, ([{"id": 1, "style": "x"}], [1]))
        selector._select_expressions_classic.assert_not_awaited()

    async def test_falls_back_to_classic_when_vector_unavailable(self):
        selector = object.__new__(ExpressionSelector)
        selector.can_use_expression_for_chat = Mock(return_value=True)
        selector._select_expressions_vector = AsyncMock(return_value=None)
        selector._select_expressions_classic = AsyncMock(return_value=([{"id": 2, "style": "y"}], [2]))

        result = await selector.select_suitable_expressions("chat-a", "hello", reply_reason="reply")

        self.assertEqual(result, ([{"id": 2, "style": "y"}], [2]))
        selector._select_expressions_classic.assert_awaited_once()

    async def test_does_not_fallback_when_vector_selects_nothing(self):
        selector = object.__new__(ExpressionSelector)
        selector.can_use_expression_for_chat = Mock(return_value=True)
        selector._select_expressions_vector = AsyncMock(return_value=([], []))
        selector._select_expressions_classic = AsyncMock(return_value=([{"id": 2, "style": "y"}], [2]))

        result = await selector.select_suitable_expressions("chat-a", "hello", reply_reason="reply")

        self.assertEqual(result, ([], []))
        selector._select_expressions_classic.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
