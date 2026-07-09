import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.manager import async_task_manager as async_task_manager_module
from src.manager.async_task_manager import AsyncTask, AsyncTaskManager
from src.manager.local_store_manager import LocalStoreManager


class CountingTask(AsyncTask):
    def __init__(self, task_name: str = "counting", run_interval: int = 0, wait_before_start: int = 0):
        super().__init__(task_name=task_name, run_interval=run_interval, wait_before_start=wait_before_start)
        self.run_count = 0
        self.run_event = asyncio.Event()

    async def run(self):
        self.run_count += 1
        self.run_event.set()


class BlockingTask(AsyncTask):
    def __init__(self, task_name: str = "blocking"):
        super().__init__(task_name=task_name)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self):
        self.started.set()
        await self.release.wait()


class AsyncTaskManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_task_waits_before_start_and_repeats_until_abort_flag_is_set(self) -> None:
        task = CountingTask(wait_before_start=2, run_interval=3)
        abort_flag = asyncio.Event()
        sleep_calls: list[int] = []

        async def fake_sleep(delay):
            sleep_calls.append(delay)
            if delay == 3:
                abort_flag.set()

        with patch.object(async_task_manager_module.asyncio, "sleep", side_effect=fake_sleep):
            await task.start_task(abort_flag)

        self.assertEqual(task.run_count, 1)
        self.assertEqual(sleep_calls, [2, 3])

    async def test_base_run_default_is_noop(self) -> None:
        task = CountingTask()

        self.assertIsNone(await AsyncTask.run(task))

    async def test_async_task_runs_once_and_is_removed_after_completion(self) -> None:
        manager = AsyncTaskManager()
        task = CountingTask()
        finished = asyncio.Event()

        await manager.add_task(task, call_back=lambda _task: finished.set())
        await asyncio.wait_for(finished.wait(), timeout=1)
        await asyncio.sleep(0)

        self.assertEqual(task.run_count, 1)
        self.assertEqual(manager.tasks, {})

    async def test_add_task_rejects_non_async_task(self) -> None:
        manager = AsyncTaskManager()

        with self.assertRaises(TypeError):
            await manager.add_task(object())

    async def test_duplicate_task_name_cancels_old_task_and_replaces_it(self) -> None:
        manager = AsyncTaskManager()
        first = BlockingTask("same")
        second = CountingTask("same")
        finished = asyncio.Event()

        await manager.add_task(first)
        await asyncio.wait_for(first.started.wait(), timeout=1)
        await manager.add_task(second, call_back=lambda _task: finished.set())
        await asyncio.wait_for(finished.wait(), timeout=1)
        await asyncio.sleep(0)

        self.assertTrue(first.started.is_set())
        self.assertEqual(second.run_count, 1)
        self.assertEqual(manager.tasks, {})

    async def test_duplicate_task_replacement_handles_timeout_and_wait_errors(self) -> None:
        manager = AsyncTaskManager()
        manager.tasks["same"] = SimpleNamespace(cancel=Mock(), get_name=lambda: "same")

        def fake_create_task(coro):
            coro.close()
            return Mock(set_name=Mock(), add_done_callback=Mock())

        with (
            patch.object(async_task_manager_module.asyncio, "wait_for", side_effect=asyncio.TimeoutError),
            patch.object(async_task_manager_module.asyncio, "create_task", side_effect=fake_create_task),
        ):
            await manager.add_task(CountingTask("same"))

        manager.tasks["same"] = SimpleNamespace(cancel=Mock(), get_name=lambda: "same")
        with (
            patch.object(async_task_manager_module.asyncio, "wait_for", side_effect=RuntimeError("wait down")),
            patch.object(async_task_manager_module.asyncio, "create_task", side_effect=fake_create_task),
        ):
            await manager.add_task(CountingTask("same"))

    async def test_finish_callbacks_observe_success_cancellation_and_failure(self) -> None:
        success_task = Mock(get_name=Mock(return_value="success"), result=Mock(return_value=None))
        AsyncTaskManager._default_finish_call_back(success_task)
        success_task.result.assert_called_once_with()

        cancelled_task = Mock(get_name=Mock(return_value="cancelled"), result=Mock(side_effect=asyncio.CancelledError))
        AsyncTaskManager._default_finish_call_back(cancelled_task)

        failing_task = Mock(get_name=Mock(return_value="failing"), result=Mock(side_effect=RuntimeError("boom")))
        AsyncTaskManager._default_finish_call_back(failing_task)

    def test_remove_task_callback_warns_when_task_is_unknown(self) -> None:
        manager = AsyncTaskManager()
        task = Mock(get_name=Mock(return_value="missing"))

        manager._remove_task_call_back(task)

        self.assertEqual(manager.tasks, {})

    async def test_stop_and_wait_all_tasks_cancels_running_tasks_and_clears_abort_flag(self) -> None:
        manager = AsyncTaskManager()
        task = BlockingTask("blocking")

        await manager.add_task(task)
        await asyncio.wait_for(task.started.wait(), timeout=1)
        self.assertEqual(manager.get_tasks_status(), {"blocking": {"status": "running"}})

        await manager.stop_and_wait_all_tasks()

        self.assertEqual(manager.tasks, {})
        self.assertFalse(manager.abort_flag.is_set())

    async def test_stop_and_wait_all_tasks_handles_cancel_timeout_and_task_errors(self) -> None:
        manager = AsyncTaskManager()
        done_task = SimpleNamespace(done=Mock(return_value=True), cancel=Mock(), get_name=lambda: "done")
        cancel_raising_task = SimpleNamespace(
            done=Mock(return_value=False), cancel=Mock(side_effect=RuntimeError("cancel down")), get_name=lambda: "bad"
        )
        running_task = SimpleNamespace(done=Mock(return_value=False), cancel=Mock(), get_name=lambda: "running")
        manager.tasks = {"done": done_task, "bad": cancel_raising_task, "running": running_task}

        with patch.object(async_task_manager_module.asyncio, "wait_for", side_effect=asyncio.TimeoutError):
            await manager.stop_and_wait_all_tasks()

        done_task.cancel.assert_not_called()
        cancel_raising_task.cancel.assert_called_once_with()
        running_task.cancel.assert_called_once_with()
        self.assertEqual(manager.tasks, {})
        self.assertFalse(manager.abort_flag.is_set())

        manager.tasks = {"running": running_task}
        with patch.object(async_task_manager_module.asyncio, "wait_for", side_effect=RuntimeError("task down")):
            await manager.stop_and_wait_all_tasks()

        manager.tasks = {"running": running_task}
        with patch.object(async_task_manager_module.asyncio, "wait_for", return_value=None):
            await manager.stop_and_wait_all_tasks()

    async def test_debug_task_status_reports_done_cancelled_failed_success_and_running_tasks(self) -> None:
        manager = AsyncTaskManager()
        manager.abort_flag.set()
        manager.tasks = {
            "done-ok": Mock(
                done=Mock(return_value=True), cancelled=Mock(return_value=False), exception=Mock(return_value=None)
            ),
            "done-cancelled": Mock(done=Mock(return_value=True), cancelled=Mock(return_value=True)),
            "done-failed": Mock(
                done=Mock(return_value=True),
                cancelled=Mock(return_value=False),
                exception=Mock(return_value=RuntimeError("boom")),
            ),
            "running": Mock(done=Mock(return_value=False)),
        }

        manager.debug_task_status()


class LocalStoreManagerTest(unittest.TestCase):
    def test_local_store_creates_file_and_persists_supported_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "nested" / "store.json"
            store = LocalStoreManager(str(store_path))

            self.assertTrue(store_path.exists())
            self.assertNotIn("missing", store)

            store["string"] = "value"
            store["list"] = [1, 2]
            store["dict"] = {"enabled": True}
            store["number"] = 3
            store["flag"] = False

            reloaded = LocalStoreManager(str(store_path))
            self.assertEqual(reloaded["string"], "value")
            self.assertEqual(reloaded["list"], [1, 2])
            self.assertEqual(reloaded["dict"], {"enabled": True})
            self.assertEqual(reloaded["number"], 3)
            self.assertFalse(reloaded["flag"])

    def test_local_store_delete_existing_and_missing_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "store.json"
            store = LocalStoreManager(str(store_path))
            store["key"] = "value"

            del store["key"]
            del store["missing"]

            self.assertIsNone(store["key"])
            self.assertEqual(json.loads(store_path.read_text(encoding="utf-8")), {})

    def test_invalid_json_store_is_rebuilt_to_empty_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "store.json"
            store_path.write_text("{invalid", encoding="utf-8")

            store = LocalStoreManager(str(store_path))

            self.assertEqual(store.store, {})
            self.assertEqual(json.loads(store_path.read_text(encoding="utf-8")), {})

    def test_local_store_accepts_filename_without_directory_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                store = LocalStoreManager("store.json")
                store["key"] = "value"

                self.assertEqual(json.loads(Path("store.json").read_text(encoding="utf-8")), {"key": "value"})
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
