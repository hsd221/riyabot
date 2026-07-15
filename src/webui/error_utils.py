"""WebUI 内部错误的安全日志与响应转换。"""

from typing import Any

from fastapi import HTTPException


def log_exception_type(logger: Any, action: str, exc: BaseException, *, level: str = "error", **context: Any) -> None:
    """仅记录异常类型与显式安全上下文，不记录异常文本或 traceback。"""
    log_method = getattr(logger, level)
    log_method(action, error_type=type(exc).__name__, **context)


def internal_server_error(
    logger: Any,
    action: str,
    exc: BaseException,
    *,
    detail: str | None = None,
) -> HTTPException:
    """记录脱敏错误并构造固定文案的 HTTP 500。"""
    log_exception_type(logger, action, exc)
    return HTTPException(status_code=500, detail=detail or action)
