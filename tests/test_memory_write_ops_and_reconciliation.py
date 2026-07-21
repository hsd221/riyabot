import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.memory import reconciliation, write_ops as write_ops_module
from src.memory.reconciliation import ReconciliationTask
from src.memory.write_ops import (
    OpStatus,
    OpType,
    WriteOp,
    WriteOpLogger,
    WriteOperation,
    ensure_atomic_write,
    generate_op_id,
)


def make_op(
    op_id: str,
    *,
    op_type: OpType = OpType.INSERT_ATOM,
    target: str = "sqlite",
    atom_ids: list[str] | None = None,
    status: OpStatus = OpStatus.PENDING,
    payload: dict | None = None,
    retry_count: int = 0,
    created_at: float = 1.0,
) -> WriteOp:
    return WriteOp(
        op_id=op_id,
        op_type=op_type,
        target=target,
        atom_ids=["atom-1"] if atom_ids is None else atom_ids,
        payload=payload or {},
        status=status,
        retry_count=retry_count,
        created_at=created_at,
    )


class WriteOpDataModelTest(unittest.TestCase):
    def test_write_op_serializes_legacy_records_and_reports_elapsed_retry_terminal_state(self) -> None:
        legacy = {
            "op_id": "op-legacy",
            "op_type": "insert_atom",
            "target": "sqlite",
            "status": "failed",
            "started_at": 10.0,
            "completed_at": 12.5,
        }

        op = WriteOp.from_dict(legacy)
        serialized = op.to_dict()

        self.assertEqual(op.op_type, OpType.INSERT_ATOM)
        self.assertEqual(op.status, OpStatus.FAILED)
        self.assertEqual(op.atom_ids, [])
        self.assertEqual(op.payload, {})
        self.assertEqual(op.elapsed, 2.5)
        self.assertTrue(op.is_retriable)
        self.assertFalse(op.is_terminal)
        self.assertEqual(serialized["op_type"], "insert_atom")
        self.assertEqual(serialized["status"], "failed")

        pending = WriteOp("op-pending", OpType.INSERT_ATOM, "sqlite")
        self.assertIsNone(pending.elapsed)

    def test_generate_op_id_and_default_log_path_for_non_db_file(self) -> None:
        with patch.object(write_ops_module.time, "time", return_value=123.456):
            with patch.object(write_ops_module.uuid, "uuid4", return_value=SimpleNamespace(hex="abcdef123456")):
                op_id = generate_op_id()

        self.assertEqual(op_id, "op_123456_abcdef12")
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = WriteOpLogger(str(Path(tmpdir) / "memory.sqlite"))
            self.assertTrue(logger.log_file.endswith("memory.sqlite_write_ops.jsonl"))

            nested_db = Path(tmpdir) / "nested" / "memory.db"
            WriteOpLogger(str(nested_db))
            self.assertTrue(nested_db.parent.exists())

    def test_write_op_logger_lifecycle_queries_stats_and_inconsistent_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = WriteOpLogger(str(Path(tmpdir) / "memory.db"))
            sqlite_op = make_op("op-sqlite", target="sqlite", atom_ids=["atom-a"], status=OpStatus.COMPLETED)
            qdrant_op = make_op("op-qdrant", target="qdrant", atom_ids=["atom-a"], status=OpStatus.FAILED)
            pending_op = make_op("op-pending", atom_ids=["atom-b"], status=OpStatus.PENDING)
            no_atom_failed = make_op("op-no-atoms", atom_ids=[], status=OpStatus.FAILED)
            mismatch_completed = make_op(
                "op-mismatch",
                op_type=OpType.UPDATE_ATOM,
                target="sqlite",
                atom_ids=["atom-a"],
                status=OpStatus.COMPLETED,
            )
            same_target_completed = make_op(
                "op-same-target",
                target="sqlite",
                atom_ids=["atom-b"],
                status=OpStatus.COMPLETED,
            )

            logger.log_op(sqlite_op)
            logger.log_op(qdrant_op)
            logger.log_op(pending_op)
            logger.log_op(no_atom_failed)
            logger.log_op(mismatch_completed)
            logger.log_op(same_target_completed)
            started = logger.mark_started("op-pending")
            failed = logger.mark_failed("op-pending", "boom")
            not_found_completed = logger.mark_completed("missing")

            self.assertEqual(started.status, OpStatus.IN_PROGRESS)
            self.assertEqual(failed.status, OpStatus.FAILED)
            self.assertEqual(failed.error_message, "boom")
            self.assertIsNone(not_found_completed)
            self.assertEqual([op.op_id for op in logger.get_pending_ops()], [])
            self.assertEqual([op.op_id for op in logger.get_failed_ops()], ["op-qdrant", "op-pending", "op-no-atoms"])
            self.assertEqual(
                [op.op_id for op in logger.get_recoverable_ops()],
                ["op-qdrant", "op-pending", "op-no-atoms"],
            )
            self.assertEqual(logger.get_op("op-sqlite").status, OpStatus.COMPLETED)
            self.assertIsNone(logger.get_op("missing"))

            inconsistent = logger.get_inconsistent_ops()
            stats = logger.get_stats()

        self.assertEqual([(ok.op_id, bad.op_id) for ok, bad in inconsistent], [("op-sqlite", "op-qdrant")])
        self.assertEqual(stats["total_ops"], 6)
        self.assertEqual(stats["by_status"]["failed"], 3)
        self.assertEqual(stats["by_type"]["insert_atom"], 5)
        self.assertEqual(stats["pending_count"], 0)
        self.assertGreater(stats["file_size_bytes"], 0)

    def test_write_op_logger_reads_missing_empty_and_invalid_lines_and_reports_empty_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = WriteOpLogger(str(Path(tmpdir) / "memory.db"))
            self.assertEqual(logger._read_all_ops(), [])
            self.assertEqual(logger.get_stats()["total_ops"], 0)

            Path(logger.log_file).write_text(
                "\n"
                "{bad json}\n"
                '{"op_id":"bad-type","op_type":"unknown","target":"sqlite"}\n'
                '{"op_id":"ok","op_type":"insert_atom","target":"sqlite","status":"pending"}\n',
                encoding="utf-8",
            )
            ops = logger._read_all_ops()

        self.assertEqual([op.op_id for op in ops], ["ok"])

    def test_write_op_logger_trims_old_terminal_records_but_keeps_non_terminal_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = WriteOpLogger(str(Path(tmpdir) / "memory.db"), max_entries=2)
            logger._write_all_ops(
                [
                    make_op("old-completed", status=OpStatus.COMPLETED, created_at=1.0),
                    make_op("pending", status=OpStatus.PENDING, created_at=2.0),
                    make_op("rolled-back", status=OpStatus.ROLLED_BACK, created_at=3.0),
                    make_op("new-completed", status=OpStatus.COMPLETED, created_at=4.0),
                ]
            )

            trimmed = logger._auto_trim()
            remaining = logger._read_all_ops()

        self.assertEqual(trimmed, 2)
        self.assertEqual([op.op_id for op in remaining], ["pending", "new-completed"])

    def test_write_op_logger_cleanup_completed_removes_only_old_terminal_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = WriteOpLogger(str(Path(tmpdir) / "memory.db"))
            now = write_ops_module.datetime.now().timestamp()
            logger._write_all_ops(
                [
                    make_op(
                        "old-completed",
                        status=OpStatus.COMPLETED,
                        created_at=1,
                    ),
                    make_op(
                        "old-rolled-back",
                        status=OpStatus.ROLLED_BACK,
                        created_at=2,
                    ),
                    make_op("old-failed", status=OpStatus.FAILED, created_at=3),
                    make_op("new-completed", status=OpStatus.COMPLETED, created_at=4),
                ]
            )
            logger._update_op("old-completed", completed_at=now - 10 * 86400)
            logger._update_op("old-rolled-back", completed_at=now - 10 * 86400)
            logger._update_op("new-completed", completed_at=now)

            removed = logger.cleanup_completed(older_than_days=7)
            remaining = [op.op_id for op in logger._read_all_ops()]

        self.assertEqual(removed, 2)
        self.assertEqual(remaining, ["old-failed", "new-completed"])

    def test_write_op_logger_lock_fallbacks_and_rotation_branches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = WriteOpLogger(str(Path(tmpdir) / "memory.db"))
            Path(logger.log_file).write_text("x\n", encoding="utf-8")

            with open(logger.log_file, "r", encoding="utf-8") as f:
                with patch("fcntl.flock", side_effect=OSError("no lock")):
                    logger._acquire_lock(f)
                    logger._release_lock(f)

            with patch.object(logger, "MAX_FILE_SIZE", 999), patch.object(logger, "MAX_LINE_COUNT", 99):
                logger._check_rotate()
            self.assertTrue(Path(logger.log_file).exists())

            with patch("os.path.getsize", return_value=0), patch("builtins.open", side_effect=OSError("read fail")):
                logger._check_rotate()

            with patch.object(logger, "MAX_FILE_SIZE", 999), patch.object(logger, "MAX_LINE_COUNT", 1):
                with patch.object(logger, "_rotate_log") as rotate:
                    logger._check_rotate()
            rotate.assert_called_once()

            with patch("os.rename", side_effect=OSError("rename fail")):
                logger._rotate_log()
            self.assertTrue(Path(logger.log_file).exists())

            with patch("builtins.open", side_effect=OSError("create fail")):
                logger._rotate_log()
            self.assertTrue(Path(f"{logger.log_file}.1").exists())

    def test_write_op_logger_rotation_removes_oldest_backup_when_many_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = WriteOpLogger(str(Path(tmpdir) / "memory.db"))
            Path(logger.log_file).write_text("active\n", encoding="utf-8")
            for idx in range(1, 51):
                Path(f"{logger.log_file}.{idx}").write_text(str(idx), encoding="utf-8")

            logger._rotate_log()

            self.assertFalse(Path(f"{logger.log_file}.1").exists())
            self.assertTrue(Path(f"{logger.log_file}.51").exists())

    def test_write_op_logger_rotation_tolerates_oldest_backup_delete_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = WriteOpLogger(str(Path(tmpdir) / "memory.db"))
            Path(logger.log_file).write_text("active\n", encoding="utf-8")
            for idx in range(1, 51):
                Path(f"{logger.log_file}.{idx}").write_text(str(idx), encoding="utf-8")

            real_remove = os.remove

            def remove_with_first_failure(path: str) -> None:
                if path == f"{logger.log_file}.1":
                    raise OSError("cannot remove")
                real_remove(path)

            with patch("os.remove", side_effect=remove_with_first_failure):
                logger._rotate_log()

            self.assertTrue(Path(f"{logger.log_file}.1").exists())

    def test_ensure_atomic_write_decorator_rolls_back_sync_failures(self) -> None:
        rollbacks = []

        @ensure_atomic_write(success_condition=bool, rollback_fn=rollbacks.append)
        def sync_write(value: bool) -> bool:
            return value

        self.assertTrue(sync_write(True))
        self.assertFalse(sync_write(False))
        self.assertEqual(rollbacks, [False])


class WriteOperationContextTest(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_atomic_write_decorator_rolls_back_async_failures(self) -> None:
        rollbacks = []

        @ensure_atomic_write(success_condition=bool, rollback_fn=rollbacks.append)
        async def async_write(value: bool) -> bool:
            return value

        self.assertTrue(await async_write(True))
        self.assertFalse(await async_write(False))
        self.assertEqual(rollbacks, [False])

    async def test_write_operation_marks_completed_or_failed_without_swallowing_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = WriteOpLogger(str(Path(tmpdir) / "memory.db"))

            async with WriteOperation(logger, OpType.UPDATE_ATOM, "sqlite", atom_ids=["atom-1"]) as success_op:
                success_id = success_op.op_id

            with self.assertRaisesRegex(RuntimeError, "delete failed"):
                async with WriteOperation(logger, OpType.DELETE_ATOM, "qdrant", atom_ids=["atom-2"]) as failed_op:
                    failed_id = failed_op.op_id
                    raise RuntimeError("delete failed")

            success = logger.get_op(success_id)
            failed = logger.get_op(failed_id)

        self.assertEqual(success.status, OpStatus.COMPLETED)
        self.assertIsNotNone(success.completed_at)
        self.assertEqual(failed.status, OpStatus.FAILED)
        self.assertIn("RuntimeError: delete failed", failed.error_message)

    async def test_write_operation_with_none_logger_is_noop(self) -> None:
        async with WriteOperation(None, OpType.INSERT_ATOM, "sqlite", atom_ids=["atom-1"]) as op:  # type: ignore[arg-type]
            self.assertEqual(op.atom_ids, ["atom-1"])


class FakeQdrant:
    def __init__(
        self,
        *,
        delete_result: bool = True,
        upsert_result: bool = True,
        payload_result: bool = True,
        atom_ids: set[str] | None = None,
    ) -> None:
        self.delete_result = delete_result
        self.upsert_result = upsert_result
        self.payload_result = payload_result
        self.atom_ids = set(atom_ids or set())
        self.deleted: list[str] = []
        self.upserts: list[dict] = []
        self.payload_updates: list[tuple[str, dict]] = []

    async def delete_atom_vector(self, atom_id: str) -> bool:
        self.deleted.append(atom_id)
        if self.delete_result:
            self.atom_ids.discard(atom_id)
        return self.delete_result

    async def upsert_atom_vector(self, **kwargs) -> bool:
        self.upserts.append(kwargs)
        if self.upsert_result:
            self.atom_ids.add(kwargs["point_id"])
        return self.upsert_result

    async def set_atom_payload(self, atom_id: str, payload: dict) -> bool:
        self.payload_updates.append((atom_id, payload))
        return self.payload_result

    async def list_atom_ids(self) -> set[str]:
        return set(self.atom_ids)


class FakeStore:
    def __init__(
        self,
        atoms: dict[str, dict] | None = None,
        qdrant: FakeQdrant | None = None,
        *,
        archive_result: bool = True,
        migrate_result: bool = True,
    ) -> None:
        self.atoms = atoms or {}
        self.qdrant = qdrant or FakeQdrant()
        self.archive_result = archive_result
        self.migrate_result = migrate_result
        self.insert_calls = 0
        self.updates: list[tuple[str, dict]] = []
        self.deletes: list[str] = []
        self.archives: list[str] = []
        self.migrations: list[tuple[str, str]] = []

    async def get_atom(self, atom_id: str) -> dict | None:
        return self.atoms.get(atom_id)

    async def list_atoms(
        self,
        atom_type: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        atoms = list(self.atoms.values())
        if atom_type is not None:
            atoms = [atom for atom in atoms if atom.get("atom_type") == atom_type]
        if status is not None:
            atoms = [atom for atom in atoms if atom.get("status") == status]
        return atoms[offset : offset + limit]

    async def list_atom_ids(self, status: str | None = None) -> set[str]:
        return {atom_id for atom_id, atom in self.atoms.items() if status is None or atom.get("status") == status}

    async def list_atom_source_hashes(self, status: str | None = None) -> dict[str, str]:
        return {
            atom_id: reconciliation.embedding_source_hash(str(atom.get("content") or ""))
            for atom_id, atom in self.atoms.items()
            if status is None or atom.get("status") == status
        }

    async def insert_atom(self, atom: dict) -> str:
        self.insert_calls += 1
        atom_id = atom["atom_id"]
        self.atoms[atom_id] = atom
        return atom_id

    async def update_atom(self, atom_id: str, updates: dict) -> None:
        self.updates.append((atom_id, updates))
        self.atoms.setdefault(atom_id, {}).update(updates)

    async def delete_atom(self, atom_id: str) -> None:
        self.deletes.append(atom_id)
        self.atoms.pop(atom_id, None)

    async def archive_atom(self, atom_id: str) -> bool:
        self.archives.append(atom_id)
        return self.archive_result

    async def migrate_atom(self, atom_id: str, target_type: str) -> bool:
        self.migrations.append((atom_id, target_type))
        return self.migrate_result


class FakeOpLogger:
    def __init__(self, pairs: list[tuple[WriteOp, WriteOp]]) -> None:
        self.pairs = pairs
        self.updates: list[tuple[str, dict]] = []

    def get_inconsistent_ops(self) -> list[tuple[WriteOp, WriteOp]]:
        return self.pairs

    def _update_op(self, op_id: str, **updates) -> None:
        self.updates.append((op_id, updates))


class WriteOpReplayTest(unittest.IsolatedAsyncioTestCase):
    def make_logger_with_ops(self, *ops: WriteOp) -> tuple[tempfile.TemporaryDirectory, WriteOpLogger]:
        tmpdir = tempfile.TemporaryDirectory()
        logger = WriteOpLogger(str(Path(tmpdir.name) / "memory.db"))
        for op in ops:
            logger.log_op(op)
        return tmpdir, logger

    async def test_replay_returns_empty_when_no_recoverable_ops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = WriteOpLogger(str(Path(tmpdir) / "memory.db"))

            recovered = await logger.replay_failed_ops(FakeStore())

        self.assertEqual(recovered, [])

    async def test_replay_insert_atom_recovers_sqlite_and_qdrant_targets(self) -> None:
        atom = {
            "atom_id": "atom-insert",
            "content": "user 喜欢爵士乐",
            "embedding": [0.1, 0.2],
            "weight": 0.9,
        }
        tmpdir, logger = self.make_logger_with_ops(
            make_op("op-insert", target="both", status=OpStatus.FAILED, payload={"atom": atom})
        )
        store = FakeStore()

        try:
            with patch.object(
                write_ops_module,
                "generate_embedding",
                new=AsyncMock(return_value=[0.7, 0.3]),
            ):
                recovered = await logger.replay_failed_ops(store)
            completed = logger.get_op("op-insert")
        finally:
            tmpdir.cleanup()

        self.assertEqual(recovered, ["op-insert"])
        self.assertEqual(store.insert_calls, 1)
        self.assertEqual(store.qdrant.upserts[0]["point_id"], "atom-insert")
        self.assertEqual(store.qdrant.upserts[0]["payload"]["weight"], 0.9)
        self.assertEqual(completed.status, OpStatus.COMPLETED)
        self.assertEqual(completed.retry_count, 1)

    async def test_replay_insert_atom_requires_payload_atom_id_when_op_has_no_atom_ids(self) -> None:
        logger = WriteOpLogger(":memory:")

        with self.assertRaisesRegex(ValueError, "INSERT_ATOM 缺少 atom_id"):
            await logger._dispatch_replay(
                make_op(
                    "op-no-atom-id",
                    target="both",
                    atom_ids=[],
                    payload={"atom": {"content": "missing atom id"}},
                ),
                FakeStore(),
            )

    async def test_replay_marks_failed_when_dispatch_raises(self) -> None:
        tmpdir, logger = self.make_logger_with_ops(
            make_op("op-missing-payload", target="both", status=OpStatus.FAILED, payload={})
        )

        try:
            recovered = await logger.replay_failed_ops(FakeStore())
            failed = logger.get_op("op-missing-payload")
        finally:
            tmpdir.cleanup()

        self.assertEqual(recovered, [])
        self.assertEqual(failed.status, OpStatus.FAILED)
        self.assertEqual(failed.retry_count, 1)
        self.assertIn("payload 缺少 atom", failed.error_message)

    async def test_replay_update_atom_updates_sqlite_and_filters_qdrant_payload_fields(self) -> None:
        store = FakeStore(qdrant=FakeQdrant())
        op = make_op(
            "op-update",
            op_type=OpType.UPDATE_ATOM,
            target="both",
            atom_ids=["atom-1"],
            payload={
                "updates": {
                    "weight": 0.4,
                    "confidence": 0.6,
                    "source_scene": "group_chat",
                }
            },
        )
        logger = WriteOpLogger(":memory:")

        await logger._dispatch_replay(op, store)

        self.assertEqual(store.updates, [("atom-1", op.payload["updates"])])
        self.assertEqual(
            store.qdrant.payload_updates,
            [("atom-1", {"weight": 0.4, "confidence": 0.6, "source_scene": "group_chat"})],
        )

    async def test_replay_content_update_regenerates_the_full_vector(self) -> None:
        atom = {
            "atom_id": "atom-content-update",
            "content": "old content",
            "weight": 0.5,
            "status": "active",
        }
        store = FakeStore(atoms={atom["atom_id"]: atom})
        logger = WriteOpLogger(":memory:")
        op = make_op(
            "op-content-update",
            op_type=OpType.UPDATE_ATOM,
            target="both",
            atom_ids=[atom["atom_id"]],
            payload={"updates": {"content": "new content", "weight": 0.7}},
        )

        with patch.object(
            write_ops_module,
            "generate_embedding",
            new=AsyncMock(return_value=[0.3, 0.7]),
        ) as generate_embedding:
            await logger._dispatch_replay(op, store)

        generate_embedding.assert_awaited_once_with("new content")
        self.assertEqual(store.qdrant.upserts[0]["vector"], [0.3, 0.7])
        self.assertEqual(store.qdrant.upserts[0]["payload"]["weight"], 0.7)
        self.assertEqual(store.qdrant.payload_updates, [])

    async def test_replay_update_atom_requires_ids_and_surfaces_qdrant_payload_failure(self) -> None:
        logger = WriteOpLogger(":memory:")

        with self.assertRaisesRegex(ValueError, "UPDATE_ATOM 需要 atom_ids"):
            await logger._dispatch_replay(make_op("op-no-id", op_type=OpType.UPDATE_ATOM, atom_ids=[]), FakeStore())

        with self.assertRaisesRegex(RuntimeError, "payload 更新失败"):
            await logger._dispatch_replay(
                make_op(
                    "op-qdrant-update",
                    op_type=OpType.UPDATE_ATOM,
                    target="qdrant",
                    payload={"updates": {"status": "archived"}},
                ),
                FakeStore(qdrant=FakeQdrant(payload_result=False)),
            )

    async def test_replay_delete_atom_deletes_requested_targets_and_reports_failures(self) -> None:
        logger = WriteOpLogger(":memory:")
        store = FakeStore(atoms={"atom-1": {"atom_id": "atom-1"}})

        await logger._dispatch_replay(make_op("op-delete", op_type=OpType.DELETE_ATOM, target="both"), store)

        self.assertEqual(store.deletes, ["atom-1"])
        self.assertEqual(store.qdrant.deleted, ["atom-1"])

        with self.assertRaisesRegex(ValueError, "DELETE_ATOM 需要 atom_ids"):
            await logger._dispatch_replay(make_op("op-no-id", op_type=OpType.DELETE_ATOM, atom_ids=[]), FakeStore())

        with self.assertRaisesRegex(RuntimeError, "Qdrant replay 删除失败"):
            await logger._dispatch_replay(
                make_op("op-delete-fails", op_type=OpType.DELETE_ATOM, target="qdrant"),
                FakeStore(qdrant=FakeQdrant(delete_result=False)),
            )

    async def test_replay_batch_insert_accepts_single_or_multiple_payloads_and_sqlite_fallback_errors(self) -> None:
        logger = WriteOpLogger(":memory:")
        single_atom = {"atom_id": "atom-single", "content": "single", "embedding": [0.1]}
        multi_atom = {"atom_id": "atom-multi", "content": "multi", "embedding": [0.2]}
        store = FakeStore()

        with patch.object(
            write_ops_module,
            "generate_embedding",
            new=AsyncMock(side_effect=[[0.6], [0.4]]),
        ):
            await logger._dispatch_replay(
                make_op("op-single", op_type=OpType.BATCH_INSERT, target="both", payload={"atom": single_atom}),
                store,
            )
            await logger._dispatch_replay(
                make_op("op-multi", op_type=OpType.BATCH_INSERT, target="both", payload={"atoms": [multi_atom]}),
                store,
            )

        self.assertEqual(store.insert_calls, 2)
        self.assertEqual([upsert["point_id"] for upsert in store.qdrant.upserts], ["atom-single", "atom-multi"])

        with self.assertRaisesRegex(ValueError, "atom payload 缺少 atom_id"):
            await logger._dispatch_replay(
                make_op("op-bad-batch", op_type=OpType.BATCH_INSERT, payload={"atoms": [{"content": "bad"}]}),
                FakeStore(),
            )

        with self.assertRaisesRegex(ValueError, "缺少 payload"):
            await logger._dispatch_replay(
                make_op("op-empty-sqlite", op_type=OpType.BATCH_INSERT, target="both", payload={}),
                FakeStore(),
            )

    async def test_replay_batch_insert_can_rebuild_qdrant_from_sqlite_fallback(self) -> None:
        logger = WriteOpLogger(":memory:")
        atom = {"atom_id": "atom-existing", "content": "from sqlite", "embedding": [0.3]}
        store = FakeStore(atoms={"atom-existing": atom})

        with patch.object(
            write_ops_module,
            "generate_embedding",
            new=AsyncMock(return_value=[0.9]),
        ):
            await logger._dispatch_replay(
                make_op(
                    "op-qdrant-fallback",
                    op_type=OpType.BATCH_INSERT,
                    target="qdrant",
                    atom_ids=["atom-existing"],
                    payload={},
                ),
                store,
            )

        self.assertEqual(store.qdrant.upserts[0]["point_id"], "atom-existing")

        with self.assertRaisesRegex(ValueError, "找不到原子"):
            await logger._dispatch_replay(
                make_op(
                    "op-missing-fallback",
                    op_type=OpType.BATCH_INSERT,
                    target="qdrant",
                    atom_ids=["missing"],
                    payload={},
                ),
                FakeStore(),
            )

    async def test_replay_archive_and_migrate_require_ids_and_successful_store_results(self) -> None:
        logger = WriteOpLogger(":memory:")
        store = FakeStore()

        await logger._dispatch_replay(make_op("op-archive", op_type=OpType.ARCHIVE_ATOM), store)
        await logger._dispatch_replay(
            make_op("op-migrate", op_type=OpType.MIGRATE_ATOM, payload={"target_type": "semantic"}),
            store,
        )

        self.assertEqual(store.archives, ["atom-1"])
        self.assertEqual(store.migrations, [("atom-1", "semantic")])

        with self.assertRaisesRegex(ValueError, "ARCHIVE_ATOM 需要 atom_ids"):
            await logger._dispatch_replay(make_op("op-no-archive-id", op_type=OpType.ARCHIVE_ATOM, atom_ids=[]), store)
        with self.assertRaisesRegex(RuntimeError, "ARCHIVE_ATOM 未处理"):
            await logger._dispatch_replay(
                make_op("op-archive-fails", op_type=OpType.ARCHIVE_ATOM),
                FakeStore(archive_result=False),
            )
        with self.assertRaisesRegex(ValueError, "MIGRATE_ATOM 需要 atom_ids"):
            await logger._dispatch_replay(make_op("op-no-migrate-id", op_type=OpType.MIGRATE_ATOM, atom_ids=[]), store)
        with self.assertRaisesRegex(RuntimeError, "MIGRATE_ATOM 未处理"):
            await logger._dispatch_replay(
                make_op("op-migrate-fails", op_type=OpType.MIGRATE_ATOM, payload={"target_type": "semantic"}),
                FakeStore(migrate_result=False),
            )

    async def test_replay_dream_consolidation_is_noop(self) -> None:
        logger = WriteOpLogger(":memory:")

        await logger._dispatch_replay(make_op("op-dream", op_type=OpType.DREAM_CONSOLE), FakeStore())

    async def test_replay_unknown_operation_type_is_skipped(self) -> None:
        logger = WriteOpLogger(":memory:")
        op = make_op("op-unknown")
        op.op_type = "unknown"  # type: ignore[assignment]

        await logger._dispatch_replay(op, FakeStore())

    async def test_replay_target_and_payload_helpers_cover_defaults_and_unknown_target(self) -> None:
        logger = WriteOpLogger(":memory:")

        self.assertEqual(logger._replay_targets(make_op("op-both", target="both")), {"sqlite", "qdrant"})
        self.assertEqual(logger._replay_targets(make_op("op-all", target="all")), {"sqlite", "qdrant"})
        self.assertEqual(logger._replay_targets(make_op("op-sqlite", target="sqlite")), {"sqlite"})
        self.assertEqual(logger._replay_targets(make_op("op-unknown", target="weird")), {"sqlite", "qdrant"})
        self.assertEqual(
            logger._atom_vector_payload("atom-defaults", {}),
            {
                "atom_id": "atom-defaults",
                "atom_type": "factual",
                "user_id": None,
                "group_id": None,
                "weight": 0.5,
                "importance": 0.5,
                "confidence": 0.5,
                "status": "active",
                "source_scene": "chat",
                "source_id": None,
                "privacy_level": "context_sensitive",
            },
        )

    async def test_ensure_sqlite_atom_and_upsert_qdrant_atom_validate_inputs(self) -> None:
        logger = WriteOpLogger(":memory:")

        with self.assertRaisesRegex(ValueError, "缺少 atom_id"):
            await logger._ensure_sqlite_atom(FakeStore(), {"content": "missing id"})

        existing = {"atom_id": "atom-existing", "content": "exists"}
        store = FakeStore(atoms={"atom-existing": existing})
        self.assertEqual(await logger._ensure_sqlite_atom(store, existing), "atom-existing")
        self.assertEqual(store.insert_calls, 0)

        with self.assertRaisesRegex(ValueError, "缺少 content"):
            await logger._upsert_qdrant_atom(FakeStore(), "atom-empty", {"atom_id": "atom-empty"})

        with patch.object(write_ops_module, "generate_embedding", new=AsyncMock(return_value=[])):
            with self.assertRaisesRegex(RuntimeError, "生成 embedding 失败"):
                await logger._upsert_qdrant_atom(
                    FakeStore(),
                    "atom-no-embedding",
                    {"atom_id": "atom-no-embedding", "content": "hello"},
                )

        with patch.object(write_ops_module, "generate_embedding", new=AsyncMock(return_value=[0.1])):
            with self.assertRaisesRegex(RuntimeError, "upsert 失败"):
                await logger._upsert_qdrant_atom(
                    FakeStore(qdrant=FakeQdrant(upsert_result=False)),
                    "atom-upsert-fails",
                    {"atom_id": "atom-upsert-fails", "content": "hello"},
                )

    async def test_replay_reembeds_instead_of_reusing_a_persisted_vector(self) -> None:
        logger = WriteOpLogger(":memory:")
        store = FakeStore()
        generate_embedding = AsyncMock(return_value=[0.8, 0.2])

        with patch.object(write_ops_module, "generate_embedding", new=generate_embedding):
            await logger._upsert_qdrant_atom(
                store,
                "atom-stale-vector",
                {
                    "atom_id": "atom-stale-vector",
                    "content": "current content",
                    "embedding": [0.1, 0.9],
                },
            )

        generate_embedding.assert_awaited_once_with("current content")
        self.assertEqual(store.qdrant.upserts[0]["vector"], [0.8, 0.2])


class ReconciliationTaskTest(unittest.IsolatedAsyncioTestCase):
    async def test_storage_drift_reembeds_vector_when_source_hash_is_stale(self) -> None:
        atom_id = "stale-source-hash"
        atom = {"atom_id": atom_id, "content": "new content", "status": "active"}

        class MetadataQdrant(FakeQdrant):
            async def list_atom_points(self) -> list[dict]:
                return [
                    {
                        "physical_id": atom_id,
                        "business_id": atom_id,
                        "embedding_source_hash": reconciliation.embedding_source_hash("old content"),
                    }
                ]

        qdrant = MetadataQdrant(atom_ids={atom_id})
        task = ReconciliationTask(FakeStore(atoms={atom_id: atom}, qdrant=qdrant))  # type: ignore[arg-type]

        with patch.object(reconciliation, "generate_embedding", new=AsyncMock(return_value=[0.7, 0.3])) as embed:
            repaired, removed = await task._reconcile_storage_drift()

        self.assertEqual((repaired, removed), (1, 0))
        embed.assert_awaited_once_with("new content")
        self.assertEqual(qdrant.upserts[0]["point_id"], atom_id)
        self.assertEqual(
            qdrant.upserts[0]["payload"]["embedding_source_hash"],
            reconciliation.embedding_source_hash("new content"),
        )

    async def test_run_repairs_actual_store_drift_without_inconsistent_write_ops(self) -> None:
        missing_atom = {
            "atom_id": "missing-active",
            "atom_type": "preference",
            "content": "user prefers concise replies",
            "weight": 0.8,
            "importance": 0.7,
            "confidence": 0.9,
            "status": "active",
            "source_scene": "private_chat",
            "source_id": "stream-1",
            "privacy_level": "context_sensitive",
        }
        shared_atom = {
            "atom_id": "shared-active",
            "content": "already indexed",
            "status": "active",
        }
        inactive_atom = {
            "atom_id": "inactive",
            "content": "must not be re-indexed",
            "status": "archived",
        }
        qdrant = FakeQdrant(atom_ids={"shared-active", "orphan-vector"})
        store = FakeStore(
            atoms={
                "missing-active": missing_atom,
                "shared-active": shared_atom,
                "inactive": inactive_atom,
            },
            qdrant=qdrant,
        )
        op_logger = FakeOpLogger([])
        task = ReconciliationTask(store, op_logger=op_logger)  # type: ignore[arg-type]

        with patch.object(reconciliation, "generate_embedding", new=AsyncMock(return_value=[0.1, 0.2])) as embed:
            await task.run()
            await task.run()

        self.assertEqual(qdrant.atom_ids, {"missing-active", "shared-active"})
        self.assertEqual(qdrant.deleted, ["orphan-vector"])
        self.assertEqual([upsert["point_id"] for upsert in qdrant.upserts], ["missing-active"])
        embed.assert_awaited_once_with("user prefers concise replies")

    async def test_reconcile_sqlite_to_qdrant_uses_payload_or_store_fallback_and_payload_defaults(self) -> None:
        atom = {
            "atom_id": "atom-1",
            "atom_type": "preference",
            "content": "user 喜欢爵士乐",
            "weight": 0.8,
            "importance": 0.7,
            "confidence": 0.9,
            "status": "active",
            "source_scene": "group_chat",
            "source_id": "stream-1",
            "privacy_level": "context_sensitive",
        }
        store = FakeStore(
            atoms={
                "atom-1": atom,
                "atom-2": {**atom, "atom_id": "atom-2"},
            }
        )
        task = ReconciliationTask(store)  # type: ignore[arg-type]

        with patch.object(reconciliation, "generate_embedding", new=AsyncMock(return_value=[0.1, 0.2])) as embed:
            payload_ok = await task._sync_sqlite_to_qdrant("atom-1", make_op("op-1", payload={"atom": atom}))
            fallback_ok = await task._sync_sqlite_to_qdrant(
                "atom-2",
                make_op("op-2", payload={"updates": {"weight": 0.4}}),
            )

        self.assertTrue(payload_ok)
        self.assertTrue(fallback_ok)
        self.assertEqual(embed.await_count, 2)
        self.assertEqual(store.qdrant.upserts[0]["point_id"], "atom-1")
        self.assertEqual(store.qdrant.upserts[0]["vector"], [0.1, 0.2])
        self.assertEqual(store.qdrant.upserts[0]["payload"]["atom_type"], "preference")
        self.assertEqual(store.qdrant.upserts[1]["point_id"], "atom-2")

    async def test_reconcile_sqlite_to_qdrant_returns_false_for_missing_content_embedding_or_upsert_failure(
        self,
    ) -> None:
        task = ReconciliationTask(FakeStore())  # type: ignore[arg-type]
        no_content = make_op("op-empty", payload={"atom": {"atom_id": "atom-empty", "content": ""}})
        missing_atom = make_op("op-missing", payload={"updates": {"weight": 0.4}})
        upsert_fails = ReconciliationTask(FakeStore(qdrant=FakeQdrant(upsert_result=False)))  # type: ignore[arg-type]
        atom = {"atom_id": "atom-1", "content": "hello"}

        self.assertFalse(await task._sync_sqlite_to_qdrant("atom-empty", no_content))
        self.assertFalse(await task._sync_sqlite_to_qdrant("missing", missing_atom))
        with patch.object(reconciliation, "generate_embedding", new=AsyncMock(return_value=[])):
            self.assertFalse(await task._sync_sqlite_to_qdrant("atom-1", make_op("op-embed", payload={"atom": atom})))
        with patch.object(reconciliation, "generate_embedding", new=AsyncMock(return_value=[0.1])):
            self.assertFalse(
                await upsert_fails._sync_sqlite_to_qdrant("atom-1", make_op("op-upsert", payload={"atom": atom}))
            )

    async def test_reconcile_one_routes_cross_store_cases_and_reports_failed_qdrant_delete(self) -> None:
        store = FakeStore(qdrant=FakeQdrant(delete_result=False))
        task = ReconciliationTask(store)  # type: ignore[arg-type]

        with patch.object(task, "_sync_sqlite_to_qdrant", new=AsyncMock(return_value=True)) as sync:
            self.assertTrue(
                await task._reconcile_one(
                    make_op("sqlite-ok", target="sqlite", status=OpStatus.COMPLETED),
                    make_op("qdrant-bad", target="qdrant", status=OpStatus.FAILED),
                )
            )
        sync.assert_awaited_once()

        self.assertFalse(
            await task._reconcile_one(
                make_op("qdrant-ok", target="qdrant", status=OpStatus.COMPLETED),
                make_op("sqlite-bad", target="sqlite", status=OpStatus.FAILED),
            )
        )
        self.assertEqual(store.qdrant.deleted, ["atom-1"])
        self.assertFalse(
            await task._reconcile_one(
                make_op("same-ok", target="sqlite", status=OpStatus.COMPLETED),
                make_op("same-bad", target="sqlite", status=OpStatus.FAILED),
            )
        )
        self.assertFalse(
            await task._reconcile_one(
                make_op("no-common-ok", target="sqlite", atom_ids=["a"], status=OpStatus.COMPLETED),
                make_op("no-common-bad", target="qdrant", atom_ids=["b"], status=OpStatus.FAILED),
            )
        )

    async def test_storage_drift_preserves_vector_for_archived_sqlite_atom(self) -> None:
        atom_id = "archived-atom"
        qdrant = FakeQdrant(atom_ids={atom_id})
        store = FakeStore(
            atoms={atom_id: {"atom_id": atom_id, "content": "archived memory", "status": "archived"}},
            qdrant=qdrant,
        )
        task = ReconciliationTask(store)  # type: ignore[arg-type]

        await task._reconcile_storage_drift()
        await task._reconcile_storage_drift()

        self.assertEqual(qdrant.deleted, [])
        self.assertEqual(qdrant.atom_ids, {atom_id})

    async def test_storage_drift_does_not_upsert_atom_archived_after_scan(self) -> None:
        atom_id = "archived-during-scan"

        class ArchiveAfterActiveScanStore(FakeStore):
            async def list_atom_ids(self, status: str | None = None) -> set[str]:
                atom_ids = await super().list_atom_ids(status=status)
                if status == "active":
                    self.atoms[atom_id]["status"] = "archived"
                return atom_ids

        qdrant = FakeQdrant()
        store = ArchiveAfterActiveScanStore(
            atoms={atom_id: {"atom_id": atom_id, "content": "stale active atom", "status": "active"}},
            qdrant=qdrant,
        )
        task = ReconciliationTask(store)  # type: ignore[arg-type]

        with patch.object(reconciliation, "generate_embedding", new=AsyncMock(return_value=[0.1])) as embed:
            await task._reconcile_storage_drift()

        self.assertEqual(qdrant.upserts, [])
        embed.assert_not_awaited()

    async def test_storage_drift_requires_two_consecutive_observations_before_deleting_orphan(self) -> None:
        atom_id = "orphan-vector"
        qdrant = FakeQdrant(atom_ids={atom_id})
        task = ReconciliationTask(FakeStore(qdrant=qdrant))  # type: ignore[arg-type]

        await task._reconcile_storage_drift()
        self.assertEqual(qdrant.deleted, [])

        await task._reconcile_storage_drift()
        self.assertEqual(qdrant.deleted, [atom_id])

    async def test_storage_drift_cancels_orphan_deletion_when_sqlite_row_appears_between_scans(self) -> None:
        atom_id = "transient-orphan"
        qdrant = FakeQdrant(atom_ids={atom_id})
        store = FakeStore(qdrant=qdrant)
        task = ReconciliationTask(store)  # type: ignore[arg-type]

        await task._reconcile_storage_drift()
        store.atoms[atom_id] = {"atom_id": atom_id, "content": "restored row", "status": "archived"}
        await task._reconcile_storage_drift()
        store.atoms.pop(atom_id)
        await task._reconcile_storage_drift()

        self.assertEqual(qdrant.deleted, [])

        await task._reconcile_storage_drift()
        self.assertEqual(qdrant.deleted, [atom_id])

    async def test_storage_drift_advances_past_failed_batch_on_next_run(self) -> None:
        atoms = {
            f"atom-{index:03d}": {
                "atom_id": f"atom-{index:03d}",
                "content": f"content-{index:03d}",
                "status": "active",
            }
            for index in range(60)
        }
        qdrant = FakeQdrant()
        task = ReconciliationTask(FakeStore(atoms=atoms, qdrant=qdrant))  # type: ignore[arg-type]

        async def embed(content: str) -> list[float]:
            index = int(content.rsplit("-", maxsplit=1)[1])
            return [] if index < 50 else [0.1]

        clock = Mock(return_value=0.0)
        with (
            patch.object(reconciliation, "generate_embedding", new=AsyncMock(side_effect=embed)),
            patch.object(reconciliation.time, "monotonic", new=clock),
        ):
            await task._reconcile_storage_drift()
            self.assertEqual(qdrant.atom_ids, set())
            clock.return_value = 121.0
            await task._reconcile_storage_drift()

        later_ids = {f"atom-{index:03d}" for index in range(50, 60)}
        self.assertTrue(qdrant.atom_ids & later_ids)

    async def test_sync_rechecks_status_and_content_around_embedding_and_upsert(self) -> None:
        archived_during_embedding = {
            "atom_id": "archived-during-embedding",
            "content": "old archived content",
            "status": "active",
        }
        archived_store = FakeStore(atoms={archived_during_embedding["atom_id"]: archived_during_embedding})
        archived_task = ReconciliationTask(archived_store)  # type: ignore[arg-type]

        async def archive_during_embedding(content: str) -> list[float]:
            archived_store.atoms[archived_during_embedding["atom_id"]]["status"] = "archived"
            return [0.1]

        with patch.object(reconciliation, "generate_embedding", new=AsyncMock(side_effect=archive_during_embedding)):
            self.assertFalse(await archived_task._sync_sqlite_to_qdrant(archived_during_embedding["atom_id"]))
        self.assertEqual(archived_store.qdrant.upserts, [])

        changed_atom = {"atom_id": "changed-content", "content": "old content", "status": "active"}
        changed_store = FakeStore(atoms={changed_atom["atom_id"]: changed_atom})
        changed_task = ReconciliationTask(changed_store)  # type: ignore[arg-type]

        async def change_content(content: str) -> list[float]:
            if content == "old content":
                changed_store.atoms[changed_atom["atom_id"]]["content"] = "new content"
                return [0.1]
            return [0.2]

        embed = AsyncMock(side_effect=change_content)
        with patch.object(reconciliation, "generate_embedding", new=embed):
            self.assertTrue(await changed_task._sync_sqlite_to_qdrant(changed_atom["atom_id"]))
        self.assertEqual([call.args[0] for call in embed.await_args_list], ["old content", "new content"])
        self.assertEqual(changed_store.qdrant.upserts[0]["vector"], [0.2])

        post_upsert_atom = {"atom_id": "archived-after-upsert", "content": "content", "status": "active"}
        post_upsert_store = FakeStore(atoms={post_upsert_atom["atom_id"]: post_upsert_atom})
        original_upsert = post_upsert_store.qdrant.upsert_atom_vector

        async def archive_after_upsert(**kwargs) -> bool:
            result = await original_upsert(**kwargs)
            post_upsert_store.atoms[post_upsert_atom["atom_id"]]["status"] = "archived"
            return result

        post_upsert_store.qdrant.upsert_atom_vector = archive_after_upsert  # type: ignore[method-assign]
        post_upsert_task = ReconciliationTask(post_upsert_store)  # type: ignore[arg-type]
        with patch.object(reconciliation, "generate_embedding", new=AsyncMock(return_value=[0.3])):
            self.assertTrue(await post_upsert_task._sync_sqlite_to_qdrant(post_upsert_atom["atom_id"]))
        self.assertEqual(post_upsert_store.qdrant.deleted, [post_upsert_atom["atom_id"]])
        self.assertEqual(post_upsert_store.qdrant.atom_ids, set())

    async def test_sync_keeps_forced_retry_when_refresh_fails_after_stale_upsert(self) -> None:
        atom_id = "stale-after-upsert"
        atom = {"atom_id": atom_id, "content": "content-v1", "status": "active"}
        store = FakeStore(atoms={atom_id: atom})
        original_upsert = store.qdrant.upsert_atom_vector

        async def change_content_after_upsert(**kwargs) -> bool:
            result = await original_upsert(**kwargs)
            if len(store.qdrant.upserts) == 1:
                atom["content"] = "content-v2"
            return result

        store.qdrant.upsert_atom_vector = change_content_after_upsert  # type: ignore[method-assign]
        task = ReconciliationTask(store)  # type: ignore[arg-type]

        with patch.object(
            reconciliation,
            "generate_embedding",
            new=AsyncMock(side_effect=[[0.1], []]),
        ):
            self.assertFalse(await task._sync_sqlite_to_qdrant(atom_id))

        self.assertIn(atom_id, task._forced_resync_ids)
        self.assertEqual(store.qdrant.atom_ids, set())

        with patch.object(reconciliation, "generate_embedding", new=AsyncMock(return_value=[0.2])):
            repaired, removed = await task._reconcile_storage_drift()

        self.assertEqual((repaired, removed), (1, 0))
        self.assertNotIn(atom_id, task._forced_resync_ids)
        self.assertEqual(store.qdrant.atom_ids, {atom_id})
        self.assertEqual(store.qdrant.upserts[-1]["vector"], [0.2])

    async def test_sync_refreshes_concurrently_changed_vector_payload(self) -> None:
        atom_id = "privacy-changed-during-upsert"
        atom = {
            "atom_id": atom_id,
            "content": "private memory",
            "status": "active",
            "privacy_level": "context_sensitive",
            "weight": 0.5,
        }
        store = FakeStore(atoms={atom_id: atom})
        original_upsert = store.qdrant.upsert_atom_vector

        async def change_payload_after_upsert(**kwargs) -> bool:
            result = await original_upsert(**kwargs)
            if len(store.qdrant.upserts) == 1:
                atom["privacy_level"] = "private"
                atom["weight"] = 0.9
            return result

        store.qdrant.upsert_atom_vector = change_payload_after_upsert  # type: ignore[method-assign]
        task = ReconciliationTask(store)  # type: ignore[arg-type]

        with patch.object(reconciliation, "generate_embedding", new=AsyncMock(return_value=[0.3])) as embed:
            self.assertTrue(await task._sync_sqlite_to_qdrant(atom_id))

        self.assertEqual(embed.await_count, 2)
        self.assertEqual(store.qdrant.upserts[-1]["payload"]["privacy_level"], "private")
        self.assertEqual(store.qdrant.upserts[-1]["payload"]["weight"], 0.9)
        self.assertNotIn(atom_id, task._forced_resync_ids)

    async def test_sync_retries_failed_stale_vector_cleanup_even_when_point_id_exists(self) -> None:
        atom_id = "cleanup-retry"
        atom = {"atom_id": atom_id, "content": "content", "status": "active"}
        qdrant = FakeQdrant(delete_result=False)
        store = FakeStore(atoms={atom_id: atom}, qdrant=qdrant)
        original_upsert = qdrant.upsert_atom_vector

        async def archive_after_upsert(**kwargs) -> bool:
            result = await original_upsert(**kwargs)
            atom["status"] = "archived"
            return result

        qdrant.upsert_atom_vector = archive_after_upsert  # type: ignore[method-assign]
        task = ReconciliationTask(store)  # type: ignore[arg-type]

        with patch.object(reconciliation, "generate_embedding", new=AsyncMock(return_value=[0.4])):
            self.assertFalse(await task._sync_sqlite_to_qdrant(atom_id))

        self.assertIn(atom_id, task._forced_cleanup_ids)
        self.assertEqual(qdrant.atom_ids, {atom_id})

        qdrant.delete_result = True
        repaired, removed = await task._reconcile_storage_drift()

        self.assertEqual((repaired, removed), (0, 1))
        self.assertNotIn(atom_id, task._forced_cleanup_ids)
        self.assertEqual(qdrant.atom_ids, set())

    async def test_forced_cleanup_rechecks_active_state_before_deleting(self) -> None:
        atom_id = "reactivated-before-cleanup"

        class ReactivateAfterActiveScanStore(FakeStore):
            async def list_atom_ids(self, status: str | None = None) -> set[str]:
                atom_ids = await super().list_atom_ids(status=status)
                if status == "active":
                    self.atoms[atom_id]["status"] = "active"
                return atom_ids

        qdrant = FakeQdrant(atom_ids={atom_id})
        store = ReactivateAfterActiveScanStore(
            atoms={atom_id: {"atom_id": atom_id, "content": "restored content", "status": "archived"}},
            qdrant=qdrant,
        )
        task = ReconciliationTask(store)  # type: ignore[arg-type]
        task._forced_cleanup_ids.add(atom_id)

        with patch.object(reconciliation, "generate_embedding", new=AsyncMock(return_value=[0.5])):
            repaired, removed = await task._reconcile_storage_drift()

        self.assertEqual((repaired, removed), (0, 1))
        self.assertEqual(qdrant.deleted, [])
        self.assertEqual(qdrant.upserts[-1]["point_id"], atom_id)
        self.assertNotIn(atom_id, task._forced_cleanup_ids)
        self.assertNotIn(atom_id, task._forced_resync_ids)

    async def test_storage_drift_prunes_retry_state_for_atoms_no_longer_in_drift(self) -> None:
        atom_id = "failed-then-archived"
        atom = {"atom_id": atom_id, "content": "content", "status": "active"}
        store = FakeStore(atoms={atom_id: atom})
        task = ReconciliationTask(store)  # type: ignore[arg-type]

        with patch.object(reconciliation, "generate_embedding", new=AsyncMock(return_value=[])):
            await task._reconcile_storage_drift()
        self.assertIn(f"sync:{atom_id}", task._drift_retry_after)

        atom["status"] = "archived"
        await task._reconcile_storage_drift()

        self.assertNotIn(f"sync:{atom_id}", task._drift_retry_after)
        self.assertNotIn(f"sync:{atom_id}", task._drift_failure_counts)

    async def test_run_skips_blacklisted_or_max_retry_ops_and_increments_failed_reconciliations(self) -> None:
        completed = make_op("ok", target="sqlite", status=OpStatus.COMPLETED)
        failed_blacklisted = make_op("blacklisted", target="qdrant", status=OpStatus.FAILED)
        failed_maxed = make_op("maxed", target="qdrant", status=OpStatus.FAILED, retry_count=5)
        failed_retry = make_op("retry", target="qdrant", status=OpStatus.FAILED, retry_count=2)
        op_logger = FakeOpLogger(
            [
                (completed, failed_blacklisted),
                (completed, failed_maxed),
                (completed, failed_retry),
            ]
        )
        task = ReconciliationTask(FakeStore(), op_logger=op_logger)  # type: ignore[arg-type]
        task._blacklist.add("blacklisted")

        with patch.object(task, "_reconcile_one", new=AsyncMock(return_value=False)) as reconcile_one:
            await task.run()

        reconcile_one.assert_awaited_once_with(completed, failed_retry)
        self.assertIn("maxed", task._blacklist)
        self.assertEqual(op_logger.updates, [("retry", {"retry_count": 3})])

    async def test_run_returns_quietly_when_logger_is_missing_empty_or_raises(self) -> None:
        await ReconciliationTask(FakeStore()).run()  # type: ignore[arg-type]

        empty_logger = SimpleNamespace(get_inconsistent_ops=Mock(return_value=[]))
        await ReconciliationTask(FakeStore(), op_logger=empty_logger).run()  # type: ignore[arg-type]
        empty_logger.get_inconsistent_ops.assert_called_once()

        broken_logger = SimpleNamespace(get_inconsistent_ops=Mock(side_effect=RuntimeError("bad log")))
        await ReconciliationTask(FakeStore(), op_logger=broken_logger).run()  # type: ignore[arg-type]
        broken_logger.get_inconsistent_ops.assert_called_once()


if __name__ == "__main__":
    unittest.main()
