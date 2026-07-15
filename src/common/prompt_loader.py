"""提示词文件加载器：文件I/O + LRU 缓存层

提供从 prompts/ 目录加载 .prompt 文件的基础能力，
支持缓存清除（热重载触发）和名称校验。
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# 项目 prompts 目录根路径
PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "prompts"
PROMPT_EXTENSION = ".prompt"

PROMPT_META_START = "###PROMPT_META###"
PROMPT_META_END = "###END_PROMPT_META###"
PROMPT_META_MARKER_PREFIXES = ("###PROMPT_META", "###END_PROMPT_META")
PROMPT_META_REQUIRED_KEYS = {"id", "kind", "stage", "status", "summary", "output"}
PROMPT_META_ALLOWED_KEYS = PROMPT_META_REQUIRED_KEYS | {"variants"}
PROMPT_KINDS = {"template", "fragment"}
PROMPT_STATUSES = {"active", "fallback", "legacy"}

# 安全名称段模式：仅允许字母、数字、下划线和连字符
SAFE_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

# 缓存修订号：每次 clear_prompt_cache() 调用时递增，
# prompt_manager 通过轮询此值感知缓存变化并触发重载
_PROMPT_CACHE_REVISION = 0


@dataclass(frozen=True)
class PromptMetadata:
    """提示词文件的维护元数据，不会进入运行时提示词正文。"""

    prompt_id: str
    kind: str
    stage: str
    status: str
    summary: str
    output: str
    variants: tuple[str, ...] = ()


@dataclass(frozen=True)
class PromptDocument:
    """解析后的提示词文档。"""

    template: str
    sections: dict[str, str]
    metadata: PromptMetadata | None = None


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


def _load_raw_prompt_template(name: str) -> str:
    """加载未经文档解析的 .prompt 文件内容。"""
    safe_name = normalize_prompt_name(name)
    filepath = _prompt_path(safe_name)
    file_signature = get_prompt_file_signature(safe_name)
    return _read_prompt_file(filepath, file_signature, _PROMPT_CACHE_REVISION)


def load_prompt_document(name: str, *, require_metadata: bool = False) -> PromptDocument:
    """加载并解析一个提示词文档。"""
    safe_name = normalize_prompt_name(name)
    return parse_prompt_document(
        _load_raw_prompt_template(safe_name),
        expected_id=safe_name,
        require_metadata=require_metadata,
    )


def load_prompt_template(name: str) -> str:
    """加载指定名称的运行时提示词模板

    文件顶部的维护元数据会被解析并剥离，不会发送给模型。

    Args:
        name: 提示词名称（不含 .prompt 后缀）

    Returns:
        不含维护元数据的模板字符串

    Raises:
        ValueError: 名称校验失败
        FileNotFoundError: 提示词文件不存在
    """
    return load_prompt_document(name).template


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
SECTION_MARKER = re.compile(r"^###SECTION:\s*([A-Za-z0-9_-]+)\s*$")
SECTION_MARKER_PREFIX = "###SECTION"
END_SECTION_MARKER = "###END_SECTION###"
END_SECTION_MARKER_PREFIX = "###END_SECTION"


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
    outside_lines: list[tuple[int, str]] = []

    for line_number, line in enumerate(template.split("\n"), start=1):
        stripped_line = line.strip()
        m = SECTION_MARKER.fullmatch(stripped_line)
        if m:
            if current_name is not None:
                raise ValueError(f"嵌套分段：第 {line_number} 行在分段 '{current_name}' 未结束时开启了新分段")
            section_name = m.group(1)
            if section_name in sections:
                raise ValueError(f"重复分段：'{section_name}'")
            current_name = section_name
            current_lines = []
            continue
        if stripped_line.startswith(SECTION_MARKER_PREFIX):
            raise ValueError(f"非法分段名：第 {line_number} 行必须使用字母、数字、下划线或连字符")
        if stripped_line == END_SECTION_MARKER:
            if current_name is None:
                raise ValueError(f"孤立结束标记：第 {line_number} 行没有对应的 SECTION")
            section_template = "\n".join(current_lines).strip()
            if not section_template:
                raise ValueError(f"空分段：'{current_name}' 没有正文")
            sections[current_name] = section_template
            current_name = None
            current_lines = []
            continue
        if stripped_line.startswith(END_SECTION_MARKER_PREFIX):
            raise ValueError(f"非法结束标记：第 {line_number} 行必须精确使用 {END_SECTION_MARKER}")
        if current_name is not None:
            current_lines.append(line)
        elif stripped_line:
            outside_lines.append((line_number, line))

    if current_name is not None:
        raise ValueError(f"未闭合分段：'{current_name}' 缺少 {END_SECTION_MARKER}")

    if sections and outside_lines:
        line_numbers = ", ".join(str(line_number) for line_number, _ in outside_lines[:3])
        raise ValueError(f"段外正文：分段文件的非空正文必须位于 SECTION 内（第 {line_numbers} 行）")

    return sections


def _parse_prompt_metadata(template: str, expected_id: str | None = None) -> tuple[PromptMetadata | None, str]:
    """解析并移除文件顶部的维护元数据。"""
    lines = template.split("\n")
    first_content_line = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_content_line is None:
        return None, template

    first_marker = lines[first_content_line].strip()
    if first_marker != PROMPT_META_START:
        for line_number, line in enumerate(lines, start=1):
            stripped_line = line.strip()
            if stripped_line in {PROMPT_META_START, PROMPT_META_END}:
                raise ValueError("提示词元数据必须位于文件正文之前，且开始/结束标记必须成对出现")
            if stripped_line.startswith(PROMPT_META_MARKER_PREFIXES):
                raise ValueError(f"非法提示词元数据标记：第 {line_number} 行必须精确使用保留标记")
        return None, template

    end_line = next(
        (index for index in range(first_content_line + 1, len(lines)) if lines[index].strip() == PROMPT_META_END),
        None,
    )
    if end_line is None:
        for line_number, line in enumerate(lines[first_content_line + 1 :], start=first_content_line + 2):
            stripped_line = line.strip()
            if stripped_line == PROMPT_META_START:
                raise ValueError(f"多余提示词元数据开始标记：第 {line_number} 行")
            if stripped_line.startswith(PROMPT_META_MARKER_PREFIXES):
                raise ValueError(f"非法提示词元数据标记：第 {line_number} 行必须精确使用保留标记")
        raise ValueError(f"提示词元数据缺少结束标记 {PROMPT_META_END}")

    for line_number, line in enumerate(lines, start=1):
        if line_number in {first_content_line + 1, end_line + 1}:
            continue
        stripped_line = line.strip()
        if stripped_line == PROMPT_META_START:
            raise ValueError(f"多余提示词元数据开始标记：第 {line_number} 行")
        if stripped_line == PROMPT_META_END:
            raise ValueError(f"多余提示词元数据结束标记：第 {line_number} 行")
        if stripped_line.startswith(PROMPT_META_MARKER_PREFIXES):
            raise ValueError(f"非法提示词元数据标记：第 {line_number} 行必须精确使用保留标记")

    values: dict[str, str] = {}
    for line_number, line in enumerate(lines[first_content_line + 1 : end_line], start=first_content_line + 2):
        stripped_line = line.strip()
        if not stripped_line:
            continue
        if ":" not in stripped_line:
            raise ValueError(f"提示词元数据第 {line_number} 行必须使用 'key: value' 格式")
        key, value = (part.strip() for part in stripped_line.split(":", maxsplit=1))
        if key not in PROMPT_META_ALLOWED_KEYS:
            raise ValueError(f"未知提示词元数据字段：{key}")
        if key in values:
            raise ValueError(f"重复提示词元数据字段：{key}")
        if not value:
            raise ValueError(f"提示词元数据字段 '{key}' 不能为空")
        values[key] = value

    missing_keys = sorted(PROMPT_META_REQUIRED_KEYS - values.keys())
    if missing_keys:
        raise ValueError(f"提示词元数据缺少字段：{', '.join(missing_keys)}")

    raw_prompt_id = values["id"]
    prompt_id = normalize_prompt_name(raw_prompt_id)
    if raw_prompt_id != prompt_id:
        raise ValueError("提示词元数据 ID 必须使用不含 .prompt 后缀的规范点分 ID")
    if expected_id is not None and prompt_id != normalize_prompt_name(expected_id):
        raise ValueError(f"ID 不匹配：元数据为 '{prompt_id}'，文件路径对应 '{expected_id}'")
    if values["kind"] not in PROMPT_KINDS:
        raise ValueError(f"未知 kind：{values['kind']}，可选值为 {sorted(PROMPT_KINDS)}")
    if values["status"] not in PROMPT_STATUSES:
        raise ValueError(f"未知 status：{values['status']}，可选值为 {sorted(PROMPT_STATUSES)}")
    for field_name in ("stage", "output"):
        if not SAFE_SEGMENT_PATTERN.fullmatch(values[field_name]):
            raise ValueError(f"提示词元数据字段 '{field_name}' 只能使用字母、数字、下划线或连字符")

    variants: tuple[str, ...] = ()
    if "variants" in values:
        variant_parts = tuple(part.strip() for part in values["variants"].split(","))
        if any(not variant for variant in variant_parts):
            raise ValueError("提示词元数据 variants 包含空分段名")
        variants = variant_parts
    if len(variants) != len(set(variants)):
        raise ValueError("提示词元数据 variants 存在重复分段")
    if any(not SAFE_SEGMENT_PATTERN.fullmatch(variant) for variant in variants):
        raise ValueError("提示词元数据 variants 只能使用合法分段名")

    body = "\n".join(lines[end_line + 1 :])
    metadata = PromptMetadata(
        prompt_id=prompt_id,
        kind=values["kind"],
        stage=values["stage"],
        status=values["status"],
        summary=values["summary"],
        output=values["output"],
        variants=variants,
    )
    return metadata, body


def parse_prompt_document(
    template: str,
    *,
    expected_id: str | None = None,
    require_metadata: bool = False,
) -> PromptDocument:
    """解析提示词维护元数据、运行时正文和命名分段。"""
    metadata, runtime_template = _parse_prompt_metadata(template, expected_id=expected_id)
    if require_metadata and metadata is None:
        raise ValueError("提示词缺少 PROMPT_META 维护元数据")
    if not runtime_template.strip():
        raise ValueError("提示词正文为空")

    sections = parse_prompt_sections(runtime_template)
    if metadata is not None and metadata.variants != tuple(sections):
        raise ValueError(f"分段声明不一致：元数据 variants={list(metadata.variants)}，实际 sections={list(sections)}")
    return PromptDocument(template=runtime_template, sections=sections, metadata=metadata)


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
    sections = load_prompt_document(name).sections
    if section not in sections:
        raise KeyError(f"段 '{section}' 不存在于提示词 '{name}' 中（可用段: {list(sections.keys())}）")
    return sections[section].format(**kwargs)


def get_prompt_cache_revision() -> int:
    """获取当前缓存修订号

    Returns:
        当前修订号
    """
    return _PROMPT_CACHE_REVISION
