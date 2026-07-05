import asyncio
import http
import json
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


class OneBotAdapterRuntime:
    def __init__(self) -> None:
        self._started = False
        self._start_lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task] = {}
        self._message_queue: Optional[asyncio.Queue[dict]] = None
        self._restart_event: Optional[asyncio.Event] = None
        self._websocket_server = None
        self._config_callback_registered = False

    async def start(self) -> None:
        async with self._start_lock:
            if self._started:
                logger.info("OneBot/NapCat 适配器已在运行，跳过重复启动")
                return

            self._message_queue = asyncio.Queue()
            self._restart_event = asyncio.Event()

            if not self._config_callback_registered:
                config_manager.on_config_change("napcat_server", self._on_napcat_config_change)
                self._config_callback_registered = True

            await config_manager.start_watch()

            self._started = True
            self._create_task(self._napcat_with_restart(), "onebot_adapter.napcat_server")
            self._create_task(mmc_start_com(), "onebot_adapter.mmc")
            self._create_task(self._message_process(), "onebot_adapter.message_process")
            self._create_task(check_timeout_response(), "onebot_adapter.response_timeout")
            logger.success("OneBot/NapCat 适配器插件运行时已启动")

    async def stop(self) -> None:
        async with self._start_lock:
            if not self._started and not self._tasks:
                return

            logger.info("正在停止 OneBot/NapCat 适配器插件运行时...")
            self._started = False

            await self._close_websocket_server()

            try:
                await asyncio.wait_for(mmc_stop_com(), timeout=3)
            except asyncio.TimeoutError:
                logger.debug("关闭 MMC 连接超时")
            except Exception as exc:
                logger.debug(f"关闭 MMC 连接时出现错误: {exc}")

            try:
                await config_manager.stop_watch()
            except Exception as exc:
                logger.debug(f"停止配置监控时出现错误: {exc}")

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
            logger.info("OneBot/NapCat 适配器插件运行时已停止")

    async def _on_napcat_config_change(self, old_value, new_value) -> None:
        if not self._started:
            return

        logger.warning(
            f"NapCat 配置已变更:\n"
            f"  旧配置: {old_value.host}:{old_value.port}\n"
            f"  新配置: {new_value.host}:{new_value.port}"
        )

        await self._close_websocket_server()
        if self._restart_event:
            self._restart_event.set()

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
            logger.error(f"OneBot/NapCat 适配器任务 {name} 异常退出: {exc}", exc_info=True)

    async def _close_websocket_server(self) -> None:
        if not self._websocket_server:
            return
        try:
            logger.debug("正在关闭 OneBot/NapCat WebSocket 服务器")
            self._websocket_server.close()
            await self._websocket_server.wait_closed()
            logger.debug("OneBot/NapCat WebSocket 服务器已关闭")
        except Exception as exc:
            logger.debug(f"关闭 OneBot/NapCat WebSocket 服务器时出现错误: {exc}")
        finally:
            self._websocket_server = None

    async def _message_recv(self, server_connection: Server.ServerConnection) -> None:
        if self._message_queue is None:
            raise RuntimeError("OneBot/NapCat 消息队列尚未初始化")

        try:
            await message_handler.set_server_connection(server_connection)
            asyncio.create_task(notice_handler.set_server_connection(server_connection))
            await nc_message_sender.set_server_connection(server_connection)
            async for raw_message in server_connection:
                logger.debug(f"{raw_message[:1500]}..." if len(raw_message) > 1500 else raw_message)
                decoded_raw_message: dict = json.loads(raw_message)
                post_type = decoded_raw_message.get("post_type")
                if post_type in ["meta_event", "message", "notice"]:
                    await self._message_queue.put(decoded_raw_message)
                elif post_type is None:
                    await put_response(decoded_raw_message)
        except asyncio.CancelledError:
            logger.debug("message_recv 收到取消信号，正在关闭连接")
            await server_connection.close()
            raise

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
                logger.warning(f"未知的 post_type: {post_type}")
            self._message_queue.task_done()
            await asyncio.sleep(0.05)

    def _check_napcat_server_token(self, conn, request):
        del conn
        token = global_config.napcat_server.token
        if not token or token.strip() == "":
            return None
        auth_header = request.headers.get("Authorization")
        if auth_header != f"Bearer {token}":
            return Server.Response(
                status=http.HTTPStatus.UNAUTHORIZED,
                headers=Server.Headers([("Content-Type", "text/plain")]),
                body=b"Unauthorized\n",
            )
        return None

    async def _napcat_with_restart(self) -> None:
        if self._restart_event is None:
            raise RuntimeError("OneBot/NapCat 重启事件尚未初始化")

        while self._started:
            self._restart_event.clear()
            try:
                await self._napcat_server()
            except asyncio.CancelledError:
                raise
            except OSError as exc:
                self._log_network_error(exc)
                break
            except Exception as exc:
                logger.error(f"OneBot/NapCat 服务器异常: {exc}", exc_info=True)
                break

            if not self._restart_event.is_set():
                break

            logger.info("正在重启 OneBot/NapCat WebSocket 服务器...")
            await asyncio.sleep(1)

    async def _napcat_server(self) -> None:
        logger.info("正在启动 RiyaBot-NapCat-Adapter...")
        logger.debug(f"日志等级: {global_config.debug.level}")
        logger.debug("日志文件: plugins/onebot_adapter/logs/adapter_*.log")

        async with Server.serve(
            self._message_recv,
            global_config.napcat_server.host,
            global_config.napcat_server.port,
            max_size=2**26,
            process_request=self._check_napcat_server_token,
        ) as server:
            self._websocket_server = server
            logger.success(
                f"Adapter 启动成功，监听: ws://{global_config.napcat_server.host}:{global_config.napcat_server.port}"
            )
            await server.serve_forever()

    def _log_network_error(self, exc: OSError) -> None:
        if exc.errno == 10048 or "address already in use" in str(exc).lower():
            logger.error(f"端口 {global_config.napcat_server.port} 已被占用，请检查:")
            logger.error("1. 是否有其他 RiyaBot-NapCat-Adapter 实例正在运行")
            logger.error("2. 修改 plugins/onebot_adapter/config.toml 中的 port 配置")
        else:
            logger.error(f"网络错误: {exc}")


adapter_runtime = OneBotAdapterRuntime()
