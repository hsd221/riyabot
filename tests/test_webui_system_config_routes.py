import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from src.webui import config_routes
from src.webui.routers import system as system_routes
from src.webui.token_manager import TokenManager


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
        self.assertEqual(exc.exception.detail, "重启失败")
        self.assertNotIn("scheduler down", exc.exception.detail)

    async def test_status_does_not_expose_internal_exception_details(self) -> None:
        with patch.object(system_routes, "_start_time", "sensitive runtime detail"):
            with self.assertRaises(HTTPException) as exc:
                await system_routes.get_riyabot_status(_auth=True)

        self.assertEqual(exc.exception.status_code, 500)
        self.assertEqual(exc.exception.detail, "获取状态失败")

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
            "dream": {"interval_minutes": 60},
            "bot": {
                "platform": "qq",
                "qq_account": "123",
                "nickname": "璃夜",
                "unknown_field": "remove-me",
            },
            "personality": {
                "personality": "温和",
                "reply_style": "简洁",
                "multiple_reply_style": ["旧可选风格"],
                "multiple_probability": 1.0,
                "plan_style": "旧 action 规则",
                "states": ["旧随机人格"],
                "state_probability": 1.0,
                "legacy_field": "remove-me",
            },
            "experimental": {
                "private_plan_style": "旧 action 规则",
                "chat_prompts": [],
            },
        }

        config_routes._prune_legacy_bot_config_keys(config_data)

        self.assertNotIn("mood", config_data)
        self.assertNotIn("jargon", config_data)
        self.assertNotIn("dream", config_data)
        self.assertNotIn("unknown_field", config_data["bot"])
        self.assertNotIn("legacy_field", config_data["personality"])
        self.assertEqual(set(config_data["personality"]), {"personality", "reply_style"})
        self.assertEqual(set(config_data["experimental"]), {"chat_prompts"})


class StructuredConfigRoutesSecurityTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.config_dir_patch = patch.object(config_routes, "CONFIG_DIR", self.tmp.name)
        self.config_dir_patch.start()

    def tearDown(self) -> None:
        self.config_dir_patch.stop()
        self.tmp.cleanup()

    def _write_model_config(self) -> Path:
        config_path = Path(self.tmp.name) / "model_config.toml"
        config_path.write_text(
            """# keep provider comments
[[api_providers]]
name = "primary"
base_url = "https://primary.example/v1"
api_key = "primary-super-secret"
client_type = "openai"

[[api_providers]]
name = "secondary"
base_url = "https://secondary.example/v1"
api_key = "secondary-super-secret"
client_type = "openai"
""",
            encoding="utf-8",
        )
        return config_path

    async def test_model_config_reads_mask_provider_api_keys(self) -> None:
        self._write_model_config()

        response = await config_routes.get_model_config(_auth=True)
        providers = response["config"]["api_providers"]

        self.assertEqual(providers[0]["api_key"], "prim***cret")
        self.assertEqual(providers[1]["api_key"], "seco***cret")
        self.assertNotIn("primary-super-secret", repr(response))
        self.assertNotIn("secondary-super-secret", repr(response))

    async def test_full_model_config_save_preserves_masked_api_keys_and_accepts_replacements(self) -> None:
        config_path = self._write_model_config()
        masked_config = (await config_routes.get_model_config(_auth=True))["config"]
        masked_config["api_providers"][0]["base_url"] = "https://changed.example/v1"

        with patch.object(config_routes.APIAdapterConfig, "from_dict", return_value=None):
            await config_routes.update_model_config(masked_config, _auth=True)

        saved_content = config_path.read_text(encoding="utf-8")
        self.assertIn("# keep provider comments", saved_content)
        self.assertIn('api_key = "primary-super-secret"', saved_content)
        self.assertIn('api_key = "secondary-super-secret"', saved_content)
        self.assertIn('base_url = "https://changed.example/v1"', saved_content)

        masked_config = (await config_routes.get_model_config(_auth=True))["config"]
        masked_config["api_providers"][0]["api_key"] = "replacement-secret"
        with patch.object(config_routes.APIAdapterConfig, "from_dict", return_value=None):
            await config_routes.update_model_config(masked_config, _auth=True)

        saved_content = config_path.read_text(encoding="utf-8")
        self.assertIn('api_key = "replacement-secret"', saved_content)
        self.assertNotIn('api_key = "primary-super-secret"', saved_content)

    async def test_model_provider_section_save_restores_masked_keys_by_provider_name(self) -> None:
        config_path = self._write_model_config()
        providers = (await config_routes.get_model_config(_auth=True))["config"]["api_providers"]
        reordered_providers = list(reversed(providers))

        with patch.object(config_routes.APIAdapterConfig, "from_dict", return_value=None):
            await config_routes.update_model_config_section("api_providers", reordered_providers, _auth=True)

        saved_document = config_routes.tomlkit.loads(config_path.read_text(encoding="utf-8"))
        saved_keys = {provider["name"]: provider["api_key"] for provider in saved_document["api_providers"]}
        self.assertEqual(
            saved_keys,
            {
                "primary": "primary-super-secret",
                "secondary": "secondary-super-secret",
            },
        )

    async def test_schema_read_and_save_failures_are_sanitized_in_responses_and_logs(self) -> None:
        secret = 'api_key = "super-secret" at /private/model_config.toml'

        with (
            patch.object(
                config_routes.ConfigSchemaGenerator,
                "generate_config_schema",
                side_effect=RuntimeError(secret),
            ),
            patch.object(config_routes.logger, "error") as logged,
            self.assertRaises(HTTPException) as schema_error,
        ):
            await config_routes.get_bot_config_schema(_auth=True)

        self.assertEqual(schema_error.exception.status_code, 500)
        self.assertEqual(schema_error.exception.detail, "获取配置架构失败")
        self.assertNotIn(secret, repr(logged.call_args))

        config_path = Path(self.tmp.name) / "bot_config.toml"
        config_path.write_text("[bot]\n", encoding="utf-8")
        with (
            patch.object(config_routes.tomlkit, "loads", side_effect=RuntimeError(secret)),
            patch.object(config_routes.logger, "error") as logged,
            self.assertRaises(HTTPException) as read_error,
        ):
            await config_routes.get_bot_config(_auth=True)

        self.assertEqual(read_error.exception.status_code, 500)
        self.assertEqual(read_error.exception.detail, "读取配置文件失败")
        self.assertNotIn(secret, repr(logged.call_args))

        with (
            patch.object(config_routes.Config, "from_dict", return_value=None),
            patch.object(config_routes, "format_toml_string", side_effect=OSError(secret)),
            patch.object(config_routes.logger, "error") as logged,
            self.assertRaises(HTTPException) as save_error,
        ):
            await config_routes.update_bot_config({}, _auth=True)

        self.assertEqual(save_error.exception.status_code, 500)
        self.assertEqual(save_error.exception.detail, "保存配置文件失败")
        self.assertNotIn(secret, repr(logged.call_args))

    async def test_structured_validation_failures_do_not_echo_values(self) -> None:
        secret = 'invalid api_key "super-secret" at /private/config.toml'
        cases = [
            (config_routes.update_bot_config, config_routes.Config),
            (config_routes.update_model_config, config_routes.APIAdapterConfig),
        ]

        for endpoint, config_class in cases:
            with self.subTest(endpoint=endpoint.__name__):
                with (
                    patch.object(config_class, "from_dict", side_effect=ValueError(secret)),
                    self.assertRaises(HTTPException) as validation_error,
                ):
                    await endpoint({}, _auth=True)

                self.assertEqual(validation_error.exception.status_code, 400)
                self.assertEqual(validation_error.exception.detail, "配置数据验证失败，请检查字段和值")
                self.assertNotIn("super-secret", str(validation_error.exception.detail))

    async def test_structured_reads_reject_symlinks_oversized_files_and_invalid_utf8(self) -> None:
        cases = [
            ("bot_config.toml", config_routes.get_bot_config),
            ("model_config.toml", config_routes.get_model_config),
        ]

        with tempfile.TemporaryDirectory() as outside_dir:
            outside_path = Path(outside_dir) / "outside.toml"
            outside_path.write_text('secret = "outside"\n', encoding="utf-8")

            for filename, endpoint in cases:
                with self.subTest(filename=filename, case="symlink"):
                    config_path = Path(self.tmp.name) / filename
                    config_path.symlink_to(outside_path)
                    with self.assertRaises(HTTPException) as symlink_error:
                        await endpoint(_auth=True)
                    self.assertEqual(symlink_error.exception.status_code, 400)
                    config_path.unlink()

                with self.subTest(filename=filename, case="oversized"):
                    config_path.write_text("value = 12345\n", encoding="utf-8")
                    with patch.object(config_routes, "MAX_CONFIG_FILE_BYTES", 4):
                        with self.assertRaises(HTTPException) as size_error:
                            await endpoint(_auth=True)
                    self.assertEqual(size_error.exception.status_code, 413)

                with self.subTest(filename=filename, case="invalid-utf8"):
                    config_path.write_bytes(b"\xff")
                    with self.assertRaises(HTTPException) as encoding_error:
                        await endpoint(_auth=True)
                    self.assertEqual(encoding_error.exception.status_code, 400)
                    config_path.unlink()

    async def test_structured_writes_reject_symlinks_and_preserve_existing_files_on_failure(self) -> None:
        config_path = Path(self.tmp.name) / "bot_config.toml"

        with tempfile.TemporaryDirectory() as outside_dir:
            outside_path = Path(outside_dir) / "outside.toml"
            outside_content = '[bot]\nnickname = "outside"\n'
            outside_path.write_text(outside_content, encoding="utf-8")
            config_path.symlink_to(outside_path)

            with (
                patch.object(config_routes.Config, "from_dict", return_value=None),
                self.assertRaises(HTTPException) as symlink_error,
            ):
                await config_routes.update_bot_config({"bot": {"nickname": "changed"}}, _auth=True)

            self.assertEqual(symlink_error.exception.status_code, 400)
            self.assertEqual(outside_path.read_text(encoding="utf-8"), outside_content)
            config_path.unlink()

        original_content = '[bot]\nnickname = "old"\n'
        config_path.write_text(original_content, encoding="utf-8")
        secret = 'write failed at /private/config with api_key="super-secret"'

        with (
            patch.object(config_routes.Config, "from_dict", return_value=None),
            patch.object(config_routes.os, "replace", side_effect=OSError(secret)),
            patch.object(config_routes.logger, "error") as logged,
            self.assertRaises(HTTPException) as replace_error,
        ):
            await config_routes.update_bot_config({"bot": {"nickname": "new"}}, _auth=True)

        self.assertEqual(replace_error.exception.status_code, 500)
        self.assertEqual(config_path.read_text(encoding="utf-8"), original_content)
        self.assertNotIn(secret, repr(logged.call_args))

        with (
            patch.object(config_routes.Config, "from_dict", return_value=None),
            patch.object(config_routes, "MAX_CONFIG_FILE_BYTES", 32),
            self.assertRaises(HTTPException) as size_error,
        ):
            await config_routes.update_bot_config({"bot": {"nickname": "x" * 100}}, _auth=True)

        self.assertEqual(size_error.exception.status_code, 413)
        self.assertEqual(config_path.read_text(encoding="utf-8"), original_content)

    async def test_structured_write_preserves_comments_version_and_rejects_changed_target(self) -> None:
        config_path = Path(self.tmp.name) / "bot_config.toml"
        config_path.write_text(
            '# keep this comment\n[inner]\nversion = "1.0.0"\n\n[bot]\nnickname = "old"\n',
            encoding="utf-8",
        )

        with patch.object(config_routes.Config, "from_dict", return_value=None):
            result = await config_routes.update_bot_config(
                {"inner": {"version": "9.9.9"}, "bot": {"nickname": "new"}},
                _auth=True,
            )

        self.assertTrue(result["success"])
        saved_content = config_path.read_text(encoding="utf-8")
        self.assertIn("# keep this comment", saved_content)
        self.assertIn('version = "1.0.0"', saved_content)
        self.assertIn('nickname = "new"', saved_content)
        self.assertNotIn('version = "9.9.9"', saved_content)

        _, fingerprint = config_routes._read_config_text("bot_config.toml")
        raced_content = '[bot]\nnickname = "raced"\n'
        config_path.write_text(raced_content, encoding="utf-8")

        with self.assertRaises(HTTPException) as race_error:
            config_routes._atomic_write_config("bot_config.toml", b'[bot]\nnickname = "lost"\n', fingerprint)

        self.assertEqual(race_error.exception.status_code, 409)
        self.assertEqual(config_path.read_text(encoding="utf-8"), raced_content)


class RawConfigRoutesSecurityTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.config_dir_patch = patch.object(config_routes, "CONFIG_DIR", self.tmp.name)
        self.config_dir_patch.start()

    def tearDown(self) -> None:
        self.config_dir_patch.stop()
        self.tmp.cleanup()

    async def test_raw_config_read_and_write_enforce_byte_limit_before_parsing(self) -> None:
        config_path = Path(self.tmp.name) / "bot_config.toml"
        config_path.write_text("value = 12345\n", encoding="utf-8")

        with patch.object(config_routes, "MAX_CONFIG_FILE_BYTES", 4):
            with self.assertRaises(HTTPException) as read_error:
                await config_routes.get_bot_config_raw(_auth=True)
            self.assertEqual(read_error.exception.status_code, 413)

            with (
                patch.object(config_routes.tomlkit, "loads") as loads,
                self.assertRaises(HTTPException) as write_error,
            ):
                await config_routes.update_bot_config_raw("value = 12345\n", _auth=True)

        self.assertEqual(write_error.exception.status_code, 413)
        loads.assert_not_called()

    async def test_raw_config_rejects_invalid_utf8_and_does_not_echo_toml_content(self) -> None:
        config_path = Path(self.tmp.name) / "bot_config.toml"
        config_path.write_bytes(b"\xff")

        with self.assertRaises(HTTPException) as read_error:
            await config_routes.get_bot_config_raw(_auth=True)
        self.assertEqual(read_error.exception.status_code, 400)

        secret_content = 'api_key = "super-secret"\n[broken'
        with self.assertRaises(HTTPException) as write_error:
            await config_routes.update_bot_config_raw(secret_content, _auth=True)
        self.assertEqual(write_error.exception.status_code, 400)
        self.assertNotIn("super-secret", str(write_error.exception.detail))

    async def test_raw_config_rejects_symlinks_and_preserves_existing_file_on_replace_failure(self) -> None:
        config_path = Path(self.tmp.name) / "bot_config.toml"

        with tempfile.TemporaryDirectory() as outside_dir:
            outside_path = Path(outside_dir) / "outside.toml"
            outside_content = '[bot]\nnickname = "outside"\n'
            outside_path.write_text(outside_content, encoding="utf-8")
            config_path.symlink_to(outside_path)

            with self.assertRaises(HTTPException) as read_error:
                await config_routes.get_bot_config_raw(_auth=True)
            self.assertEqual(read_error.exception.status_code, 400)

            with (
                patch.object(config_routes.Config, "from_dict", return_value=None),
                self.assertRaises(HTTPException) as write_error,
            ):
                await config_routes.update_bot_config_raw('[bot]\nnickname = "changed"\n', _auth=True)
            self.assertEqual(write_error.exception.status_code, 400)
            self.assertEqual(outside_path.read_text(encoding="utf-8"), outside_content)
            config_path.unlink()

        original_content = '[bot]\nnickname = "old"\n'
        config_path.write_text(original_content, encoding="utf-8")
        with (
            patch.object(config_routes.Config, "from_dict", return_value=None),
            patch.object(config_routes.os, "replace", side_effect=OSError("replace failed")),
            self.assertRaises(HTTPException) as replace_error,
        ):
            await config_routes.update_bot_config_raw('[bot]\nnickname = "new"\n', _auth=True)

        self.assertEqual(replace_error.exception.status_code, 500)
        self.assertEqual(config_path.read_text(encoding="utf-8"), original_content)


class AdapterConfigRoutesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_cwd = os.getcwd()
        os.chdir(self.root)
        self.project_root_patch = patch.object(config_routes, "PROJECT_ROOT", str(self.root))
        self.project_root_patch.start()
        self.token_manager = TokenManager(self.root / "data" / "webui.json")
        self.token_manager_patch = patch.object(config_routes, "get_token_manager", return_value=self.token_manager)
        self.token_manager_patch.start()

    def tearDown(self) -> None:
        self.token_manager_patch.stop()
        self.project_root_patch.stop()
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def test_adapter_path_normalization_and_relative_display(self) -> None:
        inside = self.root / "adapters" / "napcat.toml"
        outside = self.root.parent / "outside-adapter.toml"

        self.assertEqual(config_routes._normalize_adapter_path("adapters/napcat.toml"), str(inside))
        with patch.dict(config_routes.os.environ, {"MAIBOT_ALLOW_EXTERNAL_ADAPTER_CONFIG": ""}):
            with self.assertRaisesRegex(ValueError, "项目目录"):
                config_routes._normalize_adapter_path(str(outside))
        with patch.dict(config_routes.os.environ, {"MAIBOT_ALLOW_EXTERNAL_ADAPTER_CONFIG": "1"}):
            self.assertEqual(config_routes._normalize_adapter_path(str(outside)), str(outside))
        self.assertEqual(config_routes._normalize_adapter_path(""), "")
        self.assertEqual(config_routes._to_relative_path(str(inside)), "adapters/napcat.toml")
        self.assertEqual(config_routes._to_relative_path(str(outside)), str(outside))
        self.assertEqual(config_routes._to_relative_path("relative.toml"), "relative.toml")

    async def test_adapter_config_blocks_external_and_symlink_escape_paths_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_path = Path(outside_dir) / "outside.toml"
            outside_path.write_text('secret = "outside"\n', encoding="utf-8")
            symlink_path = self.root / "linked.toml"
            symlink_path.symlink_to(outside_path)

            with patch.dict(config_routes.os.environ, {"MAIBOT_ALLOW_EXTERNAL_ADAPTER_CONFIG": ""}):
                for unsafe_path in [str(outside_path), "linked.toml"]:
                    with self.subTest(path=unsafe_path):
                        with self.assertRaises(HTTPException) as read_error:
                            await config_routes.get_adapter_config(unsafe_path, _auth=True)
                        self.assertEqual(read_error.exception.status_code, 400)

                        with self.assertRaises(HTTPException) as write_error:
                            await config_routes.save_adapter_config(
                                {"path": unsafe_path, "content": "enabled = true\n"},
                                _auth=True,
                            )
                        self.assertEqual(write_error.exception.status_code, 400)

                with self.assertRaises(HTTPException) as preference_error:
                    await config_routes.save_adapter_config_path({"path": str(outside_path)}, _auth=True)
                self.assertEqual(preference_error.exception.status_code, 400)

            with patch.dict(config_routes.os.environ, {"MAIBOT_ALLOW_EXTERNAL_ADAPTER_CONFIG": "1"}):
                loaded = await config_routes.get_adapter_config(str(outside_path), _auth=True)
            self.assertEqual(loaded["content"], 'secret = "outside"\n')

    async def test_adapter_config_enforces_read_and_write_size_limits(self) -> None:
        adapter_path = self.root / "large.toml"
        adapter_path.write_text("value = 12345\n", encoding="utf-8")

        with patch.object(config_routes, "MAX_ADAPTER_CONFIG_BYTES", 4):
            with self.assertRaises(HTTPException) as read_error:
                await config_routes.get_adapter_config("large.toml", _auth=True)
            self.assertEqual(read_error.exception.status_code, 413)

            with self.assertRaises(HTTPException) as write_error:
                await config_routes.save_adapter_config(
                    {"path": "new.toml", "content": "value = 12345\n"},
                    _auth=True,
                )
            self.assertEqual(write_error.exception.status_code, 413)

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
        self.assertEqual((self.root / "data" / "webui.json").stat().st_mode & 0o777, 0o600)

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

        with self.assertRaises(HTTPException) as invalid_extension:
            await config_routes.save_adapter_config_path({"path": "adapter.txt"}, _auth=True)
        self.assertEqual(invalid_extension.exception.status_code, 400)

    async def test_adapter_config_path_revalidates_unsafe_legacy_preference(self) -> None:
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_path = Path(outside_dir) / "legacy.toml"
            outside_path.write_text("enabled = true\n", encoding="utf-8")
            (self.root / "data").mkdir(exist_ok=True)
            (self.root / "data" / "webui.json").write_text(
                json.dumps({"adapter_config_path": str(outside_path)}),
                encoding="utf-8",
            )

            with patch.dict(config_routes.os.environ, {"MAIBOT_ALLOW_EXTERNAL_ADAPTER_CONFIG": ""}):
                with self.assertRaises(HTTPException) as error:
                    await config_routes.get_adapter_config_path(_auth=True)

        self.assertEqual(error.exception.status_code, 400)
        self.assertNotIn(str(outside_path), str(error.exception.detail))

    @unittest.skipUnless(hasattr(os, "symlink"), "platform does not support symlinks")
    async def test_adapter_config_path_preference_does_not_follow_webui_config_symlink(self) -> None:
        adapter_path = self.root / "adapter.toml"
        adapter_path.write_text("enabled = true\n", encoding="utf-8")
        data_dir = self.root / "data"
        data_dir.mkdir(exist_ok=True)

        with tempfile.TemporaryDirectory() as outside_dir:
            external_path = Path(outside_dir) / "external.json"
            original_external = json.dumps({"password_hash": "do-not-touch"})
            external_path.write_text(original_external, encoding="utf-8")
            (data_dir / "webui.json").unlink()
            (data_dir / "webui.json").symlink_to(external_path)

            with self.assertRaises(HTTPException) as error:
                await config_routes.save_adapter_config_path({"path": "adapter.toml"}, _auth=True)

            self.assertEqual(error.exception.status_code, 400)
            self.assertEqual(external_path.read_text(encoding="utf-8"), original_external)

    async def test_adapter_config_read_and_write_validate_paths_extensions_and_toml(self) -> None:
        adapter_path = self.root / "adapter.toml"
        adapter_path.write_text('name = "napcat"\n', encoding="utf-8")
        text_path = self.root / "adapter.txt"
        text_path.write_text("not toml", encoding="utf-8")

        loaded = await config_routes.get_adapter_config("adapter.toml", _auth=True)
        self.assertEqual(loaded, {"success": True, "content": 'name = "napcat"\n'})

        invalid_utf8_path = self.root / "invalid-utf8.toml"
        invalid_utf8_path.write_bytes(b"\xff")
        with self.assertRaises(HTTPException) as invalid_utf8:
            await config_routes.get_adapter_config("invalid-utf8.toml", _auth=True)
        self.assertEqual(invalid_utf8.exception.status_code, 400)

        directory_path = self.root / "directory.toml"
        directory_path.mkdir()
        with self.assertRaises(HTTPException) as non_file:
            await config_routes.get_adapter_config("directory.toml", _auth=True)
        self.assertEqual(non_file.exception.status_code, 400)

        for path, expected_status in [("", 400), ("missing.toml", 404), ("adapter.txt", 400)]:
            with self.subTest(path=path):
                with self.assertRaises(HTTPException) as exc:
                    await config_routes.get_adapter_config(path, _auth=True)
                self.assertEqual(exc.exception.status_code, expected_status)

        with self.assertRaises(HTTPException) as missing_content:
            await config_routes.save_adapter_config({"path": "new.toml"}, _auth=True)
        self.assertEqual(missing_content.exception.status_code, 400)

        with self.assertRaises(HTTPException) as non_string_content:
            await config_routes.save_adapter_config({"path": "new.toml", "content": {"enabled": True}}, _auth=True)
        self.assertEqual(non_string_content.exception.status_code, 400)

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
        self.assertEqual((self.root / "nested" / "new.toml").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / "nested").stat().st_mode & 0o022, 0)


if __name__ == "__main__":
    unittest.main()
