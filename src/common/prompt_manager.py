"""PromptManager 单例：提示词管理器

提供全局的提示词模板管理能力，通过 load_prompts() 一次性加载所有 .prompt 文件，
通过 get_prompt() / format_prompt() 获取模板或格式化结果。

支持热重载：提示词文件发生变化时自动更新，缓存修订号变化时全量重新加载。
提供 safe_get_prompt() 作为降级兜底，避免未找到提示词时抛出异常。
"""

import contextvars
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Mapping

from src.common.logger import get_logger
from src.common.prompt_loader import (
    PromptDocument,
    PromptMetadata,
    clear_prompt_cache,
    get_prompt_cache_revision,
    load_prompt_document,
    list_prompt_templates,
)

logger = get_logger("prompt_mgr")

_ESCAPED_LEFT_BRACE = "__MAIBOT_ESCAPED_LEFT_BRACE__"
_ESCAPED_RIGHT_BRACE = "__MAIBOT_ESCAPED_RIGHT_BRACE__"

LEGACY_PROMPT_ALIASES = {
    # 旧文件 ID
    "audio_transcription": "media.audio.transcription",
    "chat.private.reply": "chat.private.reply.default",
    "chat.private.reply_self": "chat.private.reply.self",
    "chat.private.tool_planner": "chat.private.planner",
    "default_expressor_prompt": "chat.shared.expressor",
    "emoji_content_filter": "media.emoji.content_filter",
    "emoji_replace_decision": "media.emoji.replace_decision",
    "emoji_selection": "media.emoji.selection",
    "expression_auto_check": "learning.expression.auto_check",
    "expression_evaluation": "learning.expression.evaluation",
    "expression_evaluation_prompt": "learning.expression.evaluation",
    "expression_situation_summary": "learning.expression.situation_summary",
    "jargon_compare_inference": "learning.jargon.compare_inference",
    "jargon_explainer_summarize": "learning.jargon.explainer_summarize",
    "jargon_inference_content_only": "learning.jargon.inference_content_only",
    "jargon_inference_with_context": "learning.jargon.inference_with_context",
    "learn_behavior": "learning.behavior.learn",
    "learn_style": "learning.expression.learn_style",
    "lpmm_get_knowledge_prompt": "memory.knowledge_query",
    "memory_atom_extraction": "memory.atom_extraction",
    "memory_noise_insight": "memory.noise_insight",
    "memory_topic_judge": "memory.topic_judge",
    "pfc_goal_analyzer": "chat.private.pfc.goal_analyzer",
    "pfc_goal_analyzer_assess": "chat.private.pfc.goal_assessment",
    "pfc_reply_check": "chat.private.pfc.reply_check",
    "planner_prompt": "chat.group.planner",
    "private_replyer_prompt": "chat.private.reply.default",
    "private_replyer_self_prompt": "chat.private.reply.self",
    "reflect_judge": "learning.expression.reflect_judge",
    "tool_executor": "shared.tool_executor",
    # 旧分段 ID，以及旧管理器曾暴露的裸分段名
    "replyer_group.replyer_prompt_0": "chat.group.reply.light",
    "replyer_group.replyer_prompt": "chat.group.reply.standard",
    "replyer_prompt_0": "chat.group.reply.light",
    "replyer_prompt": "chat.group.reply.standard",
    "emoji_vlm_description.gif": "media.emoji.vision_description.gif",
    "emoji_vlm_description.gif_batch": "media.emoji.vision_description.gif_batch",
    "emoji_vlm_description.gif_overall": "media.emoji.vision_description.gif_overall",
    "emoji_vlm_description.static": "media.emoji.vision_description.static",
    "emoji_vlm_description.static_detailed": "media.emoji.vision_description.static_detailed",
    "gif": "media.emoji.vision_description.gif",
    "gif_batch": "media.emoji.vision_description.gif_batch",
    "gif_overall": "media.emoji.vision_description.gif_overall",
    "static": "media.emoji.vision_description.static",
    "static_detailed": "media.emoji.vision_description.static_detailed",
    "jargon_previous_meaning.context": "learning.jargon.previous_meaning.context",
    "jargon_previous_meaning.instruction": "learning.jargon.previous_meaning.instruction",
    "context": "learning.jargon.previous_meaning.context",
    "instruction": "learning.jargon.previous_meaning.instruction",
    "memory_retrieval.question": "memory.retrieval.question",
    "memory_retrieval.react_head": "memory.retrieval.react_head",
    "memory_retrieval.final": "memory.retrieval.final",
    "question": "memory.retrieval.question",
    "react_head": "memory.retrieval.react_head",
    "final": "memory.retrieval.final",
    "moderation.standard": "shared.moderation.standard",
    "moderation.strict": "shared.moderation.strict",
    "standard": "shared.moderation.standard",
    "strict": "shared.moderation.strict",
    "pfc_action_decision.initial_reply": "chat.private.pfc.action_decision.initial_reply",
    "pfc_action_decision.follow_up": "chat.private.pfc.action_decision.follow_up",
    "pfc_action_decision.end_decision": "chat.private.pfc.action_decision.end_decision",
    "initial_reply": "chat.private.pfc.action_decision.initial_reply",
    "follow_up": "chat.private.pfc.action_decision.follow_up",
    "end_decision": "chat.private.pfc.action_decision.end_decision",
    "pfc_reply_generation.direct_reply": "chat.private.pfc.reply_generation.direct_reply",
    "pfc_reply_generation.send_new_message": "chat.private.pfc.reply_generation.send_new_message",
    "pfc_reply_generation.farewell": "chat.private.pfc.reply_generation.farewell",
    "direct_reply": "chat.private.pfc.reply_generation.direct_reply",
    "send_new_message": "chat.private.pfc.reply_generation.send_new_message",
    "farewell": "chat.private.pfc.reply_generation.farewell",
}


@dataclass(frozen=True)
class PromptSource:
    file_name: str
    section_name: str | None = None


def _build_document_entries(
    file_name: str,
    document: PromptDocument,
) -> tuple[dict[str, str], dict[str, PromptSource], dict[str, PromptMetadata]]:
    """将一个提示词文件展开为运行时 ID、来源和元数据。"""
    prompts: dict[str, str] = {}
    sources: dict[str, PromptSource] = {}
    metadata: dict[str, PromptMetadata] = {}

    if document.sections:
        for section_name, section_template in document.sections.items():
            prompt_id = f"{file_name}.{section_name}"
            prompts[prompt_id] = section_template
            sources[prompt_id] = PromptSource(file_name, section_name)
            if document.metadata is not None:
                metadata[prompt_id] = document.metadata
    else:
        prompts[file_name] = document.template
        sources[file_name] = PromptSource(file_name)
        if document.metadata is not None:
            metadata[file_name] = document.metadata

    return prompts, sources, metadata


def format_prompt_template(template: str, /, **kwargs) -> str:
    """格式化模板，同时兼容旧动态模板使用的反斜杠转义花括号。"""
    escaped_template = template.replace("\\{", _ESCAPED_LEFT_BRACE).replace("\\}", _ESCAPED_RIGHT_BRACE)
    return escaped_template.format(**kwargs).replace(_ESCAPED_LEFT_BRACE, "{").replace(_ESCAPED_RIGHT_BRACE, "}")


class PromptManager:
    """提示词管理器单例"""

    def __init__(self, aliases: Mapping[str, str] | None = None):
        self._prompts: dict[str, str] = {}  # name → template string
        self._sources: dict[str, PromptSource] = {}
        self._metadata: dict[str, PromptMetadata] = {}
        self._aliases = dict(aliases or {})
        self._context_prompts: dict[str, dict[str, str]] = {}
        self._current_context = contextvars.ContextVar[str | None]("prompt_context", default=None)
        self._counter = 0
        self._cache_revision: int = 0
        self._loaded: bool = False

    def load_prompts(self) -> None:
        """加载 prompts/ 目录下所有 .prompt 文件到内存

        扫描 prompts/ 目录，加载每个 .prompt 文件，建立名称→模板的映射。
        """
        prompts: dict[str, str] = {}
        sources: dict[str, PromptSource] = {}
        metadata: dict[str, PromptMetadata] = {}

        for file_name in list_prompt_templates():
            entries, entry_sources, entry_metadata = _build_document_entries(
                file_name,
                load_prompt_document(file_name),
            )
            duplicate_ids = prompts.keys() & entries.keys()
            if duplicate_ids:
                duplicates = ", ".join(sorted(duplicate_ids))
                raise ValueError(f"提示词运行时 ID 冲突：{duplicates}")
            prompts.update(entries)
            sources.update(entry_sources)
            metadata.update(entry_metadata)

        self._prompts = prompts
        self._sources = sources
        self._metadata = metadata
        self._cache_revision = get_prompt_cache_revision()
        self._loaded = True
        logger.debug(f"已加载 {len(self._prompts)} 个提示词模板")

    def _resolve_name(self, name: str) -> str:
        resolved = name
        visited: set[str] = set()
        while resolved in self._aliases:
            if resolved in visited:
                raise ValueError(f"提示词别名存在循环引用: {name}")
            visited.add(resolved)
            resolved = self._aliases[resolved]
        return resolved

    def register_context_prompts(self, context_id: str, templates: Mapping[str, str]) -> None:
        """注册一组按聊天模板名称隔离的覆盖提示词。"""
        context_prompts = self._context_prompts.setdefault(context_id, {})
        for name, template in templates.items():
            context_prompts[self._resolve_name(name)] = str(template)

    @property
    def current_context_id(self) -> str | None:
        return self._current_context.get()

    @property
    def prompt_count(self) -> int:
        """返回当前已注册的规范提示词 ID 数量。"""
        return len(self._prompts)

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def register_prompt(self, template: str, name: str | None = None) -> str:
        """注册内存提示词，主要用于兼容运行时动态模板。"""
        if name is None:
            self._counter += 1
            name = f"prompt_{self._counter}"
        resolved_name = self._resolve_name(name)
        self._prompts[resolved_name] = str(template)
        self._sources.pop(resolved_name, None)
        self._metadata.pop(resolved_name, None)
        return resolved_name

    def add_prompt(self, name: str, template: str) -> str:
        return self.register_prompt(template, name=name)

    def register_context_prompt(self, name: str, template: str, context_id: str | None = None) -> None:
        target_context = context_id or self.current_context_id
        if target_context is None:
            self.register_prompt(template, name=name)
            return
        self.register_context_prompts(target_context, {name: template})

    @asynccontextmanager
    async def async_message_scope(self, context_id: str | None = None):
        """在当前协程中启用指定聊天模板上下文。"""
        if context_id is None:
            yield self
            return
        token = self._current_context.set(context_id)
        try:
            yield self
        finally:
            self._current_context.reset(token)

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
        resolved_name = self._resolve_name(name)
        context_id = self._current_context.get()
        if context_id is not None:
            context_prompt = self._context_prompts.get(context_id, {}).get(resolved_name)
            if context_prompt is not None:
                return context_prompt

        if not self._loaded and not self._prompts:
            self.load_prompts()

        self._reload_prompt_if_changed(resolved_name)
        if resolved_name not in self._prompts:
            raise KeyError(f"提示词 '{name}' 未找到，可用提示词: {list(self._prompts.keys())}")
        return self._prompts[resolved_name]

    def format_prompt(self, name: str, /, **kwargs) -> str:
        """加载模板并使用 kwargs 格式化

        Args:
            name: 提示词名称
            **kwargs: 格式化参数

        Returns:
            格式化后的字符串
        """
        template = self.get_prompt(name)
        return format_prompt_template(template, **kwargs)

    def get_prompt_metadata(self, name: str, /) -> PromptMetadata:
        """返回规范文件来源的职责、阶段和生命周期元数据。

        上下文覆盖只替换运行时模板，不会替换或隐藏其规范文件元数据。
        """
        self._reload_if_changed()
        resolved_name = self._resolve_name(name)
        if not self._loaded and not self._prompts:
            self.load_prompts()
        self._reload_prompt_if_changed(resolved_name)
        if resolved_name not in self._metadata:
            raise KeyError(f"提示词 '{name}' 没有规范文件元数据；纯动态提示词不提供该信息")
        return self._metadata[resolved_name]

    async def get_prompt_async(self, name: str) -> str:
        """兼容旧异步调用；模板读取本身不执行异步 I/O。"""
        return self.get_prompt(name)

    def _reload_if_changed(self) -> None:
        """检测缓存修订号是否变化，如有变化则自动重载所有提示词"""
        if not self._loaded:
            return
        current = get_prompt_cache_revision()
        if current != self._cache_revision:
            logger.info(f"检测到提示词缓存修订号变化 ({self._cache_revision} → {current})，正在重载...")
            self.load_prompts()

    def _reload_prompt_if_changed(self, name: str) -> None:
        """按文件原子重建目标提示词及其全部分段。"""
        source = self._sources.get(name)
        if source is None and name in self._prompts:
            return
        file_name = source.file_name if source is not None else self._find_source_file(name)
        if file_name is None:
            return

        try:
            document = load_prompt_document(file_name)
        except FileNotFoundError:
            self._replace_file_entries(file_name, {}, {}, {})
            return

        entries, entry_sources, entry_metadata = _build_document_entries(file_name, document)
        self._replace_file_entries(file_name, entries, entry_sources, entry_metadata)

    def _find_source_file(self, name: str) -> str | None:
        """为尚未注册的分段或新文件定位规范文件 ID。"""
        known_files = {source.file_name for source in self._sources.values()}
        candidate_files = known_files | set(list_prompt_templates())
        matches = [file_name for file_name in candidate_files if name == file_name or name.startswith(f"{file_name}.")]
        return max(matches, key=len, default=None)

    def _replace_file_entries(
        self,
        file_name: str,
        entries: dict[str, str],
        sources: dict[str, PromptSource],
        metadata: dict[str, PromptMetadata],
    ) -> None:
        """在完整解析成功后一次替换同一文件导出的所有运行时 ID。"""
        dynamic_override_ids = {
            prompt_id for prompt_id in entries if prompt_id in self._prompts and prompt_id not in self._sources
        }
        if dynamic_override_ids:
            entries = {
                prompt_id: value for prompt_id, value in entries.items() if prompt_id not in dynamic_override_ids
            }
            sources = {
                prompt_id: value for prompt_id, value in sources.items() if prompt_id not in dynamic_override_ids
            }
            metadata = {
                prompt_id: value for prompt_id, value in metadata.items() if prompt_id not in dynamic_override_ids
            }

        old_ids = {prompt_id for prompt_id, source in self._sources.items() if source.file_name == file_name}
        duplicate_ids = (self._prompts.keys() - old_ids) & entries.keys()
        if duplicate_ids:
            duplicates = ", ".join(sorted(duplicate_ids))
            raise ValueError(f"提示词运行时 ID 冲突：{duplicates}")

        current_entries = {prompt_id: self._prompts[prompt_id] for prompt_id in old_ids}
        current_sources = {prompt_id: self._sources[prompt_id] for prompt_id in old_ids}
        current_metadata = {
            prompt_id: self._metadata[prompt_id] for prompt_id in old_ids if prompt_id in self._metadata
        }
        if current_entries == entries and current_sources == sources and current_metadata == metadata:
            return

        next_prompts = {
            prompt_id: template for prompt_id, template in self._prompts.items() if prompt_id not in old_ids
        }
        next_sources = {prompt_id: source for prompt_id, source in self._sources.items() if prompt_id not in old_ids}
        next_metadata = {prompt_id: value for prompt_id, value in self._metadata.items() if prompt_id not in old_ids}
        next_prompts.update(entries)
        next_sources.update(sources)
        next_metadata.update(metadata)

        self._prompts = next_prompts
        self._sources = next_sources
        self._metadata = next_metadata
        logger.info(f"检测到提示词文件变化，已热重载: {file_name}")


# 全局单例
prompt_manager = PromptManager(aliases=LEGACY_PROMPT_ALIASES)


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
