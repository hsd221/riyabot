import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from peewee import SqliteDatabase

from src.chat.emoji_system.emoji_manager import EmojiManager
from src.chat.emoji_system.emoji_vector_index import EmojiUsageSceneVectorMatch
from src.common.database.database_model import Emoji, EmojiUsageScene
from src.plugin_system.apis import emoji_api


def make_emoji(emoji_hash: str) -> SimpleNamespace:
    return SimpleNamespace(
        hash=emoji_hash,
        full_path=f"/tmp/{emoji_hash}.png",
        description=f"描述-{emoji_hash}",
        is_deleted=False,
    )


class EmojiCandidateRankingTest(unittest.IsolatedAsyncioTestCase):
    async def test_emotion_and_human_scene_recall_are_combined_before_top_n(self) -> None:
        emoji_a = make_emoji("emoji-a")
        emoji_b = make_emoji("emoji-b")
        emoji_c = make_emoji("emoji-c")
        emoji_d = make_emoji("emoji-d")
        manager = SimpleNamespace(
            get_emoji_candidates_by_vector=AsyncMock(
                return_value=[
                    (emoji_a, "调侃", 0.9),
                    (emoji_b, "轻松", 0.7),
                    (emoji_c, "幽默", 0.8),
                ]
            ),
            get_emoji_candidates_by_scene_vector=AsyncMock(
                return_value=[
                    (emoji_b, ("对方自嘲时接梗", "对方犯小错时调侃"), 0.95),
                    (emoji_d, ("对方自嘲时表示认同",), 0.85),
                ]
            ),
            record_usage=Mock(),
        )

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "image_path_to_base64", side_effect=lambda path: f"base64:{path}"),
        ):
            candidates = await emoji_api.get_ranked_candidates(
                emotion="轻松调侃",
                scene="对方自嘲失败，准备轻松接梗",
                count=3,
                scene_weight=0.6,
            )

        self.assertIsNotNone(candidates)
        self.assertEqual([candidate.emoji_hash for candidate in candidates or []], ["emoji-b", "emoji-d", "emoji-a"])
        self.assertAlmostEqual((candidates or [])[0].emotion_score or 0.0, 0.7)
        self.assertAlmostEqual((candidates or [])[0].scene_score or 0.0, 0.95)
        self.assertAlmostEqual((candidates or [])[0].combined_score, 0.85)
        self.assertEqual((candidates or [])[0].usage_scenes, ("对方自嘲时接梗", "对方犯小错时调侃"))
        self.assertIsNone((candidates or [])[1].emotion_score)
        self.assertIsNone((candidates or [])[2].scene_score)
        manager.record_usage.assert_not_called()

    async def test_ranked_candidates_fall_back_only_when_both_vector_paths_are_unavailable(self) -> None:
        emoji = make_emoji("emoji-a")
        manager = SimpleNamespace(
            get_emoji_candidates_by_vector=AsyncMock(return_value=[(emoji, "安慰", 0.88)]),
            get_emoji_candidates_by_scene_vector=AsyncMock(return_value=None),
        )
        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "image_path_to_base64", return_value="base64-a"),
        ):
            candidates = await emoji_api.get_ranked_candidates("温柔安慰", "对方很失落", count=8)

        self.assertEqual([candidate.emoji_hash for candidate in candidates or []], ["emoji-a"])

        manager.get_emoji_candidates_by_vector.return_value = None
        with patch.object(emoji_api, "get_emoji_manager", return_value=manager):
            self.assertIsNone(await emoji_api.get_ranked_candidates("温柔安慰", "对方很失落", count=8))

    async def test_empty_scene_does_not_mask_unavailable_emotion_recall(self) -> None:
        manager = SimpleNamespace(
            get_emoji_candidates_by_vector=AsyncMock(return_value=None),
            get_emoji_candidates_by_scene_vector=AsyncMock(),
        )

        with patch.object(emoji_api, "get_emoji_manager", return_value=manager):
            candidates = await emoji_api.get_ranked_candidates(
                "温柔安慰",
                "",
                count=8,
                scene_weight=0.0,
            )

        self.assertIsNone(candidates)
        manager.get_emoji_candidates_by_scene_vector.assert_not_awaited()

    async def test_zero_scene_weight_uses_only_emotion_recall(self) -> None:
        emotion_emoji = make_emoji("emotion")
        scene_emoji = make_emoji("scene")
        manager = SimpleNamespace(
            get_emoji_candidates_by_vector=AsyncMock(return_value=[(emotion_emoji, "安慰", 0.8)]),
            get_emoji_candidates_by_scene_vector=AsyncMock(return_value=[(scene_emoji, ("对方难过时安慰",), 0.99)]),
        )

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "image_path_to_base64", side_effect=lambda path: f"base64:{path}"),
        ):
            candidates = await emoji_api.get_ranked_candidates(
                "温柔安慰",
                "对方很难过",
                count=8,
                scene_weight=0.0,
            )

        self.assertEqual([candidate.emoji_hash for candidate in candidates or []], ["emotion"])
        manager.get_emoji_candidates_by_scene_vector.assert_not_awaited()

    async def test_full_scene_weight_uses_only_scene_recall(self) -> None:
        emotion_emoji = make_emoji("emotion")
        scene_emoji = make_emoji("scene")
        manager = SimpleNamespace(
            get_emoji_candidates_by_vector=AsyncMock(return_value=[(emotion_emoji, "安慰", 0.99)]),
            get_emoji_candidates_by_scene_vector=AsyncMock(return_value=[(scene_emoji, ("对方难过时安慰",), 0.8)]),
        )

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "image_path_to_base64", side_effect=lambda path: f"base64:{path}"),
        ):
            candidates = await emoji_api.get_ranked_candidates(
                "温柔安慰",
                "对方很难过",
                count=8,
                scene_weight=1.0,
            )

        self.assertEqual([candidate.emoji_hash for candidate in candidates or []], ["scene"])
        manager.get_emoji_candidates_by_vector.assert_not_awaited()

    async def test_candidate_human_scenes_are_bounded_for_the_final_prompt(self) -> None:
        emoji = make_emoji("emoji-a")
        manager = SimpleNamespace(
            get_emoji_candidates_by_vector=AsyncMock(return_value=[]),
            get_emoji_candidates_by_scene_vector=AsyncMock(
                return_value=[(emoji, tuple(f"真人场景-{index}" for index in range(10)), 0.9)]
            ),
        )

        with (
            patch.object(emoji_api, "get_emoji_manager", return_value=manager),
            patch.object(emoji_api, "image_path_to_base64", return_value="base64-a"),
        ):
            candidates = await emoji_api.get_ranked_candidates("轻松调侃", "对方正在自嘲", count=8)

        self.assertEqual((candidates or [])[0].usage_scenes, tuple(f"真人场景-{index}" for index in range(4)))


class EmojiManagerSceneRankingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.database = SqliteDatabase(":memory:")
        self.original_database = EmojiUsageScene._meta.database
        self.database.bind([EmojiUsageScene], bind_refs=False, bind_backrefs=False)
        self.database.connect()
        self.database.create_tables([EmojiUsageScene])

    def tearDown(self) -> None:
        self.database.drop_tables([EmojiUsageScene])
        self.database.close()
        EmojiUsageScene._meta.set_database(self.original_database)

    async def test_scene_recall_uses_the_best_scene_score_per_emoji(self) -> None:
        emoji_a = make_emoji("emoji-a")
        emoji_b = make_emoji("emoji-b")
        scene_a_low = EmojiUsageScene.create(
            emoji_hash="emoji-a",
            scene="对方认真批评时道歉",
            sample_count=1,
            created_at=1.0,
            last_active_time=1.0,
        )
        scene_a_high = EmojiUsageScene.create(
            emoji_hash="emoji-a",
            scene="对方自嘲时轻松接梗",
            sample_count=2,
            created_at=2.0,
            last_active_time=2.0,
        )
        scene_b = EmojiUsageScene.create(
            emoji_hash="emoji-b",
            scene="对方犯小错时调侃",
            sample_count=1,
            created_at=3.0,
            last_active_time=3.0,
        )
        scene_a_frequent_but_less_relevant = EmojiUsageScene.create(
            emoji_hash="emoji-a",
            scene="对方普通聊天时表示收到",
            sample_count=20,
            created_at=4.0,
            last_active_time=4.0,
        )
        manager = object.__new__(EmojiManager)
        manager.emoji_objects = [emoji_a, emoji_b]
        manager._ensure_db = Mock()
        manager.usage_scene_vector_index = SimpleNamespace(
            search=AsyncMock(
                return_value=[
                    EmojiUsageSceneVectorMatch(scene_a_low.id, "emoji-a", scene_a_low.scene, 0.4),
                    EmojiUsageSceneVectorMatch(scene_b.id, "emoji-b", scene_b.scene, 0.8),
                    EmojiUsageSceneVectorMatch(scene_a_high.id, "emoji-a", scene_a_high.scene, 0.9),
                    EmojiUsageSceneVectorMatch(
                        scene_a_frequent_but_less_relevant.id,
                        "emoji-a",
                        scene_a_frequent_but_less_relevant.scene,
                        0.5,
                    ),
                ]
            )
        )

        matches = await manager.get_emoji_candidates_by_scene_vector("对方正在自嘲", limit=8)

        self.assertIsNotNone(matches)
        self.assertEqual([match[0].hash for match in matches or []], ["emoji-a", "emoji-b"])
        self.assertAlmostEqual((matches or [])[0][2], 0.9)
        self.assertEqual(
            (matches or [])[0][1],
            (scene_a_high.scene, scene_a_frequent_but_less_relevant.scene, scene_a_low.scene),
        )

    async def test_scene_recall_without_human_scenes_is_unavailable(self) -> None:
        manager = object.__new__(EmojiManager)
        manager.emoji_objects = [make_emoji("emoji-a")]
        manager._ensure_db = Mock()
        manager.usage_scene_vector_index = SimpleNamespace(search=AsyncMock())

        matches = await manager.get_emoji_candidates_by_scene_vector("对方正在自嘲", limit=8)

        self.assertIsNone(matches)
        manager.usage_scene_vector_index.search.assert_not_awaited()

    async def test_scene_recall_aggregates_before_limiting_distinct_emojis(self) -> None:
        emoji_a = make_emoji("emoji-a")
        emoji_b = make_emoji("emoji-b")
        scenes_a = [
            EmojiUsageScene.create(
                emoji_hash="emoji-a",
                scene=f"表情 A 的真人场景 {index}",
                sample_count=1,
                created_at=float(index),
                last_active_time=float(index),
            )
            for index in range(20)
        ]
        scene_b = EmojiUsageScene.create(
            emoji_hash="emoji-b",
            scene="表情 B 的匹配场景",
            sample_count=1,
            created_at=21.0,
            last_active_time=21.0,
        )
        all_matches = [
            EmojiUsageSceneVectorMatch(
                scene.id,
                "emoji-a",
                scene.scene,
                0.99 - index * 0.005,
            )
            for index, scene in enumerate(scenes_a)
        ]
        all_matches.append(EmojiUsageSceneVectorMatch(scene_b.id, "emoji-b", scene_b.scene, 0.85))

        async def search(*, limit: int, **_kwargs):
            return all_matches[:limit]

        manager = object.__new__(EmojiManager)
        manager.emoji_objects = [emoji_a, emoji_b]
        manager._ensure_db = Mock()
        manager.usage_scene_vector_index = SimpleNamespace(search=AsyncMock(side_effect=search))

        matches = await manager.get_emoji_candidates_by_scene_vector("当前场景", limit=2)

        self.assertEqual([match[0].hash for match in matches or []], ["emoji-a", "emoji-b"])


class EmojiManagerRecordUsageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.database = SqliteDatabase(":memory:")
        self.original_database = Emoji._meta.database
        self.database.bind([Emoji], bind_refs=False, bind_backrefs=False)
        self.database.connect()
        self.database.create_tables([Emoji])

    def tearDown(self) -> None:
        self.database.drop_tables([Emoji])
        self.database.close()
        Emoji._meta.set_database(self.original_database)

    def test_record_usage_returns_write_result_and_updates_persisted_counters(self) -> None:
        emoji = Emoji.create(
            full_path="/tmp/hash-a.png",
            format="png",
            emoji_hash="hash-a",
            description="测试表情",
            emotion="开心",
            record_time=1.0,
        )
        manager = object.__new__(EmojiManager)

        self.assertTrue(manager.record_usage("hash-a"))
        emoji = Emoji.get_by_id(emoji.id)
        self.assertEqual(emoji.usage_count, 1)
        self.assertIsNotNone(emoji.last_used_time)
        self.assertFalse(manager.record_usage("missing"))


if __name__ == "__main__":
    unittest.main()
