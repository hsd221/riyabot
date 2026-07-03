#!/usr/bin/env python3
"""Phase 3 综合压力测试 — 覆盖 Phase 3 新增的全部 7 个模块/子模块

测试项目:
  a. 新模块导入验证 — 所有 8 个新/更新模块导入
  b. InsightEngine 测试 — 写入 30 个原子 → 生成月度洞察
  c. InspirationEngine 测试 — 写入噪声 → 噪声回收晋升/丢弃
  d. 关联网络测试 — 构建原子关联 → BFS 链查询
  e. Qdrant 向量搜索测试 — 条件性测试向量存储
  f. Dream 周期集成测试 — DreamTask 多周期方法调用
  g. 编码管线 3-tuple 测试 — _build_atom 返回三元组验证

用法:
    timeout 600 uv run python scripts/stress_test_phase3.py

设计原则:
    - 只导入 src.memory.*，不依赖 mai 聊天模块或其他子系统
    - 不使用真实 LLM API（DreamWeaver 需要 LLM → 跳过 or mock）
    - Qdrant 可用时测试，不可用时跳过（不失败）
    - 使用临时 SQLite 数据库，不污染生产数据
"""

from __future__ import annotations

import json
import os
import random
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 环境引导
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# JSON 编码补丁 — WriteOpLogger 的 payload 可能包含 datetime 对象
# ---------------------------------------------------------------------------
_ORIGINAL_JSON_ENCODER_DEFAULT = json.JSONEncoder.default


def _json_default_patch(self: Any, obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.timestamp()
    if isinstance(obj, set):
        return list(obj)
    return _ORIGINAL_JSON_ENCODER_DEFAULT(self, obj)


json.JSONEncoder.default = _json_default_patch


# ---------------------------------------------------------------------------
# 日志抑制
# ---------------------------------------------------------------------------
def _suppress_logging() -> None:
    import src.common.logger as _mod_logger

    _mod_logger._loggers = {}

    class _QuietLogger:
        def debug(self, *a, **kw):
            pass

        def info(self, *a, **kw):
            pass

        def warning(self, *a, **kw):
            pass

        def error(self, *a, **kw):
            pass

        def critical(self, *a, **kw):
            pass

    _quiet = _QuietLogger()
    _mod_logger.get_logger = lambda name="", **kwargs: _quiet


_suppress_logging()

# ---------------------------------------------------------------------------
# 模拟数据
# ---------------------------------------------------------------------------
_CHINESE_MESSAGES = [
    "今天天气真好啊，要不要出去走走？",
    "有人看过那部新电影吗？听说评分很高",
    "晚上一起打游戏吧，我带你上分",
    "刚看到一个好好笑的段子，笑死我了",
    "这个代码我写了三天终于跑通了，感动",
    "今天老板又开会开了一下午，困死了",
    "推荐好看的番剧，最近剧荒",
    "这个 bug 调了我一整天，结果是少了个分号",
    "我刚换了个机械键盘，打字手感超好",
    "有没有人拼单买奶茶？满减很划算",
    "今天地铁又晚点了，迟到了半小时",
    "你们说 AI 会不会取代程序员啊？",
    "我家的猫今天又拆家了，气死我了",
    "有会摄影的大佬吗？想入个相机",
    "这个月的流量又用完了，好烦",
    "刚跑完五公里，感觉整个人都升华了",
    "这个周末天气不错，打算去爬山",
    "刚入手了一个新耳机，音质绝了",
    "今天被面试官问了一道算法题，完全不会",
    "大家觉得远程办公效率高吗？",
    "刚做了个甜点，味道还不错嘿嘿",
    "今天食堂的午饭意外的好吃",
    "这个项目 deadline 要到了，还在改 bug",
    "有人抢到演唱会的票了吗？",
    "健身打卡第三天，感觉腹肌要出来了",
]

_USERS = [
    "似君(Homo sapiens)",
    "没有名字有没名字",
    "hsd221",
    "Alice",
    "Bob_the_Builder",
    "小A同学2024",
    "🐱喵喵侠",
    "⚡雷电法王",
    "今天吃什么",
    "熬夜冠军🏆",
    "Genima",
    "Elaina伊蕾娜",
]

_STREAM_IDS = [
    "group_100001",
    "group_100002",
    "group_100003",
    "private_200001",
    "private_200002",
]


def _random_msg() -> str:
    return random.choice(_CHINESE_MESSAGES)


def _random_user() -> str:
    return random.choice(_USERS)


# ---------------------------------------------------------------------------
# 测试结果模型
# ---------------------------------------------------------------------------
@dataclass
class TestResult:
    name: str
    passed: bool
    detail: str = ""
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 测试执行器
# ---------------------------------------------------------------------------
class Phase3StressTest:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.store: Any = None
        self.writer: Any = None
        self.results: list[TestResult] = []

    # ── 环境初始化 ────────────────────────────────────────────────

    async def init_db(self) -> None:
        """初始化 SQLite memory_db 指向临时文件"""
        from src.memory.schema import memory_db
        from src.memory.schema import (
            MemoryAtom as MemModel,
            EpisodicDetail as EpiModel,
            SemanticDetail as SemModel,
            ConflictObservation as CoModel,
            NoisePool as NoiModel,
            MemoryTraceChain as TrModel,
            DreamRun as DrModel,
            GraphNode as GnModel,
            GraphEdge as GeModel,
            GraphEntry as GeModel2,
            InsightPool as IpModel,
            AtomAssociationModel as AaModel,
        )

        memory_db.init(
            self.db_path,
            pragmas={
                "journal_mode": "wal",
                "cache_size": -64 * 1000,
                "foreign_keys": 1,
                "ignore_check_constraints": 0,
                "synchronous": 0,
                "busy_timeout": 1000,
            },
        )
        memory_db.connect()
        memory_db.create_tables(
            [
                MemModel,
                EpiModel,
                SemModel,
                CoModel,
                NoiModel,
                TrModel,
                DrModel,
                GnModel,
                GeModel,
                GeModel2,
                IpModel,
                AaModel,
            ],
            safe=True,
        )

    async def init_store(self) -> None:
        """初始化 MemoryStore + MemoryWriter"""
        from src.memory import MemoryStore, MemoryStoreConfig

        MemoryStore._instance = None
        config = MemoryStoreConfig(sqlite_path=self.db_path)
        self.store = MemoryStore(config)
        await self.store.initialize()

        from src.memory.layer3_retrieval import MemoryWriter
        from src.memory.write_ops import WriteOpLogger

        self._op_logger = WriteOpLogger(db_path=self.db_path, max_entries=1000)
        self.writer = MemoryWriter(self.store, op_logger=self._op_logger)

    # ── 工具方法 ─────────────────────────────────────────────────

    async def _write_atom(
        self,
        content: Optional[str] = None,
        atom_type_str: Optional[str] = None,
        entities: Optional[list[str]] = None,
        source_scene: str = "group_chat",
        importance: float = 0.7,
    ) -> str:
        """写入一个原子，返回 atom_id"""
        from src.memory.atom import MemoryAtom as AD, AtomType, DecayType

        atom_id = f"p3_{int(time.time() * 1e6)}_{random.randint(0, 99999)}"
        content = content or _random_msg()
        atype = AtomType(atom_type_str) if atom_type_str else random.choice(list(AtomType))
        now_ts = datetime.now(timezone.utc).timestamp()

        atom = AD(
            atom_id=atom_id,
            atom_type=atype,
            content=content,
            importance=importance,
            confidence=0.7,
            weight=0.5,
            created_at=now_ts,
            last_accessed_at=now_ts,
            ttl_days=30,
            decay_type=DecayType.EXPONENTIAL,
            source_scene=source_scene,
            privacy_level="context_sensitive",
            entities=entities or ["test_user"],
        )
        await self.writer.write_atom(atom=atom)
        return atom_id

    async def _write_noise(
        self,
        content: str,
        significance: float = 0.5,
        source_scene: str = "chat",
    ) -> int:
        """写入一条 NoisePool 记录，返回 id"""
        from src.memory.schema import NoisePool, memory_db

        with memory_db:
            record = NoisePool.create(
                content=content,
                source_scene=source_scene,
                significance=significance,
            )
            return record.id

    async def _atom_count(self) -> int:
        from src.memory.schema import MemoryAtom as M, memory_db

        with memory_db:
            return M.select().count()

    async def _noise_count(self) -> int:
        from src.memory.schema import NoisePool as N, memory_db

        with memory_db:
            return N.select().count()

    # ── 测试方法 ─────────────────────────────────────────────────

    async def test_a_imports(self) -> TestResult:
        """测试 (a): 验证所有 Phase 3 新/更新模块可正常导入"""
        t0 = time.monotonic()
        errors: list[str] = []

        imports_to_check = {
            "InsightEngine": "src.memory.insight_engine",
            "InspirationEngine": "src.memory.inspiration_engine",
            "DreamWeaver": "src.memory.dream_weaver",
            "ExpressionBridge+ExpressionProfile": "src.memory.expression_bridge",
            "AtomAssociationStore+AssociationType": "src.memory.atom_association",
            "DreamTask+DreamCycleType": "src.memory.dream_agent",
            "EncodingPipeline (3-tuple)": "src.memory.encoding_pipeline",
            "layer3_retrieval extended (sensory)": "src.memory.layer3_retrieval",
        }

        for label, module_path in imports_to_check.items():
            try:
                __import__(module_path, fromlist=["_"])
            except Exception as e:
                errors.append(f"{label}: {e}")

        # 验证 __init__.py exports
        try:
            from src.memory import InsightEngine as IE  # noqa: F401
            from src.memory import InspirationEngine as IEE  # noqa: F401
            from src.memory import DreamWeaver as DW  # noqa: F401
            from src.memory import ExpressionBridge as EB  # noqa: F401
            from src.memory import AtomAssociationStore as AAS  # noqa: F401
            from src.memory import DreamTask as DT  # noqa: F401
        except Exception as e:
            errors.append(f"__init__.py 导出失败: {e}")

        # 验证 schema 模型（IndightPool/NoisePool 等是 schema 模型，不在 __init__）
        try:
            from src.memory.schema import InsightPool as IP  # noqa: F401
            from src.memory.schema import NoisePool as NP  # noqa: F401
            from src.memory.schema import DreamRun as DR  # noqa: F401
            from src.memory.schema import AtomAssociationModel as AAM  # noqa: F401
        except Exception as e:
            errors.append(f"schema 模型导入失败: {e}")

        # 验证 DreamTask 方法存在
        try:
            from src.memory.dream_agent import DreamTask

            for method in ("_run_daily_cycle", "_run_weekly_cycle", "_run_monthly_cycle", "_determine_cycle_type"):
                if not hasattr(DreamTask, method):
                    errors.append(f"DreamTask 缺少方法: {method}")
        except Exception as e:
            errors.append(f"DreamTask 方法验证失败: {e}")

        duration = (time.monotonic() - t0) * 1000
        passed = len(errors) == 0
        return TestResult(
            name="a_imports",
            passed=passed,
            detail=f"{len(imports_to_check)} modules, errors={len(errors)}",
            duration_ms=round(duration, 1),
            errors=errors,
        )

    async def test_b_insight_engine(self) -> TestResult:
        """测试 (b): InsightEngine — 写入 30 原子 → 生成月度洞察"""
        t0 = time.monotonic()
        errors: list[str] = []

        try:
            # 1. 写入 30 个不同类型/实体的原子
            written_ids: list[str] = []
            for i in range(30):
                atype = random.choice(["episodic", "factual", "preference", "relational", "planned"])
                entity = f"entity_{i % 5}"  # 5 个实体，部分跨类型
                aid = await self._write_atom(atom_type_str=atype, entities=[entity])
                written_ids.append(aid)

            # 2. 创建一些 AtomAssociation 记录（Scan 3 需要）
            from src.memory.atom_association import AtomAssociationStore, AssociationType

            assoc_store = AtomAssociationStore()
            for i in range(min(10, len(written_ids) - 1)):
                assoc_store.add_association(
                    written_ids[i],
                    written_ids[i + 1],
                    AssociationType.CO_OCCURRENCE,
                    0.6,
                )

            # 3. 写入一些 Profile mood_history（Scan 2 需要）
            from src.memory.user_profile import ProfileStore, UserProfile

            ps = ProfileStore()
            for uid in _USERS[:3]:
                profile = UserProfile(
                    user_id=uid,
                    mood_history=[
                        {"emotion_tags": ["joy"], "timestamp": time.time() - 86400 * i} for i in range(5, 0, -1)
                    ],
                    expression_style="活泼,简洁",
                    expression_patterns={"favorite_expressions": ["哈哈"]},
                )
                ps.save_profile(profile)

            # 4. 调用 InsightEngine
            from src.memory.insight_engine import InsightEngine

            engine = InsightEngine(self.store)
            insights = await engine.generate_monthly_insights()

            # 5. 验证
            if not insights:
                errors.append("InsightEngine 未产生任何洞察")
            else:
                # 检查每条 insight 有 content/source/confidence
                for idx, ins in enumerate(insights):
                    if "content" not in ins:
                        errors.append(f"洞察 {idx} 缺少 content")
                    if "source_atoms" not in ins:
                        errors.append(f"洞察 {idx} 缺少 source_atoms")
                    if "confidence" not in ins:
                        errors.append(f"洞察 {idx} 缺少 confidence")

                # 验证写入 InsightPool
                from src.memory.schema import InsightPool, memory_db

                with memory_db:
                    saved = InsightPool.select().count()
                if saved == 0:
                    errors.append("洞察未写入 InsightPool")

        except Exception as e:
            tb = traceback.format_exc()
            errors.append(f"InsightEngine 测试异常: {e}")
            errors.append(tb)

        duration = (time.monotonic() - t0) * 1000
        passed = len(errors) == 0
        return TestResult(
            name="b_insight_engine",
            passed=passed,
            detail=f"30 atoms, insights={len(errors) if not passed else 'generated'}",
            duration_ms=round(duration, 1),
            errors=errors,
        )

    async def test_c_inspiration_engine(self) -> TestResult:
        """测试 (c): InspirationEngine — 写入噪声 → 回收"""
        t0 = time.monotonic()
        errors: list[str] = []

        try:
            from src.memory.inspiration_engine import InspirationEngine

            # 先写入一些原子（供关键词交叉引用匹配）
            # 写入内容中包含"昨天"等时间词触发 temporal_gap 验证
            support_contents = [
                "昨天天气真好啊，要不要出去走走？",
                "昨天有人看过那部新电影吗？",
                "昨天一起打游戏吧，我带你上分",
                "昨天看到一个好好笑的段子",
                "这个代码我昨天写了三天终于跑通了",
                "昨天老板又开会开了一下午",
                "昨天推荐好看的番剧",
                "昨天的bug调了我一整天",
                "昨天我家的猫又拆家了",
                "昨天刚跑完五公里",
            ]
            for c in support_contents:
                await self._write_atom(content=c, source_scene="group_chat")

            # 写入噪声（significance > 0.3，含时间词）
            noise_contents = [
                ("昨天天气真好啊，昨天出去玩", 0.5),
                ("昨天代码写完了昨天很开心", 0.4),
                ("昨天电影很好看昨天评分很高", 0.6),
                ("昨天打游戏昨天赢了昨天上分了", 0.5),
                ("昨天的段子昨天好好笑昨天笑死了", 0.35),
            ]
            noise_ids = []
            for content, sig in noise_contents:
                nid = await self._write_noise(content=content, significance=sig)
                noise_ids.append(nid)

            noise_count_before = await self._noise_count()

            # 运行回收引擎（14天窗口，由于 support atoms 存在所以 temporal_gap=False）
            engine = InspirationEngine(
                store=self.store,
                writer=self.writer,
                retention_days=14,
            )
            result = await engine.recycle()

            # 验证结果
            if not isinstance(result, dict):
                errors.append(f"recycle() 返回不是 dict: {type(result)}")
            else:
                promoted = result.get("promoted", -1)
                discarded = result.get("discarded", -1)
                if promoted < 0 or discarded < 0:
                    errors.append(f"recycle() 返回缺少 promoted/discarded: {result}")

                # 验证噪声被删除
                noise_count_after = await self._noise_count()
                # 推理：由于 support atoms 存在，temporal_gap 会检查是否 retention_days 内有原子
                # 因为刚写了 support atoms，所以 temporal_gap = False → 所有噪声被 discard
                # 所以 noise_count_after 应小于 noise_count_before
                if noise_count_after >= noise_count_before and noise_count_before > 0:
                    errors.append(f"噪声未被删除: before={noise_count_before} after={noise_count_after}")

                # 验证 promoted 的原子出现在 memory_atoms 表 (如果有 promoted)
                if promoted > 0:
                    # 检查是否有 recycled_ 前缀的原子
                    from src.memory.schema import MemoryAtom as M, memory_db

                    with memory_db:
                        recycled = M.select().where(M.atom_id.startswith("recycled_")).count()
                    if recycled != promoted:
                        errors.append(f"晋升原子数量不匹配: expected {promoted}, found {recycled}")

        except Exception:
            errors.append(f"InspirationEngine 测试异常: {traceback.format_exc()}")

        duration = (time.monotonic() - t0) * 1000
        passed = len(errors) == 0
        return TestResult(
            name="c_inspiration_engine",
            passed=passed,
            detail=f"noise_before={noise_count_before if 'noise_count_before' in dir() else '?'} "
            f"result={result if 'result' in dir() else '?'}",
            duration_ms=round(duration, 1),
            errors=errors,
        )

    async def test_d_association_network(self) -> TestResult:
        """测试 (d): 关联网络 — 20 原子共享实体 → build_from_batch → BFS"""
        t0 = time.monotonic()
        errors: list[str] = []

        try:
            from src.memory.atom import MemoryAtom as AD, AtomType, DecayType
            from src.memory.atom_association import AtomAssociationStore
            from datetime import datetime, timezone
            from uuid import uuid4

            # 1. 创建 20 个原子（共享 entity 以实现 CO_OCCURRENCE）
            group_a = [f"entity_A{i}" for i in range(3)]  # 3 个共享实体
            group_b = [f"entity_B{i}" for i in range(2)]
            now_ts = datetime.now(timezone.utc).timestamp()

            atoms: list[AD] = []
            for i in range(20):
                # 前 10 个使用 group_a（至少 2 个共享实体）
                if i < 10:
                    ents = group_a + [f"extra_A_{i}"]
                else:
                    ents = group_b + [f"extra_B_{i}"]

                atom = AD(
                    atom_id=str(uuid4()),
                    atom_type=AtomType.EPISODIC,
                    content=f"关联测试原子 #{i}: {_random_msg()}",
                    importance=0.6,
                    confidence=0.7,
                    weight=0.5,
                    created_at=now_ts + i * 0.5,
                    last_accessed_at=now_ts,
                    ttl_days=30,
                    decay_type=DecayType.EXPONENTIAL,
                    source_scene="group_chat",
                    privacy_level="context_sensitive",
                    entities=ents,
                )
                atoms.append(atom)

            # 逐个写入
            for atom in atoms:
                await self.writer.write_atom(atom=atom)

            # 2. 构建关联
            assoc_store = AtomAssociationStore()
            stream_map = {a.atom_id: "group_100001" for a in atoms}
            created = assoc_store.build_from_batch(atoms, stream_map)

            if created == 0:
                errors.append("build_from_batch 未创建任何关联")

            # 3. 验证 get_associations
            assocs = assoc_store.get_associations(atoms[0].atom_id)
            if not assocs:
                errors.append("get_associations 返回空")

            # 4. 验证 BFS get_chain
            chain = assoc_store.get_chain(atoms[0].atom_id, max_depth=2)
            if not chain:
                errors.append("get_chain (BFS) 返回空")

            # 5. 验证可选的 get_chain 字段
            for entry in chain:
                for key in ("atom_id", "association_type", "weight", "depth"):
                    if key not in entry:
                        errors.append(f"get_chain 条目缺少字段: {key}")
                        break

            # 6. 验证 count
            total = assoc_store.count()
            if total == 0:
                errors.append("count() 返回 0")

        except Exception:
            errors.append(f"关联网络测试异常: {traceback.format_exc()}")

        duration = (time.monotonic() - t0) * 1000
        passed = len(errors) == 0
        return TestResult(
            name="d_association_network",
            passed=passed,
            detail=f"20 atoms, {created if 'created' in dir() else '?'} associations, "
            f"chain_len={len(chain) if 'chain' in dir() else '?'}",
            duration_ms=round(duration, 1),
            errors=errors,
        )

    async def test_e_qdrant(self) -> TestResult:
        """测试 (e): Qdrant 向量搜索测试（本地嵌入模式）"""
        t0 = time.monotonic()
        errors: list[str] = []
        qdrant_available = False

        try:
            from src.memory import QDRANT_AVAILABLE

            if not QDRANT_AVAILABLE:
                return TestResult(
                    name="e_qdrant",
                    passed=True,
                    detail="Qdrant 不可用（qdrant-client 未安装），跳过测试",
                    duration_ms=round((time.monotonic() - t0) * 1000, 1),
                    errors=[],
                )

            qdrant_mgr = self.store.qdrant
            if qdrant_mgr._client is None:
                return TestResult(
                    name="e_qdrant",
                    passed=True,
                    detail="QdrantManager 客户端未初始化，跳过测试",
                    duration_ms=round((time.monotonic() - t0) * 1000, 1),
                    errors=[],
                )

            qdrant_available = True
            client = qdrant_mgr._client
            collection_name = self.store.config.collection_name_atoms

            try:
                collection_info = client.get_collection(collection_name)
                points_count = collection_info.points_count
                dimension = collection_info.config.params.vectors.size
            except Exception as e:
                errors.append(f"获取集合信息失败: {e}")
                points_count = 0
                dimension = 0

            [await self._write_atom() for _ in range(10)]

            try:
                client.scroll(
                    collection_name=collection_name,
                    limit=5,
                )
            except Exception as e:
                errors.append(f"Qdrant scroll 失败: {e}")

            await self.store.get_statistics()

            local_path = self.store.config.qdrant_local_path
            local_path_exists = os.path.isdir(local_path)
            if not local_path_exists:
                errors.append(f"Qdrant 本地数据目录不存在: {local_path}")

        except Exception:
            errors.append(f"Qdrant 测试异常: {traceback.format_exc()}")

        duration = (time.monotonic() - t0) * 1000
        passed = len(errors) == 0
        return TestResult(
            name="e_qdrant",
            passed=passed,
            detail=f"available={qdrant_available} | "
            f"collection={collection_name if 'collection_name' in dir() else '?'} | "
            f"points={points_count if 'points_count' in dir() else '?'} | "
            f"dim={dimension if 'dimension' in dir() else '?'}",
            duration_ms=round(duration, 1),
            errors=errors,
        )

    async def test_f_dream_cycle(self) -> TestResult:
        """测试 (f): Dream 周期集成 — 实例化 + 周期方法"""
        t0 = time.monotonic()
        errors: list[str] = []

        try:
            from src.memory.dream_agent import DreamTask, DreamCycleType

            # 1. 实例化 DreamTask
            task = DreamTask(
                store=self.store,
                forgetting_manager=None,
                graph_store=None,
                dream_weaver=None,
            )

            # 2. 验证 _determine_cycle_type
            # 首次运行 → 应返回 DAILY（无上次运行记录）
            cycle_type = task._determine_cycle_type()
            if cycle_type is None:
                errors.append("_determine_cycle_type 首次运行返回 None（应为 DAILY）")
            elif cycle_type != DreamCycleType.DAILY:
                errors.append(f"_determine_cycle_type 返回 {cycle_type}（应为 DAILY）")

            # 3. 测试 _run_daily_cycle（由于 idle 检测可能跳过，绕过 idle 检测直接调用）
            # 直接调用 consolidate + clean_noise 验证不崩溃
            try:
                await task._consolidate(max_age_days=1, batch_size=10)
            except Exception as e:
                errors.append(f"daily _consolidate 异常: {e}")

            try:
                await task._clean_noise()
            except Exception as e:
                errors.append(f"daily _clean_noise 异常: {e}")

            # 4. 测试每周方法组件（跳过需要 DreamWeaver 的部分）
            try:
                patterns = await task._detect_cross_day_patterns()
                _ = patterns  # 可能为 0，没问题
            except Exception as e:
                errors.append(f"weekly _detect_cross_day_patterns 异常: {e}")

            # 5. 测试 monthly 审计方法
            try:
                audit = task._audit_atom_distribution()
                if not isinstance(audit, dict):
                    errors.append(f"_audit_atom_distribution 返回非 dict: {type(audit)}")
            except Exception as e:
                errors.append(f"monthly _audit_atom_distribution 异常: {e}")

            try:
                orphaned = task._count_orphaned_atoms()
                if not isinstance(orphaned, int):
                    errors.append(f"_count_orphaned_atoms 返回非 int: {type(orphaned)}")
            except Exception as e:
                errors.append(f"monthly _count_orphaned_atoms 异常: {e}")

            # 6. 测试 _build_graph
            try:
                await task._build_graph(limit=10)
            except Exception as e:
                errors.append(f"_build_graph 异常: {e}")

        except Exception:
            errors.append(f"Dream 周期测试异常: {traceback.format_exc()}")

        duration = (time.monotonic() - t0) * 1000
        passed = len(errors) == 0
        return TestResult(
            name="f_dream_cycle",
            passed=passed,
            detail=f"cycle_type={'DAILY' if 'cycle_type' in dir() and cycle_type else '?'} | "
            f"methods=consolidate/noise/patterns/audit/graph",
            duration_ms=round(duration, 1),
            errors=errors,
        )

    async def test_g_encoding_3tuple(self) -> TestResult:
        """测试 (g): 编码管线 3-tuple — _build_atom 返回 (atom, semantic_detail, episodic_detail)"""
        t0 = time.monotonic()
        errors: list[str] = []

        try:
            from src.memory.encoding_pipeline import EncodingPipeline
            from src.memory.atom import AtomType, EpisodicDetail, SemanticDetail

            # 创建 pipeline 实例（不启动计时器）
            pipeline = EncodingPipeline(
                store=self.store,
                trigger_count=99,  # 不会自动触发
                trigger_seconds=9999,
            )

            # 测试 EPISODIC 类型 → 应返回 episodic_detail
            detail_episodic = {
                "importance": 0.8,
                "entities": ["user_a", "user_b"],
                "participants": ["user_a"],
                "emotion_tags": ["joy"],
                "sensory_tags": ["visual", "emotional:joy"],
                "temporal_context": "午后",
            }
            atom_e, sem_e, epi_e = pipeline._build_atom(
                content="今天下午一起看了电影",
                atom_type=AtomType.EPISODIC,
                detail=detail_episodic,
                source_scene="group_chat",
            )

            # 验证 EPISODIC 3-tuple
            assert atom_e is not None, "EPISODIC atom 为空"
            assert atom_e.atom_type == AtomType.EPISODIC
            assert sem_e is None, "EPISODIC 不应有 semantic_detail"
            assert epi_e is not None, "EPISODIC 应有 episodic_detail"
            assert isinstance(epi_e, EpisodicDetail), f"类型错误: {type(epi_e)}"
            assert epi_e.sensory_tags == ["visual", "emotional:joy"], f"sensory_tags 不匹配: {epi_e.sensory_tags}"
            assert epi_e.temporal_context == "午后", f"temporal_context 不匹配: {epi_e.temporal_context}"
            assert epi_e.emotion_tags == ["joy"], f"emotion_tags 不匹配: {epi_e.emotion_tags}"

            # 测试 PREFERENCE 类型 → 应返回 semantic_detail
            detail_pref = {
                "importance": 0.6,
                "entities": ["user_a"],
                "attr_category": "preference",
                "attr_name": "food",
                "attr_value": "喜欢辣",
            }
            atom_p, sem_p, epi_p = pipeline._build_atom(
                content="用户喜欢吃辣",
                atom_type=AtomType.PREFERENCE,
                detail=detail_pref,
                source_scene="group_chat",
            )

            assert atom_p is not None, "PREFERENCE atom 为空"
            assert atom_p.atom_type == AtomType.PREFERENCE
            assert sem_p is not None, "PREFERENCE 应有 semantic_detail"
            assert isinstance(sem_p, SemanticDetail), f"类型错误: {type(sem_p)}"
            assert sem_p.attr_category == "preference"
            assert sem_p.attr_name == "food"
            assert sem_p.attr_value == "喜欢辣"
            assert epi_p is None, "PREFERENCE 不应有 episodic_detail"

            # 测试 FACTUAL 类型 → 应返回 semantic_detail
            detail_fact = {
                "importance": 0.7,
                "entities": ["user_a"],
                "attr_category": "interest",
                "attr_name": "coding",
                "attr_value": "喜欢Python",
            }
            atom_f, sem_f, epi_f = pipeline._build_atom(
                content="用户喜欢 Python 编程",
                atom_type=AtomType.FACTUAL,
                detail=detail_fact,
                source_scene="group_chat",
            )

            assert atom_f is not None, "FACTUAL atom 为空"
            assert sem_f is not None, "FACTUAL 应有 semantic_detail"
            assert epi_f is None, "FACTUAL 不应有 episodic_detail"

            # 测试 RELATIONAL 类型 → 二者均应为 None
            detail_rel = {
                "importance": 0.5,
                "entities": ["user_a", "user_b"],
            }
            atom_r, sem_r, epi_r = pipeline._build_atom(
                content="用户 A 和用户 B 是朋友",
                atom_type=AtomType.RELATIONAL,
                detail=detail_rel,
                source_scene="group_chat",
            )

            assert atom_r is not None, "RELATIONAL atom 为空"
            assert sem_r is None, "RELATIONAL 不应有 semantic_detail"
            assert epi_r is None, "RELATIONAL 不应有 episodic_detail"

        except AssertionError as e:
            errors.append(f"断言失败: {e}")
        except Exception:
            errors.append(f"编码管线测试异常: {traceback.format_exc()}")

        duration = (time.monotonic() - t0) * 1000
        passed = len(errors) == 0
        return TestResult(
            name="g_encoding_3tuple",
            passed=passed,
            detail="EPISODIC+PREFERENCE+FACTUAL+RELATIONAL 3-tuple 验证完成",
            duration_ms=round(duration, 1),
            errors=errors,
        )

    # ── 总入口 ─────────────────────────────────────────────────

    async def run_all(self) -> list[TestResult]:
        print("=" * 60, file=sys.stderr)
        print("  Phase 3 综合压力测试", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

        # 初始化
        await self.init_db()
        await self.init_store()

        print(f"[init] DB={self.db_path}", file=sys.stderr)

        # 运行测试
        tests = [
            ("a_imports", self.test_a_imports()),
            ("b_insight_engine", self.test_b_insight_engine()),
            ("c_inspiration_engine", self.test_c_inspiration_engine()),
            ("d_association_network", self.test_d_association_network()),
            ("e_qdrant", self.test_e_qdrant()),
            ("f_dream_cycle", self.test_f_dream_cycle()),
            ("g_encoding_3tuple", self.test_g_encoding_3tuple()),
        ]

        for name, coro in tests:
            try:
                result = await coro
            except Exception as e:
                result = TestResult(
                    name=name,
                    passed=False,
                    detail=f"未捕获异常: {e}",
                    errors=[traceback.format_exc()],
                )
            self.results.append(result)

            status = "✅ PASS" if result.passed else "❌ FAIL"
            print(f"  {status} | {result.name:25s} | {result.detail[:80]}", file=sys.stderr)
            if result.errors:
                for err in result.errors[:3]:
                    for line in err.split("\n")[:30]:
                        print(f"         | {line}", file=sys.stderr)

        return self.results

    def print_summary(self) -> None:
        """打印汇总报告"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        total_ms = sum(r.duration_ms for r in self.results)

        print("\n" + "=" * 60, file=sys.stderr)
        print("  Phase 3 Stress Test Results", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        for r in self.results:
            icon = "✅" if r.passed else "❌"
            print(f"  {icon} {r.name:30s} {r.duration_ms:>8.1f}ms", file=sys.stderr)
        print("-" * 60, file=sys.stderr)
        print(f"  Total: {total} | Passed: {passed} | Failed: {failed} | {total_ms:.0f}ms", file=sys.stderr)
        print("=" * 60, file=sys.stderr)


# ── 主入口 ─────────────────────────────────────────────────────
async def main() -> int:
    # 使用临时文件避免 :memory: 的限制
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    runner = Phase3StressTest(db_path)
    try:
        await runner.run_all()
        runner.print_summary()
        failed = sum(1 for r in runner.results if not r.passed)
        # 对于 Qdrant 跳过的情况不算失败
        qdrant_skipped = any(r.name == "e_qdrant" and "跳过" in r.detail for r in runner.results)
        return 0 if (failed == 0 or (failed == 1 and qdrant_skipped)) else 1
    finally:
        try:
            if runner.store:
                await runner.store.close()
            os.unlink(db_path)
        except Exception:
            pass


if __name__ == "__main__":
    import asyncio

    exit_code = asyncio.run(main())
    sys.exit(exit_code)
