import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from playhouse.sqlite_ext import SqliteExtDatabase

from src.common.database.database_model import BehaviorPattern, ChatStreams
from src.webui import behavior_routes
from src.webui.behavior_routes import behavior_to_response, get_behavior_stats_data


class BehaviorRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_db = SqliteExtDatabase(str(Path(self.tmpdir.name) / "behavior_routes.db"))
        self.original_dbs = {
            BehaviorPattern: BehaviorPattern._meta.database,
            ChatStreams: ChatStreams._meta.database,
        }
        self.test_db.bind([BehaviorPattern, ChatStreams], bind_refs=False, bind_backrefs=False)
        self.test_db.connect()
        self.test_db.create_tables([BehaviorPattern, ChatStreams])

    def tearDown(self) -> None:
        self.test_db.drop_tables([BehaviorPattern, ChatStreams])
        self.test_db.close()
        for model, database in self.original_dbs.items():
            model._meta.set_database(database)
        self.tmpdir.cleanup()

    def test_behavior_to_response_normalizes_source_ids(self) -> None:
        now = time.time()
        pattern = BehaviorPattern.create(
            chat_id="chat-a",
            actor_type="other_user",
            learning_type="observed_behavior",
            action="先确认对方诉求",
            outcome="对方继续补充上下文",
            source_text="alice: 我不知道怎么配",
            source_ids='["1", "2"]',
            count=2,
            score=1.2,
            enabled=True,
            selected_count=1,
            last_selected_time=now,
            last_active_time=now,
            create_date=now,
        )

        response = behavior_to_response(pattern)

        self.assertEqual(response.source_ids, ["1", "2"])
        self.assertEqual(response.action, "先确认对方诉求")
        self.assertTrue(response.enabled)

    def test_get_behavior_stats_data_counts_status_and_dimensions(self) -> None:
        now = time.time()
        old_time = now - 10 * 24 * 60 * 60
        ChatStreams.create(
            stream_id="chat-a",
            create_time=now,
            group_platform="qq",
            group_id="10001",
            group_name="测试群",
            last_active_time=now,
            platform="qq",
            user_platform="qq",
            user_id="u1",
            user_nickname="Alice",
        )
        BehaviorPattern.create(
            chat_id="chat-a",
            actor_type="other_user",
            learning_type="observed_behavior",
            action="先问清楚",
            outcome="继续聊",
            count=2,
            score=1.0,
            enabled=True,
            last_active_time=now,
            create_date=now,
        )
        BehaviorPattern.create(
            chat_id="chat-b",
            actor_type="maibot_self",
            learning_type="self_reflection",
            action="少连续追问",
            outcome="节奏更自然",
            count=1,
            score=0.8,
            enabled=False,
            last_active_time=old_time,
            create_date=old_time,
        )

        stats = get_behavior_stats_data()

        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["enabled"], 1)
        self.assertEqual(stats["disabled"], 1)
        self.assertEqual(stats["recent_7days"], 1)
        self.assertEqual(stats["chat_count"], 2)
        self.assertEqual(stats["top_chats"], {"chat-a": 1, "chat-b": 1})
        self.assertEqual(stats["actor_type_counts"], {"maibot_self": 1, "other_user": 1})
        self.assertEqual(stats["learning_type_counts"], {"observed_behavior": 1, "self_reflection": 1})


class BehaviorRouteSecurityTest(unittest.IsolatedAsyncioTestCase):
    async def test_internal_failures_are_sanitized(self) -> None:
        secret = 'database error at /private/behavior.db: token="super-secret"'
        with (
            patch.object(behavior_routes, "verify_auth_token", return_value=True),
            patch.object(behavior_routes.BehaviorPattern, "select", side_effect=RuntimeError(secret)),
            patch.object(behavior_routes.logger, "error") as logged,
            self.assertRaises(HTTPException) as failure,
        ):
            await behavior_routes.get_behavior_list(
                page=1,
                page_size=20,
                search=None,
                chat_id=None,
                enabled=None,
                actor_type=None,
                learning_type=None,
            )

        self.assertEqual(failure.exception.status_code, 500)
        self.assertEqual(failure.exception.detail, "获取行为模式列表失败")
        self.assertNotIn(secret, repr(logged.call_args))


if __name__ == "__main__":
    unittest.main()
