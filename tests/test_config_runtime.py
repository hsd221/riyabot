import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tomlkit

from src.config import config as config_module
from src.config.api_ada_configs import APIProvider, ModelInfo, ModelTaskConfig, TaskConfig


def make_model_task_config(model_list: list[str] | None = None) -> ModelTaskConfig:
    task = TaskConfig(model_list=model_list or [])
    return ModelTaskConfig(
        utils=task,
        replyer=task,
        vlm=TaskConfig(),
        voice=TaskConfig(),
        tool_use=task,
        planner=task,
        embedding=TaskConfig(),
    )


class ConfigRuntimeHelpersTest(unittest.TestCase):
    def test_created_config_files_returns_copy_and_webui_setup_marker_handles_missing_or_invalid_files(self) -> None:
        original_created = list(config_module._CREATED_CONFIG_FILES)
        try:
            config_module._CREATED_CONFIG_FILES[:] = ["bot_config.toml"]
            returned = config_module.get_created_config_files()
            returned.append("model_config.toml")
            self.assertEqual(config_module.get_created_config_files(), ["bot_config.toml"])

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                data_dir = root / "data"
                data_dir.mkdir()
                webui_path = data_dir / "webui.json"
                webui_path.write_text(
                    json.dumps({"first_setup_completed": True, "setup_completed_at": "old"}),
                    encoding="utf-8",
                )
                with patch.object(config_module, "PROJECT_ROOT", str(root)):
                    config_module._mark_webui_setup_required("created")
                marked = json.loads(webui_path.read_text(encoding="utf-8"))
                self.assertFalse(marked["first_setup_completed"])
                self.assertEqual(marked["setup_required_reason"], "created")
                self.assertNotIn("setup_completed_at", marked)
                self.assertEqual(webui_path.stat().st_mode & 0o777, 0o600)

                webui_path.write_text("{bad json", encoding="utf-8")
                with patch.object(config_module, "PROJECT_ROOT", str(root)):
                    config_module._mark_webui_setup_required("ignored")

                webui_path.unlink()
                with patch.object(config_module, "PROJECT_ROOT", str(root)):
                    config_module._mark_webui_setup_required("missing")

                if hasattr(os, "symlink"):
                    external_path = root / "external-webui.json"
                    original_external = json.dumps({"first_setup_completed": True})
                    external_path.write_text(original_external, encoding="utf-8")
                    webui_path.symlink_to(external_path)
                    with patch.object(config_module, "PROJECT_ROOT", str(root)):
                        config_module._mark_webui_setup_required("must-not-follow")
                    self.assertTrue(webui_path.is_symlink())
                    self.assertEqual(external_path.read_text(encoding="utf-8"), original_external)
        finally:
            config_module._CREATED_CONFIG_FILES[:] = original_created

    def test_toml_diff_path_and_update_helpers_preserve_versions_and_fallback_values(self) -> None:
        new = tomlkit.parse(
            """
[inner]
version = "2"
keep = 2 # new keep
added = true # added field

[nested]
value = 2
""".strip()
        )
        old = tomlkit.parse(
            """
[inner]
version = "1"
keep = 1 # old keep
removed = "x" # removed field

[nested]
value = 1
""".strip()
        )

        logs = config_module.compare_dicts(new, old)
        default_logs, changes = config_module.compare_default_values(new, old)

        self.assertTrue(any("新增: inner.added" in line for line in logs))
        self.assertTrue(any("删减: inner.removed" in line for line in logs))
        self.assertTrue(any("默认值变化: inner.keep" in line for line in default_logs))
        self.assertIn((["inner", "keep"], 1, 2), changes)
        self.assertEqual(config_module.get_value_by_path(old, ["nested", "value"]), 1)
        self.assertIsNone(config_module.get_value_by_path(old, ["missing"]))

        target = {}
        config_module.set_value_by_path(target, ["a", "b"], 1)
        self.assertEqual(target["a"]["b"], 1)
        with patch.object(config_module.tomlkit, "item", side_effect=TypeError("bad")):
            config_module.set_value_by_path(target, ["a", "fallback"], object())
        self.assertIn("fallback", target["a"])

        config_module._update_dict(old, {"inner": {"version": "skip", "keep": 3}, "nested": {"value": 4}})
        self.assertEqual(old["inner"]["version"], "1")
        self.assertEqual(old["inner"]["keep"], 3)
        self.assertEqual(old["nested"]["value"], 4)
        plain_target = {"inner": {"keep": "old"}}
        fallback_value = object()
        with patch.object(config_module.tomlkit, "item", side_effect=TypeError("bad")):
            config_module._update_dict(plain_target, {"inner": {"keep": fallback_value}})
        self.assertIs(plain_target["inner"]["keep"], fallback_value)

    def test_get_key_comment_reads_table_value_and_keytype_comments(self) -> None:
        doc = tomlkit.parse(
            """
[section] # table comment
value = 1 # value comment
""".strip()
        )

        self.assertEqual(config_module.get_key_comment(doc["section"], "ignored"), "# table comment")

        class FakeItem:
            trivia = type("Trivia", (), {"comment": "# value comment"})()

        class FakeValueContainer:
            value = {"value": FakeItem()}

        self.assertEqual(config_module.get_key_comment(FakeValueContainer(), "value"), "# value comment")

        class FakeKey:
            key = "target"
            trivia = type("Trivia", (), {"comment": "# key comment"})()

        class FakeKeysContainer:
            def keys(self):
                return [FakeKey()]

        with patch.object(config_module, "KeyType", FakeKey):
            self.assertEqual(config_module.get_key_comment(FakeKeysContainer(), "target"), "# key comment")
        self.assertIsNone(config_module.get_key_comment({}, "missing"))

    def test_version_and_blank_model_template_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text('[inner]\nversion = "1.2.3"\n', encoding="utf-8")

            self.assertEqual(config_module._get_version_from_toml(config_path), "1.2.3")
            self.assertIsNone(config_module._get_version_from_toml(Path(tmpdir) / "missing.toml"))
            no_inner = Path(tmpdir) / "no_inner.toml"
            no_inner.write_text("value = 1\n", encoding="utf-8")
            self.assertIsNone(config_module._get_version_from_toml(no_inner))

        self.assertEqual(config_module._version_tuple(None), (0,))
        self.assertEqual(config_module._version_tuple("v1.2.x-dev"), (1, 2, 0))
        self.assertTrue(config_module._is_blank_model_template({"api_providers": [], "models": []}))
        self.assertFalse(config_module._is_blank_model_template({"api_providers": [{}], "models": []}))

    def test_update_config_generic_creates_missing_config_from_template_and_marks_webui(self) -> None:
        original_created = list(config_module._CREATED_CONFIG_FILES)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                config_dir = root / "config"
                template_dir = root / "template"
                template_dir.mkdir()
                (template_dir / "bot_config_template.toml").write_text('[inner]\nversion = "1"\n', encoding="utf-8")

                with (
                    patch.object(config_module, "CONFIG_DIR", str(config_dir)),
                    patch.object(config_module, "TEMPLATE_DIR", str(template_dir)),
                    patch.object(config_module, "PROJECT_ROOT", str(root)),
                    patch.object(config_module, "_mark_webui_setup_required") as mark_setup,
                ):
                    config_module._CREATED_CONFIG_FILES.clear()
                    config_module._update_config_generic("bot_config", "bot_config_template")

                self.assertTrue((config_dir / "bot_config.toml").exists())
                self.assertEqual((config_dir / "bot_config.toml").stat().st_mode & 0o777, 0o600)
                self.assertEqual(config_dir.stat().st_mode & 0o022, 0)
                self.assertIn("bot_config.toml", config_module.get_created_config_files())
                mark_setup.assert_called_once_with("bot_config.toml 已从模板创建")
        finally:
            config_module._CREATED_CONFIG_FILES[:] = original_created

    def test_update_config_generic_migrates_defaults_versions_and_compare_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "config"
            template_dir = root / "template"
            compare_dir = template_dir / "compare"
            config_dir.mkdir()
            template_dir.mkdir()
            compare_dir.mkdir()
            (template_dir / "bot_config_template.toml").write_text(
                '[inner]\nversion = "2"\nvalue = 2\nnew_key = true\n',
                encoding="utf-8",
            )
            (compare_dir / "bot_config_template.toml").write_text(
                '[inner]\nversion = "1"\nvalue = 1\nold_key = true\n',
                encoding="utf-8",
            )
            (config_dir / "bot_config.toml").write_text(
                '[inner]\nversion = "1"\nvalue = 1\nold_key = false\n',
                encoding="utf-8",
            )

            with (
                patch.object(config_module, "CONFIG_DIR", str(config_dir)),
                patch.object(config_module, "TEMPLATE_DIR", str(template_dir)),
            ):
                config_module._update_config_generic("bot_config", "bot_config_template")

            migrated = tomlkit.parse((config_dir / "bot_config.toml").read_text(encoding="utf-8"))
            self.assertEqual(migrated["inner"]["version"], "2")
            self.assertEqual(migrated["inner"]["value"], 2)
            self.assertTrue(migrated["inner"]["new_key"])
            backups = list((config_dir / "old").glob("bot_config_*.toml"))
            self.assertTrue(backups)
            self.assertEqual((config_dir / "bot_config.toml").stat().st_mode & 0o777, 0o600)
            self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in backups))
            self.assertEqual((config_dir / "old").stat().st_mode & 0o022, 0)

    @unittest.skipUnless(hasattr(os, "symlink"), "platform does not support symlinks")
    def test_update_config_generic_rejects_symbolic_link_config_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(tmpdir)
            config_dir = root / "config"
            template_dir = root / "template"
            config_dir.mkdir()
            template_dir.mkdir()
            (template_dir / "bot_config_template.toml").write_text(
                '[inner]\nversion = "2"\n',
                encoding="utf-8",
            )
            external_path = Path(outside_dir) / "external.toml"
            original_external = '[inner]\nversion = "1"\nsecret = "do-not-touch"\n'
            external_path.write_text(original_external, encoding="utf-8")
            linked_config = config_dir / "bot_config.toml"
            linked_config.symlink_to(external_path)

            with (
                patch.object(config_module, "CONFIG_DIR", str(config_dir)),
                patch.object(config_module, "TEMPLATE_DIR", str(template_dir)),
            ):
                with self.assertRaises(RuntimeError):
                    config_module._update_config_generic("bot_config", "bot_config_template")

            self.assertTrue(linked_config.is_symlink())
            self.assertEqual(external_path.read_text(encoding="utf-8"), original_external)

    def test_update_config_generic_skips_same_version_and_blank_model_default_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "config"
            template_dir = root / "template"
            compare_dir = template_dir / "compare"
            config_dir.mkdir()
            template_dir.mkdir()
            compare_dir.mkdir()
            (template_dir / "model_config_template.toml").write_text(
                'api_providers = []\nmodels = []\n[inner]\nversion = "1"\n',
                encoding="utf-8",
            )
            (compare_dir / "model_config_template.toml").write_text(
                'api_providers = [{name = "old"}]\nmodels = []\n[inner]\nversion = "1"\n',
                encoding="utf-8",
            )
            config_path = config_dir / "model_config.toml"
            config_path.write_text('[inner]\nversion = "1"\n', encoding="utf-8")

            with (
                patch.object(config_module, "CONFIG_DIR", str(config_dir)),
                patch.object(config_module, "TEMPLATE_DIR", str(template_dir)),
            ):
                config_module._update_config_generic("model_config", "model_config_template")

            self.assertEqual(config_path.read_text(encoding="utf-8"), '[inner]\nversion = "1"\n')

    def test_update_config_generic_copies_missing_compare_and_updates_configs_without_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "config"
            template_dir = root / "template"
            config_dir.mkdir()
            template_dir.mkdir()
            (template_dir / "bot_config_template.toml").write_text(
                '[inner]\nversion = "2"\nvalue = 2\n',
                encoding="utf-8",
            )
            (config_dir / "bot_config.toml").write_text("value = 1\n", encoding="utf-8")

            with (
                patch.object(config_module, "CONFIG_DIR", str(config_dir)),
                patch.object(config_module, "TEMPLATE_DIR", str(template_dir)),
            ):
                config_module._update_config_generic("bot_config", "bot_config_template")

            self.assertTrue((template_dir / "compare" / "bot_config_template.toml").exists())
            migrated = tomlkit.parse((config_dir / "bot_config.toml").read_text(encoding="utf-8"))
            self.assertEqual(migrated["inner"]["version"], "2")

    def test_update_config_generic_logs_no_structural_changes_when_versions_differ_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "config"
            template_dir = root / "template"
            compare_dir = template_dir / "compare"
            config_dir.mkdir()
            template_dir.mkdir()
            compare_dir.mkdir()
            (template_dir / "bot_config_template.toml").write_text(
                '[inner]\nversion = "2"\nvalue = 1\n',
                encoding="utf-8",
            )
            (compare_dir / "bot_config_template.toml").write_text(
                '[inner]\nversion = "1"\nvalue = 1\n',
                encoding="utf-8",
            )
            (config_dir / "bot_config.toml").write_text(
                '[inner]\nversion = "1"\nvalue = 1\n',
                encoding="utf-8",
            )

            with (
                patch.object(config_module, "CONFIG_DIR", str(config_dir)),
                patch.object(config_module, "TEMPLATE_DIR", str(template_dir)),
                patch.object(config_module.logger, "info") as logger_info,
            ):
                config_module._update_config_generic("bot_config", "bot_config_template")

            self.assertTrue(any(call.args == ("无新增或删减项",) for call in logger_info.call_args_list))

    def test_update_config_wrappers_delegate_to_generic_updater(self) -> None:
        with patch.object(config_module, "_update_config_generic") as updater:
            config_module.update_config()
            config_module.update_model_config()

        updater.assert_any_call("bot_config", "bot_config_template")
        updater.assert_any_call("model_config", "model_config_template")


class APIAdapterConfigRuntimeTest(unittest.TestCase):
    def make_config(self, *, model_names=None, task_models=None, providers=None) -> config_module.APIAdapterConfig:
        model_names = model_names if model_names is not None else ["model-a"]
        providers = (
            providers if providers is not None else [APIProvider("provider-a", "https://api.example.test", "secret")]
        )
        models = [
            ModelInfo(model_identifier=f"id-{name}", name=name, api_provider=providers[0].name) for name in model_names
        ]
        return config_module.APIAdapterConfig(
            models=models,
            model_task_config=make_model_task_config(task_models if task_models is not None else model_names),
            api_providers=providers,
        )

    def test_api_adapter_config_validates_duplicates_unknowns_readiness_and_lookup_errors(self) -> None:
        config = self.make_config()

        self.assertTrue(config.is_runtime_ready())
        self.assertIsNone(config.get_runtime_readiness_error())
        self.assertEqual(config.get_unknown_task_models(), {})
        self.assertEqual(config.get_missing_runtime_tasks(), [])
        self.assertEqual(config.get_model_info("model-a").name, "model-a")
        self.assertEqual(config.get_provider("provider-a").name, "provider-a")

        with self.assertRaisesRegex(ValueError, "模型列表不能为空"):
            config_module.APIAdapterConfig(
                models=[], model_task_config=make_model_task_config(), api_providers=[]
            ).validate_integrity(require_complete=True)
        with self.assertRaisesRegex(ValueError, "API提供商列表不能为空"):
            config_module.APIAdapterConfig(
                models=[ModelInfo("id-a", "model-a", "provider-a")],
                model_task_config=make_model_task_config(["model-a"]),
                api_providers=[],
            ).validate_integrity(require_complete=True)
        with self.assertRaisesRegex(ValueError, "API提供商名称存在重复"):
            self.make_config(providers=[APIProvider("p", "https://a", "k"), APIProvider("p", "https://b", "k")])
        with self.assertRaisesRegex(ValueError, "模型名称存在重复"):
            self.make_config(model_names=["dup", "dup"])

        unknown = self.make_config(task_models=["missing"])
        self.assertEqual(unknown.get_unknown_task_models()["utils"], ["missing"])
        self.assertFalse(unknown.is_runtime_ready())
        self.assertIn("引用了不存在的模型", unknown.get_runtime_readiness_error())

        missing_provider = self.make_config()
        missing_provider.models[0].api_provider = "missing-provider"
        with self.assertRaisesRegex(ValueError, "api_provider 'missing-provider' 不存在"):
            missing_provider.validate_integrity(require_complete=True)

        missing_identifier = self.make_config()
        missing_identifier.models[0].model_identifier = ""
        with self.assertRaisesRegex(ValueError, "model_identifier 不能为空"):
            missing_identifier.validate_integrity()

        lazy = self.make_config()
        delattr(lazy, "models_dict")
        self.assertEqual(lazy.get_unknown_task_models(), {})

        class NotATaskConfig:
            pass

        lazy.model_task_config.utils = NotATaskConfig()
        self.assertEqual(lazy.get_missing_runtime_tasks()[0], "utils")
        self.assertEqual(lazy.get_unknown_task_models(), {})

        missing_tasks = config_module.APIAdapterConfig(
            models=[ModelInfo("id-a", "model-a", "provider-a")],
            model_task_config=make_model_task_config([]),
            api_providers=[APIProvider("provider-a", "https://api.example.test", "secret")],
        )
        self.assertIn("utils", missing_tasks.get_missing_runtime_tasks())
        self.assertFalse(missing_tasks.is_runtime_ready())

        with self.assertRaisesRegex(ValueError, "模型名称不能为空"):
            config.get_model_info("")
        with self.assertRaisesRegex(KeyError, "不存在"):
            config.get_model_info("missing")
        with self.assertRaisesRegex(ValueError, "API提供商名称不能为空"):
            config.get_provider("")
        with self.assertRaisesRegex(KeyError, "不存在"):
            config.get_provider("missing")

    def test_load_config_helpers_return_converted_objects_or_reraise_parse_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bot_config = root / "bot_config.toml"
            bot_config.write_text('[bot]\nplatform = "qq"\n', encoding="utf-8")
            model_config = root / "model_config.toml"
            model_config.write_text(
                """
[[api_providers]]
name = "provider-a"
base_url = "https://api.example.test"
api_key = "secret"

[[models]]
model_identifier = "id-a"
name = "model-a"
api_provider = "provider-a"

[model_task_config.utils]
model_list = ["model-a"]

[model_task_config.replyer]
model_list = ["model-a"]

[model_task_config.vlm]
model_list = []

[model_task_config.voice]
model_list = []

[model_task_config.tool_use]
model_list = ["model-a"]

[model_task_config.planner]
model_list = ["model-a"]

[model_task_config.embedding]
model_list = []
""".strip(),
                encoding="utf-8",
            )

            self.assertIsInstance(config_module.api_ada_load_config(str(model_config)), config_module.APIAdapterConfig)
            invalid_model_config = root / "invalid_model_config.toml"
            invalid_model_config.write_text('[[models]]\nname = "missing required fields"\n', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                config_module.api_ada_load_config(str(invalid_model_config))
            with self.assertRaisesRegex(RuntimeError, "Missing required field: 'qq_account'"):
                config_module.load_config(str(bot_config))


if __name__ == "__main__":
    unittest.main()
