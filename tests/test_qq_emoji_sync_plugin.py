import base64
import hashlib
import io
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from plugins.qq_emoji_sync.plugin import QQEmojiSyncCommand
from plugins.qq_emoji_sync.sync_service import QQEmojiSyncError, QQEmojiSyncService, SyncResult, _download_image


def make_image_base64(color: str = "red", image_format: str = "PNG") -> tuple[str, bytes, str]:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color=color).save(buffer, format=image_format)
    image_bytes = buffer.getvalue()
    return (
        base64.b64encode(image_bytes).decode("ascii"),
        image_bytes,
        hashlib.md5(image_bytes, usedforsecurity=False).hexdigest(),
    )


class QQEmojiSyncServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_default_downloader_requires_https_for_the_full_redirect_chain(self) -> None:
        with patch(
            "plugins.onebot_adapter.adapter_core.utils.get_image_base64",
            new=AsyncMock(return_value="encoded-image"),
        ) as get_image_base64:
            result = await _download_image("https://example.com/image.png")

        self.assertEqual(result, "encoded-image")
        get_image_base64.assert_awaited_once_with("https://example.com/image.png", https_only=True)

    async def test_sync_queues_valid_images_and_skips_registered_duplicates(self) -> None:
        registered_base64, _, registered_hash = make_image_base64("red")
        new_base64, new_bytes, new_hash = make_image_base64("blue")
        call_action = AsyncMock(
            return_value={
                "status": "ok",
                "retcode": 0,
                "data": ["https://example.com/registered.png", "https://example.com/new.png"],
            }
        )

        async def download_image(url: str) -> str:
            return registered_base64 if url.endswith("registered.png") else new_base64

        async def registered_hash_exists(image_hash: str) -> bool:
            return image_hash == registered_hash

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = QQEmojiSyncService(
                call_action=call_action,
                download_image=download_image,
                registered_hash_exists=registered_hash_exists,
                pending_dir=Path(tmp_dir),
                max_pending=10,
            )

            result = await service.sync(2)

            self.assertEqual(
                result,
                SyncResult(requested=2, fetched=2, queued=1, duplicates=1, rejected=0, failed=0),
            )
            queued_file = Path(tmp_dir) / f"qq_{new_hash}.png"
            self.assertEqual(queued_file.read_bytes(), new_bytes)

        call_action.assert_awaited_once_with("fetch_custom_face", {"count": 2})

    async def test_sync_accepts_a_large_but_bounded_collection(self) -> None:
        call_action = AsyncMock(return_value={"status": "ok", "retcode": 0, "data": []})
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = QQEmojiSyncService(
                call_action=call_action,
                download_image=AsyncMock(),
                registered_hash_exists=AsyncMock(return_value=False),
                pending_dir=Path(tmp_dir),
                max_pending=1000,
            )

            result = await service.sync(418)

        self.assertEqual(result, SyncResult(requested=418, fetched=0, queued=0, duplicates=0, rejected=0, failed=0))
        call_action.assert_awaited_once_with("fetch_custom_face", {"count": 418})

    async def test_sync_rejects_insecure_urls_and_invalid_image_payloads(self) -> None:
        call_action = AsyncMock(
            return_value={
                "status": "ok",
                "retcode": 0,
                "data": ["http://example.com/insecure.png", "https://example.com/not-image.png"],
            }
        )
        download_image = AsyncMock(return_value=base64.b64encode(b"not an image").decode("ascii"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            service = QQEmojiSyncService(
                call_action=call_action,
                download_image=download_image,
                registered_hash_exists=AsyncMock(return_value=False),
                pending_dir=Path(tmp_dir),
                max_pending=10,
            )

            result = await service.sync(2)

            self.assertEqual(
                result,
                SyncResult(requested=2, fetched=2, queued=0, duplicates=0, rejected=1, failed=1),
            )
            self.assertEqual(list(Path(tmp_dir).iterdir()), [])

        download_image.assert_awaited_once_with("https://example.com/not-image.png")

    async def test_sync_rejects_failed_napcat_responses_and_stops_at_pending_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pending_dir = Path(tmp_dir)
            (pending_dir / "existing.png").write_bytes(b"existing")
            service = QQEmojiSyncService(
                call_action=AsyncMock(
                    return_value={"status": "ok", "retcode": 0, "data": ["https://example.com/new.png"]}
                ),
                download_image=AsyncMock(),
                registered_hash_exists=AsyncMock(return_value=False),
                pending_dir=pending_dir,
                max_pending=1,
            )

            result = await service.sync(1)

            self.assertTrue(result.capacity_reached)
            self.assertEqual(result.queued, 0)
            service.download_image.assert_not_awaited()

        failed_service = QQEmojiSyncService(
            call_action=AsyncMock(return_value={"status": "failed", "retcode": 1404, "data": None}),
            download_image=AsyncMock(),
            registered_hash_exists=AsyncMock(return_value=False),
        )
        with self.assertRaisesRegex(QQEmojiSyncError, "NapCat 未提供收藏表情列表"):
            await failed_service.sync(1)

    async def test_sync_counts_non_image_files_toward_pending_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pending_dir = Path(tmp_dir)
            (pending_dir / "unrelated.txt").write_text("existing", encoding="utf-8")
            service = QQEmojiSyncService(
                call_action=AsyncMock(
                    return_value={"status": "ok", "retcode": 0, "data": ["https://example.com/new.png"]}
                ),
                download_image=AsyncMock(),
                registered_hash_exists=AsyncMock(return_value=False),
                pending_dir=pending_dir,
                max_pending=1,
            )

            result = await service.sync(1)

            self.assertTrue(result.capacity_reached)
            self.assertEqual(result.queued, 0)
            service.download_image.assert_not_awaited()


def make_command(user_id: str, *, permission: list[str], max_count: int = 20) -> QQEmojiSyncCommand:
    message = SimpleNamespace(
        message_info=SimpleNamespace(user_info=SimpleNamespace(user_id=user_id)),
        chat_stream=SimpleNamespace(stream_id="stream-1"),
    )
    command = QQEmojiSyncCommand(
        message=message,
        plugin_config={
            "plugin": {"permission": permission},
            "sync": {"default_count": 10, "max_count": max_count, "max_pending": 50},
        },
    )
    command.set_matched_groups({"count": None})
    command.send_text = AsyncMock(return_value=True)
    return command


class QQEmojiSyncCommandTest(unittest.IsolatedAsyncioTestCase):
    async def test_command_denies_unconfigured_or_unauthorized_users(self) -> None:
        for permission in ([], ["10001"]):
            command = make_command("20002", permission=permission)
            with patch("plugins.qq_emoji_sync.plugin.QQEmojiSyncService.sync", new=AsyncMock()) as sync:
                success, _, intercept = await command.execute()

            self.assertFalse(success)
            self.assertEqual(intercept, 2)
            sync.assert_not_awaited()

    async def test_command_validates_count_and_reports_sync_summary(self) -> None:
        too_many = make_command("10001", permission=["10001"], max_count=5)
        too_many.set_matched_groups({"count": "6"})
        with patch("plugins.qq_emoji_sync.plugin.QQEmojiSyncService.sync", new=AsyncMock()) as sync:
            success, _, intercept = await too_many.execute()
        self.assertFalse(success)
        self.assertEqual(intercept, 2)
        sync.assert_not_awaited()

        command = make_command("10001", permission=["10001"], max_count=5)
        command.set_matched_groups({"count": "2"})
        result = SyncResult(requested=2, fetched=2, queued=1, duplicates=1, rejected=0, failed=0)
        with patch("plugins.qq_emoji_sync.plugin.QQEmojiSyncService.sync", new=AsyncMock(return_value=result)) as sync:
            success, message, intercept = await command.execute()

        self.assertTrue(success)
        self.assertEqual(message, "同步完成")
        self.assertEqual(intercept, 2)
        sync.assert_awaited_once_with(2)
        self.assertIn("加入待注册 1", command.send_text.await_args_list[-1].args[0])

    async def test_command_caps_invalid_default_count_to_configured_maximum(self) -> None:
        command = make_command("10001", permission=["10001"], max_count=5)
        result = SyncResult(requested=5, fetched=0, queued=0, duplicates=0, rejected=0, failed=0)

        with patch("plugins.qq_emoji_sync.plugin.QQEmojiSyncService.sync", new=AsyncMock(return_value=result)) as sync:
            success, _, _ = await command.execute()

        self.assertTrue(success)
        sync.assert_awaited_once_with(5)


if __name__ == "__main__":
    unittest.main()
