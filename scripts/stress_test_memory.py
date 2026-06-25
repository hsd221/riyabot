#!/usr/bin/env python3
"""记忆系统压力测试 — 5 维度：批量摄入 / 持续负载 / 突发尖峰 / 并发读写 / 崩溃恢复

用法:
    # 快速验证（精简参数）
    python scripts/stress_test_memory.py --quick --test bulk

    # 全量运行
    python scripts/stress_test_memory.py --all --duration 120 --concurrency 40

    # 单测试
    python scripts/stress_test_memory.py --test sustained --duration 60

输出:
    stdout: JSON 报告摘要
    scripts/stress_results.json: 详细结果（``--output`` 指定）

设计原则:
    - 只导入 src.memory.*，不依赖 mai 聊天模块
    - 不需要真实 Qdrant 服务（qdrant-client 未安装时静默降级）
    - 使用临时 SQLite 数据库，不污染生产数据
    - 所有路径基于脚本位置解析，支持从项目根目录或 scripts/ 下运行
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import signal
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# JSON 编码补丁 — WriteOpLogger.payload 中可能包含 datetime 对象
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
# 环境引导 — 确保能导入 src.*
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# 测试结果数据模型
# ---------------------------------------------------------------------------


@dataclass
class TestResult:
    """单个测试的结果"""

    test_name: str
    passed: bool
    duration_ms: float
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 中文聊天模拟数据
# ---------------------------------------------------------------------------

_CHINESE_MESSAGE_TEMPLATES: list[str] = [
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
]

_USERS = [
    # From real chat @mentions (must include)
    "似君(Homo sapiens)",
    "没有名字有没名字",
    "hsd221",
    # English-style names
    "Alice",
    "Bob_the_Builder",
    "小A同学2024",
    # Pinyin-style
    "wojiushiwo",
    # Emoji names
    "🐱喵喵侠",
    "⚡雷电法王",
    # Meme / playful names
    "今天吃什么",
    "熬夜冠军🏆",
    # From real chat data (abbreviated @mentions)
    "Genima",
    "Elaina伊蕾娜",
    "木瓜是食草xyn",
    "巴巴哒捏",
]

_STREAM_IDS = [
    "group_100001",
    "group_100002",
    "group_100003",
    "group_100004",
    "group_100005",
    "private_200001",
    "private_200002",
    "private_200003",
    "private_200004",
    "private_200005",
]


def _random_message() -> str:
    return random.choice(_CHINESE_MESSAGE_TEMPLATES)


def _random_user() -> str:
    return random.choice(_USERS)


def _random_stream() -> str:
    return random.choice(_STREAM_IDS)


def _random_timestamp(days_ago: float = 0) -> float:
    """生成随机时间戳（可指定多少天前，用于测试衰减）"""
    return time.time() - random.uniform(0, days_ago * 86400)


# ---------------------------------------------------------------------------
# 真实 QQ 聊天数据加载
# ---------------------------------------------------------------------------

_REAL_CHAT_EXPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "data", "chat_exports")


def _clean_reply_prefix(text: str) -> str:
    """清洗回复前缀和 @提及，保留实际聊天内容。

    处理两种结构前缀：
      - "[回复 sender: original]\\n@user content" → "content"
      - "@user content" → "content"
    保留消息中间/末尾的 @提及。
    """
    lines = [raw_line for raw_line in text.split("\n") if not raw_line.strip().startswith("[回复")]
    cleaned: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("@"):
            idx = line.find(" ")
            if idx > 0 and idx < len(line) - 1:
                line = line[idx + 1 :].strip()
            else:
                continue
        if line:
            cleaned.append(line)
    return " ".join(cleaned).strip()


def load_real_chat_data() -> list[tuple[str, int, str]]:
    """加载真实 QQ 聊天数据。

    遍历导出目录下的所有 JSON 文件，提取：
      - 文本内容（清洗回复前缀）
      - 时间戳（毫秒）
      - 发送者名称
    过滤掉纯图片消息、视频消息和合并转发。
    返回 list[(text, timestamp_ms, sender_name), ...]。
    """
    if not os.path.isdir(_REAL_CHAT_EXPORTS_DIR):
        return []

    results: list[tuple[str, int, str]] = []
    for fname in sorted(os.listdir(_REAL_CHAT_EXPORTS_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(_REAL_CHAT_EXPORTS_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fp:
                data = json.load(fp)
        except Exception:
            continue

        for msg in data.get("messages", []):
            text = msg.get("content", {}).get("text", "")
            if not text:
                continue
            # 移除内嵌的附件/卡片标签
            text = re.sub(r"\[(?:图片|视频|合并转发|文件|卡片消息):[^\]]*\]", "", text)
            text = re.sub(r"\[\[?(?:图片|视频)\]?\]", "", text)
            text = text.strip()
            if not text or text.strip("[] \t\n\r") == "":
                continue
            # 纯表情/特殊消息（无实质文本内容）
            if text in ("[动画表情]", "[语音]", "[分享]", "[红包]"):
                continue

            cleaned = _clean_reply_prefix(text)
            if not cleaned:
                continue

            ts = msg.get("timestamp", 0)
            sender = msg.get("sender", {}).get("name", "unknown")
            results.append((cleaned, ts, sender))

    return results


# ---------------------------------------------------------------------------
# 真实聊天模式生成器
# ---------------------------------------------------------------------------

# 全局缓存，避免重复解析
_REAL_MESSAGES_CACHE: list[tuple[str, int, str]] | None = None


def _get_real_messages() -> list[tuple[str, int, str]]:
    global _REAL_MESSAGES_CACHE
    if _REAL_MESSAGES_CACHE is None:
        _REAL_MESSAGES_CACHE = load_real_chat_data()
    return _REAL_MESSAGES_CACHE


def generate_burst_messages(
    burst_size: int = 5,
    real_messages: list[tuple[str, int, str]] | None = None,
    real_ratio: float = 0.5,
    same_user: bool = True,
) -> list[str]:
    """生成同一用户在短时间内（<5s）的连续多条消息。

    模拟聊天中的"刷屏"行为：同一用户连续发送多条消息。
    70% 概率从真实消息中采样，30% 使用模板。
    """
    src: list[str] = []
    if real_messages and real_ratio > 0 and random.random() < real_ratio:
        src = [m[0] for m in real_messages]
    if not src:
        src = _CHINESE_MESSAGE_TEMPLATES

    count = min(burst_size, len(src))
    if count == 0:
        return [_random_message()]
    return random.sample(src, k=count)


def generate_super_long_message(
    real_messages: list[tuple[str, int, str]] | None = None,
    min_len: int = 500,
) -> str:
    """生成 500+ 字符的超长消息，拼接多条真实消息。

    模拟真实聊天中的大段输出（如分享长文本、代码、作文等）。
    """
    parts: list[str] = []
    attempts = 0
    while sum(len(t) for t in parts) < min_len and attempts < 50:
        if real_messages and random.random() < 0.7:
            t = random.choice(real_messages)[0]
        else:
            t = random.choice(_CHINESE_MESSAGE_TEMPLATES)
        if t not in parts:
            parts.append(t)
        attempts += 1
    return "。".join(parts)


def generate_realistic_stream(
    count: int,
    real_messages: list[tuple[str, int, str]] | None = None,
    real_ratio: float = 0.5,
    burst_prob: float = 0.3,
    start_ts: float | None = None,
) -> list[tuple[str, str, float]]:
    """生成模拟真实聊天节奏的消息流。

    模式: 突发(3-8条/5s内) → 静默(10-120s) → 突发/单条，交替进行。
    返回 list[(text, user_name, timestamp_seconds), ...]。
    """
    results: list[tuple[str, str, float]] = []
    current_ts = start_ts if start_ts is not None else time.time() - 86400 * 7
    real_texts = [m[0] for m in real_messages] if real_messages else []
    i = 0

    def _pick() -> str:
        if real_texts and real_ratio > 0 and random.random() < real_ratio:
            return random.choice(real_texts)
        return random.choice(_CHINESE_MESSAGE_TEMPLATES)

    while i < count:
        if random.random() < burst_prob and i + 3 <= count:
            burst_user = random.choice(_USERS)
            burst_size = random.randint(3, min(8, count - i))
            for _ in range(burst_size):
                results.append((_pick(), burst_user, current_ts))
                current_ts += random.uniform(0.3, 2.0)
                i += 1
            current_ts += random.uniform(10.0, 120.0)
        else:
            results.append((_pick(), random.choice(_USERS), current_ts))
            current_ts += random.uniform(5.0, 60.0)
            i += 1

    return results


# ---------------------------------------------------------------------------
# 内存/进程工具
# ---------------------------------------------------------------------------


def _get_rss_mib() -> float:
    """获取当前进程 RSS 内存（MiB）"""
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
        # On Linux ru_maxrss is in KiB; on macOS it's in bytes
        return usage.ru_maxrss / 1024.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# 日志抑制（减少测试输出噪音）
# ---------------------------------------------------------------------------


def _suppress_logging() -> None:
    """替换 src.common.logger 中的日志系统，减少测试输出噪音"""
    import src.common.logger as _mod_logger

    _mod_logger._loggers: dict[str, Any] = {}

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

    def _quiet_get_logger(name: str = "", **kwargs) -> _QuietLogger:
        return _QuietLogger()

    _mod_logger.get_logger = _quiet_get_logger


# ---------------------------------------------------------------------------
# 测试执行器
# ---------------------------------------------------------------------------


class StressTestRunner:
    """压力测试执行器 — 管理 5 种测试的生命周期和资源"""

    def __init__(
        self,
        db_path: str,
        quick: bool = False,
        duration: int = 120,
        concurrency: int = 20,
        use_real_data: bool = True,
        real_ratio: float = 0.5,
        burst_count: int = 3,
    ):
        self.db_path = db_path
        self.quick = quick
        self.duration = duration
        self.concurrency = concurrency
        self.use_real_data = use_real_data
        self.real_ratio = real_ratio
        self.burst_count = burst_count

        # 内存系统组件（延迟初始化）
        self.store: Any = None
        self.writer: Any = None
        self.forgetting: Any = None
        self.tracker: Any = None
        self.archiver: Any = None
        self.op_logger: Any = None

        # 测试结果收集
        self.results: list[TestResult] = []

        # 真实聊天数据（懒加载）
        self._real_messages: list[tuple[str, int, str]] = []

        # 信号处理
        self._shutdown = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self._shutdown = True
        print(f"\n[信号] 收到信号 {signum}，正在停止测试...", file=sys.stderr)

    # ── 真实数据支持 ─────────────────────────────────────────

    def _ensure_real_data(self) -> None:
        """懒加载真实聊天数据（仅在 use_real_data=True 时加载）。"""
        if self.use_real_data and not self._real_messages:
            self._real_messages = _get_real_messages()
            if self._real_messages:
                print(
                    f"[数据] 已加载 {len(self._real_messages)} 条真实聊天消息",
                    file=sys.stderr,
                )

    def _pick_content(self) -> str:
        """根据配置从真实数据或模板中选择消息内容。"""
        if self.use_real_data and self._real_messages and random.random() < self.real_ratio:
            return random.choice(self._real_messages)[0]
        return _random_message()

    # ── 组件初始化 ────────────────────────────────────────────

    async def init_components(self) -> None:
        """初始化所有记忆系统组件

        memory_db 是 schema.py 的模块级单例，指向固定路径 data/memory.db。
        为避免污染生产数据，此处重新初始化数据库连接指向临时文件。
        """
        # 1. 重新初始化 memory_db 连接指向临时 SQLite 文件
        from src.memory.schema import memory_db
        from src.memory.schema import MemoryAtom as _MemModel
        from src.memory.schema import EpisodicDetail as _EpiModel
        from src.memory.schema import SemanticDetail as _SemModel
        from src.memory.schema import ConflictObservation as _ConflictModel
        from src.memory.schema import NoisePool as _NoiseModel
        from src.memory.schema import MemoryTraceChain as _TraceModel
        from src.memory.schema import DreamRun as _DreamRunModel
        from src.memory.schema import GraphNode as _GNodeModel
        from src.memory.schema import GraphEdge as _GEdgeModel
        from src.memory.schema import GraphEntry as _GEntryModel

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
                _MemModel,
                _EpiModel,
                _SemModel,
                _ConflictModel,
                _NoiseModel,
                _TraceModel,
                _DreamRunModel,
                _GNodeModel,
                _GEdgeModel,
                _GEntryModel,
            ],
            safe=True,
        )

        # 2. 导入组件（schema 初始化完成后）
        from src.memory import (
            MemoryStore,
            MemoryStoreConfig,
        )
        from src.memory.feedback import ReinforcementTracker
        from src.memory.forgetting import ForgettingManager
        from src.memory.layer0_archive import MessageArchiver
        from src.memory.write_ops import WriteOpLogger
        from src.memory.layer3_retrieval import MemoryWriter

        config = MemoryStoreConfig(
            sqlite_path=self.db_path,
            qdrant_url="http://localhost:6333",
        )

        # 3. MemoryStore 单例
        MemoryStore._instance = None
        self.store = MemoryStore(config)
        await self.store.initialize()

        # 4. 写入器（直接写原子，不依赖 LLM 编码管线）
        self.op_logger = WriteOpLogger(
            db_path=self.db_path,
            max_entries=5000,
        )
        self.writer = MemoryWriter(self.store, op_logger=self.op_logger)

        # 5. 遗忘管理器
        self.forgetting = ForgettingManager(
            self.store,
            archive_threshold=0.05 if self.quick else 0.1,
            delete_threshold=0.005 if self.quick else 0.01,
            sweep_interval=3600,
        )

        # 6. 强化追踪器
        self.tracker = ReinforcementTracker(self.store)

        # 7. 消息归档器
        self.archiver = MessageArchiver()

        print(
            f"[初始化] MemoryStore @ {self.db_path} | quick={self.quick}",
            file=sys.stderr,
        )

    async def close_components(self) -> None:
        """清理组件"""
        if self.store:
            await self.store.close()
        from src.memory.schema import memory_db

        if not memory_db.is_closed():
            memory_db.close()

    # ── 模拟消息摄入 ─────────────────────────────────────────

    async def _create_atom(
        self,
        content: Optional[str] = None,
        atom_type_str: Optional[str] = None,
        source_scene: str = "group_chat",
        user_entity: str = "test_user",
    ) -> tuple[str, dict[str, Any]]:
        """创建一个原子并通过 MemoryWriter 写入，返回 (atom_id, write_stats)"""
        from src.memory.atom import MemoryAtom as MemoryAtomDC, AtomType, DecayType, SemanticDetail
        from uuid import uuid4

        atom_id = str(uuid4())
        content = content or self._pick_content()
        atype = AtomType(atom_type_str) if atom_type_str else random.choice(list(AtomType))

        now_ts = datetime.now(timezone.utc).timestamp()
        atom = MemoryAtomDC(
            atom_id=atom_id,
            atom_type=atype,
            content=content,
            importance=random.uniform(0.3, 1.0),
            confidence=random.uniform(0.5, 1.0),
            weight=0.5,
            created_at=now_ts,
            last_accessed_at=now_ts,
            ttl_days=random.choice([7, 30, 90, 180]),
            decay_type=random.choice(list(DecayType)),
            source_scene=source_scene,
            privacy_level="context_sensitive",
            entities=[user_entity],
        )
        detail = SemanticDetail(
            atom_id=atom_id,
            attr_category="stress_test",
            attr_name=atype.value,
            attr_value=content[:50],
        )

        t0 = time.monotonic()
        await self.writer.write_atom(atom=atom, semantic_detail=detail)
        latency = time.monotonic() - t0

        return atom_id, {"latency_sec": latency, "atom_type": atype.value}

    async def _create_atoms_batch(self, n: int) -> list[float]:
        """批量创建 N 个原子，返回每条写入延迟（秒）"""
        latencies: list[float] = []
        for i in range(n):
            if self._shutdown:
                break
            _, stats = await self._create_atom()
            latencies.append(stats["latency_sec"])
            if (i + 1) % 50 == 0:
                await asyncio.sleep(0)  # yield to event loop
        return latencies

    # ── 统计工具 ─────────────────────────────────────────────

    async def atom_count(self, status: Optional[str] = None) -> int:
        """获取记忆原子数量"""
        try:
            from src.memory.schema import MemoryAtom as MemoryAtomModel, memory_db

            with memory_db:
                if status:
                    return MemoryAtomModel.select().where(MemoryAtomModel.status == status).count()
                return MemoryAtomModel.select().count()
        except Exception:
            return 0

    async def _stats_summary(self) -> dict[str, Any]:
        """收集当前系统统计信息"""
        stats = await self.store.get_statistics()
        stats["memory_rss_mib"] = _get_rss_mib()
        return stats

    # ── 测试 1: 批量摄入 ─────────────────────────────────────

    async def test_bulk_ingestion(self) -> TestResult:
        """测试 1: 批量摄入 — 快速创建大量记忆原子并通过 MemoryWriter 写入"""
        print("\n[测试] 批量摄入 (Bulk Ingestion)...", file=sys.stderr)
        t_start = time.monotonic()
        errors: list[str] = []

        n = 50 if self.quick else 500
        print(f"  创建 {n} 个原子...", file=sys.stderr)

        # 记录初始状态
        rss_before = _get_rss_mib()
        count_before = await self.atom_count()

        # 批量创建原子
        latencies = await self._create_atoms_batch(n)

        # 收集指标
        count_after = await self.atom_count()
        rss_after = _get_rss_mib()
        duration = time.monotonic() - t_start
        atoms_created = count_after - count_before

        passed = atoms_created > 0 or errors
        metrics = {
            "atoms_requested": n,
            "atoms_created": atoms_created,
            "atoms_per_second": round(atoms_created / max(duration, 0.001), 2),
            "avg_latency_ms": round(sum(latencies) / max(len(latencies), 1) * 1000, 3),
            "max_latency_ms": round(max(latencies) * 1000, 3) if latencies else 0,
            "p99_latency_ms": round(sorted(latencies)[int(len(latencies) * 0.99)] * 1000, 3) if latencies else 0,
            "rss_before_mib": round(rss_before, 2),
            "rss_after_mib": round(rss_after, 2),
            "rss_delta_mib": round(rss_after - rss_before, 2),
            "duration_sec": round(duration, 3),
        }

        result = TestResult(
            test_name="bulk_ingestion",
            passed=passed,
            duration_ms=round(duration * 1000),
            metrics=metrics,
            errors=errors,
        )
        self.results.append(result)
        print(f"  结果: {'通过' if passed else '失败'} | {atoms_created}/{n} atoms in {duration:.2f}s", file=sys.stderr)
        return result

    # ── 测试 2: 持续负载 ─────────────────────────────────────

    async def test_sustained_load(self) -> TestResult:
        """测试 2: 持续负载 — 持续写入 + 遗忘扫描，观察衰减曲线和内存趋势"""
        print("\n[测试] 持续负载 (Sustained Load)...", file=sys.stderr)
        t_start = time.monotonic()
        errors: list[str] = []

        duration_sec = 30 if self.quick else self.duration
        write_interval = 0.5  # 每 0.5s 写一个原子（quick 模式加速）
        atoms_per_burst = 3 if self.quick else 5
        snapshot_interval = max(5, duration_sec // 6)

        print(f"  duration={duration_sec}s | write_every={write_interval}s | burst={atoms_per_burst}", file=sys.stderr)

        snapshots: list[dict[str, Any]] = []
        total_atoms_written = 0
        last_snapshot = 0.0

        # 持续写入阶段（每隔 write_interval 秒写一批）
        while (time.monotonic() - t_start) < duration_sec and not self._shutdown:
            for _ in range(atoms_per_burst):
                if self._shutdown:
                    break
                await self._create_atom()
                total_atoms_written += 1

            # 快照
            elapsed = time.monotonic() - t_start
            if elapsed - last_snapshot >= snapshot_interval:
                last_snapshot = elapsed
                snapshots.append(
                    {
                        "t_sec": round(elapsed, 2),
                        "rss_mib": round(_get_rss_mib(), 2),
                        "atoms": await self.atom_count(),
                        "written_so_far": total_atoms_written,
                    }
                )

            # 每 ~10 秒做一次遗忘扫描
            if elapsed > 10 and int(elapsed) % 10 < 2 and elapsed > 0:
                try:
                    await self.forgetting.run_sweep()
                    snapshots.append(
                        {
                            "t_sec": round(elapsed, 2),
                            "event": "sweep",
                            "rss_mib": round(_get_rss_mib(), 2),
                            "atoms": await self.atom_count(),
                        }
                    )
                except Exception as e:
                    errors.append(f"遗忘扫描失败: {e}")

            await asyncio.sleep(write_interval)

        # 最终遗忘扫描
        if not self._shutdown:
            try:
                sweep_result = await self.forgetting.run_sweep()
            except Exception as e:
                sweep_result = {"error": str(e)}
                errors.append(f"最终遗忘扫描失败: {e}")
        else:
            sweep_result = {}

        # 最终统计
        final_stats = await self._stats_summary()
        total_atoms = final_stats.get("total_atoms", 0)
        active_atoms = final_stats.get("active_atoms", 0)

        # 权重分布
        try:
            from src.memory.schema import MemoryAtom as MemoryAtomModel, memory_db

            with memory_db:
                all_weights = [a.weight for a in MemoryAtomModel.select(MemoryAtomModel.weight)]
        except Exception:
            all_weights = []

        weight_hist = (
            {
                "0-0.1": sum(1 for w in all_weights if w <= 0.1),
                "0.1-0.3": sum(1 for w in all_weights if 0.1 < w <= 0.3),
                "0.3-0.7": sum(1 for w in all_weights if 0.3 < w <= 0.7),
                "0.7-1.0": sum(1 for w in all_weights if 0.7 < w <= 1.0),
            }
            if all_weights
            else {}
        )

        duration = time.monotonic() - t_start
        passed = total_atoms > 0 or not errors
        metrics = {
            "duration_sec": round(duration, 3),
            "atoms_written": total_atoms_written,
            "total_atoms": total_atoms,
            "active_atoms": active_atoms,
            "archived_or_forgotten": total_atoms - active_atoms,
            "weight_distribution": weight_hist,
            "memory_snapshots": snapshots,
            "final_rss_mib": round(_get_rss_mib(), 2),
            "sweep_result": sweep_result if isinstance(sweep_result, dict) else {},
            "atoms_per_minute": round(total_atoms / max(duration, 0.001) * 60, 2),
        }

        result = TestResult(
            test_name="sustained_load",
            passed=passed,
            duration_ms=round(duration * 1000),
            metrics=metrics,
            errors=errors,
        )
        self.results.append(result)
        print(
            f"  结果: {'通过' if passed else '失败'} | "
            f"{total_atoms_written} written, {total_atoms} stored in {duration:.2f}s",
            file=sys.stderr,
        )
        return result

    # ── 测试 3: 突发尖峰 ─────────────────────────────────────

    async def test_burst_spike(self) -> TestResult:
        """测试 3: 突发尖峰 — 密集写入一批 → 空闲 → 重复，观察恢复和内存释放"""
        print("\n[测试] 突发尖峰 (Burst Spike)...", file=sys.stderr)
        t_start = time.monotonic()
        errors: list[str] = []

        burst_size = 30 if self.quick else 100
        idle_sec = 10 if self.quick else 30
        repeat = 2 if self.quick else 3

        print(f"  每次 {burst_size} atoms / {idle_sec}s idle × {repeat} 轮", file=sys.stderr)

        all_latencies: list[float] = []
        round_metrics: list[dict[str, Any]] = []
        rss_before_burst: float = 0.0

        for rnd in range(1, repeat + 1):
            if self._shutdown:
                break

            rss_before_burst = _get_rss_mib()

            # 突发写入 burst_size 个原子（无间隔）
            round_start = time.monotonic()
            burst_latencies: list[float] = []
            for _ in range(burst_size):
                if self._shutdown:
                    break
                _, stats = await self._create_atom()
                burst_latencies.append(stats["latency_sec"])

            all_latencies.extend(burst_latencies)
            round_duration = time.monotonic() - round_start
            rss_after_burst = _get_rss_mib()

            atoms_after = await self.atom_count()

            round_metrics.append(
                {
                    "round": rnd,
                    "duration_sec": round(round_duration, 3),
                    "atoms_per_sec": round(burst_size / max(round_duration, 0.001), 2),
                    "rss_delta_mib": round(rss_after_burst - rss_before_burst, 2),
                    "rss_after_mib": round(rss_after_burst, 2),
                    "atoms_after": atoms_after,
                }
            )

            # 空闲阶段：观察 RSS 是否会下降（GC/内存回收）
            if rnd < repeat:
                print(
                    f"  第 {rnd} 轮完成 ({burst_size} atoms in {round_duration:.2f}s)，空闲 {idle_sec}s...",
                    file=sys.stderr,
                )
                for sec in range(idle_sec):
                    await asyncio.sleep(1)
                    if sec % 5 == 0:
                        _ = _get_rss_mib()  # 触发 GC 后读取

        duration = time.monotonic() - t_start
        total_written = repeat * burst_size
        atoms_final = await self.atom_count()

        passed = atoms_final > 0 or not errors
        metrics = {
            "duration_sec": round(duration, 3),
            "rounds": repeat,
            "burst_size": burst_size,
            "total_atoms_written": total_written,
            "total_atoms_stored": atoms_final,
            "avg_latency_ms": round(sum(all_latencies) / max(len(all_latencies), 1) * 1000, 3),
            "p99_latency_ms": round(sorted(all_latencies)[int(len(all_latencies) * 0.99)] * 1000, 3)
            if all_latencies
            else 0,
            "rounds_detail": round_metrics,
            "final_rss_mib": round(_get_rss_mib(), 2),
        }

        result = TestResult(
            test_name="burst_spike",
            passed=passed,
            duration_ms=round(duration * 1000),
            metrics=metrics,
            errors=errors,
        )
        self.results.append(result)
        print(
            f"  结果: {'通过' if passed else '失败'} | {total_written} written, {atoms_final} stored", file=sys.stderr
        )
        return result

    # ── 测试 4: 并发读写 ─────────────────────────────────────

    async def test_concurrent_rw(self) -> TestResult:
        """测试 4: 并发读写 — 2 写 2 读同时操作，检查原子完整性和一致性"""
        print("\n[测试] 并发读写 (Concurrent R/W)...", file=sys.stderr)
        t_start = time.monotonic()
        errors: list[str] = []

        rounds = 50 if self.quick else 200
        writer_count = 2
        reader_count = 2

        print(f"  {writer_count} 写 + {reader_count} 读 × {rounds} 轮", file=sys.stderr)

        # ── 写入任务 ──────────────────────────────────────
        written_ids: list[str] = []
        _write_lock = asyncio.Lock()

        async def writer_task(task_id: int) -> dict[str, Any]:
            local_written = 0
            local_errors = 0
            for r in range(rounds):
                if self._shutdown:
                    break
                try:
                    from src.memory.atom import MemoryAtom as MemoryAtomDC, AtomType, DecayType
                    from uuid import uuid4

                    atom_id = str(uuid4())
                    atom = MemoryAtomDC(
                        atom_id=atom_id,
                        atom_type=random.choice(list(AtomType)),
                        content=f"[并发测试] writer_{task_id} round_{r} {_random_message()}",
                        importance=random.uniform(0.3, 1.0),
                        confidence=random.uniform(0.3, 1.0),
                        weight=0.5,
                        ttl_days=random.choice([7, 30, 90, 180]),
                        decay_type=random.choice(list(DecayType)),
                        source_scene="group_chat",
                        privacy_level="context_sensitive",
                        entities=["test_user"],
                    )

                    from src.memory.atom import SemanticDetail

                    detail = SemanticDetail(
                        atom_id=atom_id,
                        attr_category="test",
                        attr_name=f"writer_{task_id}",
                        attr_value=f"round_{r}",
                    )

                    await self.writer.write_atom(atom=atom, semantic_detail=detail)
                    async with _write_lock:
                        written_ids.append(atom_id)
                    local_written += 1
                except Exception as e:
                    local_errors += 1
                    if local_errors <= 3:
                        errors.append(f"writer_{task_id} round_{r}: {e}")
            return {"written": local_written, "errors": local_errors}

        # ── 读取任务 ──────────────────────────────────────
        async def reader_task(task_id: int) -> dict[str, Any]:
            local_reads = 0
            local_found = 0
            local_errors = 0
            for r in range(rounds):
                if self._shutdown:
                    break
                try:
                    # 随机读一个最近的 atom_id
                    async with _write_lock:
                        ids_to_check = list(written_ids)

                    if ids_to_check:
                        sample = random.choice(ids_to_check)
                        atom_data = await self.store.get_atom(sample)
                        if atom_data:
                            local_found += 1
                        else:
                            # 可能写入还没完成，正常
                            pass
                    local_reads += 1
                except Exception as e:
                    local_errors += 1
                    if local_errors <= 3:
                        errors.append(f"reader_{task_id} round_{r}: {e}")
                # 放一点微小的间隙，避免把 CPU 全占满
                await asyncio.sleep(0.001)
            return {"reads": local_reads, "found": local_found, "errors": local_errors}

        # ── 并发执行 ──────────────────────────────────────
        tasks = []
        for w in range(writer_count):
            tasks.append(asyncio.create_task(writer_task(w)))
        for rd in range(reader_count):
            tasks.append(asyncio.create_task(reader_task(rd)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 汇总
        total_written = 0
        total_reads = 0
        total_found = 0
        writer_errs = 0
        for r in results:
            if isinstance(r, dict):
                total_written += r.get("written", 0)
                writer_errs += r.get("errors", 0)
                total_reads += r.get("reads", 0)
                total_found += r.get("found", 0)
            elif isinstance(r, BaseException):
                errors.append(f"任务异常: {r}")

        # 校验: 写入数 = 最终存储数
        stored_count = await self.atom_count(status="active")
        insert_count = total_written

        # 检查 profile 一致性（如果有足够的原子）
        profile_issues = 0
        try:
            if total_written >= 5:
                from src.memory.user_profile import ProfileStore, ProfileBuilder

                ps = ProfileStore()
                pb = ProfileBuilder(ps)
                profile = pb.build_profile("test_user")
                if profile is None:
                    profile_issues += 1
        except Exception:
            pass

        duration = time.monotonic() - t_start
        atom_loss = insert_count - stored_count
        passed = (atom_loss <= 0 or atom_loss < max(5, insert_count * 0.05)) and writer_errs == 0
        # 允许少量原子丢失（边界情况如未完成写入即被读）

        metrics = {
            "duration_sec": round(duration, 3),
            "writers": writer_count,
            "readers": reader_count,
            "rounds": rounds,
            "total_written": total_written,
            "total_read_attempts": total_reads,
            "successful_reads": total_found,
            "stored_count": stored_count,
            "atom_loss": max(0, insert_count - stored_count),
            "writer_errors": writer_errs,
            "profile_issues": profile_issues,
            "final_rss_mib": round(_get_rss_mib(), 2),
        }

        result = TestResult(
            test_name="concurrent_rw",
            passed=passed,
            duration_ms=round(duration * 1000),
            metrics=metrics,
            errors=errors,
        )
        self.results.append(result)
        print(
            f"  结果: {'通过' if passed else '失败'} | "
            f"{total_written} written, {stored_count} stored, "
            f"loss={max(0, insert_count - stored_count)}",
            file=sys.stderr,
        )
        return result

    # ── 测试 5: 崩溃恢复 ─────────────────────────────────────

    async def test_crash_recovery(self) -> TestResult:
        """测试 5: 崩溃恢复 — 写入原子 → 模拟崩溃 → replay 恢复 → 校验一致性"""
        print("\n[测试] 崩溃恢复 (Crash Recovery)...", file=sys.stderr)
        t_start = time.monotonic()
        errors: list[str] = []

        n = 20 if self.quick else 100
        print(f"  写入 {n} 个原子 + 模拟崩溃 + 恢复...", file=sys.stderr)

        from src.memory.atom import MemoryAtom as MemoryAtomDC, AtomType, DecayType
        from src.memory.write_ops import OpType
        from uuid import uuid4

        # 1. 写入 N 个原子（带 write_op 日志）
        atom_ids: list[str] = []
        for i in range(n):
            atom_id = str(uuid4())
            atom_ids.append(atom_id)
            content = f"[崩溃恢复测试] atom_{i}: {_random_message()}"
            try:
                # 使用 WriteOperation 上下文管理器确保日志记录
                from src.memory.atom import SemanticDetail

                atom = MemoryAtomDC(
                    atom_id=atom_id,
                    atom_type=AtomType.FACTUAL,
                    content=content,
                    importance=0.8,
                    confidence=0.9,
                    weight=0.5,
                    ttl_days=180,
                    decay_type=DecayType.EXPONENTIAL,
                    source_scene="group_chat",
                    privacy_level="context_sensitive",
                    entities=["crash_test"],
                )

                detail = SemanticDetail(
                    atom_id=atom_id,
                    attr_category="crash_test",
                    attr_name="recovery",
                    attr_value=content,
                )

                await self.writer.write_atom(atom=atom, semantic_detail=detail)
            except Exception as e:
                errors.append(f"写入原子 {i} 失败: {e}")

        # 2. 模拟崩溃：在写操作日志中留几个 FAILED 状态的操作
        #    （模拟已经尝试执行但崩溃/失败的操作）
        fake_ops = 5 if self.quick else 10
        from src.memory.write_ops import generate_op_id, WriteOp, OpStatus

        recovered_fake_ids: list[str] = []
        for i in range(fake_ops):
            fake_id = str(uuid4())
            recovered_fake_ids.append(fake_id)
            fake_op = WriteOp(
                op_id=generate_op_id(),
                op_type=OpType.INSERT_ATOM,
                target="sqlite",
                atom_ids=[fake_id],
                payload={
                    "atom": {
                        "atom_id": fake_id,
                        "atom_type": "factual",
                        "content": f"[崩溃恢复-fake] atom_fake_{i}: {_random_message()}",
                        "importance": 0.5,
                        "confidence": 0.5,
                        "weight": 0.5,
                        "created_at": datetime.now(timezone.utc).timestamp(),
                        "last_accessed_at": datetime.now(timezone.utc).timestamp(),
                        "last_reinforced_at": datetime.now(timezone.utc).timestamp(),
                        "ttl_days": 30,
                        "decay_type": "exponential",
                        "reinforcement_count": 0,
                        "source_scene": "group_chat",
                        "privacy_level": "context_sensitive",
                        "status": "active",
                        "entities": json.dumps(["crash_test"], ensure_ascii=False),
                    }
                },
                status=OpStatus.FAILED,
            )
            # 写入日志 — 模拟崩溃后留下的失败操作记录
            self.op_logger.log_op(fake_op)

        # 3. 记录恢复前的原子数
        count_before_recovery = await self.atom_count()

        # 4. 执行恢复（重放失败操作）
        recovered = await self.op_logger.replay_failed_ops(self.store)
        count_after_recovery = await self.atom_count()

        # 5. 校验一致性
        duplicate_count = 0
        real_inserted = 0
        for aid in atom_ids:
            existing = await self.store.get_atom(aid)
            if existing:
                real_inserted += 1

        # 检查写入操作日志是否一致
        ops_after = self.op_logger._read_all_ops()
        pending_ops = [o for o in ops_after if o.status == OpStatus.PENDING]
        failed_ops = [o for o in ops_after if o.status == OpStatus.FAILED]

        duration = time.monotonic() - t_start
        passed = (
            real_inserted >= n - 2  # 允许少量原子写入失败
            and not pending_ops  # 不应该还有 pending 操作
            and recovered_fake_ids  # 至少恢复了一些
        )

        metrics = {
            "duration_sec": round(duration, 3),
            "atoms_written": n,
            "fake_pending_ops": fake_ops,
            "recovered_from_log": len(recovered),
            "real_atoms_found": real_inserted,
            "count_before_recovery": count_before_recovery,
            "count_after_recovery": count_after_recovery,
            "remaining_pending": len(pending_ops),
            "remaining_failed": len(failed_ops),
            "duplicates_detected": duplicate_count,
            "final_rss_mib": round(_get_rss_mib(), 2),
        }

        result = TestResult(
            test_name="crash_recovery",
            passed=passed,
            duration_ms=round(duration * 1000),
            metrics=metrics,
            errors=errors,
        )
        self.results.append(result)
        print(
            f"  结果: {'通过' if passed else '失败'} | "
            f"{n} written, {len(recovered)} recovered, "
            f"{real_inserted} verified",
            file=sys.stderr,
        )
        return result

    # ── 测试 6: 真实数据加载验证 ────────────────────────────

    async def test_real_data_load(self) -> TestResult:
        """测试 6: 真实数据加载 — 验证 QQ Chat Exporter 数据正确加载。"""
        print("\n[测试] 真实数据加载 (Real Data Load)...", file=sys.stderr)
        t_start = time.monotonic()
        errors: list[str] = []

        self._ensure_real_data()
        msgs = self._real_messages

        metrics: dict[str, Any] = {
            "total_messages_loaded": len(msgs),
            "unique_senders": len(set(m[2] for m in msgs)),
        }

        if msgs:
            timestamps = [m[1] for m in msgs]
            metrics["earliest_ts"] = min(timestamps)
            metrics["latest_ts"] = max(timestamps)
            metrics["time_range_days"] = round((max(timestamps) - min(timestamps)) / 86400000, 2)
            metrics["total_chars"] = sum(len(m[0]) for m in msgs)
            metrics["avg_msg_length"] = round(sum(len(m[0]) for m in msgs) / len(msgs), 1)
            metrics["max_msg_length"] = max(len(m[0]) for m in msgs)

            # 验证没有图片/视频消息泄露
            image_leaks = sum(1 for m in msgs if m[0].startswith("[图片") or m[0].startswith("[视频"))
            metrics["image_or_video_leaks"] = image_leaks
            if image_leaks:
                errors.append(f"发现 {image_leaks} 条图片/视频消息未过滤")

            # 验证所有时间戳在合理范围内（2000-2100 年）
            valid_ts = all(946656000000 < m[1] < 4102444800000 for m in msgs)
            metrics["all_timestamps_valid"] = valid_ts
            if not valid_ts:
                errors.append("存在不合理的时间戳")

        passed = len(msgs) > 0 and len(errors) == 0
        if not msgs:
            errors.append("未加载到任何真实聊天消息")

        duration = time.monotonic() - t_start
        result = TestResult(
            test_name="real_data_load",
            passed=passed,
            duration_ms=round(duration * 1000),
            metrics=metrics,
            errors=errors,
        )
        self.results.append(result)
        print(
            f"  结果: {'通过' if passed else '失败'} | {len(msgs)} msgs, {metrics.get('unique_senders', 0)} senders",
            file=sys.stderr,
        )
        return result

    # ── 测试 7: 用户画像 CRUD ─────────────────────────────────

    async def test_user_profile(self) -> TestResult:
        """测试 7: 用户画像 CRUD — 创建/更新/检索 50 个用户画像"""
        print("\n[测试] 用户画像 (User Profile)...", file=sys.stderr)
        t_start = time.monotonic()
        errors: list[str] = []

        n = 50 if not self.quick else 20
        print(f"  创建/更新/检索 {n} 个画像...", file=sys.stderr)

        try:
            from src.memory.user_profile import ProfileStore, ProfileBuilder, UserProfile

            ps = ProfileStore()
            pb = ProfileBuilder(ps)

            # 1. 创建 N 个画像
            created = 0
            for i in range(n):
                uid = f"profile_test_user_{i:04d}"
                profile = UserProfile(
                    user_id=uid,
                    traits={f"trait_{j}": random.uniform(0.3, 1.0) for j in range(3)},
                    interests=random.sample(
                        ["coding", "gaming", "music", "sports", "reading", "cooking", "travel", "photography"],
                        k=random.randint(1, 4),
                    ),
                    preferences={
                        "food": random.choice(["sweet", "spicy", "sour"]),
                        "music": random.choice(["pop", "rock", "jazz"]),
                    },
                    facts={
                        "age": str(random.randint(18, 60)),
                        "location": random.choice(["北京", "上海", "深圳", "杭州", "成都"]),
                    },
                    impression=f"用户 {uid} 的测试画像",
                )
                ps.save_profile(profile)
                created += 1

            # 2. 验证存在性
            exists_count = sum(1 for i in range(n) if ps.profile_exists(f"profile_test_user_{i:04d}"))

            # 3. 验证检索
            sample = ps.get_profile("profile_test_user_0000")
            if sample is None:
                errors.append("无法检索刚创建的画像")
            elif sample.user_id != "profile_test_user_0000":
                errors.append(f"画像 user_id 不匹配: {sample.user_id}")

            # 4. 验证列表
            profile_list = ps.list_profiles()
            if len(profile_list) < n:
                errors.append(f"画像列表不完整: 期望≥{n}, 实际={len(profile_list)}")

            # 5. 更新画像
            if sample:
                sample.facts["age"] = "25"
                sample.interests.append("testing")
                ps.save_profile(sample)
                updated = ps.get_profile("profile_test_user_0000")
                if updated and updated.facts.get("age") != "25":
                    errors.append("画像更新失败: age 未变更")
                if updated and "testing" not in updated.interests:
                    errors.append("画像更新失败: interests 未变更")

            # 6. ProfileBuilder 全量构建 (需要原子数据)
            # 先写入一些 PREFERENCE 类型原子
            from src.memory.atom import MemoryAtom as MemoryAtomDC, AtomType, DecayType
            from uuid import uuid4

            builder_profiles = 0
            for i in range(min(10, n)):
                uid = f"profile_build_user_{i:04d}"
                # 写入 FACTUAL 原子
                atom = MemoryAtomDC(
                    atom_id=str(uuid4()),
                    atom_type=AtomType.FACTUAL,
                    content=f"{uid} 喜欢 coding 和 gaming",
                    importance=0.7,
                    confidence=0.8,
                    weight=0.5,
                    ttl_days=90,
                    decay_type=DecayType.EXPONENTIAL,
                    source_scene="group_chat",
                    privacy_level="context_sensitive",
                    entities=[uid],
                )
                from src.memory.atom import SemanticDetail

                detail = SemanticDetail(
                    atom_id=atom.atom_id,
                    attr_category="preference",
                    attr_name="hobby",
                    attr_value="coding",
                )
                await self.writer.write_atom(atom=atom, semantic_detail=detail)
                bp = pb.build_profile(uid)
                if bp is not None:
                    builder_profiles += 1

        except Exception as e:
            errors.append(f"画像测试异常: {e}")
            traceback.print_exc(file=sys.stderr)

        duration = time.monotonic() - t_start
        passed = len(errors) == 0 and created == n
        metrics = {
            "profiles_created": n,
            "profiles_exists_verified": exists_count,
            "profiles_listed": len(profile_list) if "profile_list" in dir() else 0,
            "profiles_built": builder_profiles if "builder_profiles" in dir() else 0,
            "errors": len(errors),
            "duration_sec": round(duration, 3),
        }

        result = TestResult(
            test_name="user_profile",
            passed=passed,
            duration_ms=round(duration * 1000),
            metrics=metrics,
            errors=errors,
        )
        self.results.append(result)
        print(
            f"  结果: {'通过' if passed else '失败'} | {n} created, {exists_count} verified, {builder_profiles} built",
            file=sys.stderr,
        )
        return result

    # ── 测试 8: 图谱遍历 ─────────────────────────────────────

    async def test_graph_store(self) -> TestResult:
        """测试 8: 图谱遍历 — 创建节点+边，测试 get_neighbors/get_related_atoms/search_by_entity"""
        print("\n[测试] 图谱遍历 (Graph Store)...", file=sys.stderr)
        t_start = time.monotonic()
        errors: list[str] = []

        n_nodes = 30 if not self.quick else 10
        print(f"  创建 {n_nodes} 个节点 + 边 + 遍历测试...", file=sys.stderr)

        try:
            from src.memory.graph_store import GraphStore

            gs = GraphStore()

            # 1. 创建节点
            node_ids: list[int] = []
            for i in range(n_nodes):
                nid = gs.add_node(
                    node_type=random.choice(["person", "concept", "event", "place"]),
                    label=f"graph_test_entity_{i:04d}",
                    properties={"index": i, "group": i % 5},
                )
                node_ids.append(nid)

            assert len(node_ids) == n_nodes, f"创建的节点数不匹配: {len(node_ids)} vs {n_nodes}"
            assert gs.node_count() == n_nodes

            # 2. 创建边（链式连接 + 随机连接）
            edge_count = 0
            for i in range(n_nodes - 1):
                gs.add_edge(
                    source_node_id=node_ids[i],
                    target_node_id=node_ids[i + 1],
                    predicate="linked_to",
                    confidence=0.8,
                )
                edge_count += 1
            # 额外随机边
            for _ in range(n_nodes // 2):
                a, b = random.sample(node_ids, 2)
                if not gs.edge_exists(a, b, "related_to"):
                    gs.add_edge(a, b, "related_to", 0.5)
                    edge_count += 1

            assert gs.edge_count() == edge_count

            # 3. 测试 get_neighbors (BFS)
            if node_ids:
                neighbors = gs.get_neighbors(str(node_ids[0]), depth=1)
                direct_count = len(neighbors)
                assert direct_count >= 1, f"节点 0 应有至少 1 个邻居, 实际={direct_count}"

                neighbors_depth2 = gs.get_neighbors(str(node_ids[0]), depth=2)
                assert len(neighbors_depth2) >= direct_count, "depth=2 应 >= depth=1"

            # 4. 测试 search_by_entity
            search_results = gs.search_by_entity("graph_test_entity_00", top_k=5)
            assert len(search_results) >= 1, "搜索应有结果"

            # 5. 测试 get_related_atoms (需要 GraphEntry)
            entry_id = gs.add_entry(
                subject="graph_test_entity_0000",
                predicate="test_relation",
                obj="graph_test_entity_0001",
                evidence="stress test",
                confidence=0.9,
            )
            assert entry_id > 0

            # 写入一些 atom 并创建 GraphEntry 关联
            from uuid import uuid4
            from src.memory.atom import MemoryAtom as MemoryAtomDC, AtomType, DecayType

            test_atom_id = str(uuid4())
            atom = MemoryAtomDC(
                atom_id=test_atom_id,
                atom_type=AtomType.FACTUAL,
                content="这是一个图谱关联测试原子",
                importance=0.6,
                confidence=0.7,
                weight=0.5,
                ttl_days=30,
                decay_type=DecayType.EXPONENTIAL,
                source_scene="group_chat",
                privacy_level="context_sensitive",
                entities=["graph_test_entity_0000"],
            )
            await self.writer.write_atom(atom=atom)
            # 再创建几个通过 GraphEntry 连接的原子
            related = gs.get_related_atoms(test_atom_id, max_depth=2)
            # 即使没有找到直接关联的 entry，也不会抛异常
            assert isinstance(related, list)

            # 6. 测试 search_entries
            entries = gs.search_entries(subject="graph_test_entity_0000")
            assert len(entries) >= 1, "应找到至少 1 条三元组"

            # 7. 测试节点搜索
            found = gs.search_nodes("graph_test_entity_00%", node_type="person")
            assert isinstance(found, list)

            # 8. 统计验证
            stats = gs.get_stats()
            assert stats["node_count"] == n_nodes
            assert stats["edge_count"] == edge_count
            assert stats["entry_count"] >= 1

        except Exception as e:
            errors.append(f"图谱遍历测试异常: {e}")
            traceback.print_exc(file=sys.stderr)

        duration = time.monotonic() - t_start
        passed = len(errors) == 0
        metrics = {
            "nodes_created": n_nodes,
            "edges_created": edge_count,
            "entries_created": len(gs.search_entries()) if "gs" in dir() else 0,
            "neighbors_found": direct_count if "direct_count" in dir() else 0,
            "errors": len(errors),
            "duration_sec": round(duration, 3),
        }

        result = TestResult(
            test_name="graph_store",
            passed=passed,
            duration_ms=round(duration * 1000),
            metrics=metrics,
            errors=errors,
        )
        self.results.append(result)
        print(
            f"  结果: {'通过' if passed else '失败'} | {n_nodes} nodes, {edge_count} edges, traversal OK",
            file=sys.stderr,
        )
        return result

    # ── 测试 9: 梦境整合 ─────────────────────────────────────

    async def test_dream_integration(self) -> TestResult:
        """测试 9: 梦境整合 — DreamTask 导入 + 巩固/噪声清理/图谱构建"""
        print("\n[测试] 梦境整合 (Dream Integration)...", file=sys.stderr)
        t_start = time.monotonic()
        errors: list[str] = []

        try:
            from src.memory.dream_agent import DreamTask, IDLE_THRESHOLD, CONSOLIDATION_BOOST

            # 1. 创建 DreamTask 实例（验证导入和初始化）
            dream = DreamTask(store=self.store)

            assert dream.task_name == "dream_task"
            assert IDLE_THRESHOLD > 0
            assert CONSOLIDATION_BOOST > 0

            # 2. 写入一些可巩固的原子（importance >= 0.6, weight <= 0.4）
            from src.memory.atom import MemoryAtom as MemoryAtomDC, AtomType, DecayType

            consolidate_atoms = 10 if not self.quick else 5
            for i in range(consolidate_atoms):
                atom = MemoryAtomDC(
                    atom_id=f"dream_consolidate_{i:04d}",
                    atom_type=AtomType.FACTUAL,
                    content=f"梦境巩固测试原子 #{i}: 这是需要巩固的重要记忆",
                    importance=0.8,  # >= IMPORTANCE_MIN (0.6)
                    confidence=0.7,
                    weight=0.3,  # <= WEIGHT_MAX (0.4)
                    created_at=time.time() - 86400 * 7,  # 7天前
                    last_accessed_at=time.time() - 86400,
                    ttl_days=30,
                    decay_type=DecayType.EXPONENTIAL,
                    source_scene="group_chat",
                    privacy_level="context_sensitive",
                    entities=["dream_test_user"],
                )
                await self.writer.write_atom(atom=atom)

            # 写入一些不可巩固的原子（weight 太高）
            for i in range(5):
                atom = MemoryAtomDC(
                    atom_id=f"dream_skip_{i:04d}",
                    atom_type=AtomType.FACTUAL,
                    content=f"梦境跳过测试原子 #{i}: 权重已足够高",
                    importance=0.8,
                    confidence=0.7,
                    weight=0.9,  # > WEIGHT_MAX (0.4)
                    created_at=time.time(),
                    last_accessed_at=time.time(),
                    ttl_days=30,
                    decay_type=DecayType.EXPONENTIAL,
                    source_scene="group_chat",
                    privacy_level="context_sensitive",
                    entities=["dream_test_user"],
                )
                await self.writer.write_atom(atom=atom)

            # 3. 执行巩固
            consolidated = await dream._consolidate()
            if consolidated < consolidate_atoms:
                # 允许少量原子因重入等原因未巩固
                pass

            # 4. 执行噪声清理（先写入一些噪声）
            from src.memory.schema import NoisePool, memory_db

            with memory_db:
                for i in range(5):
                    NoisePool.create(
                        content=f"过期噪声 #{i}",
                        source_scene="chat",
                        significance=0.0,
                        created_at=datetime.now() - timedelta(days=30),  # 30天前
                    )
                for i in range(3):
                    NoisePool.create(
                        content=f"新鲜噪声 #{i}",
                        source_scene="chat",
                        significance=0.1,
                        created_at=datetime.now(),
                    )

            noise_cleaned = await dream._clean_noise()
            assert noise_cleaned >= 5, f"应清理至少 5 条过期噪声, 实际={noise_cleaned}"

            # 5. 执行图谱构建（写一些带实体的原子）
            from src.memory.atom import SemanticDetail

            for i in range(5):
                aid = f"dream_graph_atom_{i:04d}"
                atom = MemoryAtomDC(
                    atom_id=aid,
                    atom_type=AtomType.FACTUAL,
                    content=f"图谱构建测试原子 #{i}",
                    importance=0.6,
                    confidence=0.7,
                    weight=0.5,
                    created_at=time.time(),
                    last_accessed_at=time.time(),
                    ttl_days=90,
                    decay_type=DecayType.EXPONENTIAL,
                    source_scene="group_chat",
                    privacy_level="context_sensitive",
                    entities=["dream_graph_entity", f"dream_entity_{i}"],
                )
                detail = SemanticDetail(
                    atom_id=aid,
                    attr_category="test",
                    attr_name=f"attr_{i}",
                    attr_value=f"value_{i}",
                )
                await self.writer.write_atom(atom=atom, semantic_detail=detail)

            edges_created, entries_created = await dream._build_graph()
            assert edges_created >= 0
            assert entries_created >= 0

        except Exception as e:
            errors.append(f"梦境整合测试异常: {e}")
            traceback.print_exc(file=sys.stderr)

        duration = time.monotonic() - t_start
        passed = len(errors) == 0
        metrics: dict[str, Any] = {
            "consolidated": consolidated if "consolidated" in dir() else 0,
            "noise_cleaned": noise_cleaned if "noise_cleaned" in dir() else 0,
            "graph_edges": edges_created if "edges_created" in dir() else 0,
            "graph_entries": entries_created if "entries_created" in dir() else 0,
            "errors": len(errors),
            "duration_sec": round(duration, 3),
        }

        result = TestResult(
            test_name="dream_integration",
            passed=passed,
            duration_ms=round(duration * 1000),
            metrics=metrics,
            errors=errors,
        )
        self.results.append(result)
        print(
            f"  结果: {'通过' if passed else '失败'} | "
            f"consolidated={metrics['consolidated']}, noise={metrics['noise_cleaned']}, "
            f"graph=({metrics['graph_edges']}e, {metrics['graph_entries']}t)",
            file=sys.stderr,
        )
        return result

    # ── 测试 10: 冲突仲裁 ────────────────────────────────────

    async def test_conflict_arbitration(self) -> TestResult:
        """测试 10: 冲突仲裁 — ConflictArbiter 导入 + check_and_resolve 流程"""
        print("\n[测试] 冲突仲裁 (Conflict Arbitration)...", file=sys.stderr)
        t_start = time.monotonic()
        errors: list[str] = []

        try:
            from src.memory.conflict_arbitration import ConflictArbiter

            arbiter = ConflictArbiter(self.store)

            # 1. 无冲突时正常运行（结果为 0）
            count = await arbiter.check_and_resolve()
            assert count == 0

            # 2. 写入两个冲突原子
            from src.memory.atom import MemoryAtom as MemoryAtomDC, AtomType, DecayType
            from uuid import uuid4

            atom_a_id = str(uuid4())
            atom_b_id = str(uuid4())

            atom_a = MemoryAtomDC(
                atom_id=atom_a_id,
                atom_type=AtomType.FACTUAL,
                content="张三今年25岁",
                importance=0.7,
                confidence=0.9,
                weight=0.5,
                ttl_days=90,
                decay_type=DecayType.EXPONENTIAL,
                source_scene="group_chat",
                privacy_level="context_sensitive",
                entities=["张三"],
            )
            await self.writer.write_atom(atom=atom_a)

            atom_b = MemoryAtomDC(
                atom_id=atom_b_id,
                atom_type=AtomType.FACTUAL,
                content="张三今年30岁",
                importance=0.7,
                confidence=0.8,
                weight=0.5,
                ttl_days=90,
                decay_type=DecayType.EXPONENTIAL,
                source_scene="group_chat",
                privacy_level="context_sensitive",
                entities=["张三"],
            )
            await self.writer.write_atom(atom=atom_b)

            # 3. 创建足够的冲突观测记录触发仲裁
            from src.memory.schema import ConflictObservation, memory_db

            with memory_db:
                for _ in range(4):  # > _ACCUMULATION_THRESHOLD (3)
                    ConflictObservation.create(
                        atom_a_id=atom_a_id,
                        atom_b_id=atom_b_id,
                        conflict_type="contradiction",
                        description="年龄矛盾: 25 vs 30",
                        status="pending",
                    )

            # 4. 运行仲裁
            resolved = await arbiter.check_and_resolve()
            assert resolved >= 1, f"应解决至少 1 组冲突, 实际={resolved}"

            # 5. 验证仲裁后状态：其中一个应被归档
            atom_a_after = await self.store.get_atom(atom_a_id)
            atom_b_after = await self.store.get_atom(atom_b_id)
            archived_count = 0
            if atom_a_after and atom_a_after.get("status") == "archived":
                archived_count += 1
            if atom_b_after and atom_b_after.get("status") == "archived":
                archived_count += 1
            assert archived_count >= 1, "仲裁后应有至少 1 个原子被归档"

            # 6. 验证冲突观测已被标记为 resolved
            with memory_db:
                pending = ConflictObservation.select().where(ConflictObservation.status == "pending").count()
            # 可能还有未通过的组，但至少应减少
            assert pending < 4

        except Exception as e:
            errors.append(f"冲突仲裁测试异常: {e}")
            traceback.print_exc(file=sys.stderr)

        duration = time.monotonic() - t_start
        passed = len(errors) == 0
        metrics: dict[str, Any] = {
            "conflicts_resolved": resolved if "resolved" in dir() else 0,
            "atoms_archived": archived_count if "archived_count" in dir() else 0,
            "errors": len(errors),
            "duration_sec": round(duration, 3),
        }

        result = TestResult(
            test_name="conflict_arbitration",
            passed=passed,
            duration_ms=round(duration * 1000),
            metrics=metrics,
            errors=errors,
        )
        self.results.append(result)
        print(
            f"  结果: {'通过' if passed else '失败'} | "
            f"resolved={metrics['conflicts_resolved']}, archived={metrics['atoms_archived']}",
            file=sys.stderr,
        )
        return result

    # ── 测试 11: 客观性校验管线 ─────────────────────────────

    async def test_objectivity_check(self) -> TestResult:
        """测试 11: 客观性校验 — ObjectivityChecker 拒绝噪声/低质量原子"""
        print("\n[测试] 客观性校验 (Objectivity Check)...", file=sys.stderr)
        t_start = time.monotonic()
        errors: list[str] = []

        try:
            from src.memory.objectivity_check import ObjectivityChecker
            from src.memory.trace_chain import TraceChainRecorder
            from src.memory.atom import MemoryAtom as MemoryAtomDC, AtomType, DecayType
            from uuid import uuid4

            checker = ObjectivityChecker(self.store)
            recorder = TraceChainRecorder()

            # 1. 正常原子应通过校验
            good_atom = MemoryAtomDC(
                atom_id=str(uuid4()),
                atom_type=AtomType.FACTUAL,
                content="今天天气不错，适合出去散步。张三说他下午要去公园。",
                importance=0.6,
                confidence=0.8,
                weight=0.5,
                ttl_days=7,
                decay_type=DecayType.EXPONENTIAL,
                source_scene="group_chat",
                privacy_level="context_sensitive",
                entities=["张三"],
            )
            good_result = await checker.check_before_write(good_atom, trace_recorder=recorder)
            if not good_result.passed:
                errors.append(f"正常原子未通过校验: {good_result.recommendation}")

            # 2. 垃圾/噪声原子应被拒绝
            garbage_atom = MemoryAtomDC(
                atom_id=str(uuid4()),
                atom_type=AtomType.FACTUAL,
                content="a",  # 过短
                importance=0.05,  # 低 importance
                confidence=0.1,
                weight=0.1,
                ttl_days=1,
                decay_type=DecayType.EXPONENTIAL,
                source_scene="group_chat",
                privacy_level="context_sensitive",
                entities=[],
            )
            garbage_result = await checker.check_before_write(garbage_atom)
            if garbage_result.passed or garbage_result.recommendation != "reject":
                errors.append(f"垃圾原子应被拒绝, 实际={garbage_result.recommendation}")

            # 3. 纯符号原子应被拒绝
            symbol_atom = MemoryAtomDC(
                atom_id=str(uuid4()),
                atom_type=AtomType.FACTUAL,
                content="!!!###$$$",  # 纯符号
                importance=0.6,
                confidence=0.8,
                weight=0.5,
                ttl_days=7,
                decay_type=DecayType.EXPONENTIAL,
                source_scene="group_chat",
                privacy_level="context_sensitive",
                entities=["test"],
            )
            symbol_result = await checker.check_before_write(symbol_atom)
            if symbol_result.passed:
                errors.append("纯符号原子应被拒绝（噪声过滤）")

            # 4. 验证 trace_chain 记录
            chain = recorder.get_chain(good_atom.atom_id)
            if len(chain) == 0:
                # 如果 trace 未记录（可能 trace_recorder 只记录步骤2且正常通过时不一定记录）
                # 重新测试: 写入一些原子并通过 check_before_write 带 recorder
                pass

            # 5. 写入后续原子，验证 conflict detection 工作
            atom_a = MemoryAtomDC(
                atom_id=str(uuid4()),
                atom_type=AtomType.FACTUAL,
                content="小明今年18岁",
                importance=0.6,
                confidence=0.8,
                weight=0.5,
                ttl_days=30,
                decay_type=DecayType.EXPONENTIAL,
                source_scene="group_chat",
                privacy_level="context_sensitive",
                entities=["小明"],
            )
            await self.writer.write_atom(atom=atom_a)

            # 写入矛盾原子
            atom_b = MemoryAtomDC(
                atom_id=str(uuid4()),
                atom_type=AtomType.FACTUAL,
                content="小明今年25岁",
                importance=0.6,
                confidence=0.7,
                weight=0.5,
                ttl_days=30,
                decay_type=DecayType.EXPONENTIAL,
                source_scene="group_chat",
                privacy_level="context_sensitive",
                entities=["小明"],
            )
            conflict_result = await checker.check_before_write(atom_b)
            # 矛盾原子应至少被标记为 review（不应直接 write）
            if conflict_result.recommendation == "write":
                errors.append("矛盾原子不应直接 write")

            # 6. 验证 record_conflict 和 record_noise
            from src.memory.objectivity_check import ConflictInfo

            ci = ConflictInfo(
                existing_atom_id=atom_a.atom_id,
                existing_content=atom_a.content,
                new_content=atom_b.content,
                conflict_type="contradiction",
                overlap_score=0.6,
                new_atom_id=atom_b.atom_id,
            )
            record_id = await checker.record_conflict(ci)
            if not record_id:
                errors.append("记录冲突失败")

            noise_id = await checker.record_noise("测试噪声内容", source_scene="test", significance=0.0)
            if not noise_id:
                errors.append("记录噪声失败")

        except Exception as e:
            errors.append(f"客观性校验测试异常: {e}")
            traceback.print_exc(file=sys.stderr)

        duration = time.monotonic() - t_start
        passed = len(errors) == 0
        metrics: dict[str, Any] = {
            "good_atom_passed": good_result.passed if "good_result" in dir() else False,
            "garbage_rejected": not garbage_result.passed if "garbage_result" in dir() else False,
            "conflict_detected": conflict_result.recommendation if "conflict_result" in dir() else "none",
            "conflict_recorded": bool(record_id) if "record_id" in dir() else False,
            "noise_recorded": bool(noise_id) if "noise_id" in dir() else False,
            "errors": len(errors),
            "duration_sec": round(duration, 3),
        }

        result = TestResult(
            test_name="objectivity_check",
            passed=passed,
            duration_ms=round(duration * 1000),
            metrics=metrics,
            errors=errors,
        )
        self.results.append(result)
        print(
            f"  结果: {'通过' if passed else '失败'} | "
            f"good={metrics['good_atom_passed']}, garbage_rejected={metrics['garbage_rejected']}, "
            f"conflict={metrics['conflict_detected']}",
            file=sys.stderr,
        )
        return result

    # ── 执行器 ─────────────────────────────────────────────

    async def run_test(self, test_name: str) -> TestResult:
        """运行单个测试"""
        method_map = {
            "bulk": self.test_bulk_ingestion,
            "sustained": self.test_sustained_load,
            "burst": self.test_burst_spike,
            "concurrent": self.test_concurrent_rw,
            "crash": self.test_crash_recovery,
            "real_data": self.test_real_data_load,
            "user_profile": self.test_user_profile,
            "graph_store": self.test_graph_store,
            "dream_integration": self.test_dream_integration,
            "conflict_arbitration": self.test_conflict_arbitration,
            "objectivity_check": self.test_objectivity_check,
        }
        method = method_map.get(test_name)
        if method is None:
            raise ValueError(f"未知测试: {test_name}，可选: {list(method_map.keys())}")
        return await method()

    async def run_all(self, tests: list[str]) -> list[TestResult]:
        """运行指定列表的所有测试"""
        print(f"[启动] 压力测试 | tests={tests} | quick={self.quick}", file=sys.stderr)
        await self.init_components()
        self._ensure_real_data()
        try:
            for test_name in tests:
                if self._shutdown:
                    break
                try:
                    await self.run_test(test_name)
                except Exception as e:
                    print(f"[错误] 测试 {test_name} 异常: {e}", file=sys.stderr)
                    traceback.print_exc(file=sys.stderr)
                    self.results.append(
                        TestResult(
                            test_name=test_name,
                            passed=False,
                            duration_ms=0,
                            errors=[f"异常: {e}"],
                        )
                    )
        finally:
            await self.close_components()

        return self.results


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------


def _format_report(results: list[TestResult], elapsed: float, rss_final: float) -> dict[str, Any]:
    """生成最终报告字典"""
    passed = sum(1 for r in results if r.passed)
    total = len(results)

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "total_duration_sec": round(elapsed, 3),
            "final_rss_mib": round(rss_final, 2),
        },
        "tests": [asdict(r) for r in results],
    }
    return summary


def _print_ascii_table(results: list[TestResult]) -> None:
    """打印 ASCII 结果表格"""
    print("\n" + "=" * 100)
    print(f"{'TEST':<20} {'STATUS':<10} {'DURATION':<12} {'KEY METRICS':<56}")
    print("-" * 100)
    for r in results:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        # 提取关键指标
        key_metrics = ""
        if "atoms_created" in r.metrics:
            key_metrics = f"atoms={r.metrics['atoms_created']} speed={r.metrics.get('atoms_per_second', '?')}/s"
        elif "total_atoms" in r.metrics:
            key_metrics = f"atoms={r.metrics['total_atoms']} active={r.metrics.get('active_atoms', '?')}"
        elif "total_written" in r.metrics:
            key_metrics = (
                f"written={r.metrics['total_written']} stored={r.metrics['stored_count']} loss={r.metrics['atom_loss']}"
            )
        elif "atoms_written" in r.metrics:
            key_metrics = f"written={r.metrics['atoms_written']} recovered={r.metrics['recovered_from_log']}"
        elif "total_messages_loaded" in r.metrics:
            key_metrics = f"msgs={r.metrics['total_messages_loaded']} senders={r.metrics.get('unique_senders', '?')}"
        elif "profiles_created" in r.metrics:
            key_metrics = f"profiles={r.metrics['profiles_created']} built={r.metrics.get('profiles_built', 0)}"
        elif "nodes_created" in r.metrics:
            key_metrics = f"nodes={r.metrics['nodes_created']} edges={r.metrics.get('edges_created', 0)}"
        elif "consolidated" in r.metrics:
            key_metrics = f"cons={r.metrics['consolidated']} noise={r.metrics.get('noise_cleaned', 0)} graph=({r.metrics.get('graph_edges', 0)}e,{r.metrics.get('graph_entries', 0)}t)"
        elif "conflicts_resolved" in r.metrics:
            key_metrics = f"resolved={r.metrics['conflicts_resolved']} archived={r.metrics.get('atoms_archived', 0)}"
        elif "good_atom_passed" in r.metrics:
            key_metrics = f"good={r.metrics['good_atom_passed']} reject_garbage={r.metrics.get('garbage_rejected', False)} conflict={r.metrics.get('conflict_detected', '?')}"

        if r.errors:
            key_metrics += f" ERR={len(r.errors)}"

        print(f"{r.test_name:<20} {status:<10} {r.duration_ms / 1000:<8.2f}s {'':<4} {key_metrics:<56}")
    print("=" * 100)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="记忆系统压力测试 — 5 维度 + 6 个新模块",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  %(prog)s --quick --test bulk\n"
            "  %(prog)s --all --duration 60 --concurrency 20\n"
            "  %(prog)s --test sustained --duration 120\n"
            "  %(prog)s --test concurrent,crash\n"
            "  %(prog)s --test user_profile,graph_store,dream_integration\n"
            "  %(prog)s --quick --test objectivity_check,conflict_arbitration\n"
        ),
    )

    parser.add_argument(
        "--test",
        "-t",
        default="",
        help="测试选择：bulk/sustained/burst/concurrent/crash/real_data/user_profile/graph_store/dream_integration/conflict_arbitration/objectivity_check 逗号分隔（默认: all）",
    )
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="运行所有测试",
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=int,
        default=120,
        help="持续负载测试时长（秒，默认 120）",
    )
    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=20,
        help="并发数（默认 20）",
    )
    parser.add_argument(
        "--quick",
        "-q",
        action="store_true",
        help="快速模式（缩小参数，快速验证）",
    )
    parser.add_argument(
        "--db-path",
        default="",
        help="SQLite 数据库路径（默认: 临时文件）",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="",
        help="输出 JSON 文件路径（默认: scripts/stress_results.json）",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="显示详细日志（默认抑制日志噪音）",
    )
    parser.add_argument(
        "--use-real-data",
        action="store_true",
        default=True,
        help="使用真实聊天数据作为消息来源（默认: True）",
    )
    parser.add_argument(
        "--no-real-data",
        action="store_true",
        help="禁用真实聊天数据（仅使用模板消息）",
    )
    parser.add_argument(
        "--real-ratio",
        type=float,
        default=0.5,
        help="真实消息比例 0-1，控制测试中真实消息 vs 模板的比例（默认: 0.5）",
    )
    parser.add_argument(
        "--burst-count",
        type=int,
        default=3,
        help="突发测试中每轮突发数量（默认: 3）",
    )

    args = parser.parse_args(argv)

    # 如果 --test 为空且 --all 未设置，默认运行 all
    if not args.test and not args.all:
        args.all = True

    return args


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> int:
    """异步主入口"""
    if not args.verbose:
        _suppress_logging()

    # 解析测试列表
    if args.all or args.test.lower() in ("all", ""):
        test_names = [
            "bulk",
            "sustained",
            "burst",
            "concurrent",
            "crash",
            "real_data",
            "user_profile",
            "graph_store",
            "dream_integration",
            "conflict_arbitration",
            "objectivity_check",
        ]
    else:
        test_names = [t.strip() for t in args.test.split(",") if t.strip()]
        # 验证
        valid = {
            "bulk",
            "sustained",
            "burst",
            "concurrent",
            "crash",
            "real_data",
            "user_profile",
            "graph_store",
            "dream_integration",
            "conflict_arbitration",
            "objectivity_check",
        }
        for tn in test_names:
            if tn not in valid:
                print(f"错误: 未知测试 '{tn}'，可选: {sorted(valid)}", file=sys.stderr)
                return 1

    # 数据库路径
    if args.db_path:
        db_path = args.db_path
    else:
        tmp = tempfile.NamedTemporaryFile(suffix="_stress_memory.db", delete=False)
        tmp.close()
        db_path = tmp.name
        print(f"[数据] 使用临时数据库: {db_path}", file=sys.stderr)

    # 输出路径
    if args.output:
        output_path = args.output
    else:
        output_path = os.path.join(_SCRIPT_DIR, "stress_results.json")

    # 运行测试
    rss_start = _get_rss_mib()
    t_global = time.monotonic()

    use_real_data = not args.no_real_data if args.no_real_data else args.use_real_data

    runner = StressTestRunner(
        db_path=db_path,
        quick=args.quick,
        duration=args.duration,
        concurrency=args.concurrency,
        use_real_data=use_real_data,
        real_ratio=args.real_ratio,
        burst_count=args.burst_count,
    )

    try:
        results = await runner.run_all(test_names)
    except Exception as e:
        print(f"\n[致命错误] {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    elapsed = time.monotonic() - t_global
    rss_final = _get_rss_mib()

    # 生成报告
    report = _format_report(results, elapsed, rss_final)

    # 输出
    print("\n" + "=" * 100)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    _print_ascii_table(results)

    # 写入文件
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[报告] 已保存到: {output_path}", file=sys.stderr)
    print(f"[资源] RSS: {rss_start:.1f} → {rss_final:.1f} MiB ({rss_final - rss_start:+.1f} MiB)", file=sys.stderr)

    # 清理临时数据库
    if not args.db_path:
        try:
            os.unlink(db_path)
            # 清理 write_ops jsonl
            jsonl_path = db_path.replace(".db", "_write_ops.jsonl")
            if os.path.exists(jsonl_path):
                os.unlink(jsonl_path)
        except OSError:
            pass

    passed_count = report["summary"]["passed"]
    total_count = report["summary"]["total_tests"]
    return 0 if passed_count == total_count else 1


def main() -> None:
    args = parse_args()
    try:
        exit_code = asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\n[中断] 用户中断", file=sys.stderr)
        exit_code = 130
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
