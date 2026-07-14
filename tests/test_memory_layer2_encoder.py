import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.memory import layer2_encoder
from src.memory.atom import AtomType
from src.memory.layer2_encoder import (
    BatchEncoder,
    EncodingBuffer,
    SOURCE_IDENTITIES_DETAIL_KEY,
    SOURCE_MESSAGE_IDS_DETAIL_KEY,
    SOURCE_USER_IDS_DETAIL_KEY,
)


class FakeStore:
    pass


class StubEncoder(BatchEncoder):
    def __init__(self, *args, llm_response: str = "[]", llm_error: Exception | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.llm_response = llm_response
        self.llm_error = llm_error

    async def _call_llm(self, prompt: str) -> str:
        if self.llm_error:
            raise self.llm_error
        return self.llm_response


def make_encoder(**kwargs) -> BatchEncoder:
    encoder = BatchEncoder(store=FakeStore(), **kwargs)  # type: ignore[arg-type]
    encoder.group_summarizer = SimpleNamespace(
        add_message_async=AsyncMock(),
        get_topic_summaries=Mock(return_value=[]),
        reset_stream=Mock(),
    )
    encoder.private_summarizer = SimpleNamespace(
        append_exchange=Mock(),
        get_summary=Mock(return_value=""),
        reset=Mock(),
    )
    return encoder


class EncodingBufferTest(unittest.TestCase):
    def test_add_message_deduplicates_overflows_and_clear_resets_trigger_state(self) -> None:
        buffer = EncodingBuffer(stream_id="stream-1", max_buffer_size=2)

        self.assertTrue(buffer.add_message("user-1", "Alice", "first", 1.0, message_id="msg-1"))
        self.assertFalse(buffer.add_message("user-1", "Alice", "duplicate", 2.0, message_id="msg-1"))
        self.assertTrue(buffer.add_message("user-2", "Bob", "second", 3.0, message_id="msg-2"))
        self.assertTrue(buffer.add_message("user-3", "Carol", "third", 4.0, message_id="msg-3"))

        self.assertEqual(len(buffer), 2)
        self.assertEqual([msg["message_id"] for msg in buffer.messages], ["msg-2", "msg-3"])
        self.assertEqual(buffer.message_count_since_trigger, 3)

        with patch.object(layer2_encoder.time, "time", return_value=99.0):
            buffer.clear()

        self.assertEqual(buffer.messages, [])
        self.assertEqual(buffer.last_trigger_time, 99.0)
        self.assertEqual(buffer.message_count_since_trigger, 0)


class BatchEncoderIngestAndTriggerTest(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_routes_group_private_messages_and_honors_duplicate_ids(self) -> None:
        encoder = make_encoder()
        timestamp = datetime.fromtimestamp(123.0)

        await encoder.ingest_message("group-1", "user-1", "Alice", "hello", timestamp, message_id="msg-1")
        await encoder.ingest_message("group-1", "user-1", "Alice", "duplicate", timestamp, message_id="msg-1")
        encoder.set_stream_type("private_private_user-1", "private_chat")
        await encoder.ingest_message("private_private_user-1", "user-1", "Alice", "private", timestamp)
        encoder.set_stream_type("private_private_user-1", "group_chat")

        encoder.group_summarizer.add_message_async.assert_awaited_once_with(
            stream_id="group-1",
            message_text="hello",
            user_id="user-1",
            timestamp=123.0,
            speaker="Alice",
        )
        encoder.private_summarizer.append_exchange.assert_called_once_with(
            stream_id="private_private_user-1",
            speaker="Alice",
            content="private",
            timestamp=123.0,
        )
        self.assertEqual(encoder.buffers["private_private_user-1"].stream_type, "group_chat")

    async def test_ingest_preserves_platform_identity_metadata_for_profile_scoping(self) -> None:
        encoder = make_encoder()
        await encoder.ingest_message(
            "group-1",
            "42",
            "群昵称",
            "我喜欢梦幻游戏",
            datetime.fromtimestamp(123.0),
            message_id="msg-42",
            platform="qq",
            nickname="QQ 昵称",
            cardname="群名片",
            group_id="g1",
            group_name="测试群",
        )

        message = encoder.buffers["group-1"].messages[0]
        self.assertEqual(message["platform"], "qq")
        self.assertEqual(message["nickname"], "QQ 昵称")
        self.assertEqual(message["cardname"], "群名片")
        self.assertEqual(message["group_id"], "g1")

        identities = BatchEncoder._source_identities([message])
        self.assertEqual(identities[0]["platform"], "qq")
        self.assertEqual(identities[0]["user_id"], "42")
        self.assertEqual(BatchEncoder._source_message_ids([message]), ["msg-42"])

    def test_trigger_stats_and_stream_management_cover_buffer_lifecycle(self) -> None:
        encoder = make_encoder(trigger_count=2, trigger_seconds=10)

        self.assertFalse(encoder.should_trigger("missing"))
        encoder.buffers["empty"] = EncodingBuffer(stream_id="empty")
        self.assertFalse(encoder.should_trigger("empty"))

        with patch.object(layer2_encoder.time, "time", return_value=100.0):
            buffer = EncodingBuffer(stream_id="stream-1", last_trigger_time=95.0)
            buffer.add_message("user-1", "Alice", "hello", 1.0)
            encoder.buffers["stream-1"] = buffer

            self.assertFalse(encoder.should_trigger("stream-1"))
            self.assertEqual(encoder.get_ready_streams(), [])
            self.assertEqual(encoder.get_pending_streams(), ["stream-1"])

            buffer.message_count_since_trigger = 2
            self.assertTrue(encoder.should_trigger("stream-1"))
            self.assertEqual(encoder.get_ready_streams(), ["stream-1"])

            stats = encoder.get_buffer_stats("stream-1")
            self.assertEqual(stats["stream_id"], "stream-1")  # type: ignore[index]
            self.assertEqual(stats["buffer_size"], 1)  # type: ignore[index]
            self.assertEqual(stats["last_trigger_ago"], 5.0)  # type: ignore[index]
            self.assertTrue(stats["should_trigger"])  # type: ignore[index]

            buffer.message_count_since_trigger = 1
            buffer.last_trigger_time = 80.0
            self.assertTrue(encoder.should_trigger("stream-1"))

        self.assertIsNone(encoder.get_buffer_stats("missing"))
        self.assertEqual(set(encoder.get_all_streams()), {"empty", "stream-1"})
        self.assertEqual([(sid, buf.stream_id) for sid, buf in encoder.iter_pending()], [("stream-1", "stream-1")])

        encoder.clear_all()
        self.assertEqual(encoder.get_pending_streams(), [])
        self.assertTrue(encoder.remove_stream("stream-1"))
        self.assertFalse(encoder.remove_stream("missing"))
        encoder.reset_all()
        self.assertEqual(encoder.get_all_streams(), [])


class BatchEncoderEncodeBatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_encode_batch_returns_early_for_missing_empty_and_unready_streams(self) -> None:
        encoder = StubEncoder(store=FakeStore(), trigger_count=3)  # type: ignore[arg-type]
        encoder.group_summarizer = SimpleNamespace(get_topic_summaries=Mock(return_value=[]))

        self.assertEqual(await encoder.encode_batch("missing"), [])

        encoder.buffers["empty"] = EncodingBuffer(stream_id="empty")
        self.assertEqual(await encoder.encode_batch("empty"), [])

        encoder.buffers["waiting"] = EncodingBuffer(stream_id="waiting")
        encoder.buffers["waiting"].add_message("user-1", "Alice", "hello", 1.0)
        self.assertEqual(await encoder.encode_batch("waiting"), [])
        self.assertEqual(len(encoder.buffers["waiting"]), 1)

    async def test_encode_batch_keeps_buffer_on_llm_or_parse_failure_and_clears_after_success(self) -> None:
        failing = StubEncoder(store=FakeStore(), llm_error=RuntimeError("llm down"))  # type: ignore[arg-type]
        failing.group_summarizer = SimpleNamespace(get_topic_summaries=Mock(return_value=[]))
        failing.buffers["stream-1"] = EncodingBuffer(stream_id="stream-1")
        failing.buffers["stream-1"].add_message("user-1", "Alice", "hello", 1.0)

        self.assertEqual(await failing.encode_batch("stream-1", force=True), [])
        self.assertEqual(len(failing.buffers["stream-1"]), 1)

        invalid = StubEncoder(store=FakeStore(), llm_response="not json")  # type: ignore[arg-type]
        invalid.group_summarizer = SimpleNamespace(get_topic_summaries=Mock(return_value=[]))
        invalid.buffers["stream-1"] = EncodingBuffer(stream_id="stream-1")
        invalid.buffers["stream-1"].add_message("user-1", "Alice", "hello", 1.0)

        self.assertEqual(await invalid.encode_batch("stream-1", force=True), [])
        self.assertEqual(len(invalid.buffers["stream-1"]), 1)

        response = json.dumps(
            [
                {
                    "content": "user-2 喜欢茶",
                    "atom_type": "preference",
                    "entities": ["user-2"],
                    "importance": 0.7,
                    "detail": {"attr_name": "drink", "attr_value": "tea"},
                }
            ],
            ensure_ascii=False,
        )
        encoder = StubEncoder(
            store=FakeStore(),  # type: ignore[arg-type]
            llm_response=response,
            max_messages_per_batch=1,
        )
        encoder.group_summarizer = SimpleNamespace(get_topic_summaries=Mock(return_value=[]))
        encoder.buffers["stream-1"] = EncodingBuffer(stream_id="stream-1")
        encoder.buffers["stream-1"].add_message("user-1", "Alice", "old", 1.0)
        encoder.buffers["stream-1"].add_message("user-2", "Bob", "new", 2.0)

        extracted = await encoder.encode_batch("stream-1", force=True)

        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0][1], AtomType.PREFERENCE)
        self.assertEqual(extracted[0][2][SOURCE_USER_IDS_DETAIL_KEY], ["user-2"])
        self.assertEqual(extracted[0][2][SOURCE_MESSAGE_IDS_DETAIL_KEY], [])
        self.assertEqual(extracted[0][2][SOURCE_IDENTITIES_DETAIL_KEY][0]["platform"], "legacy")
        self.assertEqual(len(encoder.buffers["stream-1"]), 0)

    async def test_encode_all_ready_filters_empty_results(self) -> None:
        encoder = make_encoder()
        encoder.get_ready_streams = Mock(return_value=["stream-1", "stream-2"])  # type: ignore[method-assign]
        encoder.encode_batch = AsyncMock(side_effect=[[("content", AtomType.RELATIONAL, {})], []])  # type: ignore[method-assign]

        self.assertEqual(await encoder.encode_all_ready(), {"stream-1": [("content", AtomType.RELATIONAL, {})]})


class BatchEncoderParsingAndValidationTest(unittest.TestCase):
    def test_call_llm_uses_configured_task_or_falls_back_to_utils_and_strips_response(self) -> None:
        fake_request = SimpleNamespace(
            generate_response_async=AsyncMock(side_effect=[(" result ", (None, "model-x")), (" again ", None)])
        )

        with (
            patch.object(
                layer2_encoder,
                "model_config",
                SimpleNamespace(model_task_config=SimpleNamespace(utils="utils-config")),
            ),
            patch.object(layer2_encoder, "LLMRequest", Mock(return_value=fake_request)) as request_cls,
        ):
            encoder = BatchEncoder(store=FakeStore(), task_name="missing_task")  # type: ignore[arg-type]
            first = self.run_async(encoder._call_llm("prompt"))
            second = self.run_async(encoder._call_llm("prompt"))

        self.assertEqual(first, "result")
        self.assertEqual(second, "again")
        request_cls.assert_called_once_with(model_set="utils-config", request_type="memory_encoder")
        self.assertEqual(fake_request.generate_response_async.await_count, 2)

    def test_parse_llm_extraction_accepts_json_blocks_and_rejects_invalid_shapes(self) -> None:
        encoder = make_encoder()
        markdown = """```json
        [{"content": "user-1 喜欢爵士乐", "atom_type": "preference",
          "detail": {"attr_name": "music", "attr_value": "jazz"}}]
        ```"""
        generic_block = """```
        [{"content": "Alice 是 Bob 的朋友", "atom_type": "relational"}]
        ```"""

        self.assertIsNone(encoder._parse_llm_extraction(""))
        self.assertIsNone(encoder._parse_llm_extraction("not json"))
        self.assertIsNone(encoder._parse_llm_extraction('{"content": "not a list"}'))
        self.assertEqual(encoder._parse_llm_extraction(markdown)[0][1], AtomType.PREFERENCE)  # type: ignore[index]
        self.assertEqual(encoder._parse_llm_extraction(generic_block)[0][1], AtomType.RELATIONAL)  # type: ignore[index]
        self.assertIsNone(BatchEncoder._extract_json_block("```json\n[]"))

        with patch.object(
            encoder,
            "_validate_atom_item",
            side_effect=[ValueError("bad item"), ("content", AtomType.RELATIONAL, {})],
        ):
            self.assertEqual(
                encoder._parse_llm_extraction('[{"bad": true}, {"ok": true}]'),
                [("content", AtomType.RELATIONAL, {})],
            )

    def test_safe_text_list_and_source_user_helpers_reject_untrusted_shapes(self) -> None:
        self.assertEqual(BatchEncoder._safe_text({"bad": "shape"}), "")
        self.assertEqual(BatchEncoder._safe_text("  abc  ", max_length=2), "ab")
        self.assertEqual(BatchEncoder._safe_str_list("not-list"), [])
        self.assertEqual(BatchEncoder._safe_str_list(["a", "", "a", {"bad": 1}, "b"], max_items=2), ["a", "b"])
        self.assertEqual(
            BatchEncoder._source_user_ids(
                [
                    {"user_id": "user-1"},
                    {"user_id": "user-1"},
                    {"user_id": ""},
                    {"user_id": ["bad"]},
                    {"user_id": "user-2"},
                ]
            ),
            ["user-1", "user-2"],
        )

    def test_validate_atom_item_normalizes_details_and_rejects_semantically_invalid_items(self) -> None:
        encoder = make_encoder()

        self.assertIsNone(encoder._validate_atom_item("not-dict"))
        self.assertIsNone(encoder._validate_atom_item({"content": "", "atom_type": "factual"}))
        self.assertIsNone(encoder._validate_atom_item({"content": "valid content", "atom_type": "bad"}))
        self.assertIsNone(
            encoder._validate_atom_item(
                {
                    "content": "user-1 喜欢爵士乐",
                    "atom_type": "factual",
                    "detail": {"attr_name": "music"},
                }
            )
        )
        self.assertIsNone(
            encoder._validate_atom_item(
                {
                    "content": "user-1 喜欢爵士乐",
                    "atom_type": "preference",
                    "detail": "not-dict",
                }
            )
        )
        self.assertIsNone(
            encoder._validate_atom_item(
                {
                    "content": "Calm",
                    "atom_type": "episodic",
                    "entities": [],
                    "detail": {"participants": []},
                }
            )
        )

        factual = encoder._validate_atom_item(
            {
                "content": "user-1 喜欢爵士乐",
                "atom_type": "factual",
                "entities": ["user-1"],
                "importance": "bad",
                "detail": {"attr_category": "", "attr_name": "music", "attr_value": "jazz"},
            }
        )
        relational = encoder._validate_atom_item(
            {"content": "Alice 是 Bob 的朋友", "atom_type": "relational", "importance": -1}
        )

        self.assertEqual(factual[2]["importance"], 0.5)  # type: ignore[index]
        self.assertEqual(factual[2]["attr_category"], "general")  # type: ignore[index]
        self.assertEqual(relational[2], {"entities": [], "importance": 0.0})  # type: ignore[index]

    def test_semantic_validate_and_normalize_detail_cover_direct_guard_branches(self) -> None:
        encoder = make_encoder()

        self.assertFalse(encoder._semantic_validate("123 !!!", AtomType.RELATIONAL, {}, []))
        self.assertFalse(encoder._semantic_validate("valid", AtomType.RELATIONAL, {}, [""]))
        self.assertFalse(encoder._semantic_validate("valid", AtomType.RELATIONAL, {}, ["x"] * 13))
        self.assertFalse(encoder._semantic_validate("valid", AtomType.RELATIONAL, {}, ["x" * 201]))
        self.assertFalse(encoder._semantic_validate("valid", AtomType.FACTUAL, {"attr_name": "", "attr_value": ""}, []))
        self.assertFalse(encoder._semantic_validate("valid", AtomType.PREFERENCE, {"attr_name": ""}, []))
        self.assertEqual(BatchEncoder._normalize_detail("unknown", {}, []), {})  # type: ignore[arg-type]

    def test_topic_summary_formats_group_topics_and_private_summary(self) -> None:
        encoder = make_encoder()
        encoder.group_summarizer.get_topic_summaries.return_value = []
        self.assertEqual(encoder._get_topic_summary("stream-1", "group_chat"), "")

        encoder.group_summarizer.get_topic_summaries.return_value = [
            {"keywords": ["爵士", "排练"], "key_points": ["周末集合", "带乐器"]},
            {"keywords": [], "key_points": ["确认时间"]},
        ]
        group_summary = encoder._get_topic_summary("stream-1", "group_chat")

        self.assertIn("话题关键词: 爵士, 排练", group_summary)
        self.assertIn("要点: 周末集合; 带乐器", group_summary)
        self.assertIn("要点: 确认时间", group_summary)

        encoder.private_summarizer.get_summary.return_value = "私聊摘要"
        self.assertEqual(encoder._get_topic_summary("stream-1", "private_chat"), "私聊摘要")
        encoder.private_summarizer.get_summary.return_value = ""
        self.assertEqual(encoder._get_topic_summary("stream-1", "private_chat"), "")

    @staticmethod
    def run_async(awaitable):
        import asyncio

        return asyncio.run(awaitable)


if __name__ == "__main__":
    unittest.main()
