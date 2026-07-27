import asyncio
import unittest

from unittest.mock import patch

from plugins.onebot_adapter.adapter_core.recv_handler import meta_event_handler as meta_module
from plugins.onebot_adapter.adapter_core.recv_handler.meta_event_handler import MetaEventHandler


CONNECT_EVENT = {"meta_event_type": "lifecycle", "sub_type": "connect", "self_id": 10001}


def heartbeat_event(*, interval: object = 30000, online: object = True, good: object = True) -> dict:
    return {
        "meta_event_type": "heartbeat",
        "self_id": 10001,
        "status": {"online": online, "good": good},
        "interval": interval,
    }


class MetaEventHeartbeatTest(unittest.IsolatedAsyncioTestCase):
    def _handler(self) -> MetaEventHandler:
        with patch.object(
            meta_module,
            "global_config",
            type("Cfg", (), {"napcat_server": type("Srv", (), {"heartbeat_interval": 30})()})(),
        ):
            return MetaEventHandler()

    async def asyncTearDown(self) -> None:
        for task in getattr(self, "_spawned", []):
            if not task.done():
                task.cancel()

    def test_interval_from_remote_is_clamped(self) -> None:
        """心跳间隔来自 NapCat 上报，属于不可信输入：0 会让监控协程退化成忙循环。"""
        self.assertEqual(meta_module._coerce_interval(0), meta_module.DEFAULT_HEARTBEAT_INTERVAL)
        self.assertEqual(meta_module._coerce_interval(-5), meta_module.DEFAULT_HEARTBEAT_INTERVAL)
        self.assertEqual(meta_module._coerce_interval("bad"), meta_module.DEFAULT_HEARTBEAT_INTERVAL)
        self.assertEqual(meta_module._coerce_interval(None), meta_module.DEFAULT_HEARTBEAT_INTERVAL)
        self.assertEqual(meta_module._coerce_interval(float("nan")), meta_module.DEFAULT_HEARTBEAT_INTERVAL)
        self.assertEqual(meta_module._coerce_interval(0.001), meta_module.MIN_HEARTBEAT_INTERVAL)
        self.assertEqual(meta_module._coerce_interval(float("inf")), meta_module.MAX_HEARTBEAT_INTERVAL)
        self.assertEqual(meta_module._coerce_interval(15000, scale=0.001), 15.0)

    async def test_heartbeat_timeout_does_not_permanently_disable_monitoring(self) -> None:
        """超时退出后必须复位 _interval_checking，否则掉线检测只生效一次。"""
        handler = self._handler()
        handler.interval = 0.01
        handler.last_heart_beat = 0.0  # 立刻判定为超时

        await handler.handle_meta_event(CONNECT_EVENT)
        first_task = handler._heartbeat_task
        self.assertIsNotNone(first_task)
        await first_task

        self.assertFalse(handler._interval_checking)

        # 复位之后，新的心跳事件应当能重新拉起监控
        await handler.handle_meta_event(heartbeat_event(interval=10))
        second_task = handler._heartbeat_task
        self.assertIsNotNone(second_task)
        self.assertIsNot(second_task, first_task)
        second_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await second_task

    async def test_reconnect_replaces_monitor_instead_of_stacking(self) -> None:
        """重连不能叠加监控协程，且任务必须被持有强引用。"""
        handler = self._handler()
        handler.interval = 60.0

        await handler.handle_meta_event(CONNECT_EVENT)
        first_task = handler._heartbeat_task
        await asyncio.sleep(0)

        await handler.handle_meta_event(CONNECT_EVENT)
        second_task = handler._heartbeat_task

        self.assertIsNot(first_task, second_task)
        self.assertTrue(first_task.cancelled() or first_task.cancelling())
        second_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await second_task

    async def test_malformed_status_payload_is_tolerated(self) -> None:
        """status 字段来自远端，不是字典时不能直接抛 AttributeError。"""
        handler = self._handler()
        handler.interval = 60.0

        await handler.handle_meta_event({"meta_event_type": "heartbeat", "self_id": 1, "status": "online"})

        self.assertIsNone(handler._heartbeat_task)


if __name__ == "__main__":
    unittest.main()
