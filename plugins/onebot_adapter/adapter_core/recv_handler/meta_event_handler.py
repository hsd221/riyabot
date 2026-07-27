from ..logger import logger
from ..config import global_config
import time
import asyncio
from typing import Optional

from . import MetaEventType

# NapCat 上报的心跳间隔属于远端输入，必须钳制到合理区间：
# interval=0 会让监控协程退化成 100% CPU 的忙循环，过大的值又会让掉线检测形同虚设。
MIN_HEARTBEAT_INTERVAL = 1.0
MAX_HEARTBEAT_INTERVAL = 3600.0
DEFAULT_HEARTBEAT_INTERVAL = 30.0


def _coerce_interval(
    value: object,
    *,
    scale: float = 1.0,
    fallback: float = DEFAULT_HEARTBEAT_INTERVAL,
) -> float:
    """把上报的心跳间隔转成安全的秒数，非法值回退到默认间隔"""
    try:
        interval = float(value) * scale  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    # NaN 自身不等于自身
    if interval != interval or interval <= 0:
        return fallback
    return min(max(interval, MIN_HEARTBEAT_INTERVAL), MAX_HEARTBEAT_INTERVAL)


class MetaEventHandler:
    """
    处理Meta事件
    """

    def __init__(self):
        self.interval = _coerce_interval(global_config.napcat_server.heartbeat_interval)
        self._interval_checking = False
        # 事件循环只弱引用任务，丢弃返回值会让心跳监控在运行途中被回收
        self._heartbeat_task: Optional[asyncio.Task] = None
        self.last_heart_beat = time.time()

    def _restart_heartbeat_monitor(self, self_id) -> None:
        """重启心跳监控，保证任意时刻只有一个监控协程且始终持有强引用"""
        task = self._heartbeat_task
        if task is not None and not task.done():
            task.cancel()
        self._heartbeat_task = asyncio.create_task(self.check_heartbeat(self_id))

    async def handle_meta_event(self, message: dict) -> None:
        event_type = message.get("meta_event_type")
        if event_type == MetaEventType.lifecycle:
            sub_type = message.get("sub_type")
            if sub_type == MetaEventType.Lifecycle.connect:
                self_id = message.get("self_id")
                self.last_heart_beat = time.time()
                logger.info(f"Bot 连接成功: self_id={self_id}")
                self._restart_heartbeat_monitor(self_id)
        elif event_type == MetaEventType.heartbeat:
            self_id = message.get("self_id")
            status = message.get("status", {})
            if not isinstance(status, dict):
                status = {}
            is_online = status.get("online", False)
            is_good = status.get("good", False)

            if is_online and is_good:
                # 正常心跳
                self.last_heart_beat = time.time()
                self.interval = _coerce_interval(message.get("interval"), scale=0.001)
                if not self._interval_checking:
                    self._restart_heartbeat_monitor(self_id)
            else:
                if not is_online:
                    logger.error(f"Bot 离线: self_id={self_id}, online=false")
                elif not is_good:
                    logger.warning(f"Bot 状态异常: self_id={self_id}, good=false")
                else:
                    logger.warning(f"NapCat 心跳状态异常: self_id={self_id}")

    async def check_heartbeat(self, self_id) -> None:
        self._interval_checking = True
        try:
            while True:
                if time.time() - self.last_heart_beat > self.interval * 2:
                    logger.error(f"Bot 心跳超时: self_id={self_id}, timeout_seconds={self.interval * 2:.1f}")
                    break
                logger.debug(f"Bot 心跳正常: self_id={self_id}")
                await asyncio.sleep(self.interval)
        finally:
            # 必须复位：否则一次心跳超时之后该标志永远为 True，
            # 心跳分支再也不会重启监控，掉线检测就此彻底失效。
            self._interval_checking = False


meta_event_handler = MetaEventHandler()
