import base64
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from src.chat.utils import utils_image, utils_voice


def png_bytes(color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    image = Image.new("RGB", (3, 2), color=color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def png_base64(color: tuple[int, int, int] = (255, 0, 0)) -> str:
    return base64.b64encode(png_bytes(color)).decode("ascii")


def gif_base64() -> str:
    first = Image.new("RGB", (2, 2), (255, 0, 0))
    second = Image.new("RGB", (2, 2), (0, 255, 0))
    buffer = io.BytesIO()
    first.save(buffer, format="GIF", save_all=True, append_images=[second], duration=100, loop=0)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def make_image_manager() -> utils_image.ImageManager:
    manager = object.__new__(utils_image.ImageManager)
    manager._initialized = True
    manager.IMAGE_DIR = "data"
    manager.vlm = SimpleNamespace(generate_response_for_image=AsyncMock())
    return manager


class VoiceUtilsTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_voice_text_respects_asr_config_success_none_and_errors(self) -> None:
        with patch.object(utils_voice.global_config, "voice", SimpleNamespace(enable_asr=False)):
            self.assertEqual(await utils_voice.get_voice_text("voice"), "[语音]")

        fake_llm = SimpleNamespace(generate_response_for_voice=AsyncMock(return_value="你好"))
        with (
            patch.object(utils_voice.global_config, "voice", SimpleNamespace(enable_asr=True)),
            patch.object(utils_voice, "LLMRequest", return_value=fake_llm),
        ):
            self.assertEqual(await utils_voice.get_voice_text("voice"), "[语音：你好]")

        fake_llm = SimpleNamespace(generate_response_for_voice=AsyncMock(return_value=None))
        with (
            patch.object(utils_voice.global_config, "voice", SimpleNamespace(enable_asr=True)),
            patch.object(utils_voice, "LLMRequest", return_value=fake_llm),
        ):
            self.assertEqual(await utils_voice.get_voice_text("voice"), "[语音(文本生成失败)]")

        fake_llm = SimpleNamespace(generate_response_for_voice=AsyncMock(side_effect=RuntimeError("asr down")))
        with (
            patch.object(utils_voice.global_config, "voice", SimpleNamespace(enable_asr=True)),
            patch.object(utils_voice, "LLMRequest", return_value=fake_llm),
        ):
            self.assertEqual(await utils_voice.get_voice_text("voice"), "[语音]")


class ImageFileAndDbHelperTest(unittest.TestCase):
    def test_base64_file_helpers_round_trip_and_report_missing_or_empty_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "image.png"
            source.write_bytes(png_bytes())

            encoded = utils_image.image_path_to_base64(str(source))
            self.assertEqual(base64.b64decode(encoded), source.read_bytes())

            output = Path(temp_dir) / "nested" / "out.png"
            self.assertTrue(utils_image.base64_to_image(encoded, str(output)))
            self.assertEqual(output.read_bytes(), source.read_bytes())

            empty = Path(temp_dir) / "empty.png"
            empty.write_bytes(b"")
            with self.assertRaises(IOError):
                utils_image.image_path_to_base64(str(empty))
            with self.assertRaises(FileNotFoundError):
                utils_image.image_path_to_base64(str(Path(temp_dir) / "missing.png"))

    def test_description_db_helpers_get_save_and_cleanup_records(self) -> None:
        record = SimpleNamespace(description="cached")
        with patch.object(utils_image.ImageDescriptions, "get_or_none", return_value=record):
            self.assertEqual(utils_image.ImageManager._get_description_from_db("hash", "image"), "cached")
        with patch.object(utils_image.ImageDescriptions, "get_or_none", return_value=None):
            self.assertIsNone(utils_image.ImageManager._get_description_from_db("hash", "image"))
        with patch.object(utils_image.ImageDescriptions, "get_or_none", side_effect=RuntimeError("db down")):
            self.assertIsNone(utils_image.ImageManager._get_description_from_db("hash", "image"))

        existing = SimpleNamespace(description="old", timestamp=0.0, save=Mock())
        with patch.object(utils_image.ImageDescriptions, "get_or_create", return_value=(existing, False)):
            utils_image.ImageManager._save_description_to_db("hash", "new", "image")
        self.assertEqual(existing.description, "new")
        existing.save.assert_called_once()

        with patch.object(utils_image.ImageDescriptions, "get_or_create", return_value=(SimpleNamespace(), True)):
            utils_image.ImageManager._save_description_to_db("hash", "new", "image")

        class FakeDelete:
            def __init__(self, count: int):
                self.count = count

            def where(self, *_args, **_kwargs):
                return self

            def execute(self):
                return self.count

        with (
            patch.object(utils_image.Images, "delete", return_value=FakeDelete(2)),
            patch.object(utils_image.ImageDescriptions, "delete", return_value=FakeDelete(3)),
        ):
            utils_image.ImageManager._cleanup_invalid_descriptions()

        with (
            patch.object(utils_image.Images, "delete", return_value=FakeDelete(1)),
            patch.object(utils_image.ImageDescriptions, "delete", return_value=FakeDelete(1)),
        ):
            utils_image.ImageManager._cleanup_emoji_from_image_descriptions()


class ImageManagerEmojiTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_emoji_tag_and_auto_save_use_emoji_manager_and_config(self) -> None:
        manager = make_image_manager()
        image_b64 = png_base64()
        image_hash = hashlib.md5(base64.b64decode(image_b64)).hexdigest()
        fake_emoji_manager = SimpleNamespace(
            get_emoji_from_manager=AsyncMock(return_value=SimpleNamespace(emotion=["开心", "好笑"]))
        )

        with patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager):
            self.assertEqual(await manager.get_emoji_tag(image_b64), "[表情包：开心,好笑]")

        fake_emoji_manager.get_emoji_from_manager = AsyncMock(return_value=None)
        with patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager):
            self.assertEqual(await manager.get_emoji_tag(image_b64), "[表情包：未知]")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(utils_image.global_config, "emoji", SimpleNamespace(steal_emoji=False)),
        ):
            await manager._save_emoji_file_if_needed(image_b64, image_hash, "png")
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

        with tempfile.TemporaryDirectory() as temp_dir:
            emoji_dir = Path(temp_dir) / "emoji"
            fake_emoji_manager.get_emoji_from_manager = AsyncMock(return_value=None)
            with (
                patch.object(utils_image.global_config, "emoji", SimpleNamespace(steal_emoji=True)),
                patch("src.chat.emoji_system.emoji_manager.EMOJI_DIR", str(emoji_dir)),
                patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager),
            ):
                await manager._save_emoji_file_if_needed(image_b64, image_hash, "png")

            saved = emoji_dir / f"{image_hash[:8]}.png"
            self.assertTrue(saved.exists())
            self.assertEqual(saved.read_bytes(), base64.b64decode(image_b64))

            fake_emoji_manager.get_emoji_from_manager = AsyncMock(return_value=object())
            with (
                patch.object(utils_image.global_config, "emoji", SimpleNamespace(steal_emoji=True)),
                patch("src.chat.emoji_system.emoji_manager.EMOJI_DIR", str(emoji_dir)),
                patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager),
                patch.object(utils_image, "base64_to_image") as save_image,
            ):
                await manager._save_emoji_file_if_needed(image_b64, image_hash, "png")

            save_image.assert_not_called()

    async def test_get_emoji_description_uses_manager_cache_table_or_vlm_flow(self) -> None:
        manager = make_image_manager()
        image_b64 = png_base64()
        fake_emoji_manager = SimpleNamespace(get_emoji_tag_by_hash=AsyncMock(return_value=["开心", "好笑"]))

        with patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager):
            self.assertEqual(await manager.get_emoji_description(image_b64), "[表情包：开心,好笑]")

        fake_emoji_manager.get_emoji_tag_by_hash = AsyncMock(return_value=None)
        cache_record = SimpleNamespace(emotion_tags="缓存情绪", description="缓存描述")
        manager._save_emoji_file_if_needed = AsyncMock()
        with (
            patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager),
            patch.object(utils_image.EmojiDescriptionCache, "get_or_none", return_value=cache_record),
        ):
            self.assertEqual(await manager.get_emoji_description(image_b64), "[表情包：缓存情绪]")

        manager._save_emoji_file_if_needed.assert_awaited_once()

        fake_emotion_llm = SimpleNamespace(generate_response_async=AsyncMock(return_value=("惊喜,开心", None)))
        manager = make_image_manager()
        manager.vlm.generate_response_for_image = AsyncMock(return_value=("详细描述", None))
        manager._save_emoji_file_if_needed = AsyncMock()
        with (
            patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager),
            patch.object(utils_image.EmojiDescriptionCache, "get_or_none", side_effect=[None, None]),
            patch.object(
                utils_image.EmojiDescriptionCache,
                "get_or_create",
                return_value=(SimpleNamespace(save=Mock()), True),
            ),
            patch.object(utils_image, "LLMRequest", return_value=fake_emotion_llm),
        ):
            self.assertEqual(await manager.get_emoji_description(image_b64), "[表情包：惊喜，开心]")

        manager.vlm.generate_response_for_image.assert_awaited_once()
        fake_emotion_llm.generate_response_async.assert_awaited_once()
        manager._save_emoji_file_if_needed.assert_awaited_once()

        self.assertEqual(await manager.get_emoji_description("not-base64"), "[表情包(处理失败)]")


class ImageManagerDescriptionAndProcessTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_image_description_uses_existing_cache_or_generates_and_persists_new_description(self) -> None:
        manager = make_image_manager()
        image_b64 = png_base64()
        existing = SimpleNamespace(description="已有描述", count=2, save=Mock())
        with patch.object(utils_image.Images, "get_or_none", return_value=existing):
            self.assertEqual(await manager.get_image_description(image_b64), "[图片：已有描述]")

        self.assertEqual(existing.count, 3)
        existing.save.assert_called_once()

        with (
            patch.object(utils_image.Images, "get_or_none", return_value=None),
            patch.object(manager, "_get_description_from_db", return_value="备用缓存"),
        ):
            self.assertEqual(await manager.get_image_description(image_b64), "[图片：备用缓存]")

        with tempfile.TemporaryDirectory() as temp_dir:
            manager.IMAGE_DIR = temp_dir
            manager.vlm.generate_response_for_image = AsyncMock(return_value=("新描述", None))
            with (
                patch.object(utils_image.Images, "get_or_none", return_value=None),
                patch.object(manager, "_get_description_from_db", return_value=None),
                patch.object(utils_image.Images, "create") as create_image,
                patch.object(manager, "_save_description_to_db") as save_description,
                patch.object(utils_image.time, "time", return_value=1234.0),
                patch.object(utils_image.uuid, "uuid4", return_value="uuid-1"),
            ):
                self.assertEqual(await manager.get_image_description(image_b64), "[图片：新描述]")

            manager.vlm.generate_response_for_image.assert_awaited_once()
            create_image.assert_called_once()
            self.assertTrue(
                (
                    Path(temp_dir) / "image" / f"1234_{hashlib.md5(base64.b64decode(image_b64)).hexdigest()[:8]}.png"
                ).exists()
            )
            save_description.assert_called_once()

        self.assertEqual(await manager.get_image_description("not-base64"), "[图片(处理失败)]")

    def test_transform_gif_returns_jpeg_strip_or_none_for_invalid_input(self) -> None:
        transformed = utils_image.ImageManager.transform_gif(gif_base64(), similarity_threshold=0.0, max_frames=2)

        self.assertIsNotNone(transformed)
        image = Image.open(io.BytesIO(base64.b64decode(transformed)))
        self.assertEqual(image.format, "JPEG")
        self.assertEqual(image.height, 200)
        self.assertGreaterEqual(image.width, 200)
        self.assertIsNone(utils_image.ImageManager.transform_gif("not-base64"))

    async def test_process_image_reuses_existing_records_or_creates_new_and_runs_vlm_processing(self) -> None:
        manager = make_image_manager()
        image_b64 = png_base64()
        existing = SimpleNamespace(image_id="", count=None, vlm_processed=None, save=Mock())
        with patch.object(utils_image.Images, "get_or_none", return_value=existing):
            image_id, marker = await manager.process_image(image_b64)

        self.assertTrue(image_id)
        self.assertEqual(marker, f"[picid:{image_id}]")
        self.assertEqual(existing.count, 1)
        self.assertFalse(existing.vlm_processed)
        existing.save.assert_called_once()

        with tempfile.TemporaryDirectory() as temp_dir:
            manager.IMAGE_DIR = temp_dir
            manager._process_image_with_vlm = AsyncMock()
            with (
                patch.object(utils_image.Images, "get_or_none", return_value=None),
                patch.object(utils_image.Images, "create") as create_image,
                patch.object(utils_image.uuid, "uuid4", return_value="new-id"),
                patch.object(utils_image.time, "time", return_value=55.0),
            ):
                image_id, marker = await manager.process_image(image_b64)

            self.assertEqual((image_id, marker), ("new-id", "[picid:new-id]"))
            self.assertTrue((Path(temp_dir) / "images" / "new-id.png").exists())
            create_image.assert_called_once()
            manager._process_image_with_vlm.assert_awaited_once_with("new-id", image_b64)

        self.assertEqual(await manager.process_image("not-base64"), ("", "[图片]"))

    async def test_process_image_with_vlm_reuses_existing_description_cache_or_calls_model(self) -> None:
        manager = make_image_manager()
        image_b64 = png_base64()
        image = SimpleNamespace(id=1, description="", vlm_processed=False, save=Mock())
        other = SimpleNamespace(id=2, description="复用描述")
        with (
            patch.object(utils_image.Images, "get", return_value=image),
            patch.object(utils_image.Images, "get_or_none", return_value=other),
            patch.object(manager, "_save_description_to_db") as save_description,
        ):
            await manager._process_image_with_vlm("image-id", image_b64)

        self.assertEqual(image.description, "复用描述")
        self.assertTrue(image.vlm_processed)
        image.save.assert_called_once()
        save_description.assert_called_once()

        image = SimpleNamespace(id=1, description="", vlm_processed=False, save=Mock())
        manager.vlm.generate_response_for_image = AsyncMock(return_value=("模型描述", None))
        with (
            patch.object(utils_image.Images, "get", return_value=image),
            patch.object(utils_image.Images, "get_or_none", return_value=None),
            patch.object(manager, "_get_description_from_db", side_effect=[None, None]),
            patch.object(manager, "_save_description_to_db") as save_description,
            patch.object(
                utils_image.global_config,
                "personality",
                SimpleNamespace(visual_style="视觉风格"),
            ),
        ):
            await manager._process_image_with_vlm("image-id", image_b64)

        self.assertEqual(image.description, "模型描述")
        self.assertTrue(image.vlm_processed)
        manager.vlm.generate_response_for_image.assert_awaited_once()
        save_description.assert_called_once()


if __name__ == "__main__":
    unittest.main()
