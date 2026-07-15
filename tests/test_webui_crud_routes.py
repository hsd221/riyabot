import unittest
from unittest.mock import patch

from fastapi import HTTPException
from peewee import SqliteDatabase

from src.common.database.database_model import BaseModel, ChatStreams, Expression, Jargon
from src.webui import expression_routes, jargon_routes


TEST_MODELS = [ChatStreams, Expression, Jargon]


class WebUICrudRoutesTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.test_db = SqliteDatabase(":memory:")
        self.original_dbs = {model: model._meta.database for model in [BaseModel, *TEST_MODELS]}
        self.test_db.bind(TEST_MODELS, bind_refs=False, bind_backrefs=False)
        self.test_db.connect()
        self.test_db.create_tables(TEST_MODELS)

    def tearDown(self) -> None:
        self.test_db.drop_tables(TEST_MODELS)
        self.test_db.close()
        for model, database in self.original_dbs.items():
            model._meta.set_database(database)

    def create_chat_stream(
        self,
        stream_id: str,
        *,
        group_name: str | None = None,
        user_nickname: str = "User",
        platform: str = "qq",
    ) -> ChatStreams:
        return ChatStreams.create(
            stream_id=stream_id,
            create_time=1.0,
            group_platform=platform if group_name else None,
            group_id=f"group-{stream_id}" if group_name else None,
            group_name=group_name,
            last_active_time=2.0,
            platform=platform,
            user_platform=platform,
            user_id=f"user-{stream_id}",
            user_nickname=user_nickname,
            user_cardname=None,
        )


class JargonRoutesTest(WebUICrudRoutesTestCase):
    def test_jargon_helpers_parse_json_chat_ids_and_resolve_display_names(self) -> None:
        self.create_chat_stream("stream-1", group_name="测试群")

        self.assertEqual(jargon_routes.parse_chat_id_to_stream_ids(""), [])
        self.assertEqual(jargon_routes.parse_chat_id_to_stream_ids("stream-raw"), ["stream-raw"])
        self.assertEqual(
            jargon_routes.parse_chat_id_to_stream_ids('[["stream-1", "user-1"], ["stream-2", "user-2"]]'),
            ["stream-1", "stream-2"],
        )
        self.assertEqual(jargon_routes.get_display_name_for_chat_id('[["stream-1", "user-1"]]'), "测试群")
        self.assertEqual(jargon_routes.get_display_name_for_chat_id("long-stream-id"), "long-str...")

    async def test_jargon_list_stats_create_update_and_delete_routes_use_database_state(self) -> None:
        self.create_chat_stream("stream-1", group_name="群一")
        self.create_chat_stream("stream-2", user_nickname="Bob")
        first = Jargon.create(
            content="暗号",
            raw_content="暗号原文",
            meaning="真实含义",
            chat_id='[["stream-1", "u1"]]',
            is_global=True,
            count=5,
            is_jargon=True,
            is_complete=True,
        )
        second = Jargon.create(content="普通词", raw_content="普通原文", chat_id="stream-2", count=1, is_jargon=False)
        pending = Jargon.create(content="待定词", chat_id="missing-long-stream", count=2, is_jargon=None)

        listed = await jargon_routes.get_jargon_list(
            search="暗", chat_id=None, is_jargon=None, is_global=None, page=1, page_size=10
        )
        self.assertEqual(listed.total, 1)
        self.assertEqual(listed.data[0].content, "暗号")
        self.assertEqual(listed.data[0].stream_id, "stream-1")
        self.assertEqual(listed.data[0].chat_name, "群一")

        filtered = await jargon_routes.get_jargon_list(
            search=None,
            chat_id='[["stream-1", "ignored"]]',
            is_jargon=None,
            is_global=None,
            page=1,
            page_size=10,
        )
        self.assertEqual(filtered.total, 1)
        self.assertEqual(filtered.data[0].id, first.id)

        chats = await jargon_routes.get_chat_list()
        chats_by_id = {item.chat_id: item for item in chats.data}
        self.assertEqual(chats_by_id["stream-1"].chat_name, "群一")
        self.assertEqual(chats_by_id["stream-2"].chat_name, "stream-2")
        self.assertEqual(chats_by_id["missing-long-stream"].chat_name, "missing-...")

        stats = await jargon_routes.get_jargon_stats()
        self.assertEqual(stats.data["total"], 3)
        self.assertEqual(stats.data["confirmed_jargon"], 1)
        self.assertEqual(stats.data["confirmed_not_jargon"], 1)
        self.assertEqual(stats.data["pending"], 1)
        self.assertEqual(stats.data["global_count"], 1)
        self.assertEqual(stats.data["complete_count"], 1)
        self.assertEqual(stats.data["chat_count"], 3)

        detail = await jargon_routes.get_jargon_detail(first.id)
        self.assertEqual(detail.data.meaning, "真实含义")
        with self.assertRaises(HTTPException) as missing_detail:
            await jargon_routes.get_jargon_detail(999)
        self.assertEqual(missing_detail.exception.status_code, 404)

        with self.assertRaises(HTTPException) as duplicate:
            await jargon_routes.create_jargon(
                jargon_routes.JargonCreateRequest(content="暗号", raw_content=None, meaning=None, chat_id=first.chat_id)
            )
        self.assertEqual(duplicate.exception.status_code, 400)

        created = await jargon_routes.create_jargon(
            jargon_routes.JargonCreateRequest(
                content="新词", raw_content="新词原文", meaning="解释", chat_id="stream-2"
            )
        )
        self.assertEqual(created.message, "创建成功")
        self.assertEqual(Jargon.get_by_id(created.data.id).count, 0)

        updated = await jargon_routes.update_jargon(
            first.id,
            jargon_routes.JargonUpdateRequest(meaning=None, raw_content=None, is_jargon=False),
        )
        self.assertIsNone(updated.data.meaning)
        self.assertIsNone(updated.data.raw_content)
        self.assertFalse(updated.data.is_jargon)

        status_update = await jargon_routes.batch_set_jargon_status(ids=[pending.id], is_jargon=True)
        self.assertIn("成功更新 1 条黑话状态", status_update.message)
        self.assertTrue(Jargon.get_by_id(pending.id).is_jargon)

        deleted = await jargon_routes.batch_delete_jargons(jargon_routes.BatchDeleteRequest(ids=[second.id, 999]))
        self.assertEqual(deleted.deleted_count, 1)
        with self.assertRaises(HTTPException) as empty_delete:
            await jargon_routes.batch_delete_jargons(jargon_routes.BatchDeleteRequest(ids=[]))
        self.assertEqual(empty_delete.exception.status_code, 400)

        single_deleted = await jargon_routes.delete_jargon(created.data.id)
        self.assertEqual(single_deleted.deleted_count, 1)
        with self.assertRaises(HTTPException) as missing_delete:
            await jargon_routes.delete_jargon(created.data.id)
        self.assertEqual(missing_delete.exception.status_code, 404)

    async def test_jargon_internal_failures_are_sanitized(self) -> None:
        secret = 'database error at /private/jargon.db: token="super-secret"'
        with (
            patch.object(jargon_routes.Jargon, "select", side_effect=RuntimeError(secret)),
            patch.object(jargon_routes.logger, "error") as logged,
            self.assertRaises(HTTPException) as failure,
        ):
            await jargon_routes.get_jargon_list(
                search=None,
                chat_id=None,
                is_jargon=None,
                is_global=None,
                page=1,
                page_size=20,
            )

        self.assertEqual(failure.exception.status_code, 500)
        self.assertEqual(failure.exception.detail, "获取黑话列表失败")
        self.assertNotIn(secret, repr(logged.call_args))


class ExpressionRoutesTest(WebUICrudRoutesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth_patch = patch.object(expression_routes, "verify_auth_token", return_value=True)
        self.auth_patch.start()

    def tearDown(self) -> None:
        self.auth_patch.stop()
        super().tearDown()

    def test_expression_helpers_resolve_chat_names_and_response_models(self) -> None:
        self.create_chat_stream("stream-a", group_name="Alpha Group")
        self.create_chat_stream("stream-b", user_nickname="Bob")
        expression = Expression.create(
            situation="问候",
            style="轻松",
            chat_id="stream-a",
            last_active_time=10.0,
            create_date=9.0,
        )

        self.assertEqual(expression_routes.get_chat_name("stream-a"), "Alpha Group")
        self.assertEqual(expression_routes.get_chat_name("stream-b"), "Bob")
        self.assertEqual(expression_routes.get_chat_name("missing"), "missing")
        self.assertEqual(
            expression_routes.get_chat_names_batch(["stream-a", "stream-b", "missing"]),
            {"stream-a": "Alpha Group", "stream-b": "Bob", "missing": "missing"},
        )

        response = expression_routes.expression_to_response(expression)
        self.assertEqual(response.situation, "问候")
        self.assertFalse(response.checked)

    async def test_expression_crud_stats_and_review_routes_handle_checked_states(self) -> None:
        self.create_chat_stream("stream-a", group_name="Alpha Group")
        self.create_chat_stream("stream-b", user_nickname="Bob")

        with patch.object(expression_routes.time, "time", return_value=1_000.0):
            created = await expression_routes.create_expression(
                expression_routes.ExpressionCreateRequest(situation="问候", style="轻松", chat_id="stream-a")
            )
        unchecked_id = created.data.id
        passed = Expression.create(
            situation="赞同",
            style="正式",
            chat_id="stream-a",
            last_active_time=900.0,
            create_date=800.0,
            checked=True,
            rejected=False,
            modified_by="ai",
        )
        rejected = Expression.create(
            situation="吐槽",
            style="犀利",
            chat_id="stream-b",
            last_active_time=700.0,
            create_date=600.0,
            checked=True,
            rejected=True,
            modified_by="user",
        )

        chats = await expression_routes.get_chat_list()
        self.assertEqual([item.chat_name for item in chats.data], ["Alpha Group", "Bob"])

        listed = await expression_routes.get_expression_list(search="问", chat_id=None, page=1, page_size=10)
        self.assertEqual(listed.total, 1)
        self.assertEqual(listed.data[0].id, unchecked_id)
        filtered = await expression_routes.get_expression_list(search=None, chat_id="stream-a", page=1, page_size=10)
        self.assertEqual(filtered.total, 2)

        detail = await expression_routes.get_expression_detail(unchecked_id)
        self.assertEqual(detail.data.style, "轻松")
        with self.assertRaises(HTTPException) as missing_detail:
            await expression_routes.get_expression_detail(999)
        self.assertEqual(missing_detail.exception.status_code, 404)

        with self.assertRaises(HTTPException) as conflict:
            await expression_routes.update_expression(
                passed.id,
                expression_routes.ExpressionUpdateRequest(rejected=True, require_unchecked=True),
            )
        self.assertEqual(conflict.exception.status_code, 409)

        with self.assertRaises(HTTPException) as no_fields:
            await expression_routes.update_expression(unchecked_id, expression_routes.ExpressionUpdateRequest())
        self.assertEqual(no_fields.exception.status_code, 400)

        with patch.object(expression_routes.time, "time", return_value=1_100.0):
            updated = await expression_routes.update_expression(
                unchecked_id,
                expression_routes.ExpressionUpdateRequest(checked=True, rejected=False),
            )
        self.assertEqual(updated.data.modified_by, "user")
        self.assertEqual(updated.data.last_active_time, 1_100.0)

        with patch.object(expression_routes.time, "time", return_value=1_200.0):
            stats = await expression_routes.get_expression_stats()
        self.assertEqual(stats["data"]["total"], 3)
        self.assertEqual(stats["data"]["recent_7days"], 3)
        self.assertEqual(stats["data"]["chat_count"], 2)
        self.assertEqual(stats["data"]["top_chats"], {"stream-a": 2, "stream-b": 1})

        review_stats = await expression_routes.get_review_stats()
        self.assertEqual(review_stats.total, 3)
        self.assertEqual(review_stats.unchecked, 0)
        self.assertEqual(review_stats.passed, 2)
        self.assertEqual(review_stats.rejected, 1)
        self.assertEqual(review_stats.ai_checked, 1)
        self.assertEqual(review_stats.user_checked, 2)

        passed_list = await expression_routes.get_review_list(
            filter_type="passed", search=None, chat_id=None, page=1, page_size=10
        )
        self.assertEqual(passed_list.total, 2)
        rejected_list = await expression_routes.get_review_list(
            filter_type="rejected", search=None, chat_id=None, page=1, page_size=10
        )
        self.assertEqual(rejected_list.total, 1)
        all_list = await expression_routes.get_review_list(
            filter_type="all", search=None, chat_id=None, page=1, page_size=10
        )
        self.assertEqual(all_list.total, 3)

        batch_review = await expression_routes.batch_review_expressions(
            expression_routes.BatchReviewRequest(
                items=[
                    expression_routes.BatchReviewItem(id=passed.id, rejected=True, require_unchecked=True),
                    expression_routes.BatchReviewItem(id=999, rejected=False),
                    expression_routes.BatchReviewItem(id=rejected.id, rejected=False, require_unchecked=False),
                ]
            )
        )
        self.assertEqual(batch_review.total, 3)
        self.assertEqual(batch_review.succeeded, 1)
        self.assertEqual(batch_review.failed, 2)
        self.assertEqual(Expression.get_by_id(rejected.id).modified_by, "user")
        self.assertFalse(Expression.get_by_id(rejected.id).rejected)

        deleted = await expression_routes.batch_delete_expressions(
            expression_routes.BatchDeleteRequest(ids=[passed.id])
        )
        self.assertEqual(deleted.message, "成功删除 1 个表达方式")
        with self.assertRaises(HTTPException) as empty_delete:
            await expression_routes.batch_delete_expressions(expression_routes.BatchDeleteRequest(ids=[]))
        self.assertEqual(empty_delete.exception.status_code, 400)

        single_deleted = await expression_routes.delete_expression(rejected.id)
        self.assertIn("成功删除表达方式", single_deleted.message)
        with self.assertRaises(HTTPException) as missing_delete:
            await expression_routes.delete_expression(rejected.id)
        self.assertEqual(missing_delete.exception.status_code, 404)

    async def test_expression_internal_and_batch_item_failures_are_sanitized(self) -> None:
        secret = 'database error at /private/expression.db: token="super-secret"'
        with (
            patch.object(expression_routes.Expression, "select", side_effect=RuntimeError(secret)),
            patch.object(expression_routes.logger, "error") as logged,
            self.assertRaises(HTTPException) as list_failure,
        ):
            await expression_routes.get_expression_list(search=None, chat_id=None, page=1, page_size=20)

        self.assertEqual(list_failure.exception.status_code, 500)
        self.assertEqual(list_failure.exception.detail, "获取表达方式列表失败")
        self.assertNotIn(secret, repr(logged.call_args))

        with (
            patch.object(expression_routes.Expression, "get_or_none", side_effect=RuntimeError(secret)),
            patch.object(expression_routes.logger, "error") as logged,
        ):
            batch = await expression_routes.batch_review_expressions(
                expression_routes.BatchReviewRequest(
                    items=[expression_routes.BatchReviewItem(id=1, rejected=False, require_unchecked=False)]
                )
            )

        self.assertEqual(batch.failed, 1)
        self.assertEqual(batch.results[0].message, "审核失败")
        self.assertNotIn(secret, repr(logged.call_args))


if __name__ == "__main__":
    unittest.main()
