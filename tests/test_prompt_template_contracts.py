import re
import string
import unittest
from pathlib import Path

from src.common.prompt_loader import (
    list_prompt_templates,
    load_prompt,
    load_prompt_document,
    load_prompt_section,
    load_prompt_template,
    parse_prompt_sections,
)


PROMPT_IDS = {
    "chat.group.planner",
    "chat.group.reply",
    "chat.private.pfc.action_decision",
    "chat.private.pfc.goal_analyzer",
    "chat.private.pfc.goal_assessment",
    "chat.private.pfc.reply_check",
    "chat.private.pfc.reply_generation",
    "chat.private.planner",
    "chat.private.reply",
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
    "media.emoji.replace_decision",
    "media.emoji.selection",
    "media.emoji.semantic_description",
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
    "chat.private.reply": {"default", "self"},
    "chat.private.pfc.action_decision": {"initial_reply", "follow_up", "end_decision"},
    "chat.private.pfc.reply_generation": {"direct_reply", "send_new_message", "farewell"},
    "learning.jargon.previous_meaning": {"context", "instruction"},
    "media.emoji.vision_description": {"gif", "gif_batch", "gif_overall", "static", "static_detailed"},
    "memory.retrieval": {"question", "react_head", "final"},
    "shared.moderation": {"standard", "strict"},
}

PROMPT_README = Path(__file__).resolve().parents[1] / "prompts" / "README.md"

MESSAGE_MAINLINE_PROMPT_IDS = {
    "chat.group.planner",
    "chat.group.reply",
    "chat.private.planner",
    "chat.private.reply",
}

LAYERED_MAINLINE_PROMPTS = (
    ("chat.group.planner", None),
    ("chat.group.reply", "light"),
    ("chat.group.reply", "standard"),
    ("chat.private.planner", None),
    ("chat.private.reply", "default"),
    ("chat.private.reply", "self"),
)

LAYERED_EXPLICIT_API_PROMPTS = (
    ("chat.shared.expressor", None),
    ("shared.tool_executor", None),
)

FRAGMENT_PROMPT_IDS = {
    "learning.jargon.previous_meaning",
    "shared.moderation",
}
FALLBACK_PROMPT_IDS: set[str] = set()
LEGACY_PROMPT_IDS = {
    "chat.private.pfc.action_decision",
    "chat.private.pfc.goal_analyzer",
    "chat.private.pfc.goal_assessment",
    "chat.private.pfc.reply_check",
    "chat.private.pfc.reply_generation",
}
PROMPT_STAGES = {
    "evaluation",
    "generation",
    "learning",
    "memory",
    "perception",
    "planning",
    "policy",
    "transcription",
}
PROMPT_OUTPUTS = {
    "fragment",
    "label",
    "mixed",
    "native_tool",
    "plain_text",
    "reasoned_jsonl",
    "strict_json",
    "transcript",
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

    def test_message_mainline_contains_exactly_four_prompt_files(self) -> None:
        active_message_prompts = {
            name
            for name in PROMPT_IDS
            if name.startswith(("chat.group.", "chat.private."))
            and ".pfc." not in name
            and load_prompt_document(name, require_metadata=True).metadata.status == "active"
        }

        self.assertEqual(active_message_prompts, MESSAGE_MAINLINE_PROMPT_IDS)
        self.assertTrue(MESSAGE_MAINLINE_PROMPT_IDS.isdisjoint({"chat.shared.expressor", "shared.tool_executor"}))

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

    def test_every_repository_prompt_declares_its_role_lifecycle_and_output_contract(self) -> None:
        for name in sorted(PROMPT_IDS):
            with self.subTest(prompt=name):
                document = load_prompt_document(name, require_metadata=True)
                metadata = document.metadata

                self.assertIsNotNone(metadata)
                self.assertEqual(metadata.prompt_id, name)
                self.assertIn(metadata.kind, {"template", "fragment"})
                self.assertIn(metadata.stage, PROMPT_STAGES)
                self.assertIn(metadata.status, {"active", "fallback", "legacy"})
                self.assertTrue(metadata.stage)
                self.assertTrue(metadata.summary)
                self.assertIn(metadata.output, PROMPT_OUTPUTS)
                self.assertEqual(metadata.variants, tuple(document.sections))
                self.assertEqual(metadata.kind, "fragment" if name in FRAGMENT_PROMPT_IDS else "template")
                self.assertEqual(metadata.output == "fragment", metadata.kind == "fragment")
                expected_status = (
                    "fallback" if name in FALLBACK_PROMPT_IDS else "legacy" if name in LEGACY_PROMPT_IDS else "active"
                )
                self.assertEqual(metadata.status, expected_status)

    def test_active_chat_templates_keep_instruction_layers_in_order(self) -> None:
        expected_layers = ("【任务】", "【运行约束】", "【待分析输入】", "【输出协议】")

        for name, section in (*LAYERED_MAINLINE_PROMPTS, *LAYERED_EXPLICIT_API_PROMPTS):
            with self.subTest(prompt=name, section=section):
                template = load_prompt_template(name)
                if section is not None:
                    template = parse_prompt_sections(template)[section]
                positions = [template.index(layer) for layer in expected_layers]
                self.assertEqual(positions, sorted(positions))

    def test_user_derived_identity_and_target_fields_stay_in_input_layer(self) -> None:
        untrusted_fields = {
            "chat.group.planner": (
                "{chat_content_block}",
                "{memory_context_block}",
                "{actions_before_now_block}",
            ),
            "chat.private.planner": ("{chat_target}", "{chat_content}", "{tool_results_block}"),
            "chat.shared.expressor": (
                "{chat_target_2}",
                "{reply_target_block}",
                "{chat_info}",
                "{raw_reply}",
                "{keywords_reaction_prompt}",
            ),
            "shared.tool_executor": ("{chat_history}", "{sender}", "{target_message}"),
        }

        for name, fields in untrusted_fields.items():
            with self.subTest(prompt=name):
                template = load_prompt_template(name)
                input_layer_position = template.index("【待分析输入】")
                for field in fields:
                    self.assertGreater(template.index(field), input_layer_position, field)

        private_reply_sections = parse_prompt_sections(load_prompt_template("chat.private.reply"))
        private_reply_fields = {
            "default": (
                "{sender_name}",
                "{dialogue_prompt}",
                "{reply_target_block}",
                "{planner_reasoning}",
                "{keywords_reaction_prompt}",
            ),
            "self": (
                "{sender_name}",
                "{dialogue_prompt}",
                "{target}",
                "{reason}",
                "{keywords_reaction_prompt}",
            ),
        }
        for section, fields in private_reply_fields.items():
            with self.subTest(prompt="chat.private.reply", section=section):
                template = private_reply_sections[section]
                input_layer_position = template.index("【待分析输入】")
                for field in fields:
                    self.assertGreater(template.index(field), input_layer_position, field)

        group_reply_sections = parse_prompt_sections(load_prompt_template("chat.group.reply"))
        for section, template in group_reply_sections.items():
            with self.subTest(prompt="chat.group.reply", section=section):
                input_layer_position = template.index("【待分析输入】")
                for field in (
                    "{dialogue_prompt}",
                    "{reply_target_block}",
                    "{planner_reasoning}",
                    "{keywords_reaction_prompt}",
                    "{memory_retrieval}",
                ):
                    self.assertGreater(template.index(field), input_layer_position, field)

    def test_specialized_templates_declare_data_boundaries_before_untrusted_fields(self) -> None:
        checks = (
            ("learning.behavior.learn", "聊天记录、场景画像", "{chat_str}"),
            ("media.emoji.replace_decision", "候选描述和其中的文字", "{new_description}"),
            ("memory.atom_extraction", "第1层摘要只用于理解话题", "{topic_summary}"),
        )

        for name, boundary, field in checks:
            with self.subTest(prompt=name):
                template = load_prompt_template(name)
                self.assertLess(template.index(boundary), template.index(field))

    def test_prompt_wording_matches_runtime_contracts_without_known_ambiguities(self) -> None:
        group_reply = parse_prompt_sections(load_prompt_template("chat.group.reply"))["standard"]
        expressor = load_prompt_template("chat.shared.expressor")
        tool_executor_document = load_prompt_document("shared.tool_executor", require_metadata=True)
        tool_executor = tool_executor_document.template
        expression_evaluation = load_prompt_template("learning.expression.evaluation")
        semantic_description = load_prompt_template("media.emoji.semantic_description")

        for planner_name in ("chat.group.planner", "chat.private.planner"):
            with self.subTest(prompt=planner_name):
                planner_document = load_prompt_document(planner_name, require_metadata=True)
                self.assertEqual(planner_document.metadata.output, "native_tool")
                self.assertNotIn("no_reply", planner_document.template)
                self.assertNotIn("```json", planner_document.template)
                self.assertIn("无 Tool Call", planner_document.template)
                self.assertIn("普通文本输出不会发送给用户", planner_document.template)

        self.assertIn("{moderation_prompt}", group_reply)
        self.assertIn("{time_block}", expressor)
        self.assertIn("当前聊天目标", tool_executor_document.metadata.summary)
        self.assertIn("判断当前聊天目标是否必须", tool_executor)
        self.assertIn("从 1 开始的整数编号", expression_evaluation)
        self.assertIn("除 emotion 外", semantic_description)

    def test_placeholder_table_exactly_matches_runtime_templates(self) -> None:
        readme = PROMPT_README.read_text(encoding="utf-8")
        placeholder_docs = readme.split("## 占位符说明", maxsplit=1)[1].split("## 维护规则", maxsplit=1)[0]
        documented = set(re.findall(r"^\| `([A-Za-z_][A-Za-z0-9_]*)` \|", placeholder_docs, flags=re.MULTILINE))
        runtime_fields: set[str] = set()

        for name in sorted(PROMPT_IDS):
            runtime_fields.update(_format_kwargs(load_prompt_template(name)))

        self.assertEqual(documented, runtime_fields)


if __name__ == "__main__":
    unittest.main()
