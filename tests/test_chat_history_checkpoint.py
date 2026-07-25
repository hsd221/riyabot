import tempfile
import unittest
from pathlib import Path


class ChatHistoryCheckpointPersistenceTest(unittest.TestCase):
    def test_append_and_load_keep_the_last_complete_record_after_a_truncated_write(self) -> None:
        from src.bw_learner.history_learning import HistoryCandidates, HistoryWindowCheckpoint
        from src.webui.chat_history_checkpoint import (
            append_extraction_checkpoint,
            load_extraction_checkpoints,
        )

        checkpoint = HistoryWindowCheckpoint(
            window_id="window-000001",
            candidates=HistoryCandidates(),
            model_call_count=1,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir)
            append_extraction_checkpoint(task_dir, "a" * 64, checkpoint)
            with (task_dir / "extraction_checkpoints.jsonl").open("ab") as output:
                output.write(b'{"version":1,"checkpoint_key":"')

            loaded = load_extraction_checkpoints(task_dir, "a" * 64)

        self.assertEqual(list(loaded), ["window-000001"])
        self.assertEqual(loaded["window-000001"].model_call_count, 1)

    def test_checkpoint_key_mismatch_is_rejected_instead_of_reusing_stale_work(self) -> None:
        from src.bw_learner.history_learning import HistoryCandidates, HistoryWindowCheckpoint
        from src.webui.chat_history_checkpoint import (
            HistoryCheckpointUnavailableError,
            append_extraction_checkpoint,
            load_extraction_checkpoints,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir)
            append_extraction_checkpoint(
                task_dir,
                "a" * 64,
                HistoryWindowCheckpoint("window-000001", HistoryCandidates(), model_call_count=1),
            )

            with self.assertRaises(HistoryCheckpointUnavailableError) as mismatch:
                load_extraction_checkpoints(task_dir, "b" * 64)

        self.assertEqual(mismatch.exception.reason, "mismatch")

    def test_pending_result_is_written_atomically_and_loaded_as_an_object(self) -> None:
        from src.webui.chat_history_checkpoint import load_pending_learning_result, write_pending_learning_result

        payload = {
            "candidates": {
                "expressions": [],
                "behaviors": [],
                "jargons": [],
                "memories": [],
                "profiles": [],
            },
            "candidate_catalog": {
                "total": 0,
                "counts": {"expressions": 0, "behaviors": 0, "jargons": 0, "memories": 0, "profiles": 0},
                "complete": True,
                "incomplete_window_ids": [],
                "storage": "paged",
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir)
            write_pending_learning_result(task_dir, payload)
            loaded = load_pending_learning_result(task_dir)

        self.assertEqual(loaded, payload)


if __name__ == "__main__":
    unittest.main()
