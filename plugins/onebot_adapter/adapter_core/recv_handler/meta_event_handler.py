from ..logger import logger
from ..config import global_config
import time
import asyncio

from . import MetaEventType


class MetaEventHandler:
    """
    处理Meta事件
    """

    def __init__(self):
        self.interval = global_config.napcat_server.heartbeat_interval
        self._interval_checking = False

    async def handle_meta_event(self, message: dict) -> None:
        event_type = message.get("meta_event_type")
        if event_type == MetaEventType.lifecycle:
            sub_type = message.get("sub_type")
            if sub_type == MetaEventType.Lifecycle.connect:
                self_id = message.get("self_id")
                self.last_heart_beat = time.time()
                logger.info(f"Bot 连接成功: self_id={self_id}")
                asyncio.create_task(self.check_heartbeat(self_id))
        elif event_type == MetaEventType.heartbeat:
            self_id = message.get("self_id")
            status = message.get("status", {})
            is_online = status.get("online", False)
            is_good = status.get("good", False)

            if is_online and is_good:
                # 正常心跳
                if not self._interval_checking:
                    asyncio.create_task(self.check_heartbeat(self_id))
                self.last_heart_beat = time.time()
                self.interval = message.get("interval", 30000) / 1000
            else:
                if not is_online:
                    logger.error(f"Bot 离线: self_id={self_id}, online=false")
                elif not is_good:
                    logger.warning(f"Bot 状态异常: self_id={self_id}, good=false")
                else:
                    logger.warning(f"NapCat 心跳状态异常: self_id={self_id}")

    async def check_heartbeat(self, id: int) -> None:
        self._interval_checking = True
        while True:
            now_time = time.time()
            if now_time - self.last_heart_beat > self.interval * 2:
                logger.error(f"Bot 心跳超时: self_id={id}, timeout_seconds={self.interval * 2:.1f}")
                break
            else:
                logger.debug(f"Bot 心跳正常: self_id={id}")
            await asyncio.sleep(self.interval)


meta_event_handler = MetaEventHandler()
