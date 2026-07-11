import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.common import prompt_loader
from src.common import prompt_manager as common_prompt_manager
from src.common.prompt_manager import LEGACY_PROMPT_ALIASES, PromptManager


class UnifiedPromptManagerTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        prompt_loader.clear_prompt_cache()

    def test_recursive_prompt_files_use_namespaced_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "chat" / "group" / "planner.prompt"
            prompt_path.parent.mkdir(parents=True)
            prompt_path.write_text("hello {name}", encoding="utf-8")

            prompt_loader.clear_prompt_cache()
            with patch.object(prompt_loader, "PROMPTS_ROOT", Path(tmpdir)):
                self.assertEqual(prompt_loader.list_prompt_templates(), ["chat.group.planner"])
                self.assertEqual(
                    prompt_loader.load_prompt("chat.group.planner", name="Mai"),
                    "hello Mai",
                )

    def test_section_ids_are_scoped_to_their_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "chat" / "group" / "reply.prompt"
            second = root / "chat" / "private" / "reply.prompt"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_text(
                "###SECTION: default\ngroup {value}\n###END_SECTION###\n",
                encoding="utf-8",
            )
            second.write_text(
                "###SECTION: default\nprivate {value}\n###END_SECTION###\n",
                encoding="utf-8",
            )

            prompt_loader.clear_prompt_cache()
            with patch.object(prompt_loader, "PROMPTS_ROOT", root):
                manager = PromptManager()
                manager.load_prompts()

                self.assertEqual(manager.format_prompt("chat.group.reply.default", value="one"), "group one")
                self.assertEqual(manager.format_prompt("chat.private.reply.default", value="two"), "private two")
                with self.assertRaises(KeyError):
                    manager.get_prompt("default")

    async def test_legacy_aliases_and_context_overrides_resolve_to_canonical_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "chat" / "group" / "planner.prompt"
            prompt_path.parent.mkdir(parents=True)
            prompt_path.write_text("global {value}", encoding="utf-8")

            prompt_loader.clear_prompt_cache()
            with patch.object(prompt_loader, "PROMPTS_ROOT", Path(tmpdir)):
                manager = PromptManager(aliases={"planner_prompt": "chat.group.planner"})
                manager.load_prompts()
                manager.register_context_prompts(
                    "custom",
                    {"planner_prompt": "context {value}, literal \\{json\\}"},
                )

                self.assertEqual(manager.format_prompt("planner_prompt", value="one"), "global one")
                async with manager.async_message_scope("custom"):
                    self.assertEqual(
                        manager.format_prompt("chat.group.planner", value="two"),
                        "context two, literal {json}",
                    )

                self.assertEqual(manager.format_prompt("chat.group.planner", value="three"), "global three")

    def test_repository_legacy_aliases_all_target_live_prompts(self) -> None:
        manager = PromptManager(aliases=LEGACY_PROMPT_ALIASES)
        manager.load_prompts()

        for legacy_id, canonical_id in LEGACY_PROMPT_ALIASES.items():
            with self.subTest(legacy_id=legacy_id):
                self.assertEqual(manager.get_prompt(legacy_id), manager.get_prompt(canonical_id))

    def test_namespaced_prompt_content_hot_reloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "memory" / "retrieval.prompt"
            prompt_path.parent.mkdir(parents=True)
            prompt_path.write_text("before {value}", encoding="utf-8")

            prompt_loader.clear_prompt_cache()
            with patch.object(prompt_loader, "PROMPTS_ROOT", Path(tmpdir)):
                manager = PromptManager()
                manager.load_prompts()
                self.assertEqual(manager.format_prompt("memory.retrieval", value="one"), "before one")

                prompt_path.write_text("after reload {value}", encoding="utf-8")
                self.assertEqual(manager.format_prompt("memory.retrieval", value="two"), "after reload two")

    def test_empty_manager_lazy_loads_without_overwriting_in_memory_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "shared" / "tool.prompt"
            prompt_path.parent.mkdir(parents=True)
            prompt_path.write_text("disk {value}", encoding="utf-8")

            prompt_loader.clear_prompt_cache()
            with patch.object(prompt_loader, "PROMPTS_ROOT", Path(tmpdir)):
                disk_manager = PromptManager()
                self.assertFalse(disk_manager.is_loaded)
                self.assertEqual(disk_manager.format_prompt("shared.tool", value="one"), "disk one")
                self.assertTrue(disk_manager.is_loaded)

                memory_manager = PromptManager()
                memory_manager.add_prompt("shared.tool", "memory {value}")
                self.assertEqual(memory_manager.format_prompt("shared.tool", value="two"), "memory two")

    def test_legacy_prompt_builder_reexports_the_common_manager(self) -> None:
        from src.chat.utils import prompt_builder

        self.assertIs(prompt_builder.PromptManager, PromptManager)
        self.assertIs(prompt_builder.global_prompt_manager.manager, common_prompt_manager.prompt_manager)
        self.assertNotIn("_prompts", vars(prompt_builder.global_prompt_manager))


if __name__ == "__main__":
    unittest.main()
