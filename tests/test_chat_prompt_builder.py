import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.chat.utils import prompt_builder
from src.chat.utils.prompt_builder import Prompt, PromptManager


class PromptBuilderTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_manager = prompt_builder.global_prompt_manager
        prompt_builder.global_prompt_manager = PromptManager()
        self.addCleanup(self._restore_manager)

    def _restore_manager(self) -> None:
        prompt_builder.global_prompt_manager = self.original_manager

    def test_prompt_formats_positional_keyword_nested_and_escaped_braces(self) -> None:
        prompt = Prompt("Hello {name}, literal \\{json\\}", name="greet")
        positional = Prompt("{first}-{second}", name="positional")
        nested = Prompt("outer:{inner}", name="nested")
        inner = Prompt("inner {value}", name="inner")
        from_list = Prompt(["line {one}", "line {two}"], name="from_list")

        self.assertEqual(prompt.args, ["name"])
        self.assertEqual(str(prompt), "Hello {name}, literal \\{json\\}")
        self.assertEqual(prompt.format(name="Mai"), "Hello Mai, literal {json}")
        self.assertEqual(positional.format("A", "B"), "A-B")
        self.assertEqual(nested.format(inner=inner, value="ok"), "outer:inner ok")
        self.assertEqual(from_list.format(one=1, two=2), "line 1\nline 2")
        self.assertEqual(repr(prompt), "Prompt(template='Hello {name}, literal \\{json\\}', name='greet')")

        with self.assertRaisesRegex(ValueError, "格式化模板失败"):
            positional.format("A", "B", "C")
        with self.assertRaisesRegex(ValueError, "missing"):
            prompt.format(missing="value")

    async def test_prompt_manager_registers_global_prompts_and_context_prompts_override_temporarily(self) -> None:
        manager = prompt_builder.global_prompt_manager
        unnamed = Prompt("auto {value}")
        manager.add_prompt("shared", "global {value}")

        self.assertEqual(unnamed.name, "prompt_1")
        self.assertEqual(await manager.format_prompt("shared", value="one"), "global one")

        async with manager.async_message_scope("message-1"):
            await Prompt.create_async("context {value}", name="shared")
            await Prompt.create_async("scoped only {value}", name="scoped")

            self.assertEqual(await manager.format_prompt("shared", value="two"), "context two")
            self.assertEqual(await manager.format_prompt("scoped", value="three"), "scoped only three")

        self.assertEqual(await manager.format_prompt("shared", value="four"), "global four")
        with self.assertRaisesRegex(KeyError, "scoped"):
            await manager.get_prompt_async("scoped")

        async with manager.async_message_scope(None):
            self.assertEqual(await manager.format_prompt("shared", value="five"), "global five")

    async def test_prompt_context_register_async_accepts_explicit_context_without_current_scope(self) -> None:
        manager = prompt_builder.global_prompt_manager
        context_prompt = Prompt("explicit {value}", name="explicit", _should_register=False)
        await manager._context.register_async(context_prompt, context_id="ctx")

        async with manager.async_message_scope("ctx"):
            self.assertEqual(await manager.format_prompt("explicit", value="ok"), "explicit ok")

        with self.assertRaisesRegex(KeyError, "explicit"):
            await manager.get_prompt_async("explicit")

    def test_init_external_prompts_syncs_plain_and_sectioned_prompts_without_overwriting_existing(self) -> None:
        manager = prompt_builder.global_prompt_manager
        manager.add_prompt("existing", "local value")
        fake_new_manager = SimpleNamespace(
            _loaded=False,
            _prompts={
                "existing": "external ignored",
                "plain": "plain {value}",
                "sectioned": "###SECTION: first\nfirst {value}\n###END_SECTION###\n###SECTION: second\nsecond\n###END_SECTION###",
            },
            load_prompts=Mock(),
        )

        import src.common.prompt_manager as common_prompt_manager

        with patch.object(common_prompt_manager, "prompt_manager", fake_new_manager):
            count = prompt_builder.init_external_prompts()

        self.assertEqual(count, 3)
        fake_new_manager.load_prompts.assert_called_once_with()
        self.assertEqual(manager._prompts["existing"].template, "local value")
        self.assertEqual(manager._prompts["plain"].format(value="ok"), "plain ok")
        self.assertEqual(manager._prompts["first"].format(value="ok"), "first ok")
        self.assertEqual(manager._prompts["second"].format(), "second")


if __name__ == "__main__":
    unittest.main()
