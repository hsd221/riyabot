"""WebSocket 认证模块

提供所有 WebSocket 端点统一使用的临时 token 认证机制。
临时 token 有效期 60 秒，且只能使用一次，用于解决 WebSocket 握手时 Cookie 不可用的问题。
"""

import os
import secrets
import time
from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Cookie, Header, WebSocket

from src.common.logger import get_logger
from src.webui.token_manager import get_token_manager

logger = get_logger("webui.ws_auth")
router = APIRouter()

# WebSocket 临时 token 存储 {token: (expire_time, session_token)}
# 临时 token 有效期 60 秒，仅用于 WebSocket 握手
_ws_temp_tokens: dict[str, tuple[float, str]] = {}
_WS_TOKEN_EXPIRE_SECONDS = 60
_WS_MAX_TOKENS = 1024
_LOCAL_WS_HOSTS = {"localhost", "127.0.0.1", "::1"}
_LOCAL_DEV_PORTS = {5173, 7999, 8001}


def _default_port(scheme: str) -> int:
    return 443 if scheme.lower() in {"https", "wss"} else 80


def is_websocket_origin_allowed(websocket: WebSocket) -> bool:
    """校验浏览器 WebSocket Origin；无 Origin 的非浏览器客户端保持兼容。"""
    headers = getattr(websocket, "headers", {})
    origin = (headers.get("origin") or "").strip()
    if not origin:
        return True

    configured_origins = {
        item.strip().rstrip("/") for item in os.getenv("MAIBOT_ALLOWED_WS_ORIGINS", "").split(",") if item.strip()
    }
    if origin.rstrip("/") in configured_origins:
        return True

    try:
        origin_url = urlsplit(origin)
        if (
            origin_url.scheme not in {"http", "https"}
            or not origin_url.hostname
            or origin_url.username is not None
            or origin_url.password is not None
            or origin_url.path not in {"", "/"}
            or origin_url.query
            or origin_url.fragment
        ):
            return False

        host_header = (headers.get("host") or "").strip()
        request_url = getattr(websocket, "url", None)
        if host_header:
            target = urlsplit(f"//{host_header}")
            target_host = target.hostname
            target_port = target.port
        else:
            target_host = getattr(request_url, "hostname", None)
            target_port = getattr(request_url, "port", None)

        if not target_host:
            return False

        target_scheme = getattr(request_url, "scheme", "ws")
        target_port = target_port or _default_port(target_scheme)
        origin_port = origin_url.port or _default_port(origin_url.scheme)
        origin_host = origin_url.hostname.lower().rstrip(".")
        target_host = target_host.lower().rstrip(".")

        if origin_host == target_host and origin_port == target_port:
            return True
        return (
            origin_host in _LOCAL_WS_HOSTS
            and target_host in _LOCAL_WS_HOSTS
            and origin_port in _LOCAL_DEV_PORTS
            and target_port in _LOCAL_DEV_PORTS
        )
    except (TypeError, ValueError):
        return False


def _cleanup_expired_ws_tokens():
    """清理过期的临时 token"""
    now = time.time()
    expired = [t for t, (exp, _) in _ws_temp_tokens.items() if now > exp]
    for t in expired:
        del _ws_temp_tokens[t]


def generate_ws_token(session_token: str) -> str:
    """生成 WebSocket 临时 token

    Args:
        session_token: 原始的 session token

    Returns:
        临时 token 字符串
    """
    _cleanup_expired_ws_tokens()
    if len(_ws_temp_tokens) >= _WS_MAX_TOKENS:
        oldest_token = min(_ws_temp_tokens, key=lambda item: _ws_temp_tokens[item][0])
        del _ws_temp_tokens[oldest_token]
    temp_token = secrets.token_urlsafe(32)
    _ws_temp_tokens[temp_token] = (time.time() + _WS_TOKEN_EXPIRE_SECONDS, session_token)
    logger.debug("生成一次性 WebSocket 临时令牌", expires_in=_WS_TOKEN_EXPIRE_SECONDS)
    return temp_token


def verify_ws_token(temp_token: str) -> bool:
    """验证并消费 WebSocket 临时 token（一次性使用）

    Args:
        temp_token: 临时 token

    Returns:
        验证是否通过
    """
    _cleanup_expired_ws_tokens()
    if temp_token not in _ws_temp_tokens:
        logger.warning("WebSocket 临时令牌不存在或已消费")
        return False
    expire_time, session_token = _ws_temp_tokens[temp_token]
    if time.time() > expire_time:
        del _ws_temp_tokens[temp_token]
        logger.warning("WebSocket 临时令牌已过期")
        return False
    # 验证原始 session token 仍然有效
    token_manager = get_token_manager()
    if not token_manager.verify_token(session_token):
        del _ws_temp_tokens[temp_token]
        logger.warning("WebSocket 临时令牌关联的会话已失效")
        return False
    # 消费 token（一次性使用）
    del _ws_temp_tokens[temp_token]
    logger.debug("WebSocket 临时令牌验证成功")
    return True


@router.get("/ws-token")
async def get_ws_token(
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """
    获取 WebSocket 连接用的临时 token

    此端点验证当前会话的 Cookie 或 Authorization header，
    然后返回一个临时 token 用于 WebSocket 握手认证。
    临时 token 有效期 60 秒，且只能使用一次。

    注意：在未认证时返回 200 状态码但 success=False，避免前端因 401 刷新页面。
    """
    # 获取当前 session token
    session_token = None
    if maibot_session:
        session_token = maibot_session
    elif authorization and authorization.startswith("Bearer "):
        session_token = authorization.replace("Bearer ", "")

    if not session_token:
        # 返回 200 但 success=False，避免前端因 401 刷新页面
        # 这在登录页面是正常情况，不应该触发错误处理
        logger.debug("ws-token 请求：未提供认证信息（可能在登录页面）")
        return {"success": False, "message": "未提供认证信息，请先登录", "token": None, "expires_in": 0}

    # 验证 session token
    token_manager = get_token_manager()
    if not token_manager.verify_token(session_token):
        # 同样返回 200 但 success=False，避免前端刷新
        logger.debug("ws-token 请求：认证已过期")
        return {"success": False, "message": "认证已过期，请重新登录", "token": None, "expires_in": 0}

    # 生成临时 WebSocket token
    ws_token = generate_ws_token(session_token)

    return {"success": True, "token": ws_token, "expires_in": _WS_TOKEN_EXPIRE_SECONDS}
