"""提示词文件加载器：文件I/O + LRU 缓存层

提供从 prompts/ 目录加载 .prompt 文件的基础能力，
支持缓存清除（热重载触发）和名称校验。
"""

import re
from pathlib import Path
from functools import lru_cache

# 项目 prompts 目录根路径
PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "prompts"
PROMPT_EXTENSION = ".prompt"

# 安全名称段模式：仅允许字母、数字、下划线和连字符
SAFE_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

# 缓存修订号：每次 clear_prompt_cache() 调用时递增，
# prompt_manager 通过轮询此值感知缓存变化并触发重载
_PROMPT_CACHE_REVISION = 0


def normalize_prompt_name(name: str) -> str:
    """规范化提示词名称：去除扩展名后缀，校验安全性

    Args:
        name: 原始名称（可能包含 .prompt 后缀）

    Returns:
        规范化后的名称（无后缀）

    Raises:
        ValueError: 名称包含不安全字符
    """
    # 去除 .prompt 后缀（如果存在）
    if name.endswith(PROMPT_EXTENSION):
        name = name[: -len(PROMPT_EXTENSION)]

    segments = name.split(".")
    if not segments or any(not segment or not SAFE_SEGMENT_PATTERN.fullmatch(segment) for segment in segments):
        raise ValueError(f"提示词名称 '{name}' 包含不安全字符，仅允许点分隔的字母、数字、下划线和连字符")

    return ".".join(segments)


def _prompt_path(name: str) -> Path:
    """把点分提示词 ID 映射为 prompts/ 下的文件路径。"""
    safe_name = normalize_prompt_name(name)
    return PROMPTS_ROOT.joinpath(*safe_name.split(".")).with_suffix(PROMPT_EXTENSION)


def _prompt_name(filepath: Path) -> str:
    """把 prompts/ 下的文件路径映射为点分提示词 ID。"""
    relative_path = filepath.relative_to(PROMPTS_ROOT).with_suffix("")
    return ".".join(relative_path.parts)


@lru_cache(maxsize=128)
def _read_prompt_file(filepath: Path, file_signature: tuple[int, int], cache_revision: int) -> str:
    """读取提示词文件内容（LRU 缓存）

    Args:
        filepath: .prompt 文件的完整路径
        file_signature: 文件修改时间和大小，用于自动感知磁盘变更
        cache_revision: 当前缓存修订号，用于强制缓存失效

    Returns:
        文件内容字符串
    """
    return filepath.read_text(encoding="utf-8")


def load_prompt_template(name: str) -> str:
    """加载指定名称的提示词模板

    构建文件路径为 PROMPTS_ROOT / f"{name}.prompt"，读取并返回原始模板字符串。

    Args:
        name: 提示词名称（不含 .prompt 后缀）

    Returns:
        模板原始字符串

    Raises:
        ValueError: 名称校验失败
        FileNotFoundError: 提示词文件不存在
    """
    safe_name = normalize_prompt_name(name)
    filepath = _prompt_path(safe_name)
    file_signature = get_prompt_file_signature(safe_name)
    return _read_prompt_file(filepath, file_signature, _PROMPT_CACHE_REVISION)


def get_prompt_file_signature(name: str) -> tuple[int, int]:
    """返回提示词文件的修改时间和大小，用于检测热更新。"""
    stat = _prompt_path(name).stat()
    return stat.st_mtime_ns, stat.st_size


def load_prompt(name: str, /, **kwargs) -> str:
    """加载并格式化提示词（便捷入口）

    等价于 load_prompt_template(name).format(**kwargs)

    Args:
        name: 提示词名称
        **kwargs: 格式化参数

    Returns:
        格式化后的字符串
    """
    template = load_prompt_template(name)
    return template.format(**kwargs)


def clear_prompt_cache() -> None:
    """清除缓存并递增修订号

    调用后：
    1. _PROMPT_CACHE_REVISION 递增
    2. _read_prompt_file 的 LRU 缓存被清空
    3. prompt_manager 下次 get_prompt() 时会检测到修订号变化并重载
    """
    global _PROMPT_CACHE_REVISION
    _PROMPT_CACHE_REVISION += 1
    _read_prompt_file.cache_clear()


def list_prompt_templates() -> list[str]:
    """列出 prompts/ 目录下所有可用的提示词模板名称

    Returns:
        提示词名称列表（不含 .prompt 后缀，按名称排序）
    """
    if not PROMPTS_ROOT.exists():
        return []
    names = [_prompt_name(path) for path in PROMPTS_ROOT.rglob(f"*{PROMPT_EXTENSION}")]
    if len(names) != len(set(names)):
        raise ValueError("提示词目录中存在映射到同一点分 ID 的重复文件")
    return sorted(names)


# 多段模板解析：用于合并 prompt 文件中的分节标记
SECTION_MARKER = re.compile(r"^###SECTION:\s*(\S+)\s*$")
END_SECTION_MARKER = "###END_SECTION###"


def parse_prompt_sections(template: str) -> dict[str, str]:
    """解析多段 .prompt 文件，提取所有命名段

    段格式：
        ###SECTION: section_name
        {template text with {variables}}
        ###END_SECTION###

    Args:
        template: 完整文件内容

    Returns:
        段名到模板文本的映射字典
    """
    sections: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    for line in template.split("\n"):
        m = SECTION_MARKER.match(line)
        if m:
            if current_name is not None:
                sections[current_name] = "\n".join(current_lines).strip()
            current_name = m.group(1)
            current_lines = []
            continue
        if line.strip() == END_SECTION_MARKER:
            if current_name is not None:
                sections[current_name] = "\n".join(current_lines).strip()
            current_name = None
            current_lines = []
            continue
        if current_name is not None:
            current_lines.append(line)

    if current_name is not None:
        sections[current_name] = "\n".join(current_lines).strip()

    return sections


def load_prompt_section(name: str, section: str, /, **kwargs) -> str:
    """加载多段模板中的指定段并格式化

    等价于 parse_prompt_sections(load_prompt_template(name))[section].format(**kwargs)

    Args:
        name: 提示词名称
        section: 段名
        **kwargs: 格式化参数

    Returns:
        格式化后的字符串

    Raises:
        KeyError: 指定段不存在
    """
    template = load_prompt_template(name)
    sections = parse_prompt_sections(template)
    if section not in sections:
        raise KeyError(f"段 '{section}' 不存在于提示词 '{name}' 中（可用段: {list(sections.keys())}）")
    return sections[section].format(**kwargs)


def get_prompt_cache_revision() -> int:
    """获取当前缓存修订号

    Returns:
        当前修订号
    """
    return _PROMPT_CACHE_REVISION
