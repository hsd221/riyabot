import base64
import json
import math
import os
import stat
import tempfile
import unittest
from pathlib import Path

from peewee import SqliteDatabase

from src.common.database.database_model import BaseModel, LLMRequestTrace, LLMRequestTraceMedia
from src.config.api_ada_configs import ModelInfo
from src.llm_models.model_client.base_client import APIResponse, UsageRecord
from src.llm_models.exceptions import RespNotOkException
from src.llm_models.payload_content.message import MessageBuilder
from src.llm_models.payload_content.tool_option import ToolCall, ToolOptionBuilder, ToolParamType
from src.llm_models.request_trace import (
    ModelRequestTraceRecorder,
    TraceMediaInput,
    build_request_payload,
    collect_request_media,
    is_valid_trace_media_id,
    resolve_trace_media_path,
    serialize_trace_payload,
)


TRACE_MODELS = [LLMRequestTrace, LLMRequestTraceMedia]

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
WAV_BYTES = (
    b"RIFF"
    + (36).to_bytes(4, "little")
    + b"WAVEfmt "
    + (16).to_bytes(4, "little")
    + (1).to_bytes(2, "little")
    + (1).to_bytes(2, "little")
    + (8_000).to_bytes(4, "little")
    + (16_000).to_bytes(4, "little")
    + (2).to_bytes(2, "little")
    + (16).to_bytes(2, "little")
    + b"data"
    + (0).to_bytes(4, "little")
)


class ModelRequestTracePayloadTest(unittest.TestCase):
    def test_media_ids_are_strictly_bounded(self) -> None:
        self.assertTrue(is_valid_trace_media_id("image-1"))
        self.assertTrue(is_valid_trace_media_id("audio-99"))
        self.assertFalse(is_valid_trace_media_id("image-0"))
        self.assertFalse(is_valid_trace_media_id(f"image-{'1' * 65}"))

    def test_request_payload_keeps_text_and_redacts_structured_secrets(self) -> None:
        message = MessageBuilder().add_text_content("请分析这张图片").add_image_content("png", "aGVsbG8=").build()
        tool = (
            ToolOptionBuilder()
            .set_name("search")
            .set_description("Search documents")
            .add_param("query", ToolParamType.STRING, "Search query", required=True)
            .build()
        )
        model = ModelInfo(
            model_identifier="provider-model",
            name="model-a",
            api_provider="provider-a",
            force_stream_mode=True,
        )

        payload = build_request_payload(
            operation="response",
            model_info=model,
            messages=[message],
            tool_options=[tool],
            temperature=0.3,
            max_tokens=128,
            response_format=None,
            embedding_input=None,
            audio_base64=None,
            extra_params={
                "api_key": "secret-value",
                "accessToken": "camel-secret",
                "token": "plain-secret",
                "database_password": "password-secret",
                "max_tokens": 128,
            },
        )
        decoded = json.loads(serialize_trace_payload(payload))

        self.assertEqual(decoded["messages"][0]["content"][0]["text"], "请分析这张图片")
        self.assertEqual(decoded["messages"][0]["content"][1]["type"], "image")
        self.assertEqual(decoded["messages"][0]["content"][1]["format"], "png")
        self.assertEqual(decoded["messages"][0]["content"][1]["media_id"], "image-1")
        self.assertNotIn("aGVsbG8=", json.dumps(decoded, ensure_ascii=False))
        self.assertEqual(decoded["parameters"]["extra"]["api_key"], "[REDACTED]")
        self.assertEqual(decoded["parameters"]["extra"]["accessToken"], "[REDACTED]")
        self.assertEqual(decoded["parameters"]["extra"]["token"], "[REDACTED]")
        self.assertEqual(decoded["parameters"]["extra"]["database_password"], "[REDACTED]")
        self.assertEqual(decoded["parameters"]["extra"]["max_tokens"], 128)
        self.assertTrue(decoded["parameters"]["stream"])
        self.assertEqual(decoded["tools"][0]["parameters"][0]["type"], "string")

    def test_audio_payload_references_snapshot_without_embedding_base64(self) -> None:
        audio_base64 = base64.b64encode(WAV_BYTES).decode("ascii")
        model = ModelInfo(
            model_identifier="provider-model",
            name="model-a",
            api_provider="provider-a",
        )

        payload = build_request_payload(
            operation="audio",
            model_info=model,
            messages=[],
            tool_options=None,
            temperature=None,
            max_tokens=None,
            response_format=None,
            embedding_input=None,
            audio_base64=audio_base64,
            extra_params=None,
        )
        media = collect_request_media(messages=[], audio_base64=audio_base64)
        serialized = serialize_trace_payload(payload)

        self.assertEqual(payload["audio"]["media_id"], "audio-1")
        self.assertEqual(payload["audio"]["format"], "wav")
        self.assertEqual(media[0].media_id, "audio-1")
        self.assertEqual(media[0].base64_data, audio_base64)
        self.assertNotIn(audio_base64, serialized)

    def test_non_finite_numbers_are_serialized_as_valid_json_strings(self) -> None:
        decoded = json.loads(
            serialize_trace_payload(
                {"embedding": [math.nan, math.inf, -math.inf]},
            )
        )

        self.assertEqual(decoded["embedding"], ["nan", "inf", "-inf"])


class ModelRequestTraceRecorderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.test_db = SqliteDatabase(":memory:")
        self.original_dbs = {model: model._meta.database for model in [BaseModel, *TRACE_MODELS]}
        self.test_db.bind(TRACE_MODELS, bind_refs=False, bind_backrefs=False)
        self.test_db.connect()
        self.test_db.create_tables(TRACE_MODELS)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.media_root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.test_db.drop_tables(TRACE_MODELS)
        self.test_db.close()
        for model, database in self.original_dbs.items():
            model._meta.set_database(database)
        self.temp_dir.cleanup()

    def _start_trace(
        self,
        recorder: ModelRequestTraceRecorder,
        *,
        request_payload: dict,
        request_media=None,
        request_type: str = "reply.main",
        operation: str = "response",
    ) -> int:
        trace_id = recorder.start_trace(
            request_type=request_type,
            operation=operation,
            model_name="model-a",
            model_identifier="provider-model-a",
            provider_name="provider-a",
            attempt=1,
            request_payload=request_payload,
            request_media=request_media,
        )
        self.assertIsNotNone(trace_id)
        return trace_id

    def test_request_media_is_persisted_as_exact_files_and_metadata(self) -> None:
        recorder = ModelRequestTraceRecorder(max_records=10, media_root=self.media_root)
        image_base64 = base64.b64encode(PNG_BYTES).decode("ascii")
        audio_base64 = base64.b64encode(WAV_BYTES).decode("ascii")

        image_message = MessageBuilder().add_text_content("看图").add_image_content("png", image_base64).build()
        image_media = collect_request_media(messages=[image_message], audio_base64=None)
        image_trace_id = self._start_trace(
            recorder,
            request_payload={"messages": [{"content": [{"type": "image", "media_id": "image-1"}]}]},
            request_media=image_media,
        )
        audio_media = collect_request_media(messages=[], audio_base64=audio_base64)
        audio_trace_id = self._start_trace(
            recorder,
            request_payload={"audio": {"media_id": "audio-1"}},
            request_media=audio_media,
            request_type="audio",
            operation="audio",
        )

        image_row = LLMRequestTraceMedia.get(
            (LLMRequestTraceMedia.trace_id == image_trace_id) & (LLMRequestTraceMedia.media_id == "image-1")
        )
        audio_row = LLMRequestTraceMedia.get(
            (LLMRequestTraceMedia.trace_id == audio_trace_id) & (LLMRequestTraceMedia.media_id == "audio-1")
        )

        self.assertEqual(image_row.kind, "image")
        self.assertEqual(image_row.mime_type, "image/png")
        self.assertEqual(image_row.size_bytes, len(PNG_BYTES))
        self.assertEqual(audio_row.kind, "audio")
        self.assertEqual(audio_row.mime_type, "audio/wav")
        image_path = resolve_trace_media_path(image_row, media_root=self.media_root)
        audio_path = resolve_trace_media_path(audio_row, media_root=self.media_root)
        self.assertEqual(image_path.read_bytes(), PNG_BYTES)
        self.assertEqual(audio_path.read_bytes(), WAV_BYTES)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(image_path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(image_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(audio_path.stat().st_mode), 0o600)

    def test_supported_media_formats_are_detected_from_file_signatures(self) -> None:
        recorder = ModelRequestTraceRecorder(max_records=10, media_root=self.media_root)
        fixtures = (
            ("image-1", "image", b"\x89PNG\r\n\x1a\nrest", "png", "image/png", "png"),
            ("image-2", "image", b"\xff\xd8\xff\xe0rest", "jpeg", "image/jpeg", "jpg"),
            ("image-3", "image", b"GIF89arest", "gif", "image/gif", "gif"),
            ("image-4", "image", b"RIFF\x00\x00\x00\x00WEBPrest", "webp", "image/webp", "webp"),
            ("audio-1", "audio", WAV_BYTES, "wav", "audio/wav", "wav"),
            ("audio-2", "audio", b"ID3rest", "mp3", "audio/mpeg", "mp3"),
            ("audio-3", "audio", b"OggSrest", "ogg", "audio/ogg", "ogg"),
            ("audio-4", "audio", b"fLaCrest", "flac", "audio/flac", "flac"),
            ("audio-5", "audio", b"\x00\x00\x00\x18ftypM4A ", "mp4", "audio/mp4", "m4a"),
            ("audio-6", "audio", b"\x1aE\xdf\xa3rest", "webm", "audio/webm", "webm"),
            ("audio-7", "audio", b"#!AMR\nrest", "amr", "audio/amr", "amr"),
        )
        request_media = [
            TraceMediaInput(
                media_id=media_id,
                kind=kind,
                format="untrusted-declaration",
                base64_data=base64.b64encode(content).decode("ascii"),
            )
            for media_id, kind, content, _format, _mime_type, _extension in fixtures
        ]

        trace_id = self._start_trace(recorder, request_payload={"messages": []}, request_media=request_media)
        stored_media = {
            row.media_id: row for row in LLMRequestTraceMedia.select().where(LLMRequestTraceMedia.trace_id == trace_id)
        }

        self.assertEqual(set(stored_media), {media_id for media_id, *_rest in fixtures})
        for media_id, _kind, content, expected_format, expected_mime_type, expected_extension in fixtures:
            with self.subTest(media_id=media_id):
                row = stored_media[media_id]
                self.assertEqual(row.format, expected_format)
                self.assertEqual(row.mime_type, expected_mime_type)
                self.assertEqual(row.file_name, f"{media_id}.{expected_extension}")
                self.assertEqual(resolve_trace_media_path(row, media_root=self.media_root).read_bytes(), content)

    def test_media_size_limits_skip_large_files_and_bound_each_trace(self) -> None:
        image_base64 = base64.b64encode(PNG_BYTES).decode("ascii")
        message = MessageBuilder().add_image_content("png", image_base64).add_image_content("png", image_base64).build()
        media = collect_request_media(messages=[message], audio_base64=None)

        file_limited = ModelRequestTraceRecorder(
            max_records=10,
            media_root=self.media_root / "file-limited",
            max_media_file_bytes=len(PNG_BYTES) - 1,
            max_media_trace_bytes=len(PNG_BYTES) * 2,
        )
        first_trace_id = self._start_trace(file_limited, request_payload={"messages": []}, request_media=media)
        self.assertEqual(
            LLMRequestTraceMedia.select().where(LLMRequestTraceMedia.trace_id == first_trace_id).count(),
            0,
        )

        trace_limited = ModelRequestTraceRecorder(
            max_records=10,
            media_root=self.media_root / "trace-limited",
            max_media_file_bytes=len(PNG_BYTES),
            max_media_trace_bytes=len(PNG_BYTES) + 1,
        )
        second_trace_id = self._start_trace(trace_limited, request_payload={"messages": []}, request_media=media)
        stored_ids = [
            row.media_id
            for row in LLMRequestTraceMedia.select()
            .where(LLMRequestTraceMedia.trace_id == second_trace_id)
            .order_by(LLMRequestTraceMedia.media_id)
        ]
        self.assertEqual(stored_ids, ["image-1"])

    def test_pruning_trace_removes_its_media_files_and_rows(self) -> None:
        recorder = ModelRequestTraceRecorder(max_records=1, media_root=self.media_root)
        image_base64 = base64.b64encode(PNG_BYTES).decode("ascii")
        message = MessageBuilder().add_image_content("png", image_base64).build()
        media = collect_request_media(messages=[message], audio_base64=None)

        first_id = self._start_trace(recorder, request_payload={"messages": []}, request_media=media)
        first_row = LLMRequestTraceMedia.get(LLMRequestTraceMedia.trace_id == first_id)
        first_path = resolve_trace_media_path(first_row, media_root=self.media_root)
        self.assertTrue(first_path.is_file())

        self._start_trace(recorder, request_payload={"messages": []})

        self.assertIsNone(LLMRequestTrace.get_or_none(LLMRequestTrace.id == first_id))
        self.assertEqual(LLMRequestTraceMedia.select().where(LLMRequestTraceMedia.trace_id == first_id).count(), 0)
        self.assertFalse(first_path.exists())

    def test_media_write_failure_does_not_drop_the_trace(self) -> None:
        blocked_root = self.media_root / "blocked"
        blocked_root.write_bytes(b"not a directory")
        recorder = ModelRequestTraceRecorder(max_records=10, media_root=blocked_root)
        image_base64 = base64.b64encode(PNG_BYTES).decode("ascii")
        media = collect_request_media(
            messages=[MessageBuilder().add_image_content("png", image_base64).build()],
            audio_base64=None,
        )

        trace_id = self._start_trace(recorder, request_payload={"messages": []}, request_media=media)

        self.assertIsNotNone(LLMRequestTrace.get_or_none(LLMRequestTrace.id == trace_id))
        self.assertEqual(LLMRequestTraceMedia.select().where(LLMRequestTraceMedia.trace_id == trace_id).count(), 0)

    def test_untrusted_bytes_with_a_false_image_format_are_not_persisted(self) -> None:
        recorder = ModelRequestTraceRecorder(max_records=10, media_root=self.media_root)
        disguised_html = base64.b64encode(b"<script>alert('trace')</script>").decode("ascii")
        media = collect_request_media(
            messages=[MessageBuilder().add_image_content("png", disguised_html).build()],
            audio_base64=None,
        )

        trace_id = self._start_trace(recorder, request_payload={"messages": []}, request_media=media)

        self.assertEqual(LLMRequestTraceMedia.select().where(LLMRequestTraceMedia.trace_id == trace_id).count(), 0)
        self.assertFalse((self.media_root / str(trace_id) / "image-1.png").exists())

    def test_successful_trace_persists_response_usage_and_prunes_old_records(self) -> None:
        recorder = ModelRequestTraceRecorder(max_records=2)
        first_id = recorder.start_trace(
            request_type="reply.main",
            operation="response",
            model_name="model-a",
            model_identifier="provider-model-a",
            provider_name="provider-a",
            attempt=1,
            request_payload={"messages": [{"content": "first"}]},
        )
        recorder.finish_success(
            first_id,
            APIResponse(
                content="answer",
                reasoning_content="reasoning",
                tool_calls=[ToolCall("call-1", "search", {"query": "docs"})],
                usage=UsageRecord("model-a", "provider-a", 10, 4, 14),
                raw_data={"id": "response-1", "authorization": "Bearer secret"},
            ),
            duration_seconds=1.234,
        )

        second_id = recorder.start_trace(
            request_type="embedding",
            operation="embedding",
            model_name="model-b",
            model_identifier="provider-model-b",
            provider_name="provider-b",
            attempt=1,
            request_payload={"input": "second"},
        )
        third_id = recorder.start_trace(
            request_type="voice",
            operation="audio",
            model_name="model-c",
            model_identifier="provider-model-c",
            provider_name="provider-c",
            attempt=1,
            request_payload={"audio": {"base64_chars": 16}},
        )

        self.assertIsNotNone(first_id)
        self.assertIsNotNone(second_id)
        self.assertIsNotNone(third_id)
        self.assertEqual(LLMRequestTrace.select().count(), 2)
        self.assertIsNone(LLMRequestTrace.get_or_none(LLMRequestTrace.id == first_id))

        recorder.finish_success(
            second_id,
            APIResponse(
                content="embedded",
                embedding=[0.1, 0.2],
                usage=UsageRecord("model-b", "provider-b", 6, 0, 6),
            ),
            duration_seconds=0.25,
        )
        trace = LLMRequestTrace.get_by_id(second_id)
        response_payload = json.loads(trace.response_payload)

        self.assertEqual(trace.status, "success")
        self.assertEqual(trace.duration_ms, 250)
        self.assertEqual(trace.prompt_tokens, 6)
        self.assertEqual(trace.total_tokens, 6)
        self.assertEqual(response_payload["embedding"], [0.1, 0.2])

    def test_payload_truncation_stays_within_configured_character_limit(self) -> None:
        max_chars = 1_000

        serialized = serialize_trace_payload({"content": "x" * 5_000}, max_chars=max_chars)
        decoded = json.loads(serialized)

        self.assertLessEqual(len(serialized), max_chars)
        self.assertTrue(decoded["truncated"])
        self.assertEqual(decoded["original_characters"], 5_014)

    def test_request_preview_uses_prompt_text_instead_of_operation_metadata(self) -> None:
        recorder = ModelRequestTraceRecorder(max_records=10)
        model = ModelInfo(
            model_identifier="provider-model",
            name="model-a",
            api_provider="provider-a",
        )
        payload = build_request_payload(
            operation="response",
            model_info=model,
            messages=[MessageBuilder().add_text_content("真正的提示词").build()],
            tool_options=None,
            temperature=0.2,
            max_tokens=64,
            response_format=None,
            embedding_input=None,
            audio_base64=None,
            extra_params=None,
        )

        trace_id = recorder.start_trace(
            request_type="reply.main",
            operation="response",
            model_name="model-a",
            model_identifier="provider-model",
            provider_name="provider-a",
            attempt=1,
            request_payload=payload,
        )

        self.assertEqual(LLMRequestTrace.get_by_id(trace_id).request_preview, "真正的提示词")

    def test_unknown_error_message_is_not_exposed(self) -> None:
        recorder = ModelRequestTraceRecorder(max_records=10)
        trace_id = recorder.start_trace(
            request_type="reply.main",
            operation="response",
            model_name="model-a",
            model_identifier="provider-model-a",
            provider_name="provider-a",
            attempt=1,
            request_payload={"messages": []},
        )

        recorder.finish_error(
            trace_id,
            RuntimeError("private path /srv/app and token secret-value"),
            duration_seconds=0.5,
        )
        trace = LLMRequestTrace.get_by_id(trace_id)

        self.assertEqual(trace.status, "error")
        self.assertEqual(trace.error_type, "RuntimeError")
        self.assertEqual(trace.error_message, "模型请求失败，请查看服务端日志")
        self.assertNotIn("secret-value", trace.error_message)

    def test_provider_error_body_is_not_exposed(self) -> None:
        recorder = ModelRequestTraceRecorder(max_records=10)
        trace_id = recorder.start_trace(
            request_type="reply.main",
            operation="response",
            model_name="model-a",
            model_identifier="provider-model-a",
            provider_name="provider-a",
            attempt=1,
            request_payload={"messages": []},
        )

        recorder.finish_error(
            trace_id,
            RespNotOkException(418, "upstream response contains secret-value"),
            duration_seconds=0.5,
        )
        trace = LLMRequestTrace.get_by_id(trace_id)

        self.assertEqual(trace.error_message, "模型服务返回 HTTP 418")
        self.assertNotIn("secret-value", trace.response_payload)


if __name__ == "__main__":
    unittest.main()
