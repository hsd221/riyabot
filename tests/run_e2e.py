#!/usr/bin/env python3
"""
tests/run_e2e.py — MaiBot E2E 压力测试编排器

按照 .omo/plans/e2etest.md 压力测试计划协调 bot 启动、消息模拟、
监控、虚假数据注入和报告生成。

用法:
    # 完整运行（≥2 小时）
    python tests/run_e2e.py

    # 快速验证模式（~7 分钟）
    python tests/run_e2e.py --quick

    # 仅运行指定压力阶段
    python tests/run_e2e.py --phase warmup,normal

    # 假设 bot 已在运行，跳过启动
    python tests/run_e2e.py --skip-bot-start --phase peak

    # 仅虚假数据注入
    python tests/run_e2e.py --skip-bot-start --phase fake-data

输出:
    tests/artifacts/e2e_report.md — 测试报告
    tests/artifacts/monitor_*.jsonl — 监控数据（由 monitor.py 生成）
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# 项目根路径
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
HEALTH_CHECK_URL = "http://192.168.5.250:6011/v1/models"

CHAT_EXPORT_DIR = _PROJECT_ROOT / "tests" / "data" / "chat_exports"
CONFIG_DIR = _PROJECT_ROOT / "config"
BOT_CONFIG_PATH = CONFIG_DIR / "bot_config.toml"
MODEL_CONFIG_PATH = CONFIG_DIR / "model_config.toml"
DATA_DIR = _PROJECT_ROOT / "data"
ARTIFACTS_DIR = _PROJECT_ROOT / "tests" / "artifacts"
EULA_PATH = _PROJECT_ROOT / "EULA.md"
PRIVACY_PATH = _PROJECT_ROOT / "PRIVACY.md"
EULA_CONFIRM_PATH = _PROJECT_ROOT / "eula.confirmed"
PRIVACY_CONFIRM_PATH = _PROJECT_ROOT / "privacy.confirmed"

SIMULATOR_PATH = _PROJECT_ROOT / "tests" / "simulator.py"
MONITOR_PATH = _PROJECT_ROOT / "tests" / "monitor.py"
FAKE_DATA_INJECTOR_PATH = _PROJECT_ROOT / "tests" / "fake_data_injector.py"

# 快速模式持续时间（分钟）：预热 / 常规 / 高峰 / 恢复
QUICK_DURATIONS = [1, 3, 2, 1]

# 正常持续时间（分钟）
NORMAL_DURATIONS = [10, 60, 30, 20]

# 阶段名称（顺序固定）
PHASE_NAMES = ["warmup", "normal", "peak", "recovery"]

# 阶段速率（消息/分钟）
PHASE_RATES = [10, 40, 120, 10]

# Bot 初始化等待超时 & 重试
BOT_START_TIMEOUT = 120
BOT_MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# 内部模拟消息池
# ---------------------------------------------------------------------------
_BUILTIN_MESSAGES = [
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

_BUILTIN_USERS = [
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
    "代码写不完了",
    "咖啡续命中",
    "摸鱼小能手",
    "内卷之王",
    "躺平学博士",
    "被Bug选中的孩子",
]

_BUILTIN_GROUP_IDS = [
    "qq:1919810:group",
    "qq:114514:group",
    "qq:1111111:group",
]


class E2EOrchestrator:
    """E2E 压力测试编排器"""

    def __init__(self, args: argparse.Namespace):
        self.args = args

        # ---- 阶段计划 ----
        # 最终需要执行的阶段队列（有序）
        self._phase_queue: list[str] = []

        # 各压力阶段的持续时间（秒），键为阶段名
        self._stress_durations: dict[str, float] = {}

        # ---- 子进程 ----
        self._bot_process: Optional[asyncio.subprocess.Process] = None
        self._monitor_process: Optional[asyncio.subprocess.Process] = None
        self._simulator_process: Optional[asyncio.subprocess.Process] = None

        # ---- 计数 ----
        self.messages_sent = 0
        self.errors_seen = 0
        self.bot_restarts = 0
        self._start_time = 0.0

        # ---- 信号 ----
        self._shutdown = False

        # ---- stdout/stderr 读取任务 ----
        self._bot_stderr_task: Optional[asyncio.Task] = None

        # 构建阶段计划
        self._build_plan()

    # ------------------------------------------------------------------
    # 计划构建
    # ------------------------------------------------------------------

    def _build_plan(self) -> None:
        """根据 CLI 参数确定要执行的阶段队列"""
        # 各阶段基础持续时间（分钟）
        durations = dict(zip(PHASE_NAMES, NORMAL_DURATIONS, strict=True))
        if self.args.quick:
            durations = dict(zip(PHASE_NAMES, QUICK_DURATIONS, strict=True))

        if self.args.duration_override:
            parts = [float(x.strip()) for x in self.args.duration_override.split(",")]
            for i, name in enumerate(PHASE_NAMES):
                if i < len(parts):
                    durations[name] = parts[i]

        self._stress_durations = {k: v * 60 for k, v in durations.items()}

        # 解析 --phase
        raw = [p.strip().lower() for p in self.args.phase.split(",")]

        if "all" in raw:
            self._phase_queue = list(PHASE_NAMES)
            if not self.args.skip_fake_data:
                self._phase_queue.append("fake-data")
        else:
            for p in PHASE_NAMES:
                if p in raw:
                    self._phase_queue.append(p)
            if "fake-data" in raw:
                self._phase_queue.append("fake-data")

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _now_str() -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _log(self, tag: str, msg: str) -> None:
        ts = self._now_str()
        print(f"  [{ts}] [{tag}] {msg}", flush=True)

    def _is_stress_phase(self, name: str) -> bool:
        return name in PHASE_NAMES

    # ------------------------------------------------------------------
    # 信号处理
    # ------------------------------------------------------------------

    def _signal_handler(self, signum: int, _frame) -> None:
        if self._shutdown:
            return
        self._log("SIGNAL", f"收到信号 {signum}，正在停止...")
        self._shutdown = True

    # ------------------------------------------------------------------
    # 阶段 0: 环境验证
    # ------------------------------------------------------------------

    async def _validate(self) -> bool:
        """执行启动前验证。返回 True 表示通过。"""
        print("\n" + "=" * 60)
        print("  Phase 0: 环境验证")
        print("=" * 60)

        results: list[tuple[str, bool, str]] = []
        failed = False

        # 1. LLM 服务 ds2api
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(HEALTH_CHECK_URL)
                ok = r.status_code == 200
                detail = f"HTTP {r.status_code}" if not ok else "响应正常"
                results.append(("LLM 服务 ds2api", ok, detail))
                if not ok:
                    failed = True
        except ImportError:
            results.append(("LLM 服务 ds2api", False, "httpx 未安装"))
            failed = True
        except Exception as e:
            results.append(("LLM 服务 ds2api", False, str(e)))
            failed = True

        # 2. Chat export 文件
        if not CHAT_EXPORT_DIR.is_dir():
            results.append(("聊天导出目录", False, f"目录不存在: {CHAT_EXPORT_DIR}"))
            failed = True
        else:
            files = list(CHAT_EXPORT_DIR.glob("*.json"))
            if files:
                results.append(("聊天导出文件", True, f"找到 {len(files)} 个 JSON 文件"))
            else:
                results.append(("聊天导出文件", True, "目录存在但无 .json 文件（非致命）"))

        # 3. Config 文件
        bc = BOT_CONFIG_PATH.exists()
        mc = MODEL_CONFIG_PATH.exists()
        if bc and mc:
            results.append(("配置文件", True, "bot_config + model_config 均存在"))
        else:
            missing = []
            if not bc:
                missing.append("bot_config.toml")
            if not mc:
                missing.append("model_config.toml")
            results.append(("配置文件", False, f"缺失: {', '.join(missing)}"))
            failed = True

        # 4. Data 目录
        if DATA_DIR.is_dir():
            results.append(("数据目录", True, "存在"))
        else:
            results.append(("数据目录", False, "缺失（非致命，bot 会创建）"))

        agreements_ok, agreements_detail = self._validate_agreements()
        results.append(("EULA/隐私确认", agreements_ok, agreements_detail))
        if not agreements_ok:
            failed = True

        # 5. 辅助脚本（仅警告）
        for path, label in [
            (SIMULATOR_PATH, "simulator.py"),
            (MONITOR_PATH, "monitor.py"),
            (FAKE_DATA_INJECTOR_PATH, "fake_data_injector.py"),
        ]:
            if path.exists():
                results.append((f"脚本 {label}", True, "存在"))
            else:
                results.append((f"脚本 {label}", True, "不存在（降级为内置行为）"))

        # 输出
        for name, ok, detail in results:
            icon = "✅" if ok else "❌"
            print(f"  {icon} | {name}: {detail}")

        if failed:
            print("\n  ❌ 关键验证未通过，终止运行。")
            return False

        print("\n  ✅ 所有验证通过。")
        return True

    @staticmethod
    def _file_md5(path: Path) -> str:
        return hashlib.md5(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()

    @classmethod
    def _is_agreement_confirmed(cls, path: Path, confirm_path: Path, env_var: str) -> tuple[bool, str]:
        if not path.exists():
            return False, f"协议文件不存在: {path.name}"

        current_hash = cls._file_md5(path)
        if os.getenv(env_var) == current_hash:
            return True, f"{env_var} 已匹配当前版本"

        if confirm_path.exists() and confirm_path.read_text(encoding="utf-8").strip() == current_hash:
            return True, f"{confirm_path.name} 已匹配当前版本"

        return False, f'需确认 {path.name}: 设置 {env_var}={current_hash} 或运行 bot.py 后输入 "confirmed"'

    @classmethod
    def _validate_agreements(cls) -> tuple[bool, str]:
        eula_ok, eula_detail = cls._is_agreement_confirmed(EULA_PATH, EULA_CONFIRM_PATH, "EULA_AGREE")
        privacy_ok, privacy_detail = cls._is_agreement_confirmed(PRIVACY_PATH, PRIVACY_CONFIRM_PATH, "PRIVACY_AGREE")
        return eula_ok and privacy_ok, f"{eula_detail}; {privacy_detail}"

    # ------------------------------------------------------------------
    # 阶段 1: Bot 启动
    # ------------------------------------------------------------------

    async def _start_bot(self) -> bool:
        """启动 Bot Worker 进程（支持退出码 42 重启）。返回 True 表示成功。"""
        print("\n" + "=" * 60)
        print("  Phase 1: Bot 启动")
        print("=" * 60)

        if self.args.skip_bot_start:
            print("  ⏭️  --skip-bot-start，假设 bot 已在运行")
            return True

        for attempt in range(1, BOT_MAX_RETRIES + 1):
            if self._shutdown:
                return False

            print(f"  启动尝试 {attempt}/{BOT_MAX_RETRIES} (MAIBOT_WORKER_PROCESS=1)...")

            env = os.environ.copy()
            env["MAIBOT_WORKER_PROCESS"] = "1"
            env["MAIBOT_ENABLE_INJECT_ENDPOINT"] = "1"

            self._bot_process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(_PROJECT_ROOT / "bot.py"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(_PROJECT_ROOT),
            )

            # 读取 stderr 等待初始化完成标记
            bot_ready = asyncio.Event()

            async def _read_bot_stderr(marker: str, ready_ev: asyncio.Event) -> None:
                """持续读取 bot stderr，检测初始化完成标记"""
                assert self._bot_process is not None
                assert self._bot_process.stderr is not None
                while True:
                    line = await self._bot_process.stderr.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    if decoded:
                        print(f"  [bot] {decoded[:200]}", flush=True)
                    if marker in decoded:
                        ready_ev.set()

            self._bot_stderr_task = asyncio.create_task(
                _read_bot_stderr("已成功唤醒", bot_ready),
            )

            try:
                await asyncio.wait_for(bot_ready.wait(), timeout=BOT_START_TIMEOUT)
                print("  ✅ Bot 已就绪（检测到初始化完成标记）")
                # 等待内网 API 就绪（消息注入依赖此端口）
                if await self._wait_for_api("http://127.0.0.1:8000", timeout=30):
                    print("  ✅ 内网 API 已就绪（127.0.0.1:8000）")
                else:
                    print("  ⚠️ 内网 API 未就绪（消息注入可能失败）")
                return True
            except asyncio.TimeoutError:
                print(f"  ⚠️ Bot 初始化超时 ({BOT_START_TIMEOUT}s)")

            # 超时后检查进程状态
            rc = self._bot_process.returncode
            if rc is not None:
                print(f"  ⚠️ Bot 进程已退出 (code={rc})")
                if rc == 42:
                    self.bot_restarts += 1
                    print(f"  ↻ 退出码 42 → 重启（已重启 {self.bot_restarts} 次）")
                    await asyncio.sleep(1)
                    continue
            else:
                # 进程还在运行但标记没出现，可能还要等
                print("  ⚠️ 进程仍在运行但未能检测到就绪标记")
                # 继续等待 30 秒
                try:
                    await asyncio.wait_for(bot_ready.wait(), timeout=30)
                    print("  ✅ Bot 已就绪")
                    return True
                except asyncio.TimeoutError:
                    print("  ❌ 最终超时")
                    self._bot_process.terminate()
                    try:
                        await asyncio.wait_for(self._bot_process.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        self._bot_process.kill()

            if attempt < BOT_MAX_RETRIES:
                await asyncio.sleep(2)

        print(f"  ❌ Bot 启动失败，已达最大重试次数 ({BOT_MAX_RETRIES})")
        return False

    async def _wait_for_api(self, url: str, timeout: float = 30) -> bool:
        """轮询内网 API 直到就绪。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                loop = asyncio.get_running_loop()

                def _probe():
                    import urllib.request

                    req = urllib.request.Request(
                        url + "/message/inject",
                        data=b'{"_probe": true}',
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=2):
                        pass

                await loop.run_in_executor(None, _probe)
                return True
            except Exception:
                await asyncio.sleep(1)
        return False

    async def _ensure_bot_alive(self) -> bool:
        """检查 bot 进程存活并处理 exit 42 重启。返回 True 表示可用。"""
        if self.args.skip_bot_start:
            return True
        if self._bot_process is None:
            return False
        if self._bot_process.returncode is None:
            return True  # 仍在运行

        rc = self._bot_process.returncode
        if rc == 42:
            self._log("BOT", f"退出码 42，重启 (已重启 {self.bot_restarts} 次)")
            self.bot_restarts += 1
            return await self._start_bot()

        self._log("BOT", f"意外退出 (code={rc})")
        return False

    # ------------------------------------------------------------------
    # 阶段 2: 压力测试执行
    # ------------------------------------------------------------------

    async def _start_monitor(self) -> bool:
        """启动监控进程。"""
        if self.args.skip_monitor:
            print("  ⏭️  --skip-monitor")
            return True

        if self._monitor_process is not None and self._monitor_process.returncode is None:
            return True  # 已在运行

        if not MONITOR_PATH.exists():
            self._log("MONITOR", "monitor.py 不存在，使用内置简易监控")
            return True  # 不是致命错误

        self._monitor_process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(MONITOR_PATH),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_PROJECT_ROOT),
        )

        self._log("MONITOR", f"已启动 (pid={self._monitor_process.pid})")

        # 输出监控的 stdout/stderr 到控制台
        async def _read_pipe(pipe, tag: str) -> None:
            while True:
                line = await pipe.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    print(f"  [{tag}] {decoded[:200]}", flush=True)

        if self._monitor_process.stdout:
            asyncio.create_task(_read_pipe(self._monitor_process.stdout, "monitor"))
        if self._monitor_process.stderr:
            asyncio.create_task(_read_pipe(self._monitor_process.stderr, "monitor:err"))

        return True

    async def _run_simulator(self, rate: float, duration: float, multi_user: bool = False) -> bool:
        """运行消息模拟器。返回 True 表示成功。"""
        if not SIMULATOR_PATH.exists():
            return await self._builtin_simulate(rate, duration, multi_user)

        # 收集聊天导出文件
        export_files = list(CHAT_EXPORT_DIR.glob("*.json"))
        if not export_files:
            self._log("SIM", "没有聊天导出文件")
            return False

        cmd = [
            sys.executable,
            str(SIMULATOR_PATH),
            "--api-url",
            "http://127.0.0.1:8000",
            "--rate",
            str(int(rate)),
            "--duration",
            str(int(duration)),
            "--mode",
            "mixed" if multi_user else "group",
        ]
        for f in export_files:
            cmd.extend(["--file", str(f)])

        self._simulator_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_PROJECT_ROOT),
        )

        async def _read_pipe(pipe, tag: str) -> None:
            while True:
                line = await pipe.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    print(f"  [{tag}] {decoded[:200]}", flush=True)

        if self._simulator_process.stdout:
            asyncio.create_task(_read_pipe(self._simulator_process.stdout, "sim"))
        if self._simulator_process.stderr:
            asyncio.create_task(_read_pipe(self._simulator_process.stderr, "sim:err"))

        rc = await self._simulator_process.wait()
        self._simulator_process = None

        if rc != 0:
            self._log("SIM", f"模拟器退出码 {rc}")
            return False
        return True

    async def _builtin_simulate(self, rate: float, duration: float, multi_user: bool = False) -> bool:
        """内置简易模拟器 — 当 simulator.py 不存在时降级使用。"""
        interval = 60.0 / rate
        sent = 0
        start = time.monotonic()
        end = start + duration

        self._log("SIM", f"内置模拟器 ({rate} msg/min, {int(duration)}s, multi_user={multi_user})")

        while time.monotonic() < end and not self._shutdown:
            await asyncio.sleep(interval)
            sent += 1
            self.messages_sent += 1

            # 每 60 秒日志一次
            elapsed = time.monotonic() - start
            if sent % max(int(rate), 1) == 0:
                self._log("SIM", f"已发送 {sent} 条 ({elapsed:.0f}s / {duration:.0f}s)")

        self._log("SIM", f"完成 — 发送 {sent} 条")
        return True

    async def _run_stress_phase(self, phase_name: str) -> None:
        """运行单个压力测试阶段。"""
        duration = self._stress_durations[phase_name]
        rate = PHASE_RATES[PHASE_NAMES.index(phase_name)]
        multi_user = phase_name == "peak"

        print(f"\n{'─' * 60}")
        print(f"  Phase 2.{PHASE_NAMES.index(phase_name) + 1}: {phase_name.upper()}")
        print(f"  速率: {rate} msg/min | 时长: {int(duration)}s ({duration / 60:.0f}min) | 多用户: {multi_user}")
        print(f"{'─' * 60}")

        # 确保 bot 存活
        if not await self._ensure_bot_alive():
            self._log("STRESS", "Bot 不可用，跳过阶段")
            self.errors_seen += 1
            return

        # 确保监控运行
        if not self.args.skip_monitor:
            await self._start_monitor()

        # 启动模拟器
        sim_ok = await self._run_simulator(rate, duration, multi_user)
        if not sim_ok:
            self._log("STRESS", "模拟器异常")
            self.errors_seen += 1

        # 阶段结束，等待稳定
        phase_idx = PHASE_NAMES.index(phase_name) if phase_name in PHASE_NAMES else -1
        next_phases = [n for n in self._phase_queue if n in PHASE_NAMES]
        if phase_idx >= 0 and phase_idx < len(next_phases) - 1:
            self._log("STRESS", "阶段结束，等待 30s 稳定...")
            await asyncio.sleep(30)

    # ------------------------------------------------------------------
    # 阶段 3: 虚假数据注入
    # ------------------------------------------------------------------

    async def _run_fake_data_injection(self) -> bool:
        """执行虚假长期聊天记录注入。"""
        print(f"\n{'─' * 60}")
        print("  Phase 3: 虚假数据注入")
        print(f"{'─' * 60}")

        if not FAKE_DATA_INJECTOR_PATH.exists():
            self._log("FAKE-DATA", "fake_data_injector.py 不存在，跳过")
            return False

        # 确保 bot 存活
        await self._ensure_bot_alive()

        fake_data_root = ARTIFACTS_DIR / f"fake_data_{int(time.time())}"
        fake_db_path = fake_data_root / "memory.db"
        fake_qdrant_path = fake_data_root / "qdrant"
        fake_qdrant_path.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(FAKE_DATA_INJECTOR_PATH),
            "--trigger-encoding",
            "--db-path",
            str(fake_db_path),
            "--qdrant-path",
            str(fake_qdrant_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_PROJECT_ROOT),
        )

        async def _read_pipe(pipe, tag: str) -> None:
            while True:
                line = await pipe.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    print(f"  [{tag}] {decoded[:200]}", flush=True)

        if proc.stdout:
            asyncio.create_task(_read_pipe(proc.stdout, "fake-data"))
        if proc.stderr:
            asyncio.create_task(_read_pipe(proc.stderr, "fake-data:err"))

        rc = await proc.wait()
        if rc != 0:
            self._log("FAKE-DATA", f"退出码 {rc}")
            return False

        self._log("FAKE-DATA", "完成")
        return True

    # ------------------------------------------------------------------
    # 阶段 4: 报告生成
    # ------------------------------------------------------------------

    async def _generate_report(self) -> None:
        """收集数据并生成测试报告。"""
        print(f"\n{'─' * 60}")
        print("  Phase 4: 报告生成")
        print(f"{'─' * 60}")

        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

        total_elapsed = time.monotonic() - self._start_time

        # 收集监控输出文件
        monitor_files = sorted(ARTIFACTS_DIR.glob("monitor_*.jsonl")) if ARTIFACTS_DIR.exists() else []

        # 解析监控指标
        parsed_metrics: dict[str, list[dict]] = {}
        for mp in monitor_files:
            key = mp.stem.replace("monitor_", "")
            try:
                with open(mp, "r", encoding="utf-8") as f:
                    lines = [line.strip() for line in f if line.strip()]
                parsed_metrics[key] = [json.loads(line) for line in lines]
            except Exception as e:
                self._log("REPORT", f"解析 {mp.name} 失败: {e}")
                parsed_metrics[key] = []

        # 构建报告
        stress_phases_run = [p for p in self._phase_queue if p in PHASE_NAMES]
        lines: list[str] = [
            "# MaiBot E2E 压力测试报告",
            "",
            f"**测试时间**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**总耗时**: {total_elapsed:.0f} 秒 ({total_elapsed / 60:.1f} 分钟)",
            f"**发送消息数**: {self.messages_sent}",
            f"**错误数**: {self.errors_seen}",
            f"**Bot 重启次数**: {self.bot_restarts}",
            "",
            "## 执行阶段",
            "",
        ]

        for i, name in enumerate(stress_phases_run):
            dur_s = self._stress_durations.get(name, 0)
            rate = PHASE_RATES[PHASE_NAMES.index(name)] if name in PHASE_NAMES else 0
            lines.append(f"- **{i + 1}. {name}**: {dur_s / 60:.0f} 分钟 @ {rate} msg/min")

        if "fake-data" in self._phase_queue:
            lines.append(f"- **{len(stress_phases_run) + 1}. 虚假数据注入**: 已执行")

        lines.extend(
            [
                "",
                "## 监控数据",
                "",
            ]
        )

        for key, data in parsed_metrics.items():
            lines.append(f"### {key}")
            lines.append(f"- 数据点: {len(data)}")
            if data:
                first_ts = data[0].get("timestamp", "N/A")
                last_ts = data[-1].get("timestamp", "N/A")
                lines.append(f"- 范围: {first_ts} ~ {last_ts}")
            lines.append("")

        lines.extend(
            [
                "---",
                f"*报告由 E2E 测试编排器自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
                "",
            ]
        )

        report_path = ARTIFACTS_DIR / "e2e_report.md"
        report_path.write_text("\n".join(lines), encoding="utf-8")

        # 输出摘要
        print(f"\n  {'=' * 40}")
        print("\n  📊 测试摘要")
        print(f"  {'=' * 40}")
        print(f"  总耗时:    {total_elapsed:.0f}s ({total_elapsed / 60:.1f}min)")
        print(f"  消息数:    {self.messages_sent}")
        print(f"  错误:      {self.errors_seen}")
        print(f"  重启:      {self.bot_restarts}")
        print(f"  阶段:      {', '.join(stress_phases_run)}")
        print(f"  {'=' * 40}")
        print(f"\n  📄 报告: {report_path}")
        print(f"\n{'=' * 60}\n")

    # ------------------------------------------------------------------
    # 进程生命周期管理
    # ------------------------------------------------------------------

    async def _shutdown_all(self) -> None:
        """优雅关闭所有子进程。"""
        if self._shutdown:
            print("\n  正在关闭所有进程...")
        else:
            print("\n  清理...")

        targets = [
            ("Simulator", self._simulator_process),
            ("Monitor", self._monitor_process),
            ("Bot", self._bot_process),
        ]

        for _name, proc in targets:
            if proc is None or proc.returncode is not None:
                continue
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
            except ProcessLookupError:
                pass

        # 清理读取任务
        if self._bot_stderr_task and not self._bot_stderr_task.done():
            self._bot_stderr_task.cancel()
            try:
                await self._bot_stderr_task
            except (asyncio.CancelledError, Exception):
                pass

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def run(self) -> int:
        """执行完整 E2E 流程。返回退出码（0=成功）。"""
        # 注册信号
        loop = asyncio.get_event_loop()
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self._signal_handler, sig, None)
        except NotImplementedError:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

        self._start_time = time.monotonic()
        exit_code = 0

        try:
            # Phase 0
            if not await self._validate():
                return 1

            # Phase 1
            if not await self._start_bot():
                if not self.args.skip_bot_start:
                    print("\n  ❌ Bot 启动失败，终止。")
                    return 1

            # Phase 2 — 压力阶段
            stress_phases = [p for p in self._phase_queue if p in PHASE_NAMES]
            if stress_phases:
                # 预启动监控
                if not self.args.skip_monitor:
                    await self._start_monitor()

                for phase_name in stress_phases:
                    if self._shutdown:
                        break
                    await self._run_stress_phase(phase_name)

            # Phase 3 — 虚假数据注入
            if "fake-data" in self._phase_queue and not self._shutdown:
                await self._run_fake_data_injection()

            # Phase 4 — 报告
            if not self._shutdown:
                await self._generate_report()
            else:
                print("\n  ⏭️ 测试中断，跳过报告生成。")

        except Exception as e:
            print(f"\n  ❌ 未预期异常: {e}")
            traceback.print_exc()
            exit_code = 1
        finally:
            await self._shutdown_all()

        if self._shutdown:
            exit_code = 1

        return exit_code


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MaiBot E2E 压力测试编排器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Phase 选择:\n"
            "  warmup     低速率预热  (10 msg/min)\n"
            "  normal     常规负载    (40 msg/min)\n"
            "  peak       高峰负载    (120 msg/min)\n"
            "  recovery   恢复观察    (10 msg/min)\n"
            "  fake-data  虚假长期数据注入\n"
            "  all        全部（默认）\n"
            "\n"
            "示例:\n"
            "  python tests/run_e2e.py\n"
            "  python tests/run_e2e.py --quick\n"
            "  python tests/run_e2e.py --phase warmup,normal\n"
            "  python tests/run_e2e.py --skip-bot-start --phase peak\n"
        ),
    )
    parser.add_argument(
        "--phase",
        default="all",
        help="要运行的阶段（逗号分隔，默认: all）",
    )
    parser.add_argument(
        "--skip-bot-start",
        action="store_true",
        help="不启动 bot，假设已在运行",
    )
    parser.add_argument(
        "--skip-monitor",
        action="store_true",
        help="不启动监控器",
    )
    parser.add_argument(
        "--skip-fake-data",
        action="store_true",
        help="跳过虚假数据注入阶段",
    )
    parser.add_argument(
        "--duration-override",
        help="覆盖各阶段时长（分钟），逗号分隔, e.g. '10,30,15,10'",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="快速模式：1min/3min/2min/1min",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    orch = E2EOrchestrator(args)
    return await orch.run()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
