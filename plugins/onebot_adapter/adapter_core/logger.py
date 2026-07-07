import sys
from pathlib import Path
from datetime import datetime, timedelta

from loguru import logger

from .config import global_config

# 日志目录配置
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 日志等级映射。适配器只展示主程序同一套级别字母。
LEVEL_ABBR = {"TRACE": "D", "DEBUG": "D", "SUCCESS": "I", "INFO": "I", "WARNING": "W", "ERROR": "E", "CRITICAL": "C"}
LEVEL_COLORS = {
    "TRACE": "<blue>",
    "DEBUG": "<blue>",
    "SUCCESS": "<green>",
    "INFO": "<green>",
    "WARNING": "<yellow>",
    "ERROR": "<red>",
    "CRITICAL": "<magenta>",
}
CONSOLE_FORMAT = "{time:MM-DD HH:mm:ss} | <level>[{extra[level_abbr]}]</level> | <cyan>[{extra[module_name]}]</cyan> | {message}"
FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | [{extra[level_abbr]}] | [{extra[module_name]}] | {message}"


def configure_level_colors() -> None:
    """统一 loguru 级别颜色。"""
    for level_name, color in LEVEL_COLORS.items():
        try:
            logger.level(level_name, color=color)
        except ValueError:
            continue


def get_level_abbr(record):
    """获取日志等级的缩写"""
    return LEVEL_ABBR.get(record["level"].name, record["level"].name[0])


def clean_old_logs(days: int = 30):
    """清理超过指定天数的日志文件"""
    try:
        cutoff_date = datetime.now() - timedelta(days=days)
        for log_file in LOG_DIR.glob("*.log"):
            try:
                file_time = datetime.fromtimestamp(log_file.stat().st_mtime)
                if file_time < cutoff_date:
                    log_file.unlink()
            except Exception:
                continue
    except Exception:
        return


# 清理过期日志
clean_old_logs(30)

# 移除默认处理器
logger.remove()
configure_level_colors()


# 自定义格式化函数
def format_log(record):
    """格式化日志记录"""
    record["extra"]["level_abbr"] = get_level_abbr(record)
    if "module_name" not in record["extra"]:
        record["extra"]["module_name"] = "Adapter"
    return True


# 控制台输出处理器 - 简洁格式
logger.add(
    sys.stderr,
    level=global_config.debug.level,
    format=CONSOLE_FORMAT,
    filter=lambda record: format_log(record) and record["extra"].get("module_name") != "maim_message",
)

# maim_message 单独处理
logger.add(
    sys.stderr,
    level="INFO",
    format=CONSOLE_FORMAT,
    filter=lambda record: format_log(record) and record["extra"].get("module_name") == "maim_message",
)

# 文件输出处理器 - 使用与主程序控制台一致的视觉格式
log_file = LOG_DIR / f"adapter_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logger.add(
    log_file,
    level="DEBUG",
    format=FILE_FORMAT,
    rotation="100 MB",  # 单个日志文件最大100MB
    retention="30 days",  # 保留30天
    encoding="utf-8",
    enqueue=True,  # 异步写入,避免阻塞
    filter=format_log,  # 确保extra字段存在
)


def get_logger(module_name: str = "Adapter"):
    """
    获取自定义模块名的logger

    Args:
        module_name: 模块名称,用于日志输出中标识来源

    Returns:
        配置好的logger实例

    Example:
        >>> from .logger import get_logger
        >>> logger = get_logger("MyModule")
        >>> logger.info("这是一条日志")
        MM-DD HH:mm:ss | [I] | MyModule | 这是一条日志
    """
    return logger.bind(module_name=module_name)


# 默认logger实例(用于向后兼容)
logger = logger.bind(module_name="Adapter")

# maim_message的logger
custom_logger = logger.bind(module_name="maim_message")
