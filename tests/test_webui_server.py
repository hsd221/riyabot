from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import FileResponse

from src.webui import webui_server


class WebUIServerStaticFilesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        project_root = Path(self.tmpdir.name)
        static_dir = project_root / "webui" / "dist"
        static_dir.mkdir(parents=True)
        self.index_path = static_dir / "index.html"
        self.index_path.write_text("<html>app</html>", encoding="utf-8")
        assets_dir = static_dir / "assets"
        assets_dir.mkdir()
        self.asset_path = assets_dir / "app.js"
        self.asset_path.write_text("console.log('app');", encoding="utf-8")
        self.secret_path = project_root / "secret.txt"
        self.secret_path.write_text("not public", encoding="utf-8")

        self.app = FastAPI()
        self.server = webui_server.WebUIServer.__new__(webui_server.WebUIServer)
        self.server.app = self.app
        fake_module_file = project_root / "src" / "webui" / "webui_server.py"
        with patch.object(webui_server, "__file__", str(fake_module_file)):
            self.server._setup_static_files()

        self.endpoint = next(
            route.endpoint for route in self.app.routes if getattr(route, "path", None) == "/{full_path:path}"
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    async def test_spa_fallback_returns_index_for_missing_route(self) -> None:
        response = await self.endpoint("dashboard/settings")

        self.assertIsInstance(response, FileResponse)
        self.assertEqual(Path(response.path).resolve(), self.index_path.resolve())

    async def test_static_file_inside_root_is_served_with_its_media_type(self) -> None:
        response = await self.endpoint("assets/app.js")

        self.assertIsInstance(response, FileResponse)
        self.assertEqual(Path(response.path).resolve(), self.asset_path.resolve())
        self.assertEqual(response.media_type, "application/javascript")

    async def test_spa_route_does_not_serve_files_outside_static_root(self) -> None:
        response = await self.endpoint("../../secret.txt")

        self.assertIsInstance(response, FileResponse)
        self.assertEqual(Path(response.path).resolve(), self.index_path.resolve())


if __name__ == "__main__":
    unittest.main()
