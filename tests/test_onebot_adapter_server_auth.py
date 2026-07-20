import asyncio
import http
import unittest

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from plugins.onebot_adapter.adapter_core import runtime as runtime_module
from src.services.adapter_identity import get_adapter_identity_registry


class OneBotAdapterServerAuthTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        get_adapter_identity_registry().clear()

    def tearDown(self) -> None:
        get_adapter_identity_registry().clear()

    @staticmethod
    def _config(host: str, token: str) -> SimpleNamespace:
        return SimpleNamespace(
            napcat_server=SimpleNamespace(host=host, port=8095, token=token),
            debug=SimpleNamespace(level="INFO"),
        )

    @staticmethod
    def _request(authorization: str | None = None) -> SimpleNamespace:
        headers = {} if authorization is None else {"Authorization": authorization}
        return SimpleNamespace(headers=headers)

    def test_empty_token_is_only_allowed_for_loopback_bindings(self) -> None:
        adapter = runtime_module.OneBotAdapterRuntime()

        for host in ("localhost", "localhost.", "127.0.0.1", "::1", "[::1]"):
            with self.subTest(host=host), patch.object(runtime_module, "global_config", self._config(host, "  ")):
                self.assertIsNone(adapter._check_napcat_server_token(None, self._request()))

        for host in ("0.0.0.0", "::", "192.168.1.20", "adapter.internal"):
            with self.subTest(host=host), patch.object(runtime_module, "global_config", self._config(host, "")):
                response = adapter._check_napcat_server_token(None, self._request())
                self.assertIsNotNone(response)
                self.assertEqual(response.status_code, http.HTTPStatus.FORBIDDEN)

    def test_configured_token_is_required_for_every_binding(self) -> None:
        adapter = runtime_module.OneBotAdapterRuntime()

        with patch.object(runtime_module, "global_config", self._config("0.0.0.0", "server-secret")):
            self.assertIsNone(adapter._check_napcat_server_token(None, self._request("Bearer server-secret")))
            response = adapter._check_napcat_server_token(None, self._request("Bearer wrong-secret"))

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, http.HTTPStatus.UNAUTHORIZED)

    async def test_remote_empty_token_fails_before_server_bind(self) -> None:
        adapter = runtime_module.OneBotAdapterRuntime()
        serve = Mock(side_effect=AssertionError("WebSocket server must not bind"))

        with (
            patch.object(runtime_module, "global_config", self._config("0.0.0.0", "")),
            patch.object(runtime_module.Server, "serve", serve),
            self.assertRaisesRegex(RuntimeError, "令牌"),
        ):
            await adapter._napcat_server()

        serve.assert_not_called()

    async def test_runtime_status_and_identity_follow_the_onebot_connection(self) -> None:
        core_config = SimpleNamespace(
            bot=SimpleNamespace(platform="legacy", qq_account="old-account", nickname="Old Name")
        )
        with patch.object(runtime_module, "core_global_config", core_config):
            adapter = runtime_module.OneBotAdapterRuntime()
            connection = object()
            adapter._started = True
            adapter._websocket_server = object()

            self.assertEqual(adapter.get_status()["status"], "listening")

            adapter._connection_opened(connection)
            self.assertEqual(adapter.get_status()["status"], "connected")

            with patch.object(
                runtime_module,
                "get_self_info",
                AsyncMock(return_value={"user_id": 10001, "nickname": "Riya"}),
            ):
                await adapter._discover_identity(connection, fallback_account_id="10001")

            get_adapter_identity_registry().register("other_qq_adapter", "qq", "99999", "Other")
            status = adapter.get_status()
            self.assertEqual(status["identity"], {"account_id": "10001", "nickname": "Riya"})
            self.assertTrue(get_adapter_identity_registry().is_bot_account("qq", "10001"))
            self.assertEqual(
                (core_config.bot.platform, core_config.bot.qq_account, core_config.bot.nickname),
                ("qq", "10001", "Riya"),
            )

            adapter._connection_closed(connection)

            self.assertEqual(adapter.get_status()["status"], "listening")
            self.assertIsNone(adapter.get_status()["identity"])
            self.assertFalse(get_adapter_identity_registry().is_bot_account("qq", "10001"))
            self.assertEqual(
                (core_config.bot.platform, core_config.bot.qq_account, core_config.bot.nickname),
                ("legacy", "old-account", "Old Name"),
            )

    async def test_identity_profile_is_not_requested_again_after_discovery(self) -> None:
        adapter = runtime_module.OneBotAdapterRuntime()
        connection = object()
        adapter._connection_opened(connection)

        with patch.object(
            runtime_module,
            "get_self_info",
            AsyncMock(return_value={"user_id": 10001, "nickname": "Riya"}),
        ) as get_self_info:
            adapter._schedule_identity_discovery(connection, "10001")
            first_task = adapter._identity_tasks[id(connection)]
            await first_task
            await asyncio.sleep(0)

            adapter._register_identity("10001")
            adapter._schedule_identity_discovery(connection, "10001")

        self.assertEqual(get_self_info.await_count, 1)
        self.assertEqual(adapter.get_status()["identity"], {"account_id": "10001", "nickname": "Riya"})
        adapter._connection_closed(connection)

    def test_untrusted_identity_rejects_oversized_account_id(self) -> None:
        adapter = runtime_module.OneBotAdapterRuntime()

        adapter._register_identity("1" * 129, "Riya")

        self.assertIsNone(adapter.get_status()["identity"])

    def test_untrusted_identity_drops_unsafe_nickname(self) -> None:
        adapter = runtime_module.OneBotAdapterRuntime()

        adapter._register_identity("10001", "Riya\nInjected")

        self.assertEqual(adapter.get_status()["identity"], {"account_id": "10001", "nickname": ""})

    async def test_connection_requests_identity_before_the_first_onebot_event(self) -> None:
        class EmptyConnection:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        adapter = runtime_module.OneBotAdapterRuntime()
        adapter._message_queue = asyncio.Queue()
        connection = EmptyConnection()

        with (
            patch.object(runtime_module.message_handler, "set_server_connection", AsyncMock()),
            patch.object(runtime_module.notice_handler, "set_server_connection", AsyncMock()),
            patch.object(runtime_module.nc_message_sender, "set_server_connection", AsyncMock()),
            patch.object(adapter, "_schedule_identity_discovery") as schedule_identity,
        ):
            await adapter._message_recv(connection)

        schedule_identity.assert_called_once_with(connection, "")

    async def test_runtime_status_reports_server_start_failure(self) -> None:
        adapter = runtime_module.OneBotAdapterRuntime()
        adapter._started = True
        adapter._restart_event = asyncio.Event()

        with patch.object(adapter, "_napcat_server", AsyncMock(side_effect=RuntimeError("bind failed"))):
            await adapter._napcat_with_restart()

        status = adapter.get_status()
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["last_error"], "RuntimeError")

    async def test_config_change_restarts_server_task_after_start_failure(self) -> None:
        adapter = runtime_module.OneBotAdapterRuntime()
        adapter._started = True
        adapter._restart_event = asyncio.Event()
        finished_task = asyncio.create_task(asyncio.sleep(0))
        await finished_task
        adapter._tasks["onebot_adapter.napcat_server"] = finished_task

        with (
            patch.object(adapter, "_close_websocket_server", AsyncMock()),
            patch.object(adapter, "_napcat_with_restart", AsyncMock()) as run_server,
        ):
            await adapter._on_napcat_config_change(object(), object())
            restarted_task = adapter._tasks["onebot_adapter.napcat_server"]
            await restarted_task

        self.assertIsNot(restarted_task, finished_task)
        run_server.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
