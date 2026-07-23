from __future__ import annotations

import ast
import inspect
import tempfile
import textwrap
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient

from src.webui import jargon_routes, plugin_routes
from src.webui.api import planner, replier


SENSITIVE_ROUTE_FILES = (
    "person_routes.py",
    "jargon_routes.py",
    "expression_routes.py",
    "behavior_routes.py",
    "emoji_routes.py",
    "annual_report_routes.py",
    "chat_history_import_routes.py",
    "api/planner.py",
    "api/replier.py",
)

PUBLIC_HTTP_ROUTES = frozenset(
    {
        ("GET", "/api/webui/health"),
        ("POST", "/api/webui/auth/setup"),
        ("POST", "/api/webui/auth/login"),
        ("POST", "/api/webui/auth/verify"),
        ("POST", "/api/webui/auth/logout"),
        ("GET", "/api/webui/auth/check"),
        ("GET", "/api/webui/plugins/version"),
    }
)

AUTH_CALL_NAMES = frozenset(
    {
        "_require_authenticated_session",
        "get_current_token",
        "get_token_from_cookie_or_header",
        "require_auth",
        "verify_auth_token",
        "verify_auth_token_from_cookie_or_header",
        "verify_token",
    }
)
WS_AUTH_CALL_NAMES = frozenset({"verify_token", "verify_ws_token"})
WS_ORIGIN_CALL_NAMES = frozenset({"is_websocket_origin_allowed"})


def _call_name(call: object) -> str:
    return getattr(call, "__name__", "")


def _dependency_call_names(dependant: object) -> set[str]:
    names: set[str] = set()
    pending = list(getattr(dependant, "dependencies", ()))
    while pending:
        dependency = pending.pop()
        name = _call_name(getattr(dependency, "call", None))
        if name:
            names.add(name)
        pending.extend(getattr(dependency, "dependencies", ()))
    return names


def _endpoint_call_names(endpoint: object) -> set[str]:
    source = textwrap.dedent(inspect.getsource(endpoint))
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def _iter_fastapi_routes(routes: list[object], prefix: str = "", inherited: frozenset[str] = frozenset()):
    """展开 FastAPI 的懒加载 include_router 路由。"""
    for route in routes:
        if isinstance(route, (APIRoute, APIWebSocketRoute)):
            dependencies = inherited | frozenset(_dependency_call_names(route.dependant))
            yield prefix + route.path, route, dependencies
            continue

        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        if original_router is None or include_context is None:
            continue

        context_dependencies = {
            _call_name(getattr(dependency, "dependency", None))
            for dependency in (getattr(include_context, "dependencies", ()) or ())
        }
        context_dependencies.discard("")
        yield from _iter_fastapi_routes(
            original_router.routes,
            prefix + include_context.prefix,
            inherited | frozenset(context_dependencies),
        )


def _contains_direct_exception_text(node: ast.AST, exception_name: str) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.FormattedValue) and isinstance(child.value, ast.Name):
            if child.value.id == exception_name:
                return True
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "str"
            and child.args
            and isinstance(child.args[0], ast.Name)
            and child.args[0].id == exception_name
        ):
            return True
    return False


class SensitiveWebUIRouteAuthTest(unittest.TestCase):
    def _assert_requires_auth(self, router, path: str) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(path)
        self.assertEqual(response.status_code, 401)

    def test_jargon_management_routes_require_authentication(self) -> None:
        self._assert_requires_auth(jargon_routes.router, "/jargon/list")

    def test_plugin_git_status_requires_authentication(self) -> None:
        self._assert_requires_auth(plugin_routes.router, "/plugins/git-status")

    def test_planner_log_routes_require_authentication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(planner, "PLAN_LOG_DIR", Path(tmp_dir)):
            self._assert_requires_auth(planner.router, "/api/planner/overview")

    def test_replier_log_routes_require_authentication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(replier, "REPLY_LOG_DIR", Path(tmp_dir)):
            self._assert_requires_auth(replier.router, "/api/replier/overview")


class WebUIRouteAuthenticationCoverageTest(unittest.TestCase):
    def test_all_non_public_http_routes_have_authentication(self) -> None:
        from src.webui.api import planner as planner_routes
        from src.webui.api import replier as replier_routes
        from src.webui.chat_routes import router as chat_router
        from src.webui.knowledge_routes import router as knowledge_router
        from src.webui.logs_ws import router as logs_router
        from src.webui.routes import router as webui_router

        app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        for router in (
            webui_router,
            logs_router,
            knowledge_router,
            chat_router,
            planner_routes.router,
            replier_routes.router,
        ):
            app.include_router(router)

        findings: list[str] = []
        for path, route, dependencies in _iter_fastapi_routes(app.routes):
            endpoint_calls = _endpoint_call_names(route.endpoint)
            if isinstance(route, APIWebSocketRoute):
                if not endpoint_calls.intersection(WS_ORIGIN_CALL_NAMES):
                    findings.append(f"WS {path}: 缺少 Origin 校验")
                if not endpoint_calls.intersection(WS_AUTH_CALL_NAMES):
                    findings.append(f"WS {path}: 缺少认证校验")
                continue

            for method in sorted(route.methods or ()):
                if (method, path) in PUBLIC_HTTP_ROUTES:
                    continue
                if not (endpoint_calls | dependencies).intersection(AUTH_CALL_NAMES):
                    findings.append(f"{method} {path}: 缺少认证校验")

        self.assertEqual(findings, [], "\n".join(findings))

    def test_production_server_does_not_expose_fastapi_documentation(self) -> None:
        from src.webui.webui_server import WebUIServer

        setup_methods = (
            "_setup_exception_handlers",
            "_setup_request_limits",
            "_setup_anti_crawler",
            "_setup_cors",
            "_setup_security_headers",
            "_show_auth_status",
            "_register_api_routes",
            "_setup_static_files",
            "_setup_robots_txt",
        )
        with ExitStack() as stack:
            for method_name in setup_methods:
                stack.enter_context(patch.object(WebUIServer, method_name))
            server = WebUIServer()

        self.assertIsNone(server.app.openapi_url)
        self.assertIsNone(server.app.docs_url)
        self.assertIsNone(server.app.redoc_url)

    def test_server_rejects_cross_site_state_changes_globally(self) -> None:
        from src.webui.webui_server import WebUIServer

        setup_methods = (
            "_setup_exception_handlers",
            "_setup_request_limits",
            "_setup_anti_crawler",
            "_setup_cors",
            "_setup_security_headers",
            "_show_auth_status",
            "_register_api_routes",
            "_setup_static_files",
            "_setup_robots_txt",
        )
        with ExitStack() as stack:
            for method_name in setup_methods:
                stack.enter_context(patch.object(WebUIServer, method_name))
            server = WebUIServer()

        @server.app.post("/state-change")
        async def state_change():
            return {"success": True}

        with TestClient(server.app, base_url="http://testserver") as client:
            cross_site = client.post(
                "/state-change",
                headers={"Origin": "https://attacker.example", "Sec-Fetch-Site": "cross-site"},
            )
            same_origin = client.post(
                "/state-change",
                headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
            )
            non_browser = client.post("/state-change")

        self.assertEqual(cross_site.status_code, 403)
        self.assertEqual(same_origin.status_code, 200)
        self.assertEqual(non_browser.status_code, 200)


class InternalErrorDisclosureTest(unittest.TestCase):
    def test_sensitive_routes_do_not_expose_or_log_exception_text(self) -> None:
        webui_root = Path(__file__).resolve().parents[1] / "src" / "webui"
        findings: list[str] = []

        for relative_path in SENSITIVE_ROUTE_FILES:
            path = webui_root / relative_path
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

            for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler) and node.name):
                exception_name = handler.name
                for node in ast.walk(handler):
                    if not isinstance(node, ast.Call):
                        continue

                    if isinstance(node.func, ast.Name) and node.func.id == "HTTPException":
                        status_code = next(
                            (
                                keyword.value.value
                                for keyword in node.keywords
                                if keyword.arg == "status_code" and isinstance(keyword.value, ast.Constant)
                            ),
                            None,
                        )
                        detail = next((keyword.value for keyword in node.keywords if keyword.arg == "detail"), None)
                        if (
                            isinstance(status_code, int)
                            and status_code >= 500
                            and detail is not None
                            and _contains_direct_exception_text(detail, exception_name)
                        ):
                            findings.append(f"{relative_path}:{node.lineno}: 5xx 响应包含异常文本")

                    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                        if node.func.value.id != "logger":
                            continue
                        if node.func.attr == "exception":
                            findings.append(f"{relative_path}:{node.lineno}: logger.exception 会记录 traceback")
                            continue
                        for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
                            if _contains_direct_exception_text(argument, exception_name):
                                findings.append(f"{relative_path}:{node.lineno}: 日志包含异常文本")
                                break
                        if any(
                            keyword.arg == "exc_info"
                            and isinstance(keyword.value, ast.Constant)
                            and keyword.value.value is True
                            for keyword in node.keywords
                        ):
                            findings.append(f"{relative_path}:{node.lineno}: 日志包含 traceback")

        self.assertEqual(findings, [], "\n".join(findings))


class WebUILogTracebackDisclosureTest(unittest.TestCase):
    def test_webui_logs_do_not_capture_exception_tracebacks(self) -> None:
        webui_root = Path(__file__).resolve().parents[1] / "src" / "webui"
        findings: list[str] = []

        for path in sorted(webui_root.rglob("*.py")):
            relative_path = path.relative_to(webui_root)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

            for node in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
                if not (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "logger"
                ):
                    continue
                if node.func.attr == "exception":
                    findings.append(f"{relative_path}:{node.lineno}: logger.exception 会记录 traceback")
                if any(
                    keyword.arg == "exc_info"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in node.keywords
                ):
                    findings.append(f"{relative_path}:{node.lineno}: 日志启用了 exc_info traceback")

        self.assertEqual(findings, [], "\n".join(findings))


class WebUILogExceptionTextDisclosureTest(unittest.TestCase):
    def test_webui_logs_do_not_include_exception_text(self) -> None:
        webui_root = Path(__file__).resolve().parents[1] / "src" / "webui"
        findings: list[str] = []

        for path in sorted(webui_root.rglob("*.py")):
            relative_path = path.relative_to(webui_root)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

            for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler) and node.name):
                for node in ast.walk(handler):
                    if not (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "logger"
                    ):
                        continue
                    arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
                    if any(_contains_direct_exception_text(argument, handler.name) for argument in arguments):
                        findings.append(f"{relative_path}:{node.lineno}: 日志包含异常文本")

        self.assertEqual(findings, [], "\n".join(findings))


class WebUILogMessageInjectionTest(unittest.TestCase):
    def test_webui_log_messages_are_static_strings(self) -> None:
        webui_root = Path(__file__).resolve().parents[1] / "src" / "webui"
        findings: list[str] = []

        for path in sorted(webui_root.rglob("*.py")):
            relative_path = path.relative_to(webui_root)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

            for node in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
                if not (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "logger"
                    and node.args
                ):
                    continue
                if isinstance(node.args[0], ast.JoinedStr):
                    findings.append(f"{relative_path}:{node.lineno}: 日志事件名包含动态文本")

        self.assertEqual(findings, [], "\n".join(findings))


class WebUIResponseExceptionTextDisclosureTest(unittest.TestCase):
    def test_webui_responses_do_not_include_exception_text(self) -> None:
        webui_root = Path(__file__).resolve().parents[1] / "src" / "webui"
        findings: list[str] = []

        for path in sorted(webui_root.rglob("*.py")):
            relative_path = path.relative_to(webui_root)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

            for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler) and node.name):
                for node in ast.walk(handler):
                    if isinstance(node, ast.Raise) and node.exc is not None:
                        if _contains_direct_exception_text(node.exc, handler.name):
                            findings.append(f"{relative_path}:{node.lineno}: 异常响应包含异常文本")
                    elif isinstance(node, ast.Return) and node.value is not None:
                        if _contains_direct_exception_text(node.value, handler.name):
                            findings.append(f"{relative_path}:{node.lineno}: 返回响应包含异常文本")

        self.assertEqual(findings, [], "\n".join(findings))


if __name__ == "__main__":
    unittest.main()
