import os
import stat
import tempfile

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import tomlkit

from loguru import logger
from tomlkit import TOMLDocument
from tomlkit.items import Table

from .config_base import ConfigBase
from .official_configs import (
    ChatConfig,
    DebugConfig,
    ForwardConfig,
    NapcatServerConfig,
    NicknameConfig,
    RiyaBotServerConfig,
    VoiceConfig,
)

PLUGIN_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = PLUGIN_DIR / "template"
CONFIG_PATH = PLUGIN_DIR / "config.toml"
CONFIG_BACKUP_DIR = PLUGIN_DIR / "config_backup"
_MAX_CONFIG_FILE_BYTES = 1024 * 1024


def _secure_directory(path: Path) -> None:
    """创建配置目录，并拒绝链接或组/其他用户可写目录。"""
    if path.is_symlink():
        raise RuntimeError("配置目录不能是符号链接")
    path.mkdir(parents=True, exist_ok=True)
    directory_stat = path.lstat()
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise RuntimeError("配置目录路径无效")
    mode = stat.S_IMODE(directory_stat.st_mode)
    if mode & 0o022:
        path.chmod(mode & ~0o022)


def _open_regular_file(path: Path) -> tuple[int, os.stat_result]:
    """不跟随链接地打开单链接普通文件，并校验打开前后的 inode。"""
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        raise
    if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_nlink != 1:
        raise RuntimeError("配置文件路径无效")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    file_descriptor = os.open(path, flags)
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_nlink != 1
            or opened_stat.st_dev != path_stat.st_dev
            or opened_stat.st_ino != path_stat.st_ino
        ):
            raise RuntimeError("配置文件在读取期间发生变化")
        return file_descriptor, opened_stat
    except Exception:
        os.close(file_descriptor)
        raise


def _secure_regular_file(path: Path, *, mode: int | None = None) -> bool:
    if not os.path.lexists(path):
        return False
    file_descriptor, _ = _open_regular_file(path)
    try:
        if mode is not None and hasattr(os, "fchmod"):
            os.fchmod(file_descriptor, mode)
    finally:
        os.close(file_descriptor)
    return True


def _read_limited_bytes(path: Path) -> bytes:
    file_descriptor, file_stat = _open_regular_file(path)
    try:
        if file_stat.st_size > _MAX_CONFIG_FILE_BYTES:
            raise RuntimeError("配置文件过大")
        with os.fdopen(file_descriptor, "rb") as file:
            file_descriptor = -1
            content = file.read(_MAX_CONFIG_FILE_BYTES + 1)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    if len(content) > _MAX_CONFIG_FILE_BYTES:
        raise RuntimeError("配置文件过大")
    return content


def _load_toml_bytes(content: bytes) -> TOMLDocument:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("配置文件必须使用 UTF-8") from exc
    return tomlkit.loads(text)


def _read_toml_file(path: Path) -> TOMLDocument:
    return _load_toml_bytes(_read_limited_bytes(path))


def _atomic_write_bytes(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    if len(content) > _MAX_CONFIG_FILE_BYTES:
        raise RuntimeError("配置内容过大")

    _secure_directory(path.parent)
    if os.path.lexists(path):
        _secure_regular_file(path)

    file_descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(file_descriptor, mode)
        with os.fdopen(file_descriptor, "wb") as file:
            file_descriptor = -1
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
        path.chmod(mode)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _create_backup(content: bytes) -> Path:
    if len(content) > _MAX_CONFIG_FILE_BYTES:
        raise RuntimeError("配置内容过大")

    _secure_directory(CONFIG_BACKUP_DIR)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    base_name = f"config.toml.bak.{timestamp}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    for suffix in range(100):
        backup_name = base_name if suffix == 0 else f"{base_name}.{suffix}"
        backup_path = CONFIG_BACKUP_DIR / backup_name
        try:
            file_descriptor = os.open(backup_path, flags, 0o600)
        except FileExistsError:
            continue
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(file_descriptor, 0o600)
            with os.fdopen(file_descriptor, "wb") as file:
                file_descriptor = -1
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            return backup_path
        except Exception:
            if os.path.lexists(backup_path):
                backup_path.unlink()
            raise
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)

    raise RuntimeError("无法创建唯一的配置备份")


def update_config():
    template_path = TEMPLATE_DIR / "template_config.toml"
    old_config_path = CONFIG_PATH
    new_config_path = CONFIG_PATH
    _secure_directory(CONFIG_PATH.parent)

    template_content = _read_limited_bytes(template_path)
    new_config = _load_toml_bytes(template_content)

    # 检查配置文件是否存在
    if not os.path.lexists(old_config_path):
        logger.info("配置文件不存在，从模板创建新配置")
        _atomic_write_bytes(old_config_path, template_content)
        logger.info("已创建新配置文件")
        return

    _secure_regular_file(old_config_path, mode=0o600)
    old_config_content = _read_limited_bytes(old_config_path)
    old_config = _load_toml_bytes(old_config_content)

    # 检查version是否相同
    if old_config and "inner" in old_config and "inner" in new_config:
        old_version = old_config["inner"].get("version")
        new_version = new_config["inner"].get("version")
        if old_version and new_version and old_version == new_version:
            logger.info("检测到配置文件版本号相同，跳过更新")
            return
        logger.info("检测到配置文件版本号不同，开始更新")
    else:
        logger.info("已有配置文件未检测到版本号，可能是旧版本。将进行更新")

    # 备份旧配置文件
    _create_backup(old_config_content)
    logger.info("已备份旧配置文件")

    def update_dict(target: TOMLDocument | dict, source: TOMLDocument | dict):
        """
        将source字典的值更新到target字典中（如果target中存在相同的键）
        """
        for key, value in source.items():
            # 跳过version字段的更新
            if key == "version":
                continue
            if key in target:
                if isinstance(value, dict) and isinstance(target[key], (dict, Table)):
                    update_dict(target[key], value)
                else:
                    try:
                        # 对数组类型进行特殊处理
                        if isinstance(value, list):
                            # 如果是空数组，确保它保持为空数组
                            target[key] = tomlkit.array(str(value)) if value else tomlkit.array()
                        else:
                            # 其他类型使用item方法创建新值
                            target[key] = tomlkit.item(value)
                    except (TypeError, ValueError):
                        # 如果转换失败，直接赋值
                        target[key] = value

    # 将旧配置的值更新到新配置中
    logger.debug("合并适配器配置")
    update_dict(new_config, old_config)

    # 保存更新后的配置（保留注释和格式）
    updated_content = tomlkit.dumps(new_config).encode("utf-8")
    _atomic_write_bytes(new_config_path, updated_content)
    logger.info("适配器配置文件已更新")


@dataclass
class Config(ConfigBase):
    """总配置类"""

    nickname: NicknameConfig
    napcat_server: NapcatServerConfig
    maibot_server: RiyaBotServerConfig
    chat: ChatConfig
    voice: VoiceConfig
    forward: ForwardConfig
    debug: DebugConfig


def load_config(config_path: str) -> Config:
    """
    加载配置文件
    :param config_path: 配置文件路径
    :return: Config对象
    """
    try:
        config_data = _read_toml_file(Path(config_path))
        return Config.from_dict(config_data)
    except Exception as exc:
        logger.critical(f"配置文件解析失败: {type(exc).__name__}")
        raise


# 更新配置
update_config()

logger.debug("加载适配器配置文件")

# 创建配置管理器
from .config_manager import ConfigManager  # noqa: E402

_config_manager = ConfigManager()
_config_manager.load(config_path=str(CONFIG_PATH))

# 向后兼容：global_config 指向配置管理器
# 所有现有代码可以继续使用 global_config.chat.xxx 访问配置
global_config = _config_manager

logger.info("适配器配置已加载")
