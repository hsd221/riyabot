import asyncio
import base64
import os
import time
import hashlib
import uuid
import io

from dataclasses import dataclass
from typing import Optional, Tuple, List
from PIL import Image
from rich.traceback import install

from src.chat.emoji_system.emoji_description import (
    build_semantic_emoji_description,
    is_semantic_emoji_description,
)
from src.common.logger import get_logger
from src.common.prompt_manager import prompt_manager
from src.common.database.database import db
from src.common.database.database_model import Images, ImageDescriptions, EmojiDescriptionCache
from src.config.config import global_config, model_config
from src.llm_models.utils_model import LLMRequest

install(extra_lines=3)

logger = get_logger("chat_image")

GIF_DESCRIPTION_CACHE_PREFIX = "[gif-frame-sequence-v1]\n"
GIF_FRAME_BATCH_SIZE = 16
VISION_DESCRIPTION_CACHE_TYPE = "vision_v1"
VISION_DESCRIPTION_MAX_CHARS = 12000
STATIC_VISION_MAX_TOKENS = 3072
ANIMATED_VISION_MIN_TOKENS = 1024
ANIMATED_VISION_TOKENS_PER_FRAME = 128
ANIMATED_VISION_TOKEN_OVERHEAD = 256
MAX_VISION_IMAGE_BYTES = 20 * 1024 * 1024
MAX_VISION_IMAGE_DIMENSION = 8192
MAX_VISION_IMAGE_PIXELS = 40_000_000
MAX_VISION_ANIMATED_FRAMES = 256
MAX_VISION_ANIMATED_TOTAL_PIXELS = 160_000_000
MAX_VISION_FRAME_DIMENSION = 1024


@dataclass(frozen=True)
class VisualObservation:
    """中立视觉识别结果；业务类型由调用方在识别完成后决定。"""

    description: str
    image_hash: str
    image_format: str
    is_animated: bool


def _normalize_image_base64(image_base64: str) -> str:
    if not isinstance(image_base64, str) or not image_base64.strip():
        raise ValueError("图片Base64数据不能为空")

    normalized = image_base64.strip()
    if normalized.startswith("data:"):
        header, separator, payload = normalized.partition(",")
        if not separator or ";base64" not in header.lower():
            raise ValueError("图片Data URL格式无效")
        normalized = payload

    normalized = "".join(normalized.split())
    if not normalized:
        raise ValueError("图片Base64数据不能为空")
    return normalized


def _decode_image_base64(image_base64: str) -> tuple[str, bytes, str, str, bool]:
    normalized = _normalize_image_base64(image_base64)
    max_base64_length = ((MAX_VISION_IMAGE_BYTES + 2) // 3) * 4
    if len(normalized) > max_base64_length:
        raise ValueError("图片文件大小超过识图限制")

    image_bytes = base64.b64decode(normalized, validate=True)
    if not image_bytes:
        raise ValueError("图片数据不能为空")
    if len(image_bytes) > MAX_VISION_IMAGE_BYTES:
        raise ValueError("图片文件大小超过识图限制")

    with Image.open(io.BytesIO(image_bytes)) as image:
        image_format = (image.format or "").lower()
        if not image_format:
            raise ValueError("无法识别图片格式")
        width, height = image.size
        if width <= 0 or height <= 0 or width > MAX_VISION_IMAGE_DIMENSION or height > MAX_VISION_IMAGE_DIMENSION:
            raise ValueError("图片尺寸超过识图限制")
        pixel_count = width * height
        if pixel_count > MAX_VISION_IMAGE_PIXELS:
            raise ValueError("图片像素数量超过识图限制")
        frame_count = max(1, int(getattr(image, "n_frames", 1) or 1))
        is_animated = bool(getattr(image, "is_animated", False) and frame_count > 1)
        if is_animated and frame_count > MAX_VISION_ANIMATED_FRAMES:
            raise ValueError("动态图帧数超过识图限制")
        if is_animated and pixel_count * frame_count > MAX_VISION_ANIMATED_TOTAL_PIXELS:
            raise ValueError("动态图总像素数量超过识图限制")
        image.verify()

    image_hash = hashlib.md5(image_bytes, usedforsecurity=False).hexdigest()
    return normalized, image_bytes, image_hash, image_format, is_animated


def _sanitize_visual_description(description: str) -> str:
    clean_description = " ".join(str(description or "").split()).strip()
    if not clean_description:
        raise RuntimeError("视觉模型返回了空描述")
    clean_description = clean_description.replace("[", "［").replace("]", "］")
    if len(clean_description) > VISION_DESCRIPTION_MAX_CHARS:
        clean_description = f"{clean_description[: VISION_DESCRIPTION_MAX_CHARS - 1].rstrip()}…"
    return clean_description


def write_gif_description_cache(description: str) -> str:
    """为逐帧 GIF 描述添加内部缓存版本标记。"""
    current_description = read_gif_description_cache(description)
    clean_description = current_description if current_description is not None else str(description).strip()
    return f"{GIF_DESCRIPTION_CACHE_PREFIX}{clean_description}"


def read_gif_description_cache(description: Optional[str]) -> Optional[str]:
    """读取当前版本的 GIF 描述，旧版拼图描述返回 None。"""
    if not description:
        return None
    description = str(description)
    if not description.startswith(GIF_DESCRIPTION_CACHE_PREFIX):
        return None
    clean_description = description[len(GIF_DESCRIPTION_CACHE_PREFIX) :].strip()
    return clean_description or None


def get_gif_description_max_tokens(frame_count: int) -> int:
    """为动态画面描述预留随帧数增长的输出空间。"""
    return max(
        ANIMATED_VISION_MIN_TOKENS,
        max(1, frame_count) * ANIMATED_VISION_TOKENS_PER_FRAME + ANIMATED_VISION_TOKEN_OVERHEAD,
    )


async def describe_gif_frames(
    vlm: LLMRequest,
    frames: List[Tuple[str, str]],
    temperature: float,
) -> str:
    """按顺序分批识别动态图片，所有批次复用同一个感知提示词。"""
    if not frames:
        raise ValueError("GIF帧列表不能为空")

    frame_count = len(frames)
    batch_descriptions: List[str] = []
    for batch_start in range(0, frame_count, GIF_FRAME_BATCH_SIZE):
        batch_frames = frames[batch_start : batch_start + GIF_FRAME_BATCH_SIZE]
        frame_start = batch_start + 1
        frame_end = batch_start + len(batch_frames)
        prompt = prompt_manager.format_prompt(
            "media.vision.animated",
            frame_count=frame_count,
            frame_start=frame_start,
            frame_end=frame_end,
            previous_batch_description=batch_descriptions[-1] if batch_descriptions else "无，这是第一批画面。",
        )
        batch_description, _ = await vlm.generate_response_for_images(
            prompt,
            batch_frames,
            temperature=temperature,
            max_tokens=get_gif_description_max_tokens(len(batch_frames)),
            start_index=frame_start,
        )
        batch_descriptions.append(_sanitize_visual_description(batch_description))

    return "\n".join(batch_descriptions)


async def audit_gif_frames(
    vlm: LLMRequest,
    prompt: str,
    frames: List[Tuple[str, str]],
    temperature: float,
    max_tokens: int,
) -> str:
    """按顺序审核全部 GIF 帧批次，任一批次拒绝则返回否。"""
    if not frames:
        raise ValueError("GIF帧列表不能为空")

    for batch_start in range(0, len(frames), GIF_FRAME_BATCH_SIZE):
        batch_frames = frames[batch_start : batch_start + GIF_FRAME_BATCH_SIZE]
        content, _ = await vlm.generate_response_for_images(
            prompt,
            batch_frames,
            temperature=temperature,
            max_tokens=max_tokens,
            start_index=batch_start + 1,
        )
        normalized_result = content.strip().rstrip("。.!！")
        if normalized_result != "是":
            return "否"
    return "是"


def is_animated_image_base64_data(image_base64: str) -> bool:
    """根据实际帧数判断 Base64 图片是否为动态图。"""
    try:
        return _decode_image_base64(image_base64)[-1]
    except Exception:
        return False


class ImageManager:
    _instance = None
    IMAGE_DIR = "data"  # 图像存储根目录

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._ensure_image_dir()

            self._initialized = True
            self.vlm = LLMRequest(model_set=model_config.model_task_config.vlm, request_type="image")
            self._vision_tasks: dict[str, asyncio.Task[str]] = {}

            try:
                db.connect(reuse_if_open=True)
                db.create_tables([Images, ImageDescriptions, EmojiDescriptionCache], safe=True)
            except Exception as e:
                logger.error(f"数据库连接或表创建失败: {e}")

            try:
                self._cleanup_invalid_descriptions()
            except Exception as e:
                logger.warning(f"数据库清理失败: {e}")

            try:
                self._cleanup_emoji_from_image_descriptions()
            except Exception as e:
                logger.warning(f"清理ImageDescriptions中的emoji记录失败: {e}")

            self._initialized = True

    def _ensure_image_dir(self):
        """确保图像存储目录存在"""
        os.makedirs(self.IMAGE_DIR, exist_ok=True)

    @staticmethod
    def _get_description_from_db(image_hash: str, description_type: str) -> Optional[str]:
        """从数据库获取图片描述

        Args:
            image_hash: 图片哈希值
            description_type: 描述缓存命名空间（例如 vision_v1）

        Returns:
            Optional[str]: 描述文本，如果不存在则返回None
        """
        try:
            record = ImageDescriptions.get_or_none(
                (ImageDescriptions.image_description_hash == image_hash) & (ImageDescriptions.type == description_type)
            )
            return record.description if record else None
        except Exception as e:
            logger.error(f"从数据库获取描述失败 (Peewee): {str(e)}")
            return None

    @staticmethod
    def _save_description_to_db(image_hash: str, description: str, description_type: str) -> None:
        """保存图片描述到数据库

        Args:
            image_hash: 图片哈希值
            description: 描述文本
            description_type: 描述缓存命名空间（例如 vision_v1）
        """
        try:
            current_timestamp = time.time()
            defaults = {"description": description, "timestamp": current_timestamp}
            desc_obj, created = ImageDescriptions.get_or_create(
                image_description_hash=image_hash, type=description_type, defaults=defaults
            )
            if not created:  # 如果记录已存在，则更新
                desc_obj.description = description
                desc_obj.timestamp = current_timestamp
                desc_obj.save()
        except Exception as e:
            logger.error(f"保存描述到数据库失败 (Peewee): {str(e)}")

    async def _generate_visual_description(
        self,
        normalized_base64: str,
        image_hash: str,
        image_format: str,
        is_animated: bool,
    ) -> str:
        if is_animated:
            frames = [("png", frame) for frame in self.extract_gif_frames(normalized_base64)]
            if not frames:
                raise RuntimeError("动态图片帧提取失败")
            description = await describe_gif_frames(self.vlm, frames, temperature=0.2)
        else:
            prompt = prompt_manager.get_prompt("media.vision.static")
            description, _ = await self.vlm.generate_response_for_image(
                prompt,
                normalized_base64,
                image_format,
                temperature=0.2,
                max_tokens=STATIC_VISION_MAX_TOKENS,
            )

        clean_description = _sanitize_visual_description(description)
        self._save_description_to_db(image_hash, clean_description, VISION_DESCRIPTION_CACHE_TYPE)
        return clean_description

    async def recognize_image(self, image_base64: str) -> VisualObservation:
        """统一识别静态或动态图片，并按内容哈希共享中立视觉描述。"""

        normalized_base64, _, image_hash, image_format, is_animated = _decode_image_base64(image_base64)
        cached_description = self._get_description_from_db(image_hash, VISION_DESCRIPTION_CACHE_TYPE)
        if cached_description:
            return VisualObservation(
                description=_sanitize_visual_description(cached_description),
                image_hash=image_hash,
                image_format=image_format,
                is_animated=is_animated,
            )

        vision_tasks = getattr(self, "_vision_tasks", None)
        if vision_tasks is None:
            vision_tasks = {}
            self._vision_tasks = vision_tasks

        task = vision_tasks.get(image_hash)
        if task is None:
            task = asyncio.create_task(
                self._generate_visual_description(normalized_base64, image_hash, image_format, is_animated)
            )
            vision_tasks[image_hash] = task

            def cleanup_completed_task(completed_task: asyncio.Task[str]) -> None:
                if vision_tasks.get(image_hash) is completed_task:
                    vision_tasks.pop(image_hash, None)
                if not completed_task.cancelled():
                    completed_task.exception()

            task.add_done_callback(cleanup_completed_task)

        try:
            description = await asyncio.shield(task)
        finally:
            if task.done() and vision_tasks.get(image_hash) is task:
                vision_tasks.pop(image_hash, None)

        return VisualObservation(
            description=description,
            image_hash=image_hash,
            image_format=image_format,
            is_animated=is_animated,
        )

    @staticmethod
    def _cleanup_invalid_descriptions():
        """清理数据库中 description 为空或为 'None' 的记录"""
        invalid_values = ["", "None"]

        # 清理 Images 表
        deleted_images = (
            Images.delete().where((Images.description >> None) | (Images.description << invalid_values)).execute()
        )

        # 清理 ImageDescriptions 表
        deleted_descriptions = (
            ImageDescriptions.delete()
            .where((ImageDescriptions.description >> None) | (ImageDescriptions.description << invalid_values))
            .execute()
        )

        if deleted_images or deleted_descriptions:
            logger.info(f"[清理完成] 删除 Images: {deleted_images} 条, ImageDescriptions: {deleted_descriptions} 条")
        else:
            logger.info("[清理完成] 未发现无效描述记录")

    @staticmethod
    def _cleanup_emoji_from_image_descriptions():
        """清理Images和ImageDescriptions表中type为emoji的记录（已迁移到EmojiDescriptionCache）"""
        try:
            # 清理Images表中type为emoji的记录
            deleted_images = Images.delete().where(Images.type == "emoji").execute()

            # 清理ImageDescriptions表中type为emoji的记录
            deleted_descriptions = ImageDescriptions.delete().where(ImageDescriptions.type == "emoji").execute()

            total_deleted = deleted_images + deleted_descriptions
            if total_deleted > 0:
                logger.info(
                    f"[清理完成] 从Images表中删除 {deleted_images} 条emoji类型记录, "
                    f"从ImageDescriptions表中删除 {deleted_descriptions} 条emoji类型记录, "
                    f"共删除 {total_deleted} 条记录"
                )
            else:
                logger.info("[清理完成] Images和ImageDescriptions表中未发现emoji类型记录")
        except Exception as e:
            logger.error(f"清理Images和ImageDescriptions中的emoji记录时出错: {str(e)}")
            raise

    async def get_emoji_tag(self, image_base64: str) -> str:
        from src.chat.emoji_system.emoji_manager import get_emoji_manager

        emoji_manager = get_emoji_manager()
        if isinstance(image_base64, str):
            image_base64 = image_base64.encode("ascii", errors="ignore").decode("ascii")
        image_bytes = base64.b64decode(image_base64)
        image_hash = hashlib.md5(image_bytes, usedforsecurity=False).hexdigest()
        emoji = await emoji_manager.get_emoji_from_manager(image_hash)
        if not emoji:
            return "[表情包：未知]"
        emotion_list = emoji.emotion
        tag_str = ",".join(emotion_list)
        return f"[表情包：{tag_str}]"

    async def _save_emoji_file_if_needed(self, image_base64: str, image_hash: str, image_format: str) -> None:
        """如果启用了steal_emoji且表情包未注册，保存文件到data/emoji目录

        Args:
            image_base64: 图片的base64编码
            image_hash: 图片的MD5哈希值
            image_format: 图片格式
        """
        if not global_config.emoji.steal_emoji:
            return

        try:
            from src.chat.emoji_system.emoji_manager import EMOJI_DIR
            from src.chat.emoji_system.emoji_manager import get_emoji_manager

            # 确保目录存在
            os.makedirs(EMOJI_DIR, exist_ok=True)

            # 检查是否已存在该表情包（通过哈希值）
            emoji_manager = get_emoji_manager()
            existing_emoji = await emoji_manager.get_emoji_from_manager(image_hash)
            if existing_emoji:
                logger.debug(f"[自动保存] 表情包已注册，跳过保存: {image_hash[:8]}...")
                return

            # 生成文件名：使用哈希值前8位 + 格式
            filename = f"{image_hash[:8]}.{image_format}"
            file_path = os.path.join(EMOJI_DIR, filename)

            # 检查文件是否已存在（可能之前保存过但未注册）
            if not os.path.exists(file_path):
                # 保存文件
                if base64_to_image(image_base64, file_path):
                    logger.info(f"[自动保存] 表情包已保存到 {file_path} (Hash: {image_hash[:8]}...)")
                else:
                    logger.warning(f"[自动保存] 保存表情包文件失败: {file_path}")
            else:
                logger.debug(f"[自动保存] 表情包文件已存在，跳过: {file_path}")
        except Exception as save_error:
            logger.warning(f"[自动保存] 保存表情包文件时出错: {save_error}")

    async def get_emoji_description(self, image_base64: str) -> str:
        """在统一视觉识别后生成或复用表情包多维语义描述。"""
        try:
            observation = await self.recognize_image(image_base64)
            image_hash = observation.image_hash
            image_format = observation.image_format
            is_animated = observation.is_animated

            # 视觉事实已经统一识别；业务层只复用符合当前协议的表情语义缓存。
            if not is_animated:
                try:
                    from src.chat.emoji_system.emoji_manager import get_emoji_manager

                    emoji_manager = get_emoji_manager()
                    description = await emoji_manager.get_emoji_description_by_hash(image_hash)
                    if description and is_semantic_emoji_description(description):
                        logger.debug(f"已注册表情包多维描述命中: hash={image_hash[:8]}")
                        return description if description.startswith("[表情包：") else f"[表情包：{description}]"
                except Exception as e:
                    logger.debug(f"查询EmojiManager时出错: {e}")

            cache_record = None
            try:
                cache_record = EmojiDescriptionCache.get_or_none(EmojiDescriptionCache.emoji_hash == image_hash)
                if cache_record:
                    cached_description = (
                        read_gif_description_cache(cache_record.description)
                        if is_animated
                        else cache_record.description
                    )
                    if cached_description and is_semantic_emoji_description(cached_description):
                        logger.debug(f"表情包多维描述缓存命中: hash={image_hash[:8]}")
                        await self._save_emoji_file_if_needed(image_base64, image_hash, image_format)
                        return f"[表情包：{cached_description}]"
            except Exception as e:
                logger.debug(f"查询EmojiDescriptionCache时出错: {e}")

            # 将中立视觉事实转换为表情包专用语义。
            semantic_llm = LLMRequest(model_set=model_config.model_task_config.utils, request_type="emoji")
            semantic_description, emotions = await build_semantic_emoji_description(
                semantic_llm,
                observation.description,
            )
            emotion_tags = ",".join(emotions)
            logger.debug(f"[emoji识别] 多维描述: {semantic_description[:80]}... -> 情感标签: {emotion_tags}")

            # 再次检查缓存（防止并发情况下其他线程已经保存）
            try:
                latest_cache_record = EmojiDescriptionCache.get_or_none(EmojiDescriptionCache.emoji_hash == image_hash)
                latest_description = (
                    read_gif_description_cache(getattr(latest_cache_record, "description", None))
                    if is_animated
                    else getattr(latest_cache_record, "description", None)
                )
                if latest_description and is_semantic_emoji_description(latest_description):
                    logger.warning(f"生成期间命中并发写入的表情包多维描述: {image_hash[:8]}")
                    await self._save_emoji_file_if_needed(image_base64, image_hash, image_format)
                    return f"[表情包：{latest_description}]"
                cache_record = latest_cache_record or cache_record
            except Exception as e:
                logger.debug(f"再次查询EmojiDescriptionCache时出错: {e}")

            # 保存多维描述和独立情感标签到 emoji_description_cache。
            try:
                current_timestamp = time.time()
                cached_description = (
                    write_gif_description_cache(semantic_description) if is_animated else semantic_description
                )
                if cache_record:
                    cache_record.description = cached_description
                    cache_record.emotion_tags = emotion_tags
                    cache_record.timestamp = current_timestamp
                    cache_record.save()
                else:
                    cache_record, created = EmojiDescriptionCache.get_or_create(
                        emoji_hash=image_hash,
                        defaults={
                            "description": cached_description,
                            "emotion_tags": emotion_tags,
                            "timestamp": current_timestamp,
                        },
                    )
                    if not created:
                        cache_record.description = cached_description
                        cache_record.emotion_tags = emotion_tags
                        cache_record.timestamp = current_timestamp
                        cache_record.save()
                logger.info(f"[缓存保存] 表情包多维描述已保存到EmojiDescriptionCache: {image_hash[:8]}...")
            except Exception as e:
                logger.error(f"保存表情包多维描述缓存失败: {str(e)}")

            # 如果启用了steal_emoji，自动保存表情包文件到data/emoji目录
            await self._save_emoji_file_if_needed(image_base64, image_hash, image_format)

            return f"[表情包：{semantic_description}]"

        except Exception as e:
            logger.error(f"获取表情包描述失败: {str(e)}")
            return "[表情包(处理失败)]"

    async def get_image_description(self, image_base64: str) -> str:
        """统一识别后，将视觉事实作为普通图片描述持久化。"""
        try:
            observation = await self.recognize_image(image_base64)
            normalized_base64 = _normalize_image_base64(image_base64)
            image_bytes = base64.b64decode(normalized_base64, validate=True)
            image_hash = observation.image_hash
            description = observation.description
            existing_image = Images.get_or_none(Images.emoji_hash == image_hash)
            if existing_image:
                existing_image.count = (getattr(existing_image, "count", None) or 0) + 1
                existing_image.description = description
                existing_image.vlm_processed = True
                existing_image.save()
                return f"[图片：{description}]"

            # 保存图片和描述
            current_timestamp = time.time()
            filename = f"{int(current_timestamp)}_{image_hash[:8]}.{observation.image_format}"
            image_dir = os.path.join(self.IMAGE_DIR, "image")
            os.makedirs(image_dir, exist_ok=True)
            file_path = os.path.join(image_dir, filename)

            try:
                # 保存文件
                with open(file_path, "wb") as f:
                    f.write(image_bytes)

                Images.create(
                    image_id=str(uuid.uuid4()),
                    emoji_hash=image_hash,
                    path=file_path,
                    type="image",
                    description=description,
                    timestamp=current_timestamp,
                    vlm_processed=True,
                    count=1,
                )
                logger.debug(f"[数据库] 创建新图片记录: {image_hash[:8]}...")
            except Exception as e:
                logger.error(f"保存图片文件或元数据失败: {str(e)}")

            logger.info(f"[识别完成] 图片描述生成: {description[:50]}...")
            return f"[图片：{description}]"
        except Exception as e:
            logger.error(f"获取图片描述失败: {str(e)}")
            return "[图片(处理失败)]"

    @staticmethod
    def extract_gif_frames(gif_base64: str, target_height: int = 200) -> List[str]:
        """按播放顺序将 GIF 的每一帧提取为独立 PNG 图片。

        Args:
            gif_base64: GIF的base64编码字符串
            target_height: 输出帧的目标高度，默认200像素；小于等于0时保持原尺寸

        Returns:
            List[str]: 按播放顺序排列的 PNG Base64 列表，失败时返回空列表
        """
        try:
            if isinstance(gif_base64, str):
                gif_base64 = gif_base64.encode("ascii", errors="ignore").decode("ascii")
            gif_data = base64.b64decode(gif_base64)
            encoded_frames: List[str] = []
            with Image.open(io.BytesIO(gif_data)) as gif:
                frame_count = getattr(gif, "n_frames", 1)
                for frame_index in range(frame_count):
                    gif.seek(frame_index)
                    frame = gif.convert("RGBA")
                    if frame.width <= 0 or frame.height <= 0:
                        raise ValueError("动态图片帧尺寸无效")

                    scale = target_height / frame.height if target_height > 0 else 1.0
                    scale = min(
                        scale,
                        MAX_VISION_FRAME_DIMENSION / frame.width,
                        MAX_VISION_FRAME_DIMENSION / frame.height,
                    )
                    target_size = (
                        max(1, round(frame.width * scale)),
                        max(1, round(frame.height * scale)),
                    )
                    if frame.size != target_size:
                        frame = frame.resize(target_size, Image.Resampling.LANCZOS)

                    buffer = io.BytesIO()
                    frame.save(buffer, format="PNG", optimize=True)
                    encoded_frames.append(base64.b64encode(buffer.getvalue()).decode("ascii"))

            if not encoded_frames:
                logger.warning("GIF中没有找到任何帧")
            return encoded_frames
        except MemoryError:
            logger.error("GIF帧提取失败: 内存不足，可能是GIF太大或帧数太多")
            return []
        except Exception as e:
            logger.error(f"GIF帧提取失败: {str(e)}", exc_info=True)
            return []

    async def process_image(self, image_base64: str) -> Tuple[str, str]:
        """统一识别后持久化普通图片，并返回图片ID和消息标记。

        Args:
            image_base64: 图片的base64编码

        Returns:
            Tuple[str, str]: (图片ID, 描述)
        """
        try:
            observation = await self.recognize_image(image_base64)
            normalized_base64 = _normalize_image_base64(image_base64)
            image_bytes = base64.b64decode(normalized_base64, validate=True)
            image_hash = observation.image_hash

            if existing_image := Images.get_or_none(Images.emoji_hash == image_hash):
                image_id = getattr(existing_image, "image_id", "") or str(uuid.uuid4())
                existing_image.image_id = image_id
                existing_image.count = (getattr(existing_image, "count", None) or 0) + 1
                existing_image.description = observation.description
                existing_image.vlm_processed = True
                existing_image.save()
                return image_id, f"[picid:{image_id}]"

            image_id = str(uuid.uuid4())

            # 保存新图片
            current_timestamp = time.time()
            image_dir = os.path.join(self.IMAGE_DIR, "images")
            os.makedirs(image_dir, exist_ok=True)
            filename = f"{image_id}.{observation.image_format}"
            file_path = os.path.join(image_dir, filename)

            # 保存文件
            with open(file_path, "wb") as f:
                f.write(image_bytes)

            # 保存到数据库
            Images.create(
                image_id=image_id,
                emoji_hash=image_hash,
                path=file_path,
                type="image",
                description=observation.description,
                timestamp=current_timestamp,
                vlm_processed=True,
                count=1,
            )

            return image_id, f"[picid:{image_id}]"

        except Exception as e:
            logger.error(f"处理图片失败: {str(e)}")
            return "", "[图片]"


# 创建全局单例
image_manager = None


def get_image_manager() -> ImageManager:
    """获取全局图片管理器单例"""
    global image_manager
    if image_manager is None:
        image_manager = ImageManager()
    return image_manager


def image_path_to_base64(image_path: str) -> str:
    """将图片路径转换为base64编码
    Args:
        image_path: 图片文件路径
    Returns:
        str: base64编码的图片数据
    Raises:
        FileNotFoundError: 当图片文件不存在时
        IOError: 当读取图片文件失败时
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    with open(image_path, "rb") as f:
        if image_data := f.read():
            return base64.b64encode(image_data).decode("utf-8")
        else:
            raise IOError(f"读取图片文件失败: {image_path}")


def base64_to_image(image_base64: str, output_path: str) -> bool:
    """将base64编码的图片保存为文件

    Args:
        image_base64: 图片的base64编码
        output_path: 输出文件路径

    Returns:
        bool: 是否成功保存

    Raises:
        ValueError: 当base64编码无效时
        IOError: 当保存文件失败时
    """
    try:
        # 确保base64字符串只包含ASCII字符
        if isinstance(image_base64, str):
            image_base64 = image_base64.encode("ascii", errors="ignore").decode("ascii")

        # 解码base64
        image_bytes = base64.b64decode(image_base64)

        # 确保输出目录存在
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        # 保存文件
        with open(output_path, "wb") as f:
            f.write(image_bytes)

        return True

    except Exception as e:
        logger.error(f"保存base64图片失败: {e}")
        return False
