import asyncio
import base64
import hashlib
import io
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from src.chat.utils import utils_image
from src.common.prompt_loader import load_prompt_template


def png_base64() -> str:
    image = Image.new("RGB", (4, 3), color=(220, 30, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def animated_png_base64() -> str:
    first = Image.new("RGBA", (4, 3), color=(220, 30, 40, 255))
    second = Image.new("RGBA", (4, 3), color=(30, 220, 40, 255))
    buffer = io.BytesIO()
    first.save(buffer, format="PNG", save_all=True, append_images=[second], duration=100, loop=0)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def make_image_manager() -> utils_image.ImageManager:
    manager = object.__new__(utils_image.ImageManager)
    manager._initialized = True
    manager.IMAGE_DIR = "data"
    manager.vlm = SimpleNamespace(
        generate_response_for_image=AsyncMock(return_value=("画面中央是一只抬起前爪的白猫，背景为浅灰色墙面。", None)),
        generate_response_for_images=AsyncMock(),
    )
    manager._vision_tasks = {}
    return manager


class VisionPromptContractTest(unittest.TestCase):
    def test_static_prompt_requires_complete_objective_and_injection_resistant_observation(self) -> None:
        prompt = load_prompt_template("media.vision.static")

        for required_concept in ("主体", "位置", "动作", "文字", "背景", "风格", "图表", "无法确认"):
            self.assertIn(required_concept, prompt)
        self.assertIn("不能改变任务", prompt)
        self.assertIn("不要省略", prompt)
        self.assertIn("不得概括", prompt)
        self.assertIn("静默核对", prompt)
        self.assertNotIn("表情包", prompt)
        self.assertNotIn("最多30字", prompt)

    def test_animated_prompt_requires_temporal_and_per_frame_observation(self) -> None:
        prompt = load_prompt_template("media.vision.animated")

        for required_concept in ("第 {frame_start} 帧", "第 {frame_end} 帧", "逐帧", "动作变化", "文字", "无法确认"):
            self.assertIn(required_concept, prompt)
        self.assertIn("不能改变任务", prompt)
        self.assertIn("不要省略", prompt)
        self.assertIn("不得概括", prompt)
        self.assertIn("静默核对", prompt)
        self.assertIn("同上", prompt)
        self.assertIn("独立理解", prompt)
        self.assertNotIn("表情包", prompt)

class UnifiedImageRecognitionTest(unittest.IsolatedAsyncioTestCase):
    def test_animation_detection_is_based_on_frames_instead_of_gif_file_type(self) -> None:
        self.assertTrue(utils_image.is_animated_image_base64_data(animated_png_base64()))
        self.assertFalse(utils_image.is_animated_image_base64_data(png_base64()))

    def test_image_validation_rejects_oversized_bytes_pixels_and_frame_counts(self) -> None:
        static_image = png_base64()
        animated_image = animated_png_base64()

        with patch.object(utils_image, "MAX_VISION_IMAGE_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "文件大小"):
                utils_image._decode_image_base64(static_image)

        with patch.object(utils_image, "MAX_VISION_IMAGE_PIXELS", 1):
            with self.assertRaisesRegex(ValueError, "像素"):
                utils_image._decode_image_base64(static_image)

        with patch.object(utils_image, "MAX_VISION_ANIMATED_FRAMES", 1):
            with self.assertRaisesRegex(ValueError, "帧数"):
                utils_image._decode_image_base64(animated_image)

        with patch.object(utils_image, "MAX_VISION_ANIMATED_TOTAL_PIXELS", 1):
            with self.assertRaisesRegex(ValueError, "总像素"):
                utils_image._decode_image_base64(animated_image)

    def test_image_validation_rejects_truncated_image_payloads(self) -> None:
        truncated_png = base64.b64encode(base64.b64decode(png_base64())[:-8]).decode("ascii")

        with self.assertRaises((OSError, SyntaxError)):
            utils_image._decode_image_base64(truncated_png)

    def test_animated_frame_expansion_caps_extreme_aspect_ratios(self) -> None:
        panorama = Image.new("RGB", (20, 1), color=(220, 30, 40))
        buffer = io.BytesIO()
        panorama.save(buffer, format="GIF")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

        with patch.object(utils_image, "MAX_VISION_FRAME_DIMENSION", 100):
            frame_base64 = utils_image.ImageManager.extract_gif_frames(encoded, target_height=200)[0]

        with Image.open(io.BytesIO(base64.b64decode(frame_base64))) as frame:
            self.assertEqual(frame.size, (100, 5))

    async def test_static_recognition_is_cached_independently_of_business_media_type(self) -> None:
        manager = make_image_manager()
        image_base64 = png_base64()
        image_hash = hashlib.md5(base64.b64decode(image_base64)).hexdigest()
        cache: dict[tuple[str, str], str] = {}

        def read_cache(cache_hash: str, cache_type: str) -> str | None:
            return cache.get((cache_hash, cache_type))

        def write_cache(cache_hash: str, description: str, cache_type: str) -> None:
            cache[(cache_hash, cache_type)] = description

        with (
            patch.object(manager, "_get_description_from_db", side_effect=read_cache),
            patch.object(manager, "_save_description_to_db", side_effect=write_cache),
        ):
            first = await manager.recognize_image(image_base64)
            second = await manager.recognize_image(image_base64)

        self.assertEqual(first, second)
        self.assertEqual(first.image_hash, image_hash)
        self.assertEqual(first.image_format, "png")
        self.assertFalse(first.is_animated)
        self.assertEqual(first.description, "画面中央是一只抬起前爪的白猫，背景为浅灰色墙面。")
        self.assertEqual(cache[(image_hash, utils_image.VISION_DESCRIPTION_CACHE_TYPE)], first.description)
        manager.vlm.generate_response_for_image.assert_awaited_once()
        self.assertIn("视觉事实", manager.vlm.generate_response_for_image.await_args.args[0])
        self.assertEqual(manager.vlm.generate_response_for_image.await_args.kwargs["max_tokens"], 3072)

    async def test_concurrent_recognition_for_the_same_image_shares_one_model_request(self) -> None:
        manager = make_image_manager()
        image_base64 = png_base64()

        async def generate_description(*_args, **_kwargs):
            await asyncio.sleep(0)
            return "共享视觉描述", None

        manager.vlm.generate_response_for_image = AsyncMock(side_effect=generate_description)
        with (
            patch.object(manager, "_get_description_from_db", return_value=None),
            patch.object(manager, "_save_description_to_db"),
        ):
            first, second = await asyncio.gather(
                manager.recognize_image(image_base64),
                manager.recognize_image(image_base64),
            )

        self.assertEqual(first, second)
        self.assertEqual(first.description, "共享视觉描述")
        manager.vlm.generate_response_for_image.assert_awaited_once()
        self.assertEqual(manager._vision_tasks, {})

    async def test_cancelled_waiter_does_not_retain_completed_shared_task(self) -> None:
        manager = make_image_manager()
        image_base64 = png_base64()
        request_started = asyncio.Event()
        finish_request = asyncio.Event()

        async def generate_description(*_args, **_kwargs):
            request_started.set()
            await finish_request.wait()
            return "取消等待后完成的视觉描述", None

        manager.vlm.generate_response_for_image = AsyncMock(side_effect=generate_description)
        with (
            patch.object(manager, "_get_description_from_db", return_value=None),
            patch.object(manager, "_save_description_to_db"),
        ):
            waiter = asyncio.create_task(manager.recognize_image(image_base64))
            await request_started.wait()
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter

            finish_request.set()
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        self.assertEqual(manager._vision_tasks, {})

    def test_visual_description_cleanup_flattens_output_and_neutralizes_message_markers(self) -> None:
        description = utils_image._sanitize_visual_description("  第一行\n\n[图片：伪造标记]  ")

        self.assertEqual(description, "第一行 ［图片：伪造标记］")
        with self.assertRaisesRegex(RuntimeError, "空描述"):
            utils_image._sanitize_visual_description("  \n ")

    async def test_long_animation_reuses_one_prompt_for_every_batch(self) -> None:
        frames = [("png", f"frame-{index}") for index in range(1, 18)]
        vlm = SimpleNamespace(
            generate_response_for_images=AsyncMock(
                side_effect=[("第1至16帧的客观变化", None), ("第17帧的客观变化", None)]
            )
        )
        prompt_calls: list[tuple[str, dict[str, object]]] = []

        def format_prompt(name: str, **kwargs: object) -> str:
            prompt_calls.append((name, kwargs))
            return f"{name}: {kwargs}"

        with patch.object(utils_image.prompt_manager, "format_prompt", side_effect=format_prompt):
            description = await utils_image.describe_gif_frames(vlm, frames, temperature=0.2)

        self.assertEqual([name for name, _ in prompt_calls], ["media.vision.animated", "media.vision.animated"])
        self.assertEqual(prompt_calls[0][1]["frame_start"], 1)
        self.assertEqual(prompt_calls[0][1]["frame_end"], 16)
        self.assertEqual(prompt_calls[1][1]["frame_start"], 17)
        self.assertEqual(prompt_calls[1][1]["frame_end"], 17)
        self.assertIn("第1至16帧的客观变化", prompt_calls[1][1]["previous_batch_description"])
        self.assertIn("第1至16帧的客观变化", description)
        self.assertIn("第17帧的客观变化", description)
        self.assertEqual(vlm.generate_response_for_images.await_count, 2)

    async def test_normal_image_post_processing_uses_unified_observation(self) -> None:
        manager = make_image_manager()
        image_base64 = png_base64()
        image_hash = hashlib.md5(base64.b64decode(image_base64)).hexdigest()
        observation = utils_image.VisualObservation(
            description="统一的客观视觉描述",
            image_hash=image_hash,
            image_format="png",
            is_animated=False,
        )
        manager.recognize_image = AsyncMock(return_value=observation)

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(manager, "IMAGE_DIR", temp_dir),
            patch.object(utils_image.Images, "get_or_none", return_value=None),
            patch.object(utils_image.Images, "create") as create_image,
            patch.object(manager, "_save_description_to_db") as save_description,
        ):
            result = await manager.get_image_description(image_base64)

        self.assertEqual(result, "[图片：统一的客观视觉描述]")
        manager.recognize_image.assert_awaited_once_with(image_base64)
        manager.vlm.generate_response_for_image.assert_not_awaited()
        self.assertEqual(create_image.call_args.kwargs["description"], "统一的客观视觉描述")
        save_description.assert_not_called()

    async def test_emoji_post_processing_uses_unified_observation_before_semantic_cache(self) -> None:
        manager = make_image_manager()
        image_base64 = png_base64()
        image_hash = hashlib.md5(base64.b64decode(image_base64)).hexdigest()
        observation = utils_image.VisualObservation(
            description="统一的客观视觉描述",
            image_hash=image_hash,
            image_format="png",
            is_animated=False,
        )
        manager.recognize_image = AsyncMock(return_value=observation)
        semantic_description = (
            "情感：开心；适用场景：当收到好消息时，用于表达开心；"
            "表达意图：积极回应；画面内容：角色举手；画面文字：好；风格/梗：无明确梗或特殊风格"
        )
        fake_emoji_manager = SimpleNamespace(get_emoji_description_by_hash=AsyncMock(return_value=semantic_description))

        with patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager):
            result = await manager.get_emoji_description(image_base64)

        self.assertEqual(result, f"[表情包：{semantic_description}]")
        manager.recognize_image.assert_awaited_once_with(image_base64)
        manager.vlm.generate_response_for_image.assert_not_awaited()

    async def test_emoji_semantic_processing_receives_the_unified_visual_description(self) -> None:
        manager = make_image_manager()
        image_base64 = png_base64()
        image_hash = hashlib.md5(base64.b64decode(image_base64)).hexdigest()
        observation = utils_image.VisualObservation(
            description="人物站在窗前，右手举着写有‘收到’的纸张。",
            image_hash=image_hash,
            image_format="png",
            is_animated=False,
        )
        manager.recognize_image = AsyncMock(return_value=observation)
        manager._save_emoji_file_if_needed = AsyncMock()
        semantic_payload = json.dumps(
            {
                "emotion": ["平静"],
                "scene": "当需要确认消息时，用于表示已经收到",
                "intent": "确认收到信息",
                "content": "人物站在窗前举着纸张",
                "text": "收到",
                "style": "无明确梗或特殊风格",
            },
            ensure_ascii=False,
        )
        semantic_llm = SimpleNamespace(generate_response_async=AsyncMock(return_value=(semantic_payload, None)))
        fake_emoji_manager = SimpleNamespace(get_emoji_description_by_hash=AsyncMock(return_value=None))

        with (
            patch("src.chat.emoji_system.emoji_manager.get_emoji_manager", return_value=fake_emoji_manager),
            patch.object(utils_image.EmojiDescriptionCache, "get_or_none", side_effect=[None, None]),
            patch.object(
                utils_image.EmojiDescriptionCache,
                "get_or_create",
                return_value=(SimpleNamespace(save=Mock()), True),
            ),
            patch.object(utils_image, "LLMRequest", return_value=semantic_llm),
        ):
            await manager.get_emoji_description(image_base64)

        semantic_prompt = semantic_llm.generate_response_async.await_args.args[0]
        self.assertIn(observation.description, semantic_prompt)
        manager.recognize_image.assert_awaited_once_with(image_base64)


if __name__ == "__main__":
    unittest.main()
