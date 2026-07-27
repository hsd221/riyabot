"""噪声回收引擎 — 从 NoisePool 中回收可能被误分类的潜在价值内容

周期性地扫描 NoisePool，对被客观性检查器判为"噪声"的内容进行二次评估。
通过关键词交叉引用和时间覆盖率验证，判断哪些噪声值得晋升为正式记忆。

工作流程:
    1. 查询候选噪声（retention_days 天内，高显著性优先，同时保留低显著性抽样名额）
    2. 对每条候选噪声提取关键词，与现有活跃原子做交叉引用计数
    3. 时间覆盖率验证：检查噪声中是否含时间语境词，以及对应时间段是否已被覆盖
    4. 若关键词匹配 >= 3 且时间验证通过，晋升为 EPISODIC 类型记忆原子；否则丢弃

Classes:
    InspirationEngine: 噪声回收引擎
"""

from __future__ import annotations

import datetime
import hashlib
import json
from functools import reduce
from typing import Any

from src.common.logger import get_logger
from src.memory.atom import MemoryAtom as MemoryAtomDC, AtomType
from src.memory.layer1_summarizer import extract_keywords
from src.memory.layer3_retrieval import MemoryWriter
from src.memory.schema import InsightPool, NoisePool, MemoryAtom as MemoryAtomModel, memory_db
from src.memory.store import MemoryStore

logger = get_logger("memory.inspiration")


class InspirationEngine:
    """噪声回收引擎 — 扫描 NoisePool 寻找被误分类的内容

    通过启发式规则（关键词交叉引用 + 时间覆盖率验证）判断噪声是否有晋升价值。
    晋升的原子类型为 EPISODIC，置信度设为 0.3（低置信度，因为是回收品），
    来源场景标记为 "dream"。

    Args:
        store: MemoryStore 实例，用于查询现有记忆原子
        writer: MemoryWriter 实例，用于将晋升的噪声写入为新的记忆原子
        retention_days: 扫描的噪声保留期限（默认 14 天）
            在月度周期中可设为 30 天以覆盖更大范围
    """

    # 关键词匹配阈值：噪声与 >= N 个现有原子共享关键词时才视为潜在信号
    KEYWORD_MATCH_MIN: int = 3
    # 兼容旧配置：候选不再按初始显著性过滤，低显著性片段也可能成为伏笔
    SIGNIFICANCE_MIN: float = 0.3
    # 每批最大候选数
    CANDIDATE_LIMIT: int = 100
    # 每批保留给低显著性/早期片段的偏差抽样名额
    LOW_SIGNAL_SAMPLE_LIMIT: int = 30
    # 晋升原子的置信度（来源为噪声，置信度偏低）
    PROMOTED_CONFIDENCE: float = 0.3
    # 伏笔洞见的最小相关活跃原子数
    FORESHADOW_MATCH_MIN: int = 2
    # 伏笔洞见的置信度（保守低置信，避免写成事实）
    FORESHADOW_CONFIDENCE: float = 0.45
    # 单条伏笔洞见最多保留多少来源原子
    FORESHADOW_SOURCE_LIMIT: int = 5

    def __init__(
        self,
        store: MemoryStore,
        writer: MemoryWriter,
        retention_days: int = 14,
    ):
        self._store = store
        self._writer = writer
        self._retention_days = retention_days

    async def recycle(self) -> dict[str, int]:
        """执行一次噪声回收周期

        Step 1 — 查询候选噪声
        Step 2 — 关键词交叉引用
        Step 3 — 时间覆盖率验证
        Step 4 — 晋升或丢弃

        Returns:
            {"promoted": N, "discarded": M}
        """
        # ── Step 1: 查询候选 ──
        candidates = self._query_candidates()
        if not candidates:
            logger.debug("噪声回收: 无候选噪声")
            return {"promoted": 0, "discarded": 0, "insights": 0}

        promoted = 0
        discarded = 0
        insights = 0

        for noise in candidates:
            content = noise.content
            significance = noise.significance

            # ── Step 2: 关键词交叉引用 ──
            keywords = extract_keywords(content, max_keywords=5)
            if not keywords:
                # 没有可提取的关键词 → 直接丢弃
                if self._delete_noise(noise.id):
                    discarded += 1
                continue

            matched_atoms = self._matched_keyword_atoms(keywords)
            match_count = len(matched_atoms)

            # 原始聊天只能作为待核验线索，不能绕过语义提取直接晋升为记忆原子。
            if self._is_raw_archive_candidate(noise):
                if match_count >= self.FORESHADOW_MATCH_MIN:
                    if self._write_foreshadowing_insight(noise, keywords, matched_atoms):
                        insights += 1
                elif self._delete_noise(noise.id):
                    discarded += 1
                continue

            # ── Step 3: 时间覆盖率验证 ──
            temporal_gap = self._has_temporal_gap(content)

            # ── Step 4: 晋升、生成伏笔洞见或丢弃 ──
            if match_count >= self.KEYWORD_MATCH_MIN and temporal_gap:
                if await self._promote(noise):
                    promoted += 1
                    logger.info(
                        "噪声回收: 晋升",
                        extra={
                            "noise_id": noise.id,
                            "content_preview": content[:60],
                            "significance": significance,
                            "keyword_matches": match_count,
                        },
                    )
            elif match_count >= self.FORESHADOW_MATCH_MIN:
                if self._write_foreshadowing_insight(noise, keywords, matched_atoms):
                    insights += 1
            elif self._delete_noise(noise.id):
                discarded += 1

        logger.info(
            "噪声回收: 完成",
            extra={
                "promoted": promoted,
                "discarded": discarded,
                "insights": insights,
                "total_candidates": len(candidates),
            },
        )
        return {"promoted": promoted, "discarded": discarded, "insights": insights}

    # ── 内部方法 ──────────────────────────────────────────────

    def _query_candidates(self) -> list[Any]:
        """查询候选噪声

        条件:
            - 创建时间在 retention_days 内
            - 高显著性优先
            - 保留一部分低显著性/较早片段，避免真正的伏笔被高分噪声队列挤掉

        Returns:
            NoisePool 模型实例列表
        """
        cutoff = datetime.datetime.now() - datetime.timedelta(days=self._retention_days)
        try:
            with memory_db:
                low_signal_limit = min(self.LOW_SIGNAL_SAMPLE_LIMIT, self.CANDIDATE_LIMIT)
                high_signal_limit = max(0, self.CANDIDATE_LIMIT - low_signal_limit)
                high_signal_rows = list(
                    NoisePool.select()
                    .where(NoisePool.created_at >= cutoff)
                    .order_by(NoisePool.significance.desc(), NoisePool.created_at.desc())
                    .limit(high_signal_limit)
                )
                low_signal_rows = list(
                    NoisePool.select()
                    .where(NoisePool.created_at >= cutoff)
                    .order_by(NoisePool.significance.asc(), NoisePool.created_at.asc())
                    .limit(low_signal_limit)
                )
                candidates: dict[int, Any] = {}
                for row in high_signal_rows + low_signal_rows:
                    candidates[int(row.id)] = row
                return list(candidates.values())[: self.CANDIDATE_LIMIT]
        except Exception as e:
            logger.error(f"噪声回收: 查询候选失败: {e}")
            return []

    def _count_keyword_matches(self, keywords: list[str]) -> int:
        """统计与现有活跃记忆原子共享关键词的原子数量

        对每个关键词使用 SQLite LIKE 查询 content.contains()，
        条件为任一关键词匹配（OR 语义）。
        返回至少匹配任一关键词的活跃原子数量。

        Args:
            keywords: 关键词列表

        Returns:
            匹配的活跃原子数量
        """
        if not keywords:
            return 0

        return len(self._matched_keyword_atoms(keywords))

    def _matched_keyword_atoms(self, keywords: list[str], limit: int | None = None) -> list[MemoryAtomModel]:
        """查询与关键词共享内容的活跃原子，供晋升和伏笔洞见共用。"""
        if not keywords:
            return []

        try:
            with memory_db:
                # 构建 OR 条件: content LIKE '%kw1%' OR content LIKE '%kw2%' ...
                kw_conditions = [MemoryAtomModel.content.contains(kw) for kw in keywords]
                combined = reduce(lambda a, b: a | b, kw_conditions)

                query = (
                    MemoryAtomModel.select()
                    .where(
                        MemoryAtomModel.status == "active",
                        combined,
                    )
                    .order_by(MemoryAtomModel.weight.desc(), MemoryAtomModel.last_accessed_at.desc())
                )
                if limit is not None:
                    query = query.limit(limit)
                return list(query)
        except Exception as e:
            logger.warning(f"噪声回收: 关键词匹配失败: {e}")
            return []

    def _has_temporal_gap(self, content: str) -> bool:
        """检查噪声内容是否指向一个未被相关记忆覆盖的时间段

        简单启发式:
            1. 检查内容中是否包含时间语境词（如"昨天"、"上周"等）
            2. 去掉时间词后提取主题关键词
            3. 若 retention_days 内无共享主题关键词的活跃原子，则视为存在缺口

        Args:
            content: 噪声内容

        Returns:
            True 表示存在时间缺口（噪声可能值得晋升）
        """
        temporal_markers = [
            "昨天",
            "前天",
            "上周",
            "上个月",
            "刚才",
            "之前",
            "以前",
            "过去",
            "最近",
            "不久",
        ]
        if not any(marker in content for marker in temporal_markers):
            return False

        # 时间词本身不能证明主题相关，否则任何一条包含“昨天”的近期记忆
        # 都会阻断完全不同主题的噪声晋升。
        semantic_content = content
        for marker in temporal_markers:
            semantic_content = semantic_content.replace(marker, " ")
        keywords = extract_keywords(semantic_content, max_keywords=5)
        if not keywords:
            return False

        cutoff = datetime.datetime.now() - datetime.timedelta(days=self._retention_days)
        try:
            with memory_db:
                keyword_conditions = [MemoryAtomModel.content.contains(keyword) for keyword in keywords]
                related_condition = reduce(lambda a, b: a | b, keyword_conditions)
                recent_related_count = (
                    MemoryAtomModel.select()
                    .where(
                        MemoryAtomModel.status == "active",
                        MemoryAtomModel.created_at >= cutoff,
                        related_condition,
                    )
                    .count()
                )
                return recent_related_count == 0
        except Exception as e:
            logger.warning(f"噪声回收: 时间验证失败: {e}")
            return False

    async def _promote(self, noise: Any) -> bool:
        """将噪声幂等晋升为正式记忆原子，成功确认后删除候选。"""
        if self._is_raw_archive_candidate(noise):
            logger.warning("噪声回收跳过原始聊天直写晋升: source_id=%s", noise.source_id)
            return False

        # 固定 ID 使“原子已写入、候选删除失败”的重试不会创建重复记忆。
        source_identity = getattr(noise, "source_id", None) or f"noise:{int(noise.id)}"
        identity = f"{source_identity}\0{str(noise.content or '')}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        atom_id = f"recycled_{digest}"
        atom = MemoryAtomDC(
            atom_id=atom_id,
            atom_type=AtomType.EPISODIC,
            content=noise.content,
            importance=min(noise.significance, 1.0),
            confidence=self.PROMOTED_CONFIDENCE,
            source_scene="dream",
            source_id=f"noise_pool:{digest}",
        )
        try:
            if not MemoryAtomModel.select().where(MemoryAtomModel.atom_id == atom_id).exists():
                await self._writer.write_atom(atom=atom)
            if not self._delete_noise(noise.id):
                logger.warning("噪声回收: 晋升已写入但候选确认删除失败 (id=%s)", noise.id)
                return False
            return True
        except Exception as e:
            logger.error(f"噪声回收: 晋升失败 (id={noise.id}): {e}")
            return False

    @staticmethod
    def _is_raw_archive_candidate(noise: Any) -> bool:
        """判断候选是否直接来自未经语义提取的原始聊天。"""
        return str(getattr(noise, "source_id", "") or "").startswith("raw_message_archive:")

    def _write_foreshadowing_insight(
        self,
        noise: Any,
        keywords: list[str],
        matched_atoms: list[MemoryAtomModel],
    ) -> bool:
        """幂等保存伏笔洞见，并在同一事务中消费来源噪声。"""
        source_atoms = sorted({atom.atom_id for atom in matched_atoms[: self.FORESHADOW_SOURCE_LIMIT]})
        keyword_text = "、".join(keywords[:5]) if keywords else "相关线索"
        content_preview = " ".join(str(noise.content or "").split())[:100]
        content = f"伏笔洞见: 噪声片段可能与已有记忆通过「{keyword_text}」串联；原片段：{content_preview}"

        source_atoms_json = json.dumps(source_atoms, ensure_ascii=False)
        try:
            created = False
            with memory_db.atomic():
                existing = InsightPool.get_or_none(
                    InsightPool.content == content,
                    InsightPool.source_atoms == source_atoms_json,
                    InsightPool.agent_name == "dream_foreshadowing",
                )
                if existing is None:
                    InsightPool.create(
                        content=content,
                        source_atoms=source_atoms_json,
                        agent_name="dream_foreshadowing",
                        confidence=self.FORESHADOW_CONFIDENCE,
                    )
                    created = True
                deleted = NoisePool.delete().where(NoisePool.id == noise.id).execute()
                if deleted != 1:
                    raise RuntimeError(f"待消费噪声不存在或删除数量异常: {deleted}")
            logger.info(
                "噪声回收: 生成伏笔洞见",
                extra={
                    "noise_id": noise.id,
                    "matched_atoms": len(source_atoms),
                    "content_preview": content_preview[:60],
                    "created": created,
                },
            )
            return True
        except Exception as e:
            logger.warning(f"噪声回收: 写入伏笔洞见失败 (id={noise.id}): {e}")
            return False

    @staticmethod
    def _delete_noise(noise_id: int) -> bool:
        """删除一条噪声记录

        Returns:
            是否成功删除唯一候选
        """
        try:
            with memory_db:
                return NoisePool.delete().where(NoisePool.id == noise_id).execute() == 1
        except Exception as e:
            logger.warning(f"噪声回收: 删除噪声失败 (id={noise_id}): {e}")
            return False
