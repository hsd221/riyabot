import asyncio
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import APIRouter
from fastapi.testclient import TestClient

from src.common import server as common_server


def find_route_endpoint(app, path: str):
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"route not found: {path}")


class CommonServerTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        common_server.global_server = None

    async def test_inject_endpoint_registers_once_and_handles_probe_or_async_message_dispatch(self) -> None:
        server = common_server.Server()
        common_server._register_inject_endpoint(server.app)
        common_server._register_inject_endpoint(server.app)
        endpoints = [route for route in server.app.routes if getattr(route, "path", None) == "/message/inject"]

        self.assertEqual(len(endpoints), 1)
        endpoint = endpoints[0].endpoint
        self.assertEqual(await endpoint({"_probe": True}), {"status": "ok"})

        dispatched_messages = []

        class FakeChatBot:
            async def message_process(self, message):
                dispatched_messages.append(message)

        fake_module = ModuleType("src.chat.message_receive.bot")
        fake_module.chat_bot = FakeChatBot()
        created_tasks = []

        def fake_create_task(coro):
            created_tasks.append(coro)
            coro.close()
            return SimpleNamespace(cancel=Mock())

        with (
            patch.dict(sys.modules, {"src.chat.message_receive.bot": fake_module}),
            patch.object(common_server.asyncio, "create_task", side_effect=fake_create_task) as create_task,
        ):
            self.assertEqual(await endpoint({"message": "hello"}), {"status": "accepted"})

        create_task.assert_called_once()
        self.assertEqual(len(created_tasks), 1)
        self.assertEqual(dispatched_messages, [])

    def test_server_constructor_env_gate_address_router_and_get_app(self) -> None:
        with patch.dict(common_server.os.environ, {}, clear=True):
            server = common_server.Server(host="0.0.0.0", port=9000, app_name="TestServer")

        self.assertEqual(server._host, "0.0.0.0")
        self.assertEqual(server._port, 9000)
        self.assertEqual(server.app.title, "TestServer")
        self.assertIsNone(server.app.openapi_url)
        self.assertIsNone(server.app.docs_url)
        self.assertIsNone(server.app.redoc_url)
        self.assertFalse(any(getattr(route, "path", None) == "/message/inject" for route in server.app.routes))
        self.assertIs(server.get_app(), server.app)

        router = APIRouter()

        @router.get("/ping")
        async def ping():
            return {"pong": True}

        server.register_router(router, prefix="/api")
        response = TestClient(server.app).get("/api/ping")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"pong": True})

        server.set_address(host=None, port=None)
        self.assertEqual(server._host, "0.0.0.0")
        self.assertEqual(server._port, 9000)
        server.set_address(host="127.0.0.1", port=9001)
        self.assertEqual(server._host, "127.0.0.1")
        self.assertEqual(server._port, 9001)

        with patch.dict(common_server.os.environ, {"MAIBOT_ENABLE_INJECT_ENDPOINT": "1"}, clear=True):
            inject_server = common_server.Server()
        self.assertTrue(any(getattr(route, "path", None) == "/message/inject" for route in inject_server.app.routes))

    def test_remote_inject_endpoint_requires_and_verifies_dedicated_token(self) -> None:
        with patch.dict(common_server.os.environ, {"MAIBOT_ENABLE_INJECT_ENDPOINT": "1"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "MAIBOT_INJECT_TOKEN"):
                common_server.Server(host="0.0.0.0")

        with patch.dict(
            common_server.os.environ,
            {
                "MAIBOT_ENABLE_INJECT_ENDPOINT": "1",
                "MAIBOT_INJECT_TOKEN": "inject-secret",
            },
            clear=True,
        ):
            server = common_server.Server(host="0.0.0.0")

        client = TestClient(server.app)
        self.assertEqual(client.post("/message/inject", json={"_probe": True}).status_code, 401)
        self.assertEqual(
            client.post(
                "/message/inject",
                json={"_probe": True},
                headers={"X-MaiBot-Inject-Token": "wrong-secret"},
            ).status_code,
            401,
        )
        response = client.post(
            "/message/inject",
            json={"_probe": True},
            headers={"X-MaiBot-Inject-Token": "inject-secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    async def test_shutdown_marks_uvicorn_server_exit_and_suppresses_shutdown_errors(self) -> None:
        server = common_server.Server()
        fake_uvicorn = SimpleNamespace(should_exit=False, shutdown=AsyncMock())
        server._server = fake_uvicorn

        await server.shutdown()

        self.assertTrue(fake_uvicorn.should_exit)
        fake_uvicorn.shutdown.assert_awaited_once()
        self.assertIsNone(server._server)

        failing_uvicorn = SimpleNamespace(should_exit=False, shutdown=AsyncMock(side_effect=RuntimeError("bad stop")))
        server._server = failing_uvicorn

        await server.shutdown()

        self.assertTrue(failing_uvicorn.should_exit)
        self.assertIsNone(server._server)

        timeout_uvicorn = SimpleNamespace(should_exit=False, shutdown=AsyncMock(side_effect=asyncio.TimeoutError()))
        server._server = timeout_uvicorn

        await server.shutdown()

        self.assertTrue(timeout_uvicorn.should_exit)
        self.assertIsNone(server._server)

    async def test_run_serves_with_expected_config_and_always_shutdowns(self) -> None:
        server = common_server.Server(host="127.0.0.2", port=8123)
        fake_config = object()
        fake_uvicorn = SimpleNamespace(should_exit=False, serve=AsyncMock(), shutdown=AsyncMock())

        with (
            patch.object(common_server, "Config", return_value=fake_config) as config_cls,
            patch.object(common_server, "UvicornServer", return_value=fake_uvicorn) as uvicorn_cls,
        ):
            await server.run()

        config_cls.assert_called_once_with(
            app=server.app,
            host="127.0.0.2",
            port=8123,
            log_config=None,
            access_log=False,
            ws_max_size=104_857_600,
        )
        uvicorn_cls.assert_called_once_with(config=fake_config)
        fake_uvicorn.serve.assert_awaited_once()
        fake_uvicorn.shutdown.assert_awaited_once()
        self.assertIsNone(server._server)

    async def test_run_shuts_down_and_reraises_keyboard_interrupt(self) -> None:
        server = common_server.Server()
        fake_uvicorn = SimpleNamespace(
            should_exit=False,
            serve=AsyncMock(side_effect=KeyboardInterrupt),
            shutdown=AsyncMock(),
        )

        with (
            patch.object(common_server, "Config", return_value=object()),
            patch.object(common_server, "UvicornServer", return_value=fake_uvicorn),
        ):
            with self.assertRaises(KeyboardInterrupt):
                await server.run()

        self.assertTrue(fake_uvicorn.should_exit)
        fake_uvicorn.shutdown.assert_awaited_once()
        self.assertIsNone(server._server)

    async def test_run_wraps_unexpected_server_errors_after_shutdown(self) -> None:
        server = common_server.Server()
        fake_uvicorn = SimpleNamespace(
            should_exit=False,
            serve=AsyncMock(side_effect=ValueError("bind failed")),
            shutdown=AsyncMock(),
        )

        with (
            patch.object(common_server, "Config", return_value=object()),
            patch.object(common_server, "UvicornServer", return_value=fake_uvicorn),
        ):
            with self.assertRaisesRegex(RuntimeError, "服务器运行错误: bind failed"):
                await server.run()

        self.assertTrue(fake_uvicorn.should_exit)
        fake_uvicorn.shutdown.assert_awaited_once()
        self.assertIsNone(server._server)

    def test_get_global_server_uses_host_and_port_environment_once(self) -> None:
        sentinel = object()
        with (
            patch.dict(common_server.os.environ, {"HOST": "127.0.0.2", "PORT": "8123"}, clear=True),
            patch.object(common_server, "Server", return_value=sentinel) as server_cls,
        ):
            self.assertIs(common_server.get_global_server(), sentinel)
            self.assertIs(common_server.get_global_server(), sentinel)

        server_cls.assert_called_once_with(host="127.0.0.2", port=8123)


if __name__ == "__main__":
    unittest.main()
