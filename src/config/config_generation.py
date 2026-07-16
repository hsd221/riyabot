from __future__ import annotations

import ast
import inspect
import textwrap
from dataclasses import fields, is_dataclass
from functools import lru_cache
from typing import Any

import tomlkit
from tomlkit import TOMLDocument

from src.common.toml_utils import format_toml_string
from src.config.config_base import ConfigBase


@lru_cache(maxsize=None)
def _field_documents(config_type: type[ConfigBase]) -> dict[str, str]:
    """读取字段声明后紧邻的字符串，作为生成配置时的说明。"""
    try:
        source = textwrap.dedent(inspect.getsource(config_type))
        module = ast.parse(source)
    except (OSError, TypeError, SyntaxError):
        return {}

    class_node = next((node for node in module.body if isinstance(node, ast.ClassDef)), None)
    if class_node is None:
        return {}

    documents: dict[str, str] = {}
    for index, node in enumerate(class_node.body[:-1]):
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        following = class_node.body[index + 1]
        if not isinstance(following, ast.Expr) or not isinstance(following.value, ast.Constant):
            continue
        if isinstance(following.value.value, str):
            documents[node.target.id] = inspect.cleandoc(following.value.value)
    return documents


def _toml_item(value: Any) -> Any:
    if value is None:
        raise TypeError("TOML 不支持 None，请为可生成的配置字段提供明确默认值")
    if isinstance(value, set):
        value = sorted(value)
    if isinstance(value, (list, tuple)):
        array = tomlkit.array()
        for item in value:
            array.append(_toml_item(item))
        return array
    if isinstance(value, dict):
        inline = tomlkit.inline_table()
        for key, item in value.items():
            inline[key] = _toml_item(item)
        return inline
    if is_dataclass(value):
        return _toml_item(
            {
                config_field.name: getattr(value, config_field.name)
                for config_field in fields(value)
                if config_field.init and not config_field.name.startswith("_")
            }
        )
    if isinstance(value, str) and "\n" in value:
        return tomlkit.string(value, multiline=True)
    return tomlkit.item(value)


def _add_documentation(container: Any, documentation: str | None) -> None:
    if not documentation:
        return
    for line in documentation.splitlines():
        if stripped := line.strip():
            container.add(tomlkit.comment(stripped))


def _populate_dataclass(container: Any, config: ConfigBase) -> None:
    documents = _field_documents(type(config))
    for config_field in fields(config):
        if not config_field.init or config_field.name.startswith("_"):
            continue
        value = getattr(config, config_field.name)
        _add_config_field(container, config_field.name, value, documents.get(config_field.name))


def _add_config_field(container: Any, name: str, value: Any, documentation: str | None) -> None:
    _add_documentation(container, documentation)
    if isinstance(value, ConfigBase):
        nested = tomlkit.table()
        _populate_dataclass(nested, value)
        container.add(name, nested)
    else:
        container.add(name, _toml_item(value))


def build_config_document(config: ConfigBase, version: str) -> TOMLDocument:
    """从配置对象及字段文档构建可编辑的 TOML 文档。"""
    document = tomlkit.document()
    document.add(tomlkit.comment("此文件由 Python 配置定义生成；字段说明来自对应字段后的文档字符串。"))
    document.add(tomlkit.nl())

    documents = _field_documents(type(config))
    root_fields = [
        config_field for config_field in fields(config) if config_field.init and not config_field.name.startswith("_")
    ]
    scalar_fields = [
        config_field for config_field in root_fields if not isinstance(getattr(config, config_field.name), ConfigBase)
    ]
    table_fields = [
        config_field for config_field in root_fields if isinstance(getattr(config, config_field.name), ConfigBase)
    ]

    for config_field in scalar_fields:
        _add_config_field(
            document,
            config_field.name,
            getattr(config, config_field.name),
            documents.get(config_field.name),
        )
    if scalar_fields:
        document.add(tomlkit.nl())

    inner = tomlkit.table()
    inner.add(tomlkit.comment("配置结构版本；升级时由程序自动维护。"))
    inner.add("version", version)
    document.add("inner", inner)
    for config_field in table_fields:
        _add_config_field(
            document,
            config_field.name,
            getattr(config, config_field.name),
            documents.get(config_field.name),
        )
    return document


def render_config_toml(config: ConfigBase, version: str) -> str:
    return format_toml_string(build_config_document(config, version))
