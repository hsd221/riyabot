import string
import unittest

from src.common.prompt_loader import (
    list_prompt_templates,
    load_prompt,
    load_prompt_section,
    load_prompt_template,
    parse_prompt_sections,
)


PROMPT_NAMES = {
    "action_prompt",
    "audio_transcription",
    "brain_action_prompt",
    "brain_planner_prompt_react",
    "default_expressor_prompt",
    "dream_react_head",
    "dream_summary",
    "emoji_content_filter",
    "emoji_core_emotion",
    "emoji_emotion_analysis",
    "emoji_replace_decision",
    "emoji_selection",
    "emoji_vlm_description",
    "entity_extract_system",
    "expression_auto_check",
    "expression_evaluation",
    "expression_situation_summary",
    "hippo_topic_analysis",
    "hippo_topic_summary",
    "jargon_compare_inference",
    "jargon_explainer_summarize",
    "jargon_inference_content_only",
    "jargon_inference_with_context",
    "jargon_previous_meaning",
    "learn_behavior",
    "learn_style",
    "lpmm_get_knowledge_prompt",
    "memory_atom_extraction",
    "memory_noise_insight",
    "memory_retrieval",
    "memory_topic_judge",
    "moderation",
    "person_nickname",
    "pfc_action_decision",
    "pfc_goal_analyzer",
    "pfc_goal_analyzer_assess",
    "pfc_reply_check",
    "pfc_reply_generation",
    "planner_prompt",
    "planner_reply_action",
    "private_replyer_prompt",
    "private_replyer_self_prompt",
    "qa_system",
    "rdf_triple_extract_system",
    "reflect_judge",
    "replyer_group",
    "tool_executor",
}

SECTION_NAMES = {
    "emoji_vlm_description": {"gif", "gif_batch", "gif_overall", "static", "static_detailed"},
    "jargon_previous_meaning": {"context", "instruction"},
    "memory_retrieval": {"question", "react_head", "final"},
    "moderation": {"standard", "strict"},
    "pfc_action_decision": {"initial_reply", "follow_up", "end_decision"},
    "pfc_reply_generation": {"direct_reply", "send_new_message", "farewell"},
    "planner_reply_action": {"without_quote", "with_quote"},
    "replyer_group": {"replyer_prompt_0", "replyer_prompt"},
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
        self.assertEqual(set(list_prompt_templates()), PROMPT_NAMES)

    def test_every_template_and_section_formats_with_named_placeholders(self) -> None:
        for name in sorted(PROMPT_NAMES):
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
