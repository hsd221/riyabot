"""用户画像系统 — 从记忆原子聚合用户偏好/属性/事实

基于记忆系统中的 PREFERENCE 和 FACTUAL 类型原子，
通过 SemanticDetail 扩展表提取结构化属性数据，
构建持久化的用户画像（UserProfile）。纯算法聚合，不涉及 LLM。

使用方式:
    from src.memory import ProfileStore, ProfileBuilder, ProfileRetriever, UserProfile

    store = ProfileStore()
    builder = ProfileBuilder(store)
    retriever = ProfileRetriever(store)

    # 全量构建
    profile = builder.build_profile("user_123")

    # 增量更新
    builder.update_profile_from_atom("user_123", atom)

    # LLM 上下文
    context = retriever.get_profile_context("user_123")
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from src.memory.types import MoodEntry

from peewee import (
    CharField,
    DateTimeField,
    IntegerField,
    Model,
    TextField,
)

from src.common.logger import get_logger
from src.memory.atom import MemoryAtom, AtomType

logger = get_logger("memory.profile")

# ---------------------------------------------------------------------------
# 分类关键词 — 用于将 SemanticDetail.attr_category 映射到 UserProfile 字段
# ---------------------------------------------------------------------------

_PREFERENCE_KEYWORDS = {"preference", "偏好", "兴趣", "like", "dislike", "hobby", "interest", "喜欢", "讨厌", "爱好"}
_FACT_KEYWORDS = {"fact", "profile", "属性", "factual", "attribute", "trait", "info", "事实", "资料"}

# ---------------------------------------------------------------------------
# UserProfile 数据模型
# ---------------------------------------------------------------------------


@dataclass
class UserProfile:
    """用户画像数据模型

    聚合记忆系统中的偏好和事实信息，形成用户的结构化画像。

    Attributes:
        user_id: 用户唯一标识
        version: 画像版本号，随字段结构变更递增
        traits: 人格特征，键=特征名，值=置信度 0-1
        interests: 兴趣/话题列表
        preferences: 显式偏好，键=类别（如 food/music），值=偏好描述
        facts: 事实属性，键=属性名（如 age/location），值=属性值
        stats: 行为统计数据，如 message_count, active_hours
        mood_history: 感官/情绪历史记录，每条含 sensory_tags, emotion_tags, timestamp, content
        impression: 自然语言印象总结
        created_at: 首次创建时间
        updated_at: 最后更新时间
        last_extracted_at: 最后从记忆原子提取的时间
    """

    user_id: str
    version: int = 1
    traits: dict[str, float] = field(default_factory=dict)
    interests: list[str] = field(default_factory=list)
    preferences: dict[str, str] = field(default_factory=dict)
    facts: dict[str, str] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    mood_history: list[MoodEntry] = field(default_factory=list)
    impression: str = ""
    expression_style: str = ""
    expression_patterns: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_extracted_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Peewee 数据库模型
# ---------------------------------------------------------------------------


class UserProfileModel(Model):
    """用户画像数据库模型 — 字典字段序列化为 JSON 文本存储"""

    user_id = CharField(primary_key=True, max_length=128)
    version = IntegerField(default=1)
    traits_json = TextField()
    interests_json = TextField()
    preferences_json = TextField()
    facts_json = TextField()
    stats_json = TextField()
    mood_history_json = TextField(default="[]")
    impression = TextField(default="")
    created_at = DateTimeField()
    updated_at = DateTimeField()
    last_extracted_at = DateTimeField(null=True)

    class Meta:
        database = None  # 由 ProfileStore 绑定时设置
        table_name = "user_profiles"


# ---------------------------------------------------------------------------
# ProfileStore — CRUD
# ---------------------------------------------------------------------------


class ProfileStore:
    """用户画像存储 — UserProfile 的 CRUD + 序列化

    管理 user_profiles 表，负责 dataclass ↔ DB 的转换。
    """

    def __init__(self):
        """初始化并绑定数据库，确保 user_profiles 表存在"""
        from src.memory.schema import memory_db as _memory_db

        self._memory_db = _memory_db
        # 绑定数据库
        UserProfileModel._meta.database = self._memory_db
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保 user_profiles 表已创建"""
        try:
            if not UserProfileModel.table_exists():
                UserProfileModel.create_table()
                logger.info("用户画像表 'user_profiles' 已创建")
        except Exception as e:
            logger.error(f"创建用户画像表失败: {e}")

    def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """从数据库加载用户画像

        Args:
            user_id: 用户 ID

        Returns:
            UserProfile 或 None（不存在时）
        """
        try:
            row = UserProfileModel.get_or_none(UserProfileModel.user_id == user_id)
            if row is None:
                return None

            stats = _safe_json_loads(row.stats_json, dict)

            return UserProfile(
                user_id=row.user_id,
                version=row.version,
                traits=_safe_json_loads(row.traits_json, dict),
                interests=_safe_json_loads(row.interests_json, list),
                preferences=_safe_json_loads(row.preferences_json, dict),
                facts=_safe_json_loads(row.facts_json, dict),
                stats=stats,
                expression_style=stats.pop("_expression_style", "") if isinstance(stats, dict) else "",
                expression_patterns=stats.pop("_expression_patterns", {}) if isinstance(stats, dict) else {},
                mood_history=_safe_json_loads(row.mood_history_json, list),
                impression=row.impression or "",
                created_at=row.created_at,
                updated_at=row.updated_at,
                last_extracted_at=row.last_extracted_at,
            )
        except Exception as e:
            logger.error(f"加载用户画像失败 ({user_id}): {e}")
            return None

    def save_profile(self, profile: UserProfile) -> None:
        """保存用户画像（upsert）

        Args:
            profile: UserProfile 实例
        """
        profile.updated_at = datetime.now()

        # 将 expression 字段嵌入 stats 字典持久化
        stats_for_save = dict(profile.stats) if profile.stats else {}
        if profile.expression_style:
            stats_for_save["_expression_style"] = profile.expression_style
        if profile.expression_patterns:
            stats_for_save["_expression_patterns"] = profile.expression_patterns

        try:
            with self._memory_db:
                UserProfileModel.replace(
                    user_id=profile.user_id,
                    version=profile.version,
                    traits_json=json.dumps(profile.traits, ensure_ascii=False),
                    interests_json=json.dumps(profile.interests, ensure_ascii=False),
                    preferences_json=json.dumps(profile.preferences, ensure_ascii=False),
                    facts_json=json.dumps(profile.facts, ensure_ascii=False),
                    stats_json=json.dumps(stats_for_save, default=str, ensure_ascii=False),
                    mood_history_json=json.dumps(profile.mood_history, ensure_ascii=False, default=str),
                    impression=profile.impression,
                    created_at=profile.created_at,
                    updated_at=profile.updated_at,
                    last_extracted_at=profile.last_extracted_at,
                ).execute()
            logger.debug("用户画像已保存", user_id=profile.user_id)
        except Exception as e:
            logger.error(f"保存用户画像失败 ({profile.user_id}): {e}")

    def profile_exists(self, user_id: str) -> bool:
        """检查用户画像是否存在

        Args:
            user_id: 用户 ID

        Returns:
            是否存在
        """
        return UserProfileModel.select().where(UserProfileModel.user_id == user_id).exists()

    def list_profiles(self) -> list[str]:
        """列出所有存在画像的用户 ID

        Returns:
            用户 ID 列表，按 updated_at 降序
        """
        try:
            query = UserProfileModel.select(UserProfileModel.user_id).order_by(UserProfileModel.updated_at.desc())
            return [row.user_id for row in query]
        except Exception as e:
            logger.error(f"列出用户画像失败: {e}")
            return []

    def delete_profile(self, user_id: str) -> None:
        """删除用户画像

        Args:
            user_id: 用户 ID
        """
        try:
            with self._memory_db:
                UserProfileModel.delete().where(UserProfileModel.user_id == user_id).execute()
            logger.info(f"用户画像已删除: {user_id}")
        except Exception as e:
            logger.error(f"删除用户画像失败 ({user_id}): {e}")


# ---------------------------------------------------------------------------
# ProfileBuilder — 从记忆原子聚合
# ---------------------------------------------------------------------------


class ProfileBuilder:
    """用户画像构建器 — 从 PREFERENCE / FACTUAL 类型记忆原子聚合用户画像

    扫描用户的偏好和事实记忆原子，提取 SemanticDetail 中的结构化数据，
    合并到 UserProfile 中。纯算法聚合，不涉及 LLM。

    Args:
        profile_store: ProfileStore 实例，用于持久化画像
    """

    def __init__(self, profile_store: ProfileStore):
        self.profile_store = profile_store

    def build_profile(self, user_id: str) -> UserProfile:
        """全量构建用户画像

        查询该用户的所有 PREFERENCE 和 FACTUAL 类型原子，
        提取 SemanticDetail 结构化数据，聚合为 UserProfile。

        Args:
            user_id: 用户 ID

        Returns:
            构建完成的 UserProfile（已自动保存到 ProfileStore）
        """
        from src.memory.schema import MemoryAtom as MemoryAtomModel
        from src.memory.schema import SemanticDetail as SemanticDetailModel

        profile = UserProfile(user_id=user_id)
        semantic_data: list[dict[str, Any]] = []

        try:
            # Step 1: 查询所有 active 的 PREFERENCE + FACTUAL 原子
            with self.profile_store._memory_db:
                atom_rows = list(
                    MemoryAtomModel.select()
                    .where(
                        MemoryAtomModel.status == "active",
                        MemoryAtomModel.atom_type.in_(
                            [
                                AtomType.PREFERENCE.value,
                                AtomType.FACTUAL.value,
                            ]
                        ),
                    )
                    .order_by(MemoryAtomModel.weight.desc())
                    .limit(500)
                )

                if not atom_rows:
                    logger.debug(f"无可用记忆原子用于构建画像: {user_id}")
                    profile.impression = f"用户 {user_id} 的画像正在收集中"
                    self.profile_store.save_profile(profile)
                    return profile

                # Step 2: 批量加载 SemanticDetail
                atom_ids = [a.atom_id for a in atom_rows]
                detail_rows = list(SemanticDetailModel.select().where(SemanticDetailModel.atom.in_(atom_ids)))
                details_by_atom: dict[str, Any] = {d.atom: d for d in detail_rows}

            # Step 3: 过滤包含该用户的原子，提取语义数据
            for atom in atom_rows:
                # 检查 entities 中是否包含该用户
                if not _entities_contain_user(atom.entities, user_id):
                    continue

                detail = details_by_atom.get(atom.atom_id)
                if detail is None:
                    continue

                semantic_data.append(
                    {
                        "atom_id": atom.atom_id,
                        "atom_type": atom.atom_type,
                        "content": atom.content,
                        "weight": atom.weight,
                        "confidence": atom.confidence,
                        "attr_category": detail.attr_category or "",
                        "attr_name": detail.attr_name or "",
                        "attr_value": detail.attr_value or "",
                        "evidence_counter": detail.evidence_counter or 0,
                    }
                )

            # Step 4: 聚合数据到 UserProfile 字段
            self._aggregate_into_profile(profile, semantic_data)

            # Step 5: 构建印象
            profile.impression = self._build_impression(profile)
            profile.last_extracted_at = datetime.now()

            # Step 6: 保存
            self.profile_store.save_profile(profile)

            logger.info(
                "用户画像构建完成",
                user_id=user_id,
                traits=len(profile.traits),
                interests=len(profile.interests),
                preferences=len(profile.preferences),
                facts=len(profile.facts),
            )

        except Exception as e:
            logger.error(f"构建用户画像失败 ({user_id}): {e}")
            profile.impression = f"用户 {user_id} 的画像构建失败"

        return profile

    def update_profile_from_atom(self, user_id: str, atom: MemoryAtom) -> Optional[UserProfile]:
        """增量更新用户画像 — 从单条记忆原子提取数据

        当新写入 PREFERENCE 或 FACTUAL 原子时更新偏好/事实/特征，
        当原子附带情景扩展详情时同步更新 mood_history。

        Args:
            user_id: 用户 ID
            atom: 新的记忆原子（可附带 episodic_detail 或 semantic_detail）

        Returns:
            更新后的 UserProfile，无有效数据时返回 None
        """
        profile = self.profile_store.get_profile(user_id)
        if profile is None:
            profile = UserProfile(user_id=user_id)

        updated = False

        # 1. 处理 PREFERENCE / FACTUAL 语义数据
        if atom.atom_type in (AtomType.PREFERENCE, AtomType.FACTUAL) and atom.semantic_detail is not None:
            sd = atom.semantic_detail
            if sd.attr_category and sd.attr_name:
                cat_lower = sd.attr_category.lower()
                if _matches_keywords(cat_lower, _PREFERENCE_KEYWORDS):
                    profile.preferences[sd.attr_name] = sd.attr_value
                    if sd.attr_name not in ("like", "dislike", "喜欢", "讨厌"):
                        val = sd.attr_value.strip()
                        if val and val not in profile.interests:
                            profile.interests.append(val)
                    updated = True
                elif _matches_keywords(cat_lower, _FACT_KEYWORDS):
                    profile.facts[sd.attr_name] = sd.attr_value
                    if sd.attr_name in ("personality", "性格", "trait", "character", "个性"):
                        profile.traits[sd.attr_value] = max(
                            profile.traits.get(sd.attr_value, 0.0),
                            atom.confidence,
                        )
                    updated = True

        # 2. 处理感官/情绪数据 → mood_history（任意原子类型）
        if atom.episodic_detail is not None and (
            atom.episodic_detail.sensory_tags or atom.episodic_detail.emotion_tags
        ):
            detail = atom.episodic_detail
            profile.mood_history.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "sensory_tags": list(detail.sensory_tags),
                    "emotion_tags": list(detail.emotion_tags),
                    "temporal_context": detail.temporal_context,
                    "content": atom.content[:120],
                }
            )
            if len(profile.mood_history) > 200:
                profile.mood_history = profile.mood_history[-200:]
            updated = True

        if not updated:
            return None

        # 更新印象和时间戳
        profile.impression = self._build_impression(profile)
        profile.updated_at = datetime.now()
        profile.last_extracted_at = datetime.now()

        self.profile_store.save_profile(profile)

        logger.debug(
            "增量更新用户画像",
            user_id=user_id,
        )

        return profile

    # ── 内部: 数据聚合 ───────────────────────────────────────

    def _aggregate_into_profile(
        self,
        profile: UserProfile,
        semantic_data: list[dict[str, Any]],
    ) -> None:
        """将语义数据聚合到 UserProfile 各字段中

        Args:
            profile: 目标 UserProfile
            semantic_data: 语义数据列表（含 attr_category/name/value/evidence_counter）
        """
        for item in semantic_data:
            cat = item.get("attr_category", "").lower()
            name = item.get("attr_name", "")
            value = item.get("attr_value", "")
            evidence = item.get("evidence_counter", 0)
            confidence = item.get("confidence", 0.5)

            if not name or not cat:
                continue

            if _matches_keywords(cat, _PREFERENCE_KEYWORDS) and evidence >= 1:
                profile.preferences[name] = value
                if name not in ("like", "dislike", "喜欢", "讨厌"):
                    val = value.strip()
                    if val and val not in profile.interests:
                        profile.interests.append(val)

            elif _matches_keywords(cat, _FACT_KEYWORDS) and evidence >= 1:
                profile.facts[name] = value
                if name in ("personality", "性格", "trait", "character", "个性"):
                    profile.traits[value] = max(
                        profile.traits.get(value, 0.0),
                        confidence,
                    )

    def _build_impression(self, profile: UserProfile) -> str:
        """从画像数据构建自然语言印象

        Args:
            profile: UserProfile

        Returns:
            印象字符串
        """
        parts = []

        if profile.traits:
            top_traits = sorted(profile.traits.items(), key=lambda x: -x[1])[:3]
            trait_str = "、".join(t[0] for t in top_traits)
            parts.append(f"性格特征：{trait_str}")

        if profile.interests:
            interest_str = "、".join(profile.interests[:5])
            parts.append(f"兴趣：{interest_str}")

        if profile.preferences:
            pref_items = [f"{k}={v}" for k, v in list(profile.preferences.items())[:5]]
            parts.append(f"偏好：{'；'.join(pref_items)}")

        if profile.facts:
            fact_items = [f"{k}={v}" for k, v in list(profile.facts.items())[:5]]
            parts.append(f"属性：{'；'.join(fact_items)}")

        msg_count = profile.stats.get("message_count", 0) if profile.stats else 0
        if msg_count:
            parts.append(f"活跃度：{msg_count}条消息")

        return "；".join(parts) if parts else f"用户 {profile.user_id} 的画像正在收集中"


# ---------------------------------------------------------------------------
# ProfileRetriever — LLM 上下文格式化
# ---------------------------------------------------------------------------


class ProfileRetriever:
    """用户画像检索器 — 将 UserProfile 格式化为 LLM 可用的上下文文本

    用于在回复生成时注入用户画像信息，帮助 LLM 做出个性化响应。
    """

    def __init__(self, profile_store: ProfileStore):
        self.profile_store = profile_store

    def get_profile_context(self, user_id: str, max_chars: int = 800) -> str:
        """获取格式化的用户画像上下文（用于 LLM prompt）

        格式:
            【用户画像 - {user_id}】
            印象: {impression}
            特征: {traits}
            偏好: {preferences}
            ...

        Args:
            user_id: 用户 ID
            max_chars: 最大字符数

        Returns:
            格式化文本，画像不存在时返回空字符串
        """
        profile = self.profile_store.get_profile(user_id)
        if profile is None:
            return ""

        lines = [f"【用户画像 - {user_id}】"]

        if profile.impression:
            lines.append(f"印象: {profile.impression}")

        if profile.traits:
            traits_str = "、".join(f"{k}({v:.1%})" for k, v in sorted(profile.traits.items(), key=lambda x: -x[1]))
            lines.append(f"特征: {traits_str}")

        if profile.preferences:
            pref_str = "；".join(f"{k}: {v}" for k, v in profile.preferences.items())
            lines.append(f"偏好: {pref_str}")

        if profile.facts:
            fact_str = "；".join(f"{k}: {v}" for k, v in profile.facts.items())
            lines.append(f"事实: {fact_str}")

        if profile.interests:
            lines.append(f"兴趣: {'、'.join(profile.interests)}")

        public_stats = {k: v for k, v in profile.stats.items() if not str(k).startswith("_")} if profile.stats else {}
        if public_stats:
            stats_str = "；".join(f"{k}: {v}" for k, v in public_stats.items())
            lines.append(f"统计: {stats_str}")

        result = "\n".join(lines)

        if len(result) > max_chars:
            result = result[:max_chars].rsplit("\n", 1)[0]

        return result

    def get_profile_summary(self, user_id: str, max_chars: int = 200) -> str:
        """获取精炼的用户画像摘要（用于密集 prompt）

        Args:
            user_id: 用户 ID
            max_chars: 最大字符数

        Returns:
            摘要文本，画像不存在时返回空字符串
        """
        profile = self.profile_store.get_profile(user_id)
        if profile is None:
            return ""

        summary = f"【{user_id}】"

        if profile.impression:
            remaining = max_chars - len(summary) - 3
            if remaining > 0:
                summary += profile.impression[:remaining]
        else:
            parts = []
            if profile.traits:
                top = sorted(profile.traits.items(), key=lambda x: -x[1])[:2]
                parts.append("特征:" + "、".join(t[0] for t in top))
            if profile.interests:
                parts.append("兴趣:" + "、".join(profile.interests[:3]))
            if profile.preferences:
                pref_sample = list(profile.preferences.keys())[:3]
                parts.append("偏好:" + "、".join(pref_sample))

            summary += " ".join(parts) if parts else "暂无画像数据"

        if len(summary) > max_chars:
            summary = summary[: max_chars - 3] + "..."

        return summary


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _safe_json_loads(text: Optional[str], default_type: type) -> Any:
    """安全解析 JSON 字符串，失败返回空容器

    Args:
        text: JSON 字符串或 None
        default_type: 失败时返回的类型（dict / list）

    Returns:
        解析后的数据或空容器
    """
    if not text:
        return default_type()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"JSON 解析失败，返回空 {default_type.__name__}")
        return default_type()


def _entities_contain_user(entities_raw: Any, user_id: str) -> bool:
    """检查记忆原子的 entities 字段是否包含指定用户

    Args:
        entities_raw: entities 原始值（JSON 字符串或 None）
        user_id: 目标用户 ID

    Returns:
        是否包含
    """
    if not entities_raw:
        return False
    if isinstance(entities_raw, str):
        try:
            entities = json.loads(entities_raw)
        except (json.JSONDecodeError, TypeError):
            return user_id in entities_raw
    elif isinstance(entities_raw, list):
        entities = entities_raw
    else:
        return False
    return user_id in entities


def _matches_keywords(text: str, keywords: set[str]) -> bool:
    """检查文本是否包含任一关键词

    Args:
        text: 待检文本（已小写化）
        keywords: 关键词集合

    Returns:
        是否匹配
    """
    return any(kw in text for kw in keywords)
