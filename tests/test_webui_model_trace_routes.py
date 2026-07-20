import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from peewee import SqliteDatabase
from pydantic import ValidationError

from src.common.database.database_model import BaseModel, LLMRequestTrace, LLMRequestTraceMedia
from src.webui import model_trace_routes


TRACE_MODELS = [LLMRequestTrace, LLMRequestTraceMedia]


class WebUIModelTraceRoutesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        temp_root = Path(self.temp_dir.name)
        self.test_db = SqliteDatabase(temp_root / "model-traces.db", check_same_thread=False)
        self.original_dbs = {model: model._meta.database for model in [BaseModel, *TRACE_MODELS]}
        self.test_db.bind(TRACE_MODELS, bind_refs=False, bind_backrefs=False)
        self.test_db.connect()
        self.test_db.create_tables(TRACE_MODELS)
        self.media_root = temp_root / "media"
        self.media_root_patch = patch.object(model_trace_routes, "TRACE_MEDIA_ROOT", self.media_root)
        self.media_root_patch.start()

    def tearDown(self) -> None:
        self.test_db.drop_tables(TRACE_MODELS)
        self.test_db.close()
        for model, database in self.original_dbs.items():
            model._meta.set_database(database)
        self.media_root_patch.stop()
        self.temp_dir.cleanup()

    def create_trace(
        self,
        *,
        request_type: str,
        model_name: str,
        status: str,
        started_at: datetime.datetime,
        request_text: str,
    ) -> LLMRequestTrace:
        return LLMRequestTrace.create(
            request_type=request_type,
            operation="response",
            model_name=model_name,
            model_identifier=f"provider-{model_name}",
            provider_name="provider-a",
            attempt=1,
            status=status,
            started_at=started_at,
            completed_at=started_at + datetime.timedelta(seconds=1),
            duration_ms=1000,
            request_preview=request_text,
            response_preview="answer" if status == "success" else "",
            request_payload=json.dumps({"messages": [{"content": request_text}]}, ensure_ascii=False),
            response_payload=json.dumps({"content": "answer"}, ensure_ascii=False) if status == "success" else None,
            error_type="RuntimeError" if status == "error" else None,
            error_message="模型请求失败，请查看服务端日志" if status == "error" else None,
            prompt_tokens=10,
            completion_tokens=4,
            total_tokens=14,
        )

    async def test_list_route_paginates_filters_and_returns_filter_options(self) -> None:
        now = datetime.datetime(2026, 7, 20, 12, 0, 0)
        self.create_trace(
            request_type="reply.main",
            model_name="model-a",
            status="success",
            started_at=now - datetime.timedelta(minutes=2),
            request_text="first request",
        )
        expected = self.create_trace(
            request_type="planner.main",
            model_name="model-b",
            status="error",
            started_at=now - datetime.timedelta(minutes=1),
            request_text="matching request",
        )
        self.create_trace(
            request_type="reply.main",
            model_name="model-a",
            status="success",
            started_at=now,
            request_text="latest request",
        )

        result = await model_trace_routes.list_model_traces(
            page=1,
            page_size=20,
            status="error",
            request_type=None,
            model=None,
            search="matching",
            _auth=True,
        )

        self.assertEqual(result.pagination.total_items, 1)
        self.assertEqual([item.id for item in result.data], [expected.id])
        self.assertEqual(result.filter_options.request_types, ["planner.main", "reply.main"])
        self.assertEqual(result.filter_options.models, ["model-a", "model-b"])

    async def test_detail_route_decodes_payloads_and_returns_404_for_unknown_trace(self) -> None:
        trace = self.create_trace(
            request_type="reply.main",
            model_name="model-a",
            status="success",
            started_at=datetime.datetime(2026, 7, 20, 12, 0, 0),
            request_text="concrete prompt",
        )
        LLMRequestTraceMedia.create(
            trace_id=trace.id,
            media_id="image-1",
            kind="image",
            format="png",
            mime_type="text/html",
            size_bytes=8,
            file_name="image-1.png",
        )

        detail = await model_trace_routes.get_model_trace(trace.id, _auth=True)

        self.assertEqual(detail.request_payload["messages"][0]["content"], "concrete prompt")
        self.assertEqual(detail.response_payload["content"], "answer")
        self.assertEqual(detail.media[0].media_id, "image-1")
        self.assertEqual(detail.media[0].mime_type, "image/png")
        self.assertEqual(detail.media[0].size_bytes, 8)

        with self.assertRaises(HTTPException) as raised:
            await model_trace_routes.get_model_trace(9999, _auth=True)
        self.assertEqual(raised.exception.status_code, 404)

    def test_media_route_serves_image_and_audio_with_safe_headers(self) -> None:
        trace = self.create_trace(
            request_type="reply.main",
            model_name="model-a",
            status="success",
            started_at=datetime.datetime(2026, 7, 20, 12, 0, 0),
            request_text="media request",
        )
        trace_dir = self.media_root / str(trace.id)
        trace_dir.mkdir(parents=True)
        fixtures = (
            ("image-1", "image", "png", "text/html", "image/png", "image-1.png", b"\x89PNG\r\n\x1a\n"),
            (
                "audio-1",
                "audio",
                "wav",
                "application/octet-stream",
                "audio/wav",
                "audio-1.wav",
                b"RIFF\x00\x00\x00\x00WAVE",
            ),
        )
        for media_id, kind, media_format, stored_mime_type, _expected_mime_type, file_name, content in fixtures:
            (trace_dir / file_name).write_bytes(content)
            LLMRequestTraceMedia.create(
                trace_id=trace.id,
                media_id=media_id,
                kind=kind,
                format=media_format,
                mime_type=stored_mime_type,
                size_bytes=len(content),
                file_name=file_name,
            )

        app = FastAPI()
        app.include_router(model_trace_routes.router)
        with (
            patch.object(model_trace_routes, "verify_auth_token_from_cookie_or_header", return_value=True),
            TestClient(app) as client,
        ):
            for media_id, _kind, _format, _stored_mime_type, expected_mime_type, _file_name, content in fixtures:
                with self.subTest(media_id=media_id):
                    response = client.get(f"/model-traces/{trace.id}/media/{media_id}")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.content, content)
                    self.assertEqual(response.headers["content-type"], expected_mime_type)
                    self.assertEqual(response.headers["cache-control"], "private, no-store")
                    self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_json_routes_disable_private_caching(self) -> None:
        trace = self.create_trace(
            request_type="reply.main",
            model_name="model-a",
            status="success",
            started_at=datetime.datetime(2026, 7, 20, 12, 0, 0),
            request_text="sensitive request",
        )
        app = FastAPI()
        app.include_router(model_trace_routes.router)

        with (
            patch.object(model_trace_routes, "verify_auth_token_from_cookie_or_header", return_value=True),
            TestClient(app) as client,
        ):
            list_response = client.get("/model-traces")
            detail_response = client.get(f"/model-traces/{trace.id}")

        self.assertEqual(list_response.headers["cache-control"], "private, no-store")
        self.assertEqual(detail_response.headers["cache-control"], "private, no-store")

    def test_media_response_contract_rejects_cross_kind_formats(self) -> None:
        with self.assertRaises(ValidationError):
            model_trace_routes.ModelTraceImageMediaSummary(
                media_id="image-1",
                kind="image",
                format="wav",
                mime_type="audio/wav",
                size_bytes=44,
            )
        with self.assertRaises(ValidationError):
            model_trace_routes.ModelTraceAudioMediaSummary(
                media_id="audio-1",
                kind="audio",
                format="png",
                mime_type="image/png",
                size_bytes=68,
            )

    async def test_media_route_rejects_invalid_or_missing_media_ids(self) -> None:
        trace = self.create_trace(
            request_type="reply.main",
            model_name="model-a",
            status="success",
            started_at=datetime.datetime(2026, 7, 20, 12, 0, 0),
            request_text="media request",
        )

        for media_id in ("../secret", "image-0", "missing-1"):
            with self.subTest(media_id=media_id), self.assertRaises(HTTPException) as raised:
                await model_trace_routes.get_model_trace_media(trace.id, media_id, _auth=True)
            self.assertEqual(raised.exception.status_code, 404)

    def test_routes_require_authentication(self) -> None:
        app = FastAPI()
        app.include_router(model_trace_routes.router)

        with patch.object(
            model_trace_routes, "verify_auth_token_from_cookie_or_header", side_effect=HTTPException(401)
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/model-traces")
                media_response = client.get("/model-traces/1/media/image-1")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(media_response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
