import datetime
import tempfile
import unittest
from pathlib import Path

from src.memory.atom import AtomType, EpisodicDetail, MemoryAtom, SemanticDetail
from src.memory.expression_bridge import ExpressionBridge
from src.memory.schema import (
    MemoryAtom as MemoryAtomModel,
    RawMessageArchive,
    SemanticDetail as SemanticDetailModel,
    configure_memory_database,
    initialize_database,
    memory_db,
)
from src.memory.user_profile import (
    PersonIdentity,
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
    evidence_list: str = '["msg-1"]',
    subject_key: str | None = None,
) -> None:
    fields = {
        "id": atom_id,
        "atom": atom_id,
        "attr_category": category,
        "attr_name": name,
        "attr_value": value,
        "evidence_list": evidence_list,
        "evidence_counter": evidence_counter,
    }
    if subject_key is not None:
        fields["subject_key"] = subject_key
    SemanticDetailModel.create(
        **fields,
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
    def test_person_identity_merges_latest_nonempty_display_metadata(self) -> None:
        original = PersonIdentity(
            platform="qq",
            user_id="42",
            nickname="旧昵称",
            cardname="旧群名片",
            group_id="group-1",
            group_name="旧群名",
        )
        latest = PersonIdentity(
            platform="qq",
            user_id="42",
            nickname="新昵称",
            group_id="group-1",
            group_name="新群名",
        )

        merged = original.merged_with(latest)

        self.assertEqual(merged.nickname, "新昵称")
        self.assertEqual(merged.cardname, "旧群名片")
        self.assertEqual(merged.group_name, "新群名")
        self.assertEqual(merged.profile_id, "qq:42")

    def test_verified_platform_identities_are_isolated_and_refresh_display_metadata(self) -> None:
        store = ProfileStore()
        qq_identity = PersonIdentity(
            platform="qq",
            user_id="42",
            nickname="Alice",
            cardname="群名片 A",
            group_id="group-1",
            group_name="测试群",
        )
        discord_identity = PersonIdentity(
            platform="discord",
            user_id="42",
            nickname="Alice D",
        )

        qq_profile = store.get_or_create_profile(qq_identity)
        discord_profile = store.get_or_create_profile(discord_identity)
        store.get_or_create_profile(
            PersonIdentity(
                platform="qq",
                user_id="42",
                nickname="Alice 新昵称",
                cardname="群名片 B",
                group_id="group-2",
                group_name="另一个群",
            )
        )

        refreshed_qq = store.get_profile("42", platform="qq")
        refreshed_discord = store.get_profile("42", platform="discord")

        self.assertEqual(qq_profile.profile_id, "qq:42")
        self.assertEqual(discord_profile.profile_id, "discord:42")
        self.assertIsNotNone(refreshed_qq)
        self.assertIsNotNone(refreshed_discord)
        assert refreshed_qq is not None
        assert refreshed_discord is not None
        self.assertEqual(refreshed_qq.nickname, "Alice 新昵称")
        self.assertEqual(refreshed_discord.nickname, "Alice D")
        self.assertEqual(
            refreshed_qq.group_nicknames,
            [
                {
                    "platform": "qq",
                    "group_id": "group-1",
                    "group_name": "测试群",
                    "group_nick_name": "群名片 A",
                },
                {
                    "platform": "qq",
                    "group_id": "group-2",
                    "group_name": "另一个群",
                    "group_nick_name": "群名片 B",
                },
            ],
        )
        self.assertEqual(refreshed_qq.person_type, "person")
        self.assertEqual(refreshed_qq.identity_source, "message_sender")
        self.assertEqual(refreshed_qq.verification_status, "verified")
        self.assertEqual(set(store.list_profiles()), {"qq:42", "discord:42"})

    def test_legacy_entity_profile_is_migrated_as_unverified_and_excluded_from_people(self) -> None:
        now = datetime.datetime.now()
        memory_db.execute_sql(
            """
            CREATE TABLE user_profiles (
                user_id VARCHAR(128) PRIMARY KEY,
                version INTEGER NOT NULL DEFAULT 1,
                traits_json TEXT NOT NULL,
                interests_json TEXT NOT NULL,
                preferences_json TEXT NOT NULL,
                facts_json TEXT NOT NULL,
                stats_json TEXT NOT NULL,
                mood_history_json TEXT NOT NULL DEFAULT '[]',
                impression TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                last_extracted_at DATETIME
            )
            """
        )
        memory_db.execute_sql(
            """
            INSERT INTO user_profiles (
                user_id, version, traits_json, interests_json, preferences_json,
                facts_json, stats_json, mood_history_json, impression, created_at, updated_at
            ) VALUES (?, 1, '{}', '[]', '{}', '{}', '{}', '[]', ?, ?, ?)
            """,
            ("梦幻游戏", "遗留脏画像", now, now),
        )

        store = ProfileStore()
        legacy = store.get_profile("梦幻游戏")

        self.assertIsNotNone(legacy)
        assert legacy is not None
        self.assertEqual(legacy.person_type, "unknown")
        self.assertEqual(legacy.identity_source, "legacy_entity")
        self.assertEqual(legacy.verification_status, "unverified")
        self.assertEqual(store.list_profiles(), [])
        self.assertEqual(store.list_profiles(include_non_people=True), ["梦幻游戏"])

    def test_trusted_identity_claims_legacy_profile_and_backfills_semantic_subject(self) -> None:
        store = ProfileStore()
        store.save_profile(
            UserProfile(
                user_id="legacy-user",
                person_type="unknown",
                identity_source="legacy_entity",
                verification_status="unverified",
            )
        )
        create_atom_model("legacy-fact", user_id="legacy-user", atom_type="factual")
        create_semantic_detail(
            "legacy-fact",
            category="fact",
            name="city",
            value="上海",
        )

        profile = store.get_or_create_profile(PersonIdentity(platform="qq", user_id="legacy-user", nickname="小明"))

        self.assertEqual(profile.profile_id, "qq:legacy-user")
        self.assertEqual(store.get_profile("legacy-user").profile_id, "qq:legacy-user")
        detail = SemanticDetailModel.get_by_id("legacy-fact")
        self.assertEqual(detail.subject_key, "qq:legacy-user")

    def test_existing_modern_profile_also_claims_unscoped_historical_semantic_details(self) -> None:
        store = ProfileStore()
        identity = PersonIdentity(platform="qq", user_id="late-user", nickname="小明")
        store.get_or_create_profile(identity)
        create_atom_model("late-fact", user_id="late-user", atom_type="factual")
        create_semantic_detail("late-fact", category="fact", name="city", value="上海")

        store.get_or_create_profile(identity)

        detail = SemanticDetailModel.get_by_id("late-fact")
        self.assertEqual(detail.subject_key, "qq:late-user")

    def test_expression_bridge_persists_into_real_profile_and_retriever_context(self) -> None:
        store = ProfileStore()
        identity = PersonIdentity(platform="qq", user_id="expression-user", nickname="表达用户")
        store.get_or_create_profile(identity)
        bridge = ExpressionBridge(store)

        bridge.update_expression_profile(identity, ["好耶😀", "好耶😀", "好耶✨", "收到", "真的吗？"])

        loaded = store.get_profile("expression-user", platform="qq")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertTrue(loaded.expression_style)
        self.assertEqual(loaded.expression_patterns.get("favorite_expressions"), ["好耶"])
        context = ProfileRetriever(store).get_profile_context("expression-user", platform="qq")
        self.assertIn("表达风格:", context)

    def test_expression_bridge_uses_recent_messages_from_the_same_platform(self) -> None:
        store = ProfileStore()
        identity = PersonIdentity(platform="qq", user_id="shared-id", nickname="表达用户")
        store.get_or_create_profile(identity)
        now = datetime.datetime.now().timestamp()
        for index in range(3):
            RawMessageArchive.create(
                stream_id="qq-stream",
                message_id=f"qq-{index}",
                user_id=identity.user_id,
                platform="qq",
                content="好耶😀",
                timestamp=now + index,
                chat_type="group",
            )
        for index in range(6):
            RawMessageArchive.create(
                stream_id="discord-stream",
                message_id=f"discord-{index}",
                user_id=identity.user_id,
                platform="discord",
                content="不应混入？？？",
                timestamp=now + 10 + index,
                chat_type="group",
            )

        ExpressionBridge(store).update_expression_profile(identity, ["好耶😀"])

        loaded = store.get_profile(identity.profile_id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.expression_patterns["analyzed_message_count"], 3)
        self.assertEqual(loaded.expression_patterns["favorite_expressions"], ["好耶"])
        self.assertEqual(loaded.expression_patterns["question_message_ratio"], 0.0)

    def test_profile_store_hides_only_legacy_generated_expression_analysis(self) -> None:
        store = ProfileStore()
        store.save_profile(
            UserProfile(
                user_id="legacy-expression",
                expression_style="阴阳怪气",
                expression_patterns={
                    "favorite_expressions": ["跨消"],
                    "avg_message_length": 3.0,
                    "emoji_ratio": 0.0,
                    "question_ratio": 0.5,
                    "analyzed_message_count": 2,
                    "updated_at": 1.0,
                },
            )
        )
        store.save_profile(
            UserProfile(
                user_id="custom-expression",
                expression_style="短句",
                expression_patterns={"ending": ["呢"]},
            )
        )

        legacy = store.get_profile("legacy-expression")
        custom = store.get_profile("custom-expression")

        self.assertIsNotNone(legacy)
        self.assertIsNotNone(custom)
        assert legacy is not None and custom is not None
        self.assertEqual(legacy.expression_style, "")
        self.assertEqual(legacy.expression_patterns, {})
        self.assertEqual(custom.expression_style, "短句")
        self.assertEqual(custom.expression_patterns, {"ending": ["呢"]})

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
    def test_build_profile_honors_prompt_categories_evidence_and_highest_weight_value(self) -> None:
        identity = PersonIdentity(platform="qq", user_id="u1", nickname="小明")
        create_atom_model("pref-high", weight=0.9, confidence=0.9)
        create_semantic_detail(
            "pref-high",
            category="preference",
            name="梦幻游戏",
            value="喜欢",
            subject_key=identity.profile_id,
        )
        create_atom_model("pref-low", weight=0.1, confidence=0.95)
        create_semantic_detail(
            "pref-low",
            category="preference",
            name="梦幻游戏",
            value="不喜欢",
            subject_key=identity.profile_id,
        )
        for atom_id, category, name, value in (
            ("personality", "personality", "性格", "耐心"),
            ("habit", "habit", "作息", "早睡"),
            ("skill", "skill", "技能", "Python"),
        ):
            create_atom_model(atom_id, atom_type="factual", confidence=0.8)
            create_semantic_detail(
                atom_id,
                category=category,
                name=name,
                value=value,
                evidence_counter=0,
                evidence_list='["msg-1"]',
                subject_key=identity.profile_id,
            )

        profile = ProfileBuilder(ProfileStore()).build_profile(identity)

        self.assertEqual(profile.preferences, {"梦幻游戏": "喜欢"})
        self.assertEqual(profile.interests, ["梦幻游戏"])
        self.assertEqual(profile.facts, {"作息": "早睡", "技能": "Python"})
        self.assertEqual(profile.traits, {"耐心": 0.8})
        self.assertEqual(SemanticDetail(atom_id="new-detail").evidence_counter, 1)

    def test_build_profile_filters_subject_before_limit_and_separates_same_id_across_platforms(self) -> None:
        now = datetime.datetime.now()
        other_atoms = [
            {
                "atom_id": f"other-{index}",
                "atom_type": "preference",
                "content": "其他用户喜欢别的内容",
                "entities": '["other-user"]',
                "importance": 0.9,
                "confidence": 0.9,
                "weight": 0.9,
                "created_at": now,
                "last_accessed_at": now,
                "last_reinforced_at": now,
                "ttl_days": 180,
                "decay_type": "exponential",
                "reinforcement_count": 0,
                "source_scene": "group_chat",
                "privacy_level": "context_sensitive",
                "status": "active",
            }
            for index in range(500)
        ]
        with memory_db.atomic():
            MemoryAtomModel.insert_many(other_atoms).execute()

        qq_identity = PersonIdentity(platform="qq", user_id="42", nickname="QQ 用户")
        discord_identity = PersonIdentity(platform="discord", user_id="42", nickname="Discord 用户")
        create_atom_model("qq-tail", user_id="42", weight=0.1)
        create_semantic_detail(
            "qq-tail",
            category="interest",
            name="游戏",
            value="梦幻游戏",
            subject_key=qq_identity.profile_id,
        )
        create_atom_model("discord-tail", user_id="42", weight=0.05)
        create_semantic_detail(
            "discord-tail",
            category="interest",
            name="音乐",
            value="爵士乐",
            subject_key=discord_identity.profile_id,
        )

        builder = ProfileBuilder(ProfileStore())
        qq_profile = builder.build_profile(qq_identity)
        discord_profile = builder.build_profile(discord_identity)

        self.assertEqual(qq_profile.interests, ["梦幻游戏"])
        self.assertEqual(qq_profile.preferences, {})
        self.assertEqual(discord_profile.interests, ["爵士乐"])
        self.assertEqual(discord_profile.preferences, {})

    def test_build_profile_keeps_interest_personality_and_general_fact_dimensions_distinct(self) -> None:
        identity = PersonIdentity(platform="qq", user_id="dimension-user", nickname="维度用户")
        for atom_id, category, name, value, confidence in (
            ("interest", "interest", "音乐", "爵士乐", 0.8),
            ("personality", "personality", "性格", "耐心", 0.7),
            ("general", "general", "城市", "上海", 0.9),
        ):
            create_atom_model(atom_id, user_id=identity.user_id, atom_type="factual", confidence=confidence)
            create_semantic_detail(
                atom_id,
                category=category,
                name=name,
                value=value,
                subject_key=identity.profile_id,
            )

        profile = ProfileBuilder(ProfileStore()).build_profile(identity)

        self.assertEqual(profile.interests, ["爵士乐"])
        self.assertEqual(profile.traits, {"耐心": 0.7})
        self.assertEqual(profile.preferences, {})
        self.assertEqual(profile.facts, {"城市": "上海"})

    def test_incremental_update_does_not_let_low_weight_value_replace_legacy_high_weight_value(self) -> None:
        identity = PersonIdentity(platform="qq", user_id="u1", nickname="小明")
        store = ProfileStore()
        store.save_profile(
            UserProfile(
                user_id="u1",
                platform="qq",
                preferences={"music": "jazz"},
                person_type="person",
                verification_status="verified",
            )
        )
        create_atom_model("existing-high", user_id="u1", weight=0.95, confidence=0.9)
        create_semantic_detail(
            "existing-high",
            category="preference",
            name="music",
            value="jazz",
            subject_key=identity.profile_id,
        )

        updated = ProfileBuilder(store).update_profile_from_atom(
            identity,
            make_memory_atom(
                "incoming-low",
                semantic_detail=SemanticDetail(
                    atom_id="incoming-low",
                    attr_category="preference",
                    attr_name="music",
                    attr_value="rock",
                    subject_key=identity.profile_id,
                    evidence_counter=1,
                ),
            ),
        )

        self.assertIsNone(updated)
        persisted = store.get_profile(identity.profile_id)
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted.preferences["music"], "jazz")

    def test_incremental_update_preserves_dimensions_supported_by_other_sources(self) -> None:
        for atom_id, category, name, value, confidence in (
            ("music", "preference", "music", "jazz", 0.7),
            ("playlist", "preference", "playlist", "jazz", 0.8),
            ("temperament", "personality", "性格", "耐心", 0.9),
            ("character", "personality", "个性", "耐心", 0.6),
        ):
            create_atom_model(atom_id, weight=0.2, confidence=confidence)
            create_semantic_detail(atom_id, category=category, name=name, value=value)

        store = ProfileStore()
        builder = ProfileBuilder(store)
        profile = builder.build_profile("u1")
        self.assertEqual(profile.interests, ["jazz"])
        self.assertEqual(profile.traits, {"耐心": 0.9})

        builder.update_profile_from_atom(
            "u1",
            make_memory_atom(
                "music-new",
                semantic_detail=SemanticDetail(
                    atom_id="music-new",
                    attr_category="preference",
                    attr_name="music",
                    attr_value="rock",
                ),
            ),
        )
        updated = builder.update_profile_from_atom(
            "u1",
            make_memory_atom(
                "temperament-new",
                atom_type=AtomType.FACTUAL,
                semantic_detail=SemanticDetail(
                    atom_id="temperament-new",
                    attr_category="personality",
                    attr_name="性格",
                    attr_value="果断",
                ),
            ),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.interests, ["jazz", "rock"])
        self.assertEqual(updated.traits, {"耐心": 0.6, "果断": 0.75})

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
            evidence_list="[]",
        )

        store = ProfileStore()
        profile = ProfileBuilder(store).build_profile("u1")
        loaded = store.get_profile("u1")

        self.assertEqual(profile.preferences, {"music": "jazz"})
        self.assertEqual(profile.interests, ["jazz"])
        self.assertEqual(profile.facts, {})
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
        self.assertEqual(updated.preferences, {})
        self.assertEqual(updated.interests, ["lofi"])
        self.assertEqual(updated.mood_history[0]["sensory_tags"], ["auditory"])
        self.assertIsNotNone(fact_updated)
        assert fact_updated is not None
        self.assertNotIn("personality", fact_updated.facts)
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
