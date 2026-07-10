import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
GENERATION_METHODS = {
    "generate_response_async",
    "generate_response_for_audio",
    "generate_response_for_image",
}
INSTRUCTION_CUES = (
    "Generate a transcript",
    "你是",
    "必须遵守",
    "请",
    "任务：",
    "要求：",
    "只返回",
    "严格 JSON",
)


def _literal_text(node: ast.AST | None) -> str:
    if node is None:
        return ""
    return "".join(
        child.value for child in ast.walk(node) if isinstance(child, ast.Constant) and isinstance(child.value, str)
    )


def _assigned_name(node: ast.Assign | ast.AnnAssign) -> str:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return next((target.id for target in targets if isinstance(target, ast.Name)), "")


def _enclosing_function_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return ""


def _is_loader_call(node: ast.AST | None) -> bool:
    while isinstance(node, (ast.Await, ast.Expr)):
        node = node.value
    return isinstance(node, ast.Call)


class PromptExternalizationTest(unittest.TestCase):
    def test_fixed_llm_instruction_templates_are_not_embedded_in_python(self) -> None:
        findings: list[str] = []

        for path in SOURCE_ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    name = _assigned_name(node)
                    value = node.value
                elif isinstance(node, ast.Return):
                    name = _enclosing_function_name(node, parents)
                    value = node.value
                else:
                    continue

                if "prompt" not in name.lower() and "instruction" not in name.lower():
                    continue
                if _is_loader_call(value):
                    continue

                text = _literal_text(value)
                if len(text) >= 40 and any(cue in text for cue in INSTRUCTION_CUES):
                    findings.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} ({name})")

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name) and node.func.id == "Prompt" and node.args:
                    if len(_literal_text(node.args[0])) >= 40:
                        findings.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} (Prompt literal)")

                method_name = node.func.attr if isinstance(node.func, ast.Attribute) else ""
                if method_name not in GENERATION_METHODS:
                    continue
                prompt_arg = (
                    node.args[0]
                    if node.args
                    else next(
                        (keyword.value for keyword in node.keywords if keyword.arg == "prompt"),
                        None,
                    )
                )
                text = _literal_text(prompt_arg)
                if len(text) >= 40 and any(cue in text for cue in INSTRUCTION_CUES):
                    findings.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} (model call literal)")

        self.assertEqual(
            findings,
            [],
            "固定 LLM 指令应迁移至 prompts/*.prompt 并通过加载器读取:\n" + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
