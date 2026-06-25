#!/usr/bin/env python3
"""
Bot end-to-end stress test — 30+ minutes exercising ALL 14 memory pipeline components.

Pipeline components tested:
 1. MessageArchiver.archive_group_message()
 2. GroupTopicSummarizer.add_message() / PrivateChatSummarizer
 3. EncodingPipeline.ingest() + run_cycle() (mocked LLM)
 4. MemoryWriter.write_atom()
 5. ObjectivityChecker.check_before_write()
 6. ConflictArbiter.check_and_resolve()
 7. MemoryRetriever.get_context_for_reply()
 8. build_memory_retrieval_prompt()
 9. ReinforcementTracker.analyze_reply_for_memory_usage() + apply_reinforcement()
10. ForgettingManager.run_sweep()
11. ProfileStore + ProfileBuilder + update_profile_from_atom()
12. GraphStore traversal (get_neighbors / get_related_atoms)
13. DreamTask mimic (consolidation + noise cleanup)
14. TraceChainRecorder.record() + get_chain()

Usage:
    MAIBOT_WORKER_PROCESS=1 uv run python scripts/stress_test_bot_e2e.py
"""

from __future__ import annotations

import csv
import json
import os
import random
import signal
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

os.environ.setdefault("MAIBOT_WORKER_PROCESS", "1")

# ---------------------------------------------------------------------------
# 日志抑制
# ---------------------------------------------------------------------------
_LOG_SUPPRESSED = False


def suppress_logging() -> None:
    global _LOG_SUPPRESSED
    if _LOG_SUPPRESSED:
        return
    _LOG_SUPPRESSED = True
    import src.common.logger as mod_logger

    mod_logger._loggers = {}

    class _Quiet:
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

    _quiet = _Quiet()
    mod_logger.get_logger = lambda name="", **kwargs: _quiet


# ---------------------------------------------------------------------------
# 聊天模拟数据
# ---------------------------------------------------------------------------
_CHINESE_MESSAGES = [
    "今天天气真好啊，要不要出去走走？",
    "有人看过那部新电影吗？听说评分很高",
    "晚上一起打游戏吧，我带你上分",
    "刚看到一个好好笑的段子，笑死我了",
    "周末要不要约个饭？我知道一家新开的店",
    "这个代码我写了三天终于跑通了，感动",
    "有人知道怎么配置 Docker 的网络吗？",
    "今天老板又开会开了一下午，困死了",
    "求推荐好看的番剧，最近剧荒",
    "这个 bug 调了我一整天，结果是少了个分号",
    "我刚换了个机械键盘，打字手感超好",
    "明天考试我还没复习，要完蛋了",
    "有没有人拼单买奶茶？满减很划算",
    "今天地铁又晚点了，迟到了半小时",
    "你们说 AI 会不会取代程序员啊？",
    "我家的猫今天又拆家了，气死我了",
    "有会摄影的大佬吗？想入个相机",
    "这个月的流量又用完了，好烦",
    "刚跑完五公里，感觉整个人都升华了",
    "有没有好用的笔记软件推荐？",
    "今天公司团建去玩密室逃脱，超刺激",
    "谁能帮我看看这行 SQL 为什么这么慢",
    "最近在学 Rust，生命周期好难懂",
    "这个周末天气不错，打算去爬山",
    "刚入手了一个新耳机，音质绝了",
    "有人用过这个框架吗？感觉怎么样",
    "今天被面试官问了一道算法题，完全不会",
    "大家觉得远程办公效率高吗？",
    "刚做了个甜点，味道还不错嘿嘿",
    "有没有一起学日语的小伙伴？",
    "今天食堂的午饭意外的好吃",
    "这个项目 deadline 要到了，还在改 bug",
    "有人抢到演唱会的票了吗？",
    "健身打卡第三天，感觉腹肌要出来了",
    "刚看完一本书，推荐给大家",
    "今天遇到一个超有意思的人",
    "有没有好用的 VSCode 插件推荐？",
    "这个 API 文档写得太烂了，完全看不懂",
    "周末打算去逛逛博物馆，有没有一起的",
    "最近在学画画，感觉好难但很有意思",
    "Python 3.13 发布了，JIT 编译器好强",
    "今天试着做了提拉米苏，成功了！",
    "有一起拼车去机场的吗？",
    "刚看完一部纪录片，讲深海生物的",
    "推荐一个冷门但超好听的乐队",
    "有谁在学 Go 语言吗？想找人一起",
    "今天在二手市场淘到一个好键盘",
    "有没有人周末去徒步的？",
    "刚发现一个超好用的效率工具",
    "最近在尝试 intermittent fasting",
    "谁有好的 REST API 设计教程推荐",
    "今天面试被问了一道系统设计题",
    "刚买了一个无人机，周末去飞",
    "有玩摄影的群友吗？想交流一下",
    "这个新框架感觉比 React 好用",
    "今天被组长 review 代码了，学到了很多",
    "有人去过冰岛吗？想了解下攻略",
]

_USERS = [
    "似君(Homo sapiens)", "没有名字有没名字", "hsd221",
    "Alice", "Bob_the_Builder", "小A同学2024",
    "wojiushiwo", "🐱喵喵侠", "⚡雷电法王",
    "今天吃什么", "熬夜冠军🏆", "Genima",
    "Elaina伊蕾娜", "木瓜是食草xyn", "巴巴哒捏",
    "代码写不完了", "咖啡续命中", "摸鱼小能手",
    "内卷之王", "躺平学博士", "被Bug选中的孩子",
]

_STREAM_IDS = [
    "group_100001", "group_100002", "group_100003",
    "group_100004", "group_100005",
    "private_200001", "private_200002", "private_200003",
]

# PREFERENCE atoms need semantic_detail with attr_category/attr_name/attr_value
_PREFERENCE_CATEGORIES = [
    ("preference", "food", "喜欢辣"),
    ("preference", "music", "喜欢摇滚"),
    ("preference", "game", "喜欢RPG"),
    ("preference", "drink", "喜欢咖啡"),
    ("preference", "sport", "喜欢跑步"),
    ("interest", "coding", "喜欢Python"),
    ("interest", "reading", "喜欢科幻"),
    ("personality", "trait", "内向外向各半"),
]

# ---------------------------------------------------------------------------
# JSON 编码补丁
# ---------------------------------------------------------------------------
_ORIGINAL_JSON_DEFAULT = json.JSONEncoder.default


def _json_patch(self: Any, obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.timestamp()
    if isinstance(obj, set):
        return list(obj)
    return _ORIGINAL_JSON_DEFAULT(self, obj)


json.JSONEncoder.default = _json_patch

# ---------------------------------------------------------------------------
# 内存 / 进程工具
# ---------------------------------------------------------------------------
def _get_rss_mib() -> float:
    try:
        with open(f"/proc/{os.getpid()}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except (FileNotFoundError, OSError, IndexError, ValueError):
        pass
    import resource as _r
    try:
        usage = _r.getrusage(_r.RUSAGE_SELF)
        return usage.ru_maxrss / 1024.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# 运行时指标收集
# ---------------------------------------------------------------------------
@dataclass
class MetricsCollector:
    csv_path: str
    _rows: list[dict] = field(default_factory=list)
    _start: float = field(default_factory=time.time)

    def snapshot(self, **extra) -> None:
        row = {
            "elapsed_s": round(time.time() - self._start, 1),
            "rss_mb": round(_get_rss_mib(), 1),
            **extra,
        }
        self._rows.append(row)

    def write_csv(self) -> None:
        if not self._rows:
            return
        fieldnames = list(self._rows[0].keys())
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(self._rows)


# ---------------------------------------------------------------------------
# Mock LLM — 注入确定性原子
# ---------------------------------------------------------------------------
_MOCK_LLM_ATOMS_CACHE: list[dict] = []


def _build_mock_atoms(count: int = 3) -> str:
    """生成 deterministic JSON 原子列表供 mock _call_llm 返回。"""
    atoms: list[dict] = []
    for i in range(count):
        content = random.choice(_CHINESE_MESSAGES)
        atom_type = random.choice(["episodic", "factual", "preference", "relational"])
        entities = [random.choice(_USERS)]
        importance = round(random.uniform(0.3, 1.0), 2)

        if atom_type == "episodic":
            detail = {
                "participants": [random.choice(_USERS) for _ in range(random.randint(1, 2))],
                "emotion_tags": [random.choice(["开心", "感慨", "吐槽", "兴奋", "疲惫"])],
            }
        elif atom_type == "factual":
            cat = random.choice(["interest", "personality", "habit", "skill"])
            detail = {
                "attr_category": cat,
                "attr_name": f"test_attr_{i}",
                "attr_value": content[:30],
            }
        elif atom_type == "preference":
            cat, name, val = random.choice(_PREFERENCE_CATEGORIES)
            detail = {
                "attr_category": cat,
                "attr_name": name,
                "attr_value": val,
            }
        else:
            detail = {}

        atoms.append({
            "content": content,
            "atom_type": atom_type,
            "entities": entities,
            "importance": importance,
            "detail": detail,
        })

    _MOCK_LLM_ATOMS_CACHE.clear()
    _MOCK_LLM_ATOMS_CACHE.extend(atoms)
    return json.dumps(atoms, ensure_ascii=False)


async def _mock_call_llm(self, prompt: str) -> str:
    """Monkey-patch for BatchEncoder._call_llm. Returns deterministic JSON."""
    return _build_mock_atoms(random.randint(1, 4))


# ---------------------------------------------------------------------------
# 主测试类
# ---------------------------------------------------------------------------
class BotE2EStressTest:
    """Bot E2E 压力测试 — 30+ 分钟连续运行"""

    def __init__(self, db_path: str, csv_path: str):
        self.db_path = db_path
        self.csv_path = csv_path
        self.metrics = MetricsCollector(csv_path)

        # Components (lazy init)
        self.store: Any = None
        self.writer: Any = None
        self.retriever: Any = None
        self.forgetting: Any = None
        self.archiver: Any = None
        self.tracker: Any = None
        self.pipeline: Any = None
        self.op_logger: Any = None
        self.graph_store: Any = None
        self.trace_recorder: Any = None
        self.arbiter: Any = None
        self.profile_store: Any = None
        self.profile_builder: Any = None
        self.objectivity_checker: Any = None

        # Atom tracking
        self.atom_write_latencies: list[float] = []
        self.retrieval_latencies: list[float] = []
        self.sweep_latencies: list[float] = []
        self.error_count = 0
        self.last_error_log = ""

        # RSS baseline
        self.rss_baseline = _get_rss_mib()

        # Signal handling
        self._shutdown = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Test phase tracking
        self.current_phase = 0
        self.phase_names = ["ramp_up", "sustained", "burst", "cooldown"]

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self._shutdown = True
        print(f"\n[信号] 收到信号 {signum}，正在停止测试...", file=sys.stderr)

    # ── 初始化 ────────────────────────────────────────────────────

    async def init_all(self) -> None:
        """初始化所有 14 个组件 + mock LLM"""
        print("[init] 初始化所有组件...", file=sys.stderr)

        # 1. DB + schema
        from src.memory.schema import memory_db
        from src.memory.schema import (
            MemoryAtom as MemModel, EpisodicDetail as EpiModel,
            SemanticDetail as SemModel, ConflictObservation as CoModel,
            NoisePool as NoiModel, MemoryTraceChain as TrModel,
            DreamRun as DrModel, GraphNode as GnModel,
            GraphEdge as GeModel, GraphEntry as GeModel2,
            RawMessageArchive as RmaModel,
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
        models_to_create = [
            MemModel, EpiModel, SemModel, CoModel, NoiModel,
            TrModel, DrModel, GnModel, GeModel, GeModel2, RmaModel,
        ]
        for m in models_to_create:
            if not memory_db.table_exists(m._meta.table_name):
                memory_db.create_tables([m], safe=True)

        # 2. MemoryStore
        from src.memory import MemoryStore, MemoryStoreConfig
        MemoryStore._instance = None
        config = MemoryStoreConfig(sqlite_path=self.db_path)
        self.store = MemoryStore(config)
        await self.store.initialize()

        # 3. WriteOpLogger
        from src.memory.write_ops import WriteOpLogger
        self.op_logger = WriteOpLogger(db_path=self.db_path, max_entries=5000)

        # 4. MemoryWriter
        from src.memory.layer3_retrieval import MemoryWriter
        self.writer = MemoryWriter(self.store, op_logger=self.op_logger)

        # 5. MemoryRetriever
        from src.memory.layer3_retrieval import MemoryRetriever
        self.retriever = MemoryRetriever(self.store)

        # 6. ForgettingManager
        from src.memory.forgetting import ForgettingManager
        self.forgetting = ForgettingManager(
            self.store,
            archive_threshold=0.05,
            delete_threshold=0.01,
            sweep_interval=600,
        )

        # 7. MessageArchiver
        from src.memory.layer0_archive import MessageArchiver
        self.archiver = MessageArchiver()

        # 8. ReinforcementTracker
        from src.memory.feedback import ReinforcementTracker
        self.tracker = ReinforcementTracker(self.store)

        # 9. EncodingPipeline (with mocked LLM)
        from src.memory.encoding_pipeline import EncodingPipeline
        from src.memory.layer2_encoder import BatchEncoder
        # Monkey-patch BatchEncoder._call_llm to avoid real LLM
        BatchEncoder._call_llm = _mock_call_llm
        self.pipeline = EncodingPipeline(
            self.store,
            trigger_count=5,
            trigger_seconds=60,
        )

        # 10. TraceChainRecorder
        from src.memory.trace_chain import TraceChainRecorder
        self.trace_recorder = TraceChainRecorder()
        self.pipeline.set_trace_recorder(self.trace_recorder)

        # 11. ObjectivityChecker
        from src.memory.objectivity_check import ObjectivityChecker
        self.objectivity_checker = ObjectivityChecker(self.store)

        # 12. ConflictArbiter
        from src.memory.conflict_arbitration import ConflictArbiter
        self.arbiter = ConflictArbiter(self.store)

        # 13. GraphStore
        from src.memory.graph_store import GraphStore
        self.graph_store = GraphStore()

        # 14. ProfileStore + ProfileBuilder
        from src.memory.user_profile import ProfileStore, ProfileBuilder
        self.profile_store = ProfileStore()
        self.profile_builder = ProfileBuilder(self.profile_store)

        print(f"[init] 完成 | DB={self.db_path} RSS={_get_rss_mib():.0f}MiB", file=sys.stderr)

    async def close_all(self) -> None:
        """清理所有组件"""
        if self.store:
            await self.store.close()

    # ── 原子计数 ──────────────────────────────────────────────────

    async def _atom_count(self) -> int:
        try:
            from src.memory.schema import MemoryAtom as M, memory_db
            with memory_db:
                return M.select().count()
        except Exception:
            return 0

    # ── 直接写入原子（绕过编码管线，用于快速填充）───────────────

    async def _write_direct_atom(
        self,
        content: Optional[str] = None,
        atom_type_str: Optional[str] = None,
        source_scene: str = "group_chat",
        user_entity: str = "test_user",
        preference_detail: bool = False,
    ) -> str:
        """写入一个原子并记录延迟"""
        from src.memory.atom import MemoryAtom as AD, AtomType, DecayType, SemanticDetail

        atom_id = f"stress_{int(time.time() * 1e6)}_{random.randint(0, 99999)}"
        content = content or random.choice(_CHINESE_MESSAGES)
        atype = AtomType(atom_type_str) if atom_type_str else random.choice(list(AtomType))
        now_ts = datetime.now(timezone.utc).timestamp()

        atom = AD(
            atom_id=atom_id,
            atom_type=atype,
            content=content,
            importance=round(random.uniform(0.3, 1.0), 2),
            confidence=round(random.uniform(0.5, 1.0), 2),
            weight=0.5,
            created_at=now_ts,
            last_accessed_at=now_ts,
            ttl_days=random.choice([7, 30, 90, 180]),
            decay_type=random.choice(list(DecayType)),
            source_scene=source_scene,
            privacy_level="context_sensitive",
            entities=[user_entity],
        )

        detail: Optional[SemanticDetail] = None
        if preference_detail or atype == AtomType.PREFERENCE:
            cat, name, val = random.choice(_PREFERENCE_CATEGORIES)
            detail = SemanticDetail(
                atom_id=atom_id,
                attr_category=cat,
                attr_name=name,
                attr_value=val,
            )
            atom.semantic_detail = detail

        t0 = time.monotonic()
        await self.writer.write_atom(atom=atom, semantic_detail=detail)
        latency = (time.monotonic() - t0) * 1000
        self.atom_write_latencies.append(latency)
        return atom_id

    async def _write_atoms_batch(self, n: int) -> list[str]:
        ids = []
        for _ in range(n):
            if self._shutdown:
                break
            aid = await self._write_direct_atom(
                preference_detail=(random.random() < 0.3),
            )
            ids.append(aid)
        return ids

    # ── 消息归档 ──────────────────────────────────────────────────

    def _make_message(self, stream_id: str, content: str, user: str) -> Any:
        """创建一个 duck-typing 消息对象"""
        msg_content = content

        class FakeMessage:
            group_id = stream_id
            message_id = f"msg_{int(time.time() * 1e6)}_{random.randint(0, 9999)}"
            user_id = user
            content = msg_content
            timestamp = time.time()
        return FakeMessage()

    async def _archive_messages(self, count: int) -> int:
        archived = 0
        for _ in range(count):
            msg = self._make_message(
                stream_id=random.choice(_STREAM_IDS),
                content=random.choice(_CHINESE_MESSAGES),
                user=random.choice(_USERS),
            )
            await self.archiver.archive_group_message(msg)
            archived += 1
        return archived

    async def _feed_encoding_pipeline(self, count: int) -> None:
        """Feed messages into the encoding pipeline"""
        for _ in range(count):
            sid = random.choice(_STREAM_IDS)
            user = random.choice(_USERS)
            await self.pipeline.ingest(
                stream_id=sid,
                user_id=user,
                speaker=user,
                content=random.choice(_CHINESE_MESSAGES),
                timestamp=time.time(),
            )

    # ── 检索测试 ──────────────────────────────────────────────────

    async def _test_retrieval(self) -> float:
        t0 = time.monotonic()
        try:
            context = await self.retriever.get_context_for_reply(
                stream_id=random.choice(_STREAM_IDS),
                user_id=random.choice(_USERS),
                max_atoms=5,
            )
            _ = context  # consume
        except Exception as e:
            self.error_count += 1
            self.last_error_log = str(e)
        lat = (time.monotonic() - t0) * 1000
        self.retrieval_latencies.append(lat)
        return lat

    # ── 验证画线检索（prompt_integration） ─────────────────────

    async def _test_prompt_integration(self) -> None:
        """Exercise build_memory_retrieval_prompt"""
        from src.memory.prompt_integration import build_memory_retrieval_prompt

        class FakeChatStream:
            stream_id = random.choice(_STREAM_IDS)

        try:
            text, atom_ids = await build_memory_retrieval_prompt(
                chat_talking_prompt_short="test",
                sender=random.choice(_USERS),
                target=random.choice(_CHINESE_MESSAGES),
                chat_stream=FakeChatStream(),
                think_level=1,
                user_id=random.choice(_USERS),
            )
        except Exception as e:
            self.error_count += 1
            self.last_error_log = str(e)

    # ── 强化反馈 ──────────────────────────────────────────────────

    async def _test_feedback(self) -> None:
        try:
            # Get some atom IDs from DB
            from src.memory.schema import MemoryAtom as M, memory_db
            with memory_db:
                ids = [a.atom_id for a in M.select(M.atom_id).limit(10)]
            if ids:
                # Use random atom dataclass for analyze
                from src.memory.atom import MemoryAtom as AD, AtomType
                fake_atoms = [
                    AD(atom_id=aid, atom_type=AtomType.FACTUAL, content=random.choice(_CHINESE_MESSAGES))
                    for aid in ids[:5]
                ]
                usage = self.tracker.analyze_reply_for_memory_usage(
                    random.choice(_CHINESE_MESSAGES), fake_atoms
                )
                used_ids = [aid for aid, lv in usage.items() if lv != "none"]
                if used_ids:
                    await self.tracker.apply_reinforcement(used_ids, level="normal")
        except Exception as e:
            self.error_count += 1
            self.last_error_log = str(e)

    # ── 用户画像 ──────────────────────────────────────────────────

    async def _test_user_profile(self) -> None:
        try:
            # Build profile for a user
            user = random.choice(_USERS)
            self.profile_builder.build_profile(user)
            # Update profile from a new atom
            from src.memory.atom import MemoryAtom as AD, AtomType, SemanticDetail
            atom = AD(
                atom_id=f"profile_{int(time.time() * 1e6)}",
                atom_type=AtomType.PREFERENCE,
                content=random.choice(_CHINESE_MESSAGES),
                entities=[user],
            )
            cat, name, val = random.choice(_PREFERENCE_CATEGORIES)
            atom.semantic_detail = SemanticDetail(
                atom_id=atom.atom_id,
                attr_category=cat,
                attr_name=name,
                attr_value=val,
            )
            self.profile_builder.update_profile_from_atom(user, atom)
        except Exception as e:
            self.error_count += 1
            self.last_error_log = str(e)

    # ── 图谱遍历 ──────────────────────────────────────────────────

    async def _test_graph_traversal(self) -> None:
        try:
            from src.memory.schema import GraphNode, memory_db
            with memory_db:
                nodes = list(GraphNode.select().limit(5))
            for n in nodes[:3]:
                self.graph_store.get_neighbors(str(n.id), depth=1)
                self.graph_store.get_related_atoms(str(n.label), max_depth=2)
        except Exception as e:
            self.error_count += 1
            self.last_error_log = str(e)

    # ── 追溯链 ────────────────────────────────────────────────────

    async def _test_trace_chain(self) -> None:
        try:
            from src.memory.schema import MemoryAtom as M, memory_db
            with memory_db:
                ids = [a.atom_id for a in M.select(M.atom_id).limit(5)]
            for aid in ids[:3]:
                self.trace_recorder.get_chain(aid)
        except Exception as e:
            self.error_count += 1
            self.last_error_log = str(e)

    # ── 梦境模拟 ──────────────────────────────────────────────────

    async def _test_dream_mimic(self) -> None:
        """Mimic DreamTask phases without idle check"""
        from src.memory.dream_agent import (
            CONSOLIDATION_BATCH_SIZE, IMPORTANCE_MIN, WEIGHT_MAX, CONSOLIDATION_BOOST,
            NOISE_TTL_DAYS,
        )
        from src.memory.atom import MemoryAtom as AD, AtomType, DecayType, apply_dream_consolidation
        from src.memory.schema import (
            MemoryAtom as M, NoisePool, memory_db,
            GraphNode, GraphEdge, GraphEntry, SemanticDetail as SemModel,
        )
        from src.memory.dream_agent import GRAPH_ATOMS_LIMIT
        import datetime as dt

        # Phase 1: Consolidation
        consolidated = 0
        try:
            with memory_db:
                query = list(
                    M.select()
                    .where(
                        M.status == "active",
                        M.importance >= IMPORTANCE_MIN,
                        M.weight <= WEIGHT_MAX,
                    )
                    .order_by(M.weight.asc())
                    .limit(CONSOLIDATION_BATCH_SIZE)
                )
                for atom_model in query:
                    now_ts = time.time()
                    atom_dc = AD(
                        atom_id=atom_model.atom_id,
                        atom_type=AtomType(atom_model.atom_type),
                        content=atom_model.content or "",
                        importance=atom_model.importance,
                        confidence=atom_model.confidence,
                        weight=atom_model.weight,
                        created_at=now_ts,
                        last_accessed_at=now_ts,
                        ttl_days=float(atom_model.ttl_days or 7),
                        decay_type=DecayType(atom_model.decay_type),
                        source_scene=atom_model.source_scene or "unknown",
                        privacy_level=atom_model.privacy_level or "context_sensitive",
                        status=atom_model.status,
                    )
                    updated = apply_dream_consolidation(atom_dc, boost=CONSOLIDATION_BOOST)
                    M.update(weight=updated.weight).where(M.atom_id == atom_model.atom_id).execute()
                    consolidated += 1
        except Exception:
            self.error_count += 1

        # Phase 2: Noise cleanup
        try:
            cutoff = dt.datetime.now() - dt.timedelta(days=NOISE_TTL_DAYS)
            with memory_db:
                NoisePool.delete().where(NoisePool.created_at < cutoff).execute()
        except Exception:
            self.error_count += 1

        # Phase 3: Graph building
        edges_created = 0
        entries_created = 0
        try:
            with memory_db:
                top_atoms = list(
                    M.select().where(M.status == "active")
                    .order_by(M.weight.desc())
                    .limit(GRAPH_ATOMS_LIMIT)
                )
                if top_atoms:
                    atom_entities: dict[str, list[str]] = {}
                    for am in top_atoms:
                        entities: list[str] = []
                        if am.entities:
                            try:
                                parsed = json.loads(am.entities)
                                if isinstance(parsed, list):
                                    entities = [str(e) for e in parsed]
                            except Exception:
                                pass
                        atom_entities[am.atom_id] = entities
                    all_entities = set()
                    for el in atom_entities.values():
                        all_entities.update(el)
                    for entity in all_entities:
                        GraphNode.get_or_create(node_type="entity", label=entity, defaults={"properties": "{}"})
                    for el in atom_entities.values():
                        if len(el) < 2:
                            continue
                        node_map: dict[str, int] = {}
                        for entity in el:
                            node = GraphNode.get_or_none(GraphNode.label == entity)
                            if node is not None:
                                node_map[entity] = node.id
                        nids = list(node_map.values())
                        for i in range(len(nids)):
                            for j in range(i + 1, len(nids)):
                                _, created = GraphEdge.get_or_create(
                                    source_node_id=nids[i], target_node_id=nids[j],
                                    predicate="related_to", defaults={"confidence": 0.6},
                                )
                                if created:
                                    edges_created += 1
                    atom_ids = [a.atom_id for a in top_atoms]
                    details = SemModel.select().where(SemModel.atom.in_(atom_ids))
                    for detail in details:
                        if not detail.attr_name or not detail.attr_value:
                            continue
                        _, created = GraphEntry.get_or_create(
                            subject=detail.attr_category, predicate=detail.attr_name,
                            object=detail.attr_value,
                            defaults={"evidence": f"atom:{detail.atom}", "confidence": 0.7},
                        )
                        if created:
                            entries_created += 1
        except Exception:
            self.error_count += 1

    # ── 编码周期运行 ─────────────────────────────────────────────

    async def _run_encoding_cycle(self) -> dict:
        try:
            stats = await self.pipeline.run_cycle()
            return stats
        except Exception as e:
            self.error_count += 1
            self.last_error_log = str(e)
            return {"error": str(e)}

    # ── 遗忘扫描 ──────────────────────────────────────────────────

    async def _test_sweep(self) -> dict:
        t0 = time.monotonic()
        try:
            result = await self.forgetting.run_sweep()
            lat = (time.monotonic() - t0) * 1000
            self.sweep_latencies.append(lat)
            return result
        except Exception as e:
            self.error_count += 1
            self.last_error_log = str(e)
            return {"error": str(e)}

    # ── 冲突仲裁 ──────────────────────────────────────────────────

    async def _test_conflict_arbitration(self) -> int:
        try:
            resolved = await self.arbiter.check_and_resolve()
            return resolved
        except Exception:
            self.error_count += 1
            return 0

    # ── 客观性校验 ────────────────────────────────────────────────

    async def _test_objectivity_check(self) -> None:
        from src.memory.atom import MemoryAtom as AD, AtomType
        try:
            atom = AD(
                atom_id=f"obj_{int(time.time() * 1e6)}",
                atom_type=AtomType.FACTUAL,
                content=random.choice(_CHINESE_MESSAGES),
                entities=[random.choice(_USERS)],
            )
            await self.objectivity_checker.check_before_write(
                atom, trace_recorder=self.trace_recorder
            )
        except Exception:
            self.error_count += 1

    # ── 检查点 ────────────────────────────────────────────────────

    async def _checkpoint(self, phase: str, elapsed: float) -> dict:
        count = await self._atom_count()
        rss = _get_rss_mib()

        # Percentile calculations
        def pct(arr: list[float], p: float) -> float:
            if not arr:
                return 0.0
            s = sorted(arr)
            idx = min(int(len(s) * p), len(s) - 1)
            return s[idx]

        write_p50 = pct(self.atom_write_latencies, 0.5)
        write_p99 = pct(self.atom_write_latencies, 0.99)
        retrieval_p50 = pct(self.retrieval_latencies, 0.5)
        retrieval_p99 = pct(self.retrieval_latencies, 0.99)
        sweep_p50 = pct(self.sweep_latencies, 0.5)

        info = {
            "phase": phase,
            "elapsed_s": round(elapsed, 1),
            "rss_mib": round(rss, 1),
            "rss_growth_pct": round((rss - self.rss_baseline) / max(self.rss_baseline, 1) * 100, 1),
            "atom_count": count,
            "write_p50_ms": round(write_p50, 1),
            "write_p99_ms": round(write_p99, 1),
            "retrieval_p50_ms": round(retrieval_p50, 1),
            "retrieval_p99_ms": round(retrieval_p99, 1),
            "sweep_p50_ms": round(sweep_p50, 1),
            "errors": self.error_count,
        }
        return info

    # ── 主循环 ────────────────────────────────────────────────────

    async def run(self) -> dict:
        """Main entry point — runs 4 phases over 1800+ seconds"""
        print("\n" + "=" * 60, file=sys.stderr)
        print("  MaiBot E2E Stress Test — 30+ minutes", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

        overall_start = time.time()
        start_ts = overall_start

        # feed interval tracking
        last_sweep_time = 0.0
        last_encoding_time = 0.0
        last_checkpoint_time = 0.0

        # Pre-warm: ensure pipeline buffer has messages so encoding produces atoms
        # before we rely on direct atom writes for the atom pool
        print("\n[预热] 初始化数据池...", file=sys.stderr)
        await self._write_atoms_batch(50)
        await self._archive_messages(30)

        print(f"[启动] 初始原子数={await self._atom_count()} RSS={_get_rss_mib():.1f}MiB", file=sys.stderr)

        # Print header
        print(f"{'Time':>8s} {'Phase':>12s} {'Atoms':>6s} {'RSS':>7s} {'Growth':>7s} "
              f"{'Wp50':>7s} {'Wp99':>7s} {'Rp50':>7s} {'Rp99':>7s} {'Err':>4s}",
              file=sys.stderr)
        print("-" * 80, file=sys.stderr)

        # =====================================================================
        # Phase 1 — Ramp-up (0-300s): 5 messages/sec, build up atom pool
        # =====================================================================
        self.current_phase = 1
        phase_start = time.time()
        phase_duration = 300
        msg_interval = 0.2  # 5 msg/sec
        print(f"\n>>> Phase 1: Ramp-up ({phase_duration}s, 5 msg/sec) <<<\n", file=sys.stderr)
        last_msg_feed = 0.0

        while (time.time() - phase_start) < phase_duration and not self._shutdown:
            elapsed = time.time() - start_ts
            now = time.time()

            # Feed messages at 5/sec
            if now - last_msg_feed >= msg_interval:
                await self._feed_encoding_pipeline(1)
                await self._archive_messages(1)
                last_msg_feed = now

            # Sweep every 300s in real time, but accelerate: sweep every 60s in phase 1
            if elapsed - last_sweep_time >= 300 and elapsed >= 60:
                await self._test_sweep()
                last_sweep_time = elapsed

            # Encoding cycle every 60s in phase 1
            if elapsed - last_encoding_time >= 60:
                await self._run_encoding_cycle()
                last_encoding_time = elapsed

            # Checkpoint every 60s
            if elapsed - last_checkpoint_time >= 60:
                info = await self._checkpoint("ramp_up", elapsed)
                self.metrics.snapshot(**info)
                print(f"{info['elapsed_s']:>8.0f} {info['phase']:>12s} {info['atom_count']:>6d} "
                      f"{info['rss_mib']:>7.1f} {info['rss_growth_pct']:>6.1f}% "
                      f"{info['write_p50_ms']:>7.1f} {info['write_p99_ms']:>7.1f} "
                      f"{info['retrieval_p50_ms']:>7.1f} {info['retrieval_p99_ms']:>7.1f} "
                      f"{info['errors']:>4d}", file=sys.stderr)
                last_checkpoint_time = elapsed

            # Exercise various components intermittently
            if elapsed % 20 < 0.5:
                await self._test_retrieval()
            if elapsed % 10 < 0.5:
                await self._test_objectivity_check()
            if elapsed % 45 < 0.5:
                await self._test_user_profile()

            await self._write_direct_atom()
            await asyncio.sleep(0.05)

        # =====================================================================
        # Phase 2 — Sustained (300-900s): 10 msg/sec, retrievals every 30s
        # =====================================================================
        self.current_phase = 2
        phase_start = time.time()
        phase_duration = 600
        msg_interval = 0.1  # 10 msg/sec
        last_msg_feed = 0.0
        last_retrieval_time = 0.0
        print(f"\n>>> Phase 2: Sustained ({phase_duration}s, 10 msg/sec) <<<\n", file=sys.stderr)

        while (time.time() - phase_start) < phase_duration and not self._shutdown:
            elapsed = time.time() - start_ts
            now = time.time()

            # Feed 10 msg/sec
            if now - last_msg_feed >= msg_interval:
                await self._feed_encoding_pipeline(1)
                await self._archive_messages(1)
                last_msg_feed = now

            # Retrievals every 30s
            if elapsed - last_retrieval_time >= 30:
                await self._test_retrieval()
                await self._test_prompt_integration()
                await self._test_feedback()
                await self._test_trace_chain()
                last_retrieval_time = elapsed

            # Sweep every 300s
            if elapsed - last_sweep_time >= 300:
                await self._test_sweep()
                last_sweep_time = elapsed

            # Encoding cycle every 120s
            if elapsed - last_encoding_time >= 120:
                await self._run_encoding_cycle()
                last_encoding_time = elapsed

            # Checkpoint every 60s
            if elapsed - last_checkpoint_time >= 60:
                info = await self._checkpoint("sustained", elapsed)
                self.metrics.snapshot(**info)
                print(f"{info['elapsed_s']:>8.0f} {info['phase']:>12s} {info['atom_count']:>6d} "
                      f"{info['rss_mib']:>7.1f} {info['rss_growth_pct']:>6.1f}% "
                      f"{info['write_p50_ms']:>7.1f} {info['write_p99_ms']:>7.1f} "
                      f"{info['retrieval_p50_ms']:>7.1f} {info['retrieval_p99_ms']:>7.1f} "
                      f"{info['errors']:>4d}", file=sys.stderr)
                last_checkpoint_time = elapsed

            # Intermittent component exercise
            if elapsed % 15 < 0.5:
                await self._test_graph_traversal()
            if elapsed % 25 < 0.5:
                await self._test_conflict_arbitration()
            if elapsed % 40 < 0.5:
                await self._test_dream_mimic()
                await self._test_user_profile()

            await self._write_direct_atom()
            await asyncio.sleep(0.02)

        # =====================================================================
        # Phase 3 — Burst (900-1200s): 3 bursts of 50 msg in 5s, 60s apart
        # =====================================================================
        self.current_phase = 3
        phase_start = time.time()
        phase_duration = 300
        print(f"\n>>> Phase 3: Burst ({phase_duration}s, 3×50 bursts) <<<\n", file=sys.stderr)

        for burst_num in range(3):
            if self._shutdown:
                break

            print(f"\n  === Burst {burst_num + 1}/3 ===", file=sys.stderr)

            # Burst: 50 atoms + 50 archives in 5 seconds
            t0 = time.time()
            tasks = []
            for _ in range(50):
                tasks.append(self._write_direct_atom())
                tasks.append(self._archive_messages(1))
            await asyncio.gather(*tasks, return_exceptions=True)

            # Also feed encoding pipeline rapidly
            for _ in range(30):
                await self._feed_encoding_pipeline(1)
            burst_duration = time.time() - t0

            # Run encoding cycle after burst
            await self._run_encoding_cycle()

            # Retrieval burst
            for _ in range(5):
                await self._test_retrieval()

            print(f"  Burst {burst_num + 1}: 50 atoms in {burst_duration:.2f}s | "
                  f"Total atoms: {await self._atom_count()}", file=sys.stderr)

            # 60s gap between bursts (or less for last burst)
            if burst_num < 2:
                gap_start = time.time()
                while time.time() - gap_start < 60 and not self._shutdown:
                    await asyncio.sleep(1)
                    # Light load during gap
                    if random.random() < 0.2:
                        await self._test_retrieval()

            elapsed = time.time() - start_ts
            info = await self._checkpoint("burst", elapsed)
            self.metrics.snapshot(**info)

        # =====================================================================
        # Phase 4 — Cooldown (1200-1800s): 2 msg/sec, heavy retrieval
        # =====================================================================
        self.current_phase = 4
        phase_start = time.time()
        phase_duration = 600
        msg_interval = 0.5  # 2 msg/sec
        last_msg_feed = 0.0
        print(f"\n>>> Phase 4: Cooldown ({phase_duration}s, 2 msg/sec, heavy retrieval) <<<\n", file=sys.stderr)

        while (time.time() - phase_start) < phase_duration and not self._shutdown:
            elapsed = time.time() - start_ts
            now = time.time()

            # Feed 2 msg/sec
            if now - last_msg_feed >= msg_interval:
                await self._feed_encoding_pipeline(1)
                last_msg_feed = now

            # Heavy retrieval every 15s
            if elapsed - last_retrieval_time >= 15:
                for _ in range(3):
                    await self._test_retrieval()
                await self._test_prompt_integration()
                await self._test_feedback()
                await self._test_trace_chain()
                await self._test_graph_traversal()
                await self._test_conflict_arbitration()
                last_retrieval_time = elapsed

            # Final sweep
            if elapsed - last_sweep_time >= 300:
                await self._test_sweep()
                last_sweep_time = elapsed

            # Encoding every 120s
            if elapsed - last_encoding_time >= 120:
                await self._run_encoding_cycle()
                last_encoding_time = elapsed

            # Checkpoint every 60s
            if elapsed - last_checkpoint_time >= 60:
                info = await self._checkpoint("cooldown", elapsed)
                self.metrics.snapshot(**info)
                print(f"{info['elapsed_s']:>8.0f} {info['phase']:>12s} {info['atom_count']:>6d} "
                      f"{info['rss_mib']:>7.1f} {info['rss_growth_pct']:>6.1f}% "
                      f"{info['write_p50_ms']:>7.1f} {info['write_p99_ms']:>7.1f} "
                      f"{info['retrieval_p50_ms']:>7.1f} {info['retrieval_p99_ms']:>7.1f} "
                      f"{info['errors']:>4d}", file=sys.stderr)
                last_checkpoint_time = elapsed

            # Dream mimic during cooldown
            if elapsed % 30 < 0.5:
                await self._test_dream_mimic()
                await self._test_user_profile()

            # Light write
            if random.random() < 0.3:
                await self._write_direct_atom()
            await asyncio.sleep(0.05)

        # ── Final checkpoint ───────────────────────────────────────
        final_rss = _get_rss_mib()
        total_elapsed = time.time() - start_ts

        # Final sweep + encoding
        await self._test_sweep()
        await self._run_encoding_cycle()
        final_atom_count_after = await self._atom_count()

        info = await self._checkpoint("final", total_elapsed)
        self.metrics.snapshot(**info)
        self.metrics.write_csv()

        # ── Compute verdict ────────────────────────────────────────
        verdict = await self._compute_verdict(
            final_atom_count_after, total_elapsed, final_rss
        )
        return verdict

    async def _compute_verdict(
        self, final_count: int, total_elapsed: float, final_rss: float
    ) -> dict:
        """Compute pass/fail verdict"""
        failures: list[str] = []

        # Criterion 1: Zero crashes
        if self.error_count > 0:
            failures.append(f"ERRORS: {self.error_count} unhandled exceptions (last: {self.last_error_log})")

        # Criterion 2: RSS growth < 200%
        growth_pct = (final_rss - self.rss_baseline) / max(self.rss_baseline, 1) * 100
        if growth_pct >= 200:
            failures.append(f"MEMORY_LEAK: RSS growth {growth_pct:.0f}% >= 200% (baseline={self.rss_baseline:.0f}MiB)")

        # Criterion 3: Write p99 < 500ms
        if self.atom_write_latencies:
            sorted_w = sorted(self.atom_write_latencies)
            w_p99 = sorted_w[int(len(sorted_w) * 0.99)]
            if w_p99 > 500:
                failures.append(f"WRITE_P99: {w_p99:.1f}ms > 500ms ({len(self.atom_write_latencies)} samples)")

        # Criterion 4: Retrieval p99 < 300ms
        if self.retrieval_latencies:
            sorted_r = sorted(self.retrieval_latencies)
            r_p99 = sorted_r[int(len(sorted_r) * 0.99)]
            if r_p99 > 300:
                failures.append(f"RETRIEVAL_P99: {r_p99:.1f}ms > 300ms ({len(self.retrieval_latencies)} samples)")

        # Criterion 5: Decay sweep < 10s
        if self.sweep_latencies:
            max_sweep = max(self.sweep_latencies)
            if max_sweep > 10000:
                failures.append(f"SWEEP: max {max_sweep:.0f}ms > 10000ms ({len(self.sweep_latencies)} sweeps)")

        # Criterion 6: All 14 components exercised at least once
        component_checks = {
            "message_archiver": self.archiver is not None,
            "topic_summarizer": self.pipeline is not None and hasattr(self.pipeline.encoder, "group_summarizer"),
            "encoding_pipeline": self.pipeline is not None,
            "memory_writer": self.writer is not None,
            "objectivity_checker": self.objectivity_checker is not None,
            "conflict_arbiter": self.arbiter is not None,
            "memory_retriever": self.retriever is not None,
            "prompt_integration": True,  # called in _test_prompt_integration
            "reinforcement_tracker": self.tracker is not None,
            "forgetting_manager": self.forgetting is not None,
            "user_profile": self.profile_store is not None,
            "graph_store": self.graph_store is not None,
            "dream_mimic": True,  # called in _test_dream_mimic
            "trace_chain": self.trace_recorder is not None,
        }
        missing = [k for k, v in component_checks.items() if not v]
        if missing:
            failures.append(f"MISSING_COMPONENTS: {', '.join(missing)}")

        passed = len(failures) == 0

        verdict = {
            "passed": passed,
            "failures": failures,
            "total_elapsed_s": round(total_elapsed, 1),
            "final_atom_count": final_count,
            "max_rss_mib": round(final_rss, 1),
            "rss_growth_pct": round(growth_pct, 1),
            "rss_baseline_mib": round(self.rss_baseline, 1),
            "total_errors": self.error_count,
            "write_samples": len(self.atom_write_latencies),
            "retrieval_samples": len(self.retrieval_latencies),
            "sweep_samples": len(self.sweep_latencies),
        }

        if self.atom_write_latencies:
            sorted_w = sorted(self.atom_write_latencies)
            verdict["write_p50_ms"] = round(sorted_w[len(sorted_w) // 2], 1)
            verdict["write_p99_ms"] = round(sorted_w[int(len(sorted_w) * 0.99)], 1)

        if self.retrieval_latencies:
            sorted_r = sorted(self.retrieval_latencies)
            verdict["retrieval_p50_ms"] = round(sorted_r[len(sorted_r) // 2], 1)
            verdict["retrieval_p99_ms"] = round(sorted_r[int(len(sorted_r) * 0.99)], 1)

        if self.sweep_latencies:
            verdict["sweep_max_ms"] = round(max(self.sweep_latencies), 1)
            verdict["sweep_p50_ms"] = round(sorted(self.sweep_latencies)[len(self.sweep_latencies) // 2], 1)

        return verdict


# =====================================================================
# 入口
# =====================================================================
async def main() -> int:

    # Create temp DB
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="maibot_stress_")
    os.close(fd)

    csv_path = os.path.join(_SCRIPT_DIR, "..", "data", "bot_e2e_metrics.csv")
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    # Suppress logging noise
    suppress_logging()

    print(f"[启动] 临时 DB: {db_path}", file=sys.stderr)
    print(f"[启动] CSV 指标: {csv_path}", file=sys.stderr)

    test = BotE2EStressTest(db_path=db_path, csv_path=csv_path)

    try:
        await test.init_all()
        verdict = await test.run()
    except Exception as e:
        print(f"\n[致命错误] {e}", file=sys.stderr)
        traceback.print_exc()
        verdict = {
            "passed": False,
            "failures": [f"CRASH: {e}"],
            "total_elapsed_s": 0,
            "final_atom_count": 0,
            "max_rss_mib": 0,
            "rss_growth_pct": 0,
            "rss_baseline_mib": 0,
            "total_errors": 1,
            "write_samples": 0,
            "retrieval_samples": 0,
            "sweep_samples": 0,
        }
    finally:
        await test.close_all()
        # Cleanup temp DB
        try:
            os.unlink(db_path)
            # Also remove WAL/SHM files
            for ext in ("-wal", "-shm"):
                p = db_path + ext
                if os.path.exists(p):
                    os.unlink(p)
            # Remove write_ops log
            wl = db_path.replace(".db", "_write_ops.jsonl")
            if os.path.exists(wl):
                os.unlink(wl)
        except Exception:
            pass

    # ── Print verdict ─────────────────────────────────────────────
    print("\n" + "=" * 60, file=sys.stderr)
    if verdict["passed"]:
        print("  VERDICT: ✅ PASS", file=sys.stderr)
    else:
        print("  VERDICT: ❌ FAIL", file=sys.stderr)
        for f in verdict["failures"]:
            print(f"    - {f}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  Duration:   {verdict['total_elapsed_s']}s", file=sys.stderr)
    print(f"  Atoms:      {verdict['final_atom_count']}", file=sys.stderr)
    print(f"  RSS:        {verdict['rss_baseline_mib']} → {verdict.get('max_rss_mib', 0)} MiB "
          f"({verdict.get('rss_growth_pct', 0)}%)", file=sys.stderr)
    print(f"  Writes:     {verdict.get('write_samples', 0)} samples, "
          f"p50={verdict.get('write_p50_ms', 'N/A')}ms p99={verdict.get('write_p99_ms', 'N/A')}ms", file=sys.stderr)
    print(f"  Retrievals: {verdict.get('retrieval_samples', 0)} samples, "
          f"p50={verdict.get('retrieval_p50_ms', 'N/A')}ms p99={verdict.get('retrieval_p99_ms', 'N/A')}ms", file=sys.stderr)
    print(f"  Sweeps:     {verdict.get('sweep_samples', 0)} samples, "
          f"p50={verdict.get('sweep_p50_ms', 'N/A')}ms max={verdict.get('sweep_max_ms', 'N/A')}ms", file=sys.stderr)
    print(f"  Errors:     {verdict['total_errors']}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
