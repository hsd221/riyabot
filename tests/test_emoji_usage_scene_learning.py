import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from peewee import IntegrityError, SqliteDatabase

from src.chat.emoji_system.emoji_usage_scene import (
    EmojiUsageSceneLearner,
    parse_scene_compaction_response,
    parse_scene_learning_response,
)
from src.common.database.database_model import EmojiUsageEvent, EmojiUsageScene


class EmojiUsageSceneParserTest(unittest.TestCase):
    def test_learning_response_accepts_only_bounded_valid_operations(self) -> None:
        attach = parse_scene_learning_response(
            json.dumps(
                {
                    "action": "attach",
                    "scene_id": 7,
                    "scene": "  对方自嘲失败时，\n用于轻松接梗  ",
                },
                ensure_ascii=False,
            ),
            valid_scene_ids={7},
        )

        self.assertIsNotNone(attach)
        self.assertEqual(attach.action, "attach")
        self.assertEqual(attach.scene_id, 7)
        self.assertEqual(attach.scene, "对方自嘲失败时， 用于轻松接梗")

        create = parse_scene_learning_response(
            '{"action":"create","scene_id":null,"scene":"表达无奈"}',
            valid_scene_ids=set(),
        )
        self.assertIsNotNone(create)
        self.assertEqual(create.action, "create")
        self.assertIsNone(create.scene_id)

        skipped = parse_scene_learning_response(
            '{"action":"skip","scene_id":null,"scene":""}',
            valid_scene_ids={7},
        )
        self.assertIsNotNone(skipped)
        self.assertEqual(skipped.action, "skip")

        invalid_payloads = [
            "not-json",
            '{"action":"delete","scene_id":7,"scene":"x"}',
            '{"action":"attach","scene_id":99,"scene":"x"}',
            '{"action":"attach","scene_id":7,"scene":""}',
            '{"action":"create","scene_id":7,"scene":"x"}',
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.assertIsNone(parse_scene_learning_response(payload, valid_scene_ids={7}))

    def test_compaction_response_rejects_unknown_overlapping_or_singleton_groups(self) -> None:
        merges = parse_scene_compaction_response(
            json.dumps(
                {
                    "merges": [
                        {"scene_ids": [1, 2], "scene": "对方自嘲时轻松接梗"},
                        {"scene_ids": [2, 3], "scene": "重叠分组"},
                        {"scene_ids": [3], "scene": "单个场景"},
                        {"scene_ids": [3, 99], "scene": "未知场景"},
                    ]
                },
                ensure_ascii=False,
            ),
            valid_scene_ids={1, 2, 3},
        )

        self.assertEqual(len(merges), 1)
        self.assertEqual(merges[0].scene_ids, (1, 2))
        self.assertEqual(merges[0].scene, "对方自嘲时轻松接梗")


class EmojiUsageSceneLearnerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.database = SqliteDatabase(":memory:")
        self.models = [EmojiUsageScene, EmojiUsageEvent]
        self.original_databases = {model: model._meta.database for model in self.models}
        self.database.bind(self.models, bind_refs=False, bind_backrefs=False)
        self.database.connect()
        self.database.create_tables(self.models)

    def tearDown(self) -> None:
        self.database.drop_tables(self.models)
        self.database.close()
        for model, database in self.original_databases.items():
            model._meta.set_database(database)

    async def test_learn_scene_attaches_to_existing_scene_and_updates_summary(self) -> None:
        existing = EmojiUsageScene.create(
            emoji_hash="hash-a",
            scene="对方自嘲失败时接梗",
            sample_count=2,
            created_at=1.0,
            last_active_time=1.0,
        )
        model = SimpleNamespace(
            generate_response_async=AsyncMock(
                return_value=(
                    json.dumps(
                        {
                            "action": "attach",
                            "scene_id": existing.id,
                            "scene": "对方自嘲或吐槽失败时，用于轻松接梗",
                        },
                        ensure_ascii=False,
                    ),
                    None,
                )
            )
        )
        learner = EmojiUsageSceneLearner(model=model)

        result = await learner.learn_scene(
            emoji_hash="hash-a",
            chat_context="Alice：我又把代码写崩了\nBob：确实很有你的",
            emoji_description="熊猫捂嘴笑，文字为又写崩了",
            emoji_sender="Bob",
            max_scenes=8,
        )

        self.assertIsNotNone(result)
        existing = EmojiUsageScene.get_by_id(existing.id)
        self.assertEqual(existing.sample_count, 3)
        self.assertEqual(existing.scene, "对方自嘲或吐槽失败时，用于轻松接梗")
        prompt = model.generate_response_async.await_args.args[0]
        self.assertIn(f'"id": {existing.id}', prompt)
        self.assertIn("我又把代码写崩了", prompt)
        self.assertIn("熊猫捂嘴笑", prompt)
        self.assertIn("【本次表情发送者】\nBob", prompt)

    async def test_learn_scene_creates_skips_and_ignores_invalid_model_output(self) -> None:
        model = SimpleNamespace(
            generate_response_async=AsyncMock(
                side_effect=[
                    ('{"action":"create","scene_id":null,"scene":"对方抱怨反复修改时表示无奈"}', None),
                    ('{"action":"skip","scene_id":null,"scene":""}', None),
                    ('{"action":"attach","scene_id":999,"scene":"无效引用"}', None),
                ]
            )
        )
        learner = EmojiUsageSceneLearner(model=model)

        created = await learner.learn_scene("hash-a", "需求今天改了八次", "角色叹气", max_scenes=8)
        skipped = await learner.learn_scene("hash-a", "", "角色叹气", max_scenes=8)
        invalid = await learner.learn_scene("hash-a", "普通聊天", "角色叹气", max_scenes=8)

        self.assertIsNotNone(created)
        self.assertEqual(created.sample_count, 1)
        self.assertIsNone(skipped)
        self.assertIsNone(invalid)
        self.assertEqual(EmojiUsageScene.select().count(), 1)

    async def test_compact_scenes_merges_only_llm_confirmed_groups_and_preserves_counts(self) -> None:
        first = EmojiUsageScene.create(
            emoji_hash="hash-a",
            scene="对方自嘲失败时接梗",
            sample_count=3,
            created_at=1.0,
            last_active_time=2.0,
        )
        second = EmojiUsageScene.create(
            emoji_hash="hash-a",
            scene="对方吐槽自己没做好时调侃回应",
            sample_count=2,
            created_at=2.0,
            last_active_time=3.0,
        )
        third = EmojiUsageScene.create(
            emoji_hash="hash-a",
            scene="对明显假话进行轻微嘲讽",
            sample_count=4,
            created_at=3.0,
            last_active_time=4.0,
        )
        event = EmojiUsageEvent.create(
            emoji_hash="hash-a",
            message_row_id=12,
            message_id="message-1",
            occurrence_index=0,
            chat_id="chat-a",
            user_id="user-a",
            scene_id=second.id,
            status="learned",
            created_at=5.0,
        )
        model = SimpleNamespace(
            generate_response_async=AsyncMock(
                return_value=(
                    json.dumps(
                        {
                            "merges": [
                                {
                                    "scene_ids": [first.id, second.id],
                                    "scene": "对方自嘲或吐槽失败时，用于轻松接梗",
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    None,
                )
            )
        )
        learner = EmojiUsageSceneLearner(model=model)

        merged_count = await learner.compact_scenes("hash-a", max_scenes=2)

        self.assertEqual(merged_count, 1)
        self.assertEqual(EmojiUsageScene.select().where(EmojiUsageScene.emoji_hash == "hash-a").count(), 2)
        merged = EmojiUsageScene.get_by_id(first.id)
        self.assertEqual(merged.sample_count, 5)
        self.assertEqual(merged.scene, "对方自嘲或吐槽失败时，用于轻松接梗")
        self.assertFalse(EmojiUsageScene.select().where(EmojiUsageScene.id == second.id).exists())
        self.assertTrue(EmojiUsageScene.select().where(EmojiUsageScene.id == third.id).exists())
        self.assertEqual(EmojiUsageEvent.get_by_id(event.id).scene_id, first.id)

    async def test_learn_scene_returns_survivor_when_compaction_merges_attached_scene(self) -> None:
        survivor = EmojiUsageScene.create(
            emoji_hash="hash-a",
            scene="对方自嘲失败时接梗",
            sample_count=3,
            created_at=1.0,
            last_active_time=2.0,
        )
        attached = EmojiUsageScene.create(
            emoji_hash="hash-a",
            scene="对方吐槽自己没做好时调侃回应",
            sample_count=2,
            created_at=2.0,
            last_active_time=3.0,
        )
        EmojiUsageScene.create(
            emoji_hash="hash-a",
            scene="对明显假话进行轻微嘲讽",
            sample_count=4,
            created_at=3.0,
            last_active_time=4.0,
        )
        model = SimpleNamespace(
            generate_response_async=AsyncMock(
                side_effect=[
                    (
                        json.dumps(
                            {
                                "action": "attach",
                                "scene_id": attached.id,
                                "scene": "对方自嘲或吐槽失败时，用于轻松接梗",
                            },
                            ensure_ascii=False,
                        ),
                        None,
                    ),
                    (
                        json.dumps(
                            {
                                "merges": [
                                    {
                                        "scene_ids": [survivor.id, attached.id],
                                        "scene": "对方自嘲或吐槽失败时，用于轻松接梗",
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        ),
                        None,
                    ),
                ]
            )
        )
        learner = EmojiUsageSceneLearner(model=model)

        result = await learner.learn_scene(
            "hash-a",
            "我又把事情做砸了",
            "熊猫捂嘴笑",
            max_scenes=2,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.id, survivor.id)
        self.assertTrue(EmojiUsageScene.select().where(EmojiUsageScene.id == result.id).exists())
        self.assertFalse(EmojiUsageScene.select().where(EmojiUsageScene.id == attached.id).exists())

    async def test_compaction_uses_total_scene_count_beyond_the_prompt_window(self) -> None:
        scenes = [
            EmojiUsageScene.create(
                emoji_hash="hash-a",
                scene=f"真人使用场景 {index}",
                sample_count=1,
                created_at=float(index),
                last_active_time=float(index),
            )
            for index in range(33)
        ]
        survivor = scenes[-1]
        merged_away = scenes[-2]
        model = SimpleNamespace(
            generate_response_async=AsyncMock(
                return_value=(
                    json.dumps(
                        {
                            "merges": [
                                {
                                    "scene_ids": [survivor.id, merged_away.id],
                                    "scene": "合并后的真人使用场景",
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    None,
                )
            )
        )
        learner = EmojiUsageSceneLearner(model=model)

        merged_count = await learner.compact_scenes("hash-a", max_scenes=32)

        self.assertEqual(merged_count, 1)
        self.assertEqual(EmojiUsageScene.select().where(EmojiUsageScene.emoji_hash == "hash-a").count(), 32)
        model.generate_response_async.assert_awaited_once()

    def test_usage_events_are_idempotent_per_message_occurrence(self) -> None:
        event_data = {
            "emoji_hash": "hash-a",
            "message_row_id": 12,
            "message_id": "message-1",
            "occurrence_index": 0,
            "chat_id": "chat-a",
            "user_id": "user-a",
            "status": "pending",
            "created_at": time.time(),
        }
        event = EmojiUsageEvent.create(**event_data)

        self.assertEqual(event.status, "pending")
        with self.assertRaises(IntegrityError):
            EmojiUsageEvent.create(**event_data)


if __name__ == "__main__":
    unittest.main()
