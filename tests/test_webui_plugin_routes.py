import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import tomlkit
from fastapi import HTTPException

from src.plugin_system.base.config_types import ConfigField
from src.webui import plugin_routes
from src.webui.git_mirror_service import MAX_RAW_FILE_BYTES


class FakeTokenManager:
    def verify_token(self, token: str) -> bool:
        return token == "valid-token"


class FakeMirrorConfig:
    def __init__(self) -> None:
        self.mirrors = {
            "github": {
                "id": "github",
                "name": "GitHub",
                "raw_prefix": "https://raw.githubusercontent.com",
                "clone_prefix": "https://github.com",
                "enabled": True,
                "priority": 10,
            }
        }

    def get_all_mirrors(self) -> list[dict]:
        return list(self.mirrors.values())

    def get_default_priority_list(self) -> list[str]:
        return ["github", "mirror"]

    def add_mirror(
        self,
        mirror_id: str,
        name: str,
        raw_prefix: str,
        clone_prefix: str,
        enabled: bool,
        priority: int,
    ) -> dict:
        if mirror_id in self.mirrors:
            raise ValueError("镜像源已存在")
        self.mirrors[mirror_id] = {
            "id": mirror_id,
            "name": name,
            "raw_prefix": raw_prefix,
            "clone_prefix": clone_prefix,
            "enabled": enabled,
            "priority": priority,
        }
        return self.mirrors[mirror_id]

    def update_mirror(
        self,
        mirror_id: str,
        name: str | None = None,
        raw_prefix: str | None = None,
        clone_prefix: str | None = None,
        enabled: bool | None = None,
        priority: int | None = None,
    ) -> dict | None:
        mirror = self.mirrors.get(mirror_id)
        if not mirror:
            return None
        updates = {
            "name": name,
            "raw_prefix": raw_prefix,
            "clone_prefix": clone_prefix,
            "enabled": enabled,
            "priority": priority,
        }
        mirror.update({key: value for key, value in updates.items() if value is not None})
        return mirror

    def delete_mirror(self, mirror_id: str) -> bool:
        return self.mirrors.pop(mirror_id, None) is not None


class FakeGitMirrorService:
    def __init__(self) -> None:
        self.config = FakeMirrorConfig()

    def check_git_installed(self) -> dict:
        return {"installed": True, "version": "git version 2.0", "error": None}

    def get_mirror_config(self) -> FakeMirrorConfig:
        return self.config


def write_manifest(plugin_dir: Path, manifest: dict) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


class PluginRouteHelperTest(unittest.TestCase):
    def test_token_path_id_version_and_config_helpers_handle_expected_edges(self) -> None:
        self.assertEqual(
            plugin_routes.get_token_from_cookie_or_header("cookie-token", "Bearer header-token"), "cookie-token"
        )
        self.assertEqual(plugin_routes.get_token_from_cookie_or_header(None, "Bearer header-token"), "header-token")
        self.assertIsNone(plugin_routes.get_token_from_cookie_or_header(None, "Token header-token"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            base_path = Path(tmp_dir)
            self.assertEqual(
                plugin_routes.validate_safe_path("nested/plugin", base_path), (base_path / "nested/plugin").resolve()
            )
            for unsafe_path in ["../escape", "/absolute", "C:\\absolute", "bad\x00path"]:
                with self.assertRaises(HTTPException):
                    plugin_routes.validate_safe_path(unsafe_path, base_path)

        self.assertEqual(plugin_routes.validate_plugin_id("作者.Plugin-1"), "作者.Plugin-1")
        for bad_id in [
            "",
            ".hidden",
            "trailing.",
            "bad/name",
            "bad\\name",
            "bad\nname",
            "bad\x1bname",
            "bad\u202ename",
            "bad..name",
            "a" * 129,
        ]:
            with self.assertRaises(HTTPException):
                plugin_routes.validate_plugin_id(bad_id)

        self.assertEqual(plugin_routes.parse_version("1.2.3.snapshot.4"), (1, 2, 3))
        self.assertEqual(plugin_routes.parse_version("1.2"), (1, 2, 0))
        self.assertEqual(plugin_routes.parse_version("bad.version"), (0, 0, 0))

        normalized = plugin_routes.normalize_dotted_keys(
            {
                "plugin.enabled": True,
                "plugin.tags": "a,b",
                "nested": {"value.key": 1},
                "conflict": "old",
                "conflict.child": "new",
            }
        )
        self.assertEqual(
            normalized,
            {
                "plugin": {"enabled": True, "tags": "a,b"},
                "nested": {"value": {"key": 1}},
                "conflict": {"child": "new"},
            },
        )

        schema = {"plugin": {"tags": ConfigField(type=list, default=[], description="标签")}}
        config = {"plugin": {"tags": "alpha, beta,, "}}
        plugin_routes.coerce_types(schema, config)
        self.assertEqual(config["plugin"]["tags"], ["alpha", "beta"])

    def test_plugin_directory_swaps_and_uninstalls_roll_back_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugins_dir = Path(tmp_dir) / "plugins"
            plugin_path = plugins_dir / "Author_Plugin"
            staged_path = plugins_dir / "staged"
            plugin_path.mkdir(parents=True)
            staged_path.mkdir()
            (plugin_path / "state.txt").write_text("old", encoding="utf-8")
            (staged_path / "state.txt").write_text("new", encoding="utf-8")
            plugin_identity = plugin_routes._directory_identity(plugin_path)
            staged_identity = plugin_routes._directory_identity(staged_path)
            real_replace = os.replace
            replace_calls = 0

            def fail_new_version_replace(source, destination):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 2:
                    raise OSError("simulated swap failure")
                return real_replace(source, destination)

            with patch.object(plugin_routes.os, "replace", side_effect=fail_new_version_replace):
                with self.assertRaises(OSError):
                    plugin_routes._replace_plugin_directory(
                        plugin_path,
                        staged_path,
                        plugins_dir,
                        plugin_identity,
                        staged_identity,
                    )

            self.assertEqual((plugin_path / "state.txt").read_text(encoding="utf-8"), "old")
            self.assertEqual((staged_path / "state.txt").read_text(encoding="utf-8"), "new")

            with patch.object(plugin_routes, "_remove_plugin_tree", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    plugin_routes._uninstall_plugin_directory(
                        plugin_path,
                        plugins_dir,
                        plugin_routes._directory_identity(plugin_path),
                    )

            self.assertEqual((plugin_path / "state.txt").read_text(encoding="utf-8"), "old")


class PluginRouteBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.old_cwd)

        self.token_patcher = patch.object(plugin_routes, "get_token_manager", return_value=FakeTokenManager())
        self.token_patcher.start()
        self.addCleanup(self.token_patcher.stop)

        self.service = FakeGitMirrorService()
        self.service_patcher = patch.object(plugin_routes, "get_git_mirror_service", return_value=self.service)
        self.service_patcher.start()
        self.addCleanup(self.service_patcher.stop)

    @property
    def plugins_dir(self) -> Path:
        return Path(self.tmp.name) / "plugins"

    def auth_kwargs(self) -> dict:
        return {"maibot_session": "valid-token", "authorization": None}


class PluginMirrorRoutesTest(PluginRouteBase):
    async def test_version_git_status_and_mirror_routes_use_service_and_auth(self) -> None:
        version = await plugin_routes.get_maimai_version()
        self.assertGreaterEqual(version.version_major, 0)

        with self.assertRaises(HTTPException) as git_status_auth_error:
            await plugin_routes.check_git_status(maibot_session=None, authorization=None)
        self.assertEqual(git_status_auth_error.exception.status_code, 401)

        git_status = await plugin_routes.check_git_status(**self.auth_kwargs())
        self.assertTrue(git_status.installed)
        self.assertEqual(git_status.version, "git version 2.0")

        with self.assertRaises(HTTPException) as auth_error:
            await plugin_routes.get_available_mirrors(maibot_session=None, authorization=None)
        self.assertEqual(auth_error.exception.status_code, 401)

        mirrors = await plugin_routes.get_available_mirrors(**self.auth_kwargs())
        self.assertEqual([mirror.id for mirror in mirrors.mirrors], ["github"])
        self.assertEqual(mirrors.default_priority, ["github", "mirror"])

        added = await plugin_routes.add_mirror(
            plugin_routes.AddMirrorRequest(
                id="mirror",
                name="Mirror",
                raw_prefix="https://mirror/raw",
                clone_prefix="https://mirror/clone",
                enabled=False,
                priority=5,
            ),
            **self.auth_kwargs(),
        )
        self.assertEqual((added.id, added.enabled, added.priority), ("mirror", False, 5))

        updated = await plugin_routes.update_mirror(
            "mirror",
            plugin_routes.UpdateMirrorRequest(name="Mirror Updated", enabled=True),
            **self.auth_kwargs(),
        )
        self.assertEqual((updated.name, updated.enabled, updated.priority), ("Mirror Updated", True, 5))

        deleted = await plugin_routes.delete_mirror("mirror", **self.auth_kwargs())
        self.assertTrue(deleted["success"])

        with self.assertRaises(HTTPException) as not_found:
            await plugin_routes.delete_mirror("missing", **self.auth_kwargs())
        self.assertEqual(not_found.exception.status_code, 404)

        with self.assertRaises(HTTPException) as duplicate:
            await plugin_routes.add_mirror(
                plugin_routes.AddMirrorRequest(
                    id="github",
                    name="Duplicate",
                    raw_prefix="https://dup/raw",
                    clone_prefix="https://dup/clone",
                ),
                **self.auth_kwargs(),
            )
        self.assertEqual(duplicate.exception.status_code, 400)

        with self.assertRaises(HTTPException) as unsafe_url:
            await plugin_routes.add_mirror(
                plugin_routes.AddMirrorRequest(
                    id="unsafe",
                    name="Unsafe",
                    raw_prefix="file:///etc/passwd",
                    clone_prefix="ext::sh -c id",
                ),
                **self.auth_kwargs(),
            )
        self.assertEqual(unsafe_url.exception.status_code, 400)

    async def test_fetch_raw_file_reports_progress_and_wraps_service_result(self) -> None:
        self.service.fetch_raw_file = AsyncMock(
            return_value={
                "success": True,
                "data": json.dumps([{"id": "a"}, {"id": "b"}]),
                "mirror_used": "github",
                "attempts": 1,
                "url": "https://raw.githubusercontent.com/MaiM-with-u/plugins/main/index.json",
            }
        )

        with patch.object(plugin_routes, "update_progress", new=AsyncMock()) as progress:
            result = await plugin_routes.fetch_raw_file(
                plugin_routes.FetchRawFileRequest(
                    owner="MaiM-with-u",
                    repo="plugins",
                    branch="main",
                    file_path="index.json",
                ),
                **self.auth_kwargs(),
            )

        self.assertTrue(result.success)
        self.assertEqual(result.mirror_used, "github")
        self.assertEqual(result.attempts, 1)
        self.service.fetch_raw_file.assert_awaited_once()
        self.assertEqual(progress.await_args_list[-1].kwargs["stage"], "success")
        self.assertEqual(progress.await_args_list[-1].kwargs["total_plugins"], 2)

    async def test_mirror_and_raw_failures_do_not_expose_internal_details(self) -> None:
        secret = 'token="super-secret" at /private/mirrors.json'
        mirror_cases = [
            (
                plugin_routes.add_mirror,
                (
                    plugin_routes.AddMirrorRequest(
                        id="mirror",
                        name="Mirror",
                        raw_prefix="https://mirror.example/raw",
                        clone_prefix="https://mirror.example/clone",
                    ),
                ),
                "添加镜像源失败",
            ),
            (
                plugin_routes.update_mirror,
                ("github", plugin_routes.UpdateMirrorRequest(name="GitHub Updated")),
                "更新镜像源失败",
            ),
        ]

        for endpoint, args, expected_detail in mirror_cases:
            with self.subTest(endpoint=endpoint.__name__):
                with (
                    patch.object(self.service, "get_mirror_config", side_effect=RuntimeError(secret)),
                    patch.object(plugin_routes.logger, "error") as logged,
                    self.assertRaises(HTTPException) as failure,
                ):
                    await endpoint(*args, **self.auth_kwargs())

                self.assertEqual(failure.exception.status_code, 500)
                self.assertEqual(failure.exception.detail, expected_detail)
                self.assertNotIn(secret, repr(logged.call_args))

        self.service.fetch_raw_file = AsyncMock(side_effect=RuntimeError(secret))
        with (
            patch.object(plugin_routes, "update_progress", new=AsyncMock()) as progress,
            patch.object(plugin_routes.logger, "error") as logged,
            self.assertRaises(HTTPException) as raw_failure,
        ):
            await plugin_routes.fetch_raw_file(
                plugin_routes.FetchRawFileRequest(
                    owner="MaiM-with-u",
                    repo="plugins",
                    branch="main",
                    file_path="index.json",
                ),
                **self.auth_kwargs(),
            )

        self.assertEqual(raw_failure.exception.status_code, 500)
        self.assertEqual(raw_failure.exception.detail, "获取 Raw 文件失败")
        self.assertEqual(progress.await_args_list[-1].kwargs["error"], "获取 Raw 文件失败")
        self.assertNotIn(secret, repr(progress.await_args_list))
        self.assertNotIn(secret, repr(logged.call_args))

    async def test_fetch_raw_file_rejects_oversized_or_excessive_plugin_data(self) -> None:
        cases = [
            ("oversized", "x" * (MAX_RAW_FILE_BYTES + 1), "Raw 文件过大"),
            ("too-many-plugins", json.dumps([{} for _ in range(10_001)]), "插件列表条目过多"),
        ]

        for name, data, expected_detail in cases:
            with self.subTest(case=name):
                self.service.fetch_raw_file = AsyncMock(
                    return_value={
                        "success": True,
                        "data": data,
                        "mirror_used": "github",
                        "attempts": 1,
                        "url": "https://raw.githubusercontent.com/MaiM-with-u/plugins/main/index.json",
                    }
                )

                with (
                    patch.object(plugin_routes, "update_progress", new=AsyncMock()) as progress,
                    self.assertRaises(HTTPException) as failure,
                ):
                    await plugin_routes.fetch_raw_file(
                        plugin_routes.FetchRawFileRequest(
                            owner="MaiM-with-u",
                            repo="plugins",
                            branch="main",
                            file_path="index.json",
                        ),
                        **self.auth_kwargs(),
                    )

                self.assertEqual(failure.exception.status_code, 413)
                self.assertEqual(failure.exception.detail, expected_detail)
                self.assertEqual(progress.await_args_list[-1].kwargs["stage"], "error")
                self.assertEqual(progress.await_args_list[-1].kwargs["error"], expected_detail)


class PluginLifecycleRoutesTest(PluginRouteBase):
    async def test_clone_repository_validates_target_path_and_delegates_to_mirror_service(self) -> None:
        async def clone_success(**kwargs):
            target_path = kwargs["target_path"]
            target_path.mkdir(parents=True, exist_ok=True)
            return {
                "success": True,
                "path": str(target_path),
                "attempts": 1,
                "mirror_used": "github",
                "url": "https://github.com/Author/Plugin",
            }

        self.service.clone_repository = AsyncMock(side_effect=clone_success)

        result = await plugin_routes.clone_repository(
            plugin_routes.CloneRepositoryRequest(
                owner="Author",
                repo="Plugin",
                target_path="Author_Plugin",
                branch="main",
                depth=1,
            ),
            **self.auth_kwargs(),
        )

        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 1)
        clone_kwargs = self.service.clone_repository.await_args.kwargs
        self.assertEqual(clone_kwargs["owner"], "Author")
        self.assertEqual(clone_kwargs["repo"], "Plugin")
        self.assertEqual(clone_kwargs["target_path"], self.plugins_dir.resolve() / "Author_Plugin")

        with self.assertRaises(HTTPException) as unsafe_path:
            await plugin_routes.clone_repository(
                plugin_routes.CloneRepositoryRequest(owner="Author", repo="Plugin", target_path="../escape"),
                **self.auth_kwargs(),
            )
        self.assertEqual(unsafe_path.exception.status_code, 400)

    async def test_clone_repository_failure_does_not_expose_internal_details(self) -> None:
        secret = 'credential="super-secret" at /private/repository'
        self.service.clone_repository = AsyncMock(side_effect=RuntimeError(secret))

        with (
            patch.object(plugin_routes.logger, "error") as logged,
            self.assertRaises(HTTPException) as failure,
        ):
            await plugin_routes.clone_repository(
                plugin_routes.CloneRepositoryRequest(
                    owner="Author",
                    repo="Plugin",
                    target_path="Author_Plugin",
                ),
                **self.auth_kwargs(),
            )

        self.assertEqual(failure.exception.status_code, 500)
        self.assertEqual(failure.exception.detail, "克隆仓库失败")
        self.assertNotIn(secret, repr(logged.call_args))

    async def test_install_plugin_writes_manifest_id_and_rejects_existing_or_invalid_clones(self) -> None:
        async def clone_with_manifest(**kwargs):
            target_path = kwargs["target_path"]
            write_manifest(
                target_path,
                {
                    "manifest_version": 1,
                    "name": "Plugin",
                    "version": "1.0.0",
                    "author": "Author",
                },
            )
            return {"success": True, "path": str(target_path), "attempts": 1}

        self.service.clone_repository = AsyncMock(side_effect=clone_with_manifest)

        with patch.object(plugin_routes, "update_progress", new=AsyncMock()) as progress:
            result = await plugin_routes.install_plugin(
                plugin_routes.InstallPluginRequest(
                    plugin_id="Author.Plugin",
                    repository_url="https://github.com/Author/Plugin.git",
                    branch="main",
                ),
                **self.auth_kwargs(),
            )

        installed_path = self.plugins_dir / "Author_Plugin"
        self.assertTrue(result["success"])
        self.assertEqual(result["plugin_id"], "Author.Plugin")
        self.assertEqual(result["path"], "plugins/Author_Plugin")
        manifest = json.loads((installed_path / "_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], "Author.Plugin")
        self.assertEqual(self.service.clone_repository.await_args.kwargs["depth"], 1)
        self.assertNotEqual(self.service.clone_repository.await_args.kwargs["target_path"], installed_path)
        self.assertEqual(progress.await_args_list[-1].kwargs["stage"], "success")

        with patch.object(plugin_routes, "update_progress", new=AsyncMock()) as existing_progress:
            with self.assertRaises(HTTPException) as existing_error:
                await plugin_routes.install_plugin(
                    plugin_routes.InstallPluginRequest(
                        plugin_id="Author.Plugin",
                        repository_url="https://github.com/Author/Plugin",
                    ),
                    **self.auth_kwargs(),
                )
        self.assertEqual(existing_error.exception.status_code, 400)
        self.assertEqual(existing_progress.await_args_list[-1].kwargs["stage"], "error")

        async def clone_without_manifest(**kwargs):
            kwargs["target_path"].mkdir(parents=True, exist_ok=True)
            return {"success": True, "path": str(kwargs["target_path"]), "attempts": 1}

        self.service.clone_repository = AsyncMock(side_effect=clone_without_manifest)
        with patch.object(plugin_routes, "update_progress", new=AsyncMock()):
            with self.assertRaises(HTTPException) as invalid_clone:
                await plugin_routes.install_plugin(
                    plugin_routes.InstallPluginRequest(
                        plugin_id="Author.Invalid",
                        repository_url="https://github.com/Author/Invalid",
                    ),
                    **self.auth_kwargs(),
                )
        self.assertEqual(invalid_clone.exception.status_code, 400)
        self.assertFalse((self.plugins_dir / "Author_Invalid").exists())

    async def test_install_rejects_unsafe_manifests_and_sanitizes_clone_failures(self) -> None:
        outside_manifest = Path(self.tmp.name) / "outside-manifest.json"
        outside_content = json.dumps(
            {
                "manifest_version": 1,
                "name": "Outside",
                "version": "1.0.0",
                "author": "Author",
            }
        )
        outside_manifest.write_text(outside_content, encoding="utf-8")

        async def clone_with_linked_manifest(**kwargs):
            target_path = kwargs["target_path"]
            target_path.mkdir(parents=True, exist_ok=True)
            (target_path / "_manifest.json").symlink_to(outside_manifest)
            return {"success": True, "path": str(target_path), "attempts": 1}

        self.service.clone_repository = AsyncMock(side_effect=clone_with_linked_manifest)
        with patch.object(plugin_routes, "update_progress", new=AsyncMock()):
            with self.assertRaises(HTTPException) as linked_manifest:
                await plugin_routes.install_plugin(
                    plugin_routes.InstallPluginRequest(
                        plugin_id="Author.Linked",
                        repository_url="https://github.com/Author/Linked",
                    ),
                    **self.auth_kwargs(),
                )

        self.assertEqual(linked_manifest.exception.status_code, 400)
        self.assertEqual(outside_manifest.read_text(encoding="utf-8"), outside_content)
        self.assertFalse((self.plugins_dir / "Author_Linked").exists())

        outside_plugin = Path(self.tmp.name) / "outside-plugin"
        write_manifest(
            outside_plugin,
            {
                "manifest_version": 1,
                "name": "Outside Directory",
                "version": "1.0.0",
                "author": "Author",
            },
        )
        outside_plugin_content = (outside_plugin / "_manifest.json").read_text(encoding="utf-8")

        async def clone_with_linked_directory(**kwargs):
            kwargs["target_path"].symlink_to(outside_plugin, target_is_directory=True)
            return {"success": True, "path": str(kwargs["target_path"]), "attempts": 1}

        self.service.clone_repository = AsyncMock(side_effect=clone_with_linked_directory)
        with patch.object(plugin_routes, "update_progress", new=AsyncMock()):
            with self.assertRaises(HTTPException) as linked_directory:
                await plugin_routes.install_plugin(
                    plugin_routes.InstallPluginRequest(
                        plugin_id="Author.LinkedDirectory",
                        repository_url="https://github.com/Author/LinkedDirectory",
                    ),
                    **self.auth_kwargs(),
                )

        self.assertEqual(linked_directory.exception.status_code, 400)
        self.assertEqual(
            (outside_plugin / "_manifest.json").read_text(encoding="utf-8"),
            outside_plugin_content,
        )
        self.assertFalse((self.plugins_dir / "Author_LinkedDirectory").exists())

        async def clone_with_oversized_manifest(**kwargs):
            write_manifest(
                kwargs["target_path"],
                {
                    "manifest_version": 1,
                    "name": "Oversized",
                    "version": "1.0.0",
                    "author": "Author",
                    "description": "x" * plugin_routes.MAX_PLUGIN_MANIFEST_BYTES,
                },
            )
            return {"success": True, "path": str(kwargs["target_path"]), "attempts": 1}

        self.service.clone_repository = AsyncMock(side_effect=clone_with_oversized_manifest)
        with patch.object(plugin_routes, "update_progress", new=AsyncMock()):
            with self.assertRaises(HTTPException) as oversized_manifest:
                await plugin_routes.install_plugin(
                    plugin_routes.InstallPluginRequest(
                        plugin_id="Author.Oversized",
                        repository_url="https://github.com/Author/Oversized",
                    ),
                    **self.auth_kwargs(),
                )

        self.assertEqual(oversized_manifest.exception.status_code, 413)
        self.assertFalse((self.plugins_dir / "Author_Oversized").exists())

        secret = "clone failed at /private/plugins with api_key=super-secret"
        self.service.clone_repository = AsyncMock(side_effect=RuntimeError(secret))
        with (
            patch.object(plugin_routes, "update_progress", new=AsyncMock()) as progress,
            patch.object(plugin_routes.logger, "error") as logged,
            self.assertRaises(HTTPException) as clone_error,
        ):
            await plugin_routes.install_plugin(
                plugin_routes.InstallPluginRequest(
                    plugin_id="Author.Failure",
                    repository_url="https://github.com/Author/Failure",
                ),
                **self.auth_kwargs(),
            )

        self.assertEqual(clone_error.exception.status_code, 500)
        self.assertEqual(clone_error.exception.detail, "插件安装失败")
        self.assertNotIn("super-secret", repr(progress.await_args_list))
        self.assertNotIn("super-secret", repr(logged.call_args))

    async def test_uninstall_plugin_removes_new_format_directory_and_reports_missing_plugin(self) -> None:
        plugin_dir = self.plugins_dir / "Author_Plugin"
        write_manifest(
            plugin_dir,
            {
                "id": "Author.Plugin",
                "manifest_version": 1,
                "name": "Plugin",
                "version": "1.0.0",
                "author": "Author",
            },
        )

        with patch.object(plugin_routes, "update_progress", new=AsyncMock()) as progress:
            result = await plugin_routes.uninstall_plugin(
                plugin_routes.UninstallPluginRequest(plugin_id="Author.Plugin"),
                **self.auth_kwargs(),
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["plugin_name"], "Plugin")
        self.assertFalse(plugin_dir.exists())
        self.assertEqual(progress.await_args_list[-1].kwargs["stage"], "success")

        with patch.object(plugin_routes, "update_progress", new=AsyncMock()) as missing_progress:
            with self.assertRaises(HTTPException) as missing_error:
                await plugin_routes.uninstall_plugin(
                    plugin_routes.UninstallPluginRequest(plugin_id="Author.Plugin"),
                    **self.auth_kwargs(),
                )
        self.assertEqual(missing_error.exception.status_code, 404)
        self.assertEqual(missing_progress.await_args_list[-1].kwargs["stage"], "error")

    async def test_update_plugin_replaces_old_manifest_and_cleans_invalid_new_clone(self) -> None:
        plugin_dir = self.plugins_dir / "Author_Plugin"
        write_manifest(
            plugin_dir,
            {
                "id": "Author.Plugin",
                "manifest_version": 1,
                "name": "Plugin",
                "version": "1.0.0",
                "author": "Author",
            },
        )
        (plugin_dir / "old.txt").write_text("old", encoding="utf-8")

        async def clone_new_version(**kwargs):
            target_path = kwargs["target_path"]
            write_manifest(
                target_path,
                {
                    "manifest_version": 1,
                    "name": "Plugin",
                    "version": "2.0.0",
                    "author": "Author",
                },
            )
            (target_path / "new.txt").write_text("new", encoding="utf-8")
            return {"success": True, "path": str(target_path), "attempts": 1}

        self.service.clone_repository = AsyncMock(side_effect=clone_new_version)

        with patch.object(plugin_routes, "update_progress", new=AsyncMock()) as progress:
            result = await plugin_routes.update_plugin(
                plugin_routes.UpdatePluginRequest(
                    plugin_id="Author.Plugin",
                    repository_url="https://github.com/Author/Plugin",
                    branch="main",
                ),
                **self.auth_kwargs(),
            )

        self.assertTrue(result["success"])
        self.assertEqual((result["old_version"], result["new_version"]), ("1.0.0", "2.0.0"))
        self.assertFalse((plugin_dir / "old.txt").exists())
        self.assertTrue((plugin_dir / "new.txt").exists())
        updated_manifest = json.loads((plugin_dir / "_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(updated_manifest["id"], "Author.Plugin")
        self.assertEqual(progress.await_args_list[-1].kwargs["stage"], "success")

        async def clone_invalid_new_version(**kwargs):
            kwargs["target_path"].mkdir(parents=True, exist_ok=True)
            return {"success": True, "path": str(kwargs["target_path"]), "attempts": 1}

        write_manifest(
            plugin_dir,
            {
                "id": "Author.Plugin",
                "manifest_version": 1,
                "name": "Plugin",
                "version": "2.0.0",
                "author": "Author",
            },
        )
        (plugin_dir / "preserve.txt").write_text("keep", encoding="utf-8")
        self.service.clone_repository = AsyncMock(side_effect=clone_invalid_new_version)

        with patch.object(plugin_routes, "update_progress", new=AsyncMock()):
            with self.assertRaises(HTTPException) as invalid_update:
                await plugin_routes.update_plugin(
                    plugin_routes.UpdatePluginRequest(
                        plugin_id="Author.Plugin",
                        repository_url="https://github.com/Author/Plugin",
                    ),
                    **self.auth_kwargs(),
                )
        self.assertEqual(invalid_update.exception.status_code, 400)
        self.assertTrue(plugin_dir.exists())
        self.assertTrue((plugin_dir / "preserve.txt").exists())
        preserved_manifest = json.loads((plugin_dir / "_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(preserved_manifest["version"], "2.0.0")

    async def test_update_preserves_old_plugin_when_clone_fails(self) -> None:
        plugin_dir = self.plugins_dir / "Author_Plugin"
        write_manifest(
            plugin_dir,
            {
                "id": "Author.Plugin",
                "manifest_version": 1,
                "name": "Plugin",
                "version": "1.0.0",
                "author": "Author",
            },
        )
        (plugin_dir / "state.db").write_text("important", encoding="utf-8")
        self.service.clone_repository = AsyncMock(
            return_value={"success": False, "error": "remote leaked /private/path", "attempts": 1}
        )

        with patch.object(plugin_routes, "update_progress", new=AsyncMock()) as progress:
            with self.assertRaises(HTTPException) as update_error:
                await plugin_routes.update_plugin(
                    plugin_routes.UpdatePluginRequest(
                        plugin_id="Author.Plugin",
                        repository_url="https://github.com/Author/Plugin",
                    ),
                    **self.auth_kwargs(),
                )

        self.assertEqual(update_error.exception.status_code, 500)
        self.assertEqual(update_error.exception.detail, "插件更新失败")
        self.assertEqual((plugin_dir / "state.db").read_text(encoding="utf-8"), "important")
        self.assertNotIn("/private/path", repr(progress.await_args_list))


class InstalledPluginRoutesTest(PluginRouteBase):
    async def test_installed_plugins_scans_manifests_infers_ids_and_deduplicates(self) -> None:
        valid = self.plugins_dir / "Author_Plugin"
        inferred = self.plugins_dir / "LegacyFolder"
        duplicate = self.plugins_dir / "Duplicate"
        invalid = self.plugins_dir / "Invalid"
        no_manifest = self.plugins_dir / "NoManifest"
        hidden = self.plugins_dir / ".hidden"

        write_manifest(
            valid,
            {
                "id": "Author.Plugin",
                "name": "Plugin",
                "version": "1.0.0",
                "author": {"name": "Author"},
            },
        )
        write_manifest(
            inferred,
            {
                "name": "Legacy",
                "version": "2.0.0",
                "author": "LegacyAuthor",
                "repository_url": "https://github.com/LegacyAuthor/LegacyRepo.git",
            },
        )
        write_manifest(
            duplicate,
            {
                "id": "Author.Plugin",
                "name": "Duplicate",
                "version": "1.1.0",
                "author": "Author",
            },
        )
        write_manifest(invalid, {"name": "Invalid"})
        no_manifest.mkdir(parents=True)
        hidden.mkdir(parents=True)

        result = await plugin_routes.get_installed_plugins(**self.auth_kwargs())

        self.assertTrue(result["success"])
        self.assertEqual(result["total"], 2)
        plugin_ids = {plugin["id"] for plugin in result["plugins"]}
        self.assertEqual(plugin_ids, {"Author.Plugin", "LegacyAuthor.LegacyRepo"})

        inferred_manifest = json.loads((inferred / "_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(inferred_manifest["id"], "LegacyAuthor.LegacyRepo")

    async def test_installed_plugins_creates_missing_plugins_directory(self) -> None:
        result = await plugin_routes.get_installed_plugins(**self.auth_kwargs())

        self.assertEqual(result, {"success": True, "plugins": []})
        self.assertTrue(self.plugins_dir.exists())

    async def test_installed_plugins_skips_symlinked_or_oversized_manifests_and_hides_absolute_paths(self) -> None:
        valid = self.plugins_dir / "ValidPlugin"
        write_manifest(
            valid,
            {
                "id": "Author.Valid",
                "name": "Valid",
                "version": "1.0.0",
                "author": "Author",
            },
        )

        with tempfile.TemporaryDirectory() as outside_dir:
            outside_plugin = Path(outside_dir) / "OutsidePlugin"
            write_manifest(
                outside_plugin,
                {
                    "id": "Outside.Plugin",
                    "name": "Outside",
                    "version": "1.0.0",
                    "author": "Outside",
                },
            )
            (self.plugins_dir / "LinkedPlugin").symlink_to(outside_plugin, target_is_directory=True)

            linked_manifest_plugin = self.plugins_dir / "LinkedManifest"
            linked_manifest_plugin.mkdir(parents=True)
            manifest_target = linked_manifest_plugin / "manifest-target.json"
            manifest_target.write_text(
                json.dumps(
                    {
                        "id": "Author.LinkedManifest",
                        "name": "Linked",
                        "version": "1.0.0",
                    }
                ),
                encoding="utf-8",
            )
            (linked_manifest_plugin / "_manifest.json").symlink_to(manifest_target)

            result = await plugin_routes.get_installed_plugins(**self.auth_kwargs())

        self.assertEqual([plugin["id"] for plugin in result["plugins"]], ["Author.Valid"])
        self.assertEqual(result["plugins"][0]["path"], "plugins/ValidPlugin")
        self.assertFalse(Path(result["plugins"][0]["path"]).is_absolute())

        oversized = self.plugins_dir / "Oversized"
        write_manifest(
            oversized,
            {
                "id": "Author.Oversized",
                "name": "Oversized",
                "version": "1.0.0",
            },
        )
        with patch.object(plugin_routes, "MAX_PLUGIN_MANIFEST_BYTES", 8):
            limited_result = await plugin_routes.get_installed_plugins(**self.auth_kwargs())
        self.assertEqual(limited_result["plugins"], [])

    async def test_local_readme_returns_matching_file_or_structured_failure(self) -> None:
        plugin_dir = self.plugins_dir / "Author_Plugin"
        write_manifest(
            plugin_dir,
            {"id": "Author.Plugin", "name": "Plugin", "version": "1.0.0", "author": "Author"},
        )
        (plugin_dir / "readme.md").write_text("# Plugin\n\n说明", encoding="utf-8")

        success = await plugin_routes.get_local_plugin_readme("Author.Plugin", **self.auth_kwargs())
        missing_readme = await plugin_routes.get_local_plugin_readme("Missing.Plugin", **self.auth_kwargs())

        self.assertEqual(success, {"success": True, "data": "# Plugin\n\n说明"})
        self.assertEqual(missing_readme, {"success": False, "error": "插件未安装"})


class PluginConfigRoutesTest(PluginRouteBase):
    def setUp(self) -> None:
        super().setUp()
        self.plugin_dir = self.plugins_dir / "Author_Plugin"
        write_manifest(
            self.plugin_dir,
            {"id": "Author.Plugin", "name": "Plugin", "version": "1.0.0", "author": "Author"},
        )

    def write_config(self, content: str = '[plugin]\nenabled = true\ntags = ["old"]\n') -> None:
        (self.plugin_dir / "config.toml").write_text(content, encoding="utf-8")

    async def test_loaded_schema_is_returned_before_filesystem_fallback(self) -> None:
        loaded_plugin = SimpleNamespace(
            plugin_name="LoadedPlugin",
            get_manifest_info=lambda key, default=None: "Author.Plugin" if key == "id" else default,
            get_webui_config_schema=lambda: {"plugin_id": "Author.Plugin", "sections": {"plugin": {}}},
        )
        fake_manager = SimpleNamespace(
            list_loaded_plugins=lambda: ["LoadedPlugin"],
            get_plugin_instance=lambda _: loaded_plugin,
        )

        with patch("src.plugin_system.core.plugin_manager.plugin_manager", fake_manager):
            result = await plugin_routes.get_plugin_config_schema("Author.Plugin", **self.auth_kwargs())

        self.assertEqual(result["schema"]["plugin_id"], "Author.Plugin")

    async def test_filesystem_schema_raw_and_config_routes_read_current_plugin_files(self) -> None:
        self.write_config(
            """
[plugin]
enabled = true
threshold = 3
names = ["alpha", "beta"]

[[items]]
name = "first"
score = 1
""".strip()
        )
        fake_manager = SimpleNamespace(list_loaded_plugins=lambda: [], get_plugin_instance=lambda _: None)

        with patch("src.plugin_system.core.plugin_manager.plugin_manager", fake_manager):
            schema_result = await plugin_routes.get_plugin_config_schema("Author.Plugin", **self.auth_kwargs())
        raw_result = await plugin_routes.get_plugin_config_raw("Author.Plugin", **self.auth_kwargs())
        config_result = await plugin_routes.get_plugin_config("Author.Plugin", **self.auth_kwargs())

        self.assertTrue(schema_result["success"])
        self.assertEqual(schema_result["schema"]["sections"]["plugin"]["fields"]["enabled"]["ui_type"], "switch")
        self.assertEqual(schema_result["schema"]["sections"]["plugin"]["fields"]["names"]["item_type"], "string")
        self.assertIn("[[items]]", raw_result["config"])
        self.assertTrue(config_result["config"]["plugin"]["enabled"])
        self.assertEqual(config_result["config"]["plugin"]["threshold"], 3)

    async def test_raw_config_update_validates_toml_and_creates_backup(self) -> None:
        self.write_config("[plugin]\nenabled = true\n")

        result = await plugin_routes.update_plugin_config_raw(
            "Author.Plugin",
            plugin_routes.UpdatePluginConfigRequest(config="[plugin]\nenabled = false\n"),
            **self.auth_kwargs(),
        )

        self.assertTrue(result["success"])
        self.assertIn("enabled = false", (self.plugin_dir / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual(len(list(self.plugin_dir.glob("config.toml.backup.*"))), 1)

        with self.assertRaises(HTTPException) as not_string:
            await plugin_routes.update_plugin_config_raw(
                "Author.Plugin",
                plugin_routes.UpdatePluginConfigRequest(config={"plugin": {"enabled": True}}),
                **self.auth_kwargs(),
            )
        self.assertEqual(not_string.exception.status_code, 400)

        with self.assertRaises(HTTPException) as bad_toml:
            await plugin_routes.update_plugin_config_raw(
                "Author.Plugin",
                plugin_routes.UpdatePluginConfigRequest(config="[plugin\n"),
                **self.auth_kwargs(),
            )
        self.assertEqual(bad_toml.exception.status_code, 400)

    async def test_config_routes_reject_symlink_escape_and_enforce_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_plugin = Path(outside_dir) / "OutsidePlugin"
            write_manifest(
                outside_plugin,
                {"id": "Outside.Plugin", "name": "Outside", "version": "1.0.0", "author": "Outside"},
            )
            outside_config = outside_plugin / "config.toml"
            outside_config.write_text('secret = "outside"\n', encoding="utf-8")
            self.plugins_dir.mkdir(parents=True, exist_ok=True)
            (self.plugins_dir / "LinkedPlugin").symlink_to(outside_plugin, target_is_directory=True)

            with self.assertRaises(HTTPException) as read_escape:
                await plugin_routes.get_plugin_config_raw("Outside.Plugin", **self.auth_kwargs())
            self.assertIn(read_escape.exception.status_code, {400, 404})

            with self.assertRaises(HTTPException) as write_escape:
                await plugin_routes.update_plugin_config_raw(
                    "Outside.Plugin",
                    plugin_routes.UpdatePluginConfigRequest(config='secret = "changed"\n'),
                    **self.auth_kwargs(),
                )
            self.assertIn(write_escape.exception.status_code, {400, 404})
            self.assertEqual(outside_config.read_text(encoding="utf-8"), 'secret = "outside"\n')

        self.write_config("value = 12345\n")
        with patch.object(plugin_routes, "MAX_PLUGIN_CONFIG_BYTES", 4):
            with self.assertRaises(HTTPException) as oversized_read:
                await plugin_routes.get_plugin_config_raw("Author.Plugin", **self.auth_kwargs())
            self.assertEqual(oversized_read.exception.status_code, 413)

            with self.assertRaises(HTTPException) as oversized_write:
                await plugin_routes.update_plugin_config_raw(
                    "Author.Plugin",
                    plugin_routes.UpdatePluginConfigRequest(config="value = 12345\n"),
                    **self.auth_kwargs(),
                )
            self.assertEqual(oversized_write.exception.status_code, 413)

    async def test_raw_config_rejects_invalid_utf8_and_sanitizes_toml_errors(self) -> None:
        (self.plugin_dir / "config.toml").write_bytes(b"\xff")

        with self.assertRaises(HTTPException) as invalid_encoding:
            await plugin_routes.get_plugin_config_raw("Author.Plugin", **self.auth_kwargs())
        self.assertEqual(invalid_encoding.exception.status_code, 400)

        secret_content = 'api_key = "super-secret"\n[broken'
        with self.assertRaises(HTTPException) as invalid_toml:
            await plugin_routes.update_plugin_config_raw(
                "Author.Plugin",
                plugin_routes.UpdatePluginConfigRequest(config=secret_content),
                **self.auth_kwargs(),
            )
        self.assertEqual(invalid_toml.exception.status_code, 400)
        self.assertNotIn("super-secret", str(invalid_toml.exception.detail))

    async def test_structured_config_update_normalizes_webui_payload_and_coerces_schema_types(self) -> None:
        self.write_config('[plugin]\nenabled = true\ntags = ["old"]\n')
        plugin_instance = SimpleNamespace(
            config_schema={
                "plugin": {
                    "tags": ConfigField(type=list, default=[], description="标签"),
                }
            }
        )

        with patch.object(plugin_routes, "find_plugin_instance", return_value=plugin_instance):
            result = await plugin_routes.update_plugin_config(
                "Author.Plugin",
                plugin_routes.UpdatePluginConfigRequest(
                    config={"plugin.enabled": False, "plugin.tags": "alpha, beta", "extra.value": 7}
                ),
                **self.auth_kwargs(),
            )

        self.assertTrue(result["success"])
        saved = tomlkit.loads((self.plugin_dir / "config.toml").read_text(encoding="utf-8"))
        self.assertFalse(saved["plugin"]["enabled"])
        self.assertEqual(list(saved["plugin"]["tags"]), ["alpha", "beta"])
        self.assertEqual(saved["extra"]["value"], 7)
        self.assertEqual(len(list(self.plugin_dir.glob("config.toml.backup.*"))), 1)

    async def test_structured_config_routes_reject_symlinked_plugin_and_config_files(self) -> None:
        with tempfile.TemporaryDirectory() as outside_dir:
            outside_root = Path(outside_dir)
            outside_plugin = outside_root / "OutsidePlugin"
            write_manifest(
                outside_plugin,
                {
                    "id": "Outside.Plugin",
                    "name": "Outside",
                    "version": "1.0.0",
                    "author": "Outside",
                },
            )
            outside_config = outside_plugin / "config.toml"
            outside_config.write_text('[plugin]\nenabled = true\nsecret = "outside"\n', encoding="utf-8")
            (self.plugins_dir / "LinkedPlugin").symlink_to(outside_plugin, target_is_directory=True)

            calls = [
                lambda: plugin_routes.get_plugin_config("Outside.Plugin", **self.auth_kwargs()),
                lambda: plugin_routes.update_plugin_config(
                    "Outside.Plugin",
                    plugin_routes.UpdatePluginConfigRequest(config={"plugin": {"enabled": False}}),
                    **self.auth_kwargs(),
                ),
                lambda: plugin_routes.reset_plugin_config("Outside.Plugin", **self.auth_kwargs()),
                lambda: plugin_routes.toggle_plugin("Outside.Plugin", **self.auth_kwargs()),
            ]
            for call in calls:
                with self.subTest(call=call):
                    with self.assertRaises(HTTPException) as escaped:
                        await call()
                    self.assertIn(escaped.exception.status_code, {400, 404})

            self.assertEqual(
                outside_config.read_text(encoding="utf-8"),
                '[plugin]\nenabled = true\nsecret = "outside"\n',
            )

            linked_config_target = outside_root / "linked-config.toml"
            linked_config_target.write_text('[plugin]\nenabled = true\nsecret = "linked"\n', encoding="utf-8")
            (self.plugin_dir / "config.toml").symlink_to(linked_config_target)

            linked_calls = [
                lambda: plugin_routes.get_plugin_config("Author.Plugin", **self.auth_kwargs()),
                lambda: plugin_routes.update_plugin_config(
                    "Author.Plugin",
                    plugin_routes.UpdatePluginConfigRequest(config={"plugin": {"enabled": False}}),
                    **self.auth_kwargs(),
                ),
                lambda: plugin_routes.reset_plugin_config("Author.Plugin", **self.auth_kwargs()),
                lambda: plugin_routes.toggle_plugin("Author.Plugin", **self.auth_kwargs()),
            ]
            for call in linked_calls:
                with self.subTest(call=call):
                    with self.assertRaises(HTTPException) as linked:
                        await call()
                    self.assertEqual(linked.exception.status_code, 400)

            fake_manager = SimpleNamespace(list_loaded_plugins=lambda: [], get_plugin_instance=lambda _: None)
            with patch("src.plugin_system.core.plugin_manager.plugin_manager", fake_manager):
                with self.assertRaises(HTTPException) as linked_schema:
                    await plugin_routes.get_plugin_config_schema("Author.Plugin", **self.auth_kwargs())
            self.assertEqual(linked_schema.exception.status_code, 400)

            self.assertEqual(
                linked_config_target.read_text(encoding="utf-8"),
                '[plugin]\nenabled = true\nsecret = "linked"\n',
            )

    async def test_structured_config_routes_enforce_size_encoding_and_sanitized_toml_errors(self) -> None:
        self.write_config("value = 12345\n")
        with patch.object(plugin_routes, "MAX_PLUGIN_CONFIG_BYTES", 4):
            for call in [
                lambda: plugin_routes.get_plugin_config("Author.Plugin", **self.auth_kwargs()),
                lambda: plugin_routes.toggle_plugin("Author.Plugin", **self.auth_kwargs()),
            ]:
                with self.subTest(call=call):
                    with self.assertRaises(HTTPException) as oversized:
                        await call()
                    self.assertEqual(oversized.exception.status_code, 413)

        original_config = "value = 1\n"
        self.write_config(original_config)
        with patch.object(plugin_routes, "MAX_PLUGIN_CONFIG_BYTES", 32):
            with self.assertRaises(HTTPException) as oversized_output:
                await plugin_routes.update_plugin_config(
                    "Author.Plugin",
                    plugin_routes.UpdatePluginConfigRequest(config={"value": "x" * 64}),
                    **self.auth_kwargs(),
                )
        self.assertEqual(oversized_output.exception.status_code, 413)
        self.assertEqual((self.plugin_dir / "config.toml").read_text(encoding="utf-8"), original_config)

        (self.plugin_dir / "config.toml").write_bytes(b"\xff")
        with self.assertRaises(HTTPException) as invalid_encoding:
            await plugin_routes.get_plugin_config("Author.Plugin", **self.auth_kwargs())
        self.assertEqual(invalid_encoding.exception.status_code, 400)

        secret_config = 'api_key = "super-secret"\n[broken'
        self.write_config(secret_config)
        for call in [
            lambda: plugin_routes.get_plugin_config("Author.Plugin", **self.auth_kwargs()),
            lambda: plugin_routes.toggle_plugin("Author.Plugin", **self.auth_kwargs()),
            lambda: plugin_routes.update_plugin_config(
                "Author.Plugin",
                plugin_routes.UpdatePluginConfigRequest(config={"plugin": {"enabled": False}}),
                **self.auth_kwargs(),
            ),
        ]:
            with self.subTest(call=call):
                with self.assertRaises(HTTPException) as invalid_toml:
                    await call()
                self.assertEqual(invalid_toml.exception.status_code, 400)
                self.assertNotIn("super-secret", str(invalid_toml.exception.detail))

    async def test_config_backups_are_bounded_and_failed_atomic_replace_preserves_original(self) -> None:
        self.write_config("value = 0\n")
        with patch.object(plugin_routes, "MAX_PLUGIN_CONFIG_BACKUPS", 2):
            for value in range(1, 4):
                await plugin_routes.update_plugin_config_raw(
                    "Author.Plugin",
                    plugin_routes.UpdatePluginConfigRequest(config=f"value = {value}\n"),
                    **self.auth_kwargs(),
                )

        backups = sorted(self.plugin_dir.glob("config.toml.backup.*"))
        self.assertEqual(len(backups), 2)
        self.assertEqual(
            {backup.read_text(encoding="utf-8") for backup in backups},
            {"value = 1\n", "value = 2\n"},
        )

        original_config = (self.plugin_dir / "config.toml").read_text(encoding="utf-8")
        real_replace = os.replace

        def fail_config_replace(source: str | Path, destination: str | Path) -> None:
            if Path(destination).name == "config.toml":
                raise OSError("replace failed")
            real_replace(source, destination)

        with patch.object(plugin_routes.os, "replace", side_effect=fail_config_replace):
            with self.assertRaises(HTTPException) as failed_write:
                await plugin_routes.update_plugin_config_raw(
                    "Author.Plugin",
                    plugin_routes.UpdatePluginConfigRequest(config="value = 4\n"),
                    **self.auth_kwargs(),
                )
        self.assertEqual(failed_write.exception.status_code, 500)
        self.assertNotIn("replace failed", str(failed_write.exception.detail))
        self.assertEqual((self.plugin_dir / "config.toml").read_text(encoding="utf-8"), original_config)

    async def test_reset_backup_matches_the_config_that_was_atomically_removed(self) -> None:
        self.write_config("value = 1\n")
        original_read = plugin_routes._read_limited_bytes
        replaced_during_read = False

        def replace_after_read(path: Path, max_bytes: int, label: str) -> bytes:
            nonlocal replaced_during_read
            content = original_read(path, max_bytes, label)
            if path.name == "config.toml" and not replaced_during_read:
                path.write_text("value = 2\n", encoding="utf-8")
                replaced_during_read = True
            return content

        with patch.object(plugin_routes, "_read_limited_bytes", side_effect=replace_after_read):
            result = await plugin_routes.reset_plugin_config("Author.Plugin", **self.auth_kwargs())

        self.assertTrue(replaced_during_read)
        self.assertFalse((self.plugin_dir / "config.toml").exists())
        self.assertEqual((self.plugin_dir / result["backup"]).read_text(encoding="utf-8"), "value = 2\n")

    async def test_reset_and_toggle_plugin_config_preserve_structured_responses(self) -> None:
        self.write_config("[plugin]\nenabled = true\n")

        toggled = await plugin_routes.toggle_plugin("Author.Plugin", **self.auth_kwargs())
        self.assertEqual(toggled["enabled"], False)
        self.assertFalse(
            tomlkit.loads((self.plugin_dir / "config.toml").read_text(encoding="utf-8"))["plugin"]["enabled"]
        )

        reset = await plugin_routes.reset_plugin_config("Author.Plugin", **self.auth_kwargs())
        self.assertTrue(reset["success"])
        self.assertEqual(reset["backup"], Path(reset["backup"]).name)
        self.assertFalse((self.plugin_dir / "config.toml").exists())
        self.assertEqual(len(list(self.plugin_dir.glob("config.toml.reset.*"))), 1)

        second_reset = await plugin_routes.reset_plugin_config("Author.Plugin", **self.auth_kwargs())
        self.assertEqual(second_reset["message"], "配置文件不存在，无需重置")

        toggled_missing_config = await plugin_routes.toggle_plugin("Author.Plugin", **self.auth_kwargs())
        self.assertFalse(toggled_missing_config["enabled"])
        self.assertFalse(
            tomlkit.loads((self.plugin_dir / "config.toml").read_text(encoding="utf-8"))["plugin"]["enabled"]
        )

    async def test_config_routes_raise_404_for_missing_plugin(self) -> None:
        with self.assertRaises(HTTPException) as raw_error:
            await plugin_routes.get_plugin_config_raw("Missing.Plugin", **self.auth_kwargs())
        self.assertEqual(raw_error.exception.status_code, 404)

        with self.assertRaises(HTTPException) as update_error:
            await plugin_routes.update_plugin_config(
                "Missing.Plugin",
                plugin_routes.UpdatePluginConfigRequest(config={}),
                **self.auth_kwargs(),
            )
        self.assertEqual(update_error.exception.status_code, 404)
