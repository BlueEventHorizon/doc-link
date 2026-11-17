"""query-worker の Agent 定義の検査。

検索の判断品質（AI の判断）は自動テストに入れない。手動確認の手順は
`tests/doc-link/manual/query-worker_manual.md` に分けて置く。
"""

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_MD = PROJECT_ROOT / "plugins" / "doc-link" / "agents" / "query-worker.md"
SCRIPT = (
    PROJECT_ROOT
    / "plugins"
    / "doc-link"
    / "skills"
    / "query-docs"
    / "scripts"
    / "query_docs.py"
)
MANUAL = PROJECT_ROOT / "tests" / "doc-link" / "manual" / "query-worker_manual.md"
# 配布物から開発用の文書を参照していないことを確かめる検索語（Agent 定義全体が範囲）
FORBIDDEN_REFERENCES = ("docs/specs", "docs/rules", "DES-", "REQ-", "ADR-", "D-0")


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
        self.assertEqual(self.keys["name"], "query-worker")

    def test_tools_allowlist_is_minimal_and_has_no_write_permission(self):
        tools = {t.strip() for t in self.keys["tools"].split(",")}
        self.assertEqual(tools, {"Read", "Bash"})
        for banned in ("Write", "Edit", "NotebookEdit", "Agent", "Task", "Skill"):
            self.assertNotIn(banned, tools)

    def test_role_constraints_and_prohibitions(self):
        for needle in (
            "検索依頼",
            "他の Agent を起動しない",
            "Skill を実行しない",
            "引き継がない",
            "書き換えない",
            "外部サービスへ書き込まない",
            "advisor",
            "存在しない文書 ID・セクション ID を補わない",
            "訂正しない",
            "JSON を自分で組み立てない",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.body)

    def test_reads_all_entries_without_keyword_filtering(self):
        self.assertIn("全エントリを読む", self.body)
        self.assertIn("語句の一致で絞り込んで済ませない", self.body)

    def test_does_not_refer_to_development_documents(self):
        for needle in FORBIDDEN_REFERENCES:
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.text)

    def test_commands_call_only_the_query_script_subcommands(self):
        commands = re.findall(r"^uv run .*$", self.body, flags=re.MULTILINE)
        self.assertEqual(len(commands), 3)
        for command, sub in zip(
            commands, ("request-path", "submit-item", "submit-end")
        ):
            with self.subTest(sub=sub):
                self.assertIn(f'query_docs.py" {sub} ', command)
        self.assertIn("--exit-value 0", commands[2])
        self.assertTrue(SCRIPT.is_file())

    def test_ends_with_response_without_results(self):
        self.assertIn("検索結果の内容", self.body)
        self.assertIn("0 件でも渡す", self.body)


class ManualTest(unittest.TestCase):
    def test_manual_is_separate_from_automatic_tests(self):
        self.assertTrue(MANUAL.is_file())
        self.assertNotRegex(MANUAL.name, r"^test_.*\.py$")
        self.assertEqual(MANUAL.suffix, ".md")
        self.assertEqual(MANUAL.parent.name, "manual")
        self.assertEqual(list(MANUAL.parent.glob("test_*.py")), [])


if __name__ == "__main__":
    unittest.main()
