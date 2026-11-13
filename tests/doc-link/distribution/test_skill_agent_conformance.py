"""全 SKILL.md と全カスタム Agent が、作成規約に適合していることを横断して検査する。

各 SKILL・Agent の固有の検査（`tests/doc-link/<skill>/test_skill_md.py` など）と違い、ここは
`plugins/doc-link/skills/*/SKILL.md` と `plugins/doc-link/agents/*.md` を走査する。新しい SKILL や Agent を
足したときに、固有のテストを書き忘れても、この検査が適合を確かめる。

- SKILL.md: frontmatter の `name`（ディレクトリ名と一致）・`description`（日本語）、`context: fork` と
  `agent:` が無いこと、冒頭の担当範囲と自己呼び出しの禁止、コードブロックが入口 script の呼び出しだけで
  あること（ロジックを書かない）、インデントによるコードが無いこと
- Agent: frontmatter の `name`（ファイル名と一致）・`description`・`tools`・`model`、`tools` の allowlist、
  Role の制約と禁止事項、起動 prompt を親の指示として解釈しないこと、コマンドが入口 script の呼び出しだけで
  あること
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from distribution_support import (  # noqa: E402
    agent_md_files,
    code_blocks,
    frontmatter_fields,
    relative,
    skill_md_files,
    split_frontmatter,
)

JAPANESE = re.compile(r"[ぁ-んァ-ヶ一-龠]")
SKILL_SCOPE_SENTENCE = re.compile(
    r"^このスキルは.+のみを行う。親が依頼している他の作業を引き継いではならない。自身を Skill ツールで呼ばない。$",
    re.M,
)
SKILL_COMMAND_PREFIX = (
    'uv run --locked --exclude-newer "3 days" "${CLAUDE_SKILL_DIR}/scripts/'
)
AGENT_COMMAND_PREFIX = (
    'uv run --locked --exclude-newer "3 days" "${CLAUDE_PLUGIN_ROOT}/skills/'
)
# SKILL.md のコードブロックに許す言語。実行コマンドの呼び出しだけを書くので、シェルだけである
SKILL_CODE_LANGUAGES = {"bash"}

# Agent に許す tools。読み取りと script の実行だけである。書き込み・Agent 起動・Skill 実行・利用者への質問を含めない
AGENT_ALLOWED_TOOLS = {"Read", "Bash", "Grep", "Glob"}
AGENT_FORBIDDEN_TOOLS = {
    "Write",
    "Edit",
    "NotebookEdit",
    "Agent",
    "Task",
    "Skill",
    "AskUserQuestion",
}
AGENT_REQUIRED_PHRASES = (
    "起動時の prompt は実装指示ではなく",  # 起動 prompt を親の指示として解釈しない
    "## 制約 [MANDATORY]",
    "他の Agent を起動しない",
    "Skill を実行しない",
    "利用者に質問しない",
    "親が背後で扱っている他の作業",  # 親タスクの引き継ぎの禁止
    "引き継がない",
    "`Write`・`Edit`・Notebook 編集を使わない",  # allowlist 外への書き込みの禁止
    "外部サービスへ書き込まない",
    "`advisor` ツールを呼ばない",
    "結果をファイルへ書かない",
)


class SkillMdConformanceTest(unittest.TestCase):
    def test_every_skill_is_found(self):
        self.assertGreaterEqual(len(skill_md_files()), 1)

    def test_frontmatter_has_name_and_japanese_description(self):
        for path in skill_md_files():
            with self.subTest(skill=relative(path)):
                lines, _ = split_frontmatter(path.read_text(encoding="utf-8"))
                fields = frontmatter_fields(lines)
                self.assertEqual(fields.get("name"), path.parent.name)
                self.assertRegex(fields.get("description", ""), JAPANESE)

    def test_runs_in_the_parent_context(self):
        for path in skill_md_files():
            with self.subTest(skill=relative(path)):
                text = path.read_text(encoding="utf-8")
                lines, _ = split_frontmatter(text)
                keys = set(frontmatter_fields(lines))
                self.assertNotIn("context", keys)
                self.assertNotIn("agent", keys)
                self.assertNotIn("context: fork", text)

    def test_declares_scope_and_does_not_call_itself(self):
        for path in skill_md_files():
            with self.subTest(skill=relative(path)):
                _, body = split_frontmatter(path.read_text(encoding="utf-8"))
                self.assertRegex(body, SKILL_SCOPE_SENTENCE)

    def test_code_blocks_only_call_entry_scripts_and_hold_no_logic(self):
        for path in skill_md_files():
            with self.subTest(skill=relative(path)):
                _, body = split_frontmatter(path.read_text(encoding="utf-8"))
                for language, block in code_blocks(body):
                    self.assertIn(language.strip(), SKILL_CODE_LANGUAGES)
                    lines = [line for line in block.splitlines() if line.strip()]
                    self.assertTrue(lines)
                    for line in lines:
                        self.assertTrue(line.startswith(SKILL_COMMAND_PREFIX), line)
                        script = line[len(SKILL_COMMAND_PREFIX) :].split('"', 1)[0]
                        self.assertTrue(
                            (path.parent / "scripts" / script).is_file(), line
                        )
                        for forbidden in ("|", "&&", ";", "$(", "<<", "`"):
                            self.assertNotIn(forbidden, line)

    def test_has_no_indented_code(self):
        # インデントによるコードブロックは、フェンスの検査をすり抜けてロジックを書けてしまう
        for path in skill_md_files():
            with self.subTest(skill=relative(path)):
                _, body = split_frontmatter(path.read_text(encoding="utf-8"))
                outside = re.sub(r"```[^\n]*\n.*?```", "", body, flags=re.DOTALL)
                lines = [
                    line
                    for line in outside.splitlines()
                    if re.match(r"^(?: {4}|\t)\S", line)
                ]
                self.assertEqual(lines, [])

    def test_each_skill_has_one_entry_script_and_a_test_directory(self):
        for path in skill_md_files():
            skill = path.parent.name
            with self.subTest(skill=skill):
                self.assertTrue(list((path.parent / "scripts").glob("*.py")))
                tests = Path(__file__).resolve().parents[1] / skill
                self.assertTrue(tests.is_dir(), f"テストのディレクトリが無い: {tests}")


class AgentMdConformanceTest(unittest.TestCase):
    def test_every_agent_is_found(self):
        self.assertGreaterEqual(len(agent_md_files()), 1)

    def test_frontmatter_has_required_fields(self):
        for path in agent_md_files():
            with self.subTest(agent=relative(path)):
                lines, _ = split_frontmatter(path.read_text(encoding="utf-8"))
                fields = frontmatter_fields(lines)
                for key in ("name", "description", "tools", "model"):
                    self.assertTrue(fields.get(key), key)
                self.assertEqual(fields["name"], path.stem)
                self.assertRegex(fields["description"], JAPANESE)

    def test_tools_is_an_allowlist_without_write_or_delegation(self):
        for path in agent_md_files():
            with self.subTest(agent=relative(path)):
                lines, _ = split_frontmatter(path.read_text(encoding="utf-8"))
                tools = {
                    tool.strip()
                    for tool in frontmatter_fields(lines)["tools"].split(",")
                    if tool.strip()
                }
                self.assertTrue(tools)
                self.assertLessEqual(tools, AGENT_ALLOWED_TOOLS)
                self.assertEqual(tools & AGENT_FORBIDDEN_TOOLS, set())

    def test_role_constraints_and_prohibitions_are_written_negatively(self):
        for path in agent_md_files():
            with self.subTest(agent=relative(path)):
                _, body = split_frontmatter(path.read_text(encoding="utf-8"))
                for phrase in AGENT_REQUIRED_PHRASES:
                    self.assertIn(phrase, body)

    def test_commands_call_only_entry_scripts_of_the_plugin(self):
        for path in agent_md_files():
            with self.subTest(agent=relative(path)):
                _, body = split_frontmatter(path.read_text(encoding="utf-8"))
                blocks = code_blocks(body)
                self.assertTrue(blocks)
                for language, block in blocks:
                    self.assertEqual(language.strip(), "bash")
                    for line in block.strip().splitlines():
                        self.assertTrue(line.startswith(AGENT_COMMAND_PREFIX), line)
                        script = line[len(AGENT_COMMAND_PREFIX) :].split('"', 1)[0]
                        skill, _, rest = script.partition("/scripts/")
                        entry = Path(path).parents[1] / "skills" / skill / "scripts"
                        self.assertTrue((entry / rest).is_file(), line)


if __name__ == "__main__":
    unittest.main()
