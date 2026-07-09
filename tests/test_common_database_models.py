import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from peewee import BooleanField, DateTimeField, DoubleField, FloatField, IntegerField, IntegrityError, SqliteDatabase
from peewee import TextField

from src.common.database import database_model as database_model_module
from src.common.database.database import ROOT_PATH, db
from src.common.database.database_model import (
    ActionRecords,
    BaseModel,
    BehaviorPattern,
    ChatHistory,
    ChatStreams,
    Emoji,
    EmojiDescriptionCache,
    Expression,
    GroupInfo,
    Images,
    ImageDescriptions,
    Jargon,
    LLMUsage,
    Messages,
    OnlineTime,
)


TEST_MODELS = [
    ChatStreams,
    LLMUsage,
    Emoji,
    Images,
    ImageDescriptions,
    EmojiDescriptionCache,
    OnlineTime,
    GroupInfo,
    Expression,
    Jargon,
    Messages,
    ActionRecords,
    BehaviorPattern,
    ChatHistory,
]


class CommonDatabaseModelsTest(unittest.TestCase):
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

    def test_database_module_uses_project_data_sqlite_with_expected_pragmas(self) -> None:
        pragmas = dict(db._pragmas)

        self.assertTrue(db.database.endswith("data/RiyaBot.db"))
        self.assertIn("maibot", ROOT_PATH)
        self.assertEqual(pragmas["journal_mode"], "wal")
        self.assertEqual(pragmas["foreign_keys"], 1)

    def test_chat_streams_enforce_unique_stream_id_and_persist_group_user_fields(self) -> None:
        ChatStreams.create(
            stream_id="stream-1",
            create_time=1.0,
            group_platform="qq",
            group_id="group-1",
            group_name="测试群",
            last_active_time=2.0,
            platform="qq",
            user_platform="qq",
            user_id="user-1",
            user_nickname="Alice",
            user_cardname="Ali",
        )

        with self.assertRaises(IntegrityError):
            ChatStreams.create(
                stream_id="stream-1",
                create_time=3.0,
                last_active_time=4.0,
                platform="qq",
                user_platform="qq",
                user_id="user-2",
                user_nickname="Bob",
            )

        stream = ChatStreams.get(ChatStreams.stream_id == "stream-1")
        self.assertEqual(ChatStreams._meta.table_name, "chat_streams")
        self.assertEqual(stream.group_name, "测试群")
        self.assertEqual(stream.user_cardname, "Ali")

    def test_usage_emoji_image_and_online_time_models_preserve_defaults_and_uniqueness(self) -> None:
        now = datetime.datetime.now()
        LLMUsage.create(
            model_name="gpt",
            model_assign_name="chat",
            model_api_provider="provider",
            user_id="user-1",
            request_type="chat",
            endpoint="/v1/chat",
            prompt_tokens=3,
            completion_tokens=4,
            total_tokens=7,
            cost=0.01,
            time_cost=0.2,
            status="success",
            timestamp=now,
        )
        emoji = Emoji.create(
            full_path="/tmp/cat.png",
            format="png",
            emoji_hash="hash-1",
            description="cat",
            emotion="happy",
            record_time=1.0,
        )
        image = Images.create(
            image_id="img-1",
            emoji_hash="hash-1",
            description="cat",
            path="/tmp/image.png",
            timestamp=1.0,
            type="emoji",
        )
        online = OnlineTime.create(duration=5, end_timestamp=now)

        with self.assertRaises(IntegrityError):
            Emoji.create(
                full_path="/tmp/cat.png", format="png", emoji_hash="hash-2", description="dup", record_time=2.0
            )
        with self.assertRaises(IntegrityError):
            Images.create(emoji_hash="hash-2", path="/tmp/image.png", timestamp=2.0, type="image")

        self.assertEqual(emoji.query_count, 0)
        self.assertFalse(emoji.is_registered)
        self.assertFalse(emoji.is_banned)
        self.assertEqual(emoji.usage_count, 0)
        self.assertEqual(image.count, 1)
        self.assertFalse(image.vlm_processed)
        self.assertEqual(online.duration, 5)

    def test_group_expression_and_jargon_defaults_match_runtime_expectations(self) -> None:
        group = GroupInfo.create(group_id="group-1", group_name="测试群", platform="qq")
        expression = Expression.create(
            situation="问候",
            style="轻松",
            content_list='["你好"]',
            count=2,
            last_active_time=1.0,
            chat_id="stream-1",
        )
        jargon = Jargon.create(content="黑话", raw_content="黑话", chat_id="stream-1")

        self.assertEqual(group.member_count, 0)
        self.assertIsNone(group.member_list)
        self.assertFalse(expression.checked)
        self.assertFalse(expression.rejected)
        self.assertIsNone(expression.modified_by)
        self.assertEqual(jargon.count, 0)
        self.assertFalse(jargon.is_global)
        self.assertFalse(jargon.is_complete)
        self.assertIsNone(jargon.is_jargon)

    def test_message_action_behavior_history_and_description_cache_models_persist_runtime_fields(self) -> None:
        message = Messages.create(
            message_id="msg-1",
            time=1.0,
            chat_id="stream-1",
            reply_to="msg-0",
            interest_value=0.5,
            key_words="alpha,beta",
            key_words_lite="alpha",
            is_mentioned=True,
            is_at=False,
            reply_probability_boost=1.25,
            chat_info_stream_id="stream-1",
            chat_info_platform="qq",
            chat_info_user_platform="qq",
            chat_info_user_id="user-1",
            chat_info_user_nickname="Alice",
            chat_info_user_cardname="Ali",
            chat_info_group_platform="qq",
            chat_info_group_id="group-1",
            chat_info_group_name="测试群",
            chat_info_create_time=1.0,
            chat_info_last_active_time=2.0,
            user_platform="qq",
            user_id="sender-1",
            user_nickname="Sender",
            user_cardname="SenderCard",
            processed_plain_text="hello",
            display_message="Hello",
            priority_mode="normal",
            priority_info="{}",
            additional_config="{}",
            is_emoji=True,
            is_picid=True,
            is_command=True,
            intercept_message_level=2,
            is_notify=True,
            selected_expressions="[]",
        )
        action = ActionRecords.create(
            action_id="action-1",
            time=2.0,
            action_reasoning="reason",
            action_name="reply",
            action_data="{}",
            action_done=True,
            action_build_into_prompt=True,
            action_prompt_display="display",
            chat_id="stream-1",
            chat_info_stream_id="stream-1",
            chat_info_platform="qq",
        )
        image_description = ImageDescriptions.create(
            type="emoji",
            image_description_hash="desc-hash",
            description="description",
            timestamp=3.0,
        )
        cache = EmojiDescriptionCache.create(
            emoji_hash="emoji-hash",
            description="cached description",
            emotion_tags="happy,calm",
            timestamp=4.0,
        )
        behavior = BehaviorPattern.create(
            chat_id="stream-1",
            actor_type="user",
            learning_type="reply",
            action="say_hi",
            outcome="responded",
            source_text="hello",
            source_ids="msg-1",
            last_active_time=5.0,
        )
        history = ChatHistory.create(
            chat_id="stream-1",
            start_time=1.0,
            end_time=2.0,
            original_text="hello\nworld",
            participants='["Alice"]',
            theme="Greeting",
            keywords='["hello"]',
            summary="summary",
            key_point='["point"]',
        )

        self.assertTrue(message.is_command)
        self.assertEqual(message.intercept_message_level, 2)
        self.assertTrue(action.action_build_into_prompt)
        self.assertEqual(image_description.description, "description")
        self.assertEqual(cache.emotion_tags, "happy,calm")
        self.assertEqual(behavior.count, 1)
        self.assertEqual(behavior.score, 1.0)
        self.assertTrue(behavior.enabled)
        self.assertEqual(behavior.selected_count, 0)
        self.assertEqual(history.count, 0)
        self.assertEqual(history.forget_times, 0)

    def test_create_tables_delegates_to_module_database_with_declared_models(self) -> None:
        class FakeDb:
            def __init__(self) -> None:
                self.created_models = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def create_tables(self, models):
                self.created_models = list(models)

        fake_db = FakeDb()

        with patch.object(database_model_module, "db", fake_db):
            database_model_module.create_tables()

        self.assertEqual(fake_db.created_models, database_model_module.MODELS)

    def test_initialize_database_creates_missing_tables_adds_known_field_types_and_drops_extra_fields(self) -> None:
        class FakeField:
            def __init__(self, null=False, default=None):
                self.null = null
                self.default = default

        class UnknownField:
            null = True
            default = None

        fake_fields = {
            "existing": TextField(),
            "text_value": TextField(null=True, default="fallback"),
            "int_value": IntegerField(default=7),
            "float_value": FloatField(default=1.5),
            "double_value": DoubleField(default=2.5),
            "bool_value": BooleanField(default=True),
            "datetime_value": DateTimeField(default=datetime.datetime.now),
            "unknown_value": UnknownField(),
        }
        fake_model = SimpleNamespace(_meta=SimpleNamespace(table_name="fake_table", fields=fake_fields))
        missing_model = SimpleNamespace(_meta=SimpleNamespace(table_name="missing_table", fields={}))

        class FakeCursor:
            def fetchall(self):
                return [(0, "id"), (1, "existing"), (2, "extra_column")]

        class FakeDb:
            def __init__(self) -> None:
                self.created_models = []
                self.sql = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def table_exists(self, model):
                return model is fake_model

            def create_tables(self, models):
                self.created_models.extend(models)

            def execute_sql(self, sql):
                self.sql.append(sql)
                if sql.startswith("PRAGMA"):
                    return FakeCursor()
                return SimpleNamespace()

        fake_db = FakeDb()

        with (
            patch.object(database_model_module, "db", fake_db),
            patch.object(database_model_module, "MODELS", [missing_model, fake_model]),
            patch.object(database_model_module, "sync_field_constraints") as sync_field_constraints,
        ):
            database_model_module.initialize_database(sync_constraints=True)

        self.assertEqual(fake_db.created_models, [missing_model])
        self.assertIn("ALTER TABLE fake_table ADD COLUMN text_value TEXT NULL DEFAULT 'fallback'", fake_db.sql)
        self.assertIn("ALTER TABLE fake_table ADD COLUMN int_value INTEGER NOT NULL DEFAULT 7", fake_db.sql)
        self.assertIn("ALTER TABLE fake_table ADD COLUMN float_value FLOAT NOT NULL DEFAULT 1.5", fake_db.sql)
        self.assertIn("ALTER TABLE fake_table ADD COLUMN double_value DOUBLE NOT NULL DEFAULT 2.5", fake_db.sql)
        self.assertIn("ALTER TABLE fake_table ADD COLUMN bool_value INTEGER NOT NULL DEFAULT 1", fake_db.sql)
        self.assertIn("ALTER TABLE fake_table ADD COLUMN datetime_value DATETIME NOT NULL", fake_db.sql)
        self.assertIn("ALTER TABLE fake_table ADD COLUMN unknown_value TEXT NULL", fake_db.sql)
        self.assertIn("ALTER TABLE fake_table DROP COLUMN extra_column", fake_db.sql)
        sync_field_constraints.assert_called_once_with()

    def test_initialize_database_suppresses_table_check_and_alter_errors(self) -> None:
        fake_model = SimpleNamespace(
            _meta=SimpleNamespace(table_name="fake_table", fields={"missing_value": TextField(null=True)})
        )

        class FakeCursor:
            def fetchall(self):
                return [(0, "id")]

        class FailingAlterDb:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def table_exists(self, model):
                return True

            def execute_sql(self, sql):
                if sql.startswith("PRAGMA"):
                    return FakeCursor()
                raise RuntimeError("alter failed")

        with (
            patch.object(database_model_module, "db", FailingAlterDb()),
            patch.object(database_model_module, "MODELS", [fake_model]),
        ):
            database_model_module.initialize_database()

        class BrokenDb:
            def __enter__(self):
                raise RuntimeError("db unavailable")

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch.object(database_model_module, "db", BrokenDb()):
            database_model_module.initialize_database()

    def test_sync_field_constraints_skips_missing_fields_and_repairs_null_mismatches(self) -> None:
        fields = {
            "allows_null": TextField(null=True),
            "requires_value": TextField(null=False),
            "missing_value": TextField(null=True),
        }
        model = SimpleNamespace(_meta=SimpleNamespace(table_name="constraint_table", fields=fields))
        missing_model = SimpleNamespace(_meta=SimpleNamespace(table_name="missing_table", fields=fields))

        class FakeCursor:
            def fetchall(self):
                return [
                    (0, "allows_null", "TEXT", 1, None, 0),
                    (1, "requires_value", "TEXT", 0, None, 0),
                ]

        class FakeDb:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def table_exists(self, candidate):
                return candidate is model

            def execute_sql(self, sql):
                self.last_sql = sql
                return FakeCursor()

        with (
            patch.object(database_model_module, "db", FakeDb()),
            patch.object(database_model_module, "MODELS", [missing_model, model]),
            patch.object(database_model_module, "_fix_table_constraints") as fix_table_constraints,
        ):
            database_model_module.sync_field_constraints()

        fix_table_constraints.assert_called_once()
        table_name, fixed_model, constraints = fix_table_constraints.call_args.args
        self.assertEqual(table_name, "constraint_table")
        self.assertIs(fixed_model, model)
        self.assertEqual(
            [(constraint["field_name"], constraint["action"]) for constraint in constraints],
            [("allows_null", "allow_null"), ("requires_value", "disallow_null")],
        )

    def test_sync_field_constraints_suppresses_database_errors(self) -> None:
        class BrokenDb:
            def __enter__(self):
                raise RuntimeError("db unavailable")

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch.object(database_model_module, "db", BrokenDb()):
            database_model_module.sync_field_constraints()

    def test_check_field_constraints_reports_null_mismatches_and_suppresses_errors(self) -> None:
        fields = {
            "allows_null": TextField(null=True),
            "requires_value": TextField(null=False),
            "missing_value": TextField(null=True),
        }
        model = SimpleNamespace(_meta=SimpleNamespace(table_name="constraint_table", fields=fields))
        missing_model = SimpleNamespace(_meta=SimpleNamespace(table_name="missing_table", fields=fields))

        class FakeCursor:
            def fetchall(self):
                return [
                    (0, "allows_null", "TEXT", 1, None, 0),
                    (1, "requires_value", "TEXT", 0, None, 0),
                ]

        class FakeDb:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def table_exists(self, candidate):
                return candidate is model

            def execute_sql(self, sql):
                return FakeCursor()

        with (
            patch.object(database_model_module, "db", FakeDb()),
            patch.object(database_model_module, "MODELS", [missing_model, model]),
        ):
            inconsistencies = database_model_module.check_field_constraints()

        self.assertEqual(
            inconsistencies,
            {
                "constraint_table": [
                    {
                        "field_name": "allows_null",
                        "issue": "model_allows_null_but_db_not_null",
                        "model_constraint": "NULL",
                        "db_constraint": "NOT NULL",
                        "recommended_action": "allow_null",
                    },
                    {
                        "field_name": "requires_value",
                        "issue": "model_not_null_but_db_allows_null",
                        "model_constraint": "NOT NULL",
                        "db_constraint": "NULL",
                        "recommended_action": "disallow_null",
                    },
                ]
            },
        )

        class BrokenDb:
            def __enter__(self):
                raise RuntimeError("db unavailable")

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch.object(database_model_module, "db", BrokenDb()):
            self.assertEqual(database_model_module.check_field_constraints(), {})

    def test_fix_table_constraints_rebuilds_table_and_coalesces_nulls_for_not_null_fields(self) -> None:
        class UnknownField:
            pass

        fields = {
            "id": IntegerField(),
            "text_value": TextField(),
            "int_value": IntegerField(),
            "float_value": FloatField(),
            "double_value": DoubleField(),
            "bool_value": BooleanField(),
            "datetime_value": DateTimeField(),
            "unknown_value": UnknownField(),
        }
        model = SimpleNamespace(_meta=SimpleNamespace(fields=fields, primary_key=SimpleNamespace(name="id")))
        constraints_to_fix = [
            {"field_name": name, "action": "disallow_null", "current_constraint": "NULL", "target_constraint": "NOT NULL"}
            for name in fields
            if name != "id"
        ]

        class FakeCursor:
            def __init__(self, value):
                self.value = value

            def fetchone(self):
                return (self.value,)

        class FakeDb:
            def __init__(self) -> None:
                self.sql = []
                self.create_tables_calls = []

            def execute_sql(self, sql):
                self.sql.append(sql)
                if sql.startswith("SELECT COUNT(*) FROM rebuild_table_backup"):
                    return FakeCursor(2)
                if sql == "SELECT COUNT(*) FROM rebuild_table":
                    return FakeCursor(2)
                return SimpleNamespace()

            def create_tables(self, models):
                self.create_tables_calls.append(list(models))

        fake_db = FakeDb()

        with patch.object(database_model_module, "db", fake_db):
            database_model_module._fix_table_constraints("rebuild_table", model, constraints_to_fix)

        self.assertEqual(fake_db.create_tables_calls, [[model]])
        insert_sql = next(sql for sql in fake_db.sql if sql.startswith("INSERT INTO rebuild_table"))
        self.assertIn("COALESCE(text_value, '') as text_value", insert_sql)
        self.assertIn("COALESCE(int_value, 0) as int_value", insert_sql)
        self.assertIn("COALESCE(float_value, 0) as float_value", insert_sql)
        self.assertIn("COALESCE(double_value, 0) as double_value", insert_sql)
        self.assertIn("COALESCE(bool_value, 0) as bool_value", insert_sql)
        self.assertIn("COALESCE(datetime_value, '", insert_sql)
        self.assertIn("COALESCE(unknown_value, '') as unknown_value", insert_sql)
        self.assertTrue(any(sql.startswith("DROP TABLE rebuild_table_backup") for sql in fake_db.sql))

    def test_fix_table_constraints_handles_string_primary_key_direct_copy_and_count_mismatch(self) -> None:
        fields = {"custom_id": TextField(), "text_value": TextField()}
        model = SimpleNamespace(_meta=SimpleNamespace(fields=fields, primary_key="custom_id"))

        class FakeCursor:
            def __init__(self, value):
                self.value = value

            def fetchone(self):
                return (self.value,)

        class FakeDb:
            def __init__(self) -> None:
                self.sql = []

            def execute_sql(self, sql):
                self.sql.append(sql)
                if sql.startswith("SELECT COUNT(*) FROM direct_table_backup"):
                    return FakeCursor(2)
                if sql == "SELECT COUNT(*) FROM direct_table":
                    return FakeCursor(1)
                return SimpleNamespace()

            def create_tables(self, models):
                self.created_models = list(models)

        fake_db = FakeDb()

        with patch.object(database_model_module, "db", fake_db):
            database_model_module._fix_table_constraints("direct_table", model, [])

        insert_sql = next(sql for sql in fake_db.sql if sql.startswith("INSERT INTO direct_table"))
        self.assertEqual(
            insert_sql,
            "INSERT INTO direct_table (text_value) SELECT text_value FROM direct_table_backup_"
            + insert_sql.rsplit("_", 1)[-1],
        )
        self.assertFalse(any(sql.startswith("DROP TABLE direct_table_backup") for sql in fake_db.sql))

    def test_fix_table_constraints_uses_all_fields_when_primary_key_lookup_fails_or_is_absent(self) -> None:
        class BrokenMeta:
            fields = {"field_one": TextField(), "field_two": TextField()}

            @property
            def primary_key(self):
                raise RuntimeError("metadata unavailable")

        model = SimpleNamespace(_meta=BrokenMeta())
        constraints_to_fix = [
            {
                "field_name": "field_one",
                "action": "disallow_null",
                "current_constraint": "NULL",
                "target_constraint": "NOT NULL",
            }
        ]

        class FakeCursor:
            def fetchone(self):
                return (1,)

        class FakeDb:
            def __init__(self) -> None:
                self.sql = []

            def execute_sql(self, sql):
                self.sql.append(sql)
                return FakeCursor()

            def create_tables(self, models):
                self.created_models = list(models)

        fake_db = FakeDb()

        with patch.object(database_model_module, "db", fake_db):
            database_model_module._fix_table_constraints("no_pk_table", model, constraints_to_fix)

        insert_sql = next(sql for sql in fake_db.sql if sql.startswith("INSERT INTO no_pk_table"))
        self.assertIn("INSERT INTO no_pk_table (field_one, field_two)", insert_sql)
        self.assertIn("COALESCE(field_one, '') as field_one, field_two", insert_sql)

    def test_fix_table_constraints_restores_backup_on_failure_and_suppresses_restore_errors(self) -> None:
        model = SimpleNamespace(_meta=SimpleNamespace(fields={"id": IntegerField()}, primary_key=SimpleNamespace(name="id")))

        class RecoveringDb:
            def __init__(self) -> None:
                self.sql = []

            def execute_sql(self, sql):
                self.sql.append(sql)
                if sql.startswith("DROP TABLE broken_table"):
                    raise RuntimeError("drop failed")
                return SimpleNamespace(fetchone=lambda: (1,))

            def create_tables(self, models):
                self.created_models = list(models)

            def table_exists(self, table_name):
                return True

        recovering_db = RecoveringDb()

        with patch.object(database_model_module, "db", recovering_db):
            database_model_module._fix_table_constraints("broken_table", model, [])

        self.assertIn("DROP TABLE IF EXISTS broken_table", recovering_db.sql)
        self.assertTrue(any(sql.startswith("ALTER TABLE broken_table_backup_") for sql in recovering_db.sql))

        class RestoreFailingDb(RecoveringDb):
            def execute_sql(self, sql):
                if sql.startswith("CREATE TABLE"):
                    raise RuntimeError("backup failed")
                return super().execute_sql(sql)

            def table_exists(self, table_name):
                raise RuntimeError("restore check failed")

        with patch.object(database_model_module, "db", RestoreFailingDb()):
            database_model_module._fix_table_constraints("restore_broken_table", model, [])

    def test_fix_image_id_assigns_missing_ids_and_suppresses_database_errors(self) -> None:
        class FakeDb:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        missing_image = SimpleNamespace(id=1, image_id="", save=Mock())
        existing_image = SimpleNamespace(id=2, image_id="existing-id", save=Mock())

        class FakeImages:
            @staticmethod
            def select():
                return [missing_image, existing_image]

        with (
            patch.object(database_model_module, "db", FakeDb()),
            patch.object(database_model_module, "Images", FakeImages),
            patch("uuid.uuid4", return_value="generated-id"),
        ):
            database_model_module.fix_image_id()

        self.assertEqual(missing_image.image_id, "generated-id")
        missing_image.save.assert_called_once_with()
        existing_image.save.assert_not_called()

        class BrokenDb:
            def __enter__(self):
                raise RuntimeError("db unavailable")

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch.object(database_model_module, "db", BrokenDb()):
            database_model_module.fix_image_id()


if __name__ == "__main__":
    unittest.main()
