# -*- coding: utf-8 -*-
"""记忆原子客观性校验器

在记忆入库前进行客观性校验：
1. 事实一致性检查（基于关键词和 n-gram 重叠）
2. 置信度评估（基于证据一致性）
3. 噪声过滤（低质量信息筛查）

M1 阶段仅使用启发式规则，不调用 LLM API。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Optional

from src.common.logger import get_logger
from src.memory.atom import MemoryAtom
from src.memory.schema import ConflictObservation, NoisePool, memory_db
from src.memory.store import MemoryStore
from src.memory.trace_chain import TraceChainRecorder, TraceStep

logger = get_logger("memory.objectivity")

# ── 常量 ─────────────────────────────────────────────────────────────────────

_NEGATION_WORDS: set[str] = {
    "不",
    "没",
    "无",
    "非",
    "莫",
    "勿",
    "别",
    "未",
    "未曾",
    "没有",
    "不是",
    "不会",
    "不可能",
    "从不",
    "从未",
}
_MIN_CONTENT_LENGTH = 3
_NOISE_IMPORTANCE_THRESHOLD = 0.1
_HIGH_SIMILARITY_THRESHOLD = 0.85
_MEDIUM_SIMILARITY_THRESHOLD = 0.55
_CONFLICT_CONFIDENCE_PENALTY_LIGHT = 0.8
_CONFLICT_CONFIDENCE_PENALTY_HEAVY = 0.5
_CONFLICT_COUNT_THRESHOLD = 3
_MAX_CONFLICT_CANDIDATES = 100
_MAX_RECENT_ATOMS = 200

# ── 结果类型 ─────────────────────────────────────────────────────────────────


@dataclass
class ConflictInfo:
    """冲突信息

    Attributes:
        existing_atom_id: 冲突的已有原子 ID
        existing_content: 已有原子的 content
        new_content: 新原子的 content
        conflict_type: 冲突类型 — "contradiction" / "duplicate" / "supersedes"
        overlap_score: 内容重叠度（基于 n-gram Jaccard）
    """

    existing_atom_id: str
    existing_content: str
    new_content: str
    conflict_type: str
    overlap_score: float
    new_atom_id: str = ""  # 待写入原子的 ID，供 record_conflict() 填充 atom_b_id


@dataclass
class CheckResult:
    """校验结果

    Attributes:
        passed: 是否通过校验
        atom: 调整后的原子（可能修改了 confidence）
        conflicts: 检测到的冲突列表
        noise: 是否被判定为噪声
        consistency_score: 一致性分数 0-1
        recommendation: 建议操作 — "write" / "review" / "reject"
    """

    passed: bool
    atom: Optional[MemoryAtom]
    conflicts: list[ConflictInfo]
    noise: bool
    consistency_score: float
    recommendation: str


# ── 文本相似度工具函数 ───────────────────────────────────────────────────────


def _char_ngrams(text: str, n: int = 2) -> set[str]:
    """提取字符级 n-gram"""
    if n <= 0:
        return set()
    text = text.strip()
    if len(text) < n:
        return {text}
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def compute_content_similarity(text_a: str, text_b: str) -> float:
    """计算两段文本的相似度（字符级 2-gram Jaccard 系数）

    适用于中文短文本的快速相似度比较。使用字符级 2-gram 而非词级，
    避免分词依赖。

    Args:
        text_a: 第一段文本
        text_b: 第二段文本

    Returns:
        0-1 的相似度分数，值越大表示越相似
    """
    if not text_a and not text_b:
        return 1.0
    if not text_a or not text_b:
        return 0.0

    grams_a = _char_ngrams(text_a, 2)
    grams_b = _char_ngrams(text_b, 2)

    intersection = grams_a & grams_b
    union = grams_a | grams_b

    return len(intersection) / len(union) if union else 0.0


def extract_entity_set(text: str, known_entities: Optional[list[str]] = None) -> set[str]:
    """从文本中提取实体集合

    在中文语境下，通过以下方式识别实体：
    1. 引号包裹的内容（"xxx"、'xxx'、「xxx」）
    2. @ 提及的用户名
    3. 提供的已知实体列表
    4. 中英文混合大写词（如 "OpenAI"、"GPT-4"）

    Args:
        text: 待提取的文本
        known_entities: 已知实体列表（来自 MemoryAtom.entities）

    Returns:
        提取的实体集合
    """
    entities: set[str] = set()

    if known_entities:
        entities.update(e.strip() for e in known_entities if e.strip())

    # 引号包裹的内容
    quoted = re.findall(
        r'[""\u300C\u300D\u300E\u300F\uff07]([^""\u300C\u300D\u300E\u300F\uff07]+)[""\u300C\u300D\u300E\u300F\uff07]',
        text,
    )
    entities.update(q.strip() for q in quoted if q.strip())

    # @ 提及
    mentions = re.findall(r"@(\S+)", text)
    entities.update(m.strip() for m in mentions if m.strip())

    # 中英文混合大写词
    mixed_case = re.findall(r"\b[A-Z][a-zA-Z0-9/\-]+\b", text)
    entities.update(m for m in mixed_case if len(m) >= 2)

    return entities


def _extract_numeric_facts(text: str) -> list[tuple[float, str]]:
    """从文本中提取数值事实（如 "25岁"、"180cm"）"""
    facts: list[tuple[float, str]] = []
    pattern = re.compile(r"(\d+\.?\d*)\s*(岁|年|月|日|天|小时|分|秒|cm|m|kg|g|元|块|分|级|星|个|次|号?)")
    for match in pattern.finditer(text):
        try:
            value = float(match.group(1))
            unit = match.group(2)
            facts.append((value, unit))
        except ValueError:
            continue
    return facts


def _remove_negations(text: str) -> str:
    """移除文本中的否定词"""
    for neg in _NEGATION_WORDS:
        text = text.replace(neg, "")
    return text.strip()


def check_contradiction(a: str, b: str) -> bool:
    """检测两段文本之间是否存在矛盾

    基于启发式规则：
    1. 否定词检测：一句话有否定词而另一句没有，且其他内容高度相似
    2. 数值冲突：同一上下文中出现不同的数值

    Args:
        a: 文本 A
        b: 文本 B

    Returns:
        True 如果检测到矛盾
    """
    # ── 规则 1：否定词矛盾 ──
    sim = compute_content_similarity(a, b)
    if sim > _MEDIUM_SIMILARITY_THRESHOLD:
        a_has_neg = any(neg in a for neg in _NEGATION_WORDS)
        b_has_neg = any(neg in b for neg in _NEGATION_WORDS)
        if a_has_neg != b_has_neg:
            a_clean = _remove_negations(a)
            b_clean = _remove_negations(b)
            clean_sim = compute_content_similarity(a_clean, b_clean)
            if clean_sim > _HIGH_SIMILARITY_THRESHOLD:
                return True

    # ── 规则 2：数值冲突 ──
    a_facts = _extract_numeric_facts(a)
    b_facts = _extract_numeric_facts(b)
    if a_facts and b_facts:
        for val_a, unit_a in a_facts:
            for val_b, unit_b in b_facts:
                if unit_a == unit_b and abs(val_a - val_b) > 0.01:
                    return True

    return False


# ── 客观性校验器 ─────────────────────────────────────────────────────────────


class ObjectivityChecker:
    """基础客观性校验器

    在记忆入库前进行客观性校验，确保记忆原子的质量和一致性。
    M1 阶段仅使用启发式规则，无需 LLM 调用。

    Usage:
        checker = ObjectivityChecker(store)
        result = await checker.check_before_write(atom)
        if result.passed:
            await store.insert_atom(...)
        elif result.recommendation == "review":
            # 标记为待审查
    """

    def __init__(self, store: MemoryStore):
        """初始化校验器

        Args:
            store: MemoryStore 实例，用于检索已有原子
        """
        self.store = store

    async def check_before_write(
        self,
        atom: MemoryAtom,
        trace_recorder: Optional[TraceChainRecorder] = None,
    ) -> CheckResult:
        """写入前校验 — 执行完整校验链并返回校验结果

        校验流程：
        1. 噪声过滤 → 判定是否为噪声
        2. 自洽性检查 → 计算一致性分数
        3. 冲突检测 → 查找与已有原子的矛盾
        4. 置信度调整 → 根据一致性和冲突调整 confidence
        5. 综合建议 → 生成推荐操作

        Args:
            atom: 待写入的记忆原子
            trace_recorder: 追溯链记录器（可选），传入时记录第 2 步校验追溯

        Returns:
            CheckResult: 校验结果
        """
        # Step 1: 噪声过滤
        is_noise = await self.filter_noise(atom)
        if is_noise:
            logger.warning("客观性校验: 噪声过滤拒绝", atom_id=atom.atom_id, atom_type=atom.atom_type.value)
            return CheckResult(
                passed=False,
                atom=atom,
                conflicts=[],
                noise=True,
                consistency_score=0.0,
                recommendation="reject",
            )

        # Step 2: 自洽性检查
        consistency_score = await self.check_self_consistency(atom)

        # Step 3: 冲突检测
        conflicts = await self.detect_conflicts(atom)

        # Step 4: 置信度调整
        adjusted_atom = self.adjust_confidence(atom, consistency_score, conflicts)

        # Step 5: 综合建议
        recommendation = self._decide_recommendation(
            adjusted_atom,
            consistency_score,
            conflicts,
            is_noise,
        )
        passed = recommendation == "write"

        log_fn = logger.warning if not passed else logger.debug
        log_fn(
            "客观性校验结果",
            atom_id=atom.atom_id,
            atom_type=atom.atom_type.value,
            passed=passed,
            recommendation=recommendation,
            confidence_adjustment=round(adjusted_atom.confidence - atom.confidence, 4),
            consistency_score=round(consistency_score, 4),
            conflicts_count=len(conflicts),
        )

        if trace_recorder is not None:
            trace_recorder.record(
                TraceStep(
                    atom_id=atom.atom_id,
                    step_order=2,
                    agent_name="ObjectivityChecker",
                    operation="verify",
                    input_source=f"recommendation={recommendation}",
                    output_summary=f"consistency={consistency_score:.2f} conflicts={len(conflicts)}",
                    confidence_decay=adjusted_atom.confidence,
                )
            )

        return CheckResult(
            passed=passed,
            atom=adjusted_atom,
            conflicts=conflicts,
            noise=is_noise,
            consistency_score=consistency_score,
            recommendation=recommendation,
        )

    async def check_self_consistency(self, atom: MemoryAtom) -> float:
        """自洽性检查 — 返回 0-1 的一致性分数

        检查项：
        - content 长度是否合理（过短/过长 → 扣分）
        - entities 是否与 content 匹配（无匹配 → 扣分）
        - importance 与 content 长度/关键度是否匹配
        - 纯符号/无意义内容 → 扣分

        Args:
            atom: 待检查的记忆原子

        Returns:
            0-1 的一致性分数，越高表示越自洽
        """
        score = 1.0
        content = atom.content.strip()
        length = len(content)

        # ── 长度合理性 ──
        if length < 5:
            score -= 0.4
        elif length < 10:
            score -= 0.2
        elif length > 500:
            score -= 0.1  # 过长也可能有问题

        # ── 实体匹配 ──
        if atom.entities:
            matched = sum(1 for entity in atom.entities if entity and entity in content)
            entity_ratio = matched / len(atom.entities) if atom.entities else 0.0
            if entity_ratio < 0.3:
                score -= 0.3
            elif entity_ratio < 0.6:
                score -= 0.1
        else:
            # 实体列表为空时轻扣分
            if length < 20:
                score -= 0.1

        # ── 内容质量 ──
        if re.match(r"^[\d\s\W]+$", content):
            score -= 0.5  # 纯符号/数字

        # 含具体数值或引号 → 加分（更具象）
        if re.search(r"\d+", content):
            score = min(1.0, score + 0.1)
        if '"' in content or "\u300c" in content or "'" in content:
            score = min(1.0, score + 0.05)

        # ── importance 合理性 ──
        if atom.importance >= 0.9 and length < 15:
            score -= 0.2  # 高重要性但内容很短
        if atom.importance <= 0.1 and length > 100:
            score -= 0.1  # 低重要性但内容很长

        final_score = max(0.0, min(1.0, score))
        logger.debug(
            "自洽性检查完成",
            atom_id=atom.atom_id,
            content_len=len(atom.content),
            consistent=final_score >= 0.5,
            score=round(final_score, 4),
        )
        return final_score

    async def detect_conflicts(self, atom: MemoryAtom) -> list[ConflictInfo]:
        """检测与已有记忆之间的冲突

        策略：
        1. 按 entities + 相似 content 检索已有原子
        2. 对比 content 找出矛盾/重复/替代关系
        3. 只读检测，不修改现有数据

        Args:
            atom: 待写入的记忆原子

        Returns:
            冲突信息列表（可能为空）
        """
        conflicts: list[ConflictInfo] = []
        candidates = await self._fetch_conflict_candidates(atom)

        for candidate in candidates:
            candidate_content = candidate.get("content", "")
            candidate_id = candidate.get("atom_id", "")

            if not candidate_content or not candidate_id:
                continue
            if candidate_id == atom.atom_id:
                continue

            sim = compute_content_similarity(atom.content, candidate_content)
            if sim < 0.2:
                continue

            conflict_type = self._classify_conflict(
                atom.content,
                candidate_content,
                sim,
            )
            if conflict_type:
                conflicts.append(
                    ConflictInfo(
                        existing_atom_id=candidate_id,
                        existing_content=candidate_content,
                        new_content=atom.content,
                        conflict_type=conflict_type,
                        overlap_score=sim,
                    )
                )

        logger.debug(
            "冲突检测完成",
            atom_id=atom.atom_id,
            conflicts_found=len(conflicts),
            conflict_types=[c.conflict_type for c in conflicts],
        )
        return conflicts

    async def _fetch_conflict_candidates(
        self,
        atom: MemoryAtom,
    ) -> list[dict[str, Any]]:
        """获取冲突检测的候选原子"""
        candidates: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        # 按相同 atom_type 筛选
        if atom.atom_type and atom.atom_type.value:
            type_list = await self.store.list_atoms(
                atom_type=atom.atom_type.value,
                limit=_MAX_CONFLICT_CANDIDATES,
            )
            for c in type_list:
                cid = c.get("atom_id", "")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    candidates.append(c)

        # 补充其他类型
        if len(candidates) < _MAX_CONFLICT_CANDIDATES:
            recent = await self.store.list_atoms(limit=_MAX_RECENT_ATOMS)
            for c in recent:
                cid = c.get("atom_id", "")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    candidates.append(c)

        return candidates

    @staticmethod
    def _classify_conflict(
        new_content: str,
        existing_content: str,
        similarity: float,
    ) -> Optional[str]:
        """分类冲突类型"""
        if similarity >= _HIGH_SIMILARITY_THRESHOLD:
            return "duplicate"

        if similarity >= _MEDIUM_SIMILARITY_THRESHOLD:
            if check_contradiction(new_content, existing_content):
                return "contradiction"
            if len(new_content) > len(existing_content) * 1.3:
                return "supersedes"

        if similarity >= 0.3 and check_contradiction(new_content, existing_content):
            return "contradiction"

        return None

    async def filter_noise(self, atom: MemoryAtom) -> bool:
        """噪声过滤 — 返回 True 表示被判定为噪声

        过滤规则：
        - content 为空或长度 < 3 字符 → 噪声
        - content 纯数字/符号 → 噪声
        - entities 为空且 content 过短（< 10 字符）→ 噪声
        - importance < 0.1 → 可能为噪声

        Args:
            atom: 待检查的记忆原子

        Returns:
            True 表示该原子被判定为噪声
        """
        content = atom.content.strip()

        if not content or len(content) < _MIN_CONTENT_LENGTH:
            logger.debug("噪声过滤: content 过短 (%d字符)", len(content))
            return True

        if re.match(r"^[\d\s\W]+$", content):
            logger.debug("噪声过滤: 纯数字/符号内容: %r", content)
            return True

        if (not atom.entities or len(atom.entities) == 0) and len(content) < 10:
            logger.debug("噪声过滤: 无实体且内容过短: %r", content)
            return True

        if atom.importance < _NOISE_IMPORTANCE_THRESHOLD:
            logger.debug("噪声过滤: importance 过低 (%.2f)", atom.importance)
            return True

        return False

    def adjust_confidence(
        self,
        atom: MemoryAtom,
        consistency_score: float,
        conflicts: list[ConflictInfo],
    ) -> MemoryAtom:
        """根据一致性和冲突调整置信度

        策略：
        - 无冲突 → confidence * 1.0（保持不变）
        - 少量冲突（1-2 个）→ confidence * 0.8
        - 严重冲突（3+ 个）→ confidence * 0.5

        同时结合 consistency_score 微调。

        Args:
            atom: 原记忆原子
            consistency_score: 自洽性检查分数（0-1）
            conflicts: 检测到的冲突列表

        Returns:
            调整了 confidence 的新 MemoryAtom
        """
        multiplier = 1.0

        conflict_count = len(conflicts)
        if conflict_count == 0:
            pass
        elif conflict_count <= 2:
            multiplier *= _CONFLICT_CONFIDENCE_PENALTY_LIGHT  # 0.8
        else:
            multiplier *= _CONFLICT_CONFIDENCE_PENALTY_HEAVY  # 0.5

        if consistency_score < 0.3:
            multiplier *= 0.7
        elif consistency_score < 0.6:
            multiplier *= 0.9

        new_confidence = max(0.0, min(1.0, atom.confidence * multiplier))
        return replace(atom, confidence=new_confidence)

    @staticmethod
    def _decide_recommendation(
        atom: MemoryAtom,
        consistency_score: float,
        conflicts: list[ConflictInfo],
        is_noise: bool,
    ) -> str:
        """综合决策 — 生成推荐操作

        Returns:
            "write" / "review" / "reject"
        """
        if is_noise:
            return "reject"

        if consistency_score < 0.2:
            return "reject"

        has_contradiction = any(c.conflict_type == "contradiction" for c in conflicts)
        has_duplicate = any(c.conflict_type == "duplicate" for c in conflicts)

        if has_contradiction:
            return "review"
        if has_duplicate:
            return "reject" if atom.confidence < 0.3 else "review"

        if consistency_score >= 0.6 and not conflicts:
            return "write"

        if any(c.conflict_type == "supersedes" for c in conflicts):
            return "review"
        if consistency_score >= 0.4:
            return "write"

        return "review"

    # ── 冲突持久化 ────────────────────────────────────────────────────────

    async def record_conflict(self, conflict: ConflictInfo) -> str:
        """将检测到的冲突记录到 ConflictObservation 表

        Args:
            conflict: 冲突信息

        Returns:
            str: 冲突记录 ID，失败时返回空字符串
        """
        try:
            with memory_db:
                record = ConflictObservation.create(
                    atom_a_id=conflict.existing_atom_id,
                    atom_b_id=conflict.new_atom_id,
                    conflict_type=conflict.conflict_type,
                    description=(
                        f"冲突类型: {conflict.conflict_type} | "
                        f"重叠度: {conflict.overlap_score:.2f} | "
                        f"已有: {conflict.existing_content[:100]} | "
                        f"新内容: {conflict.new_content[:100]}"
                    ),
                    status="pending",
                )
                return str(record.id)
        except Exception as e:
            logger.error("记录冲突失败: %s", e)
            return ""

    async def record_noise(
        self,
        content: str,
        source_scene: str = "chat",
        significance: float = 0.0,
    ) -> str:
        """将被判定为噪声的内容记录到 NoisePool

        Args:
            content: 原始内容
            source_scene: 来源场景
            significance: 显著性评分

        Returns:
            str: 噪声记录 ID，失败时返回空字符串
        """
        try:
            with memory_db:
                record = NoisePool.create(
                    content=content[:200],
                    source_scene=source_scene,
                    significance=significance,
                )
                return str(record.id)
        except Exception as e:
            logger.error("记录噪声失败: %s", e)
            return ""
