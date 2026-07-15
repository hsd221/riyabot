#!/usr/bin/env python3
"""
QQ聊天导出消息注入模拟器 — 读取 QQChatExporter V5 JSON 导出文件，
构造 maim_message 格式消息字典，通过 get_global_api().process_message()
注入完整消息处理流水线，用于 E2E 压力测试。

Usage:
    MAIBOT_WORKER_PROCESS=1 uv run python tests/simulator.py --file tests/data/chat_exports/chat_histories_1.json
    MAIBOT_WORKER_PROCESS=1 uv run python tests/simulator.py --file tests/data/chat_exports/chat_histories_1.json --rate 30 --duration 300
    MAIBOT_WORKER_PROCESS=1 uv run python tests/simulator.py --file tests/data/chat_exports/chat_histories_1.json --burst 10
    MAIBOT_WORKER_PROCESS=1 uv run python tests/simulator.py --file tests/data/chat_exports/chat_histories_2.json --mode private --group-id g_fnat
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
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 环境引导
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("MAIBOT_WORKER_PROCESS", "1")

# ---------------------------------------------------------------------------
# 日志抑制 — 避免模拟器输出被项目日志淹没
# ---------------------------------------------------------------------------
_LOG_SUPPRESSED = False


def _suppress_logging() -> None:
    global _LOG_SUPPRESSED
    if _LOG_SUPPRESSED:
        return
    _LOG_SUPPRESSED = True
    import src.common.logger as mod_logger

    mod_logger._loggers = {}

    class _Quiet:
        def debug(self, *a, **kw):  # noqa: N802
            pass

        def info(self, *a, **kw):  # noqa: N802
            pass

        def warning(self, *a, **kw):  # noqa: N802
            pass

        def error(self, *a, **kw):  # noqa: N802
            pass

        def critical(self, *a, **kw):  # noqa: N802
            pass

    _quiet = _Quiet()
    mod_logger.get_logger = lambda name="", **kwargs: _quiet  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

_REPLY_PREFIX_RE = re.compile(r"\[回复:[^\]]*\]\s*")

# 特殊消息文本 — 无实质内容的文本应被过滤
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

# 附件/卡片标签正则 — 移除内嵌标签如 [图片: xxx.jpg]
_TAG_PATTERN = re.compile(r"\[(?:图片|视频|合并转发|文件|卡片消息|表情):[^\]]*\]")
# 纯表情标签
_EMOJI_TAG = re.compile(r"\[\[?(?:图片|视频|表情|动画表情)\]?\]")


@dataclass
class ParsedMessage:
    """从 QQChatExporter JSON 解析出的单条消息"""

    text: str
    timestamp_ms: int
    sender_uid: str
    sender_name: str
    group_name: Optional[str]
    group_id: Optional[str]


@dataclass
class ChatExport:
    """单个聊天导出文件的元数据和消息列表"""

    file_path: str
    self_uid: str
    self_name: str
    chat_type: str  # "group" or "private"
    group_id: Optional[str]
    group_name: Optional[str]
    messages: list[ParsedMessage] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return len(self.messages)

    @property
    def unique_senders(self) -> set[str]:
        return {m.sender_uid for m in self.messages}


# ---------------------------------------------------------------------------
# 聊天数据加载与清洗
# ---------------------------------------------------------------------------


def _clean_reply_prefix(text: str) -> str:
    """清洗回复前缀，保留实际聊天内容。

    处理格式："[回复 sender: original]\\ncontent" → "content"
    """
    # 移除整行 [回复...] 前缀
    text = _REPLY_PREFIX_RE.sub("", text)
    # 也处理行首的 [回复...]（可能不在单独一行）
    if text.startswith("[回复"):
        idx = text.find("]")
        if idx != -1:
            text = text[idx + 1 :].lstrip("\n").lstrip()
    return text.strip()


def _clean_message_text(raw_text: str) -> Optional[str]:
    """清洗单条消息文本，返回 None 表示应被过滤。"""
    if not raw_text:
        return None
    # 移除内嵌的附件/卡片标签
    cleaned = _TAG_PATTERN.sub("", raw_text)
    cleaned = _EMOJI_TAG.sub("", cleaned)
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    # 纯特殊消息（无实质文本）
    if cleaned in _SPECIAL_TEXTS:
        return None
    # 清洗回复前缀
    cleaned = _clean_reply_prefix(cleaned)
    return cleaned if cleaned else None


def _extract_chat_info(export: dict) -> tuple[str, str, str, Optional[str], Optional[str]]:
    """从导出元数据提取 self_uid, self_name, chat_type, group_id, group_name。

    chat_histories_1: {"chatInfo": {"name": "2023级22班--all_users", "type": "group", ...}}
    chat_histories_2: {"chatInfo": {"name": "FNAT/FNAAT联队聊天群--all_users", "type": "group", ...}}

    Returns (self_uid, self_name, chat_type, group_id, group_name).
    """
    chat_info = export.get("chatInfo", {})
    self_uid = chat_info.get("selfUid", "")
    self_name = chat_info.get("selfName", "hsd221")
    chat_type = chat_info.get("type", "group")
    # 从导出文件名/群名派生 group_id
    full_name: str = chat_info.get("name", "unknown")
    # 取 "--" 之前的部分作为群名
    group_name = full_name.split("--")[0] if "--" in full_name else full_name
    # 用群名的 hash 作为稳定的 group_id
    group_id = f"g_{abs(hash(group_name)) % 10**8}"
    return self_uid, self_name, chat_type, group_id, group_name


def load_chat_export(file_path: str) -> ChatExport:
    """加载并解析单个 QQChatExporter V5 JSON 导出文件。"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"聊天导出文件不存在: {file_path}")

    with open(path, "r", encoding="utf-8", errors="replace") as fp:
        data = json.load(fp)

    self_uid, self_name, chat_type, group_id, group_name = _extract_chat_info(data)
    export = ChatExport(
        file_path=file_path,
        self_uid=self_uid,
        self_name=self_name,
        chat_type=chat_type,
        group_id=group_id,
        group_name=group_name,
    )

    raw_messages: list[dict] = data.get("messages", [])
    skipped = 0
    for msg in raw_messages:
        # 过滤系统消息
        if msg.get("system", False):
            skipped += 1
            continue
        # 过滤被撤回消息
        if msg.get("recalled", False):
            skipped += 1
            continue
        # 提取文本内容
        content = msg.get("content", {})
        raw_text = content.get("text", "")
        if not raw_text:
            skipped += 1
            continue
        # 过滤 bot 自己发的消息
        sender_info = msg.get("sender", {})
        sender_uid = sender_info.get("uid", "")
        sender_name = sender_info.get("name", "unknown")
        if sender_uid == self_uid:
            skipped += 1
            continue
        # 清洗文本
        cleaned = _clean_message_text(raw_text)
        if cleaned is None:
            skipped += 1
            continue

        parsed = ParsedMessage(
            text=cleaned,
            timestamp_ms=msg.get("timestamp", 0),
            sender_uid=sender_uid,
            sender_name=sender_name,
            group_name=group_name,
            group_id=group_id,
        )
        export.messages.append(parsed)

    print(f"[加载] {path.name}: {export.total_count} 条有效消息 ({skipped} 条跳过)")
    return export


# ---------------------------------------------------------------------------
# 消息构造
# ---------------------------------------------------------------------------


def build_message_dict(
    parsed: ParsedMessage,
    mode: str,
    override_group_id: Optional[str] = None,
) -> dict[str, Any]:
    """将 ParsedMessage 转换为 maim_message 兼容的消息字典。

    Args:
        parsed: 解析后的消息
        mode: "group" / "private" / "mixed"
        override_group_id: 覆盖 group_id（用于统一注入到指定群）

    Returns:
        符合 get_global_api().process_message() 格式的 dict
    """
    timestamp_sec = parsed.timestamp_ms / 1000.0
    group_id = override_group_id or parsed.group_id

    message_info: dict[str, Any] = {
        "platform": "qq",
        "message_id": str(uuid.uuid4()),
        "time": timestamp_sec,
        "user_info": {
            "platform": "qq",
            "user_id": parsed.sender_uid,
            "user_nickname": parsed.sender_name,
            "user_cardname": parsed.sender_name,
        },
    }

    if mode == "private":
        # 私聊: 不包含 group_info
        message_info["group_info"] = None
    else:
        # 群聊 / mixed 模式使用群信息
        message_info["group_info"] = {
            "platform": "qq",
            "group_id": group_id or "g_default",
            "group_name": parsed.group_name or "默认群",
        }

    return {
        "message_info": message_info,
        "message_segment": {"type": "text", "data": parsed.text},
        "raw_message": None,
    }


# ---------------------------------------------------------------------------
# 速率控制
# ---------------------------------------------------------------------------


@dataclass
class InjectionStats:
    """注入统计"""

    total: int = 0
    failed: int = 0
    start_time: float = field(default_factory=time.time)
    last_report_time: float = field(default_factory=time.time)
    last_report_count: int = 0

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time

    @property
    def rate(self) -> float:
        if self.elapsed > 0:
            return self.total / (self.elapsed / 60.0)
        return 0.0

    @property
    def current_rate(self) -> float:
        span = time.time() - self.last_report_time
        if span > 0:
            return (self.total - self.last_report_count) / (span / 60.0)
        return 0.0

    def report(self, every: int = 100) -> None:
        """每 every 条打印一次进度报告"""
        if self.total > 0 and self.total % every == 0:
            now = time.time()
            span = now - self.last_report_time
            curr_rate = (self.total - self.last_report_count) / (span / 60.0) if span > 0 else 0.0
            print(
                f"[进度] 已注入 {self.total} 条 | "
                f"当前速率 {curr_rate:.1f} msg/min | "
                f"平均速率 {self.rate:.1f} msg/min | "
                f"耗时 {self.elapsed:.0f}s | "
                f"失败 {self.failed}"
            )
            self.last_report_time = now
            self.last_report_count = self.total


# ---------------------------------------------------------------------------
# 主注入器
# ---------------------------------------------------------------------------

_shutdown_event = asyncio.Event()


def _handle_signal(signum: int, frame: Any) -> None:
    """信号处理：触发优雅关闭"""
    _shutdown_event.set()


class MessageInjector:
    """消息注入器 — 读取聊天导出并以受控速率注入系统。"""

    def __init__(
        self,
        exports: list[ChatExport],
        rate: float = 10.0,
        mode: str = "group",
        burst_size: int = 0,
        override_group_id: Optional[str] = None,
        seed: Optional[int] = None,
        api_url: str = "http://127.0.0.1:8080",
    ):
        self.exports = exports
        self.target_rate = rate
        self.mode = mode
        self.burst_size = burst_size
        self.override_group_id = override_group_id
        self.stats = InjectionStats()
        self.api_url = api_url.rstrip("/")
        self.inject_token = os.environ.get("MAIBOT_INJECT_TOKEN")

        if seed is not None:
            random.seed(seed)

        self.message_pool: list[tuple[ParsedMessage, ChatExport]] = []
        for export in self.exports:
            for msg in export.messages:
                self.message_pool.append((msg, export))

        print(
            f"[初始化] 消息池: {len(self.message_pool)} 条 | "
            f"速率: {rate} msg/min | "
            f"模式: {mode} | "
            f"Burst: {burst_size} | "
            f"API: {self.api_url}/message/inject"
        )

    async def _inject_one(self, parsed: ParsedMessage, export: ChatExport) -> bool:
        """通过 HTTP POST 注入单条消息到 bot 内网 API。"""
        try:
            msg_dict = build_message_dict(
                parsed,
                mode=self.mode,
                override_group_id=self.override_group_id,
            )
            data = json.dumps(msg_dict).encode("utf-8")
            loop = asyncio.get_running_loop()

            def _post():
                import urllib.request

                headers = {"Content-Type": "application/json"}
                if self.inject_token:
                    headers["X-MaiBot-Inject-Token"] = self.inject_token
                req = urllib.request.Request(
                    f"{self.api_url}/message/inject",
                    data=data,
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.read()

            await loop.run_in_executor(None, _post)
            return True
        except Exception:
            print(f"[错误] 注入失败: {parsed.text[:50]}...")
            traceback.print_exc()
            return False

    async def _inject_burst(self) -> None:
        """爆发模式：连续发送 burst_size 条消息（无间隔）。"""
        if not self.message_pool:
            return
        count = min(self.burst_size, len(self.message_pool))
        batch = random.choices(self.message_pool, k=count)
        tasks = [self._inject_one(msg, exp) for msg, exp in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if r is True:
                self.stats.total += 1
            elif isinstance(r, Exception):
                self.stats.failed += 1
            else:
                self.stats.failed += 1 if not r else 0
        self.stats.report(every=100)

    async def _inject_steady(self, duration: float = 0) -> None:
        """稳态注入：按目标速率持续发送消息。

        Args:
            duration: 持续时间（秒），0 表示无限
        """
        if not self.message_pool:
            print("[警告] 消息池为空，无法注入")
            return

        interval = 60.0 / self.target_rate if self.target_rate > 0 else 0
        end_time = time.time() + duration if duration > 0 else float("inf")

        while time.time() < end_time and not _shutdown_event.is_set():
            # 随机选一条消息
            parsed, export = random.choice(self.message_pool)
            ok = await self._inject_one(parsed, export)
            if ok:
                self.stats.total += 1
            else:
                self.stats.failed += 1
            self.stats.report(every=100)

            if _shutdown_event.is_set():
                break
            if interval > 0:
                # 分段 sleep 以便及时响应 shutdown
                sleep_remaining = interval
                while sleep_remaining > 0 and not _shutdown_event.is_set():
                    chunk = min(sleep_remaining, 0.1)
                    await asyncio.sleep(chunk)
                    sleep_remaining -= chunk

    async def run(self, duration: float = 0, warmup_seconds: float = 0) -> InjectionStats:
        """启动注入循环。

        Args:
            duration: 总持续时间（秒），0=无限
            warmup_seconds: 预热阶段持续时间（秒），0=跳过预热
        """
        print(f"[开始] 注入启动 (消息池: {len(self.message_pool)})")

        # 预热阶段
        if warmup_seconds > 0:
            original_rate = self.target_rate
            self.target_rate = min(self.target_rate, 10.0)  # 预热低速
            print(f"[预热] {warmup_seconds}s @ {self.target_rate:.0f} msg/min")
            warmup_end = time.time() + warmup_seconds
            while time.time() < warmup_end and not _shutdown_event.is_set():
                parsed, export = random.choice(self.message_pool)
                ok = await self._inject_one(parsed, export)
                if ok:
                    self.stats.total += 1
                else:
                    self.stats.failed += 1
                interval = 60.0 / self.target_rate
                sleep_remaining = interval
                while sleep_remaining > 0 and not _shutdown_event.is_set():
                    chunk = min(sleep_remaining, 0.1)
                    await asyncio.sleep(chunk)
                    sleep_remaining -= chunk
            self.target_rate = original_rate
            print(f"[预热] 完成 (已注入 {self.stats.total} 条)")

        # 爆发阶段（如果启用了 burst 且 duration 剩余足够）
        if self.burst_size > 0:
            print(f"[爆发] 发送 {self.burst_size} 条突发消息")
            await self._inject_burst()
            if self.burst_size > 0 and not _shutdown_event.is_set():
                # Burst 后短暂停顿以模拟真实场景
                await asyncio.sleep(random.uniform(1.0, 3.0))

        # 稳态注入
        remaining = max(0, duration - (time.time() - self.stats.start_time)) if duration > 0 else 0
        if remaining > 0 or duration == 0:
            print(
                f"[稳态] 注入 @ {self.target_rate:.0f} msg/min"
                + (f" (剩余 {remaining:.0f}s)" if remaining > 0 else " (无限)")
            )
            await self._inject_steady(duration=remaining)

        return self.stats


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="QQ聊天导出消息注入模拟器 — 通过 global_api.process_message() 注入 E2E 流水线",
    )
    parser.add_argument(
        "--file",
        type=str,
        required=True,
        help="聊天导出 JSON 文件路径（支持多次指定: --file a.json --file b.json）",
        action="append",
        dest="files",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=10.0,
        help="目标注入速率（条/分钟），默认 10",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0,
        help="注入持续时间（秒），0=无限，默认 0",
    )
    parser.add_argument(
        "--burst",
        type=int,
        default=0,
        help="爆发模式消息数（在稳态注入前发送），0=禁用，默认 0",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="group",
        choices=["group", "private", "mixed"],
        help="注入模式: group=群聊, private=私聊, mixed=混合，默认 group",
    )
    parser.add_argument(
        "--group-id",
        type=str,
        default=None,
        help="强制覆盖所有消息的 group_id（用于注入到指定群而不带原始群信息）",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="随机种子（复现用）",
    )
    parser.add_argument(
        "--warmup",
        type=float,
        default=10.0,
        help="预热阶段持续时间（秒），默认 10，设为 0 跳过预热",
    )
    parser.add_argument(
        "--no-suppress-log",
        action="store_true",
        help="不抑制项目日志输出",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default="http://127.0.0.1:8080",
        help="bot 内网 API 地址（默认 http://127.0.0.1:8080）",
    )
    return parser.parse_args(argv)


async def amain(argv: Optional[list[str]] = None) -> int:
    """异步主入口"""
    args = parse_args(argv)

    if not args.no_suppress_log:
        _suppress_logging()

    # 加载所有导出文件
    exports: list[ChatExport] = []
    for fp in args.files:
        try:
            export = load_chat_export(fp)
            if export.total_count > 0:
                exports.append(export)
            else:
                print(f"[跳过] {fp}: 无有效消息")
        except Exception as e:
            print(f"[错误] 加载 {fp} 失败: {e}")
            return 1

    if not exports:
        print("[错误] 没有可用的消息源")
        return 1

    total_messages = sum(e.total_count for e in exports)
    total_senders = len(set().union(*[e.unique_senders for e in exports]))
    print(f"[摘要] 共 {len(exports)} 个导出文件 | {total_messages} 条消息 | {total_senders} 个独立发送者")
    for export in exports:
        print(
            f"  ├ {Path(export.file_path).name}: "
            f"{export.total_count} 条, "
            f"{len(export.unique_senders)} 个发送者, "
            f"群: {export.group_name}"
        )

    # 注册信号处理
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # 创建注入器
    injector = MessageInjector(
        exports=exports,
        rate=args.rate,
        mode=args.mode,
        burst_size=args.burst,
        override_group_id=args.group_id,
        seed=args.seed,
        api_url=args.api_url,
    )

    # 运行
    try:
        stats = await injector.run(
            duration=args.duration,
            warmup_seconds=args.warmup,
        )
    except asyncio.CancelledError:
        stats = injector.stats
        print("\n[中断] 注入任务被取消")

    # 打印汇总
    elapsed = stats.elapsed
    print("\n" + "=" * 60)
    print("[汇总] 注入完成")
    print(f"  总注入: {stats.total} 条")
    print(f"  失败:   {stats.failed} 条")
    print(f"  耗时:   {elapsed:.1f}s")
    print(f"  平均速率: {stats.rate:.1f} msg/min ({stats.rate / 60:.2f} msg/s)")
    if stats.total > 0:
        print(f"  成功率:  {((stats.total - stats.failed) / stats.total * 100):.1f}%")
    print("=" * 60)

    return 0 if stats.failed == 0 else 1


def main() -> None:
    """同步入口（供 python tests/simulator.py 调用）"""
    exit_code = asyncio.run(amain())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
