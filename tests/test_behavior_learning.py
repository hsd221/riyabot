import tempfile
import time
import unittest
from pathlib import Path

from playhouse.sqlite_ext import SqliteExtDatabase

from src.bw_learner.behavior_learner import parse_behavior_response
from src.bw_learner.behavior_selector import BehaviorSelector
from src.bw_learner.behavior_store import BehaviorPatternStore
from src.common.database.database_model import BehaviorPattern


class BehaviorLearningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_db = SqliteExtDatabase(str(Path(self.tmpdir.name) / "behavior.db"))
        self.original_db = BehaviorPattern._meta.database
        self.test_db.bind([BehaviorPattern], bind_refs=False, bind_backrefs=False)
        self.test_db.connect()
        self.test_db.create_tables([BehaviorPattern])

    def tearDown(self) -> None:
        self.test_db.drop_tables([BehaviorPattern])
        self.test_db.close()
        BehaviorPattern._meta.set_database(self.original_db)
        self.tmpdir.cleanup()

    def test_parse_behavior_response_accepts_upstream_json_shape(self) -> None:
        response = """
        ```json
        [
          {
            "actor_type": "other_user",
            "learning_type": "observed_behavior",
            "action": "先短句共情，再给一个可执行的小建议",
            "outcome": "对方继续补充细节",
            "source_ids": ["2", "4"]
          },
          {
            "actor_type": "unknown",
            "learning_type": "observed_behavior",
            "action": "一次性查询某个配置值",
            "outcome": "得到结果",
            "source_ids": []
          }
        ]
        ```
        """

        patterns = parse_behavior_response(response)

        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].actor_type, "other_user")
        self.assertEqual(patterns[0].learning_type, "observed_behavior")
        self.assertEqual(patterns[0].source_ids, ["2", "4"])

    def test_store_merges_similar_action_and_outcome(self) -> None:
        store = BehaviorPatternStore(similarity_threshold=0.8)
        now = time.time()

        first = store.upsert_pattern(
            chat_id="chat-a",
            actor_type="other_user",
            learning_type="observed_behavior",
            action="先确认关键配置，再给出排查步骤",
            outcome="对方补充信息，排查方向变明确",
            source_text="alice: 怎么连不上\nbob: 先看端口",
            source_ids=["1", "2"],
            current_time=now,
        )
        second = store.upsert_pattern(
            chat_id="chat-a",
            actor_type="other_user",
            learning_type="observed_behavior",
            action="先确认关键配置，再给出排查步骤",
            outcome="对方补充信息，排查方向变明确",
            source_text="alice: 还是连不上\nbob: 看下端口",
            source_ids=["3", "4"],
            current_time=now + 1,
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(BehaviorPattern.select().count(), 1)
        stored = BehaviorPattern.get_by_id(first.id)
        self.assertEqual(stored.count, 2)

    def test_selector_returns_context_relevant_reference(self) -> None:
        now = time.time()
        BehaviorPattern.create(
            chat_id="chat-a",
            actor_type="other_user",
            learning_type="observed_behavior",
            action="先确认关键配置，再给出排查步骤",
            outcome="对方补充信息，排查方向变明确",
            source_text="排查端口配置",
            source_ids='["1"]',
            count=3,
            score=1.0,
            last_active_time=now,
            create_date=now,
        )
        BehaviorPattern.create(
            chat_id="chat-a",
            actor_type="group_collective",
            learning_type="observed_behavior",
            action="顺着玩笑接梗，保持轻松语气",
            outcome="话题转向轻松闲聊",
            source_text="群友互相开玩笑",
            source_ids='["2"]',
            count=1,
            score=1.0,
            last_active_time=now,
            create_date=now,
        )

        block, selected_ids = BehaviorSelector().build_reference_block(
            "chat-a",
            "用户说接口连不上，怀疑是端口配置问题",
            max_num=1,
        )

        self.assertIn("行为参考", block)
        self.assertIn("确认关键配置", block)
        self.assertNotIn("顺着玩笑接梗", block)
        self.assertEqual(len(selected_ids), 1)


if __name__ == "__main__":
    unittest.main()
