import string
import unittest

from src.common.prompt_loader import (
    list_prompt_templates,
    load_prompt,
    load_prompt_section,
    load_prompt_template,
    parse_prompt_sections,
)


PROMPT_IDS = {
    "chat.group.action",
    "chat.group.planner",
    "chat.group.reply",
    "chat.group.reply_action",
    "chat.private.action",
    "chat.private.pfc.action_decision",
    "chat.private.pfc.goal_analyzer",
    "chat.private.pfc.goal_assessment",
    "chat.private.pfc.reply_check",
    "chat.private.pfc.reply_generation",
    "chat.private.planner",
    "chat.private.reply",
    "chat.private.reply_self",
    "chat.shared.expressor",
    "learning.behavior.learn",
    "learning.expression.auto_check",
    "learning.expression.evaluation",
    "learning.expression.learn_style",
    "learning.expression.reflect_judge",
    "learning.expression.situation_summary",
    "learning.jargon.compare_inference",
    "learning.jargon.explainer_summarize",
    "learning.jargon.inference_content_only",
    "learning.jargon.inference_with_context",
    "learning.jargon.previous_meaning",
    "media.audio.transcription",
    "media.emoji.content_filter",
    "media.emoji.core_emotion",
    "media.emoji.emotion_analysis",
    "media.emoji.replace_decision",
    "media.emoji.selection",
    "media.emoji.vision_description",
    "memory.atom_extraction",
    "memory.knowledge_query",
    "memory.noise_insight",
    "memory.retrieval",
    "memory.topic_judge",
    "shared.moderation",
    "shared.tool_executor",
}

SECTION_NAMES = {
    "chat.group.reply": {"light", "standard"},
    "chat.group.reply_action": {"without_quote", "with_quote"},
    "chat.private.pfc.action_decision": {"initial_reply", "follow_up", "end_decision"},
    "chat.private.pfc.reply_generation": {"direct_reply", "send_new_message", "farewell"},
    "learning.jargon.previous_meaning": {"context", "instruction"},
    "media.emoji.vision_description": {"gif", "gif_batch", "gif_overall", "static", "static_detailed"},
    "memory.retrieval": {"question", "react_head", "final"},
    "shared.moderation": {"standard", "strict"},
}


def _format_kwargs(template: str) -> dict[str, str]:
    formatter = string.Formatter()
    field_names: set[str] = set()
    for _, field_name, _, _ in formatter.parse(template):
        if field_name is None:
            continue
        root_name = field_name.split(".", maxsplit=1)[0].split("[", maxsplit=1)[0]
        if not root_name or root_name.isdecimal():
            raise AssertionError(f"模板只能使用命名格式化变量，发现: {field_name!r}")
        field_names.add(root_name)
    return {field_name: f"__{field_name.upper()}__" for field_name in field_names}


class PromptTemplateContractTest(unittest.TestCase):
    def test_prompt_inventory_matches_repository_contract(self) -> None:
        self.assertEqual(set(list_prompt_templates()), PROMPT_IDS)

    def test_every_template_and_section_formats_with_named_placeholders(self) -> None:
        for name in sorted(PROMPT_IDS):
            with self.subTest(prompt=name):
                template = load_prompt_template(name)
                self.assertTrue(template.strip())
                kwargs = _format_kwargs(template)
                self.assertTrue(load_prompt(name, **kwargs).strip())

                sections = parse_prompt_sections(template)
                self.assertEqual(set(sections), SECTION_NAMES.get(name, set()))
                for section in sections:
                    self.assertTrue(load_prompt_section(name, section, **kwargs).strip())


if __name__ == "__main__":
    unittest.main()
