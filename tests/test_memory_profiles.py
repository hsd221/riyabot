import datetime
import tempfile
import unittest
from pathlib import Path

from src.memory.atom import AtomType, EpisodicDetail, MemoryAtom, SemanticDetail
from src.memory.schema import (
    MemoryAtom as MemoryAtomModel,
    SemanticDetail as SemanticDetailModel,
    configure_memory_database,
    initialize_database,
    memory_db,
)
from src.memory.user_profile import (
    ProfileBuilder,
    ProfileRetriever,
    ProfileStore,
    UserProfile,
    _entities_contain_user,
    _matches_keywords,
    _safe_json_loads,
)


class MemoryProfileDatabaseFixtureMixin:
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


def create_atom_model(
    atom_id: str,
    *,
    user_id: str = "u1",
    atom_type: str = "preference",
    content: str = "u1 喜欢爵士乐",
    weight: float = 0.8,
    confidence: float = 0.8,
    status: str = "active",
) -> None:
    now = datetime.datetime.now()
    MemoryAtomModel.create(
        atom_id=atom_id,
        atom_type=atom_type,
        content=content,
        entities=f'["{user_id}", "爵士乐"]',
        importance=0.8,
        confidence=confidence,
        weight=weight,
        created_at=now,
        last_accessed_at=now,
        last_reinforced_at=now,
        ttl_days=180,
        decay_type="exponential",
        reinforcement_count=0,
        source_scene="group_chat",
        privacy_level="context_sensitive",
        status=status,
    )


def create_semantic_detail(
    atom_id: str,
    *,
    category: str,
    name: str,
    value: str,
    evidence_counter: int = 1,
) -> None:
    SemanticDetailModel.create(
        id=atom_id,
        atom=atom_id,
        attr_category=category,
        attr_name=name,
        attr_value=value,
        evidence_list='["msg-1"]',
        evidence_counter=evidence_counter,
    )


def make_memory_atom(
    atom_id: str,
    *,
    atom_type: AtomType = AtomType.PREFERENCE,
    semantic_detail: SemanticDetail | None = None,
    episodic_detail: EpisodicDetail | None = None,
) -> MemoryAtom:
    return MemoryAtom(
        atom_id=atom_id,
        atom_type=atom_type,
        content="u1 说自己喜欢 lofi",
        entities=["u1"],
        importance=0.8,
        confidence=0.75,
        weight=0.6,
        created_at=0.0,
        last_accessed_at=0.0,
        ttl_days=180,
        semantic_detail=semantic_detail,
        episodic_detail=episodic_detail,
    )


class ProfileStoreTest(MemoryProfileDatabaseFixtureMixin, unittest.TestCase):
    def test_safe_json_entity_keyword_helpers_and_profile_store_roundtrip(self) -> None:
        self.assertEqual(_safe_json_loads(None, dict), {})
        self.assertEqual(_safe_json_loads("not-json", list), [])
        self.assertTrue(_entities_contain_user('["u1", "u2"]', "u1"))
        self.assertTrue(_entities_contain_user("u1,broken-json", "u1"))
        self.assertTrue(_entities_contain_user(["u1"], "u1"))
        self.assertFalse(_entities_contain_user(123, "u1"))
        self.assertTrue(_matches_keywords("music preference", {"preference"}))

        store = ProfileStore()
        extracted_at = datetime.datetime.now()
        store.save_profile(
            UserProfile(
                user_id="u1",
                traits={"耐心": 0.8},
                interests=["jazz"],
                preferences={"music": "jazz"},
                facts={"city": "Shanghai"},
                stats={"message_count": 5},
                mood_history=[
                    {
                        "timestamp": extracted_at.isoformat(),
                        "sensory_tags": ["visual"],
                        "emotion_tags": ["calm"],
                        "content": "片段",
                    }
                ],
                expression_style="short",
                expression_patterns={"ending": ["呢"]},
                impression="已有画像",
                last_extracted_at=extracted_at,
            )
        )

        loaded = store.get_profile("u1")

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.preferences, {"music": "jazz"})
        self.assertEqual(loaded.expression_style, "short")
        self.assertEqual(loaded.expression_patterns, {"ending": ["呢"]})
        self.assertEqual(loaded.stats, {"message_count": 5})
        self.assertTrue(store.profile_exists("u1"))
        self.assertEqual(store.list_profiles(), ["u1"])
        store.delete_profile("u1")
        self.assertFalse(store.profile_exists("u1"))


class ProfileBuilderTest(MemoryProfileDatabaseFixtureMixin, unittest.TestCase):
    def test_build_profile_filters_user_entities_and_aggregates_preference_fact_and_traits(self) -> None:
        create_atom_model("pref-u1", user_id="u1", atom_type="preference", confidence=0.8)
        create_semantic_detail("pref-u1", category="preference", name="music", value="jazz", evidence_counter=2)
        create_atom_model("fact-u1", user_id="u1", atom_type="factual", content="u1 性格耐心", confidence=0.7)
        create_semantic_detail("fact-u1", category="fact", name="personality", value="耐心", evidence_counter=1)
        create_atom_model("ignored-other", user_id="u2", atom_type="preference")
        create_semantic_detail("ignored-other", category="preference", name="food", value="noodles", evidence_counter=2)
        create_atom_model("ignored-evidence", user_id="u1", atom_type="preference")
        create_semantic_detail(
            "ignored-evidence",
            category="preference",
            name="drink",
            value="tea",
            evidence_counter=0,
        )

        store = ProfileStore()
        profile = ProfileBuilder(store).build_profile("u1")
        loaded = store.get_profile("u1")

        self.assertEqual(profile.preferences, {"music": "jazz"})
        self.assertEqual(profile.interests, ["jazz"])
        self.assertEqual(profile.facts, {"personality": "耐心"})
        self.assertEqual(profile.traits, {"耐心": 0.7})
        self.assertIn("偏好：music=jazz", profile.impression)
        self.assertIsNotNone(profile.last_extracted_at)
        self.assertEqual(loaded.preferences, profile.preferences)

    def test_build_profile_saves_collecting_impression_when_no_matching_atoms_exist(self) -> None:
        store = ProfileStore()

        profile = ProfileBuilder(store).build_profile("missing-user")

        self.assertEqual(profile.impression, "用户 missing-user 的画像正在收集中")
        self.assertTrue(store.profile_exists("missing-user"))

    def test_update_profile_from_atom_handles_semantic_and_episodic_incremental_updates(self) -> None:
        store = ProfileStore()
        builder = ProfileBuilder(store)
        semantic = SemanticDetail(
            atom_id="atom-pref",
            attr_category="interest",
            attr_name="music",
            attr_value="lofi",
        )
        episodic = EpisodicDetail(
            atom_id="atom-pref",
            sensory_tags=["auditory"],
            emotion_tags=["calm"],
            temporal_context="夜晚",
        )

        updated = builder.update_profile_from_atom(
            "u1",
            make_memory_atom("atom-pref", semantic_detail=semantic, episodic_detail=episodic),
        )
        fact_updated = builder.update_profile_from_atom(
            "u1",
            make_memory_atom(
                "atom-fact",
                atom_type=AtomType.FACTUAL,
                semantic_detail=SemanticDetail(
                    atom_id="atom-fact",
                    attr_category="profile",
                    attr_name="personality",
                    attr_value="温和",
                ),
            ),
        )
        unchanged = builder.update_profile_from_atom("u1", make_memory_atom("atom-empty"))

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.preferences, {"music": "lofi"})
        self.assertEqual(updated.interests, ["lofi"])
        self.assertEqual(updated.mood_history[0]["sensory_tags"], ["auditory"])
        self.assertIsNotNone(fact_updated)
        assert fact_updated is not None
        self.assertEqual(fact_updated.facts["personality"], "温和")
        self.assertEqual(fact_updated.traits["温和"], 0.75)
        self.assertIsNone(unchanged)


class ProfileRetrieverTest(MemoryProfileDatabaseFixtureMixin, unittest.TestCase):
    def test_profile_retriever_formats_context_summary_and_missing_profiles(self) -> None:
        store = ProfileStore()
        store.save_profile(
            UserProfile(
                user_id="u1",
                traits={"耐心": 0.8},
                interests=["jazz", "lofi"],
                preferences={"music": "jazz"},
                facts={"city": "Shanghai"},
                stats={"message_count": 5, "_private": "hidden"},
                impression="性格温和，喜欢音乐",
            )
        )
        retriever = ProfileRetriever(store)

        context = retriever.get_profile_context("u1", max_chars=500)
        summary = retriever.get_profile_summary("u1", max_chars=12)

        self.assertIn("【用户画像 - u1】", context)
        self.assertIn("特征: 耐心(80.0%)", context)
        self.assertIn("偏好: music: jazz", context)
        self.assertIn("统计: message_count: 5", context)
        self.assertNotIn("_private", context)
        self.assertEqual(summary, "【u1】性格温和，")
        self.assertEqual(retriever.get_profile_context("missing"), "")
        self.assertEqual(retriever.get_profile_summary("missing"), "")


if __name__ == "__main__":
    unittest.main()
