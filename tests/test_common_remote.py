import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.common import remote


class FakeLocalStorage(dict):
    def __setitem__(self, key, value):
        super().__setitem__(key, value)

    def __delitem__(self, key):
        super().__delitem__(key)


class FakeResponse:
    def __init__(self, status: int, *, payload: dict | None = None, text: str = "") -> None:
        self.status = status
        self.payload = payload or {}
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self.payload

    async def text(self):
        return self._text


class FakeSession:
    def __init__(self, response: FakeResponse | Exception, calls: list[dict], **kwargs) -> None:
        self.response = response
        self.calls = calls
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make_session_factory(response: FakeResponse | Exception, calls: list[dict]):
    def factory(**kwargs):
        return FakeSession(response, calls, **kwargs)

    return factory


class TelemetryHeartBeatTaskTest(unittest.IsolatedAsyncioTestCase):
    def make_task(self, storage: FakeLocalStorage | None = None):
        if storage is None:
            storage = FakeLocalStorage()
        with (
            patch.object(remote, "local_storage", storage),
            patch.object(remote.TelemetryHeartBeatTask, "_get_sys_info", return_value={"os_type": "Linux"}),
        ):
            task = remote.TelemetryHeartBeatTask()
        return task, storage

    def test_sys_info_normalizes_platform_names_and_uses_config_version(self) -> None:
        with (
            patch.object(remote.platform, "python_version", return_value="3.10.0"),
            patch.object(remote.global_config, "MMC_VERSION", "9.9.9", create=True),
        ):
            for system_name, expected in [
                ("Windows", "Windows"),
                ("Linux", "Linux"),
                ("Darwin", "macOS"),
                ("Plan9", "Unknown"),
            ]:
                with patch.object(remote.platform, "system", return_value=system_name):
                    self.assertEqual(
                        remote.TelemetryHeartBeatTask._get_sys_info(),
                        {"os_type": expected, "py_version": "3.10.0", "mmc_version": "9.9.9"},
                    )

    async def test_req_uuid_requires_deploy_time_and_stores_successful_response(self) -> None:
        task, storage = self.make_task(FakeLocalStorage())

        with patch.object(remote, "local_storage", storage):
            self.assertFalse(await task._req_uuid())

        calls = []
        storage["deploy_time"] = "2026-01-01T00:00:00"
        with (
            patch.object(remote, "local_storage", storage),
            patch.object(remote, "get_tcp_connector", new=AsyncMock(return_value="connector")),
            patch.object(
                remote.aiohttp,
                "ClientSession",
                side_effect=make_session_factory(FakeResponse(200, payload={"mmc_uuid": "uuid-1"}), calls),
            ),
        ):
            self.assertTrue(await task._req_uuid())

        self.assertEqual(task.client_uuid, "uuid-1")
        self.assertEqual(storage["mmc_uuid"], "uuid-1")
        self.assertEqual(calls[0]["url"], "http://hyybuth.xyz:10058/stat/reg_client")
        self.assertEqual(calls[0]["json"], {"deploy_time": "2026-01-01T00:00:00"})

    async def test_req_uuid_retries_failures_without_real_sleep(self) -> None:
        task, storage = self.make_task(FakeLocalStorage({"deploy_time": "t"}))
        calls = []

        with (
            patch.object(remote, "local_storage", storage),
            patch.object(remote, "get_tcp_connector", new=AsyncMock(return_value="connector")),
            patch.object(
                remote.aiohttp,
                "ClientSession",
                side_effect=make_session_factory(FakeResponse(500, text="bad"), calls),
            ),
            patch.object(remote.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            self.assertFalse(await task._req_uuid())

        self.assertEqual(len(calls), 4)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [4, 16, 64])
        self.assertNotIn("mmc_uuid", storage)

    async def test_req_uuid_retries_when_success_response_lacks_uuid(self) -> None:
        task, storage = self.make_task(FakeLocalStorage({"deploy_time": "t"}))
        calls = []

        with (
            patch.object(remote, "local_storage", storage),
            patch.object(remote, "get_tcp_connector", new=AsyncMock(return_value="connector")),
            patch.object(
                remote.aiohttp,
                "ClientSession",
                side_effect=make_session_factory(FakeResponse(200, payload={"status": "ok"}), calls),
            ),
            patch.object(remote.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            self.assertFalse(await task._req_uuid())

        self.assertEqual(len(calls), 4)
        self.assertEqual(sleep.await_count, 3)
        self.assertIsNone(task.client_uuid)
        self.assertNotIn("mmc_uuid", storage)

    async def test_req_uuid_treats_post_exceptions_as_retryable_failures(self) -> None:
        task, storage = self.make_task(FakeLocalStorage({"deploy_time": "t"}))
        calls = []

        with (
            patch.object(remote, "local_storage", storage),
            patch.object(remote, "get_tcp_connector", new=AsyncMock(return_value="connector")),
            patch.object(
                remote.aiohttp,
                "ClientSession",
                side_effect=make_session_factory(RuntimeError("network down"), calls),
            ),
            patch.object(remote.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            self.assertFalse(await task._req_uuid())

        self.assertEqual(len(calls), 4)
        self.assertEqual(sleep.await_count, 3)
        self.assertIsNone(task.client_uuid)
        self.assertNotIn("mmc_uuid", storage)

    async def test_send_heartbeat_posts_info_and_resets_uuid_on_forbidden(self) -> None:
        task, storage = self.make_task(FakeLocalStorage({"mmc_uuid": "uuid-1"}))
        task.info_dict = {"os_type": "Linux"}
        calls = []

        with (
            patch.object(remote, "local_storage", storage),
            patch.object(remote, "get_tcp_connector", new=AsyncMock(return_value="connector")),
            patch.object(
                remote.aiohttp,
                "ClientSession",
                side_effect=make_session_factory(FakeResponse(204), calls),
            ),
        ):
            await task._send_heartbeat()

        self.assertEqual(calls[0]["url"], "http://hyybuth.xyz:10058/stat/client_heartbeat")
        self.assertEqual(calls[0]["headers"]["Client-UUID"], "uuid-1")
        self.assertEqual(calls[0]["json"], {"os_type": "Linux"})
        self.assertEqual(task.client_uuid, "uuid-1")

        forbidden_calls = []
        with (
            patch.object(remote, "local_storage", storage),
            patch.object(remote, "get_tcp_connector", new=AsyncMock(return_value="connector")),
            patch.object(
                remote.aiohttp,
                "ClientSession",
                side_effect=make_session_factory(FakeResponse(403), forbidden_calls),
            ),
        ):
            await task._send_heartbeat()

        self.assertIsNone(task.client_uuid)
        self.assertNotIn("mmc_uuid", storage)

    async def test_send_heartbeat_keeps_uuid_after_non_success_response(self) -> None:
        task, storage = self.make_task(FakeLocalStorage({"mmc_uuid": "uuid-1"}))
        task.info_dict = {"os_type": "Linux"}
        calls = []

        with (
            patch.object(remote, "local_storage", storage),
            patch.object(remote, "get_tcp_connector", new=AsyncMock(return_value="connector")),
            patch.object(
                remote.aiohttp,
                "ClientSession",
                side_effect=make_session_factory(FakeResponse(503, text="temporarily unavailable"), calls),
            ),
        ):
            await task._send_heartbeat()

        self.assertEqual(len(calls), 1)
        self.assertEqual(task.client_uuid, "uuid-1")
        self.assertEqual(storage["mmc_uuid"], "uuid-1")

    async def test_send_heartbeat_swallows_post_exceptions_and_keeps_uuid(self) -> None:
        task, storage = self.make_task(FakeLocalStorage({"mmc_uuid": "uuid-1"}))
        calls = []

        with (
            patch.object(remote, "local_storage", storage),
            patch.object(remote, "get_tcp_connector", new=AsyncMock(return_value="connector")),
            patch.object(
                remote.aiohttp,
                "ClientSession",
                side_effect=make_session_factory(RuntimeError("network down"), calls),
            ),
        ):
            await task._send_heartbeat()

        self.assertEqual(len(calls), 1)
        self.assertEqual(task.client_uuid, "uuid-1")
        self.assertEqual(storage["mmc_uuid"], "uuid-1")

    async def test_run_honors_telemetry_switch_and_skips_when_uuid_request_fails(self) -> None:
        task, _storage = self.make_task()

        with (
            patch.object(remote.global_config, "telemetry", SimpleNamespace(enable=False)),
            patch.object(task, "_req_uuid", new=AsyncMock(return_value=True)) as req_uuid,
            patch.object(task, "_send_heartbeat", new=AsyncMock()) as send_heartbeat,
        ):
            await task.run()

        req_uuid.assert_not_awaited()
        send_heartbeat.assert_not_awaited()

        with (
            patch.object(remote.global_config, "telemetry", SimpleNamespace(enable=True)),
            patch.object(task, "_req_uuid", new=AsyncMock(return_value=False)) as req_uuid,
            patch.object(task, "_send_heartbeat", new=AsyncMock()) as send_heartbeat,
        ):
            await task.run()

        req_uuid.assert_awaited_once()
        send_heartbeat.assert_not_awaited()

        task.client_uuid = "uuid-1"
        with (
            patch.object(remote.global_config, "telemetry", SimpleNamespace(enable=True)),
            patch.object(task, "_send_heartbeat", new=AsyncMock()) as send_heartbeat,
        ):
            await task.run()

        send_heartbeat.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
