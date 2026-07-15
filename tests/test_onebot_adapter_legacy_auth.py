import unittest

from types import SimpleNamespace
from unittest.mock import patch

from plugins.onebot_adapter.adapter_core import mmc_com_layer
from plugins.onebot_adapter.adapter_core.config.official_configs import RiyaBotServerConfig


class FakeRouter:
    instances: list["FakeRouter"] = []

    def __init__(self, route_config, custom_logger) -> None:
        self.route_config = route_config
        self.custom_logger = custom_logger
        self.handler = None
        self.run_count = 0
        FakeRouter.instances.append(self)

    def register_class_handler(self, handler) -> None:
        self.handler = handler

    async def run(self) -> None:
        self.run_count += 1

    async def stop(self) -> None:
        return None


class OneBotAdapterLegacyAuthTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeRouter.instances.clear()
        mmc_com_layer.router = None

    def tearDown(self) -> None:
        mmc_com_layer.router = None

    async def _start_legacy_client(self, *, configured_token: str = "", environment=None) -> FakeRouter:
        config = SimpleNamespace(
            platform_name="qq",
            host="core",
            port=8000,
            enable_api_server=False,
            base_url="",
            api_key="",
            auth_token=configured_token,
        )
        with (
            patch.object(mmc_com_layer, "Router", FakeRouter),
            patch.object(mmc_com_layer, "global_config", SimpleNamespace(maibot_server=config)),
            patch.dict(mmc_com_layer.os.environ, environment or {}, clear=True),
        ):
            await mmc_com_layer.mmc_start_com()
        return FakeRouter.instances[-1]

    def test_legacy_auth_token_is_optional_for_existing_configs(self) -> None:
        self.assertEqual(RiyaBotServerConfig().auth_token, "")
        loaded = RiyaBotServerConfig.from_dict({"host": "core", "port": 8000})
        self.assertEqual(loaded.auth_token, "")

    async def test_legacy_client_uses_configured_or_environment_token(self) -> None:
        configured_router = await self._start_legacy_client(configured_token="config-token")
        configured_target = configured_router.route_config.route_config["qq"]
        self.assertEqual(configured_target.token, "config-token")

        environment_router = await self._start_legacy_client(
            configured_token="config-token",
            environment={"MAIBOT_LEGACY_SERVER_TOKEN": "environment-token"},
        )
        environment_target = environment_router.route_config.route_config["qq"]
        self.assertEqual(environment_target.token, "environment-token")

        anonymous_router = await self._start_legacy_client(configured_token="   ")
        anonymous_target = anonymous_router.route_config.route_config["qq"]
        self.assertIsNone(anonymous_target.token)


if __name__ == "__main__":
    unittest.main()
