"""WebSocket 插件加载进度推送模块"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Set, Dict, Any, Optional
import json
import asyncio
import unicodedata

from src.common.logger import get_logger, redact_text
from src.webui.error_utils import log_exception_type
from src.webui.token_manager import get_token_manager
from src.webui.ws_auth import is_websocket_origin_allowed, verify_ws_token

logger = get_logger("webui.plugin_progress")

# 创建路由器
router = APIRouter()

# 全局 WebSocket 连接池
active_connections: Set[WebSocket] = set()
MAX_PROGRESS_WS_CONNECTIONS = 16
MAX_WS_CONTROL_MESSAGE_CHARS = 64
MAX_PROGRESS_MESSAGE_CHARS = 512
MAX_PROGRESS_ERROR_CHARS = 256
MAX_PROGRESS_PLUGIN_ID_CHARS = 128
MAX_PROGRESS_PLUGIN_COUNT = 10_000
_ALLOWED_OPERATIONS = {"idle", "fetch", "install", "uninstall", "update"}
_ALLOWED_STAGES = {"idle", "loading", "success", "error"}
_connection_lock = asyncio.Lock()

# 当前加载进度状态
current_progress: Dict[str, Any] = {
    "operation": "idle",  # idle, fetch, install, uninstall, update
    "stage": "idle",  # idle, loading, success, error
    "progress": 0,  # 0-100
    "message": "",
    "error": None,
    "plugin_id": None,  # 当前操作的插件 ID
    "total_plugins": 0,
    "loaded_plugins": 0,
}


def _bounded_progress_int(value: Any, *, minimum: int, maximum: int, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(minimum, min(value, maximum))


def _safe_progress_text(value: Any, *, max_chars: int, default: Optional[str]) -> Optional[str]:
    if value is None:
        return default
    if not isinstance(value, str):
        return default

    filtered = "".join(
        " " if char in "\r\n\t" else char
        for char in value
        if ord(char) >= 32 and ord(char) != 127 and unicodedata.category(char) != "Cf"
    )
    return redact_text(filtered, allow_plaintext=True, max_length=max_chars)[:max_chars]


def _normalize_progress_data(progress_data: Dict[str, Any]) -> Dict[str, Any]:
    operation = progress_data.get("operation")
    if not isinstance(operation, str) or operation not in _ALLOWED_OPERATIONS:
        operation = "idle"

    stage = progress_data.get("stage")
    if not isinstance(stage, str) or stage not in _ALLOWED_STAGES:
        stage = "idle"

    total_plugins = _bounded_progress_int(
        progress_data.get("total_plugins", 0),
        minimum=0,
        maximum=MAX_PROGRESS_PLUGIN_COUNT,
        default=0,
    )
    loaded_plugins = _bounded_progress_int(
        progress_data.get("loaded_plugins", 0),
        minimum=0,
        maximum=MAX_PROGRESS_PLUGIN_COUNT,
        default=0,
    )
    loaded_plugins = min(loaded_plugins, total_plugins)

    return {
        "operation": operation,
        "stage": stage,
        "progress": _bounded_progress_int(
            progress_data.get("progress", 0),
            minimum=0,
            maximum=100,
            default=0,
        ),
        "message": _safe_progress_text(
            progress_data.get("message"),
            max_chars=MAX_PROGRESS_MESSAGE_CHARS,
            default="",
        ),
        "error": _safe_progress_text(
            progress_data.get("error"),
            max_chars=MAX_PROGRESS_ERROR_CHARS,
            default=None,
        ),
        "plugin_id": _safe_progress_text(
            progress_data.get("plugin_id"),
            max_chars=MAX_PROGRESS_PLUGIN_ID_CHARS,
            default=None,
        ),
        "total_plugins": total_plugins,
        "loaded_plugins": loaded_plugins,
        "timestamp": asyncio.get_event_loop().time(),
    }


async def broadcast_progress(progress_data: Dict[str, Any]) -> Dict[str, Any]:
    """广播进度更新到所有连接的客户端"""
    global current_progress
    normalized_progress = _normalize_progress_data(progress_data)
    current_progress = normalized_progress.copy()

    if not active_connections:
        return normalized_progress

    message = json.dumps(normalized_progress, ensure_ascii=False)
    disconnected = set()

    for websocket in active_connections:
        try:
            await websocket.send_text(message)
        except Exception as e:
            log_exception_type(logger, "发送进度更新失败", e)
            disconnected.add(websocket)

    # 移除断开的连接
    for websocket in disconnected:
        active_connections.discard(websocket)

    return normalized_progress


async def update_progress(
    stage: str,
    progress: int,
    message: str,
    operation: str = "fetch",
    error: str = None,
    plugin_id: str = None,
    total_plugins: int = 0,
    loaded_plugins: int = 0,
):
    """更新并广播进度

    Args:
        stage: 阶段 (idle, loading, success, error)
        progress: 进度百分比 (0-100)
        message: 当前消息
        operation: 操作类型 (fetch, install, uninstall, update)
        error: 错误信息（可选）
        plugin_id: 当前操作的插件 ID
        total_plugins: 总插件数
        loaded_plugins: 已加载插件数
    """
    progress_data = {
        "operation": operation,
        "stage": stage,
        "progress": progress,
        "message": message,
        "error": error,
        "plugin_id": plugin_id,
        "total_plugins": total_plugins,
        "loaded_plugins": loaded_plugins,
        "timestamp": asyncio.get_event_loop().time(),
    }

    normalized_progress = await broadcast_progress(progress_data)
    logger.debug(
        "插件进度已更新",
        event_code="webui.plugin_progress.updated",
        operation=normalized_progress["operation"],
        stage=normalized_progress["stage"],
        progress=normalized_progress["progress"],
    )


@router.websocket("/ws/plugin-progress")
async def websocket_plugin_progress(websocket: WebSocket, token: Optional[str] = Query(None)):
    """WebSocket 插件加载进度推送端点

    客户端连接后会立即收到当前进度状态
    支持两种认证方式（按优先级）：
    1. query 参数 token（推荐，通过 /api/webui/ws-token 获取临时 token）
    2. Cookie 中的 maibot_session

    示例：ws://host/ws/plugin-progress?token=xxx
    """
    if not is_websocket_origin_allowed(websocket):
        logger.warning("插件进度 WebSocket Origin 被拒绝", event_code="webui.plugin_progress_ws.origin_rejected")
        await websocket.close(code=4003, reason="不允许的请求来源")
        return

    is_authenticated = False

    # 方式 1: 尝试验证临时 WebSocket token（推荐方式）
    if token and verify_ws_token(token):
        is_authenticated = True
        logger.debug(
            "插件进度 WebSocket 认证成功",
            event_code="webui.plugin_progress_ws.auth_success",
            auth_method="ws_token",
        )

    # 方式 2: 尝试从 Cookie 获取 session token
    if not is_authenticated:
        cookie_token = websocket.cookies.get("maibot_session")
        if cookie_token:
            token_manager = get_token_manager()
            if token_manager.verify_token(cookie_token):
                is_authenticated = True
                logger.debug(
                    "插件进度 WebSocket 认证成功",
                    event_code="webui.plugin_progress_ws.auth_success",
                    auth_method="cookie",
                )

    if not is_authenticated:
        logger.warning("插件进度 WebSocket 连接被拒绝", event_code="webui.plugin_progress_ws.auth_failed")
        await websocket.close(code=4001, reason="认证失败，请重新登录")
        return

    async with _connection_lock:
        if len(active_connections) >= MAX_PROGRESS_WS_CONNECTIONS:
            logger.warning("插件进度 WebSocket 连接数已达上限", event_code="webui.plugin_progress_ws.capacity_reached")
            await websocket.close(code=1013, reason="连接数过多，请稍后重试")
            return
        await websocket.accept()
        active_connections.add(websocket)
    logger.info(
        "插件进度 WebSocket 客户端已连接",
        event_code="webui.plugin_progress_ws.connected",
        connection_count=len(active_connections),
    )

    try:
        # 发送当前进度状态
        await websocket.send_text(json.dumps(current_progress, ensure_ascii=False))

        # 保持连接并处理客户端消息
        while True:
            try:
                data = await websocket.receive_text()

                if len(data) > MAX_WS_CONTROL_MESSAGE_CHARS:
                    active_connections.discard(websocket)
                    await websocket.close(code=1009, reason="控制消息过长")
                    break

                # 处理客户端心跳
                if data == "ping":
                    await websocket.send_text("pong")

            except WebSocketDisconnect:
                active_connections.discard(websocket)
                logger.info(
                    "插件进度 WebSocket 客户端已断开",
                    event_code="webui.plugin_progress_ws.disconnected",
                    connection_count=len(active_connections),
                )
                break
            except Exception as e:
                log_exception_type(
                    logger,
                    "插件进度 WebSocket 客户端消息处理失败",
                    e,
                    event_code="webui.plugin_progress_ws.message_failed",
                )
                active_connections.discard(websocket)
                break

    except WebSocketDisconnect:
        active_connections.discard(websocket)
        logger.info(
            "插件进度 WebSocket 客户端已断开",
            event_code="webui.plugin_progress_ws.disconnected",
            connection_count=len(active_connections),
        )
    except Exception as e:
        log_exception_type(
            logger,
            "插件进度 WebSocket 连接异常",
            e,
            event_code="webui.plugin_progress_ws.connection_failed",
        )
        active_connections.discard(websocket)


def get_progress_router() -> APIRouter:
    """获取插件进度 WebSocket 路由器"""
    return router
