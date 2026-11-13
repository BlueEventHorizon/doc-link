import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "index-docs"
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

    def test_frontmatter_has_name_and_japanese_description(self):
        keys = {
            line.split(":", 1)[0]: line.split(":", 1)[1].strip()
            for line in self.frontmatter
        }
        self.assertEqual(keys["name"], "index-docs")
        self.assertRegex(keys["description"], r"[ぁ-んァ-ヶ一-龠]")

    def test_runs_in_the_parent_context(self):
        keys = {line.split(":", 1)[0] for line in self.frontmatter}
        self.assertNotIn("context", keys)
        self.assertNotIn("agent", keys)
        self.assertNotIn("context: fork", self.text)

    def test_declares_scope_and_does_not_call_itself(self):
        self.assertIn(
            "このスキルは ToC の構築・再構築のみを行う。親が依頼している他の作業を引き継いではならない",
            self.body,
        )
        self.assertIn("自身を Skill ツールで呼ばない", self.body)

    def test_does_not_refer_to_development_documents(self):
        for needle in ("docs/specs", "docs/rules", "DES-", "REQ-", "ADR-", "D-0"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.text)

    def test_does_not_contain_internal_limit_factor_or_margin(self):
        self.assertNotRegex(self.text, r"\bH\b")
        for needle in ("1.3", "余白", "許容"):
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

    def test_invokes_toc_updater_with_ids_only_and_does_not_wait_with_wakeup(self):
        self.assertIn("doc-link:toc-updater", self.body)
        self.assertIn("識別値だけ", self.body)
        self.assertIn("最大 10 本", self.body)
        self.assertIn("最大 3 文書", self.body)
        self.assertIn("ScheduleWakeup", self.body)
        self.assertIn("待たない", self.body)

    def test_points_to_follow_up_steps(self):
        self.assertIn("embed-dlid", self.body)
        self.assertIn("check-impact", self.body)

    def test_arguments_are_only_key_and_target_spec(self):
        self.assertIn("ToC 識別キーと Index 対象指定だけ", self.body)
        self.assertNotIn("$ARGUMENTS", self.body)


if __name__ == "__main__":
    unittest.main()
