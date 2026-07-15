"""WebUI 文件路径边界校验工具。"""

from pathlib import Path


def resolve_path_within(base_path: Path, *parts: str) -> Path:
    """解析路径并确保最终目标仍位于指定根目录内。"""
    resolved_base = base_path.resolve()
    resolved_path = resolved_base.joinpath(*parts).resolve()
    if not resolved_path.is_relative_to(resolved_base):
        raise ValueError("路径超出允许目录")
    return resolved_path
