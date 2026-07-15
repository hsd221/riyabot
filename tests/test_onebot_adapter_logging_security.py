import ast
import json
import unittest

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from plugins.onebot_adapter.adapter_core.send_handler import main_send_handler, nc_sending


class _UnsafeExceptionReference(ast.NodeVisitor):
    def __init__(self, exception_names: set[str]) -> None:
        self.exception_names = exception_names
        self.found = False

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            node.attr == "__name__"
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "type"
            and len(node.value.args) == 1
            and isinstance(node.value.args[0], ast.Name)
            and node.value.args[0].id in self.exception_names
        ):
            return
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self.exception_names:
            self.found = True


class OneBotAdapterLoggingSecurityTest(unittest.TestCase):
    def test_adapter_logs_do_not_capture_tracebacks_exceptions_or_raw_payloads(self) -> None:
        adapter_root = Path(__file__).resolve().parents[1] / "plugins" / "onebot_adapter" / "adapter_core"
        findings: list[str] = []
        raw_payload_names = {"raw_message", "response", "socket_response"}

        for source_path in sorted(adapter_root.rglob("*.py")):
            relative_path = source_path.relative_to(adapter_root)
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            exception_names = {
                handler.name
                for handler in ast.walk(tree)
                if isinstance(handler, ast.ExceptHandler) and isinstance(handler.name, str)
            }
            exception_names.update({"e", "exc", "exception"})

            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)) and any(
                    alias.name == "traceback" for alias in node.names
                ):
                    findings.append(f"{relative_path}:{node.lineno}: 导入 traceback")

                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue

                if isinstance(node.func.value, ast.Name) and node.func.value.id == "traceback":
                    findings.append(f"{relative_path}:{node.lineno}: 调用 traceback.{node.func.attr}")

                if not isinstance(node.func.value, ast.Name) or node.func.value.id not in {"logger", "custom_logger"}:
                    continue

                if node.func.attr not in {"debug", "info", "warning", "error", "critical", "exception"}:
                    continue

                if node.func.attr == "exception":
                    findings.append(f"{relative_path}:{node.lineno}: logger.exception 会记录 traceback")

                for keyword in node.keywords:
                    if keyword.arg == "exc_info" and not (
                        isinstance(keyword.value, ast.Constant) and keyword.value.value in (False, None)
                    ):
                        findings.append(f"{relative_path}:{node.lineno}: 日志启用了 exc_info traceback")

                unsafe_reference = _UnsafeExceptionReference(exception_names)
                unsafe_reference.visit(node)
                if unsafe_reference.found:
                    findings.append(f"{relative_path}:{node.lineno}: 日志包含异常正文")

                referenced_names = {
                    child.id
                    for child in ast.walk(node)
                    if isinstance(child, ast.Name) and child.id in raw_payload_names
                }
                if referenced_names:
                    findings.append(
                        f"{relative_path}:{node.lineno}: 日志包含原始响应或消息变量 {sorted(referenced_names)}"
                    )

        self.assertEqual(findings, [])


class OneBotAdapterErrorResponseSecurityTest(unittest.IsolatedAsyncioTestCase):
    async def test_napcat_sender_returns_generic_error_without_logging_exception_text(self) -> None:
        secret = "wss://user:password@internal.invalid/?access_token=super-secret"
        connection = AsyncMock()
        sender = nc_sending.NCMessageSender()
        await sender.set_server_connection(connection)

        with (
            patch.object(nc_sending, "get_response", AsyncMock(side_effect=RuntimeError(secret))),
            patch.object(nc_sending, "logger") as logger,
        ):
            result = await sender.send_message_to_napcat("get_status", {})

        self.assertEqual(result, {"status": "error", "message": "request_failed"})
        self.assertNotIn(secret, repr(logger.method_calls))
        sent_payload = json.loads(connection.send.await_args.args[0])
        self.assertEqual(sent_payload["action"], "get_status")

    async def test_command_failure_does_not_forward_raw_napcat_error(self) -> None:
        secret = "NapCat failed with access_token=super-secret"
        raw_message = MagicMock()
        raw_message.message_info.platform = "qq"
        raw_message.message_info.group_info = MagicMock()
        raw_message.message_segment.data = {"name": "set_group_name"}
        handler = main_send_handler.SendHandler()
        handler._send_command_response = AsyncMock()

        with (
            patch.object(
                main_send_handler.SendCommandHandleClass,
                "handle_command",
                return_value=("set_group_name", {"group_id": 1}),
            ),
            patch.object(
                main_send_handler.nc_message_sender,
                "send_message_to_napcat",
                AsyncMock(return_value={"status": "failed", "message": secret, "data": {"secret": secret}}),
            ),
            patch.object(main_send_handler, "logger") as logger,
        ):
            await handler.send_command(raw_message)

        response_kwargs = handler._send_command_response.await_args.kwargs
        self.assertEqual(response_kwargs["error"], "NapCat 命令执行失败")
        self.assertIsNone(response_kwargs.get("data"))
        self.assertNotIn(secret, repr(logger.method_calls))


if __name__ == "__main__":
    unittest.main()
