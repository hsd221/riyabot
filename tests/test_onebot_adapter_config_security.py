import os
import tempfile
import unittest

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from plugins.onebot_adapter.adapter_core.config import config as config_module


class OneBotAdapterConfigSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.template_dir = self.root / "template"
        self.template_dir.mkdir()
        self.config_path = self.root / "config.toml"
        self.backup_dir = self.root / "config_backup"
        self.template_path = self.template_dir / "template_config.toml"
        self.template_path.write_text(
            '[inner]\nversion = "2"\n\n[feature]\nvalue = "template"\n',
            encoding="utf-8",
        )

        self.patches = [
            patch.object(config_module, "PLUGIN_DIR", self.root),
            patch.object(config_module, "TEMPLATE_DIR", self.template_dir),
            patch.object(config_module, "CONFIG_PATH", self.config_path),
            patch.object(config_module, "CONFIG_BACKUP_DIR", self.backup_dir),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self) -> None:
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.tmp.cleanup()

    @staticmethod
    def _old_config(value: str) -> str:
        return f'[inner]\nversion = "1"\n\n[feature]\nvalue = "{value}"\n'

    def test_update_config_rejects_symlink_without_touching_target(self) -> None:
        outside_path = self.root / "outside.toml"
        outside_content = self._old_config("outside-secret")
        outside_path.write_text(outside_content, encoding="utf-8")
        self.config_path.symlink_to(outside_path)

        with self.assertRaises(RuntimeError):
            config_module.update_config()

        self.assertEqual(outside_path.read_text(encoding="utf-8"), outside_content)

    def test_update_config_creates_missing_config_with_private_permissions(self) -> None:
        config_module.update_config()

        self.assertEqual(self.config_path.read_bytes(), self.template_path.read_bytes())
        self.assertEqual(self.config_path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.backup_dir.exists())

    def test_update_config_supports_platforms_without_fchmod(self) -> None:
        os_without_fchmod = SimpleNamespace(**{name: getattr(os, name) for name in dir(os) if name != "fchmod"})

        with patch.object(config_module, "os", os_without_fchmod):
            config_module.update_config()

        self.assertEqual(self.config_path.read_bytes(), self.template_path.read_bytes())

    def test_update_config_creates_secure_config_and_backup_files(self) -> None:
        original_content = self._old_config("preserved")
        self.config_path.write_text(original_content, encoding="utf-8")
        os.chmod(self.config_path, 0o666)

        config_module.update_config()

        self.assertEqual(self.config_path.stat().st_mode & 0o777, 0o600)
        self.assertIn('value = "preserved"', self.config_path.read_text(encoding="utf-8"))
        backups = list(self.backup_dir.glob("config.toml.bak.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), original_content)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.root.stat().st_mode & 0o022, 0)
        self.assertEqual(self.backup_dir.stat().st_mode & 0o022, 0)

    def test_update_config_preserves_original_when_atomic_replace_fails(self) -> None:
        original_content = self._old_config("do-not-lose")
        self.config_path.write_text(original_content, encoding="utf-8")

        with (
            patch.object(config_module.os, "replace", side_effect=OSError("replace failed with api_key=secret")),
            self.assertRaises(OSError),
        ):
            config_module.update_config()

        self.assertEqual(self.config_path.read_text(encoding="utf-8"), original_content)

    def test_update_config_uses_unique_backup_names_within_one_second(self) -> None:
        class FixedDatetime:
            values = iter(
                [
                    datetime(2026, 7, 15, 8, 30, 0, 100),
                    datetime(2026, 7, 15, 8, 30, 0, 200),
                ]
            )

            @classmethod
            def now(cls) -> datetime:
                return next(cls.values)

        with patch.object(config_module, "datetime", FixedDatetime):
            self.config_path.write_text(self._old_config("first"), encoding="utf-8")
            config_module.update_config()
            self.config_path.write_text(self._old_config("second"), encoding="utf-8")
            config_module.update_config()

        backups = list(self.backup_dir.glob("config.toml.bak.*"))
        self.assertEqual(len(backups), 2)
        self.assertEqual(
            {backup.read_text(encoding="utf-8") for backup in backups},
            {self._old_config("first"), self._old_config("second")},
        )

    @unittest.skipUnless(hasattr(os, "symlink"), "platform does not support symlinks")
    def test_load_config_rejects_symlinks_and_oversized_files(self) -> None:
        real_template_path = Path(config_module.__file__).resolve().parents[2] / "template" / "template_config.toml"
        outside_path = self.root / "valid.toml"
        outside_path.write_bytes(real_template_path.read_bytes())
        linked_path = self.root / "linked.toml"
        linked_path.symlink_to(outside_path)

        with self.assertRaises(RuntimeError):
            config_module.load_config(str(linked_path))

        hardlinked_path = self.root / "hardlinked.toml"
        os.link(outside_path, hardlinked_path)
        with self.assertRaises(RuntimeError):
            config_module.load_config(str(hardlinked_path))

        oversized_path = self.root / "oversized.toml"
        oversized_path.write_bytes(b"x" * 65)
        with (
            patch.object(config_module, "_MAX_CONFIG_FILE_BYTES", 64, create=True),
            self.assertRaisesRegex(RuntimeError, "过大"),
        ):
            config_module.load_config(str(oversized_path))


if __name__ == "__main__":
    unittest.main()
