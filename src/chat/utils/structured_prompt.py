"""将聊天主链的完整可读 Prompt 映射为有角色的 LLM 消息。"""

from dataclasses import dataclass


DYNAMIC_CONTEXT_BOUNDARY = "<!-- RIYABOT_DYNAMIC_CONTEXT -->"


@dataclass(frozen=True, slots=True)
class StructuredPrompt:
    """拆分后的系统约束与本轮动态输入。"""

    system_prompt: str | None
    user_prompt: str

    def as_request_kwargs(self) -> dict[str, str]:
        """构造 ``LLMRequest.generate_response_async`` 的兼容关键字参数。"""

        kwargs = {"prompt": self.user_prompt}
        if self.system_prompt is not None:
            kwargs["system_prompt"] = self.system_prompt
        return kwargs


def split_chat_prompt(prompt: str) -> StructuredPrompt:
    """按受控边界拆分 Prompt；不完整或被插件重写时保持旧的单 user 行为。"""

    if prompt.count(DYNAMIC_CONTEXT_BOUNDARY) != 1:
        return StructuredPrompt(system_prompt=None, user_prompt=prompt)

    system_prompt, user_prompt = prompt.split(DYNAMIC_CONTEXT_BOUNDARY, maxsplit=1)
    system_prompt = system_prompt.strip()
    user_prompt = user_prompt.strip()
    if not system_prompt or not user_prompt:
        return StructuredPrompt(system_prompt=None, user_prompt=prompt)

    return StructuredPrompt(system_prompt=system_prompt, user_prompt=user_prompt)
