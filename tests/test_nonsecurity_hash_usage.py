import ast
import unittest

from pathlib import Path


class NonSecurityHashUsageTest(unittest.TestCase):
    def test_md5_and_sha1_calls_explicitly_declare_nonsecurity_usage(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        findings: list[str] = []

        for source_root in (repository_root / "src", repository_root / "plugins"):
            for source_path in sorted(source_root.rglob("*.py")):
                tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                        continue
                    if not isinstance(node.func.value, ast.Name) or node.func.value.id != "hashlib":
                        continue
                    if node.func.attr not in {"md5", "sha1"}:
                        continue

                    marker = next((keyword for keyword in node.keywords if keyword.arg == "usedforsecurity"), None)
                    if not marker or not isinstance(marker.value, ast.Constant) or marker.value.value is not False:
                        relative_path = source_path.relative_to(repository_root)
                        findings.append(
                            f"{relative_path}:{node.lineno}: hashlib.{node.func.attr} 缺少 usedforsecurity=False"
                        )

        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
