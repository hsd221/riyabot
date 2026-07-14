import datetime
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from peewee import IntegrityError

from src.memory import layer0_archive
from src.memory.layer0_archive import MessageArchiver, _get_attr, _model_to_dict, _resolve_timestamp
from src.memory.schema import RawMessageArchive, configure_memory_database, initialize_database, memory_db


class MemoryDatabaseFixtureMixin:
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_path = memory_db.database
        configure_memory_database(str(Path(self.tmpdir.name) / "memory.db"))
        initialize_database()

    def tearDown(self) -> None:
        if not memory_db.is_closed():
            memory_db.close()
        configure_memory_database(str(self.original_path))
        self.tmpdir.cleanup()


def create_raw_message(message_id: str, *, stream_id: str = "stream-1", user_id: str = "user-1", **overrides) -> None:
    data = {
        "stream_id": stream_id,
        "message_id": message_id,
        "user_id": user_id,
        "content": f"{message_id} 内容",
        "timestamp": 100.0,
        "chat_type": "group",
    }
    data.update(overrides)
    RawMessageArchive.create(**data)


class Layer0ArchiveHelperTest(unittest.TestCase):
    def test_attr_and_timestamp_helpers_accept_candidates_and_fallbacks(self) -> None:
        source = SimpleNamespace(primary=None, secondary="value")
        moment = datetime.datetime.fromtimestamp(123.0)

        self.assertEqual(_get_attr(source, ["primary", "secondary"]), "value")
        with self.assertRaises(ValueError):
            _get_attr(SimpleNamespace(), ["missing"])

        with patch.object(layer0_archive.time, "time", return_value=999.0):
            self.assertEqual(_resolve_timestamp(None), 999.0)
            self.assertEqual(_resolve_timestamp("not-time"), 999.0)
        self.assertEqual(_resolve_timestamp(123), 123.0)
        self.assertEqual(_resolve_timestamp(123_000_000_000), 123_000_000.0)
        self.assertEqual(_resolve_timestamp(moment), 123.0)


class MessageArchiverTest(MemoryDatabaseFixtureMixin, unittest.IsolatedAsyncioTestCase):
    async def test_extract_archive_group_private_batch_and_model_dict_preserve_fields(self) -> None:
        archiver = MessageArchiver()
        group_message = SimpleNamespace(
            group_id="group-1",
            id="msg-1",
            sender_id="user-1",
            text="群聊内容",
            created_at=datetime.datetime.fromtimestamp(10.0),
            user_platform="qq",
            user_nickname="小明",
            user_cardname="群名片",
            group_info=SimpleNamespace(group_id="group-1", group_name="测试群"),
        )
        private_message = SimpleNamespace(
            stream_id="private-1",
            message_id="msg-2",
            user_id="user-2",
            content="私聊内容",
            timestamp=20.0,
        )
        batch_private = SimpleNamespace(
            chat_id="chat-3",
            msg_id="msg-3",
            author_id="user-3",
            body="批量私聊",
            time=30.0,
            chat_type="private",
        )
        batch_group = SimpleNamespace(
            chat_id="chat-4",
            msg_id="msg-4",
            author_id="user-4",
            body="批量群聊",
            time=40.0,
        )

        fields = archiver._extract_message_fields(group_message, "group")
        group_id = await archiver.archive_group_message(group_message)
        duplicate_group_id = await archiver.archive_group_message(group_message)
        private_id = await archiver.archive_private_message(private_message)
        batch_ids = await archiver.archive_batch([batch_private, batch_group])
        row = RawMessageArchive.get(RawMessageArchive.message_id == "msg-1")
        row.dream_status = "triaged"
        row.dream_route = "high"
        row.dream_significance = 0.9
        row.save()
        serialized = _model_to_dict(row)

        self.assertEqual(fields["stream_id"], "group-1")
        self.assertEqual(fields["message_id"], "msg-1")
        self.assertEqual(fields["timestamp"], 10.0)
        self.assertEqual(fields["platform"], "qq")
        self.assertEqual(fields["nickname"], "小明")
        self.assertEqual(fields["cardname"], "群名片")
        self.assertEqual(fields["group_name"], "测试群")
        self.assertEqual(group_id, duplicate_group_id)
        self.assertNotEqual(group_id, private_id)
        self.assertEqual(len(batch_ids), 2)
        self.assertEqual(RawMessageArchive.select().count(), 4)
        self.assertEqual(RawMessageArchive.get(RawMessageArchive.message_id == "msg-3").chat_type, "private")
        self.assertEqual(RawMessageArchive.get(RawMessageArchive.message_id == "msg-4").chat_type, "group")
        self.assertEqual(serialized["dream_status"], "triaged")
        self.assertEqual(serialized["dream_route"], "high")
        self.assertEqual(serialized["dream_significance"], 0.9)
        self.assertEqual(serialized["platform"], "qq")
        self.assertEqual(serialized["nickname"], "小明")
        self.assertEqual(serialized["cardname"], "群名片")
        self.assertEqual(serialized["group_id"], "group-1")
        self.assertEqual(serialized["group_name"], "测试群")

    def test_insert_record_handles_integrity_race_or_reraises_when_record_is_still_missing(self) -> None:
        archiver = MessageArchiver()
        fields = {
            "stream_id": "stream-1",
            "message_id": "msg-1",
            "user_id": "user-1",
            "content": "内容",
            "timestamp": 1.0,
            "chat_type": "group",
        }
        existing = SimpleNamespace(id=7, stream_id="stream-1", message_id="msg-1", chat_type="group")

        with (
            patch.object(layer0_archive.RawMessageArchive, "get_or_none", side_effect=[None, existing]),
            patch.object(layer0_archive.RawMessageArchive, "create", side_effect=IntegrityError("race")),
        ):
            self.assertIs(archiver._insert_record(fields), existing)

        with (
            patch.object(layer0_archive.RawMessageArchive, "get_or_none", side_effect=[None, None]),
            patch.object(layer0_archive.RawMessageArchive, "create", side_effect=IntegrityError("race")),
        ):
            with self.assertRaises(IntegrityError):
                archiver._insert_record(fields)

    async def test_query_stats_and_cleanup_apply_ordering_time_windows_and_empty_stream_defaults(self) -> None:
        create_raw_message("old", timestamp=10.0, user_id="user-1")
        create_raw_message("middle", timestamp=20.0, user_id="user-2")
        create_raw_message("new", timestamp=30.0, user_id="user-1")
        create_raw_message("other-stream", stream_id="stream-2", timestamp=40.0, user_id="user-3")
        archiver = MessageArchiver()

        stream_rows = await archiver.query_by_stream("stream-1", limit=5, before_timestamp=35.0, after_timestamp=15.0)
        user_rows = await archiver.query_by_user("user-1", limit=5)
        stats = await archiver.get_stream_stats("stream-1")
        empty_stats = await archiver.get_stream_stats("missing")
        with patch.object(layer0_archive.time, "time", return_value=35.0 + 2 * 86400):
            deleted = await archiver.cleanup_old_messages(older_than_days=2)

        self.assertEqual([row["message_id"] for row in stream_rows], ["new", "middle"])
        self.assertEqual([row["message_id"] for row in user_rows], ["new", "old"])
        self.assertEqual(
            stats,
            {
                "stream_id": "stream-1",
                "total_messages": 3,
                "time_range": {"earliest": 10.0, "latest": 30.0},
                "active_users": 2,
            },
        )
        self.assertEqual(
            empty_stats,
            {
                "stream_id": "missing",
                "total_messages": 0,
                "time_range": None,
                "active_users": 0,
            },
        )
        self.assertEqual(deleted, 3)
        self.assertEqual([row.message_id for row in RawMessageArchive.select()], ["other-stream"])


if __name__ == "__main__":
    unittest.main()
