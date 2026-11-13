import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "resolve-dlid"
SKILL_MD = SKILL_DIR / "SKILL.md"

COMMAND_PREFIX = (
    'uv run --locked --exclude-newer "3 days" "${CLAUDE_SKILL_DIR}/scripts/'
)


def split_frontmatter(text):
    lines = text.split("\n")
    assert lines[0] == "---", "frontmatter で始まらない"
    end = lines.index("---", 1)
    return lines[1:end], "\n".join(lines[end + 1 :])


def code_blocks(body):
    return re.findall(r"```[^\n]*\n(.*?)```", body, flags=re.DOTALL)


class SkillMdTest(unittest.TestCase):
    def setUp(self):
        self.text = SKILL_MD.read_text(encoding="utf-8")
        self.frontmatter, self.body = split_frontmatter(self.text)

    def test_frontmatter_has_name_and_description(self):
        keys = {
            line.split(":", 1)[0]: line.split(":", 1)[1].strip()
            for line in self.frontmatter
        }
        self.assertEqual(keys["name"], "resolve-dlid")
        self.assertTrue(keys["description"])
        self.assertRegex(keys["description"], r"[ぁ-んァ-ヶ一-龠]")

    def test_runs_in_the_parent_context(self):
        keys = {line.split(":", 1)[0] for line in self.frontmatter}
        self.assertNotIn("context", keys)
        self.assertNotIn("agent", keys)
        self.assertNotIn("context: fork", self.text)

    def test_declares_scope_and_does_not_call_itself(self):
        self.assertIn(
            "このスキルは DLID の解決のみを行う。親が依頼している他の作業を引き継いではならない",
            self.body,
        )
        self.assertIn("自身を Skill ツールで呼ばない", self.body)

    def test_does_not_refer_to_development_documents(self):
        for needle in ("docs/specs", "docs/rules", "DES-", "REQ-", "ADR-", "D-0"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.text)

    def test_code_blocks_only_call_the_entry_script(self):
        blocks = code_blocks(self.body)
        self.assertTrue(blocks)
        for block in blocks:
            for line in block.strip().splitlines():
                with self.subTest(line=line):
                    self.assertTrue(line.startswith(COMMAND_PREFIX), line)
                    script = line[len(COMMAND_PREFIX) :].split('"', 1)[0]
                    self.assertTrue((SKILL_DIR / "scripts" / script).is_file(), script)

    def test_states_it_writes_nothing_and_points_to_index_docs(self):
        self.assertIn("何も書き込まない", self.body)
        self.assertIn("index-docs", self.body)
        self.assertIn("記録されたパスに無い", self.body)

    def test_does_not_ask_the_user(self):
        self.assertNotIn("AskUserQuestion", self.body)

    def test_arguments_are_only_dlids(self):
        self.assertIn("DLID の並びだけを受け取る", self.body)
        self.assertNotIn("$ARGUMENTS", self.body)


if __name__ == "__main__":
    unittest.main()
