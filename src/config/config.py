import os
import json
import tomlkit
import shutil

from datetime import datetime
from tomlkit import TOMLDocument
from tomlkit.items import Table, KeyType
from dataclasses import field, dataclass, fields
from rich.traceback import install
from typing import ClassVar, List, Optional

from src.common.logger import get_logger
from src.common.toml_utils import format_toml_string
from src.config.config_base import ConfigBase
from src.config.official_configs import (
    BotConfig,
    PersonalityConfig,
    ExpressionConfig,
    ChatConfig,
    EmojiConfig,
    KeywordReactionConfig,
    ChineseTypoConfig,
    ResponsePostProcessConfig,
    ResponseSplitterConfig,
    TelemetryConfig,
    LogConfig,
    ExperimentalConfig,
    MessageReceiveConfig,
    MaimMessageConfig,
    LPMMKnowledgeConfig,
    RelationshipConfig,
    ToolConfig,
    VoiceConfig,
    MemoryConfig,
    DebugConfig,
    DreamConfig,
    WebUIConfig,
)

from .api_ada_configs import (
    ModelTaskConfig,
    ModelInfo,
    APIProvider,
    TaskConfig,
)


install(extra_lines=3)


# 配置主程序日志格式
logger = get_logger("config")

# 获取当前文件所在目录的父目录的父目录（即RiyaBot项目根目录）
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "template")

# 考虑到，实际上配置文件中的mai_version是不会自动更新的,所以采用硬编码
# 对该字段的更新，请严格参照语义化版本规范：https://semver.org/lang/zh-CN/
MMC_VERSION = "0.13.0"

_CREATED_CONFIG_FILES: list[str] = []


def get_created_config_files() -> list[str]:
    """返回本次启动期间由模板新创建的配置文件。"""
    return list(_CREATED_CONFIG_FILES)


def _mark_webui_setup_required(reason: str) -> None:
    """配置文件被重新创建时，要求 WebUI 重新进入首次配置。"""
    webui_config_path = os.path.join(PROJECT_ROOT, "data", "webui.json")
    if not os.path.exists(webui_config_path):
        return

    try:
        with open(webui_config_path, "r", encoding="utf-8") as f:
            webui_config = json.load(f)

        webui_config["first_setup_completed"] = False
        webui_config["setup_required_reason"] = reason
        webui_config.pop("setup_completed_at", None)

        with open(webui_config_path, "w", encoding="utf-8") as f:
            json.dump(webui_config, f, ensure_ascii=False, indent=2)

        logger.info("已标记 WebUI 需要重新进行首次配置", event_code="webui.setup.required", reason=reason)
    except Exception:
        logger.exception("标记 WebUI 首次配置状态失败", event_code="webui.setup.mark_required_failed")


def get_key_comment(toml_table, key):
    # 获取key的注释（如果有）
    if hasattr(toml_table, "trivia") and hasattr(toml_table.trivia, "comment"):
        return toml_table.trivia.comment
    if hasattr(toml_table, "value") and isinstance(toml_table.value, dict):
        item = toml_table.value.get(key)
        if item is not None and hasattr(item, "trivia"):
            return item.trivia.comment
    if hasattr(toml_table, "keys"):
        for k in toml_table.keys():
            if isinstance(k, KeyType) and k.key == key:  # type: ignore
                return k.trivia.comment  # type: ignore
    return None


def compare_dicts(new, old, path=None, logs=None):
    # 递归比较两个dict，找出新增和删减项，收集注释
    if path is None:
        path = []
    if logs is None:
        logs = []
    # 新增项
    for key in new:
        if key == "version":
            continue
        if key not in old:
            comment = get_key_comment(new, key)
            logs.append(f"新增: {'.'.join(path + [str(key)])}  注释: {comment or '无'}")
        elif isinstance(new[key], (dict, Table)) and isinstance(old.get(key), (dict, Table)):
            compare_dicts(new[key], old[key], path + [str(key)], logs)
    # 删减项
    for key in old:
        if key == "version":
            continue
        if key not in new:
            comment = get_key_comment(old, key)
            logs.append(f"删减: {'.'.join(path + [str(key)])}  注释: {comment or '无'}")
    return logs


def get_value_by_path(d, path):
    for k in path:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return None
    return d


def set_value_by_path(d, path, value):
    """设置嵌套字典中指定路径的值"""
    for k in path[:-1]:
        if k not in d or not isinstance(d[k], dict):
            d[k] = {}
        d = d[k]

    # 使用 tomlkit.item 来保持 TOML 格式
    try:
        d[path[-1]] = tomlkit.item(value)
    except (TypeError, ValueError):
        # 如果转换失败，直接赋值
        d[path[-1]] = value


def compare_default_values(new, old, path=None, logs=None, changes=None):
    # 递归比较两个dict，找出默认值变化项
    if path is None:
        path = []
    if logs is None:
        logs = []
    if changes is None:
        changes = []
    for key in new:
        if key == "version":
            continue
        if key in old:
            if isinstance(new[key], (dict, Table)) and isinstance(old[key], (dict, Table)):
                compare_default_values(new[key], old[key], path + [str(key)], logs, changes)
            elif new[key] != old[key]:
                logs.append(f"默认值变化: {'.'.join(path + [str(key)])}  旧默认值: {old[key]}  新默认值: {new[key]}")
                changes.append((path + [str(key)], old[key], new[key]))
    return logs, changes


def _get_version_from_toml(toml_path) -> Optional[str]:
    """从TOML文件中获取版本号"""
    if not os.path.exists(toml_path):
        return None
    with open(toml_path, "r", encoding="utf-8") as f:
        doc = tomlkit.load(f)
    if "inner" in doc and "version" in doc["inner"]:  # type: ignore
        return doc["inner"]["version"]  # type: ignore
    return None


def _version_tuple(v):
    """将版本字符串转换为元组以便比较"""
    if v is None:
        return (0,)
    return tuple(int(x) if x.isdigit() else 0 for x in str(v).replace("v", "").split("-")[0].split("."))


def _update_dict(target: TOMLDocument | dict | Table, source: TOMLDocument | dict):
    """
    将source字典的值更新到target字典中（如果target中存在相同的键）
    """
    for key, value in source.items():
        # 跳过version字段的更新
        if key == "version":
            continue
        if key in target:
            target_value = target[key]
            if isinstance(value, dict) and isinstance(target_value, (dict, Table)):
                _update_dict(target_value, value)
            else:
                try:
                    # 统一使用 tomlkit.item 来保持原生类型与转义，不对列表做字符串化处理
                    target[key] = tomlkit.item(value)
                except (TypeError, ValueError):
                    # 如果转换失败，直接赋值
                    target[key] = value


def _is_blank_model_template(config_data: TOMLDocument | dict) -> bool:
    """判断 model_config 模板是否为首次配置用的空白模板。"""
    return config_data.get("api_providers") == [] and config_data.get("models") == []


def _update_config_generic(config_name: str, template_name: str):
    """
    通用的配置文件更新函数

    Args:
        config_name: 配置文件名（不含扩展名），如 'bot_config' 或 'model_config'
        template_name: 模板文件名（不含扩展名），如 'bot_config_template' 或 'model_config_template'
    """
    # 获取根目录路径
    old_config_dir = os.path.join(CONFIG_DIR, "old")
    compare_dir = os.path.join(TEMPLATE_DIR, "compare")

    # 定义文件路径
    template_path = os.path.join(TEMPLATE_DIR, f"{template_name}.toml")
    old_config_path = os.path.join(CONFIG_DIR, f"{config_name}.toml")
    new_config_path = os.path.join(CONFIG_DIR, f"{config_name}.toml")
    compare_path = os.path.join(compare_dir, f"{template_name}.toml")

    # 创建compare目录（如果不存在）
    os.makedirs(compare_dir, exist_ok=True)

    template_version = _get_version_from_toml(template_path)
    compare_version = _get_version_from_toml(compare_path)

    # 检查配置文件是否存在
    if not os.path.exists(old_config_path):
        logger.info(f"{config_name}.toml配置文件不存在，从模板创建新配置")
        os.makedirs(CONFIG_DIR, exist_ok=True)  # 创建文件夹
        shutil.copy2(template_path, old_config_path)  # 复制模板文件
        created_file = f"{config_name}.toml"
        _CREATED_CONFIG_FILES.append(created_file)
        _mark_webui_setup_required(f"{created_file} 已从模板创建")
        logger.info(f"已创建新{config_name}配置文件，可在 WebUI 首次配置向导中继续填写: {old_config_path}")
        return

    compare_config = None
    new_config = None
    old_config = None

    # 先读取 compare 下的模板（如果有），用于默认值变动检测
    if os.path.exists(compare_path):
        with open(compare_path, "r", encoding="utf-8") as f:
            compare_config = tomlkit.load(f)

    # 读取当前模板
    with open(template_path, "r", encoding="utf-8") as f:
        new_config = tomlkit.load(f)

    # 检查默认值变化并处理（只有 compare_config 存在时才做）
    if compare_config and not (config_name == "model_config" and _is_blank_model_template(new_config)):
        # 读取旧配置
        with open(old_config_path, "r", encoding="utf-8") as f:
            old_config = tomlkit.load(f)
        logs, changes = compare_default_values(new_config, compare_config)
        if logs:
            logger.info(f"检测到{config_name}模板默认值变动如下：")
            for log in logs:
                logger.info(log)
            # 检查旧配置是否等于旧默认值，如果是则更新为新默认值
            config_updated = False
            for path, old_default, new_default in changes:
                old_value = get_value_by_path(old_config, path)
                if old_value == old_default:
                    set_value_by_path(old_config, path, new_default)
                    logger.info(
                        f"已自动将{config_name}配置 {'.'.join(path)} 的值从旧默认值 {old_default} 更新为新默认值 {new_default}"
                    )
                    config_updated = True

            # 如果配置有更新，立即保存到文件
            if config_updated:
                with open(old_config_path, "w", encoding="utf-8") as f:
                    f.write(format_toml_string(old_config))
                logger.info(f"已保存更新后的{config_name}配置文件")
        else:
            logger.info(f"未检测到{config_name}模板默认值变动")
    elif compare_config:
        logger.info(f"检测到{config_name}使用空白模型模板，跳过默认值自动迁移")

    # 检查 compare 下没有模板，或新模板版本更高，则复制
    if not os.path.exists(compare_path):
        shutil.copy2(template_path, compare_path)
        logger.info(f"已将{config_name}模板文件复制到: {compare_path}")
    elif _version_tuple(template_version) > _version_tuple(compare_version):
        shutil.copy2(template_path, compare_path)
        logger.info(f"{config_name}模板版本较新，已替换compare下的模板: {compare_path}")
    else:
        logger.debug(f"compare下的{config_name}模板版本不低于当前模板，无需替换: {compare_path}")

    # 读取旧配置文件和模板文件（如果前面没读过 old_config，这里再读一次）
    if old_config is None:
        with open(old_config_path, "r", encoding="utf-8") as f:
            old_config = tomlkit.load(f)
    # new_config 已经读取

    # 检查version是否相同
    if old_config and "inner" in old_config and "inner" in new_config:
        old_version = old_config["inner"].get("version")  # type: ignore
        new_version = new_config["inner"].get("version")  # type: ignore
        if old_version and new_version and old_version == new_version:
            logger.info(f"检测到{config_name}配置文件版本号相同 (v{old_version})，跳过更新")
            return
        else:
            logger.info(
                f"\n----------------------------------------\n检测到{config_name}版本号不同: 旧版本 v{old_version} -> 新版本 v{new_version}\n----------------------------------------"
            )
    else:
        logger.info(f"已有{config_name}配置文件未检测到版本号，可能是旧版本。将进行更新")

    # 创建old目录（如果不存在）
    os.makedirs(old_config_dir, exist_ok=True)  # 生成带时间戳的新文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    old_backup_path = os.path.join(old_config_dir, f"{config_name}_{timestamp}.toml")

    # 移动旧配置文件到old目录
    shutil.move(old_config_path, old_backup_path)
    logger.info(f"已备份旧{config_name}配置文件到: {old_backup_path}")

    # 复制模板文件到配置目录
    shutil.copy2(template_path, new_config_path)
    logger.info(f"已创建新{config_name}配置文件: {new_config_path}")

    # 输出新增和删减项及注释
    if old_config:
        logger.info(f"{config_name}配置项变动如下：\n----------------------------------------")
        if logs := compare_dicts(new_config, old_config):
            for log in logs:
                logger.info(log)
        else:
            logger.info("无新增或删减项")

    # 将旧配置的值更新到新配置中
    logger.info(f"开始合并{config_name}新旧配置...")
    _update_dict(new_config, old_config)

    # 保存更新后的配置（保留注释和格式，数组多行格式化）
    with open(new_config_path, "w", encoding="utf-8") as f:
        f.write(format_toml_string(new_config))
    logger.info(f"{config_name}配置文件更新完成，建议检查新配置文件中的内容，以免丢失重要信息")


def update_config():
    """更新bot_config.toml配置文件"""
    _update_config_generic("bot_config", "bot_config_template")


def update_model_config():
    """更新model_config.toml配置文件"""
    _update_config_generic("model_config", "model_config_template")


@dataclass
class Config(ConfigBase):
    """总配置类"""

    MMC_VERSION: str = field(default=MMC_VERSION, repr=False, init=False)  # 硬编码的版本信息

    bot: BotConfig
    personality: PersonalityConfig
    relationship: RelationshipConfig
    chat: ChatConfig
    message_receive: MessageReceiveConfig
    emoji: EmojiConfig
    expression: ExpressionConfig
    keyword_reaction: KeywordReactionConfig
    chinese_typo: ChineseTypoConfig
    response_post_process: ResponsePostProcessConfig
    response_splitter: ResponseSplitterConfig
    telemetry: TelemetryConfig
    log: LogConfig
    webui: WebUIConfig
    experimental: ExperimentalConfig
    maim_message: MaimMessageConfig
    lpmm_knowledge: LPMMKnowledgeConfig
    tool: ToolConfig
    memory: MemoryConfig
    debug: DebugConfig
    voice: VoiceConfig
    dream: DreamConfig


@dataclass
class APIAdapterConfig(ConfigBase):
    """API Adapter配置类"""

    RUNTIME_REQUIRED_TASKS: ClassVar[tuple[str, ...]] = ("utils", "tool_use", "replyer", "planner")

    models: List[ModelInfo]
    """模型列表"""

    model_task_config: ModelTaskConfig
    """模型任务配置"""

    api_providers: List[APIProvider] = field(default_factory=list)
    """API提供商列表"""

    def __post_init__(self):
        self.validate_integrity()

    def validate_integrity(self, require_complete: bool = False) -> None:
        """校验模型配置结构。

        首次配置阶段允许 api_providers/models 为空；真正运行前可通过
        require_complete=True 要求至少配置一个提供商和一个模型。
        """
        if require_complete and not self.models:
            raise ValueError("模型列表不能为空，请在 WebUI 中添加至少一个模型。")
        if require_complete and not self.api_providers:
            raise ValueError("API提供商列表不能为空，请在 WebUI 中添加至少一个API提供商。")

        # 检查API提供商名称是否重复
        provider_names = [provider.name for provider in self.api_providers]
        if len(provider_names) != len(set(provider_names)):
            raise ValueError("API提供商名称存在重复，请检查配置文件。")

        # 检查模型名称是否重复
        model_names = [model.name for model in self.models]
        if len(model_names) != len(set(model_names)):
            raise ValueError("模型名称存在重复，请检查配置文件。")

        self.api_providers_dict = {provider.name: provider for provider in self.api_providers}
        self.models_dict = {model.name: model for model in self.models}

        for model in self.models:
            if not model.model_identifier:
                raise ValueError(f"模型 '{model.name}' 的 model_identifier 不能为空")
            if require_complete and (not model.api_provider or model.api_provider not in self.api_providers_dict):
                raise ValueError(f"模型 '{model.name}' 的 api_provider '{model.api_provider}' 不存在")

        if require_complete:
            for task_name, unknown_models in self.get_unknown_task_models().items():
                if unknown_models:
                    raise ValueError(
                        f"任务 '{task_name}' 引用了不存在的模型: {', '.join(unknown_models)}。"
                        "请先在模型管理中添加这些模型，或从任务配置中移除。"
                    )

            missing_tasks = self.get_missing_runtime_tasks()
            if missing_tasks:
                raise ValueError(
                    "以下运行必需任务尚未分配模型: "
                    f"{', '.join(missing_tasks)}。请在 WebUI 的模型管理与分配中完成配置。"
                )

    def get_unknown_task_models(self) -> dict[str, list[str]]:
        """返回任务配置中引用但未定义的模型名称。"""
        if not hasattr(self, "models_dict"):
            self.models_dict = {model.name: model for model in self.models}

        unknown: dict[str, list[str]] = {}
        for config_field in fields(self.model_task_config):
            task_config = getattr(self.model_task_config, config_field.name, None)
            if not isinstance(task_config, TaskConfig):
                continue
            missing = [model_name for model_name in task_config.model_list if model_name not in self.models_dict]
            if missing:
                unknown[config_field.name] = missing
        return unknown

    def is_runtime_ready(self) -> bool:
        """判断模型配置是否具备启动主系统的最低条件。"""
        try:
            self.validate_integrity(require_complete=True)
        except ValueError:
            return False
        return True

    def get_runtime_readiness_error(self) -> Optional[str]:
        """返回模型配置无法启动主系统的原因。"""
        try:
            self.validate_integrity(require_complete=True)
        except ValueError as e:
            return str(e)
        return None

    def get_missing_runtime_tasks(self) -> list[str]:
        """返回尚未分配模型的运行必需任务。"""
        missing: list[str] = []
        for task_name in self.RUNTIME_REQUIRED_TASKS:
            task_config = getattr(self.model_task_config, task_name, None)
            if not isinstance(task_config, TaskConfig) or not task_config.model_list:
                missing.append(task_name)
        return missing

    def get_model_info(self, model_name: str) -> ModelInfo:
        """根据模型名称获取模型信息"""
        if not model_name:
            raise ValueError("模型名称不能为空")
        if model_name not in self.models_dict:
            raise KeyError(f"模型 '{model_name}' 不存在")
        return self.models_dict[model_name]

    def get_provider(self, provider_name: str) -> APIProvider:
        """根据提供商名称获取API提供商信息"""
        if not provider_name:
            raise ValueError("API提供商名称不能为空")
        if provider_name not in self.api_providers_dict:
            raise KeyError(f"API提供商 '{provider_name}' 不存在")
        return self.api_providers_dict[provider_name]


def load_config(config_path: str) -> Config:
    """
    加载配置文件
    Args:
        config_path: 配置文件路径
    Returns:
        Config对象
    """
    # 读取配置文件
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = tomlkit.load(f)

    # 创建Config对象
    try:
        return Config.from_dict(config_data)
    except Exception as e:
        logger.critical("配置文件解析失败")
        raise e


def api_ada_load_config(config_path: str) -> APIAdapterConfig:
    """
    加载API适配器配置文件
    Args:
        config_path: 配置文件路径
    Returns:
        APIAdapterConfig对象
    """
    # 读取配置文件
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = tomlkit.load(f)

    # 创建APIAdapterConfig对象
    try:
        return APIAdapterConfig.from_dict(config_data)
    except Exception as e:
        logger.critical("API适配器配置文件解析失败")
        raise e


# 获取配置文件路径
logger.info("应用版本已加载", event_code="config.version.loaded", version=MMC_VERSION)
update_config()
update_model_config()

logger.info("配置文件开始加载", event_code="config.load.started")
global_config = load_config(config_path=os.path.join(CONFIG_DIR, "bot_config.toml"))
model_config = api_ada_load_config(config_path=os.path.join(CONFIG_DIR, "model_config.toml"))
logger.info("配置文件加载完成", event_code="config.load.completed")
