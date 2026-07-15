import hashlib
import json
import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch

import tomlkit

from src.common import agreement, person_stub, prompt_loader, prompt_manager, tcp_connector
from src.common.knowledge_utils.dyn_topk import dyn_select_top_k
from src.common.knowledge_utils.hash import get_sha256
from src.common.knowledge_utils import json_fix
from src.common.knowledge_utils.json_fix import fix_broken_generated_json, new_fix_broken_generated_json
from src.common.toml_utils import _format_toml_value, _update_toml_doc, format_toml_string, save_toml_with_format


class KnowledgeUtilsTest(unittest.TestCase):
    def test_get_sha256_hashes_utf8_text(self) -> None:
        self.assertEqual(get_sha256("MaiBot测试"), hashlib.sha256("MaiBot测试".encode("utf-8")).hexdigest())

    def test_dyn_select_top_k_selects_scores_above_dynamic_threshold(self) -> None:
        result = dyn_select_top_k(
            [("low", 0.1), ("high", 0.9), ("middle", 0.4)],
            jmp_factor=0.5,
            var_factor=0.0,
        )

        self.assertEqual(result, [("high", 0.9, 1.0)])

    def test_dyn_select_top_k_returns_empty_for_empty_input(self) -> None:
        self.assertEqual(dyn_select_top_k([], jmp_factor=0.5, var_factor=0.0), [])

    def test_dyn_select_top_k_uses_largest_normalized_jump_as_threshold_source(self) -> None:
        result = dyn_select_top_k(
            [("a", 10.0), ("b", 8.0), ("c", 1.0), ("d", 0.0)],
            jmp_factor=1.0,
            var_factor=0.0,
        )

        self.assertEqual(result, [("a", 10.0, 1.0), ("b", 8.0, 0.8)])

    def test_dyn_select_top_k_returns_single_candidate_without_division_by_zero(self) -> None:
        result = dyn_select_top_k([("only", 0.42)], jmp_factor=0.5, var_factor=0.0)

        self.assertEqual(result, [("only", 0.42, 1.0)])

    def test_dyn_select_top_k_returns_empty_when_equal_scores_have_no_distinguishing_signal(self) -> None:
        result = dyn_select_top_k([("first", 0.5), ("second", 0.5)], jmp_factor=0.5, var_factor=0.0)

        self.assertEqual(result, [])

    def test_fix_broken_generated_json_closes_unclosed_containers_without_counting_string_braces(self) -> None:
        broken = '{"items": [{"text": "keep } inside string"}'

        repaired = fix_broken_generated_json(broken)

        self.assertEqual(json.loads(repaired), {"items": [{"text": "keep } inside string"}]})

    def test_fix_broken_generated_json_returns_valid_json_and_handles_escaped_quotes(self) -> None:
        valid = '{"message": "already valid"}'
        broken_without_comma = '{"text": "quote \\" and [ inside"'
        broken_with_trailing_fragment = '{"items": ["a", "unfinished"'

        self.assertIs(fix_broken_generated_json(valid), valid)
        self.assertEqual(json.loads(fix_broken_generated_json(broken_without_comma)), {"text": 'quote " and [ inside'})
        self.assertEqual(json.loads(fix_broken_generated_json(broken_with_trailing_fragment)), {"items": ["a"]})

    def test_new_fix_broken_generated_json_returns_valid_json_unchanged(self) -> None:
        valid = '{"message": "already valid", "count": 2}'

        self.assertIs(new_fix_broken_generated_json(valid), valid)

    def test_new_fix_broken_generated_json_delegates_invalid_content_to_json_repair(self) -> None:
        with patch.object(json_fix, "repair_json", return_value='{"fixed": true}') as repair_json:
            self.assertEqual(new_fix_broken_generated_json("{bad json"), '{"fixed": true}')

        repair_json.assert_called_once_with("{bad json")


class TomlUtilsTest(unittest.TestCase):
    def test_format_toml_string_multilines_arrays_that_exceed_threshold(self) -> None:
        output = format_toml_string({"names": ["alpha", "beta"], "nested": {"ids": [1, 2]}}, multiline_threshold=1)

        self.assertIn('names = [\n    "alpha",\n    "beta",\n]', output)
        self.assertIn("ids = [\n    1,\n    2,\n]", output)

    def test_format_toml_string_preserves_array_of_tables_shape_and_compacts_blank_lines(self) -> None:
        doc = tomlkit.parse(
            'name = "bot"\n\n\n\n[[servers]]\nname = "primary"\nports = [1, 2]\n\n\n\n[[servers]]\nname = "backup"\n'
        )

        output = format_toml_string(doc, multiline_threshold=1)

        self.assertIn('[[servers]]\nname = "primary"', output)
        self.assertIn('[[servers]]\nname = "backup"', output)
        self.assertNotIn("\n\n\n", output)

    def test_format_toml_string_can_skip_multiline_array_formatting(self) -> None:
        output = format_toml_string({"names": ["alpha", "beta"]}, multiline_threshold=-1)

        self.assertEqual(output.strip(), 'names = ["alpha", "beta"]')

    def test_internal_format_and_update_helpers_cover_fallback_shapes(self) -> None:
        list_of_dicts = [{"name": "primary"}, {"name": "backup"}]
        formatted = _format_toml_value(list_of_dicts, threshold=1)
        self.assertIs(formatted, list_of_dicts)
        self.assertEqual(formatted, [{"name": "primary"}, {"name": "backup"}])

        target = {"existing": "old"}
        _update_toml_doc(target, ["ignored"])
        _update_toml_doc("not-a-dict", {"existing": "new"})
        self.assertEqual(target, {"existing": "old"})

        class Unsupported:
            pass

        unsupported = Unsupported()
        _update_toml_doc(target, {"existing": unsupported, "added": unsupported})
        self.assertIs(target["existing"], unsupported)
        self.assertIs(target["added"], unsupported)

    def test_save_toml_with_format_preserves_comments_and_skips_version_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                '# preserved comment\nversion = "1.0"\nname = "old"\n\n[section]\nvalue = 1\n',
                encoding="utf-8",
            )

            save_toml_with_format(
                {"version": "2.0", "name": "new", "section": {"value": 2}, "added": ["x", "y"]},
                str(config_path),
            )

            output = config_path.read_text(encoding="utf-8")
            parsed = tomlkit.parse(output)
            self.assertIn("# preserved comment", output)
            self.assertEqual(parsed["version"], "1.0")
            self.assertEqual(parsed["name"], "new")
            self.assertEqual(parsed["section"]["value"], 2)
            self.assertEqual(list(parsed["added"]), ["x", "y"])

    def test_save_toml_with_format_can_replace_without_preserving_existing_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text('# old\nname = "old"\n', encoding="utf-8")

            save_toml_with_format({"name": "new"}, str(config_path), preserve_comments=False)

            output = config_path.read_text(encoding="utf-8")
            self.assertNotIn("# old", output)
            self.assertEqual(tomlkit.parse(output)["name"], "new")


class TcpConnectorTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_tcp_connector_uses_shared_ssl_context_and_can_be_closed(self) -> None:
        connector = await tcp_connector.get_tcp_connector()

        try:
            self.assertIs(connector._ssl, tcp_connector.ssl_context)
            self.assertFalse(connector.closed)
        finally:
            await connector.close()

        self.assertTrue(connector.closed)


class PromptLoaderTest(unittest.TestCase):
    def test_normalize_prompt_name_accepts_safe_suffix_and_rejects_path_traversal(self) -> None:
        self.assertEqual(prompt_loader.normalize_prompt_name("chat.main.prompt"), "chat.main")

        with self.assertRaises(ValueError):
            prompt_loader.normalize_prompt_name("../secret")

    def test_parse_prompt_sections_keeps_explicit_named_sections(self) -> None:
        template = """
###SECTION: greeting
hello {name}
###END_SECTION###
###SECTION: farewell
bye {name}
###END_SECTION###
""".strip()

        sections = prompt_loader.parse_prompt_sections(template)

        self.assertEqual(sections, {"greeting": "hello {name}", "farewell": "bye {name}"})

    def test_parse_prompt_sections_rejects_ambiguous_or_malformed_structure(self) -> None:
        malformed_templates = {
            "段外正文": "outside\n###SECTION: only\ninside\n###END_SECTION###",
            "未闭合分段": "###SECTION: only\ninside",
            "重复分段": ("###SECTION: same\none\n###END_SECTION###\n###SECTION: same\ntwo\n###END_SECTION###"),
            "嵌套分段": "###SECTION: outer\n###SECTION: inner\ninside\n###END_SECTION###",
            "孤立结束标记": "###END_SECTION###",
            "非法结束标记": "###SECTION: only\ninside\n###END_SECTION###suffix",
            "非法分段名": "###SECTION: bad.name\ninside\n###END_SECTION###",
            "空分段": "###SECTION: empty\n\n###END_SECTION###",
        }

        for case, template in malformed_templates.items():
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, case):
                prompt_loader.parse_prompt_sections(template)

        with self.assertRaisesRegex(ValueError, "非法分段名"):
            prompt_loader.parse_prompt_sections("###SECTION only\ninside\n###END_SECTION###")
        with self.assertRaisesRegex(ValueError, "非法结束标记"):
            prompt_loader.parse_prompt_sections("###SECTION: only\ninside\n###END_SECTION##")

    def test_parse_prompt_document_separates_metadata_from_runtime_template(self) -> None:
        raw_document = """###PROMPT_META###
id: chat.group.reply
kind: template
stage: generation
status: active
summary: 根据当前目标生成群聊回复
output: plain_text
variants: light, standard
###END_PROMPT_META###
###SECTION: light
short {name}
###END_SECTION###
###SECTION: standard
normal {name}
###END_SECTION###
"""

        document = prompt_loader.parse_prompt_document(raw_document, expected_id="chat.group.reply")

        self.assertIsNotNone(document.metadata)
        self.assertEqual(document.metadata.prompt_id, "chat.group.reply")
        self.assertEqual(document.metadata.variants, ("light", "standard"))
        self.assertNotIn("PROMPT_META", document.template)
        self.assertTrue(document.template.endswith("\n"))
        self.assertEqual(document.sections, {"light": "short {name}", "standard": "normal {name}"})

    def test_parse_prompt_document_rejects_metadata_drift(self) -> None:
        base = """###PROMPT_META###
id: {prompt_id}
kind: {kind}
stage: generation
status: {status}
summary: summary
output: plain_text
{variants}###END_PROMPT_META###
{body}
"""
        malformed_documents = {
            "ID 不匹配": base.format(
                prompt_id="chat.private.reply",
                kind="template",
                status="active",
                variants="",
                body="hello",
            ),
            "ID 必须使用不含 .prompt 后缀的规范点分 ID": base.format(
                prompt_id="chat.group.reply.prompt",
                kind="template",
                status="active",
                variants="",
                body="hello",
            ),
            "未知 kind": base.format(
                prompt_id="chat.group.reply",
                kind="partial",
                status="active",
                variants="",
                body="hello",
            ),
            "未知 status": base.format(
                prompt_id="chat.group.reply",
                kind="template",
                status="deprecated",
                variants="",
                body="hello",
            ),
            "分段声明不一致": base.format(
                prompt_id="chat.group.reply",
                kind="template",
                status="active",
                variants="variants: light\n",
                body=("###SECTION: light\nshort\n###END_SECTION###\n###SECTION: standard\nnormal\n###END_SECTION###"),
            ),
            "variants 包含空分段名": base.format(
                prompt_id="chat.group.reply",
                kind="template",
                status="active",
                variants="variants: light,\n",
                body="###SECTION: light\nshort\n###END_SECTION###",
            ),
        }

        for case, document in malformed_documents.items():
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, case):
                prompt_loader.parse_prompt_document(document, expected_id="chat.group.reply")

    def test_parse_prompt_document_rejects_reserved_metadata_markers_in_runtime_body(self) -> None:
        malformed_documents = {
            "多余提示词元数据结束标记": """###PROMPT_META###
id: chat.group.reply
kind: template
stage: generation
status: active
summary: summary
output: plain_text
###END_PROMPT_META###
hello
###END_PROMPT_META###
""",
            "非法提示词元数据标记": "###PROMPT_META###suffix\nhello\n",
        }

        for case, document in malformed_documents.items():
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, case):
                prompt_loader.parse_prompt_document(document, expected_id="chat.group.reply")

    def test_load_prompt_formats_template_and_lists_existing_or_missing_prompt_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_root = Path(tmpdir)
            (prompt_root / "beta.prompt").write_text("hello {name}", encoding="utf-8")
            (prompt_root / "alpha.prompt").write_text("alpha", encoding="utf-8")

            prompt_loader.clear_prompt_cache()
            with patch.object(prompt_loader, "PROMPTS_ROOT", prompt_root):
                self.assertEqual(prompt_loader.load_prompt("beta", name="Mai"), "hello Mai")
                self.assertEqual(prompt_loader.list_prompt_templates(), ["alpha", "beta"])

            with patch.object(prompt_loader, "PROMPTS_ROOT", prompt_root / "missing"):
                self.assertEqual(prompt_loader.list_prompt_templates(), [])
            prompt_loader.clear_prompt_cache()

    def test_load_prompt_observes_file_changes_without_manual_cache_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "live.prompt"
            prompt_path.write_text("first {value}", encoding="utf-8")

            prompt_loader.clear_prompt_cache()
            with patch.object(prompt_loader, "PROMPTS_ROOT", Path(tmpdir)):
                self.assertEqual(prompt_loader.load_prompt("live", value="one"), "first one")

                prompt_path.write_text("updated prompt {value}", encoding="utf-8")
                self.assertEqual(prompt_loader.load_prompt("live", value="two"), "updated prompt two")

            prompt_loader.clear_prompt_cache()

    def test_load_prompt_section_formats_requested_section_from_patched_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "sample.prompt"
            prompt_path.write_text(
                "###SECTION: header\nhi\n###END_SECTION###\n###SECTION: body\nhello {name}\n###END_SECTION###\n",
                encoding="utf-8",
            )

            prompt_loader.clear_prompt_cache()
            with patch.object(prompt_loader, "PROMPTS_ROOT", Path(tmpdir)):
                self.assertEqual(prompt_loader.load_prompt_section("sample", "body", name="Mai"), "hello Mai")
                self.assertEqual(prompt_loader.load_prompt_section("sample", "header"), "hi")
                with self.assertRaises(KeyError):
                    prompt_loader.load_prompt_section("sample", "missing")
            prompt_loader.clear_prompt_cache()


class PromptManagerTest(unittest.TestCase):
    def test_prompt_manager_loads_formats_and_reloads_when_cache_revision_changes(self) -> None:
        manager = prompt_manager.PromptManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "sample.prompt"
            prompt_path.write_text("hello {name}", encoding="utf-8")

            prompt_loader.clear_prompt_cache()
            with patch.object(prompt_loader, "PROMPTS_ROOT", Path(tmpdir)):
                manager.load_prompts()
                self.assertEqual(manager.format_prompt("sample", name="Mai"), "hello Mai")

                prompt_path.write_text("bye {name}", encoding="utf-8")
                prompt_loader.clear_prompt_cache()
                self.assertEqual(manager.format_prompt("sample", name="Mai"), "bye Mai")

            prompt_loader.clear_prompt_cache()

    def test_prompt_manager_observes_file_changes_without_manual_cache_clear(self) -> None:
        manager = prompt_manager.PromptManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "sample.prompt"
            prompt_path.write_text("before {name}", encoding="utf-8")

            prompt_loader.clear_prompt_cache()
            with patch.object(prompt_loader, "PROMPTS_ROOT", Path(tmpdir)):
                manager.load_prompts()
                self.assertEqual(manager.format_prompt("sample", name="Mai"), "before Mai")

                prompt_path.write_text("after reload {name}", encoding="utf-8")
                self.assertEqual(manager.format_prompt("sample", name="Mai"), "after reload Mai")

            prompt_loader.clear_prompt_cache()

    def test_prompt_manager_reports_missing_names_and_safe_get_prompt_returns_default(self) -> None:
        manager = prompt_manager.PromptManager()
        manager._prompts = {"known": "value"}
        manager._cache_revision = prompt_loader.get_prompt_cache_revision()

        with self.assertRaises(KeyError) as exc:
            manager.get_prompt("missing")
        self.assertIn("known", str(exc.exception))

        class MissingPromptManager:
            def format_prompt(self, name: str, **kwargs) -> str:
                raise KeyError(name)

        class BrokenPromptManager:
            def format_prompt(self, name: str, **kwargs) -> str:
                raise ValueError("bad template")

        with patch.object(prompt_manager, "prompt_manager", MissingPromptManager()):
            self.assertEqual(prompt_manager.safe_get_prompt("missing", default="fallback"), "fallback")
        with patch.object(prompt_manager, "prompt_manager", BrokenPromptManager()):
            self.assertEqual(prompt_manager.safe_get_prompt("broken", default="fallback"), "fallback")

    def test_reload_prompts_clears_loader_cache_and_populates_global_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "global.prompt"
            prompt_path.write_text("global {value}", encoding="utf-8")

            prompt_loader.clear_prompt_cache()
            replacement_manager = prompt_manager.PromptManager()
            with (
                patch.object(prompt_loader, "PROMPTS_ROOT", Path(tmpdir)),
                patch.object(prompt_manager, "prompt_manager", replacement_manager),
            ):
                prompt_manager.reload_prompts()
                self.assertEqual(replacement_manager.format_prompt("global", value="ok"), "global ok")

            prompt_loader.clear_prompt_cache()


class AgreementTest(unittest.TestCase):
    def test_calculate_file_hash_reads_content_and_missing_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            eula_path = root / "EULA.md"
            eula_path.write_text("EULA text", encoding="utf-8")

            self.assertEqual(
                agreement.calculate_file_hash(eula_path, "EULA.md"),
                hashlib.md5("EULA text".encode("utf-8")).hexdigest(),
            )
            with self.assertRaises(FileNotFoundError):
                agreement.calculate_file_hash(root / "missing.md", "missing.md")

    def test_agreement_status_uses_file_and_environment_confirmations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            eula_content = "EULA text"
            privacy_content = "Privacy text"
            (root / "EULA.md").write_text(eula_content, encoding="utf-8")
            (root / "PRIVACY.md").write_text(privacy_content, encoding="utf-8")
            eula_hash = hashlib.md5(eula_content.encode("utf-8")).hexdigest()
            privacy_hash = hashlib.md5(privacy_content.encode("utf-8")).hexdigest()
            (root / "eula.confirmed").write_text(eula_hash, encoding="utf-8")

            with (
                patch.object(agreement, "PROJECT_ROOT", root),
                patch.dict("os.environ", {"PRIVACY_AGREE": privacy_hash}, clear=False),
            ):
                status = agreement.get_agreement_status(include_content=True)

        self.assertTrue(status["eula"].confirmed)
        self.assertTrue(status["eula"].file_confirmed)
        self.assertFalse(status["eula"].environment_confirmed)
        self.assertTrue(status["privacy"].confirmed)
        self.assertFalse(status["privacy"].file_confirmed)
        self.assertTrue(status["privacy"].environment_confirmed)
        self.assertEqual(status["privacy"].content, privacy_content)

    def test_confirm_agreements_rejects_stale_hash_and_does_not_write_confirmation_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "EULA.md").write_text("EULA text", encoding="utf-8")
            (root / "PRIVACY.md").write_text("Privacy text", encoding="utf-8")
            privacy_hash = hashlib.md5("Privacy text".encode("utf-8")).hexdigest()

            with patch.object(agreement, "PROJECT_ROOT", root):
                with self.assertRaises(ValueError):
                    agreement.confirm_agreements("stale-hash", privacy_hash)

            self.assertFalse((root / "eula.confirmed").exists())
            self.assertFalse((root / "privacy.confirmed").exists())

    def test_confirm_agreements_writes_current_hashes_and_marks_all_documents_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            eula_content = "EULA text"
            privacy_content = "Privacy text"
            (root / "EULA.md").write_text(eula_content, encoding="utf-8")
            (root / "PRIVACY.md").write_text(privacy_content, encoding="utf-8")
            eula_hash = hashlib.md5(eula_content.encode("utf-8")).hexdigest()
            privacy_hash = hashlib.md5(privacy_content.encode("utf-8")).hexdigest()

            with patch.object(agreement, "PROJECT_ROOT", root):
                status = agreement.confirm_agreements(eula_hash, privacy_hash)
                self.assertTrue(agreement.are_agreements_confirmed())

            self.assertEqual((root / "eula.confirmed").read_text(encoding="utf-8"), eula_hash)
            self.assertEqual((root / "privacy.confirmed").read_text(encoding="utf-8"), privacy_hash)
            self.assertEqual(status["eula"].content, eula_content)
            self.assertTrue(all(document.confirmed for document in status.values()))


class PersonStubTest(unittest.TestCase):
    def tearDown(self) -> None:
        person_stub._KNOWN_PERSONS.clear()

    def test_get_person_id_keeps_empty_fallbacks_and_strips_adapter_prefix(self) -> None:
        self.assertEqual(person_stub.get_person_id(user_id="42"), "42")

        expected = hashlib.md5("qq_42".encode()).hexdigest()
        self.assertEqual(person_stub.get_person_id("adapter-qq", 42), expected)

    def test_person_constructor_accepts_explicit_id_name_or_platform_user_pair(self) -> None:
        by_id = person_stub.Person(platform="qq", user_id="42", person_id="custom-id")
        by_name = person_stub.Person(person_name="Alice")
        by_pair = person_stub.Person(platform="qq", user_id=42)

        self.assertEqual(by_id.person_id, "custom-id")
        self.assertEqual(by_id.person_name, "42")
        self.assertEqual(by_name.person_id, "Alice")
        self.assertEqual(by_name.person_name, "Alice")
        self.assertEqual(by_pair.person_id, hashlib.md5("qq_42".encode()).hexdigest())
        self.assertEqual(by_pair.user_id, "42")
        self.assertEqual(by_pair.get_relation_info(), "42(42)")
        self.assertEqual(asyncio.run(by_pair.build_relationship("hello", "friend")), "")
        self.assertIn("person_id=", repr(by_pair))

    def test_person_constructor_rejects_missing_identity_and_register_person_records_stub_identity(self) -> None:
        with self.assertRaises(ValueError):
            person_stub.Person()

        registered = person_stub.Person.register_person(
            platform="qq",
            user_id="42",
            nickname="Nick",
            group_id="100",
            group_nick_name="GroupNick",
        )

        self.assertEqual(registered.person_id, "Nick")
        self.assertIn("Nick", person_stub._KNOWN_PERSONS)
        self.assertTrue(person_stub.is_person_known(person_id="Nick"))
        self.assertTrue(person_stub.is_person_known(person_id="unknown"))
        self.assertIsNone(person_stub.store_person_memory_from_answer("Nick", "memory", "chat-1"))


if __name__ == "__main__":
    unittest.main()
