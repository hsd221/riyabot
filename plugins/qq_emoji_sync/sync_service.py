"""从 NapCat 拉取 QQ 收藏表情并写入 MaiBot 待注册目录。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import os
import tempfile

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

from src.chat.emoji_system.emoji_manager import EMOJI_DIR, get_emoji_manager
from src.common.logger import get_logger

logger = get_logger("qq_emoji_sync")

MAX_SYNC_COUNT = 1000
MAX_PENDING_FILES = 2000
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_EDGE = 4096
MAX_IMAGE_PIXELS = 16_000_000
MAX_URL_LENGTH = 4096

_FORMAT_EXTENSIONS = {
    "JPEG": "jpg",
    "PNG": "png",
    "GIF": "gif",
    "WEBP": "webp",
}

ActionCaller = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
ImageDownloader = Callable[[str], Awaitable[str]]
RegisteredHashLookup = Callable[[str], Awaitable[bool]]


class QQEmojiSyncError(RuntimeError):
    """可安全返回给命令调用者的同步错误。"""


@dataclass
class SyncResult:
    requested: int
    fetched: int
    queued: int
    duplicates: int
    rejected: int
    failed: int
    capacity_reached: bool = False

    def to_message(self) -> str:
        message = (
            f"QQ 收藏表情同步完成：获取 {self.fetched}，加入待注册 {self.queued}，"
            f"重复 {self.duplicates}，拒绝 {self.rejected}，失败 {self.failed}"
        )
        if self.capacity_reached:
            message += "。待注册目录已达到容量限制"
        return message


async def _call_napcat_action(action: str, params: dict[str, Any]) -> dict[str, Any]:
    from plugins.onebot_adapter.adapter_core.send_handler.nc_sending import nc_message_sender

    if nc_message_sender.server_connection is None:
        raise QQEmojiSyncError("NapCat 尚未连接，请稍后重试")
    return await nc_message_sender.send_message_to_napcat(action, params)


async def _download_image(url: str) -> str:
    from plugins.onebot_adapter.adapter_core.utils import get_image_base64

    return await get_image_base64(url, https_only=True)


async def _registered_hash_exists(image_hash: str) -> bool:
    manager = get_emoji_manager()
    if await manager.get_emoji_from_manager(image_hash):
        return True
    return bool(await manager.get_emoji_from_db(image_hash))


class QQEmojiSyncService:
    def __init__(
        self,
        *,
        call_action: ActionCaller | None = None,
        download_image: ImageDownloader | None = None,
        registered_hash_exists: RegisteredHashLookup | None = None,
        pending_dir: Path | str = EMOJI_DIR,
        max_pending: int = 1000,
    ) -> None:
        if isinstance(max_pending, bool) or not isinstance(max_pending, int):
            raise TypeError("max_pending 必须是整数")
        if not 1 <= max_pending <= MAX_PENDING_FILES:
            raise ValueError(f"max_pending 必须在 1 到 {MAX_PENDING_FILES} 之间")

        self.call_action = call_action or _call_napcat_action
        self.download_image = download_image or _download_image
        self.registered_hash_exists = registered_hash_exists or _registered_hash_exists
        self.pending_dir = Path(pending_dir)
        self.max_pending = max_pending

    async def sync(self, count: int) -> SyncResult:
        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError("同步数量必须是整数")
        if not 1 <= count <= MAX_SYNC_COUNT:
            raise ValueError(f"同步数量必须在 1 到 {MAX_SYNC_COUNT} 之间")

        response = await self._fetch_custom_face_response(count)
        raw_urls = response.get("data")
        if not isinstance(raw_urls, list):
            raise QQEmojiSyncError("NapCat 未提供收藏表情列表，请确认版本支持 fetch_custom_face")

        urls = raw_urls[:count]
        result = SyncResult(
            requested=count,
            fetched=len(urls),
            queued=0,
            duplicates=0,
            rejected=0,
            failed=0,
        )
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        seen_urls: set[str] = set()

        for raw_url in urls:
            if self._pending_count() >= self.max_pending:
                result.capacity_reached = True
                return result

            if not self._is_allowed_url(raw_url):
                result.rejected += 1
                continue

            url = raw_url.strip()
            if url in seen_urls:
                result.duplicates += 1
                continue
            seen_urls.add(url)

            try:
                image_base64 = await self.download_image(url)
                image_bytes, extension, image_hash = self._decode_and_validate_image(image_base64)
                if await self.registered_hash_exists(image_hash) or self._pending_hash_exists(image_hash):
                    result.duplicates += 1
                    continue
                if self._pending_count() >= self.max_pending:
                    result.capacity_reached = True
                    return result
                if not self._write_pending_image(image_bytes, image_hash, extension):
                    result.duplicates += 1
                    continue
            except (QQEmojiSyncError, OSError, ValueError, TypeError, binascii.Error, UnidentifiedImageError):
                result.failed += 1
                logger.warning("QQ 收藏表情处理失败", event_code="qq_emoji_sync.item_failed")
                continue
            except Exception:
                result.failed += 1
                logger.exception("QQ 收藏表情处理异常", event_code="qq_emoji_sync.item_exception")
                continue

            result.queued += 1

        return result

    async def _fetch_custom_face_response(self, count: int) -> dict[str, Any]:
        try:
            response = await self.call_action("fetch_custom_face", {"count": count})
        except QQEmojiSyncError:
            raise
        except Exception as exc:
            raise QQEmojiSyncError("无法请求 NapCat 收藏表情接口") from exc

        if not isinstance(response, dict):
            raise QQEmojiSyncError("NapCat 收藏表情接口返回了无效响应")
        if response.get("status") != "ok" or response.get("retcode") not in (None, 0):
            raise QQEmojiSyncError("NapCat 未提供收藏表情列表，请确认版本支持 fetch_custom_face")
        return response

    @staticmethod
    def _is_allowed_url(raw_url: object) -> bool:
        if not isinstance(raw_url, str):
            return False
        url = raw_url.strip()
        if not url or len(url) > MAX_URL_LENGTH:
            return False
        try:
            parsed = urlsplit(url)
        except ValueError:
            return False
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
        )

    @staticmethod
    def _decode_and_validate_image(image_base64: str) -> tuple[bytes, str, str]:
        if not isinstance(image_base64, str) or not image_base64:
            raise ValueError("图片数据为空")
        image_bytes = base64.b64decode(image_base64, validate=True)
        if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError("图片大小无效")

        with Image.open(io.BytesIO(image_bytes)) as image:
            image_format = (image.format or "").upper()
            extension = _FORMAT_EXTENSIONS.get(image_format)
            if extension is None:
                raise ValueError("图片格式不受支持")
            width, height = image.size
            if width <= 0 or height <= 0 or width > MAX_IMAGE_EDGE or height > MAX_IMAGE_EDGE:
                raise ValueError("图片尺寸无效")
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError("图片像素过多")
            image.verify()

        image_hash = hashlib.md5(image_bytes, usedforsecurity=False).hexdigest()
        return image_bytes, extension, image_hash

    def _pending_count(self) -> int:
        return sum(1 for _entry in self.pending_dir.iterdir())

    def _pending_hash_exists(self, image_hash: str) -> bool:
        if any(self.pending_dir.glob(f"qq_{image_hash}.*")):
            return True
        return any(self.pending_dir.glob(f"{image_hash[:8]}.*"))

    def _write_pending_image(self, image_bytes: bytes, image_hash: str, extension: str) -> bool:
        destination = self.pending_dir / f"qq_{image_hash}.{extension}"
        if destination.exists():
            return False

        file_descriptor, temp_path = tempfile.mkstemp(prefix=".qq-emoji-", dir=self.pending_dir)
        try:
            with os.fdopen(file_descriptor, "wb") as temp_file:
                temp_file.write(image_bytes)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            try:
                os.link(temp_path, destination)
            except FileExistsError:
                return False
            return True
        finally:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass
