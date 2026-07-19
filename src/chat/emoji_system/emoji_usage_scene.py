import asyncio
import json
import time

from dataclasses import dataclass
from typing import Any, Literal

from src.common.database.database_model import EmojiUsageEvent, EmojiUsageScene, Messages
from src.common.logger import get_logger
from src.common.prompt_manager import prompt_manager
from src.config.config import global_config, model_config
from src.llm_models.utils_model import LLMRequest


logger = get_logger("emoji_usage_scene")

MAX_SCENE_LENGTH = 240
MAX_CONTEXT_LENGTH = 6000
MAX_DESCRIPTION_LENGTH = 2000
MAX_SCENES_IN_PROMPT = 32
MAX_MERGE_GROUPS = 16
MAX_CONTEXT_MESSAGES = 32

_learning_tasks: set[asyncio.Task] = set()


def is_bot_self(platform: str, user_id: str) -> bool:
    from src.chat.utils.utils import is_bot_self as check_bot_self

    return check_bot_self(platform, user_id)


@dataclass(frozen=True)
class SceneLearningDecision:
    action: Literal["skip", "attach", "create"]
    scene_id: int | None
    scene: str


@dataclass(frozen=True)
class SceneMergeDecision:
    scene_ids: tuple[int, ...]
    scene: str


def _load_json_object(payload: str) -> dict[str, Any] | None:
    text = str(payload or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    object_start = text.find("{")
    object_end = text.rfind("}")
    if object_start < 0 or object_end <= object_start:
        return None
    try:
        value = json.loads(text[object_start : object_end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _normalize_scene(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip(" \t\r\n\"'")[:MAX_SCENE_LENGTH]


def parse_scene_learning_response(
    payload: str,
    *,
    valid_scene_ids: set[int],
) -> SceneLearningDecision | None:
    data = _load_json_object(payload)
    if data is None:
        return None

    action = data.get("action")
    raw_scene_id = data.get("scene_id")
    scene = _normalize_scene(data.get("scene"))
    if action == "skip":
        if raw_scene_id is not None:
            return None
        return SceneLearningDecision("skip", None, "")
    if action == "create":
        if raw_scene_id is not None or not scene:
            return None
        return SceneLearningDecision("create", None, scene)
    if action == "attach":
        if isinstance(raw_scene_id, bool) or not isinstance(raw_scene_id, int):
            return None
        if raw_scene_id not in valid_scene_ids or not scene:
            return None
        return SceneLearningDecision("attach", raw_scene_id, scene)
    return None


def parse_scene_compaction_response(
    payload: str,
    *,
    valid_scene_ids: set[int],
) -> list[SceneMergeDecision]:
    data = _load_json_object(payload)
    raw_merges = data.get("merges") if data is not None else None
    if not isinstance(raw_merges, list):
        return []

    merges: list[SceneMergeDecision] = []
    claimed_ids: set[int] = set()
    for raw_merge in raw_merges[:MAX_MERGE_GROUPS]:
        if not isinstance(raw_merge, dict):
            continue
        raw_ids = raw_merge.get("scene_ids")
        scene = _normalize_scene(raw_merge.get("scene"))
        if not isinstance(raw_ids, list) or not scene:
            continue
        scene_ids: list[int] = []
        for raw_id in raw_ids:
            if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id in scene_ids:
                scene_ids = []
                break
            scene_ids.append(raw_id)
        scene_id_set = set(scene_ids)
        if len(scene_ids) < 2 or not scene_id_set.issubset(valid_scene_ids) or scene_id_set & claimed_ids:
            continue
        merges.append(SceneMergeDecision(tuple(scene_ids), scene))
        claimed_ids.update(scene_ids)
    return merges


class EmojiUsageSceneLearner:
    """让 LLM 将一次真人表情使用归入稳定的场景集合。"""

    def __init__(self, model: Any | None = None) -> None:
        self.model = model or LLMRequest(
            model_set=model_config.model_task_config.utils,
            request_type="emoji.usage_scene",
        )
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, emoji_hash: str) -> asyncio.Lock:
        lock = self._locks.get(emoji_hash)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[emoji_hash] = lock
        return lock

    @staticmethod
    def _get_scenes(emoji_hash: str) -> list[EmojiUsageScene]:
        return list(
            EmojiUsageScene.select()
            .where(EmojiUsageScene.emoji_hash == emoji_hash)
            .order_by(EmojiUsageScene.sample_count.desc(), EmojiUsageScene.last_active_time.desc())
            .limit(MAX_SCENES_IN_PROMPT)
        )

    @staticmethod
    def _render_scenes(scenes: list[EmojiUsageScene]) -> str:
        if not scenes:
            return "无"
        return "\n".join(
            json.dumps(
                {"id": scene.id, "scene": scene.scene, "sample_count": scene.sample_count},
                ensure_ascii=False,
            )
            for scene in scenes
        )

    async def _generate(self, prompt: str, *, max_tokens: int) -> str | None:
        try:
            response, _ = await self.model.generate_response_async(
                prompt,
                temperature=0.1,
                max_tokens=max_tokens,
            )
        except Exception as error:
            logger.warning(f"真人表情场景学习模型调用失败: {error}")
            return None
        return str(response or "")

    async def learn_scene(
        self,
        emoji_hash: str,
        chat_context: str,
        emoji_description: str,
        emoji_sender: str = "用户",
        *,
        max_scenes: int,
    ) -> EmojiUsageScene | None:
        normalized_hash = " ".join(str(emoji_hash or "").split()).strip()[:128]
        if not normalized_hash:
            return None
        bounded_max_scenes = max(1, min(int(max_scenes), MAX_SCENES_IN_PROMPT))

        async with self._lock_for(normalized_hash):
            scenes = self._get_scenes(normalized_hash)
            prompt = prompt_manager.format_prompt(
                "media.emoji.usage_scene_learning",
                emoji_description=str(emoji_description or "")[:MAX_DESCRIPTION_LENGTH],
                emoji_sender=str(emoji_sender or "用户")[:200],
                chat_context=str(chat_context or "")[-MAX_CONTEXT_LENGTH:],
                existing_usage_scenes=self._render_scenes(scenes),
            )
            response = await self._generate(prompt, max_tokens=400)
            if response is None:
                return None
            decision = parse_scene_learning_response(
                response,
                valid_scene_ids={scene.id for scene in scenes},
            )
            if decision is None:
                logger.warning("真人表情场景学习返回了无效结构，已忽略")
                return None
            if decision.action == "skip":
                return None

            now = time.time()
            if decision.action == "create":
                result = EmojiUsageScene.create(
                    emoji_hash=normalized_hash,
                    scene=decision.scene,
                    sample_count=1,
                    created_at=now,
                    last_active_time=now,
                )
            else:
                result = EmojiUsageScene.get_or_none(
                    (EmojiUsageScene.id == decision.scene_id) & (EmojiUsageScene.emoji_hash == normalized_hash)
                )
                if result is None:
                    return None
                result.scene = decision.scene
                result.sample_count += 1
                result.last_active_time = now
                result.save()

            if (
                EmojiUsageScene.select().where(EmojiUsageScene.emoji_hash == normalized_hash).count()
                > bounded_max_scenes
            ):
                _, scene_id_remap = await self._compact_scenes_unlocked(normalized_hash, bounded_max_scenes)
                result = EmojiUsageScene.get_or_none(
                    (EmojiUsageScene.id == scene_id_remap.get(result.id, result.id))
                    & (EmojiUsageScene.emoji_hash == normalized_hash)
                )
            return result

    async def compact_scenes(self, emoji_hash: str, *, max_scenes: int) -> int:
        normalized_hash = " ".join(str(emoji_hash or "").split()).strip()[:128]
        if not normalized_hash:
            return 0
        bounded_max_scenes = max(1, min(int(max_scenes), MAX_SCENES_IN_PROMPT))
        async with self._lock_for(normalized_hash):
            merged_groups, _ = await self._compact_scenes_unlocked(normalized_hash, bounded_max_scenes)
            return merged_groups

    async def _compact_scenes_unlocked(self, emoji_hash: str, max_scenes: int) -> tuple[int, dict[int, int]]:
        scene_count = EmojiUsageScene.select().where(EmojiUsageScene.emoji_hash == emoji_hash).count()
        if scene_count <= max_scenes:
            return 0, {}
        scenes = self._get_scenes(emoji_hash)
        prompt = prompt_manager.format_prompt(
            "media.emoji.usage_scene_compaction",
            existing_usage_scenes=self._render_scenes(scenes),
            max_scenes=max_scenes,
        )
        response = await self._generate(prompt, max_tokens=700)
        if response is None:
            return 0, {}
        merges = parse_scene_compaction_response(
            response,
            valid_scene_ids={scene.id for scene in scenes},
        )
        merged_groups = 0
        scene_id_remap: dict[int, int] = {}
        database = EmojiUsageScene._meta.database
        for merge in merges:
            with database.atomic():
                group = list(
                    EmojiUsageScene.select().where(
                        (EmojiUsageScene.emoji_hash == emoji_hash) & (EmojiUsageScene.id.in_(merge.scene_ids))
                    )
                )
                if len(group) != len(merge.scene_ids):
                    continue
                by_id = {scene.id: scene for scene in group}
                survivor = by_id[merge.scene_ids[0]]
                survivor.scene = merge.scene
                survivor.sample_count = sum(scene.sample_count for scene in group)
                survivor.last_active_time = max(scene.last_active_time for scene in group)
                survivor.save()
                deleted_scene_ids = merge.scene_ids[1:]
                EmojiUsageEvent.update(scene_id=survivor.id).where(
                    EmojiUsageEvent.scene_id.in_(deleted_scene_ids)
                ).execute()
                EmojiUsageScene.delete().where(EmojiUsageScene.id.in_(deleted_scene_ids)).execute()
                scene_id_remap.update({scene_id: survivor.id for scene_id in merge.scene_ids})
                merged_groups += 1
        return merged_groups, scene_id_remap


emoji_usage_scene_learner = EmojiUsageSceneLearner()


def _get_prior_chat_context(message: Messages, message_count: int) -> str:
    bounded_count = max(0, min(int(message_count), MAX_CONTEXT_MESSAGES))
    if bounded_count == 0:
        return ""

    prior_messages = list(
        Messages.select()
        .where(
            (Messages.chat_id == message.chat_id)
            & ((Messages.time < message.time) | ((Messages.time == message.time) & (Messages.id < message.id)))
        )
        .order_by(Messages.time.desc(), Messages.id.desc())
        .limit(bounded_count)
    )
    lines: list[str] = []
    for prior_message in reversed(prior_messages):
        content = str(prior_message.processed_plain_text or "").strip()
        if not content:
            continue
        sender = str(prior_message.user_nickname or prior_message.user_id or "用户").strip()
        lines.append(f"{sender}: {content}")
    return "\n".join(lines)


async def learn_emoji_usage_event(
    emoji_hash: str,
    message_id: str,
    occurrence_index: int,
    emoji_description: str,
    *,
    chat_id: str | None = None,
    context_message_count: int = 8,
    max_scenes: int = 8,
) -> EmojiUsageEvent | None:
    """学习一次真人表情使用；同一消息 occurrence 只处理一次。"""
    message_query = Messages.select().where(Messages.message_id == str(message_id))
    normalized_chat_id = str(chat_id or "").strip()
    if normalized_chat_id:
        message_query = message_query.where(Messages.chat_id == normalized_chat_id)
    message = message_query.order_by(Messages.time.desc(), Messages.id.desc()).first()
    if message is None or is_bot_self(str(message.user_platform or ""), str(message.user_id or "")):
        return None

    normalized_hash = " ".join(str(emoji_hash or "").split()).strip()[:128]
    if not normalized_hash:
        return None

    event, created = EmojiUsageEvent.get_or_create(
        chat_id=message.chat_id,
        message_id=message.message_id,
        occurrence_index=max(0, int(occurrence_index)),
        emoji_hash=normalized_hash,
        defaults={
            "message_row_id": message.id,
            "user_id": message.user_id,
            "status": "pending",
            "created_at": time.time(),
        },
    )
    if not created:
        return event

    chat_context = _get_prior_chat_context(message, context_message_count)
    if not chat_context:
        event.status = "skipped"
        event.save(only=[EmojiUsageEvent.status])
        return event

    try:
        scene = await emoji_usage_scene_learner.learn_scene(
            normalized_hash,
            chat_context=chat_context,
            emoji_description=emoji_description,
            emoji_sender=str(message.user_nickname or message.user_id or "用户").strip(),
            max_scenes=max_scenes,
        )
    except Exception as error:
        event.status = "failed"
        event.save(only=[EmojiUsageEvent.status])
        logger.warning(f"真人表情场景学习失败，已跳过: {error}")
        return event

    event.status = "learned" if scene is not None else "skipped"
    event.scene_id = getattr(scene, "id", None)
    event.save(only=[EmojiUsageEvent.status, EmojiUsageEvent.scene_id])
    return event


async def _learn_when_message_is_stored(
    emoji_hash: str,
    message_id: str,
    occurrence_index: int,
    emoji_description: str,
    chat_id: str | None,
    context_message_count: int,
    max_scenes: int,
) -> None:
    for attempt in range(6):
        try:
            message_query = Messages.select().where(Messages.message_id == str(message_id))
            if chat_id:
                message_query = message_query.where(Messages.chat_id == chat_id)
            if message_query.exists():
                await learn_emoji_usage_event(
                    emoji_hash,
                    message_id,
                    occurrence_index,
                    emoji_description,
                    chat_id=chat_id,
                    context_message_count=context_message_count,
                    max_scenes=max_scenes,
                )
                return
        except Exception as error:
            logger.warning(f"调度真人表情场景学习失败，已隔离: {error}")
            return
        await asyncio.sleep(0.5 * (attempt + 1))


def schedule_emoji_usage_scene_learning(
    emoji_hash: str,
    message_id: str,
    occurrence_index: int,
    emoji_description: str,
    *,
    chat_id: str | None = None,
) -> None:
    """Best-effort 调度场景学习，不阻塞媒体识别与消息接收。"""
    if not global_config.emoji.usage_scene_enabled:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("当前没有运行中的事件循环，跳过真人表情场景学习调度")
        return

    task = loop.create_task(
        _learn_when_message_is_stored(
            emoji_hash,
            str(message_id),
            max(0, int(occurrence_index)),
            str(emoji_description or ""),
            str(chat_id or "").strip() or None,
            global_config.emoji.usage_scene_context_messages,
            global_config.emoji.usage_scene_max_scenes,
        )
    )
    _learning_tasks.add(task)
    task.add_done_callback(_learning_tasks.discard)
