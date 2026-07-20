import asyncio
import http
import ipaddress
import json
import secrets
import time
from typing import Optional

import websockets as Server

from .config import config_manager, global_config
from .logger import logger
from .mmc_com_layer import mmc_start_com, mmc_stop_com
from .recv_handler.message_handler import message_handler
from .recv_handler.meta_event_handler import meta_event_handler
from .recv_handler.notice_handler import notice_handler
from .response_pool import check_timeout_response, put_response
from .send_handler.nc_sending import nc_message_sender
from .utils import get_self_info
from src.config.config import global_config as core_global_config
from src.services.adapter_identity import get_adapter_identity_registry


ADAPTER_INSTANCE_ID = "onebot_default"
ADAPTER_PLATFORM = "qq"
NAPCAT_SERVER_TASK_NAME = "onebot_adapter.napcat_server"
MAX_ACCOUNT_ID_LENGTH = 128
MAX_NICKNAME_LENGTH = 256


def _is_loopback_host(host: str) -> bool:
    """Only explicit loopback bind addresses may run without a token."""
    normalized = host.strip().lower().rstrip(".")
    if normalized == "localhost":
        return True
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    normalized = normalized.split("%", maxsplit=1)[0]
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _plain_response(status_code: http.HTTPStatus, body: bytes) -> Server.Response:
    return Server.Response(
        status_code=status_code,
        reason_phrase=status_code.phrase,
        headers=Server.Headers([("Content-Type", "text/plain")]),
        body=body,
    )


class OneBotAdapterRuntime:
    def __init__(self) -> None:
        self._started = False
        self._start_lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task] = {}
        self._message_queue: Optional[asyncio.Queue[dict]] = None
        self._restart_event: Optional[asyncio.Event] = None
        self._websocket_server = None
        self._config_callback_registered = False
        self._active_connections: set[int] = set()
        self._identity_tasks: dict[int, asyncio.Task] = {}
        self._identity_retry_after: dict[int, float] = {}
        self._connected_at: float | None = None
        self._last_event_at: float | None = None
        self._last_error: str | None = None
        self._fallback_bot_identity: tuple[object, object, object] | None = None

    async def start(self) -> None:
        async with self._start_lock:
            if self._started:
                logger.info("OneBot/NapCat 适配器已在运行，跳过重复启动")
                return

            self._message_queue = asyncio.Queue()
            self._restart_event = asyncio.Event()
            self._last_error = None

            if not self._config_callback_registered:
                config_manager.on_config_change("napcat_server", self._on_napcat_config_change)
                self._config_callback_registered = True

            await config_manager.start_watch()

            self._started = True
            self._create_task(self._napcat_with_restart(), NAPCAT_SERVER_TASK_NAME)
            self._create_task(mmc_start_com(), "onebot_adapter.mmc")
            self._create_task(self._message_process(), "onebot_adapter.message_process")
            self._create_task(check_timeout_response(), "onebot_adapter.response_timeout")
            logger.info("OneBot/NapCat 适配器插件运行时已启动")

    async def stop(self) -> None:
        async with self._start_lock:
            if not self._started and not self._tasks:
                return

            logger.info("OneBot/NapCat 适配器运行时开始停止")
            self._started = False

            await self._close_websocket_server()

            try:
                await asyncio.wait_for(mmc_stop_com(), timeout=3)
            except asyncio.TimeoutError:
                logger.debug("关闭 MMC 连接超时")
            except Exception as exc:
                logger.debug(f"关闭 MMC 连接时出现错误: error_type={type(exc).__name__}")

            try:
                await config_manager.stop_watch()
            except Exception as exc:
                logger.debug(f"停止配置监控时出现错误: error_type={type(exc).__name__}")

            tasks = [task for task in self._tasks.values() if not task.done()]
            for task in tasks:
                task.cancel()

            if tasks:
                try:
                    await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5)
                except asyncio.TimeoutError:
                    logger.warning("等待 OneBot/NapCat 适配器任务取消超时")

            self._tasks.clear()
            self._message_queue = None
            self._restart_event = None
            self._active_connections.clear()
            self._identity_retry_after.clear()
            self._connected_at = None
            self._last_event_at = None
            get_adapter_identity_registry().unregister(ADAPTER_INSTANCE_ID)
            self._restore_core_identity()
            logger.info("OneBot/NapCat 适配器插件运行时已停止")

    async def _on_napcat_config_change(self, old_value, new_value) -> None:
        if not self._started:
            return

        logger.warning("NapCat 配置已变更，准备重启连接")

        await self._close_websocket_server()
        if self._restart_event:
            self._restart_event.set()
            napcat_task = self._tasks.get(NAPCAT_SERVER_TASK_NAME)
            if napcat_task is None or napcat_task.done():
                self._create_task(self._napcat_with_restart(), NAPCAT_SERVER_TASK_NAME)

    def _create_task(self, coro, name: str) -> None:
        task = asyncio.create_task(coro, name=name)
        self._tasks[name] = task
        task.add_done_callback(lambda done_task: self._task_done_callback(name, done_task))

    def _task_done_callback(self, name: str, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc:
            self._last_error = type(exc).__name__
            logger.error(f"OneBot/NapCat 适配器任务异常退出: task={name} error_type={type(exc).__name__}")

    def _connection_opened(self, server_connection: object) -> None:
        connection_id = id(server_connection)
        if not self._active_connections:
            self._connected_at = time.time()
            self._fallback_bot_identity = (
                core_global_config.bot.platform,
                core_global_config.bot.qq_account,
                core_global_config.bot.nickname,
            )
        self._active_connections.add(connection_id)

    def _connection_closed(self, server_connection: object) -> None:
        connection_id = id(server_connection)
        self._active_connections.discard(connection_id)
        identity_task = self._identity_tasks.pop(connection_id, None)
        self._identity_retry_after.pop(connection_id, None)
        if identity_task and not identity_task.done():
            identity_task.cancel()
        if not self._active_connections:
            self._connected_at = None
            get_adapter_identity_registry().unregister(ADAPTER_INSTANCE_ID)
            self._restore_core_identity()

    def _restore_core_identity(self) -> None:
        if self._fallback_bot_identity is None:
            return
        (
            core_global_config.bot.platform,
            core_global_config.bot.qq_account,
            core_global_config.bot.nickname,
        ) = self._fallback_bot_identity
        self._fallback_bot_identity = None

    def _register_identity(self, account_id: object, nickname: object = "") -> None:
        normalized_account_id = self._normalize_identity_text(account_id, MAX_ACCOUNT_ID_LENGTH)
        if not normalized_account_id:
            return
        registry = get_adapter_identity_registry()
        normalized_nickname = self._normalize_identity_text(nickname, MAX_NICKNAME_LENGTH)
        current_identity = registry.get(ADAPTER_INSTANCE_ID)
        if (
            not normalized_nickname
            and current_identity
            and current_identity.adapter_id == ADAPTER_INSTANCE_ID
            and current_identity.account_id == normalized_account_id
        ):
            normalized_nickname = current_identity.nickname

        registry.register(
            ADAPTER_INSTANCE_ID,
            ADAPTER_PLATFORM,
            normalized_account_id,
            normalized_nickname,
        )
        core_global_config.bot.platform = ADAPTER_PLATFORM
        core_global_config.bot.qq_account = normalized_account_id
        if normalized_nickname:
            core_global_config.bot.nickname = normalized_nickname

    @staticmethod
    def _normalize_identity_text(value: object, max_length: int) -> str:
        normalized = str(value or "").strip()
        if len(normalized) > max_length or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            return ""
        return normalized

    async def _discover_identity(self, server_connection: object, fallback_account_id: object = "") -> None:
        connection_id = id(server_connection)
        if connection_id not in self._active_connections:
            return
        profile = await get_self_info(server_connection)  # type: ignore[arg-type]
        if connection_id not in self._active_connections:
            return
        profile = profile if isinstance(profile, dict) else {}
        self._register_identity(
            profile.get("user_id") or fallback_account_id,
            profile.get("nickname") or "",
        )

    def _schedule_identity_discovery(self, server_connection: object, fallback_account_id: object) -> None:
        connection_id = id(server_connection)
        normalized_account_id = str(fallback_account_id or "").strip()
        current_identity = get_adapter_identity_registry().get(ADAPTER_INSTANCE_ID)
        if (
            current_identity
            and current_identity.adapter_id == ADAPTER_INSTANCE_ID
            and current_identity.account_id == normalized_account_id
            and current_identity.nickname
        ):
            return
        if time.monotonic() < self._identity_retry_after.get(connection_id, 0):
            return
        current_task = self._identity_tasks.get(connection_id)
        if current_task and not current_task.done():
            return

        task = asyncio.create_task(
            self._discover_identity(server_connection, fallback_account_id),
            name=f"onebot_adapter.identity.{connection_id}",
        )
        self._identity_tasks[connection_id] = task

        def clear_finished_task(done_task: asyncio.Task) -> None:
            if self._identity_tasks.get(connection_id) is done_task:
                self._identity_tasks.pop(connection_id, None)
            if done_task.cancelled():
                return
            try:
                error = done_task.exception()
            except asyncio.CancelledError:
                return
            if error:
                logger.warning(f"获取 OneBot 账号资料失败: error_type={type(error).__name__}")
            identity = get_adapter_identity_registry().get(ADAPTER_INSTANCE_ID)
            if identity and identity.nickname:
                self._identity_retry_after.pop(connection_id, None)
            else:
                self._identity_retry_after[connection_id] = time.monotonic() + 60

        task.add_done_callback(clear_finished_task)

    def get_status(self) -> dict:
        if not self._started:
            status = "stopped"
        elif self._active_connections:
            status = "connected"
        elif self._websocket_server is not None:
            status = "listening"
        elif self._last_error:
            status = "error"
        else:
            status = "starting"

        identity = get_adapter_identity_registry().get(ADAPTER_INSTANCE_ID)
        return {
            "status": status,
            "started": self._started,
            "connected": bool(self._active_connections),
            "identity": identity.to_public_dict() if identity else None,
            "connection": {
                "host": str(global_config.napcat_server.host),
                "port": int(global_config.napcat_server.port),
            },
            "connected_at": self._connected_at,
            "last_event_at": self._last_event_at,
            "last_error": self._last_error,
        }

    async def _close_websocket_server(self) -> None:
        if not self._websocket_server:
            return
        try:
            logger.debug("正在关闭 OneBot/NapCat WebSocket 服务器")
            self._websocket_server.close()
            await self._websocket_server.wait_closed()
            logger.debug("OneBot/NapCat WebSocket 服务器已关闭")
        except Exception as exc:
            logger.debug(f"关闭 OneBot/NapCat WebSocket 服务器时出现错误: error_type={type(exc).__name__}")
        finally:
            self._websocket_server = None

    async def _message_recv(self, server_connection: Server.ServerConnection) -> None:
        if self._message_queue is None:
            raise RuntimeError("OneBot/NapCat 消息队列尚未初始化")

        self._connection_opened(server_connection)
        try:
            await message_handler.set_server_connection(server_connection)
            asyncio.create_task(notice_handler.set_server_connection(server_connection))
            await nc_message_sender.set_server_connection(server_connection)
            self._schedule_identity_discovery(server_connection, "")
            async for raw_message in server_connection:
                decoded_raw_message: dict = json.loads(raw_message)
                self._last_event_at = time.time()
                self_id = decoded_raw_message.get("self_id")
                if self_id:
                    self._register_identity(self_id)
                    self._schedule_identity_discovery(server_connection, self_id)
                post_type = decoded_raw_message.get("post_type")
                if post_type in ["meta_event", "message", "notice"]:
                    logger.debug(f"收到 OneBot/NapCat 事件: post_type={post_type}")
                    await self._message_queue.put(decoded_raw_message)
                elif post_type is None:
                    logger.debug("收到 OneBot/NapCat 响应")
                    await put_response(decoded_raw_message)
        except asyncio.CancelledError:
            logger.debug("message_recv 收到取消信号，正在关闭连接")
            await server_connection.close()
            raise
        finally:
            self._connection_closed(server_connection)

    async def _message_process(self) -> None:
        if self._message_queue is None:
            raise RuntimeError("OneBot/NapCat 消息队列尚未初始化")

        while True:
            message = await self._message_queue.get()
            post_type = message.get("post_type")
            if post_type == "message":
                await message_handler.handle_raw_message(message)
            elif post_type == "meta_event":
                await meta_event_handler.handle_meta_event(message)
            elif post_type == "notice":
                await notice_handler.handle_notice(message)
            else:
                logger.warning("收到未知的 OneBot/NapCat 事件类型")
            self._message_queue.task_done()
            await asyncio.sleep(0.05)

    def _check_napcat_server_token(self, conn, request):
        del conn
        token = global_config.napcat_server.token
        if not token or token.strip() == "":
            if not _is_loopback_host(str(global_config.napcat_server.host)):
                return _plain_response(http.HTTPStatus.FORBIDDEN, b"Forbidden\n")
            return None
        auth_header = request.headers.get("Authorization") or ""
        expected = f"Bearer {token}"
        if not secrets.compare_digest(auth_header.encode("utf-8"), expected.encode("utf-8")):
            return _plain_response(http.HTTPStatus.UNAUTHORIZED, b"Unauthorized\n")
        return None

    async def _napcat_with_restart(self) -> None:
        if self._restart_event is None:
            raise RuntimeError("OneBot/NapCat 重启事件尚未初始化")

        while self._started:
            self._restart_event.clear()
            self._last_error = None
            try:
                await self._napcat_server()
            except asyncio.CancelledError:
                raise
            except OSError as exc:
                self._last_error = type(exc).__name__
                self._log_network_error(exc)
                break
            except Exception as exc:
                self._last_error = type(exc).__name__
                logger.error(f"OneBot/NapCat 服务器异常: error_type={type(exc).__name__}")
                break

            if not self._restart_event.is_set():
                break

            logger.info("OneBot/NapCat WebSocket 服务器开始重启")
            await asyncio.sleep(1)

    async def _napcat_server(self) -> None:
        logger.info("OneBot/NapCat WebSocket 服务器开始启动")
        logger.debug(f"日志等级: {global_config.debug.level}")
        logger.debug("日志文件: plugins/onebot_adapter/logs/adapter_*.log")

        host = str(global_config.napcat_server.host)
        token = global_config.napcat_server.token
        if (not token or token.strip() == "") and not _is_loopback_host(host):
            logger.error("NapCat WebSocket 非回环监听必须配置访问令牌")
            raise RuntimeError("NapCat WebSocket 非回环监听必须配置访问令牌")

        async with Server.serve(
            self._message_recv,
            host,
            global_config.napcat_server.port,
            max_size=2**26,
            process_request=self._check_napcat_server_token,
        ) as server:
            self._websocket_server = server
            logger.info("Adapter 启动成功")
            await server.serve_forever()

    def _log_network_error(self, exc: OSError) -> None:
        if exc.errno == 10048 or "address already in use" in str(exc).lower():
            logger.error(f"端口已被占用: port={global_config.napcat_server.port}")
        else:
            logger.error(f"网络错误: error_type={type(exc).__name__}")


adapter_runtime = OneBotAdapterRuntime()
