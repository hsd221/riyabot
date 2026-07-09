import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from src.webui import config_routes
from src.webui.routers import system as system_routes


class SystemRoutesTest(unittest.IsolatedAsyncioTestCase):
    def test_require_auth_delegates_to_shared_cookie_or_header_auth(self) -> None:
        with patch.object(system_routes, "verify_auth_token_from_cookie_or_header", return_value=True) as verify:
            self.assertTrue(system_routes.require_auth(maibot_session="cookie-token", authorization=None))

        verify.assert_called_once_with("cookie-token", None)

    async def test_status_uses_start_time_current_time_and_version(self) -> None:
        with (
            patch.object(system_routes, "_start_time", 10.0),
            patch.object(system_routes.time, "time", return_value=25.5),
            patch.object(system_routes, "MMC_VERSION", "9.9.9"),
        ):
            status = await system_routes.get_riyabot_status(_auth=True)

        self.assertTrue(status.running)
        self.assertEqual(status.uptime, 15.5)
        self.assertEqual(status.version, "9.9.9")
        self.assertEqual(status.start_time, system_routes.datetime.fromtimestamp(10.0).isoformat())

    async def test_restart_schedules_delayed_restart_without_exiting_current_process(self) -> None:
        scheduled = []

        def fake_create_task(coro):
            scheduled.append(coro)
            coro.close()
            return object()

        with patch("asyncio.create_task", side_effect=fake_create_task):
            response = await system_routes.restart_riyabot(_auth=True)

        self.assertTrue(response.success)
        self.assertEqual(response.message, "璃夜正在重启中...")
        self.assertEqual(len(scheduled), 1)

    async def test_restart_translates_scheduler_failures_to_http_500(self) -> None:
        def failing_create_task(coro):
            coro.close()
            raise RuntimeError("scheduler down")

        with patch("asyncio.create_task", side_effect=failing_create_task):
            with self.assertRaises(HTTPException) as exc:
                await system_routes.restart_riyabot(_auth=True)

        self.assertEqual(exc.exception.status_code, 500)
        self.assertIn("scheduler down", exc.exception.detail)

    async def test_reload_config_returns_current_placeholder_response(self) -> None:
        self.assertEqual(
            await system_routes.reload_config(_auth=True),
            {"success": True, "message": "配置重载功能待实现"},
        )


class ConfigRoutesHelperTest(unittest.IsolatedAsyncioTestCase):
    async def test_section_schema_and_legacy_config_pruning_are_stable(self) -> None:
        schema = await config_routes.get_config_section_schema("model_info", _auth=True)

        self.assertTrue(schema["success"])
        self.assertEqual(schema["schema"]["className"], "ModelInfo")
        self.assertIn("model_identifier", {field["name"] for field in schema["schema"]["fields"]})

        with self.assertRaises(HTTPException) as missing:
            await config_routes.get_config_section_schema("missing-section", _auth=True)
        self.assertEqual(missing.exception.status_code, 404)

        config_data = {
            "mood": {"legacy": True},
            "jargon": {"legacy": True},
            "bot": {
                "platform": "qq",
                "qq_account": "123",
                "nickname": "璃夜",
                "unknown_field": "remove-me",
            },
            "personality": {
                "personality": "温和",
                "reply_style": "简洁",
                "legacy_field": "remove-me",
            },
        }

        config_routes._prune_legacy_bot_config_keys(config_data)

        self.assertNotIn("mood", config_data)
        self.assertNotIn("jargon", config_data)
        self.assertNotIn("unknown_field", config_data["bot"])
        self.assertNotIn("legacy_field", config_data["personality"])


class AdapterConfigRoutesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_cwd = os.getcwd()
        os.chdir(self.root)
        self.project_root_patch = patch.object(config_routes, "PROJECT_ROOT", str(self.root))
        self.project_root_patch.start()

    def tearDown(self) -> None:
        self.project_root_patch.stop()
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def test_adapter_path_normalization_and_relative_display(self) -> None:
        inside = self.root / "adapters" / "napcat.toml"
        outside = self.root.parent / "outside-adapter.toml"

        self.assertEqual(config_routes._normalize_adapter_path("adapters/napcat.toml"), str(inside))
        self.assertEqual(config_routes._normalize_adapter_path(str(outside)), str(outside))
        self.assertEqual(config_routes._normalize_adapter_path(""), "")
        self.assertEqual(config_routes._to_relative_path(str(inside)), "adapters/napcat.toml")
        self.assertEqual(config_routes._to_relative_path(str(outside)), str(outside))
        self.assertEqual(config_routes._to_relative_path("relative.toml"), "relative.toml")

    async def test_adapter_config_path_preference_round_trips_through_temp_data_file(self) -> None:
        adapter_path = self.root / "adapters" / "napcat.toml"
        adapter_path.parent.mkdir()
        adapter_path.write_text("adapter = true\n", encoding="utf-8")

        self.assertEqual(await config_routes.get_adapter_config_path(_auth=True), {"success": True, "path": None})

        saved = await config_routes.save_adapter_config_path({"path": "adapters/napcat.toml"}, _auth=True)
        self.assertEqual(saved, {"success": True, "message": "路径已保存"})
        self.assertEqual(
            json.loads((self.root / "data" / "webui.json").read_text(encoding="utf-8"))["adapter_config_path"],
            "adapters/napcat.toml",
        )

        loaded = await config_routes.get_adapter_config_path(_auth=True)
        self.assertEqual(loaded["path"], "adapters/napcat.toml")
        self.assertIsNotNone(loaded["lastModified"])

        (self.root / "data" / "webui.json").write_text(
            json.dumps({"adapter_config_path": "missing.toml"}),
            encoding="utf-8",
        )
        missing = await config_routes.get_adapter_config_path(_auth=True)
        self.assertEqual(missing, {"success": True, "path": "missing.toml", "lastModified": None})

        with self.assertRaises(HTTPException) as empty_path:
            await config_routes.save_adapter_config_path({"path": ""}, _auth=True)
        self.assertEqual(empty_path.exception.status_code, 400)

    async def test_adapter_config_read_and_write_validate_paths_extensions_and_toml(self) -> None:
        adapter_path = self.root / "adapter.toml"
        adapter_path.write_text('name = "napcat"\n', encoding="utf-8")
        text_path = self.root / "adapter.txt"
        text_path.write_text("not toml", encoding="utf-8")

        loaded = await config_routes.get_adapter_config("adapter.toml", _auth=True)
        self.assertEqual(loaded, {"success": True, "content": 'name = "napcat"\n'})

        for path, expected_status in [("", 400), ("missing.toml", 404), ("adapter.txt", 400)]:
            with self.subTest(path=path):
                with self.assertRaises(HTTPException) as exc:
                    await config_routes.get_adapter_config(path, _auth=True)
                self.assertEqual(exc.exception.status_code, expected_status)

        with self.assertRaises(HTTPException) as missing_content:
            await config_routes.save_adapter_config({"path": "new.toml"}, _auth=True)
        self.assertEqual(missing_content.exception.status_code, 400)

        with self.assertRaises(HTTPException) as invalid_extension:
            await config_routes.save_adapter_config({"path": "new.txt", "content": "name = 'x'\n"}, _auth=True)
        self.assertEqual(invalid_extension.exception.status_code, 400)

        with self.assertRaises(HTTPException) as invalid_toml:
            await config_routes.save_adapter_config({"path": "new.toml", "content": "[broken"}, _auth=True)
        self.assertEqual(invalid_toml.exception.status_code, 400)

        saved = await config_routes.save_adapter_config(
            {"path": "nested/new.toml", "content": "enabled = true\n"},
            _auth=True,
        )
        self.assertEqual(saved, {"success": True, "message": "配置已保存"})
        self.assertEqual((self.root / "nested" / "new.toml").read_text(encoding="utf-8"), "enabled = true\n")


if __name__ == "__main__":
    unittest.main()
