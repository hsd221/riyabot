import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.llm_models.payload_content import ToolCall
from src.plugin_system.core import tool_use
from src.plugin_system.core.tool_use import ToolExecutor


def make_executor(*, enable_cache: bool = True, cache_ttl: int = 2) -> ToolExecutor:
    executor = ToolExecutor.__new__(ToolExecutor)
    executor.chat_id = "stream-1"
    executor.chat_stream = object()
    executor.log_prefix = "[stream]"
    executor.enable_cache = enable_cache
    executor.cache_ttl = cache_ttl
    executor.tool_cache = {}
    executor.llm_model = SimpleNamespace(generate_response_async=AsyncMock())
    return executor


class FakeTool:
    def __init__(self, result=None, side_effect=None) -> None:
        self.result = result if result is not None else {"content": "tool result"}
        self.side_effect = side_effect
        self.calls = []

    async def execute(self, args):
        self.calls.append(args)
        if self.side_effect:
            raise self.side_effect
        return self.result


class ToolExecutorTest(unittest.IsolatedAsyncioTestCase):
    def test_init_builds_chat_context_llm_request_and_cache_settings(self) -> None:
        chat_manager = SimpleNamespace(
            get_stream=Mock(return_value="stream-object"),
            get_stream_name=Mock(return_value="Group"),
        )
        llm_request = object()

        with (
            patch.object(tool_use, "get_chat_manager", return_value=chat_manager),
            patch.object(tool_use.model_config.model_task_config, "tool_use", "tool-model"),
            patch.object(tool_use, "LLMRequest", return_value=llm_request) as llm_request_factory,
        ):
            executor = ToolExecutor("stream-1", enable_cache=False, cache_ttl=7)

        self.assertEqual(executor.chat_id, "stream-1")
        self.assertEqual(executor.chat_stream, "stream-object")
        self.assertEqual(executor.log_prefix, "[Group]")
        self.assertFalse(executor.enable_cache)
        self.assertEqual(executor.cache_ttl, 7)
        self.assertEqual(executor.tool_cache, {})
        self.assertIs(executor.llm_model, llm_request)
        chat_manager.get_stream.assert_called_once_with("stream-1")
        chat_manager.get_stream_name.assert_called_once_with("stream-1")
        llm_request_factory.assert_called_once_with(model_set="tool-model", request_type="tool_executor")

    def test_tool_definitions_filter_user_disabled_tools_and_cache_status(self) -> None:
        executor = make_executor(cache_ttl=2)

        with (
            patch.object(
                tool_use,
                "get_llm_available_tool_definitions",
                return_value=[("enabled", {"name": "enabled"}), ("disabled", {"name": "disabled"})],
            ),
            patch.object(tool_use.global_announcement_manager, "get_disabled_chat_tools", return_value=["disabled"]),
        ):
            self.assertEqual(executor._get_tool_definitions(), [{"name": "enabled"}])

        cache_key = executor._generate_cache_key("message", "history", "sender")
        executor._set_cache(cache_key, [{"tool_name": "enabled", "content": "cached"}])

        self.assertEqual(
            executor.get_cache_status(),
            {"enabled": True, "cache_count": 1, "cache_ttl": 2, "ttl_distribution": {2: 1}},
        )
        self.assertEqual(executor._get_from_cache(cache_key), [{"tool_name": "enabled", "content": "cached"}])
        self.assertEqual(executor.tool_cache[cache_key]["ttl"], 1)
        executor.tool_cache[cache_key]["ttl"] = 0
        self.assertIsNone(executor._get_from_cache(cache_key))
        self.assertEqual(executor.get_cache_status()["cache_count"], 0)

        executor._set_cache(cache_key, [{"tool_name": "enabled"}])
        executor.set_cache_config(enable_cache=False, cache_ttl=5)
        self.assertEqual(executor.get_cache_status(), {"enabled": False, "cache_count": 0})
        self.assertEqual(executor.cache_ttl, 5)
        executor.clear_cache()
        self.assertEqual(executor.tool_cache, {})

        no_cache_executor = make_executor(enable_cache=False, cache_ttl=2)
        no_cache_executor._set_cache("key", [{"tool_name": "lookup"}])
        self.assertEqual(no_cache_executor.tool_cache, {})
        self.assertIsNone(no_cache_executor._get_from_cache("key"))
        no_cache_executor.tool_cache["expired"] = {"result": [], "ttl": 0, "timestamp": 1.0}
        no_cache_executor._cleanup_expired_cache()
        self.assertIn("expired", no_cache_executor.tool_cache)

        cleanup_executor = make_executor(cache_ttl=2)
        cleanup_executor.tool_cache["expired"] = {"result": [], "ttl": 0, "timestamp": 1.0}
        cleanup_executor.tool_cache["alive"] = {"result": [], "ttl": 1, "timestamp": 1.0}
        cleanup_executor._cleanup_expired_cache()
        self.assertNotIn("expired", cleanup_executor.tool_cache)
        self.assertIn("alive", cleanup_executor.tool_cache)

    async def test_execute_tool_call_gets_instance_marks_llm_called_and_handles_missing_tool(self) -> None:
        executor = make_executor()
        fake_tool = FakeTool(result={"content": "lookup result"})
        tool_call = ToolCall("call-1", "lookup", {"query": "MaiBot"})

        with patch.object(tool_use, "get_tool_instance", return_value=fake_tool) as get_instance:
            result = await executor.execute_tool_call(tool_call)

        self.assertEqual(
            result,
            {
                "tool_call_id": "call-1",
                "role": "tool",
                "name": "lookup",
                "type": "function",
                "content": "lookup result",
            },
        )
        self.assertEqual(fake_tool.calls, [{"query": "MaiBot", "llm_called": True}])
        get_instance.assert_called_once_with("lookup", executor.chat_stream)

        with patch.object(tool_use, "get_tool_instance", return_value=None):
            self.assertIsNone(await executor.execute_tool_call(ToolCall("call-2", "missing", {})))

        provided_tool = FakeTool(result={})
        with patch.object(tool_use, "get_tool_instance") as get_instance:
            self.assertIsNone(await executor.execute_tool_call(ToolCall("call-3", "provided", {}), provided_tool))
        get_instance.assert_not_called()
        self.assertEqual(provided_tool.calls, [{"llm_called": True}])

        failing_tool = FakeTool(side_effect=RuntimeError("boom"))
        with self.assertRaisesRegex(RuntimeError, "boom"):
            await executor.execute_tool_call(ToolCall("call-4", "failing", {}), failing_tool)

    async def test_execute_tool_calls_skips_empty_content_stringifies_objects_and_records_errors(self) -> None:
        executor = make_executor()
        calls = [
            ToolCall("call-1", "structured", {}),
            ToolCall("call-2", "empty", {}),
            ToolCall("call-3", "boom", {}),
        ]

        async def execute_one(tool_call):
            if tool_call.func_name == "structured":
                return {"type": "function", "id": "result-1", "content": {"answer": 42}}
            if tool_call.func_name == "empty":
                return {"type": "function", "id": "result-2", "content": "   "}
            raise RuntimeError("provider failed")

        executor.execute_tool_call = AsyncMock(side_effect=execute_one)

        results, used_tools = await executor.execute_tool_calls(calls)

        self.assertEqual(used_tools, ["structured"])
        self.assertEqual(results[0]["tool_name"], "structured")
        self.assertEqual(results[0]["content"], "{'answer': 42}")
        self.assertEqual(results[1]["type"], "tool_error")
        self.assertEqual(results[1]["tool_name"], "boom")
        self.assertIn("provider failed", results[1]["content"])

        self.assertEqual(await executor.execute_tool_calls(None), ([], []))

    async def test_execute_from_chat_message_uses_cache_or_llm_tool_calls_and_returns_details(self) -> None:
        executor = make_executor(cache_ttl=2)
        cached = [{"tool_name": "cached_tool", "content": "cached"}]
        cache_key = executor._generate_cache_key("target", "history", "sender")
        executor._set_cache(cache_key, cached)

        cached_result, cached_tools, cached_prompt = await executor.execute_from_chat_message(
            "target",
            "history",
            "sender",
            return_details=True,
        )

        self.assertEqual(cached_result, cached)
        self.assertEqual(cached_tools, ["cached_tool"])
        self.assertEqual(cached_prompt, "")
        cached_result, cached_tools, cached_prompt = await executor.execute_from_chat_message(
            "target",
            "history",
            "sender",
            return_details=False,
        )
        self.assertEqual(cached_result, cached)
        self.assertEqual(cached_tools, [])
        self.assertEqual(cached_prompt, "")

        executor.tool_cache.clear()
        executor._get_tool_definitions = Mock(return_value=[{"name": "lookup"}])
        executor.execute_tool_calls = AsyncMock(return_value=([{"tool_name": "lookup", "content": "done"}], ["lookup"]))
        executor.llm_model.generate_response_async = AsyncMock(
            return_value=("response", ("reasoning", "model", [ToolCall("call-1", "lookup", {"q": "x"})]))
        )

        with (
            patch.object(tool_use.prompt_manager, "format_prompt", new=Mock(return_value="tool prompt")),
            patch.object(tool_use.global_config.bot, "nickname", "Mai"),
        ):
            result, used_tools, prompt = await executor.execute_from_chat_message(
                "target",
                "history",
                "sender",
                return_details=True,
            )

        self.assertEqual(result, [{"tool_name": "lookup", "content": "done"}])
        self.assertEqual(used_tools, ["lookup"])
        self.assertEqual(prompt, "tool prompt")
        executor.llm_model.generate_response_async.assert_awaited_once_with(
            prompt="tool prompt",
            tools=[{"name": "lookup"}],
            raise_when_empty=False,
        )
        self.assertEqual(executor.get_cache_status()["cache_count"], 1)

        executor.tool_cache.clear()
        executor._get_tool_definitions = Mock(return_value=[])
        self.assertEqual(
            await executor.execute_from_chat_message("target", "history", "sender", return_details=True),
            ([], [], ""),
        )
        self.assertEqual(
            await executor.execute_from_chat_message("target", "history", "sender", return_details=False),
            ([], [], ""),
        )

        executor._get_tool_definitions = Mock(return_value=[{"name": "lookup"}])
        executor.execute_tool_calls = AsyncMock(return_value=([{"tool_name": "lookup", "content": "done"}], ["lookup"]))
        executor.llm_model.generate_response_async = AsyncMock(
            return_value=("response", ("reasoning", "model", [ToolCall("call-2", "lookup", {"q": "y"})]))
        )
        with (
            patch.object(tool_use.prompt_manager, "format_prompt", new=Mock(return_value="tool prompt")),
            patch.object(tool_use.global_config.bot, "nickname", "Mai"),
        ):
            result, used_tools, prompt = await executor.execute_from_chat_message(
                "target-2",
                "history",
                "sender",
                return_details=False,
            )

        self.assertEqual(result, [{"tool_name": "lookup", "content": "done"}])
        self.assertEqual(used_tools, [])
        self.assertEqual(prompt, "")

    async def test_execute_specific_tool_simple_wraps_success_and_suppresses_failures(self) -> None:
        executor = make_executor()
        executor.execute_tool_call = AsyncMock(return_value={"content": ["line-1", "line-2"], "type": "function"})

        result = await executor.execute_specific_tool_simple("lookup", {"query": "MaiBot"})

        self.assertEqual(result["type"], "function")
        self.assertEqual(result["content"], ["line-1", "line-2"])
        self.assertEqual(result["tool_name"], "lookup")

        executor.execute_tool_call = AsyncMock(side_effect=RuntimeError("boom"))
        self.assertIsNone(await executor.execute_specific_tool_simple("lookup", {}))
