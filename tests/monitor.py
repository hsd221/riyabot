#!/usr/bin/env python3
"""E2E 压力测试监控守护进程

收集系统指标、LLM 调用追踪、记忆/梦境系统行为、向量数据库状态、
数据库指标和日志关键字，输出 JSONL 和周期性摘要。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 项目根路径设置
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# psutil —— 如果不可用则降级为 /proc 解析
# ---------------------------------------------------------------------------
try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# ---------------------------------------------------------------------------
# Qdrant 客户端
# ---------------------------------------------------------------------------
try:
    from qdrant_client import QdrantClient

    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 需要监控的记忆子系统 Logger 名称（与 src/common/logger.py MODULE_COLORS 对齐）
LOGGER_NAMES_MEMORY: list[str] = [
    "memory.store",  # 原子 CRUD
    "memory.dream",  # 梦境周期
    "memory.weaver",  # 梦呓编织
    "memory.encoding",  # 编码管线
    "memory.forgetting",  # 遗忘扫描
    "memory.layer3",  # 检索
    "memory.layer2",  # 编码器
    "memory.layer0",  # 归档
    "recon",  # 双写一致性协调（注意：命名不含 memory. 前缀）
    "memory.insight",  # 洞见生成
    "memory.inspiration",  # 噪声回收
    "memory.conflict",  # 冲突仲裁
    "memory.feedback",  # 记忆强化
    "memory.association",  # 记忆关联
    "memory.atom",  # 原子操作
    "memory.schema",  # 数据库表
    "memory.trace",  # 追溯链
    "memory.graph",  # 图谱
]

# LLM 追踪相关 Logger
LOGGER_NAMES_LLM: list[str] = [
    "memory.encoding",
    "memory.weaver",
    "memory.insight",
    "memory.inspiration",
]

# 梦境相关 Logger
LOGGER_NAMES_DREAM: list[str] = [
    "memory.dream",
    "memory.weaver",
]

# 数据库监控表
DB_TABLES: list[str] = [
    "memory_atoms",
    "noise_pool",
    "insight_pool",
    "dream_runs",
    "graph_edges",
]

# 日志扫描关键字
ERROR_KEYWORDS: list[str] = [
    "Error",
    "Exception",
    "Timeout",
    "OOM",
    "Traceback",
    "failed",
    "corrupted",
]

MEMORY_DB_PATH = PROJECT_ROOT / "data" / "memory.db"


def _is_chat_observation_log(entry: dict[str, Any]) -> bool:
    """Return True for chat-content logs that may contain historical error text."""
    logger_name = str(entry.get("logger_name") or entry.get("logger", ""))
    level = str(entry.get("level", "")).lower()
    message = str(entry.get("event") or entry.get("message", ""))

    if level not in {"debug", "info"}:
        return False
    if logger_name in {"chat", "所见", "聊天"}:
        return True
    if logger_name == "person_stub" and "register_person" in message:
        return True
    return "[所见]" in message


# ---------------------------------------------------------------------------
# 自定义 Logging Handler —— 捕获目标 Logger 的日志记录
# ---------------------------------------------------------------------------


class LogCaptureHandler(logging.Handler):
    """捕获指定 Logger 名称的日志记录，转发到 asyncio 队列。"""

    def __init__(
        self,
        memory_names: list[str],
        llm_names: list[str],
        dream_names: list[str],
        queue: asyncio.Queue,
        level: int = logging.DEBUG,
    ) -> None:
        super().__init__(level=level)
        self._memory_names = memory_names
        self._llm_names = llm_names
        self._dream_names = dream_names
        self._queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            name = record.name
            msg = record.getMessage()

            # 梦境行为检测
            if any(name.startswith(d) for d in self._dream_names):
                entry = {
                    "type": "dream_trace",
                    "logger": name,
                    "level": record.levelname,
                    "message": msg,
                    "timestamp": record.created,
                }
                self._try_put_nowait(entry)

            # LLM 追踪检测
            if any(name.startswith(n) for n in self._llm_names) or (
                record.levelno >= logging.DEBUG and ("prompt" in msg.lower() or "response" in msg.lower())
            ):
                entry = {
                    "type": "llm_trace",
                    "logger": name,
                    "level": record.levelname,
                    "message": msg,
                    "timestamp": record.created,
                    "context": {},
                }
                self._try_put_nowait(entry)

            # 记忆行为检测
            if any(name.startswith(m) for m in self._memory_names):
                entry = {
                    "type": "memory_trace",
                    "logger": name,
                    "level": record.levelname,
                    "message": msg,
                    "timestamp": record.created,
                }
                self._try_put_nowait(entry)

            # 通用日志（maibot_statistic, async_task_manager）
            if name == "maibot_statistic" or name == "async_task_manager":
                entry = {
                    "type": "general_trace",
                    "logger": name,
                    "level": record.levelname,
                    "message": msg,
                    "timestamp": record.created,
                }
                self._try_put_nowait(entry)

        except Exception:
            self.handleError(record)

    def _try_put_nowait(self, entry: dict) -> None:
        """非阻塞入队，队列满则丢弃最旧的条目。"""
        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            # 队列满时丢弃最旧的条目
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(entry)
            except asyncio.QueueFull:
                pass


# ---------------------------------------------------------------------------
# 指标收集器
# ---------------------------------------------------------------------------


class MetricsCollector:
    """异步指标收集器，管理所有采集协程。"""

    def __init__(self, output_path: str, interval: int = 5, duration: int = 0) -> None:
        self.output_path = Path(output_path)
        self.interval = interval
        self.duration = duration
        self.start_time = time.time()

        # 日志事件队列（缓冲 10000 条）
        self.log_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)

        # 统计计数器
        self.memory_writes = 0
        self.memory_queries = 0
        self.memory_consolidations = 0
        self.memory_anomalies = 0
        self.dream_generations = 0
        self.dream_triggers = 0
        self.dream_stores = 0
        self.dream_errors = 0
        self.llm_trace_count = 0
        self.error_count = 0

        # 文件锁
        self._file_lock = asyncio.Lock()
        self._output_file = None  # type: ignore

        # /proc 降级缓存
        self._proc_net_dev: tuple[float, dict[str, int]] | None = None

    # ---- 文件写入 ----

    async def _open_output(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._output_file = open(self.output_path, "w", encoding="utf-8")

    async def _close_output(self) -> None:
        if self._output_file and not self._output_file.closed:
            self._output_file.close()

    async def _write_metric(self, category: str, data: dict[str, Any]) -> None:
        """写入一条指标到 JSONL。"""
        metric = {
            "type": "metric",
            "category": category,
            "timestamp": time.time(),
            "data": data,
        }
        line = json.dumps(metric, ensure_ascii=False)
        async with self._file_lock:
            if self._output_file and not self._output_file.closed:
                self._output_file.write(line + "\n")
                self._output_file.flush()

    async def _flush_log_queue(self) -> None:
        """将日志队列中的事件批量写入 JSONL。"""
        batch: list[dict] = []
        while not self.log_queue.empty() and len(batch) < 500:
            try:
                batch.append(self.log_queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not batch:
            return

        lines = "\n".join(json.dumps(e, ensure_ascii=False) for e in batch)
        async with self._file_lock:
            if self._output_file and not self._output_file.closed:
                self._output_file.write(lines + "\n")
                self._output_file.flush()

    # ---- 系统指标 ----

    async def collect_system_metrics(self) -> None:
        """每 interval 秒采集一次系统指标。"""
        while True:
            try:
                data: dict[str, Any] = {}

                if HAS_PSUTIL:
                    # CPU
                    data["cpu_percent"] = psutil.cpu_percent(interval=0.1)

                    # 内存
                    mem = psutil.virtual_memory()
                    data["memory_rss"] = mem.used
                    data["memory_vms"] = mem.total
                    data["memory_percent"] = mem.percent
                    proc = psutil.Process()
                    data["process_rss"] = proc.memory_info().rss
                    data["process_vms"] = proc.memory_info().vms

                    # 磁盘 IO
                    disk = psutil.disk_io_counters()
                    if disk:
                        data["disk_read_bytes"] = disk.read_bytes
                        data["disk_write_bytes"] = disk.write_bytes
                        data["disk_read_count"] = disk.read_count
                        data["disk_write_count"] = disk.write_count

                    # 网络 IO
                    net = psutil.net_io_counters()
                    data["net_bytes_sent"] = net.bytes_sent
                    data["net_bytes_recv"] = net.bytes_recv
                    data["net_packets_sent"] = net.packets_sent
                    data["net_packets_recv"] = net.packets_recv

                    # 进程数 / 线程数
                    data["process_threads"] = proc.num_threads()
                    data["process_open_files"] = len(proc.open_files())

                    # 负载
                    load = psutil.getloadavg()
                    data["load_1m"] = load[0]
                    data["load_5m"] = load[1]
                    data["load_15m"] = load[2]
                else:
                    # 降级：从 /proc 读取
                    data.update(self._proc_cpu_percent())
                    data.update(self._proc_memory())
                    data.update(self._proc_net_io())

                await self._write_metric("system", data)
            except Exception as e:
                await self._write_metric("system", {"error": str(e)})

            await asyncio.sleep(self.interval)

    # ---- /proc 降级实现 ----

    @staticmethod
    def _proc_cpu_percent() -> dict[str, float]:
        """从 /proc/stat 读取 CPU（近似）。"""
        try:
            with open("/proc/stat", encoding="utf-8") as f:
                line = f.readline()
            parts = line.split()
            if len(parts) >= 5:
                user = int(parts[1])
                nice = int(parts[2])
                system = int(parts[3])
                idle = int(parts[4])
                total = user + nice + system + idle
                return {
                    "cpu_ticks_user": user,
                    "cpu_ticks_system": system,
                    "cpu_ticks_idle": idle,
                    "cpu_ticks_total": total,
                }
        except (FileNotFoundError, IndexError, ValueError):
            pass
        return {}

    @staticmethod
    def _proc_memory() -> dict[str, int]:
        """从 /proc/meminfo 读取内存。"""
        try:
            with open("/proc/meminfo", encoding="utf-8") as f:
                content = f.read()
            lines = content.split("\n")
            mem_total = 0
            mem_avail = 0
            for line in lines:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    mem_avail = int(line.split()[1]) * 1024
            if mem_total and mem_avail:
                return {"memory_total": mem_total, "memory_avail": mem_avail, "memory_used": mem_total - mem_avail}
        except (FileNotFoundError, IndexError, ValueError):
            pass
        return {}

    def _proc_net_io(self) -> dict[str, int]:
        """从 /proc/net/dev 读取网络 IO。"""
        try:
            with open("/proc/net/dev", encoding="utf-8") as f:
                content = f.read()
            lines = content.strip().split("\n")
            rx_bytes = 0
            tx_bytes = 0
            for line in lines[2:]:  # 跳过前两行标题
                parts = line.split()
                if len(parts) >= 10:
                    rx_bytes += int(parts[1])
                    tx_bytes += int(parts[9])
            return {"net_bytes_recv": rx_bytes, "net_bytes_sent": tx_bytes}
        except (FileNotFoundError, IndexError, ValueError):
            pass
        return {}

    # ---- 数据库监控 ----

    async def collect_db_metrics(self) -> None:
        """每 30 秒采集一次 SQLite 数据库指标。"""
        await asyncio.sleep(3)  # 等系统启动
        while True:
            try:
                data: dict[str, Any] = {}

                # 文件大小
                db_path = MEMORY_DB_PATH
                if db_path.exists():
                    data["file_size_bytes"] = db_path.stat().st_size
                else:
                    data["file_size_bytes"] = 0

                # 数据库健康检查 + 行数统计
                try:
                    conn = sqlite3.connect(str(db_path))
                    conn.execute("PRAGMA busy_timeout=1000")
                    cursor = conn.execute("PRAGMA integrity_check")
                    integrity = cursor.fetchone()
                    data["integrity_check"] = integrity[0] if integrity else "unknown"

                    for table in DB_TABLES:
                        try:
                            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                            data[f"row_count_{table}"] = cursor.fetchone()[0]
                        except sqlite3.OperationalError:
                            data[f"row_count_{table}"] = -1

                    conn.close()
                except sqlite3.Error as e:
                    data["error"] = str(e)

                await self._write_metric("database", data)
            except Exception as e:
                await self._write_metric("database", {"error": str(e)})

            await asyncio.sleep(30)

    # ---- 向量数据库（Qdrant）监控 ----

    async def collect_qdrant_metrics(self) -> None:
        """每 60 秒检查一次 Qdrant 状态。"""
        if not HAS_QDRANT:
            await self._write_metric("vectordb", {"status": "unavailable", "reason": "qdrant_client not installed"})
            return

        await asyncio.sleep(5)
        qdrant_logged_unavailable = False

        # 尝试从配置文件读取 Qdrant URL
        qdrant_url = None
        qdrant_local_path = None
        try:
            config_path = PROJECT_ROOT / "config" / "bot_config.toml"
            if config_path.exists():
                import tomlkit

                with open(config_path, encoding="utf-8") as f:
                    cfg = tomlkit.load(f)
                mc = cfg.get("memory", {})
                qdrant_url = mc.get("qdrant_url", None)
                qdrant_local_path = mc.get("qdrant_local_path", None)
        except Exception:
            pass

        while True:
            try:
                data: dict[str, Any] = {}
                client = None
                if qdrant_local_path:
                    local_dir = PROJECT_ROOT / qdrant_local_path
                    data["local_path"] = str(local_dir)
                    data["local_path_exists"] = local_dir.exists()
                    if local_dir.exists():
                        data["local_path_size_bytes"] = sum(
                            f.stat().st_size for f in local_dir.rglob("*") if f.is_file()
                        )

                if qdrant_url:
                    client = QdrantClient(url=qdrant_url)
                    data["remote_url"] = qdrant_url
                elif qdrant_local_path:
                    client = QdrantClient(path=str(PROJECT_ROOT / qdrant_local_path))

                if client:
                    try:
                        collections = client.get_collections()
                        data["collections"] = [c.name for c in collections.collections]
                        data["collection_count"] = len(collections.collections)
                        for c in collections.collections:
                            info = client.get_collection(c.name)
                            data[f"points_count_{c.name}"] = info.points_count
                    except Exception as e:
                        data["query_error"] = str(e)
                    finally:
                        client.close()

                qdrant_logged_unavailable = False
                await self._write_metric("vectordb", data)
            except Exception as e:
                if not qdrant_logged_unavailable:
                    await self._write_metric("vectordb", {"status": "error", "error": str(e)})
                    qdrant_logged_unavailable = True

            await asyncio.sleep(60)

    # ---- 日志文件扫描 ----

    async def scan_log_files(self) -> None:
        """每 15 秒扫描 logs/ 目录中的最新 JSONL 文件，检测错误关键字。"""
        await asyncio.sleep(3)
        log_dir = PROJECT_ROOT / "logs"
        last_position: dict[str, int] = {}

        # 错误去重：记录已发现的错误避免重复
        seen_errors: set[str] = set()

        while True:
            try:
                if not log_dir.exists():
                    await asyncio.sleep(15)
                    continue

                # 获取最新的日志文件
                log_files = sorted(log_dir.glob("app_*.log.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
                if not log_files:
                    await asyncio.sleep(15)
                    continue

                latest_file = log_files[0]
                filepath = str(latest_file)
                last_pos = last_position.get(filepath, 0)

                try:
                    file_size = latest_file.stat().st_size
                    if file_size <= last_pos:
                        await asyncio.sleep(15)
                        continue

                    with open(latest_file, encoding="utf-8") as f:
                        f.seek(last_pos)
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            # 解析 JSONL
                            try:
                                entry = json.loads(line)
                                if isinstance(entry, dict) and _is_chat_observation_log(entry):
                                    continue
                                msg_text = json.dumps(entry, ensure_ascii=False)
                            except json.JSONDecodeError:
                                msg_text = line

                            # 扫描错误关键字
                            for kw in ERROR_KEYWORDS:
                                if kw.lower() in msg_text.lower():
                                    # 生成去重指纹
                                    fingerprint = f"{kw}:{msg_text[:200]}"
                                    if fingerprint not in seen_errors:
                                        seen_errors.add(fingerprint)
                                        self.error_count += 1
                                        await self._write_metric(
                                            "log_scan",
                                            {
                                                "keyword": kw,
                                                "file": latest_file.name,
                                                "match": msg_text[:500],
                                            },
                                        )
                                    break

                    last_position[filepath] = file_size

                    # 限制 seen_errors 大小
                    if len(seen_errors) > 10000:
                        seen_errors.clear()

                except (FileNotFoundError, PermissionError):
                    pass

            except Exception:
                pass

            await asyncio.sleep(15)

    # ---- 摘要输出 ----

    async def print_summary(self) -> None:
        """每 30 秒打印一次实时摘要。"""
        first_summary = True
        while True:
            await asyncio.sleep(30)
            elapsed = time.time() - self.start_time

            if first_summary:
                print(f"\n{'=' * 60}", flush=True)
                print(f" [监控] 启动 | 间隔={self.interval}s | 输出={self.output_path}", flush=True)
                print(
                    f" psutil={'✓' if HAS_PSUTIL else '✗(降级)'} | qdrant_client={'✓' if HAS_QDRANT else '✗'}",
                    flush=True,
                )
                print(f" memory.db={'✓' if MEMORY_DB_PATH.exists() else '✗'}", flush=True)
                print(f"{'=' * 60}\n", flush=True)
                first_summary = False

            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"运行 {elapsed:.0f}s | "
                f"系统 ✓ | "
                f"记忆 W:{self.memory_writes} Q:{self.memory_queries} C:{self.memory_consolidations} "
                f"异常:{self.memory_anomalies} | "
                f"梦境 生成:{self.dream_generations} 触发:{self.dream_triggers} "
                f"存入:{self.dream_stores} 错误:{self.dream_errors} | "
                f"LLM追踪:{self.llm_trace_count} | "
                f"错误:{self.error_count}",
                flush=True,
            )

    # ---- 日志事件消费 ----

    async def consume_log_events(self) -> None:
        """消费日志队列，更新统计计数器并写入 JSONL。"""
        while True:
            try:
                entry = await asyncio.wait_for(self.log_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # 定期刷新队列
                await self._flush_log_queue()
                continue

            # 更新计数器
            etype = entry.get("type", "")
            msg = entry.get("message", "")
            level = entry.get("level", "INFO")
            logger_name = entry.get("logger", "")

            if etype == "llm_trace":
                self.llm_trace_count += 1
            elif etype == "memory_trace":
                if "memory.store" in logger_name:
                    msg_lower = msg.lower()
                    if any(w in msg_lower for w in ("insert", "write")):
                        self.memory_writes += 1
                    elif "delete" in msg_lower:
                        pass  # 也计入 writes
                    else:
                        self.memory_queries += 1
                if "memory.encoding" in logger_name:
                    self.memory_consolidations += 1
                if level in ("WARNING", "ERROR", "CRITICAL"):
                    self.memory_anomalies += 1
            elif etype == "dream_trace":
                msg_lower = msg.lower()
                if "memory.dream" in logger_name:
                    if "start" in msg_lower:
                        self.dream_triggers += 1
                    elif "complete" in msg_lower or "consolidat" in msg_lower:
                        self.dream_generations += 1
                    elif "fail" in msg_lower:
                        self.dream_errors += 1
                if "memory.weaver" in logger_name:
                    self.dream_stores += 1
                if level in ("ERROR", "CRITICAL"):
                    self.dream_errors += 1

            # 写入 JSONL
            line = json.dumps(entry, ensure_ascii=False)
            async with self._file_lock:
                if self._output_file and not self._output_file.closed:
                    self._output_file.write(line + "\n")
                    self._output_file.flush()

            self.log_queue.task_done()

    # ---- 主运行循环 ----

    async def run(self) -> None:
        """启动所有采集协程。"""
        await self._open_output()

        # 注册日志捕获 handler
        handler = LogCaptureHandler(
            memory_names=LOGGER_NAMES_MEMORY,
            llm_names=LOGGER_NAMES_LLM,
            dream_names=LOGGER_NAMES_DREAM,
            queue=self.log_queue,
        )
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)

        # 创建采集任务
        collectors = [
            self.collect_system_metrics(),
            self.collect_db_metrics(),
            self.collect_qdrant_metrics(),
            self.scan_log_files(),
            self.print_summary(),
            self.consume_log_events(),
        ]

        # 如果指定了 duration，设置超时取消
        main_task = asyncio.gather(*collectors, return_exceptions=True)

        if self.duration > 0:
            try:
                await asyncio.wait_for(main_task, timeout=self.duration)
            except asyncio.TimeoutError:
                pass
        else:
            # 无限运行等待信号
            stop_event = asyncio.Event()
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGINT, stop_event.set)
            loop.add_signal_handler(signal.SIGTERM, stop_event.set)

            await stop_event.wait()

        # 清理
        await self.shutdown(handler)

    async def shutdown(self, handler: LogCaptureHandler | None = None) -> None:
        """优雅关闭。"""
        # 移除 handler
        if handler:
            root_logger = logging.getLogger()
            root_logger.removeHandler(handler)

        # 刷新日志队列
        await self._flush_log_queue()

        # 关闭输出文件
        await self._close_output()

        # 打印最终摘要
        elapsed = time.time() - self.start_time
        print(f"\n{'=' * 60}", flush=True)
        print(" [监控] 最终报告", flush=True)
        print(f" 运行时间: {elapsed:.0f}s", flush=True)
        print(f" 输出文件: {self.output_path}", flush=True)
        print(f" LLM 追踪: {self.llm_trace_count} 条", flush=True)
        print(f" 记忆写入: {self.memory_writes} 次", flush=True)
        print(f" 记忆查询: {self.memory_queries} 次", flush=True)
        print(f" 记忆巩固: {self.memory_consolidations} 次", flush=True)
        print(f" 记忆异常: {self.memory_anomalies} 次", flush=True)
        print(f" 梦境生成: {self.dream_generations} 次", flush=True)
        print(f" 梦境触发: {self.dream_triggers} 次", flush=True)
        print(f" 梦境存入: {self.dream_stores} 次", flush=True)
        print(f" 梦境错误: {self.dream_errors} 次", flush=True)
        print(f" 日志错误: {self.error_count} 个关键字", flush=True)
        print(f"{'=' * 60}\n", flush=True)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="E2E 压力测试监控守护进程")
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="采集间隔（秒，默认 5）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(PROJECT_ROOT / "tests" / "artifacts" / "monitor_metrics.jsonl"),
        help="输出 JSONL 文件路径",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        help="运行时长（秒，0=无限运行，默认 0）",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    collector = MetricsCollector(
        output_path=args.output,
        interval=args.interval,
        duration=args.duration,
    )
    await collector.run()


if __name__ == "__main__":
    asyncio.run(main())
