import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "embed-dlid"
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
        self.assertEqual(keys["name"], "embed-dlid")
        self.assertTrue(keys["description"])
        self.assertRegex(keys["description"], r"[ぁ-んァ-ヶ一-龠]")

    def test_runs_in_the_parent_context(self):
        keys = {line.split(":", 1)[0] for line in self.frontmatter}
        self.assertNotIn("context", keys)
        self.assertNotIn("agent", keys)
        self.assertNotIn("context: fork", self.text)

    def test_declares_scope_and_does_not_call_itself(self):
        self.assertIn(
            "このスキルは DLID の付与のみを行う。親が依頼している他の作業を引き継いではならない",
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

    def test_asks_the_user_only_about_the_origin(self):
        self.assertIn("AskUserQuestion", self.body)
        self.assertEqual(self.body.count("AskUserQuestion"), 1)

    def test_points_to_index_docs_as_the_next_step(self):
        self.assertIn("index-docs", self.body)

    def test_arguments_are_only_key_and_target_spec(self):
        self.assertIn("ToC 識別キーと Index 対象指定だけ", self.body)
        self.assertNotIn("$ARGUMENTS", self.body)


if __name__ == "__main__":
    unittest.main()
