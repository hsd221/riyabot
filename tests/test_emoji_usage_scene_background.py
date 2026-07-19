import base64
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from peewee import SqliteDatabase

from src.chat.emoji_system import emoji_usage_scene
from src.chat.message_receive import media_background
from src.common.database.database_model import EmojiUsageEvent, EmojiUsageScene, Messages


def create_message(
    message_id: str,
    *,
    row_time: float,
    chat_id: str = "chat-a",
    user_id: str = "user-a",
    content: str = "消息",
) -> Messages:
    return Messages.create(
        message_id=message_id,
        time=row_time,
        chat_id=chat_id,
        chat_info_stream_id=chat_id,
        chat_info_platform="qq",
        chat_info_user_platform="qq",
        chat_info_user_id="chat-user",
        chat_info_user_nickname="Chat User",
        chat_info_create_time=1.0,
        chat_info_last_active_time=row_time,
        user_platform="qq",
        user_id=user_id,
        user_nickname=user_id,
        processed_plain_text=content,
        is_emoji="[表情包" in content,
    )


class EmojiUsageSceneEventLearningTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.database = SqliteDatabase(":memory:")
        self.models = [Messages, EmojiUsageScene, EmojiUsageEvent]
        self.original_databases = {model: model._meta.database for model in self.models}
        self.database.bind(self.models, bind_refs=False, bind_backrefs=False)
        self.database.connect()
        self.database.create_tables(self.models)

    def tearDown(self) -> None:
        self.database.drop_tables(self.models)
        self.database.close()
        for model, database in self.original_databases.items():
            model._meta.set_database(database)

    async def test_event_uses_only_prior_messages_from_the_same_chat_in_chronological_order(self) -> None:
        create_message("old-1", row_time=1.0, content="第一条上下文")
        create_message("other-chat", row_time=2.0, chat_id="chat-b", content="其他群消息")
        create_message("old-2", row_time=3.0, content="第二条上下文")
        current = create_message("emoji-message", row_time=4.0, content="[表情包：角色叹气]")
        create_message("future", row_time=5.0, content="未来消息")
        learned_scene = SimpleNamespace(id=9)

        with (
            patch.object(
                emoji_usage_scene.emoji_usage_scene_learner,
                "learn_scene",
                new=AsyncMock(return_value=learned_scene),
            ) as learn_scene,
            patch.object(emoji_usage_scene, "is_bot_self", return_value=False),
        ):
            event = await emoji_usage_scene.learn_emoji_usage_event(
                emoji_hash="hash-a",
                message_id=current.message_id,
                occurrence_index=0,
                emoji_description="[表情包：角色叹气]",
                context_message_count=8,
                max_scenes=8,
            )

        self.assertIsNotNone(event)
        self.assertEqual(event.status, "learned")
        self.assertEqual(event.scene_id, 9)
        learn_scene.assert_awaited_once()
        context = learn_scene.await_args.kwargs["chat_context"]
        self.assertLess(context.index("第一条上下文"), context.index("第二条上下文"))
        self.assertNotIn("其他群消息", context)
        self.assertNotIn("未来消息", context)
        self.assertNotIn("角色叹气", context)
        self.assertEqual(learn_scene.await_args.kwargs["emoji_sender"], current.user_nickname)

    async def test_event_is_idempotent_and_skips_bot_or_contextless_messages(self) -> None:
        current = create_message("emoji-message", row_time=2.0, content="[表情包：角色叹气]")
        learner = AsyncMock(return_value=SimpleNamespace(id=3))

        with (
            patch.object(emoji_usage_scene.emoji_usage_scene_learner, "learn_scene", new=learner),
            patch.object(emoji_usage_scene, "is_bot_self", return_value=False),
        ):
            first = await emoji_usage_scene.learn_emoji_usage_event(
                "hash-a", current.message_id, 0, "角色叹气", context_message_count=8, max_scenes=8
            )
            second = await emoji_usage_scene.learn_emoji_usage_event(
                "hash-a", current.message_id, 0, "角色叹气", context_message_count=8, max_scenes=8
            )

        self.assertEqual(first.status, "skipped")
        self.assertEqual(second.id, first.id)
        learner.assert_not_awaited()
        self.assertEqual(EmojiUsageEvent.select().count(), 1)

        bot_message = create_message("bot-emoji", row_time=3.0, user_id="bot", content="[表情包：笑]")
        with (
            patch.object(emoji_usage_scene.emoji_usage_scene_learner, "learn_scene", new=learner),
            patch.object(emoji_usage_scene, "is_bot_self", return_value=True),
        ):
            bot_event = await emoji_usage_scene.learn_emoji_usage_event(
                "hash-b", bot_message.message_id, 0, "笑", context_message_count=8, max_scenes=8
            )

        self.assertIsNone(bot_event)
        self.assertEqual(EmojiUsageEvent.select().count(), 1)

    async def test_event_uses_chat_id_to_resolve_duplicate_platform_message_ids(self) -> None:
        create_message("context-a", row_time=1.0, chat_id="chat-a", content="甲群上下文")
        create_message("context-b", row_time=2.0, chat_id="chat-b", content="乙群上下文")
        target = create_message(
            "duplicate-message-id",
            row_time=3.0,
            chat_id="chat-b",
            content="[表情包：乙群表情]",
        )
        create_message(
            "duplicate-message-id",
            row_time=4.0,
            chat_id="chat-a",
            content="[表情包：甲群表情]",
        )
        learner = AsyncMock(return_value=SimpleNamespace(id=7))

        with (
            patch.object(emoji_usage_scene.emoji_usage_scene_learner, "learn_scene", new=learner),
            patch.object(emoji_usage_scene, "is_bot_self", return_value=False),
        ):
            event = await emoji_usage_scene.learn_emoji_usage_event(
                "hash-a",
                target.message_id,
                0,
                "乙群表情",
                chat_id="chat-b",
                context_message_count=8,
                max_scenes=8,
            )

        self.assertIsNotNone(event)
        self.assertEqual(event.message_row_id, target.id)
        self.assertEqual(event.chat_id, "chat-b")
        context = learner.await_args.kwargs["chat_context"]
        self.assertIn("乙群上下文", context)
        self.assertNotIn("甲群上下文", context)


class EmojiUsageSceneMediaSchedulingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        media_background._media_task_states.clear()
        media_background._message_media_refs.clear()
        media_background._backfill_locks.clear()

    def tearDown(self) -> None:
        media_background._media_task_states.clear()
        media_background._message_media_refs.clear()
        media_background._backfill_locks.clear()

    async def test_cached_and_already_completed_emojis_schedule_each_message_occurrence(self) -> None:
        media_data = base64.b64encode(b"same-emoji").decode("ascii")
        description = "[表情包：真人常用反应图]"

        with (
            patch.object(media_background, "_load_cached_media_result", return_value=description),
            patch.object(media_background, "_schedule_placeholder_backfill"),
            patch.object(media_background, "schedule_emoji_usage_scene_learning") as schedule_learning,
        ):
            media_background._schedule_media_task("emoji", media_data, "message-1", chat_id="chat-1")
            media_background._schedule_media_task("emoji", media_data, "message-2", chat_id="chat-2")

        emoji_hash = media_background._hash_media_data(media_data)
        self.assertEqual(
            schedule_learning.call_args_list,
            [
                unittest.mock.call(emoji_hash, "message-1", 0, description, chat_id="chat-1"),
                unittest.mock.call(emoji_hash, "message-2", 0, description, chat_id="chat-2"),
            ],
        )

    async def test_new_analysis_schedules_all_occurrences_without_blocking_backfill(self) -> None:
        media_data = base64.b64encode(b"new-emoji").decode("ascii")
        task_key = media_background._make_task_key("emoji", media_data)
        state = media_background._MediaTaskState(kind="emoji", media_hash=task_key.split(":", 1)[1])
        state.message_refs = [("message-1", 0, "chat-1"), ("message-1", 1, "chat-1")]
        media_background._media_task_states[task_key] = state

        with (
            patch.object(media_background, "_analyze_media", new=AsyncMock(return_value="[表情包：描述]")),
            patch.object(media_background, "_schedule_placeholder_backfill") as schedule_backfill,
            patch.object(media_background, "schedule_emoji_usage_scene_learning") as schedule_learning,
        ):
            await media_background._run_media_task(task_key, media_data)

        self.assertEqual(schedule_backfill.call_count, 2)
        self.assertEqual(schedule_learning.call_count, 2)
        schedule_learning.assert_any_call(
            state.media_hash,
            "message-1",
            0,
            "[表情包：描述]",
            chat_id="chat-1",
        )
        schedule_learning.assert_any_call(
            state.media_hash,
            "message-1",
            1,
            "[表情包：描述]",
            chat_id="chat-1",
        )


class EmojiUsageSceneSchedulingConfigTest(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_uses_configured_context_and_scene_limits_and_can_be_disabled(self) -> None:
        enabled_config = SimpleNamespace(
            emoji=SimpleNamespace(
                usage_scene_enabled=True,
                usage_scene_context_messages=12,
                usage_scene_max_scenes=6,
            )
        )
        with (
            patch.object(emoji_usage_scene, "global_config", enabled_config),
            patch.object(
                emoji_usage_scene,
                "_learn_when_message_is_stored",
                new=AsyncMock(),
            ) as learn_when_stored,
        ):
            emoji_usage_scene.schedule_emoji_usage_scene_learning(
                "hash-a",
                "message-1",
                0,
                "描述",
                chat_id="chat-a",
            )
            await asyncio.gather(*tuple(emoji_usage_scene._learning_tasks))

        learn_when_stored.assert_awaited_once_with("hash-a", "message-1", 0, "描述", "chat-a", 12, 6)

        disabled_config = SimpleNamespace(emoji=SimpleNamespace(usage_scene_enabled=False))
        with (
            patch.object(emoji_usage_scene, "global_config", disabled_config),
            patch.object(emoji_usage_scene, "_learn_when_message_is_stored", new=AsyncMock()) as disabled_learner,
        ):
            emoji_usage_scene.schedule_emoji_usage_scene_learning("hash-a", "message-2", 0, "描述")
            await asyncio.sleep(0)

        disabled_learner.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
