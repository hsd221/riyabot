"""
WebUI 认证模块
提供统一的认证依赖，支持 Cookie 和 Header 两种方式
"""

from typing import Optional
from fastapi import HTTPException, Cookie, Header, Response, Request
from src.common.logger import get_logger, hash_id
from src.config.config import global_config
from .token_manager import get_token_manager
from .rate_limiter import is_trusted_proxy

logger = get_logger("webui.auth")

# Cookie 配置
COOKIE_NAME = "maibot_session"
COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7天


def _is_secure_environment() -> bool:
    """
    检测是否应该启用安全 Cookie（HTTPS）

    Returns:
        bool: 如果应该使用 secure cookie 则返回 True
    """
    # 从配置读取
    if global_config.webui.secure_cookie:
        logger.info("配置中启用了 secure_cookie")
        return True

    # 检查是否是生产环境
    if global_config.webui.mode == "production":
        logger.info("WebUI运行在生产模式，启用 secure cookie")
        return True

    # 默认：开发环境不启用（因为通常是 HTTP）
    logger.debug("WebUI运行在开发模式，禁用 secure cookie")
    return False


def request_uses_https(request: Optional[Request] = None) -> bool:
    """根据直连协议或可信代理转发头判断当前请求是否使用 HTTPS。"""
    if request is None:
        return False
    request_scheme = getattr(getattr(request, "url", None), "scheme", "").lower()
    if request_scheme == "https":
        return True
    peer_ip = getattr(getattr(request, "client", None), "host", "")
    if not is_trusted_proxy(peer_ip, global_config):
        return False
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", maxsplit=1)[0].strip().lower()
    return forwarded_proto == "https"


def _should_use_secure_cookie(request: Optional[Request] = None) -> bool:
    """根据实际传输协议和显式配置决定是否设置 Secure。"""
    configured_secure = _is_secure_environment()
    if request is None:
        return configured_secure

    request_scheme = getattr(getattr(request, "url", None), "scheme", "").lower()
    is_https = request_uses_https(request)
    if is_https:
        return True
    if configured_secure:
        logger.warning(
            "当前连接不是 HTTPS，认证 Cookie 无法启用 Secure",
            event_code="webui.auth.insecure_transport",
            scheme=request_scheme or "unknown",
        )
    return False


def get_current_token(
    request: Request,
    maibot_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> str:
    """
    获取当前请求的 token，优先从 Cookie 获取，其次从 Header 获取

    Args:
        request: FastAPI Request 对象
        maibot_session: Cookie 中的 token
        authorization: Authorization Header (Bearer token)

    Returns:
        验证通过的 token

    Raises:
        HTTPException: 认证失败时抛出 401 错误
    """
    token = None

    # 优先从 Cookie 获取
    if maibot_session:
        token = maibot_session
    # 其次从 Header 获取（兼容旧版本）
    elif authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")

    if not token:
        raise HTTPException(status_code=401, detail="未提供有效的认证信息")

    # 验证 token
    token_manager = get_token_manager()
    if not token_manager.verify_token(token):
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    return token


def set_auth_cookie(response: Response, token: str, request: Optional[Request] = None) -> None:
    """
    设置认证 Cookie

    Args:
        response: FastAPI Response 对象
        token: 要设置的 token
        request: FastAPI Request 对象（可选，用于检测协议）
    """
    is_secure = _should_use_secure_cookie(request)

    # 设置 Cookie
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,  # 防止 JS 读取，阻止 XSS 窃取
        samesite="strict",
        secure=is_secure,  # 根据实际协议决定
        path="/",  # 确保 Cookie 在所有路径下可用
    )

    logger.info(
        "已设置认证 Cookie",
        token_hash=hash_id(token),
        secure=is_secure,
        samesite="strict",
        httponly=True,
        path="/",
        max_age=COOKIE_MAX_AGE,
    )


def clear_auth_cookie(response: Response, request: Optional[Request] = None) -> None:
    """
    清除认证 Cookie

    Args:
        response: FastAPI Response 对象
    """
    is_secure = _should_use_secure_cookie(request)

    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        samesite="strict",
        secure=is_secure,
        path="/",
    )
    logger.debug("已清除认证 Cookie")


def verify_auth_token_from_cookie_or_header(
    maibot_session: Optional[str] = None,
    authorization: Optional[str] = None,
) -> bool:
    """
    验证认证 Token，支持从 Cookie 或 Header 获取

    Args:
        maibot_session: Cookie 中的 token
        authorization: Authorization header (Bearer token)

    Returns:
        验证成功返回 True

    Raises:
        HTTPException: 认证失败时抛出 401 错误
    """
    token = None

    # 优先从 Cookie 获取
    if maibot_session:
        token = maibot_session
    # 其次从 Header 获取（兼容旧版本）
    elif authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")

    if not token:
        raise HTTPException(status_code=401, detail="未提供有效的认证信息")

    # 验证 token
    token_manager = get_token_manager()
    if not token_manager.verify_token(token):
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    return True
