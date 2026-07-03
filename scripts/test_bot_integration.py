"""
MaiBot 端到端集成测试
========================
验证 chat→memory→retrieval 全过程在零 LLM 调用、零网络依赖下无崩溃导入和运行。

测试分区:
  1. Import 验证 — 所有关键模块 try/except 导入
  2. Memory 读写 — MemoryWriter → MemoryRetriever 闭环
  3. 全管道模拟 — MessageArchiver → Pipeline.ingest() → run_cycle() → retriever
  4. 后台任务 — EncodingTask / ForgettingSweepTask / DreamTask 实例化 + run()
  5. 汇总报告
"""

import asyncio
import os
import sys
import time
import json

# ── 强制 UTF-8 ──────────────────────────────────────────────────────────────
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["MAIBOT_WORKER_PROCESS"] = "1"

# ── 测前准备：分离测试 DB（文件 DB 用于 import，测试使用独立 :memory:）─────
# schema.py 在 import 时已初始化文件型 memory.db（无法阻止）。
# 我们额外创建一个 :memory: 数据库，手动建表并将后面测试涉及的模型绑定到它。
from peewee import SqliteDatabase
import src.memory.schema as _schema

_temp_db = SqliteDatabase(":memory:")
_temp_db.connect()
# 将所有 schema 模型绑定到临时 DB，并在临时 DB 上建表
for _model in _schema.MODELS:
    _model._meta.database = _temp_db
_temp_db.create_tables(_schema.MODELS)
# 为 schema 中引用 memory_db 的函数打补丁，确保它们使用临时 DB
_schema.memory_db = _temp_db

# ── 测试结果容器 ──────────────────────────────────────────────────────────
_results: dict[str, str] = {}  # name → "PASS" / "FAIL: ..."


def _check(name: str, ok: bool, detail: str = "") -> None:
    """记录一个测试结果"""
    status = "PASS" if ok else f"FAIL: {detail}"
    _results[name] = status
    print(f"  [{status}] {name}")


def _cleanup_temp_db() -> None:
    """清空所有临时表（不删表结构）"""
    from src.memory.schema import (
        MemoryAtom,
        EpisodicDetail,
        SemanticDetail,
        MemoryTraceChain,
        RawMessageArchive,
        ConflictObservation,
        NoisePool,
        InsightPool,
        GraphNode,
        GraphEdge,
        GraphEntry,
        DreamRun,
    )

    tables = [
        MemoryAtom,
        EpisodicDetail,
        SemanticDetail,
        MemoryTraceChain,
        RawMessageArchive,
        ConflictObservation,
        NoisePool,
        InsightPool,
        GraphNode,
        GraphEdge,
        GraphEntry,
        DreamRun,
    ]
    with _temp_db.atomic():
        for tbl in tables:
            tbl.delete().execute()


# ═════════════════════════════════════════════════════════════════════════════
# Section 1: Import Verification
# ═════════════════════════════════════════════════════════════════════════════


def test_imports() -> None:
    """验证所有关键模块可导入"""
    print("\n" + "=" * 60)
    print("Section 1: Import 验证")
    print("=" * 60)

    modules = [
        ("bot (main entry)", "bot"),
        ("src.main (MainSystem)", "src.main"),
        ("src.memory (full package)", "src.memory"),
        ("src.memory.encoding_pipeline", "src.memory.encoding_pipeline"),
        ("src.memory.prompt_integration", "src.memory.prompt_integration"),
        ("src.memory.objectivity_check", "src.memory.objectivity_check"),
        ("src.chat.brain_chat.brain_chat", "src.chat.brain_chat.brain_chat"),
        ("src.chat.heart_flow.heartFC_chat", "src.chat.heart_flow.heartFC_chat"),
        ("src.chat.replyer.group_generator", "src.chat.replyer.group_generator"),
        ("src.chat.replyer.private_generator", "src.chat.replyer.private_generator"),
    ]

    for label, module_name in modules:
        try:
            __import__(module_name)
            _check(f"  import {label}", True)
        except Exception as e:
            _check(f"  import {label}", False, f"{e}")


# ═════════════════════════════════════════════════════════════════════════════
# Section 2: Memory Read-after-Write
# ═════════════════════════════════════════════════════════════════════════════


async def test_memory_read_write() -> None:
    """MemoryWriter 写入原子 → MemoryRetriever 检索验证"""
    print("\n" + "=" * 60)
    print("Section 2: Memory 读写验证")
    print("=" * 60)

    _cleanup_temp_db()

    from src.memory import MemoryStore, MemoryStoreConfig
    from src.memory.layer3_retrieval import MemoryRetriever
    from src.memory.store import MemoryStore as MemoryStoreCls

    # 重置单例
    MemoryStoreCls._instance = None
    config = MemoryStoreConfig()
    store = MemoryStore(config)
    await store.initialize()

    retriever = MemoryRetriever(store)

    test_atom_id = "test-integration-atom-001"
    test_content = "小明喜欢打篮球，每周至少打三次"

    # 直接通过 store.insert_atom 写入（绕过 WriteOperation 的 json.dumps 序列化限制）
    try:
        import datetime as _dt

        returned_id = await store.insert_atom(
            {
                "atom_id": test_atom_id,
                "atom_type": "factual",
                "content": test_content,
                "entities": ["小明", "篮球"],
                "importance": 0.8,
                "confidence": 0.9,
                "weight": 0.7,
                "created_at": _dt.datetime.now(),
                "last_accessed_at": _dt.datetime.now(),
                "ttl_days": 180,
                "decay_type": "exponential",
                "reinforcement_count": 0,
                "source_scene": "group_chat",
                "privacy_level": "public",
                "status": "active",
            }
        )
        # store.insert_atom() 返回新生成的 UUID 而非传入的 atom_id
        # （已知行为：return 的是 uuid4() 生成的 ID，而非 atom_data["atom_id"]）
        written = await store.get_atom(test_atom_id)
        _check("  写入原子", written is not None and returned_id != "", f"exists={written is not None}")
    except Exception as e:
        _check("  写入原子", False, str(e))
        return  # 后续依赖写入成功

    # 检索（按场景）
    try:
        context = await retriever.get_context_for_reply(
            stream_id="group_99999",
            max_atoms=10,
        )
        found = test_content in context
        _check("  检索上下文包含写入内容", found, f"context={context[:200]!r}")
    except Exception as e:
        _check("  检索上下文", False, str(e))

    # 按关键词检索
    try:
        kw_results = await retriever.keyword_search(query="篮球", limit=5)
        kw_found = any(test_atom_id == r.get("atom_id") for r in kw_results)
        _check("  关键词检索包含写入原子", kw_found, f"results={len(kw_results)}")
    except Exception as e:
        _check("  关键词检索", False, str(e))

    # 带 ID 检索
    try:
        ctx, ids = await retriever.get_context_for_reply_with_ids(
            stream_id="group_99999",
            max_atoms=10,
        )
        id_found = test_atom_id in ids
        _check("  带ID检索返回正确 atom_id", id_found, f"ids={ids}")
    except Exception as e:
        _check("  带ID检索", False, str(e))


# ═════════════════════════════════════════════════════════════════════════════
# Section 3: Full Pipeline Simulation
# ═════════════════════════════════════════════════════════════════════════════


async def test_full_pipeline() -> None:
    """模拟一条消息经过 Layer0 → Layer1 → Pipeline → 检索的完整流程"""
    print("\n" + "=" * 60)
    print("Section 3: 全管道模拟")
    print("=" * 60)

    _cleanup_temp_db()

    from src.memory import MemoryStore, MemoryStoreConfig
    from src.memory.store import MemoryStore as MemoryStoreCls
    from src.memory.layer0_archive import MessageArchiver
    from src.memory.layer1_summarizer import GroupTopicSummarizer
    from src.memory.encoding_pipeline import EncodingPipeline
    from src.memory.layer3_retrieval import MemoryRetriever

    # 重置单例并创建新的内存 store
    MemoryStoreCls._instance = None
    config = MemoryStoreConfig()
    store = MemoryStore(config)
    await store.initialize()

    # ── 3a. 消息归档 ──────────────────────────────────────────
    try:
        archiver = MessageArchiver()
        from src.memory.schema import RawMessageArchive as RawMsgModel
        import types

        # 构造一个模拟消息对象（duck-typing）
        mock_message = types.SimpleNamespace(
            group_id="group_test_123",
            message_id="msg_001",
            user_id="user_bob",
            content="今天天气真好，适合出去打球",
            timestamp=time.time(),
        )
        record_id = await archiver.archive_group_message(mock_message)
        count = RawMsgModel.select().count()
        _check("  3a 消息归档", count >= 1, f"record_id={record_id} count={count}")
    except Exception as e:
        _check("  3a 消息归档", False, str(e))

    # ── 3b. 话题摘要 ──────────────────────────────────────────
    try:
        summarizer = GroupTopicSummarizer()
        tid = summarizer.add_message(
            stream_id="group_test_123",
            message_text="今天天气真好，适合出去打球",
            user_id="user_bob",
            timestamp=time.time(),
        )
        topics = summarizer.get_topic_summaries("group_test_123")
        _check("  3b 话题摘要", len(topics) >= 1, f"topic_id={tid} topics={len(topics)}")
    except Exception as e:
        _check("  3b 话题摘要", False, str(e))

    # ── 3c. 编码管线（不触发 LLM，验证无崩溃）──────────────
    pipeline = None
    try:
        pipeline = EncodingPipeline(store, trigger_count=999, trigger_seconds=99999)
        _check("  3c 管线初始化", True)
    except Exception as e:
        _check("  3c 管线初始化", False, str(e))

    if pipeline:
        try:
            await pipeline.ingest(
                stream_id="group_test_123",
                user_id="user_bob",
                speaker="Bob",
                content="今天天气真好，适合出去打球",
                timestamp=time.time(),
            )
            _check("  3c ingest()", True)
        except Exception as e:
            _check("  3c ingest()", False, str(e))

        # 执行一个编码周期（缓冲区不足 999 条，不会触发 LLM）
        try:
            stats = await pipeline.run_cycle()
            _check("  3c run_cycle() 无崩溃", True, f"stats={stats}")
        except Exception as e:
            _check("  3c run_cycle() 无崩溃", False, str(e))

    # ── 3d. 手动写入 + 检索验证 ──────────────────────────────

    try:
        import datetime as _dt

        await store.insert_atom(
            {
                "atom_id": "pipeline-test-atom-002",
                "atom_type": "episodic",
                "content": "群 group_test_123 中 user_bob 说今天天气好适合打球",
                "entities": ["user_bob", "打球"],
                "importance": 0.6,
                "confidence": 0.8,
                "weight": 0.6,
                "created_at": _dt.datetime.now(),
                "last_accessed_at": _dt.datetime.now(),
                "ttl_days": 7,
                "decay_type": "exponential",
                "reinforcement_count": 0,
                "source_scene": "group_chat",
                "privacy_level": "public",
                "status": "active",
            }
        )

        retriever = MemoryRetriever(store)
        ctx = await retriever.get_context_for_reply(stream_id="group_test_123", max_atoms=10)
        found = "天气" in ctx or "打球" in ctx or "user_bob" in ctx
        _check("  3d 检索验证", found, f"context={ctx[:200]!r}")
    except Exception as e:
        _check("  3d 检索验证", False, str(e))

    # ── 3e. 跨场景检索 ────────────────────────────────────────
    try:
        retriever = MemoryRetriever(store)
        cross = await retriever.get_cross_scene_context(
            scene_type="group_chat",
            stream_id="group_test_123",
            user_id="user_bob",
            max_atoms=3,
        )
        # 跨场景可能为空（我们没有写 private_chat 记忆），不崩溃即为通过
        _check("  3e 跨场景检索无崩溃", True, f"chars={len(cross)}")
    except Exception as e:
        _check("  3e 跨场景检索无崩溃", False, str(e))


# ═════════════════════════════════════════════════════════════════════════════
# Section 4: Background Task Lifecycle
# ═════════════════════════════════════════════════════════════════════════════


async def test_background_tasks() -> None:
    """验证 EncodingTask / ForgettingSweepTask / DreamTask 的创建和 run()"""
    print("\n" + "=" * 60)
    print("Section 4: 后台任务生命周期")
    print("=" * 60)

    _cleanup_temp_db()

    from src.memory import MemoryStore, MemoryStoreConfig
    from src.memory.store import MemoryStore as MemoryStoreCls
    from src.memory.encoding_pipeline import EncodingPipeline, EncodingTask
    from src.memory.forgetting import ForgettingManager, ForgettingSweepTask
    from src.memory.dream_agent import DreamTask
    from src.memory.graph_store import GraphStore

    MemoryStoreCls._instance = None
    config = MemoryStoreConfig()
    store = MemoryStore(config)
    await store.initialize()

    # ── EncodingTask ──────────────────────────────────────────
    try:
        pipeline = EncodingPipeline(store, trigger_count=999, trigger_seconds=99999)
        task = EncodingTask(pipeline, interval=300)
        # run() 应该无异常（缓冲区空 → 无就绪流 → 返回）
        await task.run()
        _check("  EncodingTask 创建 + run()", True)
    except Exception as e:
        _check("  EncodingTask 创建 + run()", False, str(e))

    # ── ForgettingSweepTask ───────────────────────────────────
    try:
        fg_mgr = ForgettingManager(store)
        task = ForgettingSweepTask(fg_mgr)
        result = await task._manager.run_sweep()
        assert isinstance(result, dict), f"run_sweep 应返回 dict, 得到 {type(result)}"
        _check("  ForgettingSweepTask 创建 + run()", True, f"result={result}")
    except Exception as e:
        _check("  ForgettingSweepTask 创建 + run()", False, str(e))

    # ── DreamTask ─────────────────────────────────────────────
    try:
        graph_store = GraphStore()
        task = DreamTask(
            store=store,
            forgetting_manager=None,
            graph_store=graph_store,
        )
        # 不执行完整 run() 周期（会触发 _check_idle 等），仅验证构造
        _check("  DreamTask 创建", True)
    except Exception as e:
        _check("  DreamTask 创建", False, str(e))

    # ── DreamTask.run() 额外验证（要求非梦想时段内跳过，不崩溃）─
    try:
        graph_store2 = GraphStore()
        task2 = DreamTask(
            store=store,
            forgetting_manager=None,
            graph_store=graph_store2,
        )
        await task2.run()
        _check("  DreamTask.run() 无崩溃", True)
    except Exception as e:
        _check("  DreamTask.run() 无崩溃", False, str(e))


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════


def print_report() -> None:
    """打印汇总报告"""
    print("\n" + "=" * 60)
    print(" 测试汇总报告")
    print("=" * 60)
    passed = sum(1 for v in _results.values() if v == "PASS")
    failed = sum(1 for v in _results.values() if v.startswith("FAIL"))
    total = len(_results)
    print(f"  通过: {passed}/{total}")
    print(f"  失败: {failed}/{total}")
    if failed:
        print("\n  ❌ 失败明细:")
        for name, status in _results.items():
            if status.startswith("FAIL"):
                print(f"     {name}: {status}")
    print("=" * 60)

    # 导出 JSON 报告
    report_path = os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        "data",
        "test_bot_integration_result.json",
    )
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": time.time(),
                "passed": passed,
                "failed": failed,
                "total": total,
                "results": dict(_results),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"  报告已导出: {report_path}")


async def main() -> None:
    print("=" * 60)
    print(" MaiBot 端到端集成测试")
    print(f"  CWD: {os.getcwd()}")
    print(f"  TIME: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Section 1: Import
    test_imports()

    # Section 2: Memory read-after-write
    await test_memory_read_write()

    # Section 3: Full pipeline
    await test_full_pipeline()

    # Section 4: Background tasks
    await test_background_tasks()

    # Report
    print_report()


if __name__ == "__main__":
    asyncio.run(main())
