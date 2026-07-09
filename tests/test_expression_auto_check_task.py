import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from peewee import SqliteDatabase

from src.bw_learner import expression_auto_check_task
from src.common.database.database_model import Expression


def make_expression(**overrides):
    defaults = {
        "situation": "用户问候",
        "style": "轻松短句回应",
        "content_list": "[]",
        "count": 1,
        "last_active_time": 100.0,
        "chat_id": "chat-1",
        "create_date": 100.0,
        "checked": False,
        "rejected": False,
        "modified_by": None,
    }
    defaults.update(overrides)
    return Expression.create(**defaults)


class ExpressionAutoCheckPromptAndLLMTest(unittest.IsolatedAsyncioTestCase):
    def test_create_evaluation_prompt_includes_base_and_custom_criteria(self) -> None:
        fake_config = SimpleNamespace(
            expression=SimpleNamespace(expression_auto_check_custom_criteria=["不能包含内部配置名", "要适合群聊语境"])
        )

        with patch.object(expression_auto_check_task, "global_config", fake_config):
            prompt = expression_auto_check_task.create_evaluation_prompt("被问配置", "先确认上下文")

        self.assertIn("使用条件或使用情景：被问配置", prompt)
        self.assertIn("表达方式或言语风格：先确认上下文", prompt)
        self.assertIn("1. 表达方式或言语风格 是否与使用条件或使用情景 匹配", prompt)
        self.assertIn("5. 不能包含内部配置名", prompt)
        self.assertIn("6. 要适合群聊语境", prompt)
        self.assertIn('"suitable": true/false', prompt)

    async def test_single_expression_check_parses_plain_and_embedded_json_and_reports_invalid_responses(self) -> None:
        judge = SimpleNamespace(
            generate_response_async=AsyncMock(return_value=('{"suitable": true, "reason": "可用"}', ("", "m", None)))
        )

        with (
            patch.object(expression_auto_check_task, "judge_llm", judge),
            patch.object(expression_auto_check_task, "create_evaluation_prompt", return_value="prompt") as build_prompt,
        ):
            self.assertEqual(
                await expression_auto_check_task.single_expression_check("情境", "风格"), (True, "可用", None)
            )

        build_prompt.assert_called_once_with("情境", "风格")
        judge.generate_response_async.assert_awaited_once_with(prompt="prompt", temperature=0.6, max_tokens=1024)

        judge.generate_response_async = AsyncMock(
            return_value=('前缀 {"suitable": false, "reason": "过于特指"} 后缀', ("", "m", None))
        )
        with patch.object(expression_auto_check_task, "judge_llm", judge):
            self.assertEqual(
                await expression_auto_check_task.single_expression_check("情境", "风格"),
                (False, "过于特指", None),
            )

        judge.generate_response_async = AsyncMock(return_value=("not json", ("", "m", None)))
        with patch.object(expression_auto_check_task, "judge_llm", judge):
            suitable, reason, error = await expression_auto_check_task.single_expression_check("情境", "风格")

        self.assertFalse(suitable)
        self.assertIn("评估过程出错", reason)
        self.assertIn("无法从响应中提取JSON格式的评估结果", error)


class ExpressionAutoCheckTaskDatabaseTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = SqliteDatabase(":memory:")
        self.original_db = Expression._meta.database
        self.db.bind([Expression], bind_refs=False, bind_backrefs=False)
        self.db.connect()
        self.db.create_tables([Expression])

    def tearDown(self) -> None:
        self.db.drop_tables([Expression])
        self.db.close()
        Expression._meta.set_database(self.original_db)

    async def test_select_expressions_samples_only_unchecked_records_and_caps_requested_count(self) -> None:
        first = make_expression(situation="first")
        second = make_expression(situation="second")
        make_expression(situation="checked", checked=True)
        task = expression_auto_check_task.ExpressionAutoCheckTask.__new__(
            expression_auto_check_task.ExpressionAutoCheckTask
        )

        with patch.object(
            expression_auto_check_task.random, "sample", side_effect=lambda values, count: values[:count]
        ):
            selected = await task._select_expressions(5)

        self.assertEqual([expr.id for expr in selected], [first.id, second.id])

    async def test_evaluate_expression_persists_ai_checked_pass_and_reject_states(self) -> None:
        passed = make_expression(situation="pass")
        failed = make_expression(situation="fail")
        task = expression_auto_check_task.ExpressionAutoCheckTask.__new__(
            expression_auto_check_task.ExpressionAutoCheckTask
        )

        with patch.object(
            expression_auto_check_task,
            "single_expression_check",
            new=AsyncMock(return_value=(True, "合理", None)),
        ) as check:
            self.assertTrue(await task._evaluate_expression(passed))

        check.assert_awaited_once_with("pass", "轻松短句回应")
        passed = Expression.get_by_id(passed.id)
        self.assertTrue(passed.checked)
        self.assertFalse(passed.rejected)
        self.assertEqual(passed.modified_by, "ai")

        with patch.object(
            expression_auto_check_task,
            "single_expression_check",
            new=AsyncMock(return_value=(False, "太具体", "provider timeout")),
        ):
            self.assertFalse(await task._evaluate_expression(failed))

        failed = Expression.get_by_id(failed.id)
        self.assertTrue(failed.checked)
        self.assertTrue(failed.rejected)
        self.assertEqual(failed.modified_by, "ai")

    async def test_evaluate_expression_returns_false_when_persisting_status_fails(self) -> None:
        expression = SimpleNamespace(
            id=99,
            situation="情境",
            style="风格",
            checked=False,
            rejected=False,
            modified_by=None,
            save=Mock(side_effect=RuntimeError("db down")),
        )
        task = expression_auto_check_task.ExpressionAutoCheckTask.__new__(
            expression_auto_check_task.ExpressionAutoCheckTask
        )

        with patch.object(
            expression_auto_check_task,
            "single_expression_check",
            new=AsyncMock(return_value=(True, "合理", None)),
        ):
            self.assertFalse(await task._evaluate_expression(expression))

        self.assertTrue(expression.checked)
        self.assertFalse(expression.rejected)
        self.assertEqual(expression.modified_by, "ai")


class ExpressionAutoCheckTaskRunTest(unittest.IsolatedAsyncioTestCase):
    async def test_task_init_uses_configured_interval(self) -> None:
        fake_config = SimpleNamespace(expression=SimpleNamespace(expression_auto_check_interval=321))

        with patch.object(expression_auto_check_task, "global_config", fake_config):
            task = expression_auto_check_task.ExpressionAutoCheckTask()

        self.assertEqual(task.task_name, "Expression Auto Check Task")
        self.assertEqual(task.wait_before_start, 60)
        self.assertEqual(task.run_interval, 321)

    async def test_run_skips_when_disabled_invalid_count_or_no_selected_expressions(self) -> None:
        task = expression_auto_check_task.ExpressionAutoCheckTask.__new__(
            expression_auto_check_task.ExpressionAutoCheckTask
        )
        task._select_expressions = AsyncMock(return_value=[])
        task._evaluate_expression = AsyncMock()

        disabled_config = SimpleNamespace(
            expression=SimpleNamespace(expression_self_reflect=False, expression_auto_check_count=2)
        )
        with patch.object(expression_auto_check_task, "global_config", disabled_config):
            await task.run()
        task._select_expressions.assert_not_awaited()

        invalid_count_config = SimpleNamespace(
            expression=SimpleNamespace(expression_self_reflect=True, expression_auto_check_count=0)
        )
        with patch.object(expression_auto_check_task, "global_config", invalid_count_config):
            await task.run()
        task._select_expressions.assert_not_awaited()

        enabled_config = SimpleNamespace(
            expression=SimpleNamespace(expression_self_reflect=True, expression_auto_check_count=2)
        )
        with patch.object(expression_auto_check_task, "global_config", enabled_config):
            await task.run()
        task._select_expressions.assert_awaited_once_with(2)
        task._evaluate_expression.assert_not_awaited()

    async def test_run_evaluates_selected_expressions_counts_results_and_sleeps_between_each(self) -> None:
        expressions = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
        task = expression_auto_check_task.ExpressionAutoCheckTask.__new__(
            expression_auto_check_task.ExpressionAutoCheckTask
        )
        task._select_expressions = AsyncMock(return_value=expressions)
        task._evaluate_expression = AsyncMock(side_effect=[True, False])
        fake_config = SimpleNamespace(
            expression=SimpleNamespace(expression_self_reflect=True, expression_auto_check_count=2)
        )

        with (
            patch.object(expression_auto_check_task, "global_config", fake_config),
            patch.object(expression_auto_check_task.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            await task.run()

        task._select_expressions.assert_awaited_once_with(2)
        self.assertEqual(task._evaluate_expression.await_args_list[0].args[0], expressions[0])
        self.assertEqual(task._evaluate_expression.await_args_list[1].args[0], expressions[1])
        self.assertEqual(sleep.await_count, 2)
        sleep.assert_awaited_with(0.3)


if __name__ == "__main__":
    unittest.main()
