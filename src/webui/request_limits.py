"""WebUI HTTP 请求体大小限制。"""

from __future__ import annotations

from collections.abc import Mapping

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_MAX_WEBUI_REQUEST_BYTES = 8 * 1024 * 1024
_AUTH_REQUEST_BYTES = 16 * 1024
_RAW_CONFIG_REQUEST_BYTES = 2 * 1024 * 1024 + 64 * 1024
_SINGLE_EMOJI_REQUEST_BYTES = 11 * 1024 * 1024
_BATCH_EMOJI_REQUEST_BYTES = 201 * 1024 * 1024
_CHAT_HISTORY_IMPORT_REQUEST_BYTES = 101 * 1024 * 1024

WEBUI_PATH_BODY_LIMITS = {
    "/api/webui/auth/setup": _AUTH_REQUEST_BYTES,
    "/api/webui/auth/login": _AUTH_REQUEST_BYTES,
    "/api/webui/auth/verify": _AUTH_REQUEST_BYTES,
    "/api/webui/auth/password": _AUTH_REQUEST_BYTES,
    "/api/webui/auth/update": _AUTH_REQUEST_BYTES,
    "/api/webui/config/bot/raw": _RAW_CONFIG_REQUEST_BYTES,
    "/api/webui/emoji/upload": _SINGLE_EMOJI_REQUEST_BYTES,
    "/api/webui/emoji/batch/upload": _BATCH_EMOJI_REQUEST_BYTES,
    "/api/webui/chat-history-imports": _CHAT_HISTORY_IMPORT_REQUEST_BYTES,
}


class _RequestBodyTooLarge(Exception):
    pass


def _parse_content_length(headers: list[tuple[bytes, bytes]]) -> int | None:
    values: list[int] = []
    for name, raw_value in headers:
        if name.lower() != b"content-length":
            continue
        try:
            decoded = raw_value.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("invalid content length") from exc
        for item in decoded.split(","):
            item = item.strip()
            if not item or not item.isdecimal():
                raise ValueError("invalid content length")
            try:
                values.append(int(item))
            except ValueError as exc:
                raise ValueError("invalid content length") from exc

    if not values:
        return None
    if any(value != values[0] for value in values[1:]):
        raise ValueError("conflicting content length")
    return values[0]


class RequestBodyLimitMiddleware:
    """在 FastAPI 解析 JSON/表单前限制声明值和实际接收字节数。"""

    def __init__(
        self,
        app: ASGIApp,
        default_limit: int = DEFAULT_MAX_WEBUI_REQUEST_BYTES,
        path_limits: Mapping[str, int] | None = None,
    ) -> None:
        if default_limit <= 0:
            raise ValueError("default_limit must be positive")
        self.app = app
        self.default_limit = default_limit
        self.path_limits = dict(WEBUI_PATH_BODY_LIMITS if path_limits is None else path_limits)
        if any(limit <= 0 for limit in self.path_limits.values()):
            raise ValueError("path limits must be positive")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self.path_limits.get(scope.get("path", ""), self.default_limit)
        try:
            content_length = _parse_content_length(scope.get("headers", []))
        except ValueError:
            await JSONResponse(status_code=400, content={"detail": "Content-Length 请求头无效"})(scope, receive, send)
            return

        if content_length is not None and content_length > limit:
            await JSONResponse(status_code=413, content={"detail": "请求体过大"})(scope, receive, send)
            return

        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > limit:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await JSONResponse(status_code=413, content={"detail": "请求体过大"})(scope, receive, send)
