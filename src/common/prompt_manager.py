"""PromptManager 单例：提示词管理器

提供全局的提示词模板管理能力，通过 load_prompts() 一次性加载所有 .prompt 文件，
通过 get_prompt() / format_prompt() 获取模板或格式化结果。

支持热重载：提示词文件发生变化时自动更新，缓存修订号变化时全量重新加载。
提供 safe_get_prompt() 作为降级兜底，避免未找到提示词时抛出异常。
"""

from src.common.logger import get_logger
from src.common.prompt_loader import (
    load_prompt_template,
    get_prompt_cache_revision,
    list_prompt_templates,
    clear_prompt_cache,
)

logger = get_logger("prompt_mgr")


class PromptManager:
    """提示词管理器单例"""

    def __init__(self):
        self._prompts: dict[str, str] = {}  # name → template string
        self._file_prompt_names: set[str] = set()
        self._cache_revision: int = 0
        self._loaded: bool = False

    def load_prompts(self) -> None:
        """加载 prompts/ 目录下所有 .prompt 文件到内存

        扫描 prompts/ 目录，加载每个 .prompt 文件，建立名称→模板的映射。
        """
        self._prompts.clear()
        self._file_prompt_names.clear()
        names = list_prompt_templates()
        for name in names:
            self._prompts[name] = load_prompt_template(name)
            self._file_prompt_names.add(name)
        self._cache_revision = get_prompt_cache_revision()
        self._loaded = True
        logger.debug(f"已加载 {len(self._prompts)} 个提示词模板")

    def get_prompt(self, name: str, /) -> str:
        """获取指定名称的提示词模板字符串

        在获取前会检测目标文件和缓存修订号，如有变化则触发重载。

        Args:
            name: 提示词名称

        Returns:
            模板原始字符串（未格式化）

        Raises:
            KeyError: 提示词未找到
        """
        self._reload_if_changed()
        self._reload_prompt_if_changed(name)
        if name not in self._prompts:
            raise KeyError(f"提示词 '{name}' 未找到，可用提示词: {list(self._prompts.keys())}")
        return self._prompts[name]

    def format_prompt(self, name: str, /, **kwargs) -> str:
        """加载模板并使用 kwargs 格式化

        Args:
            name: 提示词名称
            **kwargs: 格式化参数

        Returns:
            格式化后的字符串
        """
        template = self.get_prompt(name)
        return template.format(**kwargs)

    def _reload_if_changed(self) -> None:
        """检测缓存修订号是否变化，如有变化则自动重载所有提示词"""
        current = get_prompt_cache_revision()
        if current != self._cache_revision:
            logger.info(f"检测到提示词缓存修订号变化 ({self._cache_revision} → {current})，正在重载...")
            self.load_prompts()

    def _reload_prompt_if_changed(self, name: str) -> None:
        """从带文件签名的 LRU 缓存中获取最新的单个模板。"""
        if name in self._prompts and name not in self._file_prompt_names:
            return

        try:
            template = load_prompt_template(name)
        except FileNotFoundError:
            self._prompts.pop(name, None)
            self._file_prompt_names.discard(name)
            return

        if self._prompts.get(name) != template:
            self._prompts[name] = template
            logger.info(f"检测到提示词文件变化，已热重载: {name}")
        self._file_prompt_names.add(name)


# 全局单例
prompt_manager = PromptManager()


def safe_get_prompt(name: str, /, default: str = "", **kwargs) -> str:
    """安全获取格式化后的提示词，失败时返回默认值

    降级兜底函数，当提示词文件缺失或未加载时不会抛出异常，
    而是返回 default 并记录警告日志。

    Args:
        name: 提示词名称
        default: 默认返回值（空字符串）
        **kwargs: 格式化参数

    Returns:
        格式化后的提示词字符串，或 default（失败时）
    """
    try:
        return prompt_manager.format_prompt(name, **kwargs)
    except (KeyError, FileNotFoundError) as e:
        logger.warning(f"提示词 '{name}' 未找到（文件缺失或未加载）: {e}")
        return default
    except Exception as e:
        logger.error(f"加载提示词 '{name}' 时出现意外错误: {e}")
        return default


def reload_prompts() -> None:
    """强制从磁盘重载所有提示词"""
    clear_prompt_cache()
    prompt_manager.load_prompts()
