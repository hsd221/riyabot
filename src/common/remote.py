import asyncio

import aiohttp
import platform

from src.common.logger import get_logger, hash_id
from src.common.tcp_connector import get_tcp_connector
from src.config.config import global_config
from src.manager.async_task_manager import AsyncTask
from src.manager.local_store_manager import local_storage

logger = get_logger("remote")

TELEMETRY_SERVER_URL = "http://hyybuth.xyz:10058"
"""遥测服务地址"""


class TelemetryHeartBeatTask(AsyncTask):
    HEARTBEAT_INTERVAL = 300

    def __init__(self):
        super().__init__(task_name="Telemetry Heart Beat Task", run_interval=self.HEARTBEAT_INTERVAL)
        self.server_url = TELEMETRY_SERVER_URL
        """遥测服务地址"""

        self.client_uuid: str | None = local_storage["mmc_uuid"] if "mmc_uuid" in local_storage else None  # type: ignore
        """客户端UUID"""

        self.info_dict = self._get_sys_info()
        """系统信息字典"""

    @staticmethod
    def _get_sys_info() -> dict[str, str]:
        """获取系统信息"""
        info_dict = {
            "os_type": "Unknown",
            "py_version": platform.python_version(),
            "mmc_version": global_config.MMC_VERSION,
        }

        match platform.system():
            case "Windows":
                info_dict["os_type"] = "Windows"
            case "Linux":
                info_dict["os_type"] = "Linux"
            case "Darwin":
                info_dict["os_type"] = "macOS"
            case _:
                info_dict["os_type"] = "Unknown"

        return info_dict

    async def _req_uuid(self) -> bool:
        """
        向服务端请求UUID（不应在已存在UUID的情况下调用，会覆盖原有的UUID）
        """

        if "deploy_time" not in local_storage:
            logger.error("本地存储缺少部署时间，无法请求 UUID", event_code="telemetry.uuid.deploy_time_missing")
            return False

        try_count: int = 0
        while True:
            # 如果不存在，则向服务端请求一个新的UUID（注册客户端）
            logger.info("开始请求遥测 UUID", event_code="telemetry.uuid.request_started")

            try:
                async with aiohttp.ClientSession(connector=await get_tcp_connector()) as session:
                    async with session.post(
                        f"{TELEMETRY_SERVER_URL}/stat/reg_client",
                        json={"deploy_time": local_storage["deploy_time"]},
                        timeout=aiohttp.ClientTimeout(total=5),  # 设置超时时间为5秒
                    ) as response:
                        logger.debug(
                            "遥测 UUID 注册响应",
                            event_code="telemetry.uuid.response",
                            status_code=response.status,
                            deploy_time_hash=hash_id(local_storage["deploy_time"]),  # type: ignore
                        )

                        if response.status == 200:
                            data = await response.json()
                            if client_id := data.get("mmc_uuid"):
                                # 将UUID存储到本地
                                local_storage["mmc_uuid"] = client_id
                                self.client_uuid = client_id
                                logger.info(
                                    "遥测 UUID 获取完成",
                                    event_code="telemetry.uuid.request_completed",
                                    uuid_hash=hash_id(self.client_uuid),
                                )
                                return True  # 成功获取UUID，返回True
                            else:
                                logger.error("遥测 UUID 响应缺少 UUID", event_code="telemetry.uuid.invalid_response")
                        else:
                            response_text = await response.text()
                            logger.error(
                                "遥测 UUID 请求失败，主程序继续运行",
                                event_code="telemetry.uuid.request_failed",
                                status_code=response.status,
                                response=response_text,
                            )
            except Exception as e:
                logger.warning(
                    "遥测 UUID 请求异常，主程序继续运行",
                    event_code="telemetry.uuid.request_exception",
                    error_type=type(e).__name__,
                    error=str(e) or "未知错误",
                    exc_info=True,
                )

            # 请求失败，重试次数+1
            try_count += 1
            if try_count > 3:
                # 如果超过3次仍然失败，则退出
                logger.error("遥测 UUID 获取失败，已达到最大重试次数", event_code="telemetry.uuid.retries_exhausted")
                return False
            else:
                # 如果可以重试，等待后继续（指数退避）
                logger.info("遥测 UUID 将重试", event_code="telemetry.uuid.retry_scheduled", delay_seconds=4**try_count)
                await asyncio.sleep(4**try_count)

    async def _send_heartbeat(self):
        """向服务器发送心跳"""
        headers = {
            "Client-UUID": self.client_uuid,
            "User-Agent": f"HeartbeatClient/{self.client_uuid[:8]}",  # type: ignore
        }

        logger.debug(
            "遥测心跳开始发送",
            event_code="telemetry.heartbeat.send_started",
            server_url=self.server_url,
            uuid_hash=hash_id(self.client_uuid),
        )

        try:
            async with aiohttp.ClientSession(connector=await get_tcp_connector()) as session:
                async with session.post(
                    f"{self.server_url}/stat/client_heartbeat",
                    headers=headers,
                    json=self.info_dict,
                    timeout=aiohttp.ClientTimeout(total=5),  # 设置超时时间为5秒
                ) as response:
                    logger.debug("遥测心跳响应", event_code="telemetry.heartbeat.response", status_code=response.status)

                    # 处理响应
                    if 200 <= response.status < 300:
                        # 成功
                        logger.debug(
                            "遥测心跳发送完成", event_code="telemetry.heartbeat.sent", status_code=response.status
                        )
                    elif response.status == 403:
                        # 403 Forbidden
                        logger.warning(
                            "遥测心跳被拒绝，UUID 将重置",
                            event_code="telemetry.heartbeat.forbidden",
                            status_code=response.status,
                            uuid_hash=hash_id(self.client_uuid),
                        )
                        self.client_uuid = None
                        del local_storage["mmc_uuid"]  # 删除本地存储的UUID
                    else:
                        # 其他错误
                        response_text = await response.text()
                        logger.warning(
                            "遥测心跳发送失败，主程序继续运行",
                            event_code="telemetry.heartbeat.failed",
                            status_code=response.status,
                            response=response_text,
                        )
        except Exception as e:
            logger.warning(
                "遥测心跳发送异常，主程序继续运行",
                event_code="telemetry.heartbeat.exception",
                error_type=type(e).__name__,
                error=str(e) or "未知错误",
                exc_info=True,
            )

    async def run(self):
        # 发送心跳
        if global_config.telemetry.enable:
            if self.client_uuid is None and not await self._req_uuid():
                logger.warning(
                    "遥测 UUID 不可用，跳过本次心跳", event_code="telemetry.heartbeat.skipped_uuid_unavailable"
                )
                return

            await self._send_heartbeat()
