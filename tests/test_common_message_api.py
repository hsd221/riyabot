import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.common.message import api as message_api
from src.config.official_configs import MaimMessageConfig


class FakeMessageServer:
    instances: list["FakeMessageServer"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.valid_tokens: list[str] = []
        self.processed_messages: list[dict] = []
        self.run_count = 0
        self.stop_count = 0
        FakeMessageServer.instances.append(self)

    def add_valid_token(self, token: str) -> None:
        self.valid_tokens.append(token)

    async def process_message(self, message: dict) -> None:
        self.processed_messages.append(message)

    async def run(self) -> None:
        self.run_count += 1

    async def stop(self) -> None:
        self.stop_count += 1


class FakeServerConfig:
    instances: list["FakeServerConfig"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.on_auth = None
        self.on_message = None
        FakeServerConfig.instances.append(self)


class FakeWebSocketServer:
    instances: list["FakeWebSocketServer"] = []

    def __init__(self, config: FakeServerConfig) -> None:
        self.config = config
        self.start_count = 0
        self.stop_count = 0
        FakeWebSocketServer.instances.append(self)

    async def start(self) -> None:
        self.start_count += 1

    async def stop(self) -> None:
        self.stop_count += 1


class FakeAPIMessage:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def to_dict(self) -> dict:
        return dict(self.payload)


def maim_config(**overrides):
    data = {
        "auth_token": [],
        "enable_api_server": False,
        "api_server_host": "127.0.0.1",
        "api_server_port": 8090,
        "api_server_use_wss": False,
        "api_server_cert_file": "",
        "api_server_key_file": "",
        "api_server_allowed_api_keys": [],
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class CommonMessageAPITest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        message_api.global_api = None
        FakeMessageServer.instances.clear()
        FakeServerConfig.instances.clear()
        FakeWebSocketServer.instances.clear()

    def tearDown(self) -> None:
        message_api.global_api = None

    def test_additional_api_server_defaults_to_loopback(self) -> None:
        self.assertEqual(MaimMessageConfig().api_server_host, "127.0.0.1")

    def test_legacy_auth_tokens_normalize_a_string_and_ignore_invalid_shapes(self) -> None:
        with patch.dict(message_api.os.environ, {}, clear=True):
            self.assertEqual(
                message_api._legacy_auth_tokens(SimpleNamespace(auth_token="  legacy-token  ")),
                ["legacy-token"],
            )
            self.assertEqual(message_api._legacy_auth_tokens(SimpleNamespace(auth_token=42)), [])

    def call_get_global_api(self, *, version: str, config: SimpleNamespace):
        with (
            patch.object(message_api, "MessageServer", FakeMessageServer),
            patch.object(message_api.importlib.metadata, "version", return_value=version),
            patch.object(message_api, "global_config", SimpleNamespace(maim_message=config)),
            patch.object(message_api, "get_global_server", return_value=SimpleNamespace(get_app=lambda: "app")),
            patch.dict(message_api.os.environ, {"HOST": "127.0.0.1", "PORT": "8123"}, clear=True),
        ):
            return message_api.get_global_api()

    def test_legacy_message_server_uses_basic_kwargs_when_version_is_incompatible(self) -> None:
        api = self.call_get_global_api(
            version="0.2.9",
            config=maim_config(auth_token=["secret"]),
        )

        self.assertIs(api, FakeMessageServer.instances[0])
        self.assertEqual(api.kwargs, {"host": "127.0.0.1", "port": 8123, "app": "app"})
        self.assertEqual(api.valid_tokens, [])
        self.assertIs(message_api.get_global_api(), api)

    def test_compatible_message_server_enables_logger_token_and_custom_uvicorn_settings(self) -> None:
        api = self.call_get_global_api(
            version="0.3.3",
            config=maim_config(auth_token=["token-a", "token-b"]),
        )

        self.assertEqual(api.kwargs["host"], "127.0.0.1")
        self.assertEqual(api.kwargs["port"], 8123)
        self.assertIs(api.kwargs["app"], "app")
        self.assertIn("custom_logger", api.kwargs)
        self.assertTrue(api.kwargs["enable_token"])
        self.assertFalse(api.kwargs["enable_custom_uvicorn_logger"])
        self.assertEqual(api.valid_tokens, ["token-a", "token-b"])

    def test_legacy_remote_bind_requires_auth_or_explicit_compatibility_override(self) -> None:
        def build_api(*, version: str = "0.3.3", auth_tokens=None, extra_environment=None):
            message_api.global_api = None
            FakeMessageServer.instances.clear()
            environment = {"HOST": "0.0.0.0", "PORT": "8123", **(extra_environment or {})}
            with (
                patch.object(message_api, "MessageServer", FakeMessageServer),
                patch.object(message_api.importlib.metadata, "version", return_value=version),
                patch.object(
                    message_api,
                    "global_config",
                    SimpleNamespace(maim_message=maim_config(auth_token=auth_tokens or [])),
                ),
                patch.object(message_api, "get_global_server", return_value=SimpleNamespace(get_app=lambda: "app")),
                patch.dict(message_api.os.environ, environment, clear=True),
            ):
                return message_api.get_global_api()

        protected_api = build_api()
        self.assertEqual(protected_api.kwargs["host"], "127.0.0.1")
        self.assertNotIn("enable_token", protected_api.kwargs)

        configured_api = build_api(auth_tokens=["config-token"])
        self.assertEqual(configured_api.kwargs["host"], "0.0.0.0")
        self.assertTrue(configured_api.kwargs["enable_token"])
        self.assertEqual(configured_api.valid_tokens, ["config-token"])

        environment_api = build_api(extra_environment={"MAIBOT_LEGACY_SERVER_TOKEN": "environment-token"})
        self.assertEqual(environment_api.kwargs["host"], "0.0.0.0")
        self.assertTrue(environment_api.kwargs["enable_token"])
        self.assertEqual(environment_api.valid_tokens, ["environment-token"])

        compatibility_api = build_api(extra_environment={"MAIBOT_ALLOW_UNAUTHENTICATED_LEGACY_SERVER": "1"})
        self.assertEqual(compatibility_api.kwargs["host"], "0.0.0.0")
        self.assertNotIn("enable_token", compatibility_api.kwargs)

        unsupported_api = build_api(version="0.2.9", auth_tokens=["unsupported-token"])
        self.assertEqual(unsupported_api.kwargs["host"], "127.0.0.1")
        self.assertEqual(unsupported_api.valid_tokens, [])

    async def test_additional_api_server_configures_auth_bridge_and_lifecycle_for_supported_versions(self) -> None:
        server_module = types.ModuleType("maim_message.server")
        server_module.WebSocketServer = FakeWebSocketServer
        server_module.ServerConfig = FakeServerConfig
        message_module = types.ModuleType("maim_message.message")
        message_module.APIMessageBase = object

        with (
            patch.dict(sys.modules, {"maim_message.server": server_module, "maim_message.message": message_module}),
            patch.object(message_api, "MessageServer", FakeMessageServer),
            patch.object(message_api.importlib.metadata, "version", return_value="0.6.0"),
            patch.object(
                message_api,
                "global_config",
                SimpleNamespace(
                    maim_message=maim_config(
                        auth_token=["legacy-token"],
                        enable_api_server=True,
                        api_server_host="127.0.0.2",
                        api_server_port=9000,
                        api_server_use_wss=True,
                        api_server_cert_file="/tmp/cert.pem",
                        api_server_key_file="/tmp/key.pem",
                        api_server_allowed_api_keys=["allowed-key"],
                    )
                ),
            ),
            patch.object(message_api, "get_global_server", return_value=SimpleNamespace(get_app=lambda: "app")),
            patch.dict(message_api.os.environ, {"HOST": "127.0.0.1", "PORT": "8123"}, clear=True),
        ):
            api = message_api.get_global_api()

        self.assertIs(api.extra_server, FakeWebSocketServer.instances[0])
        config = api.extra_server.config
        self.assertEqual(
            config.kwargs,
            {
                "host": "127.0.0.2",
                "port": 9000,
                "ssl_enabled": True,
                "ssl_certfile": "/tmp/cert.pem",
                "ssl_keyfile": "/tmp/key.pem",
            },
        )
        self.assertTrue(await config.on_auth({"api_key": "allowed-key"}))
        self.assertFalse(await config.on_auth({"api_key": "denied-key"}))

        message = FakeAPIMessage(
            {
                "message_info": {
                    "platform": "qq",
                    "sender_info": {
                        "user_info": {"user_id": "user-1"},
                        "group_info": {"group_id": "group-1"},
                    },
                }
            }
        )
        await config.on_message(message, {"api_key": "allowed-key"})

        self.assertEqual(api.platform_map, {"qq": "allowed-key"})
        processed = api.processed_messages[0]
        self.assertEqual(processed["message_info"]["user_info"], {"user_id": "user-1"})
        self.assertEqual(processed["message_info"]["group_info"], {"group_id": "group-1"})
        self.assertIsNone(processed["raw_message"])

        await api.run()
        await api.stop()

        self.assertEqual(api.extra_server.start_count, 1)
        self.assertEqual(api.extra_server.stop_count, 1)
        self.assertEqual(api.run_count, 1)
        self.assertEqual(api.stop_count, 1)

    async def test_additional_api_server_allows_empty_api_keys_and_handles_platform_map_update_failures(self) -> None:
        class BrokenPlatformMap:
            def __setitem__(self, key, value):
                raise RuntimeError("map failed")

        server_module = types.ModuleType("maim_message.server")
        server_module.WebSocketServer = FakeWebSocketServer
        server_module.ServerConfig = FakeServerConfig
        message_module = types.ModuleType("maim_message.message")
        message_module.APIMessageBase = object
        safe_logger = Mock()

        with (
            patch.dict(sys.modules, {"maim_message.server": server_module, "maim_message.message": message_module}),
            patch.object(message_api, "MessageServer", FakeMessageServer),
            patch.object(message_api.importlib.metadata, "version", return_value="0.6.0"),
            patch.object(
                message_api,
                "global_config",
                SimpleNamespace(maim_message=maim_config(enable_api_server=True, api_server_allowed_api_keys=[])),
            ),
            patch.object(message_api, "get_global_server", return_value=SimpleNamespace(get_app=lambda: "app")),
            patch.object(message_api, "get_logger", return_value=safe_logger),
            patch.dict(message_api.os.environ, {"HOST": "127.0.0.1", "PORT": "8123"}, clear=True),
        ):
            api = message_api.get_global_api()

        config = api.extra_server.config
        self.assertTrue(await config.on_auth({"api_key": "any-key"}))
        api.platform_map = BrokenPlatformMap()

        await config.on_message(
            FakeAPIMessage({"message_info": {"platform": "qq", "sender_info": {}}}),
            {"api_key": "allowed-key"},
        )

        self.assertEqual(api.processed_messages[0]["message_info"]["platform"], "qq")
        self.assertNotIn("map failed", repr(safe_logger.method_calls))
        self.assertFalse(any(call.kwargs.get("exc_info") for call in safe_logger.method_calls))
        safe_logger.exception.assert_not_called()

    async def test_additional_api_server_requires_keys_for_remote_bind_unless_explicitly_allowed(self) -> None:
        server_module = types.ModuleType("maim_message.server")
        server_module.WebSocketServer = FakeWebSocketServer
        server_module.ServerConfig = FakeServerConfig
        message_module = types.ModuleType("maim_message.message")
        message_module.APIMessageBase = object

        def build_api(extra_environment: dict[str, str] | None = None):
            message_api.global_api = None
            FakeServerConfig.instances.clear()
            FakeWebSocketServer.instances.clear()
            environment = {"HOST": "127.0.0.1", "PORT": "8123", **(extra_environment or {})}
            with (
                patch.dict(sys.modules, {"maim_message.server": server_module, "maim_message.message": message_module}),
                patch.object(message_api, "MessageServer", FakeMessageServer),
                patch.object(message_api.importlib.metadata, "version", return_value="0.6.0"),
                patch.object(
                    message_api,
                    "global_config",
                    SimpleNamespace(
                        maim_message=maim_config(
                            enable_api_server=True,
                            api_server_host="0.0.0.0",
                            api_server_allowed_api_keys=[],
                        )
                    ),
                ),
                patch.object(message_api, "get_global_server", return_value=SimpleNamespace(get_app=lambda: "app")),
                patch.dict(message_api.os.environ, environment, clear=True),
            ):
                return message_api.get_global_api()

        protected_api = build_api()
        self.assertFalse(await protected_api.extra_server.config.on_auth({"api_key": "any-key"}))

        legacy_api = build_api({"MAIBOT_ALLOW_UNAUTHENTICATED_API_SERVER": "1"})
        self.assertTrue(await legacy_api.extra_server.config.on_auth({"api_key": "any-key"}))

    def test_additional_api_server_import_and_initialization_failures_keep_legacy_server_available(self) -> None:
        with (
            patch.dict(sys.modules, {"maim_message.server": None, "maim_message.message": None}),
            patch.object(message_api, "MessageServer", FakeMessageServer),
            patch.object(message_api.importlib.metadata, "version", return_value="0.6.0"),
            patch.object(
                message_api,
                "global_config",
                SimpleNamespace(maim_message=maim_config(enable_api_server=True)),
            ),
            patch.object(message_api, "get_global_server", return_value=SimpleNamespace(get_app=lambda: "app")),
            patch.dict(message_api.os.environ, {"HOST": "127.0.0.1", "PORT": "8123"}, clear=True),
        ):
            api = message_api.get_global_api()

        self.assertIs(api, FakeMessageServer.instances[0])
        self.assertFalse(hasattr(api, "extra_server"))

        message_api.global_api = None

        class FailingWebSocketServer:
            def __init__(self, config):
                raise RuntimeError("api-key-super-secret")

        server_module = types.ModuleType("maim_message.server")
        server_module.WebSocketServer = FailingWebSocketServer
        server_module.ServerConfig = FakeServerConfig
        message_module = types.ModuleType("maim_message.message")
        message_module.APIMessageBase = object
        safe_logger = Mock()

        with (
            patch.dict(sys.modules, {"maim_message.server": server_module, "maim_message.message": message_module}),
            patch.object(message_api, "MessageServer", FakeMessageServer),
            patch.object(message_api.importlib.metadata, "version", return_value="0.6.0"),
            patch.object(
                message_api,
                "global_config",
                SimpleNamespace(maim_message=maim_config(enable_api_server=True)),
            ),
            patch.object(message_api, "get_global_server", return_value=SimpleNamespace(get_app=lambda: "app")),
            patch.object(message_api, "get_logger", return_value=safe_logger),
            patch.dict(message_api.os.environ, {"HOST": "127.0.0.1", "PORT": "8123"}, clear=True),
        ):
            api = message_api.get_global_api()

        self.assertIs(api, FakeMessageServer.instances[-1])
        self.assertFalse(hasattr(api, "extra_server"))
        self.assertNotIn("api-key-super-secret", repr(safe_logger.method_calls))
        self.assertFalse(any(call.kwargs.get("exc_info") for call in safe_logger.method_calls))
        safe_logger.exception.assert_not_called()

    def test_invalid_or_missing_version_falls_back_to_basic_message_server(self) -> None:
        with (
            patch.object(message_api, "MessageServer", FakeMessageServer),
            patch.object(
                message_api.importlib.metadata,
                "version",
                side_effect=message_api.importlib.metadata.PackageNotFoundError,
            ),
            patch.object(message_api, "global_config", SimpleNamespace(maim_message=maim_config(auth_token=["token"]))),
            patch.object(message_api, "get_global_server", return_value=SimpleNamespace(get_app=lambda: "app")),
            patch.dict(message_api.os.environ, {"HOST": "127.0.0.1", "PORT": "8123"}, clear=True),
        ):
            api = message_api.get_global_api()

        self.assertEqual(api.kwargs, {"host": "127.0.0.1", "port": 8123, "app": "app"})
        self.assertEqual(api.valid_tokens, [])


if __name__ == "__main__":
    unittest.main()
