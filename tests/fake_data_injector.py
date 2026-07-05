#!/usr/bin/env python3
"""Fake data injector for memory system testing.

Injects synthetic chat records spanning various time periods into the memory
database (data/memory.db), then optionally triggers memory consolidation and
dream generation to verify the system handles historical data correctly.

Usage:
    # Dry-run (inspect what would be injected)
    python tests/fake_data_injector.py --dry-run

    # Basic injection (raw_message_archive only)
    python tests/fake_data_injector.py

    # Full injection + encoding pipeline trigger
    python tests/fake_data_injector.py --trigger-encoding

    # Custom paths
    python tests/fake_data_injector.py --db-path /tmp/test.db --export-dir tests/data/chat_exports
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Project root bootstrap
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "memory.db"
_DEFAULT_EXPORT_DIR = _PROJECT_ROOT / "tests" / "data" / "chat_exports"

# Fictional users (15 users with realistic Chinese names)
FICTIONAL_USERS: list[tuple[str, str]] = [
    ("student_001", "张明"),
    ("student_002", "李华"),
    ("student_003", "王芳"),
    ("student_004", "赵磊"),
    ("student_005", "陈静"),
    ("student_006", "刘洋"),
    ("student_007", "黄丽"),
    ("student_008", "周杰"),
    ("student_009", "吴敏"),
    ("student_010", "孙涛"),
    ("student_011", "林小红"),
    ("student_012", "郑伟"),
    ("student_013", "许文强"),
    ("student_014", "冯刚"),
    ("student_015", "朱丽"),
]

# Fictional groups
FICTIONAL_GROUPS: list[tuple[str, str, str]] = [
    ("group_001", "2023级计算机科学与技术班", "class"),
    ("group_002", "游戏开黑交流群", "game"),
    ("group_003", "学习资源共享群", "study"),
]

# Special message texts to filter out
_SPECIAL_TEXTS = frozenset(
    {
        "[动画表情]",
        "[语音]",
        "[分享]",
        "[红包]",
        "[音乐]",
        "[视频]",
        "[图片]",
        "[文件]",
        "[合并转发]",
        "[QQ红包]",
    }
)
_TAG_PATTERN = re.compile(r"\[(?:图片|视频|合并转发|文件|卡片消息|表情):[^\]]*\]")
_EMOJI_TAG = re.compile(r"\[\[?(?:图片|视频|表情|动画表情)\]?\]")
_REPLY_PREFIX_RE = re.compile(r"\[回复[^\]]*\]\s*")

# Timeline definitions: (label, days_ago, count, spread_hours)
# Each entry says: inject N messages spread over M hours, starting X days ago.
TIMELINE_SLOTS: list[tuple[str, int, int, int]] = [
    ("1 day ago", 1, 50, 6),  # 50 msgs over 6 hours, 1 day ago
    ("3 days ago", 3, 100, 12),  # 100 msgs over 12 hours, 3 days ago
    ("1 week ago", 7, 200, 48),  # 200 msgs over 2 days, 1 week ago
    ("1 month ago", 30, 300, 120),  # 300 msgs over 5 days, 1 month ago
    ("1 quarter ago", 90, 500, 336),  # 500 msgs over 14 days, 1 quarter ago
]

# Total: 1150 messages


def _clean_reply_prefix(text: str) -> str:
    """Strip reply prefix like '[回复 xxx: original]'."""
    text = _REPLY_PREFIX_RE.sub("", text)
    if text.startswith("[回复"):
        idx = text.find("]")
        if idx != -1:
            text = text[idx + 1 :].lstrip("\n").lstrip()
    return text.strip()


def _clean_message_text(raw_text: str) -> Optional[str]:
    """Clean message text; return None if the message should be filtered."""
    if not raw_text:
        return None
    # Remove embedded media/card tags
    cleaned = _TAG_PATTERN.sub("", raw_text)
    cleaned = _EMOJI_TAG.sub("", cleaned)
    cleaned = cleaned.strip()
    if not cleaned or cleaned.strip("[] \t\n\r") == "":
        return None
    if cleaned in _SPECIAL_TEXTS:
        return None
    return _clean_reply_prefix(cleaned)


def load_chat_messages(export_dir: str) -> list[tuple[str, str, int]]:
    """Parse chat export JSON files and extract (text, sender_name, timestamp_ms)."""
    export_path = Path(export_dir)
    if not export_path.is_dir():
        print(f"[警告] 导出目录不存在: {export_dir}", file=sys.stderr)
        return []

    results: list[tuple[str, str, int]] = []
    for fname in sorted(export_path.iterdir()):
        if not fname.suffix == ".json":
            continue
        try:
            with open(fname, "r", encoding="utf-8", errors="replace") as fp:
                data = json.load(fp)
        except Exception as e:
            print(f"[警告] 无法解析 {fname}: {e}", file=sys.stderr)
            continue

        for msg in data.get("messages", []):
            text = msg.get("content", {}).get("text", "")
            if not text:
                continue
            cleaned = _clean_message_text(text)
            if not cleaned:
                continue

            ts = msg.get("timestamp", 0)
            sender = msg.get("sender", {}).get("name", "unknown")
            results.append((cleaned, sender, ts))

    return results


def compute_stream_id(platform: str, group_id: str) -> str:
    """Compute stream_id for a group chat."""
    return hashlib.md5(f"{platform}{group_id}".encode()).hexdigest()


def compute_private_stream_id(platform: str, user_id: str) -> str:
    """Compute stream_id for a private chat."""
    return hashlib.md5(f"{platform}{user_id}private".encode()).hexdigest()


def generate_timeline_messages(
    messages_pool: list[tuple[str, str, int]],
) -> list[dict[str, Any]]:
    """Generate synthetic messages across the defined timeline.

    Each message dict contains: stream_id, message_id, user_id, content,
    timestamp (Unix seconds), chat_type, group_id.
    """
    now = datetime.now(timezone.utc)
    result: list[dict[str, Any]] = []

    user_ids = [uid for uid, _ in FICTIONAL_USERS]
    group_info = {gid: (gname, gtopic) for gid, gname, gtopic in FICTIONAL_GROUPS}

    # Pre-classify pool messages by rough topic (keyword matching)
    game_keywords = {"游戏", "玩", "开黑", "上分", "打", "段位", "皮肤", "副本", "boss"}
    study_keywords = {"学习", "作业", "考试", "复习", "老师", "课程", "论文", "实验", "图书馆"}

    def _classify_content(text: str) -> str:
        for kw in game_keywords:
            if kw in text:
                return "game"
        for kw in study_keywords:
            if kw in text:
                return "study"
        return "class"

    # Build a categorized pool
    categorized: dict[str, list[tuple[str, str, int]]] = {"class": [], "game": [], "study": []}
    for text, sender, ts in messages_pool:
        topic = _classify_content(text)
        categorized[topic].append((text, sender, ts))

    # Ensure each category has enough messages; fall back to class pool
    for cat in categorized:
        if not categorized[cat]:
            categorized[cat] = categorized["class"]

    message_counter = [0]  # use list for closure mutability

    for _slot_label, days_ago, count, spread_hours in TIMELINE_SLOTS:
        slot_start = now - timedelta(days=days_ago, hours=spread_hours / 2)
        pool_for_slot = categorized[random.choice(list(categorized.keys()))]

        for i in range(count):
            message_counter[0] += 1
            fake_msg_id = f"fake_{message_counter[0]:06d}"

            # Pick a random user
            user_id = random.choice(user_ids)
            user_name = next(n for uid, n in FICTIONAL_USERS if uid == user_id)

            # Pick a group
            if days_ago <= 3:
                # Recent messages: more likely in active groups (game + class)
                gid = random.choice(["group_001", "group_002"])
            else:
                gid = random.choice(list(group_info.keys()))

            # Pick content from the pool (with possible depletion recovery)
            if not pool_for_slot:
                pool_for_slot = categorized["class"]
            text, _, _ = random.choice(pool_for_slot)

            # Compute a timestamp within the slot window
            fraction = i / max(count - 1, 1)  # 0.0 to 1.0
            spread_seconds = spread_hours * 3600
            offset = fraction * spread_seconds
            ts = slot_start + timedelta(seconds=offset)

            stream_id = compute_stream_id("qq", gid)

            result.append(
                {
                    "stream_id": stream_id,
                    "message_id": fake_msg_id,
                    "user_id": user_id,
                    "speaker": user_name,
                    "content": text,
                    "timestamp": ts.timestamp(),
                    "chat_type": "group",
                    "group_id": gid,
                }
            )

    return result


# ---------------------------------------------------------------------------
# Injection Method A: raw_message_archive table
# ---------------------------------------------------------------------------


def inject_raw_message_archive(
    conn: sqlite3.Connection,
    messages: list[dict[str, Any]],
    dry_run: bool = False,
) -> int:
    """Insert messages into raw_message_archive table.

    Returns count of messages inserted.
    """
    if dry_run:
        return len(messages)

    cursor = conn.cursor()
    inserted = 0
    for msg in messages:
        try:
            cursor.execute(
                """INSERT INTO raw_message_archive
                   (stream_id, message_id, user_id, content, timestamp, chat_type)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    msg["stream_id"],
                    msg["message_id"],
                    msg["user_id"],
                    msg["content"],
                    msg["timestamp"],
                    msg["chat_type"],
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass  # skip duplicates
        except Exception as e:
            print(f"  [错误] 插入消息 {msg['message_id']} 失败: {e}", file=sys.stderr)
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Injection Method B: direct atom insertion (via MemoryStore)
# ---------------------------------------------------------------------------


def _make_atom_data(
    content: str,
    atom_type: str = "episodic",
    importance: float = 0.5,
    confidence: float = 0.7,
) -> dict[str, Any]:
    """Build an atom_data dict suitable for MemoryStore.insert_atom()."""
    return {
        "atom_type": atom_type,
        "content": content,
        "entities": [],
        "importance": importance,
        "confidence": confidence,
        "weight": importance * confidence,
        "source_scene": "chat",
        "status": "active",
        "privacy_level": "context_sensitive",
    }


async def _get_initialized_memory_store(
    db_path: Path | None = None,
    qdrant_path: Path | None = None,
) -> Any | None:
    """Create or reuse the MemoryStore singleton for standalone test scripts."""
    try:
        from src.memory.store import MemoryStore, MemoryStoreConfig
    except ImportError as e:
        print(f"  [跳过] 无法导入 MemoryStore: {e}", file=sys.stderr)
        return None

    if getattr(MemoryStore, "_instance", None) is None:
        if db_path:
            config = MemoryStoreConfig(
                sqlite_path=str(db_path),
                qdrant_local_path=str(qdrant_path or db_path.parent / "qdrant"),
            )
        else:
            config = MemoryStoreConfig()
        store = MemoryStore(config)
    else:
        store = MemoryStore.get_instance()

    if not store._initialized:
        try:
            await store.initialize()
        except Exception as e:
            print(f"  [跳过] MemoryStore 初始化失败: {e}", file=sys.stderr)
            return None

    return store


async def _close_memory_store() -> None:
    """Close the MemoryStore singleton created by this standalone script."""
    try:
        from src.memory.store import MemoryStore
    except ImportError:
        return

    if getattr(MemoryStore, "_instance", None) is None:
        return

    store = MemoryStore.get_instance()
    if getattr(store, "_initialized", False):
        await store.close()


async def inject_direct_atoms(
    messages: list[dict[str, Any]],
    dry_run: bool = False,
    db_path: Path | None = None,
    qdrant_path: Path | None = None,
) -> int:
    """Inject atoms directly via MemoryStore (Method B).

    Requires MemoryStore to be initialized. Skips if dry_run or import fails.
    """
    if dry_run:
        return 0

    store = await _get_initialized_memory_store(db_path, qdrant_path)
    if store is None:
        return 0

    # Inject a subset (every 10th message) as direct atoms
    atom_count = 0
    for i, msg in enumerate(messages):
        if i % 10 != 0:
            continue

        atom_type = random.choice(["episodic", "semantic"])
        importance = round(random.uniform(0.3, 0.95), 2)
        confidence = round(random.uniform(0.5, 0.95), 2)

        atom_data = _make_atom_data(
            content=msg["content"],
            atom_type=atom_type,
            importance=importance,
            confidence=confidence,
        )

        try:
            await store.insert_atom(atom_data)
            atom_count += 1
        except Exception as e:
            print(f"  [错误] 原子插入失败: {e}", file=sys.stderr)

    return atom_count


# ---------------------------------------------------------------------------
# Post-injection: trigger encoding pipeline
# ---------------------------------------------------------------------------


async def trigger_encoding_pipeline(
    messages: list[dict[str, Any]],
    dry_run: bool = False,
    db_path: Path | None = None,
    qdrant_path: Path | None = None,
) -> dict[str, Any]:
    """Feed messages into EncodingPipeline and run a cycle.

    Returns stats dict from run_cycle(), or error info.
    """
    result: dict[str, Any] = {"ingested": 0, "atoms_written": 0, "errors": 0}

    if dry_run:
        return result

    try:
        # Import here so script works without full bot setup
        from src.memory.encoding_pipeline import EncodingPipeline, get_encoding_pipeline
    except ImportError as e:
        print(f"  [跳过] 无法导入编码管线: {e}", file=sys.stderr)
        return result

    store = await _get_initialized_memory_store(db_path, qdrant_path)
    if store is None:
        return result

    # Reuse existing pipeline or create a temporary one
    pipeline = get_encoding_pipeline()
    if pipeline is None:
        pipeline = EncodingPipeline(
            store=store,
            trigger_count=5,
            trigger_seconds=60,
        )

    # Ingest a subset of messages (every 5th) into the pipeline buffer
    ingested = 0
    for i, msg in enumerate(messages):
        if i % 5 != 0:
            continue
        try:
            stream_type = "private_chat" if msg["chat_type"] == "private" else "group_chat"
            await pipeline.ingest(
                stream_id=msg["stream_id"],
                user_id=msg["user_id"],
                speaker=msg.get("speaker", msg["user_id"]),
                content=msg["content"],
                timestamp=msg["timestamp"],
                stream_type=stream_type,
            )
            ingested += 1
        except Exception as e:
            print(f"  [错误] ingest 失败: {e}", file=sys.stderr)
            result["errors"] += 1

    result["ingested"] = ingested
    print(f"  [编码] 已摄入 {ingested} 条消息到编码缓冲区")

    # Run encoding cycle
    try:
        stats = await pipeline.run_cycle()
        result["atoms_written"] = stats.get("atoms_written", 0)
        result["streams_processed"] = stats.get("streams_processed", 0)
        print(f"  [编码] 编码周期完成: {stats}")
    except Exception as e:
        print(f"  [错误] 编码周期运行失败: {e}", file=sys.stderr)
        result["errors"] += 1

    return result


# ---------------------------------------------------------------------------
# Verification & reporting
# ---------------------------------------------------------------------------


def print_verification(
    conn: sqlite3.Connection,
    messages: list[dict[str, Any]],
    inject_count: int,
    atom_count: int,
    encoding_result: dict[str, Any],
) -> None:
    """Query the database and print a verification report."""
    cursor = conn.cursor()

    print()
    print("=" * 72)
    print("  Verification Report")
    print("=" * 72)

    # 1. Count total rows in raw_message_archive
    cursor.execute("SELECT COUNT(*) FROM raw_message_archive")
    total_archive = cursor.fetchone()[0]
    print(f"  raw_message_archive total rows: {total_archive}")

    # 2. Count per time period (by stream_id -> group mapping)
    # We can't easily reconstruct groups from stream_id (it's MD5 hashed),
    # but we can count total injected vs total in DB
    cursor.execute("SELECT COUNT(*) FROM raw_message_archive WHERE timestamp > ?", (time.time() - 2 * 86400,))
    recent_1d = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM raw_message_archive WHERE timestamp > ? AND timestamp <= ?",
        (time.time() - 3 * 86400, time.time() - 1 * 86400),
    )
    recent_3d = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM raw_message_archive WHERE timestamp > ? AND timestamp <= ?",
        (time.time() - 10 * 86400, time.time() - 3 * 86400),
    )
    recent_1w = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM raw_message_archive WHERE timestamp > ? AND timestamp <= ?",
        (time.time() - 45 * 86400, time.time() - 10 * 86400),
    )
    recent_1m = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM raw_message_archive WHERE timestamp <= ?",
        (time.time() - 45 * 86400,),
    )
    recent_1q = cursor.fetchone()[0]

    print()
    print("  Per time period (raw_message_archive):")
    print(f"    1 day ago:     {recent_1d}  (target: 50)")
    print(f"    3 days ago:    {recent_3d}  (target: 100)")
    print(f"    1 week ago:    {recent_1w}  (target: 200)")
    print(f"    1 month ago:   {recent_1m}  (target: 300)")
    print(f"    1 quarter ago: {recent_1q}  (target: 500)")

    # 3. Count rows in memory_atoms
    try:
        cursor.execute("SELECT COUNT(*) FROM memory_atoms")
        total_atoms = cursor.fetchone()[0]
        print(f"\n  memory_atoms total rows: {total_atoms}")

        # Count by type
        cursor.execute(
            "SELECT atom_type, COUNT(*) FROM memory_atoms GROUP BY atom_type ORDER BY atom_type",
        )
        rows = cursor.fetchall()
        if rows:
            print("  memory_atoms by type:")
            for atom_type, count in rows:
                print(f"    {atom_type}: {count}")
    except sqlite3.OperationalError:
        print("\n  memory_atoms table not found or empty")

    # 4. Method B injection summary
    print("\n  Injection Summary:")
    print(f"    Method A (raw_message_archive): {inject_count} messages")
    print(f"    Method B (direct atoms):        {atom_count} atoms")
    print(f"    Encoding ingested:              {encoding_result.get('ingested', 0)} messages")
    print(f"    Encoding atoms written:         {encoding_result.get('atoms_written', 0)}")

    # 5. User coverage
    cursor.execute(
        "SELECT DISTINCT user_id FROM raw_message_archive ORDER BY user_id",
    )
    users_in_db = {row[0] for row in cursor.fetchall()}
    print(f"\n  Unique users in archive: {len(users_in_db)}")
    for uid in sorted(users_in_db):
        cursor.execute(
            "SELECT COUNT(*) FROM raw_message_archive WHERE user_id = ?",
            (uid,),
        )
        cnt = cursor.fetchone()[0]
        user_name = next((n for u, n in FICTIONAL_USERS if u == uid), uid)
        print(f"    {uid} ({user_name}): {cnt} messages")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Create required tables if they do not exist."""
    cursor = conn.cursor()

    # Match the exact schema from src/memory/schema.py
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_message_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp REAL NOT NULL,
            chat_type TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_raw_message_archive_stream_id
        ON raw_message_archive(stream_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_raw_message_archive_message_id
        ON raw_message_archive(message_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_raw_archive_stream_ts
        ON raw_message_archive(stream_id, timestamp)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memory_atoms (
            atom_id TEXT PRIMARY KEY,
            atom_type TEXT NOT NULL,
            content TEXT NOT NULL,
            entities TEXT,
            importance REAL DEFAULT 0.5,
            confidence REAL DEFAULT 0.5,
            weight REAL DEFAULT 0.5,
            created_at TEXT,
            last_accessed_at TEXT,
            last_reinforced_at TEXT,
            ttl_days INTEGER DEFAULT 7,
            decay_type TEXT DEFAULT 'exponential',
            reinforcement_count INTEGER DEFAULT 0,
            source_scene TEXT DEFAULT 'chat',
            privacy_level TEXT DEFAULT 'public',
            trace_chain_id TEXT,
            status TEXT DEFAULT 'active',
            embedding_id TEXT
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_memory_atoms_status_weight
        ON memory_atoms(status, weight)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_memory_atoms_created_status
        ON memory_atoms(created_at, status)
    """)

    conn.commit()


def _warn_existing_data(conn: sqlite3.Connection) -> bool:
    """Check if the database already has data; return True if user should confirm."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM raw_message_archive")
        count = cursor.fetchone()[0]
        return count > 0
    except sqlite3.OperationalError:
        return False


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def print_summary_table(
    messages: list[dict[str, Any]],
) -> None:
    """Print a human-readable summary of generated timeline messages."""
    print()
    print("=" * 72)
    print("  Generated Fake Data Summary")
    print("=" * 72)

    user_map = {uid: name for uid, name in FICTIONAL_USERS}
    group_map = {gid: gname for gid, gname, _ in FICTIONAL_GROUPS}

    # Count per timeline slot
    for slot_label, days_ago, _expected_count, spread_hours in TIMELINE_SLOTS:
        slot_start = time.time() - (days_ago + spread_hours / 2 / 24) * 86400
        slot_end = time.time() - (days_ago - spread_hours / 2 / 24) * 86400
        count = sum(1 for m in messages if slot_start <= m["timestamp"] <= slot_end)
        print(f"  {slot_label:20s}  {count:4d} messages  (spread over {spread_hours}h)")

    print(f"\n  Total messages: {len(messages)}")

    # Users used
    used_users = {m["user_id"] for m in messages}
    print(f"\n  Users ({len(used_users)}):")
    for uid in sorted(used_users):
        name = user_map.get(uid, uid)
        cnt = sum(1 for m in messages if m["user_id"] == uid)
        print(f"    {uid:15s} ({name:6s}): {cnt} messages")

    # Groups used
    used_groups = {m["group_id"] for m in messages}
    print(f"\n  Groups ({len(used_groups)}):")
    for gid in sorted(used_groups):
        gname = group_map.get(gid, gid)
        cnt = sum(1 for m in messages if m["group_id"] == gid)
        print(f"    {gid:15s} ({gname}): {cnt} messages")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inject fake chat records into memory.db for memory system testing.",
    )
    parser.add_argument(
        "--db-path",
        default=str(_DEFAULT_DB_PATH),
        help=f"Path to memory.db (default: {_DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--export-dir",
        default=str(_DEFAULT_EXPORT_DIR),
        help=f"Path to chat export JSON files (default: {_DEFAULT_EXPORT_DIR})",
    )
    parser.add_argument(
        "--trigger-encoding",
        action="store_true",
        help="Also inject direct atoms via MemoryStore and trigger encoding pipeline",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without actually injecting",
    )
    parser.add_argument(
        "--qdrant-path",
        default=None,
        help="Optional Qdrant local path. E2E uses this to avoid locking the bot's live Qdrant directory.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path)
    export_dir = Path(args.export_dir)
    qdrant_path = Path(args.qdrant_path) if args.qdrant_path else None
    dry_run = args.dry_run

    print(f"[配置] DB 路径:    {db_path}")
    print(f"[配置] 导出目录:  {export_dir}")
    if qdrant_path:
        print(f"[配置] Qdrant 路径: {qdrant_path}")
    print(f"[配置] 触发编码:  {args.trigger_encoding}")
    print(f"[配置] Dry-run:   {dry_run}")

    # Step 1: Load chat export messages
    print("\n[步骤 1] 加载聊天导出数据...")
    messages_pool = load_chat_messages(str(export_dir))
    print(f"  加载 {len(messages_pool)} 条原始消息")

    if not messages_pool:
        print("[错误] 没有加载到任何消息，退出", file=sys.stderr)
        sys.exit(1)

    # Step 2: Generate timeline
    print("\n[步骤 2] 生成时间线假数据...")
    timeline_messages = generate_timeline_messages(messages_pool)
    print(f"  生成了 {len(timeline_messages)} 条假消息")

    # Print summary
    print_summary_table(timeline_messages)

    # Step 3: Open database
    print(f"\n[步骤 3] {'(预演) ' if dry_run else ''}打开数据库...")
    if not dry_run:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        _ensure_tables(conn)

        if _warn_existing_data(conn):
            print("  [注意] 数据库已有数据，将追加注入")
    else:
        conn = None  # type: ignore

    # Step 4: Inject method A
    print(f"\n[步骤 4] {'(预演) ' if dry_run else ''}注入 raw_message_archive (Method A)...")
    inject_count = inject_raw_message_archive(conn, timeline_messages, dry_run=dry_run)  # type: ignore
    print(f"  注入 {inject_count} 条消息")

    # Step 5: Inject method B (optional)
    atom_count = 0
    if args.trigger_encoding:
        print(f"\n[步骤 5] {'(预演) ' if dry_run else ''}注入直接原子 (Method B)...")
        if not dry_run:
            import asyncio

            atom_count = asyncio.run(
                inject_direct_atoms(timeline_messages, dry_run=False, db_path=db_path, qdrant_path=qdrant_path)
            )
            print(f"  注入 {atom_count} 个直接原子")
    else:
        print("\n[步骤 5] 跳过直接原子注入 (使用 --trigger-encoding 启用)")

    # Step 6: Trigger encoding pipeline (optional)
    encoding_result: dict[str, Any] = {"ingested": 0, "atoms_written": 0, "errors": 0}
    if args.trigger_encoding:
        print(f"\n[步骤 6] {'(预演) ' if dry_run else ''}触发编码管线...")
        if not dry_run:
            import asyncio

            encoding_result = asyncio.run(
                trigger_encoding_pipeline(
                    timeline_messages,
                    dry_run=False,
                    db_path=db_path,
                    qdrant_path=qdrant_path,
                ),
            )
            print(
                f"  编码结果: ingested={encoding_result.get('ingested', 0)}, "
                f"atoms_written={encoding_result.get('atoms_written', 0)}"
            )
    else:
        print("\n[步骤 6] 跳过编码管线触发 (使用 --trigger-encoding 启用)")

    # Step 7: Verification
    if not dry_run:
        print("\n[步骤 7] 验证...")
        print_verification(conn, timeline_messages, inject_count, atom_count, encoding_result)  # type: ignore

        conn.close()
        print(f"\n[完成] 数据已注入: {db_path}")
    else:
        print("\n[完成] Dry-run 完成。使用 --trigger-encoding 执行实际注入。")

    # Print post-injection instructions
    if not dry_run:
        print()
        print("-" * 72)
        print("  后续步骤:")
        print("    1. 运行压力测试:  python scripts/stress_test_memory.py --quick --test real_data")
        print("    2. 启动 bot 观察梦境系统处理历史数据")
        print("    3. 检查 memory_atoms 表中由编码管线创建的原子")
        print("-" * 72)

    if args.trigger_encoding and not dry_run:
        import asyncio

        asyncio.run(_close_memory_store())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[中断] 用户中断", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\n[致命错误] {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
