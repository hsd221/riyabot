"""冲突仲裁模块 — Phase 2D

在冲突观察区（ConflictObservation）累积到足够观测次数后，
基于启发式规则自动仲裁记忆原子间的矛盾。

使用"累积触发制"（accumulation trigger）：
冲突仅在至少被观测到 {_ACCUMULATION_THRESHOLD} 次，且跨越多个时间段后，
才进入自动仲裁流程。

仲裁优先级链：evidence_count > trace_reliability > confidence > recency

Integration:
    arbiter = ConflictArbiter(MemoryStore.get_instance())
    count = await arbiter.check_and_resolve()
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import Optional

from src.common.logger import get_logger
from src.memory.embedding_utils import generate_embedding
from src.memory.schema import ConflictObservation, MemoryTraceChain, RawMessageArchive, SemanticDetail, memory_db
from src.memory.store import MemoryStore
from src.memory.types import AtomDict

logger = get_logger("memory.conflict")

# ── 常量 ─────────────────────────────────────────────────────────────────────

_ACCUMULATION_THRESHOLD = 3  # 累积触发阈值
_MIN_DISTINCT_OBSERVATION_DAYS = 2  # 至少跨越两个日期，避免单日刷屏触发画像推翻
_TRACE_RELIABILITY_MARGIN = 0.2  # 追溯链可靠度差异超过该值时参与裁决
_MERGEABLE_CONFLICT_TYPES = {"duplicate"}  # 只有重复事实可以合并，矛盾/替代关系必须裁决
RAW_ARCHIVE_SOURCE_RE = re.compile(r"raw_message_archive:(\d+)")


# ── 仲裁决策枚举 ─────────────────────────────────────────────────────────────


class ConflictDecision(str, enum.Enum):
    """仲裁决策类型"""

    KEEP_A = "keep_a"  # 保留 A，归档 B
    KEEP_B = "keep_b"  # 保留 B，归档 A
    MERGE = "merge"  # 合并两个原子
    BOTH = "both"  # 同时降低双方置信度
    NEEDS_LLM = "needs_llm"  # 需要 LLM 仲裁
    DEFER = "defer"  # 推迟（信息不足）


# ── 仲裁结果 ─────────────────────────────────────────────────────────────────


@dataclass
class Resolution:
    """仲裁结果

    Attributes:
        decision: 仲裁决策
        atom_a_id: 原子 A ID
        atom_b_id: 原子 B ID
        merged_content: 合并后的内容（仅 MERGE 决策时有效）
        reason: 仲裁理由
        confidence_impact: 置信度影响因子（0-1，仅 BOTH 决策时非零）
    """

    decision: ConflictDecision
    atom_a_id: str
    atom_b_id: str
    merged_content: Optional[str] = None
    reason: str = ""
    confidence_impact: float = 0.0


# ── 冲突仲裁器 ───────────────────────────────────────────────────────────────


class ConflictArbiter:
    """冲突仲裁器

    基于启发式规则的冲突仲裁代理，在冲突观测累积到阈值后自动处理。
    不调用 LLM，纯规则驱动。

    Usage:
        arbiter = ConflictArbiter(store)
        count = await arbiter.check_and_resolve()
    """

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    # ── 主入口 ─────────────────────────────────────────────────────────────

    async def check_and_resolve(self) -> int:
        """检查并自动仲裁累积冲突

        1. 查询所有 pending 状态的冲突观测
        2. 按 (unordered_atom_pair, conflict_type) 分组
        3. 仅处理累积观测次数 >= {_ACCUMULATION_THRESHOLD} 且跨时间段的组
        4. 启发式仲裁后，将整组标记为 resolved

        Returns:
            int: 本轮解决的冲突组数
        """
        pending = list(
            ConflictObservation.select()
            .where(ConflictObservation.status == "pending")
            .order_by(ConflictObservation.created_at.asc())
        )

        if not pending:
            return 0

        # ── 按无序原子对 + 冲突类型分组，兼容 A/B 反向记录同一冲突 ──
        groups: dict[tuple[str, str, str], list[ConflictObservation]] = {}
        for obs in pending:
            key = self._conflict_group_key(obs)
            groups.setdefault(key, []).append(obs)

        resolved_count = 0
        for (left_atom_id, right_atom_id, conflict_type), obs_list in groups.items():
            if len(obs_list) < _ACCUMULATION_THRESHOLD:
                logger.debug(
                    "冲突组 %s/%s 观测次数不足 (%d < %d)，跳过",
                    left_atom_id,
                    conflict_type,
                    len(obs_list),
                    _ACCUMULATION_THRESHOLD,
                )
                continue

            distinct_days = self._distinct_observation_days(obs_list)
            if distinct_days < _MIN_DISTINCT_OBSERVATION_DAYS:
                logger.debug(
                    "冲突组 %s↔%s/%s 缺少跨时间段证据 (%d < %d)，跳过",
                    left_atom_id,
                    right_atom_id,
                    conflict_type,
                    distinct_days,
                    _MIN_DISTINCT_OBSERVATION_DAYS,
                )
                continue

            latest_obs = obs_list[-1]  # 取该组最新的一条

            # atom_b_id 为空时无法仲裁（兼容早期记录）
            if not latest_obs.atom_b_id:
                logger.warning(
                    "冲突 %s/%s 缺少 atom_b_id，跳过",
                    left_atom_id,
                    conflict_type,
                )
                continue

            resolution = await self.resolve(latest_obs)

            if resolution.decision in (ConflictDecision.DEFER, ConflictDecision.NEEDS_LLM):
                logger.debug(
                    "冲突 %s ↔ %s 暂不仲裁（%s）",
                    left_atom_id,
                    right_atom_id,
                    resolution.decision.value,
                )
                continue

            await self._apply_resolution(resolution, latest_obs)

            # 将该组所有观测记录标记为 resolved
            ids_to_mark = [o.id for o in obs_list if o.id != latest_obs.id]
            if ids_to_mark:
                try:
                    ConflictObservation.update(status="resolved").where(
                        ConflictObservation.id.in_(ids_to_mark)
                    ).execute()
                except Exception as e:
                    logger.warning("批量标记冲突已解决失败: %s", e)

            resolved_count += 1
            logger.info(
                f"冲突已仲裁: {left_atom_id[:8]} ↔ {right_atom_id[:8]} "
                f"type={conflict_type} decision={resolution.decision.value} reason={resolution.reason}"
            )

        if resolved_count > 0:
            logger.info(f"本轮自动仲裁完成，共解决 {resolved_count} 组冲突")

        return resolved_count

    @staticmethod
    def _conflict_group_key(conflict: ConflictObservation) -> tuple[str, str, str]:
        """按无序原子对生成冲突组 key，避免 A/B 反向观测被拆开。"""
        left, right = sorted((conflict.atom_a_id or "", conflict.atom_b_id or ""))
        return left, right, conflict.conflict_type

    @staticmethod
    def _distinct_observation_days(conflicts: list[ConflictObservation]) -> int:
        """统计冲突观察覆盖的自然日数量。"""
        days: set[object] = set()
        for conflict in conflicts:
            created_at = conflict.created_at
            if hasattr(created_at, "date"):
                days.add(created_at.date())
            else:
                days.add(str(created_at)[:10])
        return len(days)

    async def resolve(self, conflict: ConflictObservation) -> Resolution:
        """解析单条冲突 — 主仲裁方法

        流程：
        1. 加载两个冲突原子
        2. 尝试合并（相同实体 + 相同类型 + factual）
        3. 基于证据的仲裁
        4. 无法解决时标记 NEEDS_LLM

        Args:
            conflict: 冲突观测记录

        Returns:
            Resolution: 仲裁结果
        """
        atom_a = await self.store.get_atom(conflict.atom_a_id)
        atom_b = await self.store.get_atom(conflict.atom_b_id)

        if atom_a is None or atom_b is None:
            return Resolution(
                decision=ConflictDecision.DEFER,
                atom_a_id=conflict.atom_a_id,
                atom_b_id=conflict.atom_b_id,
                reason="其中一个原子不存在或被删除",
            )

        # Step 1: 仅对重复事实尝试合并；矛盾事实必须进入证据仲裁，不能拼接成一条记忆。
        if self._can_merge(conflict.conflict_type, atom_a, atom_b):
            merged = self._merge_atoms(atom_a, atom_b)
            return Resolution(
                decision=ConflictDecision.MERGE,
                atom_a_id=conflict.atom_a_id,
                atom_b_id=conflict.atom_b_id,
                merged_content=merged,
                reason="相同实体和类型，合并两个原子",
            )

        # Step 2: 基于证据的仲裁
        return await self._evidence_based_arbitrate(atom_a, atom_b)

    # ── 证据仲裁 ───────────────────────────────────────────────────────────

    async def _evidence_based_arbitrate(
        self,
        atom_a: AtomDict,
        atom_b: AtomDict,
    ) -> Resolution:
        """基于证据的启发式仲裁

        优先级链：evidence_count > trace_reliability > confidence > recency

        Args:
            atom_a: 原子 A 的数据字典
            atom_b: 原子 B 的数据字典

        Returns:
            Resolution: 仲裁结果
        """
        a_id = atom_a["atom_id"]
        b_id = atom_b["atom_id"]

        # ── 1. 比较证据计数 ──
        ev_a = self._get_evidence_count(a_id)
        ev_b = self._get_evidence_count(b_id)

        if ev_a > ev_b:
            return Resolution(
                decision=ConflictDecision.KEEP_A,
                atom_a_id=a_id,
                atom_b_id=b_id,
                reason=f"原子 A 证据更充分 (ev={ev_a}) vs 原子 B (ev={ev_b})",
            )
        if ev_b > ev_a:
            return Resolution(
                decision=ConflictDecision.KEEP_B,
                atom_a_id=a_id,
                atom_b_id=b_id,
                reason=f"原子 B 证据更充分 (ev={ev_b}) vs 原子 A (ev={ev_a})",
            )

        # ── 2. 比较追溯链可靠度 ──
        trace_a = self._get_trace_reliability_score(a_id)
        trace_b = self._get_trace_reliability_score(b_id)

        if abs(trace_a - trace_b) > _TRACE_RELIABILITY_MARGIN:
            if trace_a > trace_b:
                return Resolution(
                    decision=ConflictDecision.KEEP_A,
                    atom_a_id=a_id,
                    atom_b_id=b_id,
                    reason=f"原子 A 追溯链更可靠 ({trace_a:.2f} vs {trace_b:.2f})",
                )
            return Resolution(
                decision=ConflictDecision.KEEP_B,
                atom_a_id=a_id,
                atom_b_id=b_id,
                reason=f"原子 B 追溯链更可靠 ({trace_b:.2f} vs {trace_a:.2f})",
            )

        # ── 3. 比较置信度（仅当差异 > 0.1 时） ──
        conf_a = atom_a.get("confidence", 0.5) or 0.5
        conf_b = atom_b.get("confidence", 0.5) or 0.5

        if abs(conf_a - conf_b) > 0.1:
            if conf_a > conf_b:
                return Resolution(
                    decision=ConflictDecision.KEEP_A,
                    atom_a_id=a_id,
                    atom_b_id=b_id,
                    reason=f"原子 A 置信度更高 ({conf_a:.2f} vs {conf_b:.2f})",
                )
            return Resolution(
                decision=ConflictDecision.KEEP_B,
                atom_a_id=a_id,
                atom_b_id=b_id,
                reason=f"原子 B 置信度更高 ({conf_b:.2f} vs {conf_a:.2f})",
            )

        # ── 4. 比较时间（更新的胜出） ──
        created_a = atom_a.get("created_at", "")
        created_b = atom_b.get("created_at", "")

        if created_a and created_b and created_a != created_b:
            if created_a > created_b:
                return Resolution(
                    decision=ConflictDecision.KEEP_A,
                    atom_a_id=a_id,
                    atom_b_id=b_id,
                    reason=f"原子 A 更新 ({created_a[:19]}) vs 原子 B ({created_b[:19]})",
                )
            return Resolution(
                decision=ConflictDecision.KEEP_B,
                atom_a_id=a_id,
                atom_b_id=b_id,
                reason=f"原子 B 更新 ({created_b[:19]}) vs 原子 A ({created_a[:19]})",
            )

        # ── 5. 无法决定 ──
        return Resolution(
            decision=ConflictDecision.NEEDS_LLM,
            atom_a_id=a_id,
            atom_b_id=b_id,
            reason="证据、置信度、时间均无法区分",
        )

    # ── 证据查询 ───────────────────────────────────────────────────────────

    @staticmethod
    def _get_evidence_count(atom_id: str) -> int:
        """获取指定原子的证据计数（来自 SemanticDetail）

        通过 SemanticDetail.evidence_counter 字段获取该原子被
        独立确认的次数。

        Args:
            atom_id: 原子 ID

        Returns:
            int: 证据计数，找不到时返回 0
        """
        try:
            detail = SemanticDetail.get_or_none(SemanticDetail.id == atom_id)
            if detail is not None:
                return detail.evidence_counter
        except Exception as e:
            logger.warning("获取证据计数失败 (%s): %s", atom_id, e)
        return 0

    @staticmethod
    def _get_trace_reliability_score(atom_id: str) -> float:
        """沿追溯链计算证据可靠度。

        该分数只作为明显差异时的仲裁依据。没有追溯链时返回中性值 0.5；
        有可验证原始归档来源和校验/分诊步骤的链会获得小幅加成。
        """
        try:
            traces = list(
                MemoryTraceChain.select()
                .where(MemoryTraceChain.atom_id == atom_id)
                .order_by(MemoryTraceChain.step_number.asc())
            )
        except Exception as e:
            logger.warning("获取追溯链失败 (%s): %s", atom_id, e)
            return 0.5

        if not traces:
            return 0.5

        decay_scores = [
            max(0.0, min(1.0, float(trace.confidence_decay if trace.confidence_decay is not None else 1.0)))
            for trace in traces
        ]
        score = sum(decay_scores) / len(decay_scores)

        joined_source = " ".join(str(trace.input_source or "") for trace in traces).lower()
        operations = {str(trace.operation_type or "").lower() for trace in traces}
        agents = {str(trace.agent_name or "").lower() for trace in traces}
        raw_archive_ids = ConflictArbiter._raw_archive_ids_from_traces(traces)

        if raw_archive_ids:
            score += ConflictArbiter._raw_archive_reliability_boost(raw_archive_ids)
        elif "raw_message_archive" in joined_source:
            score += 0.03
        if {"verify", "triage"} & operations:
            score += 0.05
        if any("objectivity" in agent or "triage" in agent for agent in agents):
            score += 0.05

        return max(0.0, min(1.0, score))

    @staticmethod
    def _raw_archive_ids_from_traces(traces: list[MemoryTraceChain]) -> set[int]:
        """从追溯链中提取 raw archive 记录 ID。"""
        raw_ids: set[int] = set()
        for trace in traces:
            raw_ids.update(ConflictArbiter._raw_archive_ids_from_text(trace.input_source or ""))
            raw_ids.update(ConflictArbiter._raw_archive_ids_from_text(trace.output_summary or ""))
        return raw_ids

    @staticmethod
    def _raw_archive_ids_from_text(text: str) -> set[int]:
        """从文本中提取 raw_message_archive:<id> 引用。"""
        raw_ids: set[int] = set()
        for match in RAW_ARCHIVE_SOURCE_RE.finditer(text or ""):
            try:
                raw_ids.add(int(match.group(1)))
            except (TypeError, ValueError):
                continue
        return raw_ids

    @staticmethod
    def _raw_archive_reliability_boost(raw_ids: set[int]) -> float:
        """根据可追溯原始归档记录计算可靠度加成。"""
        if not raw_ids:
            return 0.0

        boosts: list[float] = []
        for raw_id in raw_ids:
            try:
                raw = RawMessageArchive.get_or_none(RawMessageArchive.id == raw_id)
            except Exception as e:
                logger.debug("读取原始归档失败 raw_id=%s: %s", raw_id, e)
                raw = None
            if raw is None:
                continue

            boost = 0.18
            if (raw.content or "").strip():
                boost += 0.03
            if str(raw.chat_type or "").lower() in {
                "group",
                "private",
                "summary",
                "topic_summary",
                "group_summary",
                "private_summary",
            }:
                boost += 0.02
            try:
                significance = max(0.0, min(1.0, float(raw.dream_significance or 0.0)))
            except (TypeError, ValueError):
                significance = 0.0
            boost += min(0.05, significance * 0.05)
            boosts.append(boost)

        if not boosts:
            return -0.05
        return min(0.25, max(boosts))

    # ── 合并判定 ───────────────────────────────────────────────────────────

    @staticmethod
    def _can_merge(conflict_type: str, atom_a: AtomDict, atom_b: AtomDict) -> bool:
        """判断两个原子是否可以合并

        合并条件：
        - 冲突类型明确为 duplicate
        - 双方都有实体且相同
        - 相同 atom_type
        - 双方都是 factual 类型（事实性记忆，适合合并）

        Args:
            conflict_type: 冲突类型
            atom_a: 原子 A 的数据字典
            atom_b: 原子 B 的数据字典

        Returns:
            bool: 是否可以合并
        """
        if str(conflict_type or "").lower() not in _MERGEABLE_CONFLICT_TYPES:
            return False

        entities_a = set(atom_a.get("entities", []) or [])
        entities_b = set(atom_b.get("entities", []) or [])

        if not entities_a or not entities_b:
            return False
        if entities_a != entities_b:
            return False
        if atom_a.get("atom_type") != atom_b.get("atom_type"):
            return False
        if atom_a.get("atom_type") != "factual":
            return False
        return True

    @staticmethod
    def _merge_atoms(atom_a: AtomDict, atom_b: AtomDict) -> str:
        """合并两个原子的内容

        策略：以较长内容为主，附加较短内容中的补充信息。
        如果一段包含另一段，直接返回较长者。

        Args:
            atom_a: 原子 A 的数据字典
            atom_b: 原子 B 的数据字典

        Returns:
            str: 合并后的内容
        """
        content_a = (atom_a.get("content") or "").strip()
        content_b = (atom_b.get("content") or "").strip()

        if not content_a:
            return content_b
        if not content_b:
            return content_a

        # 去重：如果 B 包含在 A 或 A 包含在 B 中
        if content_b in content_a:
            return content_a
        if content_a in content_b:
            return content_b

        # 以较长者为主，附加较短者
        if len(content_a) >= len(content_b):
            return f"{content_a}；{content_b}"
        return f"{content_b}；{content_a}"

    # ── 应用仲裁结果 ───────────────────────────────────────────────────────

    async def _apply_resolution(
        self,
        resolution: Resolution,
        conflict: ConflictObservation,
    ) -> None:
        """应用仲裁结果到存储层

        根据决策类型更新原子状态：
        - KEEP_A: 归档原子 B
        - KEEP_B: 归档原子 A
        - MERGE: 合并到原子 A，归档原子 B
        - BOTH: 同时降低两个原子的置信度

        Args:
            resolution: 仲裁结果
            conflict: 原始冲突观测记录
        """
        decision = resolution.decision
        a_id = resolution.atom_a_id
        b_id = resolution.atom_b_id

        logger.debug(
            "应用仲裁: %s -> %s (a=%s, b=%s)",
            decision.value,
            resolution.reason,
            a_id[:8],
            b_id[:8],
        )

        try:
            if decision == ConflictDecision.KEEP_A:
                await self.store.update_atom(b_id, {"status": "archived"})
                await self.store.qdrant.delete_atom_vector(b_id)

            elif decision == ConflictDecision.KEEP_B:
                await self.store.update_atom(a_id, {"status": "archived"})
                await self.store.qdrant.delete_atom_vector(a_id)

            elif decision == ConflictDecision.MERGE and resolution.merged_content:
                # 合并到原子 A：内容变更，重新生成 embedding
                await self.store.update_atom(
                    a_id,
                    {
                        "content": resolution.merged_content,
                        "confidence": min(1.0, await self._get_confidence(a_id) + 0.05),
                    },
                )
                try:
                    atom_a = await self.store.get_atom(a_id)
                    if atom_a:
                        embedding = await generate_embedding(resolution.merged_content)
                        if embedding:
                            await self.store.qdrant.upsert_atom_vector(
                                point_id=a_id,
                                vector=embedding,
                                payload={
                                    "atom_id": a_id,
                                    "atom_type": atom_a.get("atom_type", "factual"),
                                    "weight": atom_a.get("weight", 0.5),
                                    "importance": atom_a.get("importance", 0.5),
                                    "confidence": atom_a.get("confidence", 0.5),
                                    "status": atom_a.get("status", "active"),
                                    "source_scene": atom_a.get("source_scene", "chat"),
                                    "source_id": atom_a.get("source_id"),
                                    "privacy_level": atom_a.get("privacy_level", "context_sensitive"),
                                },
                            )
                except Exception as e:
                    logger.warning("Qdrant 同步失败 (MERGE A): %s", e)

                # 归档原子 B
                await self.store.update_atom(b_id, {"status": "archived"})
                await self.store.qdrant.delete_atom_vector(b_id)

            elif decision == ConflictDecision.BOTH:
                impact = resolution.confidence_impact or 0.1
                for atom_id in (a_id, b_id):
                    atom = await self.store.get_atom(atom_id)
                    if atom:
                        current_conf = atom.get("confidence") or 0.5
                        new_conf = max(0.0, min(1.0, current_conf * (1.0 - impact)))
                        await self.store.update_atom(atom_id, {"confidence": new_conf})
                        await self.store.qdrant.set_atom_payload(atom_id, {"confidence": new_conf})

        except Exception as e:
            logger.error("应用仲裁结果失败: %s", e, exc_info=True)
            return

        # 标记冲突观测为 resolved
        try:
            with memory_db:
                ConflictObservation.update(status="resolved").where(ConflictObservation.id == conflict.id).execute()
        except Exception as e:
            logger.error("标记冲突为已解决失败: %s", e)

    async def _get_confidence(self, atom_id: str) -> float:
        """获取原子的置信度

        Args:
            atom_id: 原子 ID

        Returns:
            float: 置信度（0-1）
        """
        atom = await self.store.get_atom(atom_id)
        if atom:
            return atom.get("confidence", 0.5) or 0.5
        return 0.5
