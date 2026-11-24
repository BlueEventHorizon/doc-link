"""query-docs の SKILL.md の検査。

設計書が値や形式を定めていない点の解釈:
- 検索の失敗（`collect` の終了コード 3）と、その他のエラーは、どちらも `errors` をそのまま返す（結果を補わない）。
- 利用者が二択を選ばずに終えたときは、`--choice` を推測せず、検索せずに終える。
"""

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "query-docs"
SKILL_MD = SKILL_DIR / "SKILL.md"

COMMAND_PREFIX = 'uv run --locked "${CLAUDE_SKILL_DIR}/scripts/'
# 配布物から開発用の文書を参照していないことを確かめる検索語（SKILL.md 全体が範囲）
FORBIDDEN_REFERENCES = ("docs/specs", "docs/rules", "DES-", "REQ-", "ADR-", "D-0")


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
        self.assertEqual(keys["name"], "query-docs")
        self.assertRegex(keys["description"], r"[ぁ-んァ-ヶ一-龠]")

    def test_runs_in_the_parent_context(self):
        keys = {line.split(":", 1)[0] for line in self.frontmatter}
        self.assertNotIn("context", keys)
        self.assertNotIn("agent", keys)
        self.assertNotIn("context: fork", self.text)

    def test_declares_scope_and_does_not_call_itself(self):
        self.assertIn(
            "このスキルは文書の検索のみを行う。親が依頼している他の作業を引き継いではならない",
            self.body,
        )
        self.assertIn("自身を Skill ツールで呼ばない", self.body)

    def test_does_not_refer_to_development_documents(self):
        for needle in FORBIDDEN_REFERENCES:
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.text)

    def test_code_blocks_only_call_the_query_script(self):
        blocks = code_blocks(self.body)
        self.assertTrue(blocks)
        for block in blocks:
            for line in block.strip().splitlines():
                with self.subTest(line=line):
                    self.assertTrue(line.startswith(COMMAND_PREFIX), line)
                    script = line[len(COMMAND_PREFIX) :].split('"', 1)[0]
                    self.assertTrue((SKILL_DIR / "scripts" / script).is_file(), script)

    def test_handles_every_prepare_action(self):
        for needle in (
            "initial_build_required",
            "confirm_rebuild",
            "invoke_query_worker",
            "終了コードが 1 のときは、検索を停止し",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.body)
        self.assertIn("旧版（既存の ToC）で検索する選択肢を出さない", self.body)

    def test_does_not_define_the_meaning_of_exit_code_1(self):
        # 1 は区別のないエラー。理由は script の表が持ち、SKILL は行動だけを書く
        self.assertNotIn("終了コードが 1 のときは、判定不能", self.body)

    def test_asks_two_choices_with_scale_and_passes_choice(self):
        self.assertIn("AskUserQuestion", self.body)
        self.assertIn("scale", self.body)
        self.assertIn("再構築してから検索する", self.body)
        self.assertIn("既存の ToC のまま検索する", self.body)
        self.assertIn("--choice rebuild", self.body)
        self.assertIn("--choice existing", self.body)
        self.assertIn("そのまま渡す", self.body)
        self.assertIn("index-docs", self.body)

    def test_rebuild_passes_only_the_target_file_to_index_docs(self):
        # D-063: 検査した対象を、script が書いた対象指定ファイルで渡す。AI は対象指定を引数へ書き写さない
        for needle in (
            "`--target-file {target_file}` だけである",
            "返されたままの値を渡す",
            "自分で引数へ書き写さない",
            "`--choice rebuild --target-file {target_file}`",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.body)
        # 保存済みの指定を読んで引数へ戻す手順が、残っていない
        for needle in ("target_spec_source", "`target_spec` の `paths`"):
            with self.subTest(absent=needle):
                self.assertNotIn(needle, self.body)

    def test_invokes_query_worker_with_search_id_only_and_does_not_wait_with_wakeup(
        self,
    ):
        self.assertIn("doc-link:query-worker", self.body)
        self.assertIn("検索 ID（`search_id`）だけ", self.body)
        self.assertIn("ScheduleWakeup", self.body)
        self.assertIn("待たない", self.body)

    def test_returns_version_freshness_and_does_not_fill_failures(self):
        for needle in (
            "toc_version",
            "freshness",
            "freshness_notice",
            "path_notice",
            "反映していない可能性",
            "結果を補わない",
            "cleanup",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.body)

    def test_passes_only_a_search_request_even_if_parent_asks_for_edits(self):
        self.assertIn("検索の依頼としてだけ扱う", self.body)
        self.assertIn("実装・編集・コミット", self.body)
        self.assertIn("--task=-値", self.body)
        self.assertNotIn("$ARGUMENTS", self.body)

    def test_does_not_rewrite_toc_state(self):
        self.assertIn("ToC を現在の状態として再確定しない", self.body)


if __name__ == "__main__":
    unittest.main()
