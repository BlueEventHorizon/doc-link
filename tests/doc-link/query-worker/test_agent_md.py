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
    / "worker_io.py"
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
            "存在しない見出しを作らない",
            "訂正しない",
            "JSON のキーは手順 3 のものだけを使う",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.body)

    def test_answers_every_document_without_skipping_or_keyword_filtering(self):
        # 全文書がいずれかの worker に読まれる（要件 D-056）。担当の文書を飛ばさず、まとめて答えない
        self.assertIn("文書を飛ばさない", self.body)
        self.assertIn("語句の一致で絞り込まず", self.body)
        self.assertIn("1 回の答えに、複数の文書をまとめない", self.body)

    def test_selects_with_priority_on_not_missing_documents(self):
        self.assertIn("取りこぼしを出さないことを優先する", self.body)
        self.assertIn("関連するかどうか迷う文書は、`maybe` とする", self.body)
        self.assertIn("明らかに無関係な文書だけを、`no` とする", self.body)

    def test_answers_with_three_words_and_no_scores(self):
        # 関連の強弱は、閉じた 3 つの語。点数・数・真偽値は書かせない
        for needle in (
            "`yes`: タスクに対して、意味として関連すると判断できる",
            "`maybe`: 判断がつかないが、関連するかもしれない",
            "`no`: 明らかに無関係である",
            '{"relevance": "yes"',
            '{"relevance": "no"}',
            '`"yes"`・`"maybe"`・`"no"` の語のどれかだけである',
            "点数・数・真偽値・ほかの語を書かない",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.body)
        self.assertNotIn('"relevant"', self.body)
        # 関連の薄さを理由に落とす旧い指示が戻らない
        self.assertNotIn("関連の薄い文書を、件数を満たすために加えない", self.body)

    def test_does_not_refer_to_development_documents(self):
        for needle in FORBIDDEN_REFERENCES:
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.text)

    def test_commands_call_only_the_wrapper_with_the_worker_id_as_the_only_argument(
        self,
    ):
        # 引数は、サブコマンドと担当の識別値だけ。`uv run`・プロジェクトのルート・オプションは、ラッパーが持つ
        commands = re.findall(r"^uv run .*$", self.body, flags=re.MULTILINE)
        self.assertEqual(len(commands), 3)
        for command, sub in zip(commands, ("next", "answer", "answer")):
            with self.subTest(sub=sub, command=command):
                self.assertTrue(
                    command.endswith(f'worker_io.py" {sub} {{担当の識別値}}')
                    or command.endswith(
                        f"worker_io.py\" {sub} {{担当の識別値}} <<'EOF'"
                    )
                )
                self.assertNotIn("--", command.replace("--locked", ""))
        self.assertNotIn("query_docs.py", self.body)
        self.assertTrue(SCRIPT.is_file())

    def test_answers_one_document_at_a_time_as_json_on_standard_input(self):
        # Issue #19: 文書を 1 件ずつ受け取って答える。答えを渡せないまま終了にならない
        for needle in (
            "標準入力の JSON で渡す",
            "<<'EOF'",
            "区切り `'EOF'` の引用符を外さない",
            '{"relevance": "no"}',
            "`relevance`・`reason`・`headings` だけである",
            "同じ文書について 3 回までとする",
            "検索は失敗として扱われ",
            "`next` は呼び直さない",
            "`done` が真",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.body)
        for removed in (
            "submit-item",
            "submit-end",
            "終了の値を渡す",
            "--exit-value",
            "submit {",
            "request {",
            "全エントリ",
            "写し",
        ):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, self.body)

    def test_never_names_or_numbers_the_documents_and_answers_headings_only(self):
        # Issue #17・#19: 文書を指す名前・ID・番号は、AI が書き写して誤る。どの文書への答えかは script が持つ位置で決める
        for needle in (
            "文書を指す名前（タイトル）も、文書 ID・セクション ID・番号も、見ず、書かない",
            "script が文書の位置を持っている",
            "答えるのは、script が今見せている 1 件の文書についてだけである",
            "`（同名 k/n）` が付いた見出しは、付いたまま書く",
            "一意に決まる所まで書けばよい",
            "候補に無い見出しを作らない",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.body)
        for removed in ("doc_link_id", "section_id", "section_ids", "DLID-"):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, self.text)

    def test_ends_with_response_without_results(self):
        self.assertIn("検索結果の内容", self.body)
        self.assertIn("応答に書かない", self.body)


class ManualTest(unittest.TestCase):
    def test_manual_is_separate_from_automatic_tests(self):
        self.assertTrue(MANUAL.is_file())
        self.assertNotRegex(MANUAL.name, r"^test_.*\.py$")
        self.assertEqual(MANUAL.suffix, ".md")
        self.assertEqual(MANUAL.parent.name, "manual")
        self.assertEqual(list(MANUAL.parent.glob("test_*.py")), [])


if __name__ == "__main__":
    unittest.main()
