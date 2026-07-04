#!/usr/bin/env python3
"""
适配器模拟器 — 模拟真实 QQ 适配器向 MaiBot 逐条发送消息，测试记忆系统端到端流程。

工作方式:
  1. 通过 HTTP POST 向 bot 内网 API (/message/inject) 逐条发送消息
  2. bot 按真实管线处理（Heartflow → 编码 → 记忆存储）
  3. 脚本监控: 注入延迟 / RSS / memory.db 行数增长 / LLM 调用明细 / 错误

消息来源:
  - 优先使用 tests/data/chat_exports/*.json 真实聊天记录
  - 回退到内置消息模板

模型调用记录:
  - 从 data/MaiBot.db 的 llm_usage 表读取本次运行期间新增记录
  - 默认输出到 tests/artifacts/adapter_sim_llm_summary_*.json
    和 tests/artifacts/adapter_sim_llm_calls_*.jsonl/.csv

用法:
    # bot 已在运行（使用真实聊天数据）
    python tests/adapter_sim.py

    # 快速验证
    python tests/adapter_sim.py --quick

    # 指定消息间隔（模拟真实聊天节奏）
    python tests/adapter_sim.py --message-interval 1.5

    # 自动启动 bot + 限制总条数（会启用 /message/inject 测试端点）
    python tests/adapter_sim.py --start-bot --batches 10 --message-interval 2.0
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import random
import re
import signal
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 项目根路径
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("MAIBOT_WORKER_PROCESS", "1")

# ---------------------------------------------------------------------------
# 消息清洗（与记忆系统测试脚本一致）
# ---------------------------------------------------------------------------

_REPLY_PREFIX_RE = re.compile(r"\[回复[^\]]*\]\s*")
_TAG_PATTERN = re.compile(r"\[(?:图片|视频|合并转发|文件|卡片消息|表情):[^\]]*\]")
_EMOJI_TAG = re.compile(r"\[\[?(?:图片|视频|表情|动画表情)\]?\]")
_SPECIAL_TEXTS = frozenset({
    "[动画表情]", "[语音]", "[分享]", "[红包]", "[音乐]", "[视频]",
    "[图片]", "[文件]", "[合并转发]", "[QQ红包]",
})


def _clean_reply_prefix(text: str) -> str:
    """清洗回复前缀，保留实际聊天内容。"""
    text = _REPLY_PREFIX_RE.sub("", text)
    if text.startswith("[回复"):
        idx = text.find("]")
        if idx != -1:
            text = text[idx + 1:].lstrip("\n").lstrip()
    return text.strip()


def _clean_message_text(raw_text: str) -> Optional[str]:
    """清洗单条消息文本，返回 None 表示应被过滤。"""
    if not raw_text:
        return None
    cleaned = _TAG_PATTERN.sub("", raw_text)
    cleaned = _EMOJI_TAG.sub("", cleaned)
    cleaned = cleaned.strip()
    if not cleaned or cleaned.strip("[] \t\n\r") == "":
        return None
    if cleaned in _SPECIAL_TEXTS:
        return None
    return _clean_reply_prefix(cleaned)

# ---------------------------------------------------------------------------
# 聊天导出数据加载
# ---------------------------------------------------------------------------

_CHAT_EXPORT_DIR = _PROJECT_ROOT / "tests" / "data" / "chat_exports"


def _extract_chat_info(chat_info: dict) -> tuple[str, str, str]:
    """从 chatInfo 提取群组信息。

    chat_histories_1: {"name": "2023级22班--all_users", "type": "group", ...}
    Returns (group_id, group_name, self_uid).
    """
    full_name = chat_info.get("name", "unknown")
    # "--" 之前的部分作为群名
    group_name = full_name.split("--")[0] if "--" in full_name else full_name
    # 用群名的 sha1 作为跨进程稳定的 group_id
    digest = hashlib.sha1(group_name.encode("utf-8", errors="ignore")).hexdigest()[:10]
    group_id = f"g_{digest}"
    return group_id, group_name, chat_info.get("selfUid", "")


def load_chat_messages(export_dir: str | Path = _CHAT_EXPORT_DIR) -> list[dict]:
    """加载聊天导出数据，按时间排序。

    返回列表，按 timestamp 升序排列，每项含:
      text, sender_name, sender_uid, timestamp, group_id, group_name
    过滤: 系统消息、撤回消息、bot 自己发的、纯媒体/表情消息。
    """
    export_dir = Path(export_dir)
    if not export_dir.is_dir():
        print(f"  [加载] 目录不存在: {export_dir}", file=sys.stderr)
        return []

    results: list[dict] = []
    for fpath in sorted(export_dir.glob("*.json")):
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as fp:
                data = json.load(fp)
        except Exception as e:
            print(f"  [警告] 解析 {fpath.name} 失败: {e}", file=sys.stderr)
            continue

        group_id, group_name, self_uid = _extract_chat_info(data.get("chatInfo", {}))
        file_count = 0
        for msg in data.get("messages", []):
            if msg.get("system") or msg.get("recalled"):
                continue
            content = msg.get("content", {})
            raw_text = content.get("text", "")
            if not raw_text:
                continue

            sender = msg.get("sender", {})
            sender_uid = sender.get("uid", "")
            if sender_uid == self_uid:
                continue

            cleaned = _clean_message_text(raw_text)
            if not cleaned:
                continue

            results.append({
                "text": cleaned,
                "name": sender.get("name", "unknown"),
                "uid": sender_uid,
                "timestamp": msg.get("timestamp", 0) / 1000.0,  # ms→s
                "group_id": group_id,
                "group_name": group_name,
            })
            file_count += 1

        print(f"  [加载] {fpath.name}: {file_count} 条有效消息", file=sys.stderr)

    # 按时间排序（所有文件混排，保证全局时间序）
    results.sort(key=lambda m: m["timestamp"])
    return results


# ---------------------------------------------------------------------------
# 内置回退消息（无真实数据时使用）
# ---------------------------------------------------------------------------

_FALLBACK_MESSAGES = [
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
    "今天考试我还没复习，要完蛋了",
    "有没有人拼单买奶茶？满减很划算",
    "你们说 AI 会不会取代程序员啊？",
    "我家的猫今天又拆家了，气死我了",
    "有会摄影的大佬吗？想入个相机",
    "最近在学 Rust，生命周期好难懂",
    "今天被面试官问了一道算法题，完全不会",
    "有没有好用的笔记软件推荐？",
    "这个项目 deadline 要到了，还在改 bug",
    "周末打算去逛逛博物馆，有没有一起的",
    "这个 API 文档写得太烂了，完全看不懂",
]

_FALLBACK_NAMES = ["似君(Homo sapiens)", "没有名字有没名字", "hsd221", "Alice", "Genima", "Elaina伊蕾娜"]

_GROUP_INFO = [
    ("g_100001", "2023级22班"),
    ("g_100002", "游戏开黑交流群"),
    ("g_100003", "学习资源共享群"),
]

# ---------------------------------------------------------------------------
# 资源监控
# ---------------------------------------------------------------------------


def _get_rss_mib() -> float:
    """获取当前进程 RSS（MiB）"""
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
# 消息池（由 load_chat_messages 填充，失败则使用内置回退）
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 消息队列（按时间序回放，非随机抽取）
# ---------------------------------------------------------------------------

_message_queue: list[dict] = []  # 按 ts 排序的消息列表
_message_cursor: int = 0         # 当前回放位置
_message_loop: bool = False       # 播完后是否从头循环


def init_message_pool(chat_dir: str | Path | None = None) -> int:
    """初始化消息队列，优先从聊天导出加载，失败则用内置模板。

    Returns: 有效消息数
    """
    global _message_queue, _message_cursor

    if chat_dir:
        loaded = load_chat_messages(chat_dir)
    else:
        loaded = load_chat_messages()

    if loaded:
        _message_queue = loaded
        print(f"  [消息队列] {len(_message_queue)} 条, "
              f"跨度 {_message_queue[0]['timestamp']:.0f} ~ {_message_queue[-1]['timestamp']:.0f} "
              f"({(loaded[-1]['timestamp']-loaded[0]['timestamp'])/86400:.0f} 天)",
              file=sys.stderr)
    else:
        print("  [消息队列] 无真实数据，使用内置模板", file=sys.stderr)
        _message_queue = [{"text": t, "name": random.choice(_FALLBACK_NAMES),
                           "uid": f"u_fallback_{i}", "timestamp": time.time() + i,
                           "group_id": "g_fallback", "group_name": "回退群"}
                          for i, t in enumerate(_FALLBACK_MESSAGES)]

    _message_cursor = 0
    return len(_message_queue)


def next_message() -> Optional[dict]:
    """取下一条消息，返回 None 表示队列耗尽。"""
    global _message_cursor
    if _message_cursor >= len(_message_queue):
        if _message_loop:
            _message_cursor = 0
        else:
            return None
    entry = _message_queue[_message_cursor]
    _message_cursor += 1
    return entry


# ---------------------------------------------------------------------------
# 消息构造（与适配器格式一致，保留原始群组信息，时间使用当前注入时刻）
# ---------------------------------------------------------------------------


def build_message(platform: str = "qq") -> Optional[dict[str, Any]]:
    """从消息队列取下一条消息构造适配器格式的 dict。

    时间戳使用 time.time()，与真实 QQ 适配器行为一致；
    若复用聊天导出里的旧时间戳，心流循环（按[last_read_time, now]轮询）会将其视为
    历史消息而跳过，导致 LLM/记忆管线不处理。

    Returns: 消息 dict，队列耗尽返回 None。
    """
    entry = next_message()
    if entry is None:
        return None

    return {
        "message_info": {
            "platform": platform,
            "message_id": str(uuid.uuid4()),
            "time": time.time(),
            "user_info": {
                "platform": platform,
                "user_id": entry["uid"],
                "user_nickname": entry["name"],
                "user_cardname": entry["name"],
            },
            "group_info": {
                "platform": platform,
                "group_id": entry["group_id"],
                "group_name": entry["group_name"],
            },
        },
        "message_segment": {"type": "text", "data": entry["text"]},
        "raw_message": None,
    }


# ---------------------------------------------------------------------------
# 数据库监控
# ---------------------------------------------------------------------------

_MEMORY_DB_PATH = _PROJECT_ROOT / "data" / "memory.db"
_MAIBOT_DB_PATH = _PROJECT_ROOT / "data" / "MaiBot.db"
_DEFAULT_ARTIFACT_DIR = _PROJECT_ROOT / "tests" / "artifacts"


def _read_env_file_value(key: str) -> Optional[str]:
    """从项目 .env 读取一个简单 KEY=VALUE 配置。"""
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        return None
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            current_key, value = line.split("=", 1)
            if current_key.strip() == key:
                return value.strip().strip("\"'")
    except OSError:
        return None
    return None


def _default_api_url() -> str:
    """根据当前项目配置推导 bot 内网 API 地址。"""
    explicit_url = os.environ.get("MAIBOT_API_URL")
    if explicit_url:
        return explicit_url.rstrip("/")

    host = os.environ.get("HOST") or _read_env_file_value("HOST") or "127.0.0.1"
    port = os.environ.get("PORT") or _read_env_file_value("PORT") or "8080"
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def _open_sqlite(path: Path) -> sqlite3.Connection:
    """打开 SQLite 连接并返回 dict row。"""
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """检查 SQLite 表是否存在。"""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_llm_usage_cursor() -> dict[str, Any]:
    """获取 llm_usage 当前游标，用于之后只导出本次运行期间新增记录。"""
    result: dict[str, Any] = {
        "db_exists": _MAIBOT_DB_PATH.exists(),
        "table_exists": False,
        "max_id": 0,
        "record_count": 0,
    }
    if not result["db_exists"]:
        return result

    try:
        conn = _open_sqlite(_MAIBOT_DB_PATH)
        if not _table_exists(conn, "llm_usage"):
            conn.close()
            return result

        result["table_exists"] = True
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS max_id, COUNT(*) AS count FROM llm_usage").fetchone()
        result["max_id"] = int(row["max_id"] or 0)
        result["record_count"] = int(row["count"] or 0)
        conn.close()
    except Exception as e:
        result["error"] = str(e)
    return result


def load_llm_usage_since(start_id: int) -> list[dict[str, Any]]:
    """读取 start_id 之后的 llm_usage 明细。"""
    if not _MAIBOT_DB_PATH.exists():
        return []

    try:
        conn = _open_sqlite(_MAIBOT_DB_PATH)
        if not _table_exists(conn, "llm_usage"):
            conn.close()
            return []

        rows = conn.execute(
            """
            SELECT
                id,
                model_name,
                model_assign_name,
                model_api_provider,
                user_id,
                request_type,
                endpoint,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                cost,
                time_cost,
                status,
                timestamp
            FROM llm_usage
            WHERE id > ?
            ORDER BY id ASC
            """,
            (start_id,),
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"  [LLM] 读取 llm_usage 失败: {e}", file=sys.stderr)
        return []

    return [dict(row) for row in rows]


def _blank_llm_bucket() -> dict[str, Any]:
    """创建模型调用聚合桶。"""
    return {
        "requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost": 0.0,
        "time_cost_sum": 0.0,
        "time_cost_count": 0,
        "avg_time_cost": 0.0,
    }


def _add_llm_record(bucket: dict[str, Any], row: dict[str, Any]) -> None:
    """把一条 llm_usage 记录累加进聚合桶。"""
    prompt_tokens = int(row.get("prompt_tokens") or 0)
    completion_tokens = int(row.get("completion_tokens") or 0)
    total_tokens = int(row.get("total_tokens") or (prompt_tokens + completion_tokens))
    cost = float(row.get("cost") or 0.0)
    time_cost = row.get("time_cost")

    bucket["requests"] += 1
    bucket["prompt_tokens"] += prompt_tokens
    bucket["completion_tokens"] += completion_tokens
    bucket["total_tokens"] += total_tokens
    bucket["cost"] += cost
    if time_cost is not None:
        bucket["time_cost_sum"] += float(time_cost or 0.0)
        bucket["time_cost_count"] += 1


def _finalize_llm_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    """补全平均耗时并规整成本精度。"""
    finalized = dict(bucket)
    if finalized["time_cost_count"]:
        finalized["avg_time_cost"] = round(finalized["time_cost_sum"] / finalized["time_cost_count"], 3)
    finalized["cost"] = round(finalized["cost"], 6)
    finalized["time_cost_sum"] = round(finalized["time_cost_sum"], 3)
    return finalized


def summarize_llm_usage(rows: list[dict[str, Any]], start_id: int, start_time: float, end_time: float) -> dict[str, Any]:
    """生成模型调用明细的聚合摘要。"""
    totals = _blank_llm_bucket()
    by_request_type: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_endpoint: dict[str, dict[str, Any]] = {}
    by_provider: dict[str, dict[str, Any]] = {}

    for row in rows:
        _add_llm_record(totals, row)

        request_type = row.get("request_type") or "unknown"
        model = row.get("model_assign_name") or row.get("model_name") or "unknown"
        provider = row.get("model_api_provider") or "unknown"
        endpoint = row.get("endpoint") or "unknown"

        for group, key in (
            (by_request_type, request_type),
            (by_model, model),
            (by_provider, provider),
            (by_endpoint, endpoint),
        ):
            group.setdefault(key, _blank_llm_bucket())
            _add_llm_record(group[key], row)

    def _finalize_group(group: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {
            key: _finalize_llm_bucket(value)
            for key, value in sorted(
                group.items(),
                key=lambda item: (item[1]["requests"], item[1]["total_tokens"], item[0]),
                reverse=True,
            )
        }

    end_id = max((int(row.get("id") or 0) for row in rows), default=start_id)
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "database": str(_MAIBOT_DB_PATH),
        "cursor": {
            "start_id": start_id,
            "end_id": end_id,
        },
        "period": {
            "start_unix": round(start_time, 3),
            "end_unix": round(end_time, 3),
            "duration_s": round(end_time - start_time, 3),
        },
        "totals": _finalize_llm_bucket(totals),
        "by_request_type": _finalize_group(by_request_type),
        "by_model": _finalize_group(by_model),
        "by_provider": _finalize_group(by_provider),
        "by_endpoint": _finalize_group(by_endpoint),
    }


def write_llm_usage_report(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, str]:
    """把模型调用明细和摘要写入 tests/artifacts。"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d_%H%M%S")

    summary_path = output_path / f"adapter_sim_llm_summary_{run_id}.json"
    jsonl_path = output_path / f"adapter_sim_llm_calls_{run_id}.jsonl"
    csv_path = output_path / f"adapter_sim_llm_calls_{run_id}.csv"

    with open(summary_path, "w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False, indent=2)

    with open(jsonl_path, "w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    fieldnames = [
        "id",
        "timestamp",
        "request_type",
        "endpoint",
        "model_assign_name",
        "model_name",
        "model_api_provider",
        "user_id",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost",
        "time_cost",
        "status",
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    return {
        "summary": str(summary_path),
        "jsonl": str(jsonl_path),
        "csv": str(csv_path),
    }


def check_memory_db() -> dict[str, Any]:
    """检查 memory.db 状态，返回行数统计。"""
    result: dict[str, Any] = {"db_exists": _MEMORY_DB_PATH.exists()}
    if not result["db_exists"]:
        return result

    result["db_size_mb"] = round(_MEMORY_DB_PATH.stat().st_size / (1024 * 1024), 2)

    try:
        conn = sqlite3.connect(str(_MEMORY_DB_PATH), timeout=2)
        conn.execute("PRAGMA busy_timeout=1000")
        cursor = conn.execute("SELECT COUNT(*) FROM memory_atoms")
        result["atom_count"] = cursor.fetchone()[0]
        cursor = conn.execute("SELECT COUNT(*) FROM raw_message_archive")
        result["archive_count"] = cursor.fetchone()[0]
        cursor = conn.execute("SELECT COUNT(*) FROM noise_pool")
        result["noise_count"] = cursor.fetchone()[0]
        cursor = conn.execute("SELECT COUNT(*) FROM insight_pool")
        result["insight_count"] = cursor.fetchone()[0]
        cursor = conn.execute("SELECT COUNT(*) FROM dream_runs")
        result["dream_count"] = cursor.fetchone()[0]
        conn.close()
    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# 主模拟器
# ---------------------------------------------------------------------------


class AdapterSimulator:
    """适配器模拟器 — 向 bot 发送消息并监控记忆系统状态。"""

    def __init__(
        self,
        api_url: str | None = None,
        batch_size: int = 30,
        batches: int = 0,
        message_interval: float = 2.0,
        enable_db_monitor: bool = True,
        enable_llm_monitor: bool = True,
        llm_report_dir: str | Path = _DEFAULT_ARTIFACT_DIR,
        settle_seconds: float = 10.0,
        chat_dir: str | Path | None = None,
        start_bot: bool = False,
    ):
        self.api_url = (api_url or _default_api_url()).rstrip("/")
        self.inject_url = f"{self.api_url}/message/inject"
        self.batch_size = batch_size
        self.batches = batches
        self.message_interval = message_interval
        self.enable_db_monitor = enable_db_monitor
        self.enable_llm_monitor = enable_llm_monitor
        self.llm_report_dir = llm_report_dir
        self.settle_seconds = settle_seconds
        self.chat_dir = chat_dir
        self.start_bot = start_bot

        # 初始化消息队列
        init_message_pool(chat_dir)

        # Stats
        self.total_sent = 0
        self.total_ok = 0
        self.total_fail = 0
        self.latencies: list[float] = []
        self.errors: list[str] = []
        self.start_time = 0.0
        self.db_snapshots: list[dict[str, Any]] = []
        self.llm_start_cursor: dict[str, Any] = {}
        self.llm_rows: list[dict[str, Any]] = []
        self.llm_summary: dict[str, Any] = {}
        self.llm_report_paths: dict[str, str] = {}

        # Bot process
        self._bot_proc: asyncio.subprocess.Process | None = None
        self._bot_stderr_task: asyncio.Task | None = None
        self._shutdown = False

    # ── 信号处理 ──────────────────────────────────────────────────

    def _signal_handler(self, signum: int, _frame: Any) -> None:
        if self._shutdown:
            return
        print(f"\n[信号] 收到信号 {signum}，正在停止...")
        self._shutdown = True
        if self._bot_proc and self._bot_proc.returncode is None:
            self._bot_proc.terminate()

    # ── Bot 生命周期 ──────────────────────────────────────────────

    @staticmethod
    def _kill_existing_bots() -> None:
        """杀掉所有已存在的 bot.py 进程。"""
        import subprocess
        try:
            result = subprocess.run(
                ["pgrep", "-f", "python.*bot\\.py"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = [int(p) for p in result.stdout.strip().split()]
                print(f"  [bot] 发现旧进程 PIDs={pids}，正在杀死...")
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                # 等进程彻底退出
                time.sleep(1)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    async def _start_bot(self) -> bool:
        """启动 bot.py 子进程。返回 True 表示成功。"""
        # 先杀旧进程
        self._kill_existing_bots()
        print("[bot] 启动: MAIBOT_WORKER_PROCESS=1 MAIBOT_ENABLE_INJECT_ENDPOINT=1 python bot.py")

        env = os.environ.copy()
        env["MAIBOT_WORKER_PROCESS"] = "1"
        env["MAIBOT_ENABLE_INJECT_ENDPOINT"] = "1"

        self._bot_proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(_PROJECT_ROOT / "bot.py"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(_PROJECT_ROOT),
        )

        ready = asyncio.Event()

        async def _read_stderr():
            assert self._bot_proc and self._bot_proc.stderr
            while True:
                line = await self._bot_proc.stderr.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    print(f"  [bot] {decoded[:200]}")
                if "已成功唤醒" in decoded:
                    ready.set()

        self._bot_stderr_task = asyncio.create_task(_read_stderr())

        try:
            await asyncio.wait_for(ready.wait(), timeout=120)
            print("[bot] ✅ 已就绪")
            await asyncio.sleep(3)  # 等 API 服务器启动
            return True
        except asyncio.TimeoutError:
            print("[bot] ❌ 启动超时")
            if self._bot_proc.returncode is not None:
                print(f"  bot 进程已退出 (code={self._bot_proc.returncode})")
            return False

    async def _stop_bot(self) -> None:
        """停止 bot 子进程。"""
        if self._bot_proc and self._bot_proc.returncode is None:
            self._bot_proc.terminate()
            try:
                await asyncio.wait_for(self._bot_proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                self._bot_proc.kill()
                await self._bot_proc.wait()
        if self._bot_stderr_task and not self._bot_stderr_task.done():
            self._bot_stderr_task.cancel()
            try:
                await self._bot_stderr_task
            except (asyncio.CancelledError, Exception):
                pass

    # ── API 探针 ─────────────────────────────────────────────────

    async def _probe_api(self) -> bool:
        """检查 bot 内网 API 是否可用。"""
        try:
            loop = asyncio.get_running_loop()

            def _probe():
                import urllib.request

                req = urllib.request.Request(
                    self.inject_url,
                    data=json.dumps({"_probe": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=2):
                    pass

            await loop.run_in_executor(None, _probe)
            return True
        except Exception:
            return False

    async def _wait_for_api(self, timeout: float = 60) -> bool:
        """轮询 API 直到就绪。"""
        deadline = time.time() + timeout
        while time.time() < deadline and not self._shutdown:
            if await self._probe_api():
                return True
            await asyncio.sleep(1)
        return False

    # ── HTTP 注入 ─────────────────────────────────────────────────

    async def _send_one(self, msg: dict[str, Any]) -> float | None:
        """发送一条消息，返回延迟 ms 或 None（失败）。"""
        t0 = time.monotonic()
        try:
            data = json.dumps(msg).encode("utf-8")
            loop = asyncio.get_running_loop()

            def _post():
                import urllib.request

                req = urllib.request.Request(
                    self.inject_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.read()

            await loop.run_in_executor(None, _post)
            return (time.monotonic() - t0) * 1000
        except Exception as e:
            self.errors.append(str(e)[:200])
            return None

    # ── DB 监控 ───────────────────────────────────────────────────

    async def _db_snapshot(self, tag: str = "") -> dict[str, Any]:
        """采集一次 DB 快照。"""
        info = check_memory_db()
        info["tag"] = tag
        info["elapsed_s"] = round(time.time() - self.start_time, 1)
        info["rss_mib"] = round(_get_rss_mib(), 2)
        info["total_sent"] = self.total_sent
        info["total_ok"] = self.total_ok
        self.db_snapshots.append(info)
        return info

    # ── 实时摘要 ─────────────────────────────────────────────────

    async def _report(self, phase: str, force: bool = False) -> None:
        """打印实时摘要。"""
        if not force and self.total_sent % 50 != 0:
            return

        elapsed = time.time() - self.start_time
        ok = self.total_ok
        fail = self.total_fail
        rate = ok / (elapsed / 60) if elapsed > 0 else 0
        lat_str = ""
        if self.latencies:
            p50 = sorted(self.latencies)[len(self.latencies) // 2]
            p99 = sorted(self.latencies)[int(len(self.latencies) * 0.99)]
            lat_str = f" | 延迟 P50={p50:.1f}ms P99={p99:.1f}ms"

        db = await self._db_snapshot(tag=phase)
        atoms = db.get("atom_count", "?")
        archive = db.get("archive_count", "?")
        rss = db.get("rss_mib", 0)

        print(
            f"[{phase}] {self.total_sent}条 "
            f"ok={ok} fail={fail} "
            f"{rate:.1f}条/min"
            f"{lat_str} | "
            f"DB: atoms={atoms} archive={archive} "
            f"RSS={rss:.0f}MiB"
        )

    # ── 主循环 ───────────────────────────────────────────────────

    async def run(self, db_interval: float = 30) -> int:
        """运行模拟器 — 按真实适配器节奏逐条注入。

        Args:
            db_interval: DB 快照间隔（秒）

        Returns: 退出码
        """
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self.start_time = time.time()

        # ── 启动 bot ─────────────────────────────────────────
        if self.start_bot:
            ok = await self._start_bot()
            if not ok:
                return 1
            if not await self._wait_for_api(timeout=30):
                print("  ❌ bot API 未就绪")
                return 1

        # ── API 可用性检查 ────────────────────────────────────
        print(f"\n[API] 检查: {self.inject_url}")
        if not await self._probe_api():
            print("  ❌ bot API 不可用，请先启动 bot 或使用 --start-bot")
            print("     手动启动 bot 时需设置 MAIBOT_ENABLE_INJECT_ENDPOINT=1")
            return 1
        print("  ✅ bot API 可用")

        # ── LLM 调用游标 ──────────────────────────────────────
        if self.enable_llm_monitor:
            self.llm_start_cursor = get_llm_usage_cursor()
            print(
                "\n[LLM] 初始游标: "
                f"db={self.llm_start_cursor.get('db_exists')} "
                f"table={self.llm_start_cursor.get('table_exists')} "
                f"max_id={self.llm_start_cursor.get('max_id', 0)} "
                f"records={self.llm_start_cursor.get('record_count', 0)}"
            )

        # ── 首次 DB 快照 ──────────────────────────────────────
        if self.enable_db_monitor:
            before = await self._db_snapshot("initial")
            print(f"\n[DB] 初始: atoms={before.get('atom_count', '?')} "
                  f"archive={before.get('archive_count', '?')} "
                  f"size={before.get('db_size_mb', '?')}MB")

        rss_baseline = _get_rss_mib()
        msg_num = 0
        batch_num = 0
        max_total = self.batches * self.batch_size if self.batches > 0 else None
        bucket_results: list[float | None] = []
        bucket_t0 = time.monotonic()

        print(f"\n[开始] 模拟真实适配器: 每条间隔 {self.message_interval}s, "
              f"每 {self.batch_size} 条报告一次")

        while not self._shutdown:
            if max_total is not None and msg_num >= max_total:
                print("\n  ✅ 已达到指定总消息数")
                break

            msg = build_message()
            if msg is None:
                print("\n  ✅ 消息队列已全部播完")
                break

            msg_num += 1
            result = await self._send_one(msg)
            bucket_results.append(result)
            if result is not None:
                self.total_ok += 1
                self.latencies.append(result)
            else:
                self.total_fail += 1
            self.total_sent += 1

            if msg_num % self.batch_size == 0:
                batch_num += 1
                bucket_time = time.monotonic() - bucket_t0
                ok = sum(1 for r in bucket_results if r is not None)
                fail = len(bucket_results) - ok
                lat_ok = [r for r in bucket_results if r is not None]
                lat_str = ""
                if lat_ok:
                    p50 = sorted(lat_ok)[len(lat_ok) // 2]
                    lat_str = f" P50={p50:.1f}ms"

                if self.enable_db_monitor:
                    db = await self._db_snapshot(f"batch{batch_num}")
                    atoms = db.get("atom_count", "?")
                    archive = db.get("archive_count", "?")
                else:
                    atoms, archive = "?", "?"

                print(f"  [第{batch_num}批] {len(bucket_results)}条 ok={ok} fail={fail} "
                      f"{bucket_time:.1f}s{lat_str} | "
                      f"atoms={atoms} archive={archive}")
                bucket_results = []
                bucket_t0 = time.monotonic()

            await asyncio.sleep(self.message_interval)

        # ── 收尾 ──────────────────────────────────────────────
        print(f"\n[收尾] 等待 bot 处理剩余消息（{self.settle_seconds:g}s）...")
        if self.settle_seconds > 0:
            await asyncio.sleep(self.settle_seconds)

        final_db = await self._db_snapshot("final") if self.enable_db_monitor else {}
        if self.enable_llm_monitor:
            self._collect_llm_usage()

        self._print_final_report(final_db, rss_baseline)

        # 清理 bot 进程
        if self._bot_proc:
            print("\n[bot] 正在停止...")
            await self._stop_bot()

        return 0

    # ── 最终报告 ────────────────────────────────────────────────

    def _collect_llm_usage(self) -> None:
        """收集并落盘本次运行期间新增的 LLMUsage 记录。"""
        start_id = int(self.llm_start_cursor.get("max_id") or 0)
        self.llm_rows = load_llm_usage_since(start_id)
        self.llm_summary = summarize_llm_usage(self.llm_rows, start_id, self.start_time, time.time())
        self.llm_report_paths = write_llm_usage_report(
            self.llm_rows,
            self.llm_summary,
            self.llm_report_dir,
        )

    def _print_final_report(self, final_db: dict[str, Any], rss_baseline: float) -> None:
        """打印最终报告。"""
        elapsed = time.time() - self.start_time
        ok = self.total_ok
        fail = self.total_fail

        print("\n" + "=" * 72)
        print("  📊 适配器模拟 — 最终报告")
        print("=" * 72)

        # 注入统计
        print("\n  [注入统计]")
        print(f"    总发送:    {self.total_sent} 条")
        print(f"    成功:      {ok} 条")
        print(f"    失败:      {fail} 条")
        print(f"    成功率:    {(ok/max(self.total_sent,1)*100):.1f}%")
        print(f"    耗时:      {elapsed:.0f}s ({elapsed/60:.1f}min)")
        print(f"    平均速率:  {ok/max(elapsed/60,0.001):.1f} 条/min")

        if self.latencies:
            sorted_lat = sorted(self.latencies)
            print("\n  [注入延迟]")
            print(f"    P50:       {sorted_lat[len(sorted_lat)//2]:.1f}ms")
            print(f"    P95:       {sorted_lat[int(len(sorted_lat)*0.95)]:.1f}ms")
            print(f"    P99:       {sorted_lat[int(len(sorted_lat)*0.99)]:.1f}ms")
            print(f"    MAX:       {max(sorted_lat):.1f}ms")
            print(f"    AVG:       {sum(sorted_lat)/len(sorted_lat):.1f}ms")

        # DB 状态
        if self.enable_db_monitor and self.db_snapshots:
            first = self.db_snapshots[0]
            last = self.db_snapshots[-1]

            print("\n  [memory.db 状态]")
            print(f"    文件大小:  {final_db.get('db_size_mb', 0):.2f} MB")
            print(f"    原子:      {first.get('atom_count', 0)} → {last.get('atom_count', 0)} "
                  f"(+{last.get('atom_count', 0) - first.get('atom_count', 0)})")
            print(f"    归档:      {first.get('archive_count', 0)} → {last.get('archive_count', 0)} "
                  f"(+{last.get('archive_count', 0) - first.get('archive_count', 0)})")
            print(f"    噪声池:    {last.get('noise_count', 0)}")
            print(f"    梦境:      {last.get('dream_count', 0)}")
            print(f"    洞见:      {last.get('insight_count', 0)}")

        # 资源
        rss_final = _get_rss_mib()
        rss_growth = rss_final - rss_baseline
        print("\n  [资源]")
        print(f"    RSS:       {rss_baseline:.1f} → {rss_final:.1f} MiB ({rss_growth:+.1f} MiB)")

        if self.errors:
            print(f"\n  [错误] ({len(self.errors)} 次)")
            for err in self.errors[:10]:
                print(f"    ❌ {err}")

        if self.enable_llm_monitor:
            totals = self.llm_summary.get("totals", {})
            print("\n  [模型调用]")
            print(f"    请求数:    {totals.get('requests', 0)}")
            print(f"    Tokens:    {totals.get('total_tokens', 0)} "
                  f"(in={totals.get('prompt_tokens', 0)}, out={totals.get('completion_tokens', 0)})")
            print(f"    费用:      {totals.get('cost', 0.0):.6f}")
            print(f"    平均耗时:  {totals.get('avg_time_cost', 0.0):.3f}s")

            by_request_type = self.llm_summary.get("by_request_type", {})
            if by_request_type:
                print("    按类型:")
                for name, item in list(by_request_type.items())[:10]:
                    print(
                        f"      - {name}: {item.get('requests', 0)}次, "
                        f"{item.get('total_tokens', 0)} tokens, "
                        f"{item.get('cost', 0.0):.6f}"
                    )

            by_model = self.llm_summary.get("by_model", {})
            if by_model:
                print("    按模型:")
                for name, item in list(by_model.items())[:10]:
                    print(
                        f"      - {name}: {item.get('requests', 0)}次, "
                        f"{item.get('total_tokens', 0)} tokens, "
                        f"{item.get('avg_time_cost', 0.0):.3f}s avg"
                    )

            if self.llm_report_paths:
                print("    明细:")
                print(f"      summary: {self.llm_report_paths.get('summary')}")
                print(f"      jsonl:   {self.llm_report_paths.get('jsonl')}")
                print(f"      csv:     {self.llm_report_paths.get('csv')}")

        memory_growth = last.get("atom_count", 0) - first.get("atom_count", 0) if self.db_snapshots else 0
        if memory_growth > 0:
            print(f"\n  ✅ 结论: 记忆系统正常工作 — 记录了 {memory_growth} 条原子")
        elif self.total_sent > 0:
            print("\n  ⚠️  结论: 未检测到记忆原子增长（可能编码管线未触发）")
        else:
            print("\n  ⚠️  结论: 未发送任何消息")

        print("=" * 72)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="适配器模拟器 — 从聊天导出按时间序回放消息",
    )
    parser.add_argument("--api-url", default=_default_api_url(),
                        help="bot 内网 API 地址 (默认读取 MAIBOT_API_URL 或 .env 的 HOST/PORT)")
    parser.add_argument("--batch-size", type=int, default=30,
                        help="报告/统计桶大小 (默认 30)")
    parser.add_argument("--batches", type=int, default=0,
                        help="发送总批次数 (0=播完整个消息队列为止)")
    parser.add_argument("--message-interval", type=float, default=2.0,
                        help="相邻两条消息的发送间隔 (秒，默认 2.0，模拟真实适配器)")
    parser.add_argument("--db-interval", type=float, default=30.0,
                        help="DB 快照间隔 (秒，默认 30)")
    parser.add_argument("--start-bot", action="store_true",
                        help="自动启动 bot.py 子进程")
    parser.add_argument("--quick", "-q", action="store_true",
                        help="快速模式: batch-size=30 batches=3 message-interval=0.5")
    parser.add_argument("--no-db-monitor", action="store_true",
                        help="禁用 DB 监控")
    parser.add_argument("--no-llm-monitor", action="store_true",
                        help="禁用模型调用记录导出")
    parser.add_argument("--llm-report-dir", type=str, default=str(_DEFAULT_ARTIFACT_DIR),
                        help="模型调用报告输出目录 (默认: tests/artifacts)")
    parser.add_argument("--settle-seconds", type=float, default=10.0,
                        help="停止注入后等待 bot 处理剩余消息的秒数 (默认 10)")
    parser.add_argument("--chat-dir", type=str, default=None,
                        help="聊天导出目录 (默认: tests/data/chat_exports)")
    return parser.parse_args(argv)


async def main() -> int:
    args = parse_args(argv=None)

    if args.quick:
        args.batch_size = 30
        args.batches = 3
        args.message_interval = 0.5

    sim = AdapterSimulator(
        api_url=args.api_url,
        batch_size=args.batch_size,
        batches=args.batches,
        message_interval=args.message_interval,
        enable_db_monitor=not args.no_db_monitor,
        enable_llm_monitor=not args.no_llm_monitor,
        llm_report_dir=args.llm_report_dir,
        settle_seconds=args.settle_seconds,
        chat_dir=args.chat_dir,
        start_bot=args.start_bot,
    )

    return await sim.run(db_interval=args.db_interval)


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n[中断] 用户中断")
        sys.exit(130)
