import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_MD = PROJECT_ROOT / "plugins" / "doc-link" / "agents" / "toc-updater.md"
SCRIPT = (
    PROJECT_ROOT
    / "plugins"
    / "doc-link"
    / "skills"
    / "index-docs"
    / "scripts"
    / "index_docs.py"
)
MANUAL = PROJECT_ROOT / "tests" / "doc-link" / "manual" / "toc-updater_manual.md"


def split_frontmatter(text):
    lines = text.split("\n")
    assert lines[0] == "---", "frontmatter で始まらない"
    end = lines.index("---", 1)
    return lines[1:end], "\n".join(lines[end + 1 :])


class AgentMdTest(unittest.TestCase):
    def setUp(self):
        self.text = AGENT_MD.read_text(encoding="utf-8")
        frontmatter, self.body = split_frontmatter(self.text)
        self.keys = {
            line.split(":", 1)[0]: line.split(":", 1)[1].strip() for line in frontmatter
        }

    def test_frontmatter_has_required_fields(self):
        for name in ("name", "description", "tools", "model"):
            with self.subTest(name=name):
                self.assertTrue(self.keys.get(name))
        self.assertEqual(self.keys["name"], "toc-updater")

    def test_tools_allowlist_is_minimal(self):
        tools = {t.strip() for t in self.keys["tools"].split(",")}
        self.assertEqual(tools, {"Read", "Bash"})
        for banned in ("Write", "Edit", "NotebookEdit", "Agent", "Task", "Skill"):
            self.assertNotIn(banned, tools)

    def test_role_constraints_and_prohibitions(self):
        for needle in (
            "生成依頼",
            "最大 3 文書",
            "他の Agent を起動しない",
            "Skill を実行しない",
            "引き継がない",
            "書き換えない",
            "外部サービスへ書き込まない",
            "advisor",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.body)

    def test_does_not_refer_to_development_documents(self):
        for needle in ("docs/specs", "docs/rules", "DES-", "REQ-", "ADR-", "D-0"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.text)

    def test_does_not_contain_internal_limit_factor_or_margin(self):
        self.assertNotRegex(self.text, r"\bH\b")
        for needle in ("1.3", "余白", "許容"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.text)

    def test_describes_exit_values_and_language(self):
        self.assertIn("source_unreadable", self.body)
        self.assertIn("--exit-value 0", self.body)
        self.assertIn("英語", self.body)
        self.assertIn("H1", self.body)

    def test_commands_call_only_the_entry_script_subcommands(self):
        commands = re.findall(r"^uv run .*$", self.body, flags=re.MULTILINE)
        self.assertEqual(len(commands), 2)
        self.assertIn('index_docs.py" request', commands[0])
        self.assertIn('index_docs.py" deliver', commands[1])
        self.assertTrue(SCRIPT.is_file())

    def test_does_not_write_results_to_files(self):
        self.assertIn("JSON を自分で組み立てない", self.body)


class ManualTest(unittest.TestCase):
    def test_manual_is_separate_from_automatic_tests(self):
        self.assertTrue(MANUAL.is_file())
        self.assertNotRegex(MANUAL.name, r"^test_.*\.py$")
        self.assertEqual(MANUAL.suffix, ".md")
        self.assertEqual(MANUAL.parent.name, "manual")
        self.assertEqual(list(MANUAL.parent.glob("test_*.py")), [])


if __name__ == "__main__":
    unittest.main()
