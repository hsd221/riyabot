import http
import unittest

from types import SimpleNamespace
from unittest.mock import Mock, patch

from plugins.onebot_adapter.adapter_core import runtime as runtime_module


class OneBotAdapterServerAuthTest(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
