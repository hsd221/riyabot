"""WebSocket 日志推送模块"""

import asyncio
import heapq
import json
from pathlib import Path
from typing import Optional, Set

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.common.logger import get_logger
from src.webui.error_utils import log_exception_type
from src.webui.token_manager import get_token_manager
from src.webui.ws_auth import is_websocket_origin_allowed, verify_ws_token

logger = get_logger("webui.logs_ws")
router = APIRouter()

# 全局 WebSocket 连接池
active_connections: Set[WebSocket] = set()

MAX_LOG_SCAN_BYTES = 4 * 1024 * 1024
MAX_LOG_LINE_BYTES = 256 * 1024
MAX_LOG_FILES = 20
MAX_LOG_ENTRIES = 1000
MAX_LOG_WS_CONNECTIONS = 16
MAX_WS_CONTROL_MESSAGE_CHARS = 64
_connection_lock = asyncio.Lock()


def _read_tail_lines(log_file: Path, max_lines: int) -> list[str]:
    """从文件尾部读取有限字节，避免把超大日志整体载入内存。"""
    if max_lines <= 0:
        return []

    with log_file.open("rb") as file:
        file.seek(0, 2)
        file_size = file.tell()
        scan_size = min(file_size, MAX_LOG_SCAN_BYTES)
        start_offset = file_size - scan_size
        file.seek(start_offset)
        data = file.read(scan_size)

    if start_offset > 0:
        first_newline = data.find(b"\n")
        if first_newline < 0:
            return []
        data = data[first_newline + 1 :]

    lines = data.splitlines()
    result = []
    for line in lines[-max_lines:]:
        if len(line) > MAX_LOG_LINE_BYTES:
            continue
        result.append(line.decode("utf-8", errors="replace"))
    return result


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def load_recent_logs(limit: int = 100) -> list[dict]:
    """从日志文件中加载最近的日志

    Args:
        limit: 返回的最大日志条数

    Returns:
        日志列表
    """
    limit = max(0, min(limit, MAX_LOG_ENTRIES))
    if limit == 0:
        return []

    logs = []
    log_dir = Path("logs")

    if not log_dir.exists():
        return logs

    # 获取所有日志文件,按修改时间排序
    log_files = heapq.nlargest(MAX_LOG_FILES, log_dir.glob("app_*.log.jsonl"), key=_safe_mtime)

    # 用于生成唯一 ID 的计数器
    log_counter = 0

    # 从最新的文件开始读取
    for log_file in log_files:
        if len(logs) >= limit:
            break

        try:
            candidate_count = min(MAX_LOG_ENTRIES * 4, max(100, (limit - len(logs)) * 4))
            lines = _read_tail_lines(log_file, candidate_count)
            # 从文件末尾开始读取
            for line in reversed(lines):
                if len(logs) >= limit:
                    break
                try:
                    log_entry = json.loads(line.strip())
                    # 转换为前端期望的格式
                    # 使用时间戳 + 计数器生成唯一 ID
                    timestamp_id = log_entry.get("timestamp", "0").replace("-", "").replace(" ", "").replace(":", "")
                    formatted_log = {
                        "id": f"{timestamp_id}_{log_counter}",
                        "timestamp": log_entry.get("timestamp", ""),
                        "level": log_entry.get("level", "INFO").upper(),
                        "module": log_entry.get("logger_name", ""),
                        "message": log_entry.get("event", ""),
                    }
                    logs.append(formatted_log)
                    log_counter += 1
                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception as e:
            log_exception_type(
                logger,
                "日志文件读取失败",
                e,
                event_code="webui.logs.file_read_failed",
            )
            continue

    # 反转列表，使其按时间顺序排列（旧到新）
    return list(reversed(logs))


@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket, token: Optional[str] = Query(None)):
    """WebSocket 日志推送端点

    客户端连接后会持续接收服务器端的日志消息
    支持两种认证方式（按优先级）：
    1. query 参数 token（推荐，通过 /api/webui/ws-token 获取临时 token）
    2. Cookie 中的 maibot_session

    示例：ws://host/ws/logs?token=xxx
    """
    if not is_websocket_origin_allowed(websocket):
        logger.warning("日志 WebSocket Origin 被拒绝", event_code="webui.logs_ws.origin_rejected")
        await websocket.close(code=4003, reason="不允许的请求来源")
        return

    is_authenticated = False

    # 方式 1: 尝试验证临时 WebSocket token（推荐方式）
    if token and verify_ws_token(token):
        is_authenticated = True
        logger.debug("日志 WebSocket 临时令牌认证成功", event_code="webui.logs_ws.auth_success", auth_method="ws_token")

    # 方式 2: 尝试从 Cookie 获取 session token
    if not is_authenticated:
        cookie_token = websocket.cookies.get("maibot_session")
        if cookie_token:
            token_manager = get_token_manager()
            if token_manager.verify_token(cookie_token):
                is_authenticated = True
                logger.debug(
                    "日志 WebSocket Cookie 认证成功", event_code="webui.logs_ws.auth_success", auth_method="cookie"
                )

    if not is_authenticated:
        logger.warning("日志 WebSocket 连接被拒绝", event_code="webui.logs_ws.auth_failed")
        await websocket.close(code=4001, reason="认证失败，请重新登录")
        return

    async with _connection_lock:
        if len(active_connections) >= MAX_LOG_WS_CONNECTIONS:
            logger.warning("日志 WebSocket 连接数已达上限", event_code="webui.logs_ws.capacity_reached")
            await websocket.close(code=1013, reason="连接数过多，请稍后重试")
            return
        await websocket.accept()
        active_connections.add(websocket)
    logger.debug(
        "日志 WebSocket 客户端已连接", event_code="webui.logs_ws.connected", connection_count=len(active_connections)
    )

    # 连接建立后，立即发送历史日志
    try:
        recent_logs = load_recent_logs(limit=100)
        logger.debug("历史日志已发送到客户端", event_code="webui.logs_ws.history_sent", count=len(recent_logs))

        for log_entry in recent_logs:
            await websocket.send_text(json.dumps(log_entry, ensure_ascii=False))
    except Exception as e:
        log_exception_type(logger, "历史日志发送失败", e, event_code="webui.logs_ws.history_send_failed")

    try:
        # 保持连接，等待客户端消息或断开
        while True:
            # 接收客户端消息（用于心跳或控制指令）
            data = await websocket.receive_text()

            if len(data) > MAX_WS_CONTROL_MESSAGE_CHARS:
                active_connections.discard(websocket)
                await websocket.close(code=1009, reason="控制消息过长")
                return

            # 可以处理客户端的控制消息，例如：
            # - "ping" -> 心跳检测
            # - {"filter": "ERROR"} -> 设置日志级别过滤
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        active_connections.discard(websocket)
        logger.debug(
            "日志 WebSocket 客户端已断开",
            event_code="webui.logs_ws.disconnected",
            connection_count=len(active_connections),
        )
    except Exception as e:
        log_exception_type(logger, "日志 WebSocket 连接异常", e, event_code="webui.logs_ws.connection_failed")
        active_connections.discard(websocket)


async def broadcast_log(log_data: dict):
    """广播日志到所有连接的 WebSocket 客户端

    Args:
        log_data: 日志数据字典
    """
    if not active_connections:
        return

    # 格式化为 JSON
    message = json.dumps(log_data, ensure_ascii=False)

    # 记录需要断开的连接
    disconnected = set()

    # 广播到所有客户端
    for connection in active_connections:
        try:
            await connection.send_text(message)
        except Exception:
            # 发送失败，标记为断开
            disconnected.add(connection)

    # 清理断开的连接
    if disconnected:
        active_connections.difference_update(disconnected)
        logger.debug(
            "断开的日志 WebSocket 连接已清理", event_code="webui.logs_ws.disconnected_cleaned", count=len(disconnected)
        )
