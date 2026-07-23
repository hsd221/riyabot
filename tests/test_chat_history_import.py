import json
import tempfile
import unittest
from pathlib import Path


class QQChatExportParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _write_export(self, messages: list[dict], *, chat_info: dict | None = None) -> Path:
        payload = {
            "metadata": {"name": "QQChatExporter", "version": "0.1.0"},
            "chatInfo": chat_info
            or {
                "name": "测试群",
                "type": "group",
                "selfUin": "10000",
                "peerUid": "123456",
            },
            "statistics": {"totalMessages": len(messages)},
            "messages": messages,
            "exportOptions": {"options": {"encoding": "utf-8"}},
        }
        source = self.root / "history.json"
        source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return source

    @staticmethod
    def _message(
        message_id: str,
        text: str,
        *,
        timestamp: int = 1_750_000_000_000,
        sender_uin: str = "20001",
        sender_name: str = "甲",
        message_type: str = "text",
        recalled: bool = False,
        system: bool = False,
        elements: list[dict] | None = None,
    ) -> dict:
        return {
            "id": message_id,
            "timestamp": timestamp,
            "sender": {
                "uid": f"uid-{sender_uin}",
                "uin": sender_uin,
                "name": sender_name,
                "groupCard": f"{sender_name}名片",
            },
            "type": message_type,
            "content": {
                "text": text,
                "elements": elements if elements is not None else [{"type": "text", "data": {"text": text}}],
                "resources": [],
                "mentions": [],
            },
            "recalled": recalled,
            "system": system,
        }

    def test_stream_parser_handles_small_chunks_unicode_and_reply_evidence(self) -> None:
        from src.bw_learner.history_import import analyze_qq_chat_export, iter_normalized_messages

        messages = [
            self._message("m1", "第一条，含中文"),
            self._message(
                "m2",
                "[回复消息]@甲 收到",
                timestamp=1_750_000_001_000,
                sender_uin="20002",
                sender_name="乙",
                message_type="reply",
                elements=[
                    {
                        "type": "reply",
                        "data": {
                            "referencedMessageId": "m1",
                            "senderUin": "20001",
                            "senderName": "甲",
                            "content": "第一条，含中文",
                        },
                    },
                    {"type": "at", "data": {"uin": "20001", "name": "甲"}},
                    {"type": "text", "data": {"text": " 收到"}},
                ],
            ),
        ]
        source = self._write_export(messages)
        normalized = self.root / "normalized.jsonl"

        analysis = analyze_qq_chat_export(source, normalized, read_chunk_chars=7)
        parsed = list(iter_normalized_messages(normalized))

        self.assertEqual(analysis.source_format, "qq_chat_exporter")
        self.assertEqual(analysis.chat.name, "测试群")
        self.assertEqual(analysis.chat.source_id, "123456")
        self.assertEqual(analysis.total_messages, 2)
        self.assertEqual(analysis.retained_messages, 2)
        self.assertEqual([message.content for message in parsed], ["第一条，含中文", "收到"])
        self.assertEqual(parsed[1].reply_to_id, "m1")
        self.assertEqual(parsed[1].sender_id, "20002")
        self.assertEqual(parsed[1].sender_card, "乙名片")

    def test_bot_detection_does_not_depend_on_top_level_field_order(self) -> None:
        from src.bw_learner.history_import import analyze_qq_chat_export, iter_normalized_messages

        payload = {
            "messages": [self._message("bot-message", "Bot 历史发言", sender_uin="10000", sender_name="Bot")],
            "metadata": {"name": "QQChatExporter", "version": "0.1.0"},
            "chatInfo": {
                "name": "测试群",
                "type": "group",
                "selfUin": "10000",
                "peerUid": "123456",
            },
        }
        source = self.root / "reordered.json"
        source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        normalized = self.root / "normalized.jsonl"

        analysis = analyze_qq_chat_export(source, normalized, read_chunk_chars=7)
        parsed = list(iter_normalized_messages(normalized))

        self.assertTrue(parsed[0].is_bot)
        self.assertTrue(analysis.participants[0].is_bot)

    def test_noise_filter_counts_hard_noise_and_collapses_same_sender_bursts(self) -> None:
        from src.bw_learner.history_import import analyze_qq_chat_export, iter_normalized_messages

        base = 1_750_000_000_000
        messages = [
            self._message("system", "某人加入群聊", system=True),
            self._message("recalled", "撤回内容", recalled=True),
            self._message(
                "image",
                "[图片:a.jpg]",
                message_type="text",
                elements=[{"type": "image", "data": {"filename": "a.jpg"}}],
            ),
            self._message(
                "mention",
                "@乙",
                elements=[{"type": "at", "data": {"uin": "20002", "name": "乙"}}],
            ),
            self._message("punct", "？？？"),
            self._message("repeat-1", "醍醐灌顶", timestamp=base + 1_000),
            self._message("repeat-2", "醍醐灌顶", timestamp=base + 2_000),
            self._message("repeat-3", "醍醐灌顶", timestamp=base + 3_000),
            self._message(
                "other-repeat",
                "醍醐灌顶",
                timestamp=base + 4_000,
                sender_uin="20002",
                sender_name="乙",
            ),
            self._message("ack", "行", timestamp=base + 5_000),
        ]
        source = self._write_export(messages)
        normalized = self.root / "normalized.jsonl"

        analysis = analyze_qq_chat_export(source, normalized, bot_user_ids={"10000"})
        parsed = list(iter_normalized_messages(normalized))

        self.assertEqual(analysis.total_messages, 10)
        self.assertEqual(analysis.retained_messages, 4)
        self.assertEqual(analysis.filtered_messages, 6)
        self.assertEqual(analysis.noise_counts["system"], 1)
        self.assertEqual(analysis.noise_counts["recalled"], 1)
        self.assertEqual(analysis.noise_counts["no_text"], 2)
        self.assertEqual(analysis.noise_counts["punctuation_only"], 1)
        self.assertEqual(analysis.noise_counts["duplicate_burst"], 1)
        self.assertEqual([message.message_id for message in parsed], ["repeat-1", "repeat-2", "other-repeat", "ack"])
        self.assertTrue(parsed[-1].is_low_signal)

    def test_normalization_bounds_untrusted_message_fields(self) -> None:
        from src.bw_learner.history_import import (
            MAX_DISPLAY_NAME_CHARS,
            MAX_MESSAGE_CONTENT_CHARS,
            analyze_qq_chat_export,
            iter_normalized_messages,
        )

        messages = [
            self._message(
                "m1",
                "长" * (MAX_MESSAGE_CONTENT_CHARS + 100),
                sender_name="名" * (MAX_DISPLAY_NAME_CHARS + 100),
            ),
            self._message("m" * 129, "无效消息编号"),
        ]
        source = self._write_export(messages)
        normalized = self.root / "normalized.jsonl"

        analysis = analyze_qq_chat_export(source, normalized)
        parsed = list(iter_normalized_messages(normalized))

        self.assertEqual(analysis.retained_messages, 1)
        self.assertEqual(analysis.noise_counts["missing_message_id"], 1)
        self.assertEqual(len(parsed[0].content), MAX_MESSAGE_CONTENT_CHARS)
        self.assertEqual(len(parsed[0].sender_name), MAX_DISPLAY_NAME_CHARS)

    def test_filters_non_finite_or_implausible_timestamps(self) -> None:
        from src.bw_learner.history_import import analyze_qq_chat_export, iter_normalized_messages

        messages = [
            self._message("valid", "有效消息"),
            self._message("nan", "无效时间", timestamp="NaN"),
            self._message("huge", "过大时间", timestamp=10**40),
        ]
        source = self._write_export(messages)
        normalized = self.root / "normalized.jsonl"

        analysis = analyze_qq_chat_export(source, normalized)
        parsed = list(iter_normalized_messages(normalized))

        self.assertEqual([message.message_id for message in parsed], ["valid"])
        self.assertEqual(analysis.noise_counts["invalid_timestamp"], 2)

    def test_rejects_unknown_or_private_export_shape(self) -> None:
        from src.bw_learner.history_import import ChatHistoryFormatError, analyze_qq_chat_export

        source = self._write_export([], chat_info={"name": "私聊", "type": "private", "peerUid": "u-1"})

        with self.assertRaisesRegex(ChatHistoryFormatError, "仅支持 QQ 群聊"):
            analyze_qq_chat_export(source, self.root / "normalized.jsonl")

    def test_rejects_an_oversized_single_json_value_and_removes_partial_output(self) -> None:
        from src.bw_learner.history_import import (
            MAX_RAW_JSON_VALUE_CHARS,
            ChatHistoryFormatError,
            analyze_qq_chat_export,
        )

        message = self._message("m1", "普通消息")
        message["padding"] = "x" * (MAX_RAW_JSON_VALUE_CHARS + 1)
        source = self._write_export([message])
        normalized = self.root / "normalized.jsonl"

        with self.assertRaisesRegex(ChatHistoryFormatError, "单个 JSON 值超过大小限制"):
            analyze_qq_chat_export(source, normalized)

        self.assertFalse(normalized.exists())


class HistoryWindowSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "normalized.jsonl"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_windows_preserve_conversation_boundaries_and_selection_is_deterministic(self) -> None:
        from src.bw_learner.history_import import (
            ImportedMessage,
            build_history_windows,
            select_history_windows,
            write_normalized_messages,
        )

        messages = []
        timestamp = 1_750_000_000.0
        for index in range(18):
            if index == 9:
                timestamp += 3_600
            messages.append(
                ImportedMessage(
                    message_id=f"m{index}",
                    timestamp=timestamp + index,
                    sender_id=f"u{index % 3}",
                    sender_name=f"用户{index % 3}",
                    sender_card="",
                    content=f"第{index}条有信息的聊天内容",
                    reply_to_id=f"m{index - 1}" if index % 4 == 0 else None,
                    is_bot=False,
                    is_low_signal=False,
                )
            )
        write_normalized_messages(self.path, messages)

        windows = build_history_windows(
            self.path,
            max_messages=5,
            max_chars=10_000,
            max_gap_seconds=600,
            overlap_messages=1,
        )
        selected_once = select_history_windows(windows, budget=3, priority_sender_ids=["u0", "u1", "u2"])
        selected_twice = select_history_windows(windows, budget=3, priority_sender_ids=["u0", "u1", "u2"])

        self.assertGreaterEqual(len(windows), 4)
        self.assertTrue(all(window.message_count <= 5 for window in windows))
        self.assertTrue(any(window.start_timestamp >= 1_750_003_600 for window in windows))
        self.assertEqual(
            [window.window_id for window in selected_once], [window.window_id for window in selected_twice]
        )
        self.assertEqual(len(selected_once), 3)
        self.assertEqual(set().union(*(window.sender_ids for window in selected_once)), {"u0", "u1", "u2"})

    def test_oversized_overlap_is_dropped_without_emitting_duplicate_windows(self) -> None:
        from src.bw_learner.history_import import (
            ImportedMessage,
            build_history_windows,
            write_normalized_messages,
        )

        messages = [
            ImportedMessage(
                message_id=f"m{index}",
                timestamp=1_750_000_000.0 + index,
                sender_id="u1",
                sender_name="用户",
                sender_card="",
                content="内容测试",
                reply_to_id=None,
                is_bot=False,
                is_low_signal=False,
            )
            for index in range(3)
        ]
        write_normalized_messages(self.path, messages)

        windows = build_history_windows(
            self.path,
            max_messages=3,
            max_chars=5,
            overlap_messages=1,
        )

        self.assertEqual(
            [tuple(message.message_id for message in window.messages) for window in windows],
            [("m0",), ("m1",), ("m2",)],
        )


if __name__ == "__main__":
    unittest.main()
