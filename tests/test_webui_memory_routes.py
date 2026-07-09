import datetime
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from peewee import SqliteDatabase

from src.webui import memory_routes
from src.webui.memory_routes import DreamRun, InsightPool, MemoryAtom, NoisePool


class MemoryRoutesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.models = [MemoryAtom, DreamRun, InsightPool, NoisePool]
        self.db = SqliteDatabase(":memory:")
        self.bind_ctx = self.db.bind_ctx(self.models)
        self.bind_ctx.__enter__()
        self.addCleanup(self.bind_ctx.__exit__, None, None, None)
        self.db.connect()
        self.db.create_tables(self.models)
        self.addCleanup(self._cleanup_db)

        self.ready_patcher = patch.object(memory_routes, "_ensure_memory_database_ready", return_value=None)
        self.ready_patcher.start()
        self.addCleanup(self.ready_patcher.stop)

    def _cleanup_db(self) -> None:
        if not self.db.is_closed():
            self.db.drop_tables(self.models)
            self.db.close()

    def create_atom(
        self,
        atom_id: str,
        *,
        atom_type: str = "episodic",
        status: str = "active",
        content: str | None = None,
        entities: object = None,
        created_at: datetime.datetime | None = None,
        importance: float = 0.5,
        confidence: float = 0.5,
        weight: float = 0.5,
    ) -> MemoryAtom:
        if entities is None:
            entities_value = None
        elif isinstance(entities, str):
            entities_value = entities
        else:
            entities_value = json.dumps(entities, ensure_ascii=False)

        return MemoryAtom.create(
            atom_id=atom_id,
            atom_type=atom_type,
            content=content or f"content-{atom_id}",
            entities=entities_value,
            importance=importance,
            confidence=confidence,
            weight=weight,
            status=status,
            source_scene="chat",
            created_at=created_at or datetime.datetime(2026, 1, 1, 12, 0),
            last_accessed_at=datetime.datetime(2026, 1, 1, 12, 0),
            last_reinforced_at=datetime.datetime(2026, 1, 1, 12, 0),
        )

    def test_helpers_format_dates_parse_json_fields_and_delegate_auth(self) -> None:
        atom = self.create_atom(
            "atom-json",
            entities=[{"name": "小明"}],
            created_at=datetime.datetime(2026, 2, 3, 4, 5, 6),
        )
        invalid_atom = self.create_atom("atom-invalid", entities="{bad json")
        dream = DreamRun.create(
            run_type="daily",
            start_time=datetime.datetime(2026, 2, 1, 1, 0),
            end_time=None,
            status="running",
            atoms_processed=2,
            atoms_created=1,
            summary="summary",
        )
        insight = InsightPool.create(
            content="insight",
            source_atoms=json.dumps(["atom-json"], ensure_ascii=False),
            agent_name="dream_weaver",
            confidence=0.8,
            created_at=datetime.datetime(2026, 2, 2, 2, 0),
        )
        invalid_insight = InsightPool.create(
            content="invalid",
            source_atoms="[bad",
            agent_name="dream_weaver",
            confidence=0.1,
        )
        noise = NoisePool.create(
            content="noise",
            source_scene="private",
            significance=0.2,
            created_at=datetime.datetime(2026, 2, 4, 4, 0),
            ttl_days=3,
        )

        self.assertEqual(memory_routes._format_datetime("raw"), "raw")
        self.assertIsNone(memory_routes._format_datetime(None))
        self.assertEqual(memory_routes._atom_to_dict(atom)["entities"], [{"name": "小明"}])
        self.assertEqual(memory_routes._atom_to_dict(invalid_atom)["entities"], "{bad json")
        self.assertEqual(memory_routes._dream_run_to_dict(dream)["start_time"], "2026-02-01T01:00:00")
        self.assertEqual(memory_routes._insight_to_dict(insight)["source_atoms"], ["atom-json"])
        self.assertEqual(memory_routes._insight_to_dict(invalid_insight)["source_atoms"], "[bad")
        self.assertEqual(memory_routes._noise_to_dict(noise)["source_scene"], "private")

        with patch.object(memory_routes, "verify_auth_token_from_cookie_or_header", return_value=True) as verify:
            self.assertTrue(memory_routes.require_auth(maibot_session="cookie", authorization="Bearer token"))
        verify.assert_called_once_with("cookie", "Bearer token")

    async def test_memory_stats_counts_atoms_by_status_type_and_related_tables(self) -> None:
        self.create_atom("a1", atom_type="episodic", status="active")
        self.create_atom("a2", atom_type="factual", status="active")
        self.create_atom("a3", atom_type="factual", status="archived")
        self.create_atom("a4", atom_type="custom", status="active")
        DreamRun.create(run_type="daily", start_time=datetime.datetime(2026, 1, 1), status="completed")
        InsightPool.create(content="insight", source_atoms=None, agent_name="agent", confidence=0.7)
        NoisePool.create(content="noise", source_scene="chat", significance=0.1, ttl_days=7)

        stats = await memory_routes.get_memory_stats(_auth=True)

        self.assertEqual(stats.total_atoms, 4)
        self.assertEqual(stats.active_atoms, 3)
        self.assertEqual(stats.type_distribution, {"episodic": 1, "factual": 2})
        self.assertEqual(stats.dream_run_count, 1)
        self.assertEqual(stats.insight_count, 1)
        self.assertEqual(stats.noise_pool_count, 1)

    async def test_memory_atoms_filter_order_paginate_and_detail_routes(self) -> None:
        self.create_atom(
            "old-active",
            atom_type="episodic",
            status="active",
            entities=["old"],
            created_at=datetime.datetime(2026, 1, 1, 10, 0),
        )
        self.create_atom(
            "new-active",
            atom_type="episodic",
            status="active",
            entities=["new"],
            created_at=datetime.datetime(2026, 1, 2, 10, 0),
            importance=0.9,
        )
        self.create_atom(
            "archived",
            atom_type="factual",
            status="archived",
            created_at=datetime.datetime(2026, 1, 3, 10, 0),
        )

        first_page = await memory_routes.get_memory_atoms(
            atom_type="episodic",
            status="active",
            limit=1,
            offset=0,
            _auth=True,
        )
        second_page = await memory_routes.get_memory_atoms(
            atom_type="episodic",
            status="active",
            limit=1,
            offset=1,
            _auth=True,
        )
        all_statuses = await memory_routes.get_memory_atoms(
            atom_type=None,
            status=None,
            limit=10,
            offset=0,
            _auth=True,
        )
        detail = await memory_routes.get_memory_atom_detail("new-active", _auth=True)

        self.assertEqual(first_page.total, 2)
        self.assertEqual([item.atom_id for item in first_page.items], ["new-active"])
        self.assertEqual([item.atom_id for item in second_page.items], ["old-active"])
        self.assertEqual(all_statuses.total, 3)
        self.assertEqual(detail.data.atom_id, "new-active")
        self.assertEqual(detail.data.entities, ["new"])
        self.assertEqual(detail.data.importance, 0.9)

        with self.assertRaises(HTTPException) as missing:
            await memory_routes.get_memory_atom_detail("missing", _auth=True)
        self.assertEqual(missing.exception.status_code, 404)

    async def test_dream_insight_and_noise_routes_order_and_paginate_records(self) -> None:
        DreamRun.create(
            run_type="daily",
            start_time=datetime.datetime(2026, 1, 1, 8, 0),
            end_time=datetime.datetime(2026, 1, 1, 9, 0),
            status="completed",
            atoms_processed=5,
            atoms_created=2,
            summary="old",
        )
        newer_run = DreamRun.create(
            run_type="weekly",
            start_time=datetime.datetime(2026, 1, 2, 8, 0),
            status="running",
            atoms_processed=6,
            atoms_created=3,
            summary="new",
        )
        InsightPool.create(
            content="old insight",
            source_atoms=json.dumps(["a1"]),
            agent_name="agent",
            confidence=0.6,
            created_at=datetime.datetime(2026, 1, 1, 8, 0),
        )
        InsightPool.create(
            content="new insight",
            source_atoms=json.dumps(["a2"]),
            agent_name="agent",
            confidence=0.9,
            created_at=datetime.datetime(2026, 1, 2, 8, 0),
        )
        NoisePool.create(
            content="old noise",
            source_scene="chat",
            significance=0.1,
            created_at=datetime.datetime(2026, 1, 1, 8, 0),
            ttl_days=7,
        )
        NoisePool.create(
            content="new noise",
            source_scene="private",
            significance=0.2,
            created_at=datetime.datetime(2026, 1, 2, 8, 0),
            ttl_days=3,
        )

        dream_runs = await memory_routes.get_dream_runs(limit=1, offset=0, _auth=True)
        insights = await memory_routes.get_insights(limit=2, offset=0, _auth=True)
        noise = await memory_routes.get_noise_pool(limit=1, offset=1, _auth=True)

        self.assertEqual(dream_runs.total, 2)
        self.assertEqual(dream_runs.items[0].id, newer_run.id)
        self.assertEqual(dream_runs.items[0].status, "running")
        self.assertEqual(dream_runs.items[0].summary, "new")
        self.assertEqual(insights.total, 2)
        self.assertEqual([item.content for item in insights.items], ["new insight", "old insight"])
        self.assertEqual(insights.items[0].source_atoms, ["a2"])
        self.assertEqual(noise.total, 2)
        self.assertEqual(noise.items[0].content, "old noise")
        self.assertEqual(noise.items[0].ttl_days, 7)
