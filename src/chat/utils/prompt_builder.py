"""旧提示词 API 的无状态兼容入口。

新代码应直接使用 :mod:`src.common.prompt_manager`。本模块只保留旧异步调用形态
和 ``Prompt`` 模板对象，所有模板、缓存和上下文状态都由公共 ``PromptManager`` 持有。
"""

import re
from contextlib import asynccontextmanager
from typing import Any, List, Optional, Union

from src.common.logger import get_logger
from src.common.prompt_manager import PromptManager, prompt_manager

logger = get_logger("prompt_build")


class _LegacyPromptContextAdapter:
    def __init__(self, manager: PromptManager):
        self.manager = manager

    @property
    def _current_context(self) -> str | None:
        return self.manager.current_context_id

    async def register_async(self, prompt: "Prompt", context_id: str | None = None) -> None:
        target_context = context_id or self.manager.current_context_id
        if target_context is None:
            return
        if not prompt.name:
            raise ValueError("上下文提示词必须提供名称")
        self.manager.register_context_prompt(prompt.name, prompt.template, context_id=target_context)


class LegacyPromptManagerAdapter:
    """保留旧异步方法签名，但不持有任何提示词状态。"""

    def __init__(self, manager: PromptManager):
        self.manager = manager
        self._context = _LegacyPromptContextAdapter(manager)

    @asynccontextmanager
    async def async_message_scope(self, message_id: str | None = None):
        async with self.manager.async_message_scope(message_id):
            yield self

    async def get_prompt_async(self, name: str) -> "Prompt":
        return Prompt(self.manager.get_prompt(name), name=name, _should_register=False)

    async def format_prompt(self, name: str, **kwargs) -> str:
        return self.manager.format_prompt(name, **kwargs)

    def register(self, prompt: "Prompt") -> None:
        prompt.name = self.manager.register_prompt(prompt.template, name=prompt.name)

    def add_prompt(self, name: str, template: str) -> "Prompt":
        prompt = Prompt(template, name=name, _should_register=False)
        self.register(prompt)
        return prompt


global_prompt_manager = LegacyPromptManagerAdapter(prompt_manager)


def init_external_prompts() -> int:
    """兼容旧启动入口；公共管理器已经直接加载外部模板。"""
    if not prompt_manager.is_loaded:
        prompt_manager.load_prompts()
    return prompt_manager.prompt_count


class Prompt(str):
    _TEMP_LEFT_BRACE = "__ESCAPED_LEFT_BRACE__"
    _TEMP_RIGHT_BRACE = "__ESCAPED_RIGHT_BRACE__"

    @staticmethod
    def _process_escaped_braces(template) -> str:
        if isinstance(template, list):
            template = "\n".join(str(item) for item in template)
        elif not isinstance(template, str):
            template = str(template)
        return template.replace("\\{", Prompt._TEMP_LEFT_BRACE).replace("\\}", Prompt._TEMP_RIGHT_BRACE)

    @staticmethod
    def _restore_escaped_braces(template: str) -> str:
        return template.replace(Prompt._TEMP_LEFT_BRACE, "{").replace(Prompt._TEMP_RIGHT_BRACE, "}")

    def __new__(
        cls,
        fstr,
        name: Optional[str] = None,
        args: Union[List[Any], tuple[Any, ...], None] = None,
        **kwargs,
    ):
        if isinstance(args, tuple):
            args = list(args)
        should_register = kwargs.pop("_should_register", True)
        processed_fstr = cls._process_escaped_braces(fstr)

        template_args = []
        for expr in re.findall(r"\{(.*?)}", processed_fstr):
            if expr and expr not in template_args:
                template_args.append(expr)

        if kwargs or args:
            formatted = cls._format_template(fstr, args=args, kwargs=kwargs)
            obj = super().__new__(cls, formatted)
        else:
            obj = super().__new__(cls, "")

        obj.template = fstr
        obj.name = name
        obj.args = template_args
        obj._args = args or []
        obj._kwargs = kwargs

        manager = getattr(global_prompt_manager, "manager", global_prompt_manager)
        if should_register and manager.current_context_id is None:
            obj.name = manager.register_prompt(obj.template, name=obj.name)
        return obj

    @classmethod
    async def create_async(
        cls,
        fstr,
        name: Optional[str] = None,
        args: Union[List[Any], tuple[Any, ...], None] = None,
        **kwargs,
    ):
        prompt = cls(fstr, name, args, **kwargs)
        manager = getattr(global_prompt_manager, "manager", global_prompt_manager)
        if manager.current_context_id:
            if not prompt.name:
                raise ValueError("上下文提示词必须提供名称")
            manager.register_context_prompt(prompt.name, prompt.template)
        return prompt

    @classmethod
    def _format_template(
        cls,
        template,
        args: Optional[List[Any]] = None,
        kwargs: Optional[dict[str, Any]] = None,
    ) -> str:
        processed_template = cls._process_escaped_braces(template)
        template_args = []
        for expr in re.findall(r"\{(.*?)}", processed_template):
            if expr and expr not in template_args:
                template_args.append(expr)

        formatted_args = {}
        if args:
            for index, arg in enumerate(args):
                if index >= len(template_args):
                    logger.error(
                        f"构建提示词模板失败，解析到的参数列表{template_args}，长度为{len(template_args)}，"
                        f"输入的参数列表为{args}，提示词模板为{template}"
                    )
                    raise ValueError("格式化模板失败")
                formatted_args[template_args[index]] = arg.format(**(kwargs or {})) if isinstance(arg, Prompt) else arg

        formatted_kwargs = {}
        if kwargs:
            for key, value in kwargs.items():
                if isinstance(value, Prompt):
                    remaining_kwargs = {item_key: item for item_key, item in kwargs.items() if item_key != key}
                    formatted_kwargs[key] = value.format(**remaining_kwargs)
                else:
                    formatted_kwargs[key] = value

        try:
            if args:
                processed_template = processed_template.format(**formatted_args)
            if kwargs:
                processed_template = processed_template.format(**formatted_kwargs)
            return cls._restore_escaped_braces(processed_template)
        except (IndexError, KeyError) as exc:
            raise ValueError(
                f"格式化模板失败: {template}, args={formatted_args}, kwargs={formatted_kwargs} {exc}"
            ) from exc

    def format(self, *args, **kwargs) -> str:
        return self._format_template(
            self.template,
            args=list(args) if args else self._args,
            kwargs=kwargs or self._kwargs,
        )

    def __str__(self) -> str:
        return super().__str__() if self._kwargs or self._args else self.template

    def __repr__(self) -> str:
        return f"Prompt(template='{self.template}', name='{self.name}')"
