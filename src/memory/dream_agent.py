"""
DreamAgent — 梦境维护后台任务 (Phase 2C)

闲时运行记忆巩固、噪声清理、图谱构建。
所有操作基于启发式规则，不调用 LLM。

DreamTask 作为 AsyncTask 子类运行，由 async_task_manager 调度。
"""

from __future__ import annotations

import datetime
import json
import time
from enum import Enum
from typing import Any, Optional

from src.common.logger import get_logger
from src.config.config import global_config
from src.manager.async_task_manager import AsyncTask
from src.memory.atom import (
    MemoryAtom as MemoryAtomDC,
    AtomType,
    DecayType,
    apply_dream_consolidation,
)
from src.memory.schema import (
    InsightPool,
    MemoryAtom as MemoryAtomModel,
    DreamRun,
    GraphEdge,
    GraphEntry,
    GraphNode,
    NoisePool,
    SemanticDetail as SemanticDetailModel,
    memory_db,
)
from src.memory.forgetting import _safe_timestamp
from src.memory.store import MemoryStore

logger = get_logger("memory.dream")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

IDLE_THRESHOLD: int = 300
"""空闲判定阈值（秒），所有 ChatStream 的最后活动时间距今超过此值才算空闲"""

CONSOLIDATION_BOOST: float = 0.15
"""梦境巩固提升量，传给 apply_dream_consolidation() 的 boost 参数"""

SIMILARITY_THRESHOLD: float = 0.4
"""图谱边相似度阈值（暂未用于基于向量的相似度，保留供未来使用）"""

IMPORTANCE_MIN: float = 0.6
"""需要巩固的最小重要性——低于此值的记忆不参与巩固"""

WEIGHT_MAX: float = 0.4
"""需要巩固的最大权重——高于此值的记忆已足够强，无需巩固"""

CONSOLIDATION_BATCH_SIZE: int = 50
"""单次梦境巩固的最大原子数量"""

GRAPH_ATOMS_LIMIT: int = 20
"""参与图谱构建的 Top-N 原子数（按 weight 降序）"""

NOISE_TTL_DAYS: int = 7
"""噪声池默认保留天数，超过此期限的噪声条目将被清理"""

# ---------------------------------------------------------------------------
# 周期枚举
# ---------------------------------------------------------------------------


class DreamCycleType(Enum):
    """梦境周期类型 — 区分日常/每周/月度三种粒度的维护周期"""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


# 周期间隔（超过此时间未运行对应周期则触发，优先级: daily > weekly > monthly）
DAILY_CYCLE_HOURS: int = 24
WEEKLY_CYCLE_DAYS: int = 7
MONTHLY_CYCLE_DAYS: int = 30


# ---------------------------------------------------------------------------
# DreamTask
# ---------------------------------------------------------------------------


class DreamTask(AsyncTask):
    """梦境维护后台任务 — 闲时运行记忆巩固、噪声清理、图谱构建

    工作在系统空闲时段（所有 ChatStream 静默超过 IDLE_THRESHOLD 秒），
    在允许的梦境时间段内（DreamConfig.is_in_dream_time()）执行以下操作：

    Phase 1 — Consolidation:  提升重要但正在衰减的记忆原子的权重
    Phase 2 — Noise cleanup:  清理噪声池中过期的噪声条目
    Phase 3 — Graph building: 基于原子实体构建图谱节点/边，提取语义三元组

    Attributes:
        _store: MemoryStore 实例
        _forgetting_manager: 可选的 ForgettingManager
        _graph_store: 可选的 GraphStore（未实现时通过 Peewee 直接操作表）
    """

    def __init__(
        self,
        store: MemoryStore,
        forgetting_manager: Optional[Any] = None,
        graph_store: Optional[Any] = None,
        dream_weaver: Optional[Any] = None,
    ):
        """初始化 DreamTask

        Args:
            store: MemoryStore 实例（承载 SQLite + Qdrant）
            forgetting_manager: ForgettingManager 实例（可选，用于获取衰减统计）
            graph_store: GraphStore 实例（可选，暂未实现时可为 None）
            dream_weaver: DreamWeaver 实例（可选，用于梦呓编织洞见生成）
        """
        dream_cfg = global_config.dream
        super().__init__(
            task_name="dream_task",
            wait_before_start=dream_cfg.first_delay_seconds,
            run_interval=dream_cfg.interval_minutes * 60,
        )
        self._store = store
        self._forgetting_manager = forgetting_manager
        self._graph_store = graph_store
        self._dream_weaver = dream_weaver

    # ── 主循环 ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        """执行一次梦境维护周期 — 自动判定周期类型并分发

        流程:
        1. 检查是否在允许的梦境时间段内
        2. 检查系统是否空闲
        3. 判定当前应运行的周期类型（daily > weekly > monthly）
        4. 分发到对应的周期处理器
        """
        # 1. 检查梦境时间段
        dream_cfg = global_config.dream
        if not dream_cfg.is_in_dream_time():
            logger.debug("不在做梦时间段内，跳过本轮梦境")
            return

        # 2. 检查空闲状态
        if not await self._check_idle():
            logger.debug("聊天流活跃中，跳过本轮梦境")
            return

        # 3. 判定周期类型
        cycle_type = self._determine_cycle_type()
        if cycle_type is None:
            logger.debug("所有周期均未到期，跳过本轮梦境")
            return

        # 4. 分发到对应的周期处理器
        logger.info(f"开始 {cycle_type.value} 梦境周期")
        try:
            if cycle_type == DreamCycleType.DAILY:
                await self._run_daily_cycle()
            elif cycle_type == DreamCycleType.WEEKLY:
                await self._run_weekly_cycle()
            elif cycle_type == DreamCycleType.MONTHLY:
                await self._run_monthly_cycle()
        except Exception as e:
            logger.exception(f"{cycle_type.value} 梦境周期执行异常: {e}")

    # ── 周期判定 ────────────────────────────────────────────────────────

    def _determine_cycle_type(self) -> DreamCycleType | None:
        """判定当前应运行的梦境周期

        按优先级 daily > weekly > monthly 检查上次运行时间。
        若某种周期已超过其间隔阈值未运行，则返回该周期类型。

        Returns:
            DreamCycleType 或 None（所有周期均未到期时跳过）
        """
        try:
            with memory_db:
                last_daily: DreamRun | None = (
                    DreamRun.select()
                    .where(DreamRun.run_type == "daily", DreamRun.status == "completed")
                    .order_by(DreamRun.start_time.desc())
                    .first()
                )
                last_weekly: DreamRun | None = (
                    DreamRun.select()
                    .where(DreamRun.run_type == "weekly", DreamRun.status == "completed")
                    .order_by(DreamRun.start_time.desc())
                    .first()
                )
                last_monthly: DreamRun | None = (
                    DreamRun.select()
                    .where(DreamRun.run_type == "monthly", DreamRun.status == "completed")
                    .order_by(DreamRun.start_time.desc())
                    .first()
                )
        except Exception as e:
            logger.error(f"查询上次梦境运行记录失败: {e}")
            return DreamCycleType.DAILY

        now = datetime.datetime.now()

        if last_daily is None or (now - last_daily.start_time).total_seconds() > DAILY_CYCLE_HOURS * 3600:
            return DreamCycleType.DAILY

        if last_weekly is None or (now - last_weekly.start_time).days >= WEEKLY_CYCLE_DAYS:
            return DreamCycleType.WEEKLY

        if last_monthly is None or (now - last_monthly.start_time).days >= MONTHLY_CYCLE_DAYS:
            return DreamCycleType.MONTHLY

        return None

    def _create_dream_run(self, run_type: str) -> int | None:
        """创建 DreamRun 记录并返回 ID

        Args:
            run_type: 运行类型（daily/weekly/monthly）

        Returns:
            DreamRun 记录 ID，失败返回 None
        """
        try:
            with memory_db:
                record = DreamRun.create(
                    run_type=run_type,
                    start_time=datetime.datetime.now(),
                    status="running",
                )
                return record.id
        except Exception as e:
            logger.error(f"创建 DreamRun 记录失败: {e}")
            return None

    @staticmethod
    def _get_atoms_modified_since(days: int) -> list:
        """查询最近 N 天内修改过的活跃原子

        Args:
            days: 天数范围

        Returns:
            MemoryAtomModel 实例列表（按 weight 降序）
        """
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        try:
            with memory_db:
                return list(
                    MemoryAtomModel.select()
                    .where(
                        MemoryAtomModel.last_accessed_at >= cutoff,
                        MemoryAtomModel.status == "active",
                    )
                    .order_by(MemoryAtomModel.weight.desc())
                )
        except Exception as e:
            logger.error(f"查询近期原子失败: {e}")
            return []

    # ── 空闲检测 ────────────────────────────────────────────────────────

    async def _check_idle(self) -> bool:
        """检查系统是否空闲

        查询 ChatStreams 表，若所有 stream 的 last_active_time 距今均超过
        IDLE_THRESHOLD 秒则视为空闲。

        Returns:
            True 表示系统空闲（可以进行梦境），False 表示仍有活跃 ChatStream
        """
        try:
            from src.common.database.database_model import ChatStreams

            now = time.time()
            threshold = now - IDLE_THRESHOLD

            active_count = ChatStreams.select().where(ChatStreams.last_active_time > threshold).count()

            return active_count == 0

        except Exception as e:
            logger.warning(f"空闲检测失败（默认允许执行梦境）: {e}")
            return True  # 安全兜底：检测失败时允许梦境继续

    # ── Phase 1: 记忆巩固 ─────────────────────────────────────────────

    async def _consolidate(self, max_age_days: int | None = None, batch_size: int | None = None) -> int:
        """Phase 1 — 提升重要但正在衰减的记忆

        选取 status='active'、importance >= IMPORTANCE_MIN、weight <= WEIGHT_MAX
        的原子，调用 apply_dream_consolidation() 为其权重应用 consolidation boost。

        Args:
            max_age_days: 若指定，仅处理最近 N 天内修改过的原子
            batch_size: 处理原子数量上限，默认使用 CONSOLIDATION_BATCH_SIZE

        Returns:
            成功巩固的原子数量
        """
        limit = batch_size or CONSOLIDATION_BATCH_SIZE
        count = 0
        now_ts = time.time()

        try:
            with memory_db:
                conditions: list[Any] = [
                    MemoryAtomModel.status == "active",
                    MemoryAtomModel.importance >= IMPORTANCE_MIN,
                    MemoryAtomModel.weight <= WEIGHT_MAX,
                ]
                if max_age_days is not None:
                    cutoff = datetime.datetime.now() - datetime.timedelta(days=max_age_days)
                    conditions.append(MemoryAtomModel.last_accessed_at >= cutoff)

                query = MemoryAtomModel.select().where(*conditions).order_by(MemoryAtomModel.weight.asc()).limit(limit)

                for atom_model in query:
                    try:
                        atom_dc = MemoryAtomDC(
                            atom_id=atom_model.atom_id,
                            atom_type=AtomType(atom_model.atom_type),
                            content=atom_model.content or "",
                            importance=atom_model.importance,
                            confidence=atom_model.confidence,
                            weight=atom_model.weight,
                            created_at=_safe_timestamp(atom_model.created_at, now_ts),
                            last_accessed_at=_safe_timestamp(atom_model.last_accessed_at, now_ts),
                            ttl_days=float(atom_model.ttl_days or 7),
                            decay_type=DecayType(atom_model.decay_type),
                            reinforcement_count=atom_model.reinforcement_count or 0,
                            source_scene=atom_model.source_scene or "unknown",
                            privacy_level=atom_model.privacy_level or "context_sensitive",
                            status=atom_model.status,
                        )

                        updated = apply_dream_consolidation(atom_dc, boost=CONSOLIDATION_BOOST)

                        MemoryAtomModel.update(weight=updated.weight).where(
                            MemoryAtomModel.atom_id == atom_model.atom_id
                        ).execute()
                        count += 1

                    except Exception as e:
                        logger.error(f"巩固原子失败 ({atom_model.atom_id}): {e}")

        except Exception as e:
            logger.error(f"记忆巩固阶段异常: {e}")

        if count > 0:
            logger.info(f"梦境巩固: {count} 个原子权重已提升 (boost={CONSOLIDATION_BOOST})")
        return count

    # ── Phase 2: 噪声清理 ─────────────────────────────────────────────

    async def _clean_noise(self) -> int:
        """Phase 2 — 清理噪声池中过期的噪声条目

        删除 NoisePool 中创建时间距今超过 NOISE_TTL_DAYS 天的记录。

        Returns:
            清理的噪声条目数量
        """
        try:
            cutoff = datetime.datetime.now() - datetime.timedelta(days=NOISE_TTL_DAYS)

            with memory_db:
                deleted = NoisePool.delete().where(NoisePool.created_at < cutoff).execute()

            if deleted > 0:
                logger.info(f"噪声清理: {deleted} 条过期噪声已清除 (ttl={NOISE_TTL_DAYS}天)")
            return deleted

        except Exception as e:
            logger.error(f"噪声清理阶段异常: {e}")
            return 0

    # ── Phase 3: 图谱构建 ─────────────────────────────────────────────

    async def _build_graph(self, limit: int | None = None) -> tuple[int, int]:
        """Phase 3 — 构建知识图谱节点/边，提取语义三元组

        选取 weight 最高的 N 个活跃原子 (N=limit or GRAPH_ATOMS_LIMIT)：
        1. 从原子 entities 字段提取实体，创建/获取 GraphNode
        2. 对出现在同一原子中的实体对，创建 GraphEdge (predicate='related_to')
        3. 从 SemanticDetail 表提取 SPO 三元组，写入 GraphEntry

        Args:
            limit: 参与的原子数量上限，默认使用 GRAPH_ATOMS_LIMIT

        Returns:
            tuple[int, int]: (创建的边数, 创建的三元组数)
        """
        atom_limit = limit or GRAPH_ATOMS_LIMIT
        edges_created = 0
        entries_created = 0

        try:
            with memory_db:
                top_atoms = list(
                    MemoryAtomModel.select()
                    .where(MemoryAtomModel.status == "active")
                    .order_by(MemoryAtomModel.weight.desc())
                    .limit(atom_limit)
                )

                if not top_atoms:
                    return 0, 0

                # 提取实体并构建节点/边
                atom_entities: dict[str, list[str]] = {}
                for atom_model in top_atoms:
                    entities: list[str] = []
                    if atom_model.entities:
                        try:
                            parsed = json.loads(atom_model.entities)
                            if isinstance(parsed, list):
                                entities = [str(e) for e in parsed]
                        except (json.JSONDecodeError, TypeError):
                            pass
                    atom_entities[atom_model.atom_id] = entities

                # 为每个 unique 实体创建 GraphNode
                all_entities = set()
                for ent_list in atom_entities.values():
                    all_entities.update(ent_list)

                for entity in all_entities:
                    GraphNode.get_or_create(
                        node_type="entity",
                        label=entity,
                        defaults={"properties": "{}"},
                    )

                # 对同一原子中的实体对创建 GraphEdge
                for ent_list in atom_entities.values():
                    if len(ent_list) < 2:
                        continue
                    node_map: dict[str, int] = {}
                    for entity in ent_list:
                        node = GraphNode.get_or_none(GraphNode.label == entity)
                        if node is not None:
                            node_map[entity] = node.id

                    node_ids = list(node_map.values())
                    for i in range(len(node_ids)):
                        for j in range(i + 1, len(node_ids)):
                            _, created = GraphEdge.get_or_create(
                                source_node_id=node_ids[i],
                                target_node_id=node_ids[j],
                                predicate="related_to",
                                defaults={"confidence": 0.6},
                            )
                            if created:
                                edges_created += 1

                # 从 SemanticDetail 提取 SPO 三元组
                atom_ids = [a.atom_id for a in top_atoms]
                details = SemanticDetailModel.select().where(SemanticDetailModel.atom.in_(atom_ids))

                for detail in details:
                    if not detail.attr_name or not detail.attr_value:
                        continue
                    _, created = GraphEntry.get_or_create(
                        subject=detail.attr_category,
                        predicate=detail.attr_name,
                        object=detail.attr_value,
                        defaults={
                            "evidence": f"atom:{detail.atom}",
                            "confidence": 0.7,
                        },
                    )
                    if created:
                        entries_created += 1

        except Exception as e:
            logger.error(f"图谱构建阶段异常: {e}")

        if edges_created > 0 or entries_created > 0:
            logger.info(f"图谱构建: {edges_created} 条边, {entries_created} 条三元组 (atoms={atom_limit})")
        return edges_created, entries_created

    # ── 日常周期 (24h) ──────────────────────────────────────────────────

    async def _run_daily_cycle(self) -> None:
        """日常梦境周期 — 作用域: 最近 24 小时修改的原子

        Phase 1: 记忆巩固（importance≥0.6, weight≤0.4, max 50）
        Phase 2: 噪声清理（NoisePool > 7 天）
        """
        dream_run_id = self._create_dream_run("daily")
        if dream_run_id is None:
            return

        atoms_processed = 0
        noise_cleaned = 0

        try:
            atoms_processed = await self._consolidate(max_age_days=1)
            noise_cleaned = await self._clean_noise()
        except Exception as e:
            logger.exception(f"日常梦境周期异常: {e}")
            self._finalize_dream_run(dream_run_id, "failed", atoms_processed, str(e))
            return

        summary = self._build_summary(atoms_processed, noise_cleaned, 0, 0)
        self._finalize_dream_run(dream_run_id, "completed", atoms_processed, summary)
        logger.info(f"日常梦境完成: {summary}")

    # ── 每周周期 (7天) ──────────────────────────────────────────────────

    async def _run_weekly_cycle(self) -> None:
        """每周梦境周期 — 作用域: 最近 7 天修改的原子

        Phase 1: 全量巩固（max 100 个原子）
        Phase 2: 噪声清理
        Phase 3: 图谱构建（top-30 原子）
        Phase 4: 跨日模式检测 — 发现同一实体的不同类型原子，记录到 InsightPool
        Phase 5: 梦呓编织（可选）— 通过 DreamWeaver 从 NoisePool 提取洞见
        """
        dream_run_id = self._create_dream_run("weekly")
        if dream_run_id is None:
            return

        atoms_processed = 0
        noise_cleaned = 0
        edges_created = 0
        entries_created = 0
        patterns_found = 0

        # 噪声回收计数（Phase 6 产出）
        recycled_promoted = 0
        recycled_discarded = 0

        try:
            # Phase 1: 全量巩固
            atoms_processed = await self._consolidate(max_age_days=7, batch_size=100)

            # Phase 2: 噪声清理
            noise_cleaned = await self._clean_noise()

            # Phase 3: 图谱构建 (top-30)
            edges_created, entries_created = await self._build_graph(limit=30)

            # Phase 4: 跨日模式检测
            patterns_found = await self._detect_cross_day_patterns()

            # Phase 5: 梦呓编织（可选，依赖 DreamWeaver + LLM）
            weaver_insights = 0
            if self._dream_weaver is not None:
                try:
                    insights = await self._dream_weaver.weave()
                    weaver_insights = len(insights)
                except Exception as we:
                    logger.warning("梦呓编织阶段异常（降级处理）: %s", we)

            # Phase 6: 噪声回收（可选，依赖 InspirationEngine）
            try:
                from src.memory.inspiration_engine import InspirationEngine
                from src.memory.layer3_retrieval import MemoryWriter

                writer = MemoryWriter(store=self._store)
                engine = InspirationEngine(
                    store=self._store,
                    writer=writer,
                    retention_days=14,
                )
                result = await engine.recycle()
                recycled_promoted = result.get("promoted", 0)
                recycled_discarded = result.get("discarded", 0)
            except ImportError:
                logger.debug("InspirationEngine 不可用，跳过噪声回收")
            except Exception as ie:
                logger.warning("噪声回收阶段异常（降级处理）: %s", ie)

        except Exception as e:
            logger.exception(f"每周梦境周期异常: {e}")
            self._finalize_dream_run(dream_run_id, "failed", atoms_processed, str(e))
            return

        if patterns_found > 0:
            logger.info(f"跨日模式检测: 发现 {patterns_found} 个模式")
        if weaver_insights > 0:
            logger.info(f"梦呓编织: 生成 {weaver_insights} 条洞见")
        if recycled_promoted > 0:
            logger.info(f"噪声回收: 晋升 {recycled_promoted} 条，丢弃 {recycled_discarded} 条")

        summary = self._build_summary(atoms_processed, noise_cleaned, edges_created, entries_created)
        if weaver_insights:
            summary += f"，{weaver_insights}条洞见"
        if recycled_promoted:
            summary += f"，回收{recycled_promoted}条"
        self._finalize_dream_run(dream_run_id, "completed", atoms_processed, summary)
        logger.info(f"每周梦境完成: {summary}")

    async def _detect_cross_day_patterns(self) -> int:
        """跨日模式检测 — 扫描同一实体关联的不同类型原子

        查询最近 7 天的活跃原子，按实体分组；
        若某实体出现在多种 atom_type 的原子中，记录到 InsightPool。

        Returns:
            发现的跨日模式数量
        """
        patterns = 0
        recent_atoms = self._get_atoms_modified_since(7)
        if not recent_atoms:
            return 0

        # 按实体分组，记录每个实体出现的 atom_type 集合
        entity_types: dict[str, set[str]] = {}
        entity_atoms: dict[str, list[str]] = {}

        for atom in recent_atoms:
            if not atom.entities:
                continue
            try:
                entities = json.loads(atom.entities)
                if not isinstance(entities, list):
                    continue
            except (json.JSONDecodeError, TypeError):
                continue

            for entity in entities:
                e = str(entity)
                if e not in entity_types:
                    entity_types[e] = set()
                    entity_atoms[e] = []
                entity_types[e].add(atom.atom_type)
                entity_atoms[e].append(atom.atom_id)

        # 检查哪些实体有多个 atom_type
        for entity, types in entity_types.items():
            if len(types) >= 2:
                patterns += 1
                content = f"跨日模式: 实体 '{entity}' 出现在 {len(types)} 种记忆类型中 ({', '.join(sorted(types))})"
                try:
                    with memory_db:
                        InsightPool.create(
                            content=content,
                            source_atoms=json.dumps(entity_atoms[entity], ensure_ascii=False),
                            agent_name="dream_weekly",
                            confidence=0.5,
                        )
                except Exception as e:
                    logger.error(f"写入跨日模式到 InsightPool 失败: {e}")

        return patterns

    # ── 月度周期 (30天) ─────────────────────────────────────────────────

    async def _run_monthly_cycle(self) -> None:
        """月度梦境周期 — 作用域: 全部活跃原子

        Phase 1: 全量审计 — 按类型/状态/权重范围统计原子分布
        Phase 2: 画像审计 — 对每个有画像的用户，验证画像事实与存储原子的一致性
        Phase 3: 关系网络重建 — 全量图谱构建 (top-50) + 对比边数变化
        Phase 4: 健康诊断 — 检测孤儿原子、过期噪声、空分区
        Phase 5: 月度恍然大悟（InsightEngine 跨域扫描，可选依赖）
        Phase 6: 噪声回收（30天窗口，可选依赖 InspirationEngine）
        Phase 7: 生成月度总结报告
        """
        dream_run_id = self._create_dream_run("monthly")
        if dream_run_id is None:
            return

        audit_stats: dict[str, Any] = {}
        health_issues: list[str] = []

        try:
            # Phase 1: 全量审计
            audit_stats = self._audit_atom_distribution()
            logger.info(
                f"月度审计: {audit_stats.get('total_active', 0)} 个活跃原子, "
                f"{len(audit_stats.get('type_distribution', {}))} 种类型"
            )

            # Phase 2: 画像审计
            profile_discrepancies = self._audit_profiles()
            if profile_discrepancies:
                health_issues.append(f"画像差异: {profile_discrepancies} 条不匹配")

            # Phase 3: 关系网络重建
            old_edge_count = self._count_graph_edges()
            edges_created, entries_created = await self._build_graph(limit=50)
            new_edge_count = self._count_graph_edges()
            edge_delta = new_edge_count - old_edge_count
            audit_stats["edge_count_before"] = old_edge_count
            audit_stats["edge_count_after"] = new_edge_count
            audit_stats["edge_delta"] = edge_delta
            logger.info(f"关系网络重建: {old_edge_count} → {new_edge_count} 条边 ({edge_delta:+d})")

            # Phase 4: 健康诊断
            orphaned = self._count_orphaned_atoms()
            stale_noise = self._count_stale_noise(30)
            empty_partitions = audit_stats.get("empty_types", [])
            if orphaned:
                health_issues.append(f"孤儿原子: {orphaned} 个")
            if stale_noise:
                health_issues.append(f"过期噪声: {stale_noise} 条 (>30天)")
            if empty_partitions:
                health_issues.append(f"空分区: {', '.join(empty_partitions)}")

            # Phase 5: 月度恍然大悟（InsightEngine 跨域扫描）
            insight_count = 0
            try:
                from src.memory.insight_engine import InsightEngine

                engine = InsightEngine(self._store)
                insights = await engine.generate_monthly_insights()
                insight_count = len(insights)
                if insight_count > 0:
                    logger.info(f"月度恍然大悟: 发现 {insight_count} 条跨域洞察")
            except Exception as ie:
                logger.warning("月度恍然大悟阶段异常（降级处理）: %s", ie)

            # Phase 6: 噪声回收（30天窗口）
            recycled_promoted = 0
            recycled_discarded = 0
            try:
                from src.memory.inspiration_engine import InspirationEngine
                from src.memory.layer3_retrieval import MemoryWriter

                writer = MemoryWriter(store=self._store)
                engine = InspirationEngine(
                    store=self._store,
                    writer=writer,
                    retention_days=30,
                )
                result = await engine.recycle()
                recycled_promoted = result.get("promoted", 0)
                recycled_discarded = result.get("discarded", 0)
                if recycled_promoted > 0 or recycled_discarded > 0:
                    health_issues.append(f"噪声回收: 晋升{recycled_promoted}条, 丢弃{recycled_discarded}条")
                    logger.info(f"月度噪声回收: 晋升 {recycled_promoted} 条，丢弃 {recycled_discarded} 条")
            except ImportError:
                logger.debug("InspirationEngine 不可用，跳过月度噪声回收")
            except Exception as ie:
                logger.warning("月度噪声回收阶段异常（降级处理）: %s", ie)

            # Phase 7: 生成月度报告
            report = self._build_monthly_report(audit_stats, health_issues)
            if insight_count:
                report_lines = report.split("\n")
                report_lines.insert(-1, f"跨域洞察: {insight_count} 条")
                report = "\n".join(report_lines)
            if recycled_promoted:
                report_lines = report.split("\n")
                report_lines.insert(-1, f"噪声回收: 晋升{recycled_promoted}条")
                report = "\n".join(report_lines)
            logger.info(f"月度梦境报告:\n{report}")

        except Exception as e:
            logger.exception(f"月度梦境周期异常: {e}")
            self._finalize_dream_run(dream_run_id, "failed", audit_stats.get("total_active", 0), str(e))
            return

        recycle_part = f", 回收{recycled_promoted}条" if recycled_promoted else ""
        insight_part = f", {insight_count}条洞察" if insight_count else ""
        summary = (
            f"审计{audit_stats.get('total_active', 0)}原子, {len(health_issues)}个问题{insight_part}{recycle_part}"
        )
        self._finalize_dream_run(dream_run_id, "completed", audit_stats.get("total_active", 0), summary)
        logger.info(f"月度梦境完成: {summary}")

    # ── 月度审计工具 ────────────────────────────────────────────────────

    def _audit_atom_distribution(self) -> dict[str, Any]:
        """全量审计 — 统计所有内存原子按类型/状态/权重范围的分布

        Returns:
            包含统计信息的字典
        """
        stats: dict[str, Any] = {}
        try:
            with memory_db:
                total = MemoryAtomModel.select().count()
                active = MemoryAtomModel.select().where(MemoryAtomModel.status == "active").count()
                archived = MemoryAtomModel.select().where(MemoryAtomModel.status == "archived").count()
                forgotten = MemoryAtomModel.select().where(MemoryAtomModel.status == "forgotten").count()

                type_dist: dict[str, int] = {}
                for t in ("episodic", "factual", "relational", "preference", "planned"):
                    c = (
                        MemoryAtomModel.select()
                        .where(
                            MemoryAtomModel.status == "active",
                            MemoryAtomModel.atom_type == t,
                        )
                        .count()
                    )
                    if c > 0:
                        type_dist[t] = c

                weight_ranges: dict[str, int] = {
                    "low(0-0.3)": MemoryAtomModel.select()
                    .where(
                        MemoryAtomModel.status == "active",
                        MemoryAtomModel.weight < 0.3,
                    )
                    .count(),
                    "mid(0.3-0.7)": MemoryAtomModel.select()
                    .where(
                        MemoryAtomModel.status == "active",
                        MemoryAtomModel.weight >= 0.3,
                        MemoryAtomModel.weight < 0.7,
                    )
                    .count(),
                    "high(0.7-1.0)": MemoryAtomModel.select()
                    .where(
                        MemoryAtomModel.status == "active",
                        MemoryAtomModel.weight >= 0.7,
                    )
                    .count(),
                }

                # 发现没有活跃原子的空类型
                empty_types: list[str] = []
                for t in ("episodic", "factual", "relational", "preference", "planned"):
                    if (
                        MemoryAtomModel.select()
                        .where(
                            MemoryAtomModel.status == "active",
                            MemoryAtomModel.atom_type == t,
                        )
                        .count()
                        == 0
                    ):
                        empty_types.append(t)

                stats = {
                    "total": total,
                    "total_active": active,
                    "total_archived": archived,
                    "total_forgotten": forgotten,
                    "type_distribution": type_dist,
                    "weight_ranges": weight_ranges,
                    "empty_types": empty_types,
                }
        except Exception as e:
            logger.error(f"全量审计失败: {e}")
            stats = {"error": str(e)}
        return stats

    def _audit_profiles(self) -> int:
        """画像审计 — 验证画像事实是否与存储原子一致

        对有画像的用户，逐一检查各事实字段对应的记忆原子是否存在。

        Returns:
            发现的不匹配数
        """
        discrepancies = 0
        try:
            from src.memory.user_profile import ProfileStore

            profile_store = ProfileStore()
            user_ids = profile_store.list_profiles()
            if not user_ids:
                return 0

            for uid in user_ids:
                profile = profile_store.get_profile(uid)
                if not profile or not profile.facts:
                    continue
                for fact_key, fact_value in profile.facts.items():
                    matching = (
                        MemoryAtomModel.select()
                        .where(
                            MemoryAtomModel.status == "active",
                            MemoryAtomModel.content.contains(fact_value),
                        )
                        .count()
                    )
                    if matching == 0:
                        discrepancies += 1
                        logger.debug(f"画像审计: 用户 {uid} 的事实 '{fact_key}={fact_value}' 无对应记忆原子")
        except Exception as e:
            logger.error(f"画像审计失败: {e}")
        return discrepancies

    @staticmethod
    def _count_graph_edges() -> int:
        """统计当前图谱边总数

        Returns:
            边数
        """
        try:
            with memory_db:
                return GraphEdge.select().count()
        except Exception as e:
            logger.error(f"统计图谱边数失败: {e}")
            return 0

    @staticmethod
    def _count_orphaned_atoms() -> int:
        """统计孤儿原子 — 无实体、weight 为 0、或从未被访问

        Returns:
            孤儿原子数量
        """
        try:
            with memory_db:
                orphaned = (
                    MemoryAtomModel.select()
                    .where(
                        MemoryAtomModel.status == "active",
                        (
                            (MemoryAtomModel.entities.is_null())
                            | (MemoryAtomModel.entities == "")
                            | (MemoryAtomModel.entities == "[]")
                            | (MemoryAtomModel.weight == 0)
                        ),
                    )
                    .count()
                )
                return orphaned
        except Exception as e:
            logger.error(f"统计孤儿原子失败: {e}")
            return 0

    @staticmethod
    def _count_stale_noise(max_days: int) -> int:
        """统计过期噪声条目

        Args:
            max_days: 超过此天数的视为过期

        Returns:
            过期噪声数量
        """
        try:
            cutoff = datetime.datetime.now() - datetime.timedelta(days=max_days)
            with memory_db:
                return NoisePool.delete().where(NoisePool.created_at < cutoff).execute()
        except Exception as e:
            logger.error(f"统计过期噪声失败: {e}")
            return 0

    @staticmethod
    def _build_monthly_report(stats: dict[str, Any], health_issues: list[str]) -> str:
        """生成月度梦境总结报告

        Args:
            stats: 审计统计字典
            health_issues: 健康问题列表

        Returns:
            格式化的报告字符串
        """
        lines = ["═══ 月度梦境报告 ═══"]
        if "error" in stats:
            lines.append(f"审计异常: {stats['error']}")
            return "\n".join(lines)

        lines.append(f"原子总量: {stats.get('total', 0)}")
        lines.append(
            f"活跃: {stats.get('total_active', 0)} | "
            f"归档: {stats.get('total_archived', 0)} | "
            f"遗忘: {stats.get('total_forgotten', 0)}"
        )

        type_dist = stats.get("type_distribution", {})
        if type_dist:
            type_parts = [f"{k}: {v}" for k, v in type_dist.items()]
            lines.append(f"类型分布: {' | '.join(type_parts)}")

        weight_ranges = stats.get("weight_ranges", {})
        if weight_ranges:
            wr_parts = [f"{k}: {v}" for k, v in weight_ranges.items()]
            lines.append(f"权重分布: {' | '.join(wr_parts)}")

        edge_before = stats.get("edge_count_before", 0)
        edge_after = stats.get("edge_count_after", 0)
        if edge_before or edge_after:
            lines.append(f"关系网络: {edge_before} → {edge_after} 条边")

        if health_issues:
            lines.append(f"健康问题 ({len(health_issues)}):")
            for issue in health_issues:
                lines.append(f"  • {issue}")
        else:
            lines.append("健康状态: 无异常")

        lines.append("═══ 报告结束 ═══")
        return "\n".join(lines)

    # ── 工具方法 ────────────────────────────────────────────────────────

    @staticmethod
    def _build_summary(consolidated: int, noise_cleaned: int, edges: int, entries: int) -> str:
        """生成梦境运行摘要文本

        Args:
            consolidated: 巩固的原子数
            noise_cleaned: 清理的噪声数
            edges: 创建的图谱边数
            entries: 创建的三元组数

        Returns:
            中文摘要字符串
        """
        parts: list[str] = []
        if consolidated:
            parts.append(f"巩固{consolidated}条记忆")
        if noise_cleaned:
            parts.append(f"清理{noise_cleaned}条噪声")
        if edges:
            parts.append(f"构建{edges}条图谱边")
        if entries:
            parts.append(f"提取{entries}条三元组")
        return "，".join(parts) if parts else "无操作"

    def _finalize_dream_run(
        self,
        dream_run_id: int,
        status: str,
        atoms_processed: int,
        summary_or_error: str,
    ) -> None:
        """更新 DreamRun 运行记录

        Args:
            dream_run_id: DreamRun 记录 ID
            status: 结束状态（completed / failed）
            atoms_processed: 处理的原子数
            summary_or_error: 成功时传入摘要，失败时传入错误信息
        """
        try:
            with memory_db:
                DreamRun.update(
                    status=status,
                    end_time=datetime.datetime.now(),
                    atoms_processed=atoms_processed,
                    summary=summary_or_error,
                ).where(DreamRun.id == dream_run_id).execute()
        except Exception as e:
            logger.error(f"更新 DreamRun 记录失败 (id={dream_run_id}): {e}")
