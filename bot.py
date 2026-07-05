import asyncio
import os
import time
import platform
import shutil
import sys
import subprocess
from dotenv import load_dotenv
from pathlib import Path
from rich.traceback import install
from src.common.logger import initialize_logging, get_logger, shutdown_logging

# 设置工作目录为脚本所在目录
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

env_path = Path(__file__).parent / ".env"
template_env_path = Path(__file__).parent / "template" / "template.env"

if env_path.exists():
    load_dotenv(str(env_path), override=True)
else:
    try:
        if template_env_path.exists():
            shutil.copyfile(template_env_path, env_path)
            print("未找到.env，已从 template/template.env 自动创建")
            load_dotenv(str(env_path), override=True)
        else:
            print("未找到.env文件，也未找到模板 template/template.env")
            raise FileNotFoundError(".env 文件不存在，请创建并配置所需的环境变量")
    except Exception as e:
        print(f"自动创建 .env 失败: {e}")
        raise

# 检查是否是 Worker 进程，只在 Worker 进程中输出详细的初始化信息
# Runner 进程只需要基本的日志功能，不需要详细的初始化日志
is_worker = os.environ.get("MAIBOT_WORKER_PROCESS") == "1"
initialize_logging(verbose=is_worker)
install(extra_lines=3)
logger = get_logger("main")

# 定义重启退出码
RESTART_EXIT_CODE = 42


def run_runner_process():
    """
    Runner 进程逻辑：作为守护进程运行，负责启动和监控 Worker 进程。
    处理重启请求 (退出码 42) 和 Ctrl+C 信号。
    """
    script_file = sys.argv[0]
    python_executable = sys.executable

    # 设置环境变量，标记子进程为 Worker 进程
    env = os.environ.copy()
    env["MAIBOT_WORKER_PROCESS"] = "1"

    while True:
        # 启动子进程 (Worker)
        # 使用 sys.executable 确保使用相同的 Python 解释器
        cmd = [python_executable, script_file] + sys.argv[1:]
        logger.info(
            "Worker 进程启动",
            event_code="runner.worker.start",
            script_file=script_file,
            python_executable=python_executable,
            argv_count=len(sys.argv),
        )

        process = subprocess.Popen(cmd, env=env)

        try:
            # 等待子进程结束
            return_code = process.wait()

            if return_code == RESTART_EXIT_CODE:
                logger.info("Worker 请求重启", event_code="runner.worker.restart_requested", exit_code=return_code)
                time.sleep(1)  # 稍作等待
                continue
            else:
                logger.info("Worker 进程退出", event_code="runner.worker.exited", exit_code=return_code)
                sys.exit(return_code)

        except KeyboardInterrupt:
            # 向子进程发送终止信号
            if process.poll() is None:
                # 在 Windows 上，Ctrl+C 通常已经发送给了子进程（如果它们共享控制台）
                # 但为了保险，我们可以尝试 terminate
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning("Worker 进程停止超时，执行强制终止", event_code="runner.worker.kill_timeout")
                    process.kill()
            sys.exit(0)


# 检查是否是 Worker 进程
# 如果没有设置 MAIBOT_WORKER_PROCESS 环境变量，说明是直接运行的脚本，
# 此时应该作为 Runner 运行。
if os.environ.get("MAIBOT_WORKER_PROCESS") != "1":
    if __name__ == "__main__":
        run_runner_process()
    # 如果作为模块导入，不执行 Runner 逻辑，但也不应该执行下面的 Worker 逻辑
    sys.exit(0)

# 以下是 Worker 进程的逻辑

# 最早期初始化日志系统，确保所有后续模块都使用正确的日志格式
# 注意：Runner 进程已经在第 37 行初始化了日志系统，但 Worker 进程是独立进程，需要重新初始化
# 由于 Runner 和 Worker 是不同进程，它们有独立的内存空间，所以都会初始化一次
# 这是正常的，但为了避免重复的初始化日志，我们在 initialize_logging() 中添加了防重复机制
# 不过由于是不同进程，每个进程仍会初始化一次，这是预期的行为

from src.main import MainSystem  # noqa
from src.manager.async_task_manager import async_task_manager  # noqa


# logger = get_logger("main")


# install(extra_lines=3)

# 设置工作目录为脚本所在目录
# script_dir = os.path.dirname(os.path.abspath(__file__))
# os.chdir(script_dir)
logger.info("工作目录已设置", event_code="app.workdir.set", workdir=script_dir)


confirm_logger = get_logger("confirm")
# 获取没有加载env时的环境变量
env_mask = {key: os.getenv(key) for key in os.environ}

uvicorn_server = None
driver = None
app = None
loop = None


def print_opensource_notice():
    """打印开源项目提示，防止倒卖"""
    from colorama import init, Fore, Style

    init()

    notice_lines = [
        "",
        f"{Fore.CYAN}{'═' * 70}{Style.RESET_ALL}",
        f"{Fore.GREEN}  ★ RiyaBot / 璃夜Bot - 开源 AI 聊天机器人 ★{Style.RESET_ALL}",
        f"{Fore.CYAN}{'─' * 70}{Style.RESET_ALL}",
        f"{Fore.YELLOW}  本项目是完全免费的开源软件，基于 GPL-3.0 协议发布{Style.RESET_ALL}",
        f"{Fore.WHITE}  如果有人向你「出售本软件」，你被骗了！{Style.RESET_ALL}",
        "",
        f"{Fore.WHITE}  官方仓库: {Fore.BLUE}https://github.com/hsd221/riyabot {Style.RESET_ALL}",
        f"{Fore.WHITE}  项目文档: {Fore.BLUE}https://github.com/hsd221/riyabot#readme {Style.RESET_ALL}",
        f"{Fore.CYAN}{'─' * 70}{Style.RESET_ALL}",
        f"{Fore.RED}  ⚠ 将本软件作为「商品」倒卖、隐瞒开源性质均违反协议！{Style.RESET_ALL}",
        f"{Fore.CYAN}{'═' * 70}{Style.RESET_ALL}",
        "",
    ]

    for line in notice_lines:
        print(line)


def easter_egg():
    # 彩蛋
    from colorama import init, Fore

    init()
    text = "多年以后，面对AI行刑队，张三将会回想起他2023年在会议上讨论人工智能的那个下午"
    rainbow_colors = [Fore.RED, Fore.YELLOW, Fore.GREEN, Fore.CYAN, Fore.BLUE, Fore.MAGENTA]
    rainbow_text = ""
    for i, char in enumerate(text):
        rainbow_text += rainbow_colors[i % len(rainbow_colors)] + char
    print(rainbow_text)


async def graceful_shutdown():  # sourcery skip: use-named-expression
    try:
        logger.info("应用开始关闭", event_code="app.shutdown.started")

        # 关闭 WebUI 服务器
        try:
            from src.webui.webui_server import get_webui_server

            webui_server = get_webui_server()
            if webui_server and webui_server._server:
                await webui_server.shutdown()
        except Exception as e:
            logger.warning("WebUI 服务器关闭失败，继续关闭流程", event_code="app.shutdown.webui_failed", error=str(e))

        from src.plugin_system.core.events_manager import events_manager
        from src.plugin_system.base.component_types import EventType

        # 触发 ON_STOP 事件
        await events_manager.handle_mai_events(event_type=EventType.ON_STOP)

        # 停止所有异步任务
        await async_task_manager.stop_and_wait_all_tasks()

        # 获取所有剩余任务，排除当前任务
        remaining_tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

        if remaining_tasks:
            logger.info("剩余异步任务开始取消", event_code="app.shutdown.cancel_tasks", count=len(remaining_tasks))

            # 取消所有剩余任务
            for task in remaining_tasks:
                if not task.done():
                    task.cancel()

            # 等待所有任务完成，设置超时
            try:
                await asyncio.wait_for(asyncio.gather(*remaining_tasks, return_exceptions=True), timeout=15.0)
                logger.info("剩余异步任务已取消", event_code="app.shutdown.tasks_cancelled", count=len(remaining_tasks))
            except asyncio.TimeoutError:
                logger.warning(
                    "等待异步任务取消超时", event_code="app.shutdown.task_cancel_timeout", timeout_seconds=15.0
                )
            except Exception:
                logger.exception("等待异步任务取消失败", event_code="app.shutdown.task_cancel_failed")

        logger.info("应用关闭完成", event_code="app.shutdown.completed")

    except Exception:
        logger.exception("应用关闭失败", event_code="app.shutdown.failed")


def check_eula() -> bool:
    """检查EULA和隐私条款确认状态"""
    from src.common.agreement import get_agreement_status

    agreement_status = get_agreement_status(include_content=False)
    pending_agreements = [document.title for document in agreement_status.values() if not document.confirmed]

    if not pending_agreements:
        return True

    confirm_logger.warning(
        "EULA或隐私条款尚未确认，已交由 WebUI 首次配置向导处理",
        event_code="agreement.webui_confirmation_required",
        pending=pending_agreements,
        eula_hash=agreement_status["eula"].hash,
        privacy_hash=agreement_status["privacy"].hash,
    )
    return False


def raw_main():
    # 利用 TZ 环境变量设定程序工作的时区
    if platform.system().lower() != "windows":
        time.tzset()  # type: ignore

    # 打印开源提示（防止倒卖）
    print_opensource_notice()

    agreements_confirmed = check_eula()
    logger.info("协议确认检查完成", event_code="agreement.check_completed", confirmed=agreements_confirmed)

    easter_egg()

    # 返回MainSystem实例
    return MainSystem()


if __name__ == "__main__":
    exit_code = 0  # 用于记录程序最终的退出状态
    try:
        # 获取MainSystem实例
        main_system = raw_main()

        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # 初始化 WebSocket 日志推送
        from src.common.logger import initialize_ws_handler

        initialize_ws_handler(loop)

        try:
            # 执行初始化和任务调度
            loop.run_until_complete(main_system.initialize())
            # Schedule tasks returns a future that runs forever.
            # We can run console_input_loop concurrently.
            main_tasks = loop.create_task(main_system.schedule_tasks())
            loop.run_until_complete(main_tasks)

        except KeyboardInterrupt:
            logger.warning("收到中断信号，开始关闭流程", event_code="app.interrupt_received")

            # 取消主任务
            if "main_tasks" in locals() and main_tasks and not main_tasks.done():
                main_tasks.cancel()
                try:
                    loop.run_until_complete(main_tasks)
                except asyncio.CancelledError:
                    pass

            # 执行优雅关闭
            if loop and not loop.is_closed():
                try:
                    loop.run_until_complete(graceful_shutdown())
                except Exception:
                    logger.exception("中断处理期间关闭失败", event_code="app.interrupt_shutdown_failed")
        # 新增：检测外部请求关闭

    except SystemExit as e:
        # 捕获 SystemExit (例如 sys.exit()) 并保留退出代码
        if isinstance(e.code, int):
            exit_code = e.code
        else:
            exit_code = 1 if e.code else 0
        if exit_code == RESTART_EXIT_CODE:
            logger.info("收到重启退出码", event_code="app.restart_exit_requested", exit_code=exit_code)

    except Exception:
        logger.exception("主程序异常退出", event_code="app.main_failed")
        exit_code = 1  # 标记发生错误
    finally:
        # 确保 loop 在任何情况下都尝试关闭（如果存在且未关闭）
        if "loop" in locals() and loop and not loop.is_closed():
            loop.close()
            print("[主程序] 事件循环已关闭")

        # 关闭日志系统，释放文件句柄
        try:
            shutdown_logging()
        except Exception as e:
            print(f"关闭日志系统时出错: {e}")

        print("[主程序] 准备退出...")

        # 使用 os._exit() 强制退出，避免被阻塞
        # 由于已经在 graceful_shutdown() 中完成了所有清理工作，这是安全的
        os._exit(exit_code)
