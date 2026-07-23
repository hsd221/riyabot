import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from peewee import SqliteDatabase


class FakeUploadFile:
    def __init__(self, content: bytes, filename: str = "history.json", content_type: str = "application/json"):
        self._source = io.BytesIO(content)
        self.filename = filename
        self.content_type = content_type
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        return self._source.read(size)

    async def close(self) -> None:
        self.closed = True


def make_export(*, chat_type: str = "group") -> bytes:
    payload = {
        "metadata": {"name": "QQChatExporter", "version": "0.1.0"},
        "chatInfo": {
            "name": "测试群" if chat_type == "group" else "某人",
            "type": chat_type,
            "selfUin": "10000",
            "peerUid": "123456",
        },
        "statistics": {"totalMessages": 3},
        "messages": [
            {
                "id": "m1",
                "timestamp": 1_750_000_000_000,
                "sender": {"uin": "20001", "name": "甲", "groupCard": "甲"},
                "type": "text",
                "content": {"elements": [{"type": "text", "data": {"text": "这下真破防了"}}]},
                "recalled": False,
                "system": False,
            },
            {
                "id": "m2",
                "timestamp": 1_750_000_001_000,
                "sender": {"uin": "20002", "name": "乙", "groupCard": "乙"},
                "type": "text",
                "content": {"elements": [{"type": "text", "data": {"text": "破防就是绷不住了"}}]},
                "recalled": False,
                "system": False,
            },
            {
                "id": "m3",
                "timestamp": 1_750_000_002_000,
                "sender": {"uin": "20002", "name": "乙", "groupCard": "乙"},
                "type": "text",
                "content": {"elements": [{"type": "text", "data": {"text": "？？？"}}]},
                "recalled": False,
                "system": False,
            },
        ],
        "exportOptions": {},
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class ChatHistoryImportRoutesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from src.common.database.database_model import ChatHistoryImportTask
        from src.webui import chat_history_import_routes

        self.model = ChatHistoryImportTask
        self.routes = chat_history_import_routes
        self.db = SqliteDatabase(":memory:")
        self.original_database = self.model._meta.database
        self.db.bind([self.model], bind_refs=False, bind_backrefs=False)
        self.db.connect()
        self.db.create_tables([self.model])
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name) / "imports"
        self.root.mkdir()
        self.root_patch = patch.object(self.routes, "IMPORT_ROOT", self.root)
        self.auth_patch = patch.object(self.routes, "verify_auth_token", return_value=True)
        self.root_patch.start()
        self.auth_patch.start()
        self.routes._running_tasks.clear()
        self.routes._analyzing_import_ids.clear()

    def tearDown(self) -> None:
        for task in self.routes._running_tasks.values():
            task.cancel()
        self.routes._running_tasks.clear()
        self.routes._analyzing_import_ids.clear()
        self.auth_patch.stop()
        self.root_patch.stop()
        self.tmpdir.cleanup()
        self.db.drop_tables([self.model])
        self.db.close()
        self.model._meta.set_database(self.original_database)

    async def _upload(self):
        upload = FakeUploadFile(make_export())
        response = await self.routes.create_chat_history_import(upload, None, None)
        self.assertTrue(upload.closed)
        return response

    async def test_upload_streams_analyzes_and_removes_the_raw_export(self) -> None:
        response = await self._upload()

        self.assertEqual(response.status, "ready")
        self.assertEqual(response.analysis.chat.name, "测试群")
        self.assertEqual(response.analysis.total_messages, 3)
        self.assertEqual(response.analysis.retained_messages, 2)
        self.assertEqual(response.analysis.noise_counts, {"punctuation_only": 1})
        self.assertEqual(response.estimated_model_calls, {"fast": 2, "balanced": 2, "deep": 2, "full": 2})
        task_dir = self.root / response.import_id
        self.assertFalse((task_dir / "source.json").exists())
        self.assertTrue((task_dir / "normalized.jsonl").exists())

        with self.assertRaises(HTTPException) as duplicate:
            await self.routes.create_chat_history_import(FakeUploadFile(make_export()), None, None)
        self.assertEqual(duplicate.exception.status_code, 409)

    async def test_upload_rejects_oversized_and_private_exports_without_retaining_files(self) -> None:
        with patch.object(self.routes, "MAX_UPLOAD_BYTES", 32):
            with self.assertRaises(HTTPException) as oversized:
                await self.routes.create_chat_history_import(FakeUploadFile(make_export()), None, None)
        self.assertEqual(oversized.exception.status_code, 413)
        self.assertEqual(list(self.root.iterdir()), [])

        with self.assertRaises(HTTPException) as private:
            await self.routes.create_chat_history_import(FakeUploadFile(make_export(chat_type="private")), None, None)
        self.assertEqual(private.exception.status_code, 400)
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_upload_rejects_while_another_import_is_active(self) -> None:
        self.routes._analyzing_import_ids.add("f" * 32)
        upload = FakeUploadFile(make_export())

        with self.assertRaises(HTTPException) as active:
            await self.routes.create_chat_history_import(upload, None, None)

        self.assertEqual(active.exception.status_code, 409)
        self.assertTrue(upload.closed)
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_participants_are_previewed_and_loaded_with_server_pagination(self) -> None:
        response = await self._upload()
        task = self.model.get()
        analysis = json.loads(task.analysis_json)
        analysis["participants"] = [
            {
                "source_id": str(index),
                "name": f"用户 {index}",
                "card": f"成员 {index}",
                "message_count": 100 - index,
                "is_bot": False,
            }
            for index in range(65)
        ]
        analysis["participant_count"] = 65
        task.analysis_json = json.dumps(analysis, ensure_ascii=False)
        task.save()

        detail = await self.routes.get_chat_history_import(response.import_id, None, None)
        page = await self.routes.list_chat_history_participants(
            response.import_id,
            query="成员 3",
            page=1,
            page_size=10,
            maibot_session=None,
            authorization=None,
        )

        self.assertEqual(detail.analysis.participant_count, 65)
        self.assertEqual(len(detail.analysis.participants), 30)
        self.assertEqual(page.pagination.page_size, 10)
        self.assertGreater(page.pagination.total_items, 1)
        self.assertLessEqual(len(page.data), 10)
        self.assertTrue(all("3" in participant.card for participant in page.data))

    async def test_start_runs_in_background_persists_progress_and_cleans_normalized_text(self) -> None:
        from src.bw_learner.history_learning import HistoryCandidates

        response = await self._upload()
        captured_options = {}

        class FakeLearner:
            async def learn(self, _path, **kwargs):
                captured_options.update(kwargs)
                await kwargs["progress"]("extracting", 1, 2)
                await asyncio.sleep(0)
                await kwargs["progress"]("storing", 1, 1)
                return SimpleNamespace(
                    candidates=HistoryCandidates(),
                    to_json=lambda: {
                        "candidates": {
                            "expressions": [],
                            "behaviors": [],
                            "jargons": [],
                            "memories": [],
                            "profiles": [],
                        },
                        "model_call_count": 2,
                    },
                )

        enrichment = AsyncMock(
            return_value=SimpleNamespace(
                to_json=lambda: {
                    "memories_created": 1,
                    "profiles_created": 1,
                    "profiles_updated": 0,
                    "profiles_skipped": 0,
                    "write_failures": 0,
                }
            )
        )
        with (
            patch.object(self.routes, "ChatHistoryLearner", return_value=FakeLearner()),
            patch.object(self.routes, "store_history_enrichment", enrichment),
        ):
            started = await self.routes.start_chat_history_import(
                response.import_id,
                self.routes.ChatHistoryImportStartRequest(
                    depth="fast",
                    participant_ids=["20001", "20002"],
                    extract_memories=True,
                    update_profiles=True,
                ),
                None,
                None,
            )
            background = self.routes._running_tasks[response.import_id]
            await background

        self.assertEqual(started.status, "running")
        detail = await self.routes.get_chat_history_import(response.import_id, None, None)
        self.assertEqual(detail.status, "completed")
        self.assertEqual(detail.progress.stage, "completed")
        self.assertEqual(detail.result["model_call_count"], 2)
        self.assertTrue(detail.options["extract_memories"])
        self.assertTrue(detail.options["update_profiles"])
        self.assertTrue(captured_options["extract_memories"])
        self.assertTrue(captured_options["update_profiles"])
        self.assertEqual(detail.result["enrichment_store_result"]["memories_created"], 1)
        enrichment.assert_awaited_once()
        enrichment_options = enrichment.await_args.kwargs
        self.assertEqual(enrichment_options["import_id"], response.import_id)
        self.assertEqual(enrichment_options["group_id"], "123456")
        self.assertTrue(enrichment_options["extract_memories"])
        self.assertTrue(enrichment_options["update_profiles"])
        self.assertFalse((self.root / response.import_id / "normalized.jsonl").exists())
        self.assertTrue((self.root / response.import_id / "result.json").exists())

        deleted = await self.routes.delete_chat_history_import(response.import_id, None, None)
        self.assertTrue(deleted.success)
        self.assertFalse((self.root / response.import_id).exists())
        self.assertEqual(self.model.select().count(), 0)

    async def test_start_keeps_enrichment_disabled_by_default(self) -> None:
        response = await self._upload()
        captured_options = {}

        class FakeLearner:
            async def learn(self, _path, **kwargs):
                captured_options.update(kwargs)
                return SimpleNamespace(
                    to_json=lambda: {
                        "candidates": {
                            "expressions": [],
                            "behaviors": [],
                            "jargons": [],
                            "memories": [],
                            "profiles": [],
                        },
                        "model_call_count": 1,
                    }
                )

        enrichment = AsyncMock()
        with (
            patch.object(self.routes, "ChatHistoryLearner", return_value=FakeLearner()),
            patch.object(self.routes, "store_history_enrichment", enrichment),
        ):
            started = await self.routes.start_chat_history_import(
                response.import_id,
                self.routes.ChatHistoryImportStartRequest(depth="fast"),
                None,
                None,
            )
            await self.routes._running_tasks[response.import_id]

        self.assertFalse(started.options["extract_memories"])
        self.assertFalse(started.options["update_profiles"])
        self.assertFalse(captured_options["extract_memories"])
        self.assertFalse(captured_options["update_profiles"])
        enrichment.assert_not_awaited()
        detail = await self.routes.get_chat_history_import(response.import_id, None, None)
        self.assertIsNone(detail.result["enrichment_store_result"])

    async def test_all_member_scope_submits_only_small_exclusion_list(self) -> None:
        response = await self._upload()
        captured_options = {}

        class FakeLearner:
            async def learn(self, _path, **kwargs):
                captured_options.update(kwargs)
                return SimpleNamespace(
                    candidates=SimpleNamespace(profiles=()),
                    to_json=lambda: {
                        "candidates": {
                            "expressions": [],
                            "behaviors": [],
                            "jargons": [],
                            "memories": [],
                            "profiles": [],
                        },
                        "model_call_count": 1,
                    },
                )

        commit = AsyncMock()
        with (
            patch.object(self.routes, "ChatHistoryLearner", return_value=FakeLearner()),
            patch.object(self.routes, "_commit_learning_result", commit),
        ):
            started = await self.routes.start_chat_history_import(
                response.import_id,
                self.routes.ChatHistoryImportStartRequest(
                    depth="fast",
                    participant_scope=self.routes.ChatHistoryParticipantScopeRequest(
                        mode="all",
                        excluded_ids=["20002"],
                    ),
                ),
                None,
                None,
            )
            await self.routes._running_tasks[response.import_id]

        self.assertEqual(started.options["participant_scope"], {"mode": "all", "excluded_ids": ["20002"]})
        self.assertIsNone(captured_options["eligible_sender_ids"])
        self.assertEqual(captured_options["excluded_sender_ids"], ["20002"])
        commit.assert_awaited_once()

    async def test_existing_profile_pauses_all_writes_until_review(self) -> None:
        from src.bw_learner.history_learning import HistoryCandidates, ProfileCandidate

        response = await self._upload()
        candidates = HistoryCandidates(
            profiles=(ProfileCandidate("20001", "interest", "音乐", "爵士乐", ("m1",), 0.82),)
        )

        class FakeLearner:
            async def learn(self, _path, **kwargs):
                self.options = kwargs
                return SimpleNamespace(
                    candidates=candidates,
                    to_json=lambda: {
                        "candidates": candidates.to_json(),
                        "model_call_count": 2,
                        "store_result": None,
                    },
                )

        learner = FakeLearner()
        conflict = {
            "profile_id": "qq:20001",
            "subject_id": "20001",
            "current": {"profile_id": "qq:20001", "facts": {"城市": "上海"}},
            "imported": [{"category": "interest", "name": "音乐", "value": "爵士乐"}],
        }
        commit = AsyncMock()
        with (
            patch.object(self.routes, "ChatHistoryLearner", return_value=learner),
            patch.object(self.routes, "load_history_enrichment_evidence", return_value={}),
            patch.object(self.routes, "find_history_profile_conflicts", return_value=[conflict]),
            patch.object(self.routes, "_commit_learning_result", commit),
        ):
            await self.routes.start_chat_history_import(
                response.import_id,
                self.routes.ChatHistoryImportStartRequest(depth="fast", update_profiles=True),
                None,
                None,
            )
            await self.routes._running_tasks[response.import_id]

        task = await self.routes.get_chat_history_import(response.import_id, None, None)
        self.assertEqual(task.status, "awaiting_profile_review")
        self.assertEqual(task.progress.stage, "awaiting_profile_review")
        self.assertEqual(task.result["profile_review"]["conflicts"][0]["profile_id"], "qq:20001")
        self.assertFalse(learner.options["store"])
        self.assertTrue((self.root / response.import_id / "normalized.jsonl").exists())
        commit.assert_not_awaited()

    async def test_profile_review_requires_one_decision_per_conflict(self) -> None:
        response = await self._upload()
        task = self.model.get()
        task.status = "awaiting_profile_review"
        task.options_json = json.dumps({"update_profiles": True})
        task.result_json = json.dumps(
            {
                "candidates": {
                    "expressions": [],
                    "behaviors": [],
                    "jargons": [],
                    "memories": [],
                    "profiles": [],
                },
                "profile_review": {
                    "conflicts": [
                        {"profile_id": "qq:20001"},
                        {"profile_id": "qq:20002"},
                    ],
                    "decisions": None,
                },
            }
        )
        task.save()

        with self.assertRaises(HTTPException) as incomplete:
            await self.routes.submit_chat_history_profile_decisions(
                response.import_id,
                self.routes.ChatHistoryProfileDecisionRequest(decisions={"qq:20001": "keep_existing"}),
                None,
                None,
            )
        self.assertEqual(incomplete.exception.status_code, 422)

        commit = AsyncMock()
        with patch.object(self.routes, "_commit_learning_result", commit):
            started = await self.routes.submit_chat_history_profile_decisions(
                response.import_id,
                self.routes.ChatHistoryProfileDecisionRequest(
                    decisions={
                        "qq:20001": "keep_existing",
                        "qq:20002": "apply_imported",
                    }
                ),
                None,
                None,
            )
            await self.routes._running_tasks[response.import_id]

        self.assertEqual(started.status, "running")
        commit.assert_awaited_once()
        self.assertEqual(
            commit.await_args.kwargs["profile_decisions"],
            {"qq:20001": "keep_existing", "qq:20002": "apply_imported"},
        )

    async def test_start_rejects_unknown_participants_and_invalid_state(self) -> None:
        response = await self._upload()
        with self.assertRaises(HTTPException) as unknown:
            await self.routes.start_chat_history_import(
                response.import_id,
                self.routes.ChatHistoryImportStartRequest(depth="balanced", participant_ids=["not-in-export"]),
                None,
                None,
            )
        self.assertEqual(unknown.exception.status_code, 422)
        self.assertEqual(self.model.get().status, "ready")

    async def test_get_marks_a_running_task_interrupted_after_process_restart(self) -> None:
        response = await self._upload()
        task = self.model.get()
        task.status = "running"
        task.progress_stage = "extracting"
        task.save()

        recovered = await self.routes.get_chat_history_import(response.import_id, None, None)

        self.assertEqual(recovered.status, "failed")
        self.assertEqual(recovered.progress.stage, "failed")
        self.assertIn("服务重启", recovered.error_message)
        self.assertFalse((self.root / response.import_id / "normalized.jsonl").exists())
        self.assertEqual(self.model.get().normalized_path, "")

    async def test_failed_learning_removes_normalized_chat_text(self) -> None:
        response = await self._upload()

        class FailingLearner:
            async def learn(self, _path, **_kwargs):
                raise RuntimeError("model unavailable")

        with patch.object(self.routes, "ChatHistoryLearner", return_value=FailingLearner()):
            await self.routes.start_chat_history_import(
                response.import_id,
                self.routes.ChatHistoryImportStartRequest(depth="fast"),
                None,
                None,
            )
            await self.routes._running_tasks[response.import_id]

        task = self.model.get()
        self.assertEqual(task.status, "failed")
        self.assertEqual(task.normalized_path, "")
        self.assertFalse((self.root / response.import_id / "normalized.jsonl").exists())

    async def test_cooperative_cancellation_marks_task_cancelled(self) -> None:
        from src.bw_learner.history_learning import HistoryLearningCancelled

        response = await self._upload()

        class CooperativelyCancelledLearner:
            async def learn(self, _path, **_kwargs):
                raise HistoryLearningCancelled("聊天记录学习已取消")

        with patch.object(self.routes, "ChatHistoryLearner", return_value=CooperativelyCancelledLearner()):
            await self.routes.start_chat_history_import(
                response.import_id,
                self.routes.ChatHistoryImportStartRequest(depth="fast"),
                None,
                None,
            )
            await self.routes._running_tasks[response.import_id]

        task = self.model.get()
        self.assertEqual(task.status, "cancelled")
        self.assertIsNone(task.error_message)
        self.assertEqual(task.normalized_path, "")
        self.assertFalse((self.root / response.import_id / "normalized.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
