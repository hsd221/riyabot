import asyncio
import json
import os
import socket
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock, Mock, patch

import httpx
import tomlkit
from fastapi import HTTPException, Response
from starlette.responses import PlainTextResponse

from src.config.config_base import ConfigBase
from src.webui import (
    anti_crawler,
    auth,
    git_mirror_service,
    knowledge_routes,
    logs_ws,
    model_routes,
    plugin_progress_ws,
    token_manager,
    routes as webui_routes,
    webui_server,
    ws_auth,
)
from src.webui.config_schema import ConfigSchemaGenerator, FieldSchema, FieldType
from src.webui.rate_limiter import RateLimiter, check_api_rate_limit, check_auth_rate_limit


@dataclass
class NestedWebConfig(ConfigBase):
    enabled: bool = True
    """是否启用"""


@dataclass
class WebSchemaSampleConfig(ConfigBase):
    required_name: str
    """必填名称"""

    mode: Literal["basic", "advanced"] = "basic"
    """模式"""

    personality: str = ""
    """长文本人格"""

    retry_count: int = 2
    """重试次数"""

    ratio: float = 0.5
    """比例"""

    flags: set[str] = field(default_factory=set)
    """标记集合"""

    names: list[str] = field(default_factory=list)
    """名称列表"""

    metadata: dict = field(default_factory=dict)
    """元数据"""

    nested: NestedWebConfig = field(default_factory=NestedWebConfig)
    """嵌套配置"""

    MMC_VERSION: str = "0.0.0"
    _private: str = "hidden"


def fake_request(headers: dict[str, str] | None = None, host: str = "127.0.0.1"):
    return SimpleNamespace(headers=headers or {}, client=SimpleNamespace(host=host))


def fake_web_request(
    headers: dict[str, str] | None = None,
    host: str = "127.0.0.1",
    path: str = "/api/status",
    scheme: str = "http",
):
    return SimpleNamespace(
        headers=headers or {},
        client=SimpleNamespace(host=host),
        url=SimpleNamespace(path=path, scheme=scheme),
    )


class ConfigSchemaGeneratorTest(unittest.TestCase):
    def test_field_schema_to_dict_omits_none_values_and_serializes_constraints(self) -> None:
        field_schema = FieldSchema(
            name="count",
            type=FieldType.INTEGER,
            label="Count",
            description="Total count",
            default=2,
            required=False,
            options=["1", "2"],
            min_value=1,
            max_value=5,
            items={"type": "integer"},
            properties={"nested": []},
        )

        self.assertEqual(
            field_schema.to_dict(),
            {
                "name": "count",
                "type": "integer",
                "label": "Count",
                "description": "Total count",
                "required": False,
                "default": 2,
                "options": ["1", "2"],
                "minValue": 1,
                "maxValue": 5,
                "items": {"type": "integer"},
                "properties": {"nested": []},
            },
        )

    def test_generate_schema_maps_field_types_defaults_descriptions_and_nested_schema(self) -> None:
        schema = ConfigSchemaGenerator.generate_schema(WebSchemaSampleConfig)
        fields_by_name = {item["name"]: item for item in schema["fields"]}

        self.assertEqual(schema["className"], "WebSchemaSampleConfig")
        self.assertEqual(fields_by_name["required_name"]["type"], "string")
        self.assertTrue(fields_by_name["required_name"]["required"])
        self.assertEqual(fields_by_name["required_name"]["description"], "必填名称")
        self.assertEqual(fields_by_name["mode"]["type"], "select")
        self.assertEqual(fields_by_name["mode"]["options"], ["basic", "advanced"])
        self.assertEqual(fields_by_name["personality"]["type"], "textarea")
        self.assertEqual(fields_by_name["retry_count"]["type"], "integer")
        self.assertEqual(fields_by_name["ratio"]["type"], "number")
        self.assertEqual(fields_by_name["flags"]["type"], "array")
        self.assertEqual(fields_by_name["flags"]["items"], {"type": "string"})
        self.assertEqual(fields_by_name["names"]["items"], {"type": "string"})
        self.assertEqual(fields_by_name["metadata"]["type"], "object")
        self.assertEqual(fields_by_name["nested"]["type"], "object")
        self.assertIn("nested", schema["nested"])
        self.assertNotIn("MMC_VERSION", fields_by_name)
        self.assertNotIn("_private", fields_by_name)

    def test_generate_schema_can_omit_nested_config_fields_and_rejects_non_configbase(self) -> None:
        schema = ConfigSchemaGenerator.generate_schema(WebSchemaSampleConfig, include_nested=False)
        fields_by_name = {item["name"]: item for item in schema["fields"]}

        self.assertNotIn("nested", fields_by_name)
        self.assertIsNone(schema["nested"])
        with self.assertRaisesRegex(ValueError, "必须继承自 ConfigBase"):
            ConfigSchemaGenerator.generate_schema(str)


class RateLimiterTest(unittest.TestCase):
    def test_client_ip_prefers_forwarded_for_then_real_ip_then_client_host(self) -> None:
        limiter = RateLimiter()

        with patch(
            "src.webui.rate_limiter.global_config",
            SimpleNamespace(webui=SimpleNamespace(trust_xff=True, trusted_proxies="127.0.0.1")),
        ):
            self.assertEqual(limiter._get_client_ip(fake_request({"X-Forwarded-For": "1.1.1.1, 2.2.2.2"})), "1.1.1.1")
            self.assertEqual(limiter._get_client_ip(fake_request({"X-Real-IP": "3.3.3.3"})), "3.3.3.3")
        self.assertEqual(limiter._get_client_ip(fake_request(host="4.4.4.4")), "4.4.4.4")
        self.assertEqual(limiter._get_client_ip(SimpleNamespace(headers={}, client=None)), "unknown")

    def test_check_rate_limit_counts_requests_within_sliding_window(self) -> None:
        limiter = RateLimiter()
        request = fake_request(host="10.0.0.1")

        with patch("src.webui.rate_limiter.time.time", side_effect=[100.0, 100.0, 101.0, 101.0, 102.0, 200.0, 200.0]):
            self.assertEqual(limiter.check_rate_limit(request, max_requests=2, window_seconds=60), (True, 1))
            self.assertEqual(limiter.check_rate_limit(request, max_requests=2, window_seconds=60), (True, 0))
            self.assertEqual(limiter.check_rate_limit(request, max_requests=2, window_seconds=60), (False, 0))
            self.assertEqual(limiter.check_rate_limit(request, max_requests=2, window_seconds=60), (True, 1))

    def test_blocking_failure_recording_and_reset_use_same_client_key(self) -> None:
        limiter = RateLimiter()
        request = fake_request(host="10.0.0.2")

        with patch("src.webui.rate_limiter.time.time", return_value=100.0):
            self.assertEqual(
                limiter.record_failed_attempt(request, max_failures=2, window_seconds=60, block_duration=30), (False, 1)
            )
            self.assertEqual(
                limiter.record_failed_attempt(request, max_failures=2, window_seconds=60, block_duration=30), (True, 0)
            )
            self.assertEqual(limiter.is_blocked(request), (True, 30))

        limiter.reset_failures(request)
        self.assertNotIn("10.0.0.2:auth_failures", limiter._requests)

    def test_expired_blocks_are_cleaned_before_block_check(self) -> None:
        limiter = RateLimiter()
        request = fake_request(host="10.0.0.3")
        limiter._blocked["10.0.0.3"] = 99.0

        with patch("src.webui.rate_limiter.time.time", return_value=100.0):
            self.assertEqual(limiter.is_blocked(request), (False, None))
        self.assertEqual(limiter._blocked, {})

    def test_auth_and_api_dependencies_raise_http_429_when_limits_are_exceeded(self) -> None:
        request = fake_request(host="10.0.0.4")
        limiter = RateLimiter()

        with patch("src.webui.rate_limiter.get_rate_limiter", return_value=limiter):
            with patch.object(limiter, "is_blocked", return_value=(True, 12)):
                with self.assertRaises(HTTPException) as blocked:
                    asyncio.run(check_auth_rate_limit(request))
                self.assertEqual(blocked.exception.status_code, 429)
                self.assertEqual(blocked.exception.headers["Retry-After"], "12")

            with patch.object(limiter, "is_blocked", return_value=(False, None)):
                with patch.object(limiter, "check_rate_limit", return_value=(False, 0)):
                    with self.assertRaises(HTTPException) as auth_limited:
                        asyncio.run(check_auth_rate_limit(request))
                    self.assertEqual(auth_limited.exception.status_code, 429)
                    self.assertEqual(auth_limited.exception.headers["Retry-After"], "60")

                    with self.assertRaises(HTTPException) as api_limited:
                        asyncio.run(check_api_rate_limit(request))
                    self.assertEqual(api_limited.exception.status_code, 429)
                    self.assertEqual(api_limited.exception.headers["Retry-After"], "60")


class TokenManagerTest(unittest.TestCase):
    def test_token_manager_creates_verifies_updates_and_tracks_setup_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "webui.json"
            manager = token_manager.TokenManager(config_path)
            self.assertEqual(manager.get_token(), "")
            self.assertFalse(manager.is_password_configured())
            self.assertTrue(manager.is_first_setup())
            self.assertTrue(manager.set_initial_password("abc12345")[0])
            self.assertTrue(manager.verify_token(manager.create_session()))
            self.assertFalse(manager.verify_password("wrong123"))
            self.assertEqual(manager.update_password("abc12345", "def45678"), (True, "密码更新成功"))
            self.assertTrue(manager.verify_password("def45678"))
            self.assertFalse(manager.verify_password("abc12345"))
            self.assertTrue(manager.is_first_setup())
            self.assertTrue(manager.mark_setup_completed())
            self.assertFalse(manager.is_first_setup())
            self.assertTrue(manager.reset_setup_status())
            self.assertTrue(manager.is_first_setup())

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("password_hash", saved)
            self.assertNotIn("access_token", saved)
            self.assertFalse(saved["first_setup_completed"])
            self.assertNotIn("setup_completed_at", saved)

    def test_token_manager_keeps_empty_config_unconfigured_and_fails_closed_on_invalid_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            empty_path = Path(tmp_dir) / "empty.json"
            empty_path.write_text("{}", encoding="utf-8")
            invalid_path = Path(tmp_dir) / "invalid.json"
            invalid_path.write_text("{not json", encoding="utf-8")

            manager = token_manager.TokenManager(empty_path)
            self.assertEqual(manager.get_token(), "")
            self.assertFalse(manager.is_password_configured())
            with self.assertRaises(RuntimeError):
                token_manager.TokenManager(invalid_path)
            self.assertEqual(invalid_path.read_text(encoding="utf-8"), "{not json")

        original_instance = token_manager._token_manager_instance
        try:
            sentinel = object()
            token_manager._token_manager_instance = sentinel  # type: ignore[assignment]
            self.assertIs(token_manager.get_token_manager(), sentinel)
        finally:
            token_manager._token_manager_instance = original_instance


class AuthAndWsAuthTest(unittest.IsolatedAsyncioTestCase):
    def test_auth_reads_cookie_before_header_and_rejects_missing_or_invalid_tokens(self) -> None:
        manager = SimpleNamespace(verify_token=Mock(side_effect=lambda token: token == "valid"))
        request = fake_web_request()

        with patch.object(auth, "get_token_manager", return_value=manager):
            self.assertEqual(auth.get_current_token(request, maibot_session="valid"), "valid")
            self.assertEqual(
                auth.get_current_token(request, maibot_session=None, authorization="Bearer valid"), "valid"
            )
            self.assertTrue(auth.verify_auth_token_from_cookie_or_header(authorization="Bearer valid"))

            with self.assertRaises(HTTPException) as missing:
                auth.get_current_token(request, maibot_session=None, authorization=None)
            self.assertEqual(missing.exception.status_code, 401)

            with self.assertRaises(HTTPException) as invalid:
                auth.verify_auth_token_from_cookie_or_header(maibot_session="bad")
            self.assertEqual(invalid.exception.detail, "Token 无效或已过期")

        self.assertEqual(manager.verify_token.call_args_list[0].args[0], "valid")

    def test_auth_cookie_security_uses_environment_and_request_scheme(self) -> None:
        fake_config = SimpleNamespace(webui=SimpleNamespace(secure_cookie=False, mode="development"))
        with patch.object(auth, "global_config", fake_config):
            self.assertFalse(auth._is_secure_environment())
            fake_config.webui.mode = "production"
            self.assertTrue(auth._is_secure_environment())
            fake_config.webui.mode = "development"
            fake_config.webui.secure_cookie = True
            self.assertTrue(auth._is_secure_environment())

        response = Response()
        with patch.object(auth, "_is_secure_environment", return_value=True):
            auth.set_auth_cookie(response, "token-value", fake_web_request(scheme="http"))
        cookie_header = response.headers["set-cookie"]
        self.assertIn("maibot_session=token-value", cookie_header)
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("SameSite=strict", cookie_header)
        self.assertNotIn("Secure", cookie_header)

        clear_response = Response()
        with patch.object(auth, "_is_secure_environment", return_value=True):
            auth.clear_auth_cookie(clear_response)
        self.assertIn('maibot_session=""', clear_response.headers["set-cookie"])
        self.assertIn("Secure", clear_response.headers["set-cookie"])

    async def test_ws_tokens_are_one_time_expiring_and_session_bound(self) -> None:
        ws_auth._ws_temp_tokens.clear()
        manager = SimpleNamespace(verify_token=Mock(return_value=True))
        with (
            patch.object(ws_auth.secrets, "token_urlsafe", return_value="temporary-token"),
            patch.object(ws_auth.time, "time", return_value=100.0),
        ):
            temp = ws_auth.generate_ws_token("session-token")
        self.assertEqual(temp, "temporary-token")
        self.assertEqual(ws_auth._ws_temp_tokens[temp], (160.0, "session-token"))

        with (
            patch.object(ws_auth, "get_token_manager", return_value=manager),
            patch.object(ws_auth.time, "time", return_value=120.0),
        ):
            self.assertTrue(ws_auth.verify_ws_token(temp))
            self.assertFalse(ws_auth.verify_ws_token(temp))
        manager.verify_token.assert_called_once_with("session-token")

        ws_auth._ws_temp_tokens["expired"] = (90.0, "session-token")
        with patch.object(ws_auth.time, "time", return_value=100.0):
            self.assertFalse(ws_auth.verify_ws_token("expired"))
        self.assertNotIn("expired", ws_auth._ws_temp_tokens)

        with patch.object(
            ws_auth, "get_token_manager", return_value=SimpleNamespace(verify_token=Mock(return_value=False))
        ):
            with patch.object(ws_auth.time, "time", return_value=100.0):
                ws_auth._ws_temp_tokens["revoked"] = (160.0, "session-token")
                self.assertFalse(ws_auth.verify_ws_token("revoked"))
        self.assertNotIn("revoked", ws_auth._ws_temp_tokens)

    async def test_ws_token_endpoint_accepts_cookie_or_bearer_and_returns_soft_failures(self) -> None:
        manager = SimpleNamespace(verify_token=Mock(side_effect=lambda token: token == "valid"))

        with patch.object(ws_auth, "get_token_manager", return_value=manager):
            self.assertEqual(
                await ws_auth.get_ws_token(maibot_session=None, authorization=None),
                {"success": False, "message": "未提供认证信息，请先登录", "token": None, "expires_in": 0},
            )
            self.assertEqual(
                await ws_auth.get_ws_token(maibot_session="bad"),
                {"success": False, "message": "认证已过期，请重新登录", "token": None, "expires_in": 0},
            )

        with (
            patch.object(ws_auth, "get_token_manager", return_value=manager),
            patch.object(ws_auth, "generate_ws_token", return_value="ws-token") as generate,
        ):
            self.assertEqual(
                await ws_auth.get_ws_token(maibot_session=None, authorization="Bearer valid"),
                {"success": True, "token": "ws-token", "expires_in": 60},
            )
        generate.assert_called_once_with("valid")


class AntiCrawlerTest(unittest.IsolatedAsyncioTestCase):
    def test_ip_whitelist_parsing_wildcards_and_mode_config_are_stable(self) -> None:
        parsed = anti_crawler._parse_allowed_ips("127.0.0.1, 192.168.1.0/24, 10.0.*, # comment, bad.ip")

        self.assertEqual(str(parsed[0]), "127.0.0.1")
        self.assertEqual(str(parsed[1]), "192.168.1.0/24")
        self.assertRegex("10.0.5.9", parsed[2])
        self.assertEqual(anti_crawler._convert_wildcard_to_regex("*"), r".*")
        self.assertIsNone(anti_crawler._convert_wildcard_to_regex("300.*"))

        self.assertFalse(anti_crawler._get_mode_config("false")["enabled"])
        self.assertTrue(anti_crawler._get_mode_config("strict")["block_on_detect"])
        self.assertEqual(anti_crawler._get_mode_config("loose")["rate_limit_max_requests"], 60)
        self.assertFalse(anti_crawler._get_mode_config("basic")["block_on_detect"])
        self.assertFalse(anti_crawler._get_mode_config("unknown")["block_on_detect"])

    def test_detection_helpers_cover_user_agent_headers_ip_trust_and_allowlist(self) -> None:
        middleware = anti_crawler.AntiCrawlerMiddleware(lambda scope, receive, send: None, mode="strict")

        self.assertTrue(middleware._is_crawler_user_agent("Mozilla Googlebot/2.1"))
        self.assertFalse(middleware._is_crawler_user_agent("Mozilla/5.0"))
        self.assertFalse(middleware._is_crawler_user_agent(None))
        self.assertTrue(middleware._is_asset_scanner_header(fake_web_request({"X-Scan": "Shodan"})))
        self.assertTrue(middleware._detect_asset_scanner(fake_web_request({"User-Agent": "CensysInspect"}))[0])
        self.assertEqual(
            middleware._detect_asset_scanner(fake_web_request({"X-Originating-IP": "203.0.113.1"})),
            (True, "unknown_scanner"),
        )

        allowed = anti_crawler._parse_allowed_ips("127.0.0.1, 192.168.1.0/24, 10.0.*")
        trusted = anti_crawler._parse_allowed_ips("172.16.0.0/16")
        with (
            patch.object(anti_crawler, "ALLOWED_IPS", allowed),
            patch.object(anti_crawler, "TRUSTED_PROXIES", trusted),
            patch.object(anti_crawler, "TRUST_XFF", True),
        ):
            self.assertTrue(middleware._is_ip_allowed("127.0.0.1"))
            self.assertTrue(middleware._is_ip_allowed("192.168.1.42"))
            self.assertTrue(middleware._is_ip_allowed("10.0.3.4"))
            self.assertFalse(middleware._is_ip_allowed("8.8.8.8"))
            self.assertTrue(middleware._is_trusted_proxy("172.16.0.8"))
            self.assertEqual(
                middleware._get_client_ip(
                    fake_web_request(
                        {"X-Forwarded-For": "8.8.8.8, 1.1.1.1", "X-Real-IP": "9.9.9.9"},
                        host="172.16.0.8",
                    )
                ),
                "8.8.8.8",
            )
            self.assertEqual(
                middleware._get_client_ip(
                    fake_web_request({"X-Forwarded-For": "bad", "X-Real-IP": "9.9.9.9"}, host="172.16.0.8")
                ),
                "9.9.9.9",
            )
            self.assertEqual(
                middleware._get_client_ip(fake_web_request({"X-Forwarded-For": "8.8.8.8"}, host="203.0.113.2")),
                "203.0.113.2",
            )

    def test_rate_limit_sliding_window_allowlist_and_oldest_cleanup(self) -> None:
        middleware = anti_crawler.AntiCrawlerMiddleware(lambda scope, receive, send: None, mode="strict")
        middleware.rate_limit_max_requests = 2
        middleware.rate_limit_window = 10
        middleware.max_tracked_ips = 2

        with patch.object(anti_crawler, "ALLOWED_IPS", anti_crawler._parse_allowed_ips("127.0.0.1")):
            self.assertFalse(middleware._check_rate_limit("127.0.0.1"))

        with (
            patch.object(anti_crawler, "ALLOWED_IPS", []),
            patch.object(anti_crawler.time, "time", side_effect=[100, 101, 102, 111]),
        ):
            self.assertFalse(middleware._check_rate_limit("10.0.0.1"))
            self.assertFalse(middleware._check_rate_limit("10.0.0.1"))
            self.assertTrue(middleware._check_rate_limit("10.0.0.1"))
            self.assertFalse(middleware._check_rate_limit("10.0.0.1"))

        middleware.request_times = {
            "empty": anti_crawler.deque(),
            "old": anti_crawler.deque([1.0]),
            "new": anti_crawler.deque([2.0]),
        }
        middleware._cleanup_oldest_ips()
        self.assertNotIn("empty", middleware.request_times)
        self.assertIn("old", middleware.request_times)

        middleware.request_times = {"old": anti_crawler.deque([1.0]), "new": anti_crawler.deque([2.0])}
        middleware._cleanup_oldest_ips()
        self.assertNotIn("old", middleware.request_times)

    async def test_dispatch_allows_static_and_blocks_scanners_crawlers_or_rate_limit(self) -> None:
        middleware = anti_crawler.AntiCrawlerMiddleware(lambda scope, receive, send: None, mode="strict")

        async def call_next(request):
            return PlainTextResponse("ok")

        static_response = await middleware.dispatch(fake_web_request(path="/assets/app.js"), call_next)
        with patch.object(anti_crawler, "ALLOWED_IPS", []):
            scanner_response = await middleware.dispatch(
                fake_web_request({"User-Agent": "Shodan"}, host="203.0.113.10", path="/api"), call_next
            )
            crawler_response = await middleware.dispatch(
                fake_web_request({"User-Agent": "Googlebot"}, host="203.0.113.10", path="/api"), call_next
            )

        self.assertEqual(static_response.status_code, 200)
        self.assertEqual(scanner_response.status_code, 403)
        self.assertIn("Asset scanning", scanner_response.body.decode())
        self.assertEqual(crawler_response.status_code, 403)
        self.assertIn("Crawlers", crawler_response.body.decode())

        with (
            patch.object(anti_crawler, "ALLOWED_IPS", []),
            patch.object(middleware, "_check_rate_limit", return_value=True),
        ):
            limited = await middleware.dispatch(fake_web_request({"User-Agent": "Mozilla"}, path="/api"), call_next)
        self.assertEqual(limited.status_code, 429)

        disabled = anti_crawler.AntiCrawlerMiddleware(lambda scope, receive, send: None, mode="false")
        self.assertEqual((await disabled.dispatch(fake_web_request(path="/api"), call_next)).status_code, 200)


class GitMirrorServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_git_mirror_config_loads_defaults_preserves_existing_file_and_manages_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "webui.json"
            with patch.object(git_mirror_service.GitMirrorConfig, "CONFIG_FILE", config_path):
                config = git_mirror_service.GitMirrorConfig()

                self.assertTrue(config_path.exists())
                self.assertGreaterEqual(len(config.get_all_mirrors()), 1)
                self.assertEqual(config.get_enabled_mirrors()[0]["priority"], 1)
                self.assertIn("github", config.get_default_priority_list())

                added = config.add_mirror(
                    "custom",
                    "Custom Mirror",
                    "https://raw.example.test",
                    "https://clone.example.test",
                    priority=10,
                )
                self.assertEqual(added["id"], "custom")
                with self.assertRaisesRegex(ValueError, "已存在"):
                    config.add_mirror("custom", "Duplicate", "raw", "clone")

                updated = config.update_mirror("custom", enabled=False, priority=2)
                self.assertFalse(updated["enabled"])
                self.assertEqual(updated["priority"], 2)
                self.assertIsNone(config.update_mirror("missing", enabled=True))
                self.assertTrue(config.delete_mirror("custom"))
                self.assertFalse(config.delete_mirror("custom"))

                saved = json.loads(config_path.read_text(encoding="utf-8"))
                saved["other_setting"] = "kept"
                saved["git_mirrors"] = [
                    {
                        "id": "m2",
                        "name": "Mirror 2",
                        "raw_prefix": "https://raw2",
                        "clone_prefix": "https://clone2",
                        "enabled": True,
                        "priority": 1,
                    },
                    {
                        "id": "m1",
                        "name": "Mirror 1",
                        "raw_prefix": "https://raw1",
                        "clone_prefix": "https://clone1",
                        "enabled": True,
                        "priority": 0,
                    },
                ]
                config_path.write_text(json.dumps(saved), encoding="utf-8")

                loaded = git_mirror_service.GitMirrorConfig()
                self.assertEqual([m["id"] for m in loaded.get_enabled_mirrors()], ["m1", "m2"])
                loaded.add_mirror("m3", "Mirror 3", "https://raw3", "https://clone3")
                self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["other_setting"], "kept")

    def test_git_installed_check_and_service_singleton_are_mockable(self) -> None:
        with (
            patch.object(git_mirror_service.shutil, "which", return_value="/usr/bin/git"),
            patch.object(
                git_mirror_service.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout="git version 2.45.0\n", stderr=""),
            ),
        ):
            self.assertEqual(
                git_mirror_service.GitMirrorService.check_git_installed(),
                {"installed": True, "version": "git version 2.45.0", "path": "/usr/bin/git"},
            )

        with patch.object(git_mirror_service.shutil, "which", return_value=None):
            missing = git_mirror_service.GitMirrorService.check_git_installed()
        self.assertFalse(missing["installed"])
        self.assertIn("未找到 Git", missing["error"])

        original = git_mirror_service._git_mirror_service
        try:
            sentinel = object()
            git_mirror_service._git_mirror_service = sentinel  # type: ignore[assignment]
            self.assertIs(git_mirror_service.get_git_mirror_service(), sentinel)
        finally:
            git_mirror_service._git_mirror_service = original

    async def test_git_mirror_service_fetch_and_clone_selection_delegate_without_network_or_git(self) -> None:
        mirrors = [
            {
                "id": "first",
                "name": "First",
                "raw_prefix": "https://raw.first",
                "clone_prefix": "https://clone.first",
                "enabled": True,
                "priority": 1,
            },
            {
                "id": "second",
                "name": "Second",
                "raw_prefix": "https://raw.second",
                "clone_prefix": "https://clone.second",
                "enabled": True,
                "priority": 2,
            },
        ]
        config = SimpleNamespace(
            get_enabled_mirrors=Mock(return_value=mirrors),
            get_mirror_by_id=Mock(side_effect=lambda mirror_id: mirrors[1] if mirror_id == "second" else None),
        )
        service = git_mirror_service.GitMirrorService(max_retries=2, config=config)

        with patch.object(
            service,
            "_fetch_raw_from_mirror",
            side_effect=[
                {"success": False, "error": "bad", "attempts": 1},
                {"success": True, "data": "ok", "mirror_used": "second", "attempts": 1},
            ],
        ) as fetch_from_mirror:
            result = await service.fetch_raw_file("owner", "repo", "main", "file.txt")

        self.assertTrue(result["success"])
        self.assertEqual(fetch_from_mirror.await_count, 2)

        missing = await service.fetch_raw_file("owner", "repo", "main", "file.txt", mirror_id="missing")
        self.assertFalse(missing["success"])
        self.assertEqual(missing["attempts"], 0)

        with patch.object(
            service, "_fetch_with_url", return_value={"success": True, "mirror_used": "custom"}
        ) as fetch_url:
            self.assertTrue((await service.fetch_raw_file("", "", "", "", custom_url="https://raw.custom"))["success"])
        fetch_url.assert_awaited_once_with("https://raw.custom", "custom")

        with patch.object(service, "_clone_from_mirror", return_value={"success": True, "path": "/tmp/repo"}) as clone:
            clone_result = await service.clone_repository("owner", "repo", Path("/tmp/repo"), mirror_id="second")
        self.assertTrue(clone_result["success"])
        clone.assert_awaited_once()


class ModelRoutesTest(unittest.IsolatedAsyncioTestCase):
    def test_model_response_parsers_normalize_openai_gemini_and_urls(self) -> None:
        self.assertEqual(model_routes._normalize_url("https://api.example.test///"), "https://api.example.test")
        self.assertEqual(model_routes._normalize_url(""), "")
        self.assertEqual(
            model_routes._parse_openai_response(
                {"data": [{"id": "gpt-test", "name": "GPT Test", "owned_by": "openai"}, {"object": "ignored"}]}
            ),
            [{"id": "gpt-test", "name": "GPT Test", "owned_by": "openai"}],
        )
        self.assertEqual(
            model_routes._parse_gemini_response(
                {"models": [{"name": "models/gemini-pro", "displayName": "Gemini Pro"}, {"bad": "ignored"}]}
            ),
            [{"id": "gemini-pro", "name": "Gemini Pro", "owned_by": "google"}],
        )
        self.assertEqual(model_routes._parse_openai_response({"data": "bad"}), [])
        self.assertEqual(model_routes._parse_gemini_response({"models": "bad"}), [])

    def test_provider_config_reads_named_provider_and_handles_missing_or_invalid_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir)
            doc = tomlkit.document()
            doc["api_providers"] = [
                {"name": "openai", "base_url": "https://api.openai.test", "api_key": "secret"},
                {"name": "gemini", "base_url": "https://gemini.test", "api_key": "gemini-secret"},
            ]
            (config_dir / "model_config.toml").write_text(tomlkit.dumps(doc), encoding="utf-8")

            with patch.object(model_routes, "CONFIG_DIR", str(config_dir)):
                self.assertEqual(
                    model_routes._get_provider_config("openai"),
                    {"name": "openai", "base_url": "https://api.openai.test", "api_key": "secret"},
                )
                self.assertIsNone(model_routes._get_provider_config("missing"))

            (config_dir / "model_config.toml").write_text("{bad toml", encoding="utf-8")
            with patch.object(model_routes, "CONFIG_DIR", str(config_dir)):
                self.assertIsNone(model_routes._get_provider_config("openai"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(model_routes, "CONFIG_DIR", tmp_dir):
                self.assertIsNone(model_routes._get_provider_config("openai"))

    async def test_fetch_models_from_provider_sets_auth_style_and_translates_upstream_errors(self) -> None:
        calls = []

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None, params=None):
                calls.append({"url": url, "headers": headers or {}, "params": params or {}})
                return httpx.Response(
                    200,
                    json={"data": [{"id": "gpt-test"}]},
                    request=httpx.Request("GET", url),
                )

        with patch.object(model_routes.httpx, "AsyncClient", FakeAsyncClient):
            models = await model_routes._fetch_models_from_provider(
                "https://api.example.test/",
                "secret",
                "/models",
                "openai",
                client_type="openai",
            )
            gemini_models = await model_routes._fetch_models_from_provider(
                "https://gemini.example.test",
                "gemini-secret",
                "/models",
                "openai",
                client_type="gemini",
            )

        self.assertEqual(models, [{"id": "gpt-test", "name": "gpt-test", "owned_by": ""}])
        self.assertEqual(gemini_models[0]["id"], "gpt-test")
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(calls[0]["params"], {})
        self.assertEqual(calls[1]["headers"], {})
        self.assertEqual(calls[1]["params"], {"key": "gemini-secret"})

        class UnauthorizedClient(FakeAsyncClient):
            async def get(self, url, headers=None, params=None):
                return httpx.Response(401, text="unauthorized", request=httpx.Request("GET", url))

        with patch.object(model_routes.httpx, "AsyncClient", UnauthorizedClient):
            with self.assertRaises(HTTPException) as exc:
                await model_routes._fetch_models_from_provider("https://api.test", "bad", "/models", "openai")
        self.assertEqual(exc.exception.status_code, 502)
        self.assertIn("API Key", exc.exception.detail)

        class TimeoutClient(FakeAsyncClient):
            async def get(self, url, headers=None, params=None):
                raise httpx.TimeoutException("slow")

        with patch.object(model_routes.httpx, "AsyncClient", TimeoutClient):
            with self.assertRaises(HTTPException) as exc:
                await model_routes._fetch_models_from_provider("https://api.test", "key", "/models", "openai")
        self.assertEqual(exc.exception.status_code, 504)

        with patch.object(model_routes.httpx, "AsyncClient", FakeAsyncClient):
            with self.assertRaises(HTTPException) as bad_parser:
                await model_routes._fetch_models_from_provider("https://api.test", "key", "/models", "bad")
        self.assertEqual(bad_parser.exception.status_code, 400)

    async def test_model_route_wrappers_validate_provider_config_and_delegate_fetch(self) -> None:
        with patch.object(model_routes, "_get_provider_config", return_value=None):
            with self.assertRaises(HTTPException) as missing:
                await model_routes.get_provider_models(provider_name="missing", _auth=True)
        self.assertEqual(missing.exception.status_code, 404)

        with patch.object(model_routes, "_get_provider_config", return_value={"base_url": "", "api_key": "secret"}):
            with self.assertRaises(HTTPException) as no_url:
                await model_routes.get_provider_models(provider_name="bad", _auth=True)
        self.assertEqual(no_url.exception.status_code, 400)

        with (
            patch.object(
                model_routes,
                "_get_provider_config",
                return_value={"base_url": "https://api.test", "api_key": "secret", "client_type": "openai"},
            ),
            patch.object(
                model_routes, "_fetch_models_from_provider", new=AsyncMock(return_value=[{"id": "m1"}])
            ) as fetch,
        ):
            result = await model_routes.get_provider_models(
                provider_name="openai",
                parser="openai",
                endpoint="/models",
                _auth=True,
            )

        self.assertEqual(result, {"success": True, "models": [{"id": "m1"}], "provider": "openai", "count": 1})
        fetch.assert_awaited_once_with(
            base_url="https://api.test",
            api_key="secret",
            endpoint="/models",
            parser="openai",
            client_type="openai",
        )

        with patch.object(model_routes, "_fetch_models_from_provider", new=AsyncMock(return_value=[{"id": "m2"}])):
            self.assertEqual(
                await model_routes.get_models_by_url(
                    base_url="https://api.test",
                    api_key="secret",
                    parser="openai",
                    endpoint="/models",
                    client_type="openai",
                    _auth=True,
                ),
                {"success": True, "models": [{"id": "m2"}], "count": 1},
            )

    async def test_provider_connection_reports_network_latency_and_api_key_status(self) -> None:
        calls = []

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None):
                calls.append({"url": url, "headers": headers or {}, "timeout": self.kwargs.get("timeout")})
                if url.endswith("/models"):
                    return httpx.Response(401, text="unauthorized", request=httpx.Request("GET", url))
                return httpx.Response(204, request=httpx.Request("GET", url))

        with patch.object(model_routes.httpx, "AsyncClient", FakeAsyncClient):
            result = await model_routes.test_provider_connection(
                base_url="https://api.example.test/",
                api_key="bad-key",
                _auth=True,
            )

        self.assertTrue(result["network_ok"])
        self.assertFalse(result["api_key_valid"])
        self.assertEqual(result["http_status"], 204)
        self.assertIsInstance(result["latency_ms"], float)
        self.assertIn("API Key", result["error"])
        self.assertEqual(calls[0]["url"], "https://api.example.test")
        self.assertEqual(calls[0]["timeout"], 10.0)
        self.assertEqual(calls[1]["url"], "https://api.example.test/models")
        self.assertEqual(calls[1]["headers"]["Authorization"], "Bearer bad-key")

        class ConnectErrorClient(FakeAsyncClient):
            async def get(self, url, headers=None):
                raise httpx.ConnectError("offline", request=httpx.Request("GET", url))

        with patch.object(model_routes.httpx, "AsyncClient", ConnectErrorClient):
            failed = await model_routes.test_provider_connection(
                base_url="https://offline.example.test",
                api_key=None,
                _auth=True,
            )

        self.assertFalse(failed["network_ok"])
        self.assertIsNone(failed["api_key_valid"])
        self.assertIn("连接失败", failed["error"])

        with self.assertRaises(HTTPException) as empty_url:
            await model_routes.test_provider_connection(base_url="", api_key=None, _auth=True)
        self.assertEqual(empty_url.exception.status_code, 400)

    async def test_provider_connection_by_name_reads_model_config_and_delegates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir)
            model_config = tomlkit.document()
            model_config["api_providers"] = [
                {"name": "openai", "base_url": "https://api.example.test", "api_key": "secret"},
                {"name": "no-key", "base_url": "https://no-key.example.test", "api_key": ""},
                {"name": "no-url", "api_key": "secret"},
            ]
            (config_dir / "model_config.toml").write_text(tomlkit.dumps(model_config), encoding="utf-8")

            with (
                patch.object(model_routes, "CONFIG_DIR", str(config_dir)),
                patch.object(
                    model_routes, "test_provider_connection", new=AsyncMock(return_value={"network_ok": True})
                ) as test_connection,
            ):
                result = await model_routes.test_provider_connection_by_name(provider_name="openai", _auth=True)
                no_key_result = await model_routes.test_provider_connection_by_name(provider_name="no-key", _auth=True)

                with self.assertRaises(HTTPException) as missing_provider:
                    await model_routes.test_provider_connection_by_name(provider_name="missing", _auth=True)
                with self.assertRaises(HTTPException) as missing_url:
                    await model_routes.test_provider_connection_by_name(provider_name="no-url", _auth=True)

        self.assertEqual(result, {"network_ok": True})
        self.assertEqual(no_key_result, {"network_ok": True})
        self.assertEqual(
            test_connection.await_args_list[0].kwargs, {"base_url": "https://api.example.test", "api_key": "secret"}
        )
        self.assertEqual(
            test_connection.await_args_list[1].kwargs, {"base_url": "https://no-key.example.test", "api_key": None}
        )
        self.assertEqual(missing_provider.exception.status_code, 404)
        self.assertEqual(missing_url.exception.status_code, 400)

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(model_routes, "CONFIG_DIR", tmp_dir):
                with self.assertRaises(HTTPException) as missing_file:
                    await model_routes.test_provider_connection_by_name(provider_name="openai", _auth=True)
        self.assertEqual(missing_file.exception.status_code, 404)


class KnowledgeRoutesTest(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_knowledge_routes_return_empty_graph_stats_and_search_results(self) -> None:
        graph = await knowledge_routes.get_knowledge_graph(limit=10, node_type="entity", _auth=True)
        stats = await knowledge_routes.get_knowledge_stats(_auth=True)
        search = await knowledge_routes.search_knowledge_node(query="小明", _auth=True)

        self.assertEqual(graph.nodes, [])
        self.assertEqual(graph.edges, [])
        self.assertEqual(stats.total_nodes, 0)
        self.assertEqual(stats.total_edges, 0)
        self.assertEqual(stats.entity_nodes, 0)
        self.assertEqual(stats.paragraph_nodes, 0)
        self.assertEqual(stats.avg_connections, 0.0)
        self.assertEqual(search, [])

    def test_require_auth_delegates_cookie_and_header_to_shared_auth_checker(self) -> None:
        with patch.object(knowledge_routes, "verify_auth_token_from_cookie_or_header", return_value=True) as verify:
            self.assertTrue(knowledge_routes.require_auth("cookie-token", "Bearer header-token"))

        verify.assert_called_once_with("cookie-token", "Bearer header-token")


class FakeWebSocket:
    def __init__(self, *, cookies=None, receive_items=None):
        self.cookies = cookies or {}
        self.receive_items = list(receive_items or [])
        self.accepted = False
        self.closed = None
        self.sent_texts = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=None, reason=None):
        self.closed = (code, reason)

    async def send_text(self, text):
        self.sent_texts.append(text)

    async def receive_text(self):
        if not self.receive_items:
            raise logs_ws.WebSocketDisconnect(code=1000)
        item = self.receive_items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FailingSendWebSocket(FakeWebSocket):
    async def send_text(self, text):
        raise RuntimeError("send failed")


class LogsWebSocketTest(unittest.IsolatedAsyncioTestCase):
    def test_load_recent_logs_reads_latest_jsonl_files_skips_bad_lines_and_orders_old_to_new(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_dir = Path(tmp_dir) / "logs"
            log_dir.mkdir()
            old_log = log_dir / "app_old.log.jsonl"
            new_log = log_dir / "app_new.log.jsonl"
            old_log.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-07-07 10:00:00",
                        "level": "info",
                        "logger_name": "old",
                        "event": "old event",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            new_log.write_text(
                "{bad json\n"
                + json.dumps(
                    {
                        "timestamp": "2026-07-07 11:00:00",
                        "level": "warning",
                        "logger_name": "new",
                        "event": "new event",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            os.utime(old_log, (1, 1))
            os.utime(new_log, (2, 2))

            with patch.object(logs_ws, "Path", lambda _path: log_dir):
                logs = logs_ws.load_recent_logs(limit=2)

        self.assertEqual([entry["message"] for entry in logs], ["old event", "new event"])
        self.assertEqual(logs[0]["level"], "INFO")
        self.assertEqual(logs[1]["level"], "WARNING")
        self.assertTrue(logs[0]["id"].startswith("20260707100000_"))

    async def test_broadcast_log_sends_json_to_active_connections_and_removes_disconnected_clients(self) -> None:
        original_connections = set(logs_ws.active_connections)
        ok = FakeWebSocket()
        broken = FailingSendWebSocket()
        logs_ws.active_connections.clear()
        logs_ws.active_connections.update({ok, broken})

        try:
            await logs_ws.broadcast_log({"message": "hello"})
        finally:
            logs_ws.active_connections.clear()
            logs_ws.active_connections.update(original_connections)

        self.assertEqual(json.loads(ok.sent_texts[0]), {"message": "hello"})
        self.assertNotIn(broken, logs_ws.active_connections)

    async def test_websocket_logs_rejects_unauthenticated_and_accepts_ws_token_with_history_and_ping(self) -> None:
        denied = FakeWebSocket()
        with (
            patch.object(logs_ws, "verify_ws_token", return_value=False),
            patch.object(
                logs_ws, "get_token_manager", return_value=SimpleNamespace(verify_token=Mock(return_value=False))
            ),
        ):
            await logs_ws.websocket_logs(denied, token=None)

        self.assertEqual(denied.closed, (4001, "认证失败，请重新登录"))
        self.assertFalse(denied.accepted)

        original_connections = set(logs_ws.active_connections)
        accepted = FakeWebSocket(receive_items=["ping", logs_ws.WebSocketDisconnect(code=1000)])
        logs_ws.active_connections.clear()
        try:
            with (
                patch.object(logs_ws, "verify_ws_token", return_value=True),
                patch.object(logs_ws, "load_recent_logs", return_value=[{"message": "old"}]),
            ):
                await logs_ws.websocket_logs(accepted, token="ws-token")
        finally:
            logs_ws.active_connections.clear()
            logs_ws.active_connections.update(original_connections)

        self.assertTrue(accepted.accepted)
        self.assertEqual(json.loads(accepted.sent_texts[0]), {"message": "old"})
        self.assertEqual(accepted.sent_texts[1], "pong")
        self.assertNotIn(accepted, logs_ws.active_connections)


class PluginProgressWebSocketTest(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_and_update_progress_store_current_state_and_prune_disconnected_clients(self) -> None:
        original_connections = set(plugin_progress_ws.active_connections)
        original_progress = plugin_progress_ws.current_progress.copy()
        ok = FakeWebSocket()
        broken = FailingSendWebSocket()
        plugin_progress_ws.active_connections.clear()
        plugin_progress_ws.active_connections.update({ok, broken})

        try:
            await plugin_progress_ws.broadcast_progress({"stage": "loading", "progress": 10})
            self.assertEqual(plugin_progress_ws.current_progress, {"stage": "loading", "progress": 10})
            self.assertEqual(json.loads(ok.sent_texts[0]), {"stage": "loading", "progress": 10})
            self.assertNotIn(broken, plugin_progress_ws.active_connections)

            await plugin_progress_ws.update_progress(
                stage="success",
                progress=100,
                message="done",
                operation="install",
                plugin_id="plugin-a",
                total_plugins=3,
                loaded_plugins=3,
            )
        finally:
            plugin_progress_ws.active_connections.clear()
            plugin_progress_ws.active_connections.update(original_connections)
            plugin_progress_ws.current_progress = original_progress

        sent_update = json.loads(ok.sent_texts[1])
        self.assertEqual(sent_update["operation"], "install")
        self.assertEqual(sent_update["stage"], "success")
        self.assertEqual(sent_update["progress"], 100)
        self.assertEqual(sent_update["plugin_id"], "plugin-a")
        self.assertIn("timestamp", sent_update)

    async def test_websocket_plugin_progress_rejects_unauthenticated_and_cleans_up_after_disconnect(self) -> None:
        denied = FakeWebSocket()
        with (
            patch.object(plugin_progress_ws, "verify_ws_token", return_value=False),
            patch.object(
                plugin_progress_ws,
                "get_token_manager",
                return_value=SimpleNamespace(verify_token=Mock(return_value=False)),
            ),
        ):
            await plugin_progress_ws.websocket_plugin_progress(denied, token=None)

        self.assertEqual(denied.closed, (4001, "认证失败，请重新登录"))
        self.assertFalse(denied.accepted)

        original_connections = set(plugin_progress_ws.active_connections)
        original_progress = plugin_progress_ws.current_progress.copy()
        accepted = FakeWebSocket(receive_items=["ping", plugin_progress_ws.WebSocketDisconnect(code=1000)])
        plugin_progress_ws.active_connections.clear()
        plugin_progress_ws.current_progress = {"operation": "idle", "stage": "idle", "progress": 0}

        try:
            with patch.object(plugin_progress_ws, "verify_ws_token", return_value=True):
                await plugin_progress_ws.websocket_plugin_progress(accepted, token="ws-token")
        finally:
            plugin_progress_ws.active_connections.clear()
            plugin_progress_ws.active_connections.update(original_connections)
            plugin_progress_ws.current_progress = original_progress

        self.assertTrue(accepted.accepted)
        self.assertEqual(json.loads(accepted.sent_texts[0]), {"operation": "idle", "stage": "idle", "progress": 0})
        self.assertEqual(accepted.sent_texts[1], "pong")
        self.assertNotIn(accepted, plugin_progress_ws.active_connections)

    def test_get_progress_router_returns_module_router(self) -> None:
        self.assertIs(plugin_progress_ws.get_progress_router(), plugin_progress_ws.router)


class WebUIRoutesTest(unittest.IsolatedAsyncioTestCase):
    async def test_health_logout_and_auth_check_use_cookie_or_bearer_token(self) -> None:
        self.assertEqual(await webui_routes.health_check(), {"status": "healthy", "service": "RiyaBot WebUI"})

        response = Response()
        with patch.object(webui_routes, "clear_auth_cookie") as clear_cookie:
            self.assertEqual(await webui_routes.logout(response), {"success": True, "message": "已成功登出"})
        clear_cookie.assert_called_once_with(response)

        token_manager_stub = SimpleNamespace(
            verify_token=Mock(side_effect=lambda token: token == "valid"),
            is_password_configured=Mock(return_value=True),
        )
        with patch.object(webui_routes, "get_token_manager", return_value=token_manager_stub):
            self.assertEqual(
                await webui_routes.check_auth_status(SimpleNamespace(), maibot_session=None, authorization=None),
                {"authenticated": False, "password_configured": True},
            )
            self.assertEqual(
                await webui_routes.check_auth_status(SimpleNamespace(), maibot_session="valid"),
                {"authenticated": True, "password_configured": True},
            )
            self.assertEqual(
                await webui_routes.check_auth_status(
                    SimpleNamespace(), maibot_session=None, authorization="Bearer invalid"
                ),
                {"authenticated": False, "password_configured": True},
            )

        with patch.object(webui_routes, "get_token_manager", side_effect=RuntimeError("token db down")):
            self.assertEqual(
                await webui_routes.check_auth_status(SimpleNamespace(), maibot_session="valid"),
                {"authenticated": False, "password_configured": True},
            )

    async def test_update_and_regenerate_token_are_disabled(self) -> None:
        response = Response()
        token_manager_stub = SimpleNamespace(
            verify_token=Mock(side_effect=lambda token: token == "current"),
        )

        with patch.object(webui_routes, "get_token_manager", return_value=token_manager_stub):
            with self.assertRaises(HTTPException) as missing:
                await webui_routes.update_token(
                    webui_routes.TokenUpdateRequest(new_token="new-token-123"),
                    response,
                    SimpleNamespace(),
                    maibot_session=None,
                    authorization=None,
                )
            with self.assertRaises(HTTPException) as invalid:
                await webui_routes.regenerate_token(
                    response, SimpleNamespace(), maibot_session=None, authorization="Bearer bad"
                )

        self.assertEqual(missing.exception.status_code, 401)
        self.assertEqual(invalid.exception.status_code, 401)

        with patch.object(webui_routes, "get_token_manager", return_value=token_manager_stub):
            with self.assertRaises(HTTPException) as update_disabled:
                await webui_routes.update_token(
                    webui_routes.TokenUpdateRequest(new_token="new-token-123"),
                    response,
                    SimpleNamespace(),
                    maibot_session="current",
                )
            with self.assertRaises(HTTPException) as regenerate_disabled:
                await webui_routes.regenerate_token(
                    response,
                    SimpleNamespace(),
                    maibot_session="current",
                )

        self.assertEqual(update_disabled.exception.status_code, 410)
        self.assertEqual(regenerate_disabled.exception.status_code, 410)

    async def test_setup_status_complete_reset_and_agreement_routes_map_auth_and_state_errors(self) -> None:
        token_manager_stub = SimpleNamespace(
            verify_token=Mock(side_effect=lambda token: token == "current"),
            is_first_setup=Mock(return_value=False),
            mark_setup_completed=Mock(return_value=True),
            reset_setup_status=Mock(return_value=True),
        )
        document_status = {
            "eula": SimpleNamespace(
                title="EULA",
                file_name="EULA.md",
                hash="eula-hash",
                confirmed=True,
                environment_confirmed=False,
                content="eula text",
            ),
            "privacy": SimpleNamespace(
                title="Privacy",
                file_name="PRIVACY.md",
                hash="privacy-hash",
                confirmed=False,
                environment_confirmed=True,
                content="privacy text",
            ),
        }

        with (
            patch.object(webui_routes, "get_token_manager", return_value=token_manager_stub),
            patch.object(webui_routes, "are_agreements_confirmed", return_value=False),
            patch.object(webui_routes, "_get_model_config_readiness_error", return_value="missing model"),
            patch("src.config.config.get_created_config_files", return_value=["bot_config.toml"]),
        ):
            status = await webui_routes.get_setup_status(SimpleNamespace(), maibot_session="current")
            with self.assertRaises(HTTPException) as complete_blocked:
                await webui_routes.complete_setup(SimpleNamespace(), maibot_session="current")

        self.assertTrue(status.is_first_setup)
        self.assertTrue(status.agreement_required)
        self.assertEqual(status.created_config_files, ["bot_config.toml"])
        self.assertTrue(status.model_config_required)
        self.assertEqual(status.model_config_message, "missing model")
        self.assertEqual(complete_blocked.exception.status_code, 400)

        with (
            patch.object(webui_routes, "get_token_manager", return_value=token_manager_stub),
            patch.object(webui_routes, "are_agreements_confirmed", return_value=True),
            patch.object(webui_routes, "_get_model_config_readiness_error", return_value=""),
        ):
            completed = await webui_routes.complete_setup(
                SimpleNamespace(), maibot_session=None, authorization="Bearer current"
            )
            reset = await webui_routes.reset_setup(SimpleNamespace(), maibot_session="current")

        self.assertEqual(completed, webui_routes.CompleteSetupResponse(success=True, message="配置已完成"))
        self.assertEqual(reset, webui_routes.ResetSetupResponse(success=True, message="配置状态已重置"))

        with (
            patch.object(webui_routes, "get_token_manager", return_value=token_manager_stub),
            patch.object(webui_routes, "get_agreement_status", return_value=document_status),
        ):
            agreement = await webui_routes.get_setup_agreement(SimpleNamespace(), maibot_session="current")

        self.assertTrue(agreement.agreement_required)
        self.assertEqual(agreement.eula.hash, "eula-hash")
        self.assertEqual(agreement.privacy.content, "privacy text")

        with (
            patch.object(webui_routes, "get_token_manager", return_value=token_manager_stub),
            patch.object(webui_routes, "confirm_agreements", side_effect=ValueError("stale")),
        ):
            with self.assertRaises(HTTPException) as stale:
                await webui_routes.confirm_setup_agreement(
                    webui_routes.AgreementConfirmRequest(eula_hash="old", privacy_hash="old"),
                    SimpleNamespace(),
                    maibot_session="current",
                )

        self.assertEqual(stale.exception.status_code, 409)


class WebUIServerTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        webui_server._webui_server = None

    def make_server(self, *, host: str = "127.0.0.1", port: int = 0):
        server = webui_server.WebUIServer.__new__(webui_server.WebUIServer)
        server.host = host
        server.port = port
        server._server = None
        return server

    def test_check_port_available_handles_free_and_bound_ipv4_ports(self) -> None:
        server = self.make_server(port=0)
        self.assertTrue(server._check_port_available())

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            occupied_port = sock.getsockname()[1]

            server.port = occupied_port
            self.assertFalse(server._check_port_available())

    async def test_start_fails_fast_when_port_is_unavailable_without_creating_uvicorn_server(self) -> None:
        server = self.make_server(port=8001)

        with (
            patch.object(server, "_check_port_available", return_value=False),
            patch.object(webui_server, "UvicornServer") as uvicorn_server,
        ):
            with self.assertRaises(OSError):
                await server.start()

        uvicorn_server.assert_not_called()

    async def test_shutdown_marks_underlying_server_exit_and_suppresses_shutdown_errors(self) -> None:
        server = self.make_server()
        fake_uvicorn = SimpleNamespace(should_exit=False, shutdown=AsyncMock())
        server._server = fake_uvicorn

        await server.shutdown()

        self.assertTrue(fake_uvicorn.should_exit)
        fake_uvicorn.shutdown.assert_awaited_once()
        self.assertIsNone(server._server)

        failing_uvicorn = SimpleNamespace(should_exit=False, shutdown=AsyncMock(side_effect=RuntimeError("bad stop")))
        server._server = failing_uvicorn

        await server.shutdown()

        self.assertTrue(failing_uvicorn.should_exit)
        self.assertIsNone(server._server)

    def test_get_webui_server_uses_environment_once(self) -> None:
        sentinel = object()
        with (
            patch.dict(os.environ, {"WEBUI_HOST": "127.0.0.2", "WEBUI_PORT": "9002"}, clear=False),
            patch.object(webui_server, "WebUIServer", return_value=sentinel) as server_cls,
        ):
            self.assertIs(webui_server.get_webui_server(), sentinel)
            self.assertIs(webui_server.get_webui_server(), sentinel)

        server_cls.assert_called_once_with(host="127.0.0.2", port=9002)


if __name__ == "__main__":
    unittest.main()
