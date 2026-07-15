import base64
import hashlib
import io
import json
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


def partial_update_gif_base64() -> str:
    palette = [0, 0, 0, 255, 0, 0, 0, 255, 0] + [0, 0, 0] * 253
    first = Image.new("P", (3, 3), 1)
    first.putpalette(palette)
    second = Image.new("P", (3, 3), 0)
    second.putpalette(palette)
    second.putpixel((1, 1), 2)
    buffer = io.BytesIO()
    first.save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
        transparency=0,
        disposal=1,
        optimize=False,
    )
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def make_image_manager() -> utils_image.ImageManager:
    manager = object.__new__(utils_image.ImageManager)
    manager._initialized = True
    manager.IMAGE_DIR = "data"
    manager.vlm = SimpleNamespace(
        generate_response_for_image=AsyncMock(),
        generate_response_for_images=AsyncMock(),
    )
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
        registered_description = (
            "情感：开心、好笑；适用场景：当朋友讲笑话时，用于表示被逗乐；"
            "表达意图：积极回应；画面内容：小狗拍桌大笑；画面文字：哈哈哈；风格/梗：夸张反应图"
        )
        fake_emoji_manager = SimpleNamespace(
            get_emoji_description_by_hash=AsyncMock(return_value=registered_description)
        )

        with patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager):
            self.assertEqual(await manager.get_emoji_description(image_b64), f"[表情包：{registered_description}]")

        fake_emoji_manager.get_emoji_description_by_hash = AsyncMock(return_value=None)
        cached_description = (
            "情感：无奈；适用场景：当对方说出离谱内容时，用于表达无语；"
            "表达意图：轻度吐槽；画面内容：猫咪眯眼侧头；画面文字：无文字；风格/梗：猫 meme"
        )
        cache_record = SimpleNamespace(emotion_tags="缓存情绪", description=cached_description)
        manager._save_emoji_file_if_needed = AsyncMock()
        with (
            patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager),
            patch.object(utils_image.EmojiDescriptionCache, "get_or_none", return_value=cache_record),
        ):
            self.assertEqual(await manager.get_emoji_description(image_b64), f"[表情包：{cached_description}]")

        manager._save_emoji_file_if_needed.assert_awaited_once()

        semantic_payload = json.dumps(
            {
                "emotion": ["惊喜", "开心"],
                "scene": "当收到意外好消息时，用于表达惊喜和开心",
                "intent": "积极回应并分享喜悦",
                "content": "角色睁大眼睛后举手欢呼",
                "text": "好耶",
                "style": "夸张庆祝反应图",
            },
            ensure_ascii=False,
        )
        fake_semantic_llm = SimpleNamespace(generate_response_async=AsyncMock(return_value=(semantic_payload, None)))
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
            patch.object(utils_image, "LLMRequest", return_value=fake_semantic_llm),
        ):
            self.assertEqual(
                await manager.get_emoji_description(image_b64),
                "[表情包：情感：惊喜、开心；适用场景：当收到意外好消息时，用于表达惊喜和开心；"
                "表达意图：积极回应并分享喜悦；画面内容：角色睁大眼睛后举手欢呼；"
                "画面文字：好耶；风格/梗：夸张庆祝反应图]",
            )

        manager.vlm.generate_response_for_image.assert_awaited_once()
        fake_semantic_llm.generate_response_async.assert_awaited_once()
        manager._save_emoji_file_if_needed.assert_awaited_once()

        self.assertEqual(await manager.get_emoji_description("not-base64"), "[表情包(处理失败)]")

    async def test_get_emoji_description_sends_gif_frames_as_ordered_png_images(self) -> None:
        manager = make_image_manager()
        manager.vlm.generate_response_for_images = AsyncMock(return_value=("逐帧与整体描述", None))
        manager._save_emoji_file_if_needed = AsyncMock()
        fake_emoji_manager = SimpleNamespace(get_emoji_description_by_hash=AsyncMock(return_value="旧描述"))
        semantic_payload = json.dumps(
            {
                "emotion": ["开心"],
                "scene": "当聊天气氛轻松时，用于表示开心回应",
                "intent": "积极接住对方的话题",
                "content": "角色连续点头并露出笑容",
                "text": "无文字",
                "style": "循环动态反应图",
            },
            ensure_ascii=False,
        )
        fake_semantic_llm = SimpleNamespace(generate_response_async=AsyncMock(return_value=(semantic_payload, None)))
        stale_cache = SimpleNamespace(description="旧拼图描述", emotion_tags="旧情绪", save=Mock())

        with (
            patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager),
            patch.object(utils_image.EmojiDescriptionCache, "get_or_none", side_effect=[stale_cache, stale_cache]),
            patch.object(
                utils_image.EmojiDescriptionCache,
                "get_or_create",
                return_value=(stale_cache, False),
            ),
            patch.object(utils_image, "LLMRequest", return_value=fake_semantic_llm),
        ):
            self.assertEqual(
                await manager.get_emoji_description(gif_base64()),
                "[表情包：情感：开心；适用场景：当聊天气氛轻松时，用于表示开心回应；"
                "表达意图：积极接住对方的话题；画面内容：角色连续点头并露出笑容；"
                "画面文字：无文字；风格/梗：循环动态反应图]",
            )

        args = manager.vlm.generate_response_for_images.await_args.args
        self.assertIn("分别概括每一帧", args[0])
        self.assertIn("整体", args[0])
        self.assertEqual([image_format for image_format, _ in args[1]], ["png", "png"])
        self.assertEqual(manager.vlm.generate_response_for_images.await_args.kwargs["max_tokens"], 512)
        self.assertIn("情感：开心；适用场景：", utils_image.read_gif_description_cache(stale_cache.description))
        fake_emoji_manager.get_emoji_description_by_hash.assert_not_awaited()
        manager.vlm.generate_response_for_image.assert_not_awaited()

    async def test_get_emoji_description_upgrades_legacy_registered_description_without_vlm(self) -> None:
        manager = make_image_manager()
        manager._save_emoji_file_if_needed = AsyncMock()
        fake_emoji_manager = SimpleNamespace(
            get_emoji_description_by_hash=AsyncMock(return_value="[表情包：旧注册视觉描述]")
        )
        semantic_payload = json.dumps(
            {
                "emotion": ["无奈"],
                "scene": "当事情反复返工时，用于表达疲惫无奈",
                "intent": "吐槽当前处境",
                "content": "角色低头趴在桌面上",
                "text": "又来",
                "style": "夸张反应图",
            },
            ensure_ascii=False,
        )
        fake_semantic_llm = SimpleNamespace(generate_response_async=AsyncMock(return_value=(semantic_payload, None)))

        with (
            patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager),
            patch.object(utils_image.EmojiDescriptionCache, "get_or_none", side_effect=[None, None]),
            patch.object(
                utils_image.EmojiDescriptionCache,
                "get_or_create",
                return_value=(SimpleNamespace(save=Mock()), True),
            ),
            patch.object(utils_image, "LLMRequest", return_value=fake_semantic_llm),
        ):
            result = await manager.get_emoji_description(png_base64())

        self.assertEqual(
            result,
            "[表情包：情感：无奈；适用场景：当事情反复返工时，用于表达疲惫无奈；"
            "表达意图：吐槽当前处境；画面内容：角色低头趴在桌面上；"
            "画面文字：又来；风格/梗：夸张反应图]",
        )
        manager.vlm.generate_response_for_image.assert_not_awaited()
        self.assertIn("旧注册视觉描述", fake_semantic_llm.generate_response_async.await_args.args[0])

    async def test_get_emoji_description_reuses_versioned_gif_cache_without_exposing_marker(self) -> None:
        manager = make_image_manager()
        manager._save_emoji_file_if_needed = AsyncMock()
        fake_emoji_manager = SimpleNamespace(get_emoji_description_by_hash=AsyncMock(return_value="旧描述"))
        semantic_description = (
            "情感：无奈；适用场景：当工作反复返工时，用于表达疲惫无奈；"
            "表达意图：吐槽现状；画面内容：角色缓慢趴到桌上；画面文字：又来；风格/梗：循环反应图"
        )
        cache_record = SimpleNamespace(
            description=utils_image.write_gif_description_cache(semantic_description),
            emotion_tags="新版情绪",
        )

        with (
            patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager),
            patch.object(utils_image.EmojiDescriptionCache, "get_or_none", return_value=cache_record),
        ):
            result = await manager.get_emoji_description(gif_base64())

        self.assertEqual(result, f"[表情包：{semantic_description}]")
        manager.vlm.generate_response_for_images.assert_not_awaited()
        fake_emoji_manager.get_emoji_description_by_hash.assert_not_awaited()

    async def test_describe_gif_frames_batches_long_sequences_and_builds_overall_summary(self) -> None:
        frames = [("png", f"frame-{index}") for index in range(1, 18)]
        vlm = SimpleNamespace(
            generate_response_for_images=AsyncMock(side_effect=[("第1至16帧概括", None), ("第17帧概括", None)]),
            generate_response_async=AsyncMock(return_value=("完整动作概括", None)),
        )

        description = await utils_image.describe_gif_frames(vlm, frames, temperature=0.4)

        image_calls = vlm.generate_response_for_images.await_args_list
        self.assertEqual([len(call.args[1]) for call in image_calls], [16, 1])
        self.assertEqual([call.kwargs["start_index"] for call in image_calls], [1, 17])
        self.assertEqual([call.kwargs["max_tokens"] for call in image_calls], [1152, 512])
        self.assertIn("第1至16帧概括", image_calls[1].args[0])
        overall_prompt = vlm.generate_response_async.await_args.args[0]
        self.assertIn("第1至16帧概括", overall_prompt)
        self.assertIn("第17帧概括", overall_prompt)
        self.assertEqual(
            description,
            "逐帧概括：\n第1至16帧概括\n\n第17帧概括\n\n整体概括：\n完整动作概括",
        )

    async def test_audit_gif_frames_requires_every_batch_to_explicitly_pass(self) -> None:
        frames = [("png", f"frame-{index}") for index in range(17)]

        for responses, expected in [
            (["是。", "是"], "是"),
            (["否，不符合要求", "是"], "否"),
            (["无法判断", "是"], "否"),
        ]:
            with self.subTest(responses=responses):
                vlm = SimpleNamespace(
                    generate_response_for_images=AsyncMock(
                        side_effect=[(response, None) for response in responses]
                    )
                )
                result = await utils_image.audit_gif_frames(
                    vlm,
                    "审核",
                    frames,
                    temperature=0.3,
                    max_tokens=1000,
                )

                self.assertEqual(result, expected)


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

    def test_extract_gif_frames_returns_ordered_png_frames_or_empty_for_invalid_input(self) -> None:
        frames = utils_image.ImageManager.extract_gif_frames(gif_base64())

        self.assertEqual(len(frames), 2)
        decoded_frames = [Image.open(io.BytesIO(base64.b64decode(frame))) for frame in frames]
        self.assertEqual([frame.format for frame in decoded_frames], ["PNG", "PNG"])
        self.assertEqual([frame.size for frame in decoded_frames], [(200, 200), (200, 200)])
        self.assertEqual(decoded_frames[0].convert("RGB").getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(decoded_frames[1].convert("RGB").getpixel((0, 0)), (0, 255, 0))
        self.assertEqual(utils_image.ImageManager.extract_gif_frames("not-base64"), [])

    def test_extract_gif_frames_does_not_truncate_after_old_fifteen_frame_limit(self) -> None:
        source_frames = [Image.new("RGB", (2, 2), (index * 15, 0, 0)) for index in range(17)]
        buffer = io.BytesIO()
        source_frames[0].save(
            buffer,
            format="GIF",
            save_all=True,
            append_images=source_frames[1:],
            duration=100,
            loop=0,
        )

        frames = utils_image.ImageManager.extract_gif_frames(base64.b64encode(buffer.getvalue()).decode("ascii"))

        self.assertEqual(len(frames), 17)

    def test_extract_gif_frames_composes_partial_updates_into_complete_frames(self) -> None:
        frames = utils_image.ImageManager.extract_gif_frames(partial_update_gif_base64(), target_height=0)

        second_frame = Image.open(io.BytesIO(base64.b64decode(frames[1]))).convert("RGBA")
        self.assertEqual(second_frame.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(second_frame.getpixel((1, 1)), (0, 255, 0, 255))

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
