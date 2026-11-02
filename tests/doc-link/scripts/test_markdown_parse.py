"""プラグイン共通 script `markdown_parse.py`（frontmatter・見出し・アンカー行・セクション範囲の解析）の単体テスト。

期待値は実装ではなく、DES-008 §1・§2、REQ-002 FR-002・AC-012、D-033 の規則から導く。
行番号は元の文書（frontmatter を含む）の 1 始まりで、各テストの入力の行を数えて書く。
"""

import sys
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "doc-link" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import markdown_parse  # noqa: E402
from markdown_parse import FrontmatterStatus  # noqa: E402

DOC_ID = "DLID-7k3m9q2x4p8r"
SEC_A = "DLID-4m8q2x7k3p9r"
SEC_B = "DLID-0123456789ab"
SEC_C = "DLID-zzzzzzzzzzzz"


def _lines(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _summary(heading):
    return (
        heading.line,
        heading.level,
        heading.text,
        heading.section_dlid,
        heading.section_start,
        heading.section_end,
    )


class TestHeadings(unittest.TestCase):
    def test_each_heading_has_line_level_text_dlid_and_section_range(self):
        text = _lines(
            "---",  # 1
            "doc_link_id: " + DOC_ID,  # 2
            "---",  # 3
            "",  # 4
            '<a id="' + SEC_A + '"></a>',  # 5
            "",  # 6
            "# 文書の題",  # 7
            "",  # 8
            "前書き。",  # 9
            "",  # 10
            '<a id="' + SEC_B + '"></a>',  # 11
            "",  # 12
            "## 1. **強調**と `code`",  # 13
            "",  # 14
            "本文。",  # 15
            "",  # 16
            "### 1.1 下位",  # 17
            "",  # 18
            "下位の本文。",  # 19
            "",  # 20
            '<a id="' + SEC_C + '"></a>',  # 21
            "",  # 22
            "## 2. 次の節",  # 23
            "",  # 24
            "末尾。",  # 25
        )
        doc = markdown_parse.parse_markdown(text)
        self.assertEqual(doc.line_count, 25)
        self.assertEqual(
            [_summary(h) for h in doc.headings],
            [
                # H1 の範囲は、同じ階層以上の次の見出しが無いので文書の末尾まで
                (7, 1, "文書の題", SEC_A, 7, 25),
                # H2 の範囲は次の H2 の直前まで（下位の H3 を含む）
                (13, 2, "1. **強調**と `code`", SEC_B, 13, 22),
                # H3 の範囲は、より上の階層の次の見出し（H2）の直前まで
                (17, 3, "1.1 下位", None, 17, 22),
                (23, 2, "2. 次の節", SEC_C, 23, 25),
            ],
        )
        self.assertEqual([h.anchor_line for h in doc.headings], [5, 11, None, 21])

    def test_all_atx_levels(self):
        text = _lines(
            "# a", "## b", "### c", "#### d", "##### e", "###### f", "####### g"
        )
        doc = markdown_parse.parse_markdown(text)
        # 7 個の `#` は見出しにならない（CommonMark）
        self.assertEqual(
            [(h.line, h.level, h.text) for h in doc.headings],
            [
                (1, 1, "a"),
                (2, 2, "b"),
                (3, 3, "c"),
                (4, 4, "d"),
                (5, 5, "e"),
                (6, 6, "f"),
            ],
        )
        # 各見出しの範囲は、次の見出しが下位なので文書の末尾まで
        self.assertEqual({h.section_end for h in doc.headings}, {7})

    def test_setext_headings(self):
        text = _lines(
            "題",  # 1
            "===",  # 2
            "",  # 3
            "節",  # 4
            "---",  # 5
            "",  # 6
            "本文。",  # 7
        )
        doc = markdown_parse.parse_markdown(text)
        self.assertEqual(
            [_summary(h) for h in doc.headings],
            [(1, 1, "題", None, 1, 7), (4, 2, "節", None, 4, 7)],
        )

    def test_same_level_heading_ends_previous_section(self):
        text = _lines("## a", "x", "## b", "y", "# c", "z")
        doc = markdown_parse.parse_markdown(text)
        self.assertEqual(
            [(h.line, h.section_start, h.section_end) for h in doc.headings],
            [(1, 1, 2), (3, 3, 4), (5, 5, 6)],
        )

    def test_document_without_trailing_newline(self):
        doc = markdown_parse.parse_markdown("# a\n\nb")
        self.assertEqual(doc.line_count, 3)
        self.assertEqual(_summary(doc.headings[0]), (1, 1, "a", None, 1, 3))

    def test_crlf_line_numbers(self):
        text = "---\r\ndoc_link_id: " + DOC_ID + "\r\n---\r\n\r\n# a\r\n\r\n## b\r\n"
        doc = markdown_parse.parse_markdown(text)
        self.assertEqual(doc.frontmatter_status, FrontmatterStatus.PARSED)
        self.assertEqual(doc.doc_link_id, DOC_ID)
        self.assertEqual(doc.line_count, 7)
        self.assertEqual(
            [(h.line, h.section_end) for h in doc.headings], [(5, 7), (7, 7)]
        )

    def test_no_headings(self):
        doc = markdown_parse.parse_markdown(_lines("本文だけ。"))
        self.assertEqual(doc.headings, ())

    def test_empty_document(self):
        doc = markdown_parse.parse_markdown("")
        self.assertEqual(doc.frontmatter_status, FrontmatterStatus.ABSENT)
        self.assertEqual(doc.line_count, 0)
        self.assertEqual(doc.headings, ())


class TestBlocksAreNotHeadings(unittest.TestCase):
    def test_heading_like_lines_in_code_and_html_blocks(self):
        text = _lines(
            "# 本物",  # 1
            "",  # 2
            "```",  # 3
            "# フェンスの中",  # 4
            "```",  # 5
            "",  # 6
            "~~~",  # 7
            "## チルダのフェンスの中",  # 8
            "~~~",  # 9
            "",  # 10
            "    # インデントのコードブロック",  # 11
            "",  # 12
            "<div>",  # 13
            "# HTML ブロックの中",  # 14
            "</div>",  # 15
            "",  # 16
            "<!--",  # 17
            "## コメントの中",  # 18
            "-->",  # 19
            "",  # 20
            "## 本物 2",  # 21
        )
        doc = markdown_parse.parse_markdown(text)
        self.assertEqual(
            [(h.line, h.level, h.text) for h in doc.headings],
            [(1, 1, "本物"), (21, 2, "本物 2")],
        )
        # コードブロック内の見出し様の行はセクションを区切らない
        self.assertEqual(doc.headings[0].section_end, 21)

    def test_setext_underline_inside_code_block_is_not_heading(self):
        text = _lines("```", "a", "---", "```")
        doc = markdown_parse.parse_markdown(text)
        self.assertEqual(doc.headings, ())


class TestAnchorLine(unittest.TestCase):
    def test_anchor_directly_before_heading_without_blank_line(self):
        # ATX 見出しは段落を中断するので、アンカー行は単独の段落になり、次のブロックが見出しになる
        text = _lines('<a id="' + SEC_A + '"></a>', "# a")
        doc = markdown_parse.parse_markdown(text)
        heading = doc.headings[0]
        self.assertEqual((heading.anchor_line, heading.section_dlid), (1, SEC_A))
        # セクション範囲は見出しの行から始まる
        self.assertEqual(heading.section_start, 2)

    def test_unrecognizable_anchor_id_has_no_dlid(self):
        cases = {
            "not_dlid": "sec-1",
            "upper": "DLID-7K3M9Q2X4P8R",
            "too_short": "DLID-7k3m9q2x4p8",
            "empty": "",
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                text = _lines('<a id="' + value + '"></a>', "", "# a")
                heading = markdown_parse.parse_markdown(text).headings[0]
                self.assertIsNone(heading.section_dlid)
                self.assertEqual(heading.anchor_line, 1)
                self.assertEqual(heading.anchor_id, value)

    def test_paragraphs_that_are_not_anchor_lines(self):
        cases = {
            # アンカー行の後に段落があり、次のブロックが見出しでない
            "paragraph_between": _lines(
                '<a id="' + SEC_A + '"></a>', "", "本文。", "", "# a"
            ),
            # 段落の続きの行（段落に取り込まれている）
            "inside_text_paragraph": _lines(
                "本文。", '<a id="' + SEC_A + '"></a>', "", "# a"
            ),
            # 二つの html_inline 以外の内容を含む
            "with_text": _lines('<a id="' + SEC_A + '">x</a>', "", "# a"),
            # 閉じタグが無い（HTML ブロックとして解析される）
            "open_tag_only": _lines('<a id="' + SEC_A + '">', "", "# a"),
            # 閉じタグが `</a>` でない
            "other_close_tag": _lines('<a id="' + SEC_A + '"></b>', "", "# a"),
            # 開始タグが `<a id="…">` の形でない
            "other_attribute": _lines('<a name="' + SEC_A + '"></a>', "", "# a"),
            "extra_attribute": _lines(
                '<a id="' + SEC_A + '" class="x"></a>', "", "# a"
            ),
            # コードブロック内のアンカー行の様な行
            "in_code_block": _lines("```", '<a id="' + SEC_A + '"></a>', "```", "# a"),
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                heading = markdown_parse.parse_markdown(text).headings[-1]
                self.assertIsNone(heading.section_dlid)
                self.assertIsNone(heading.anchor_line)
                self.assertIsNone(heading.anchor_id)

    def test_anchor_belongs_only_to_the_following_heading(self):
        text = _lines(
            "# a",  # 1
            "",  # 2
            '<a id="' + SEC_A + '"></a>',  # 3
            "",  # 4
            "## b",  # 5
        )
        doc = markdown_parse.parse_markdown(text)
        self.assertEqual(
            [(h.line, h.anchor_line, h.section_dlid) for h in doc.headings],
            [(1, None, None), (5, 3, SEC_A)],
        )


class TestFrontmatter(unittest.TestCase):
    def test_frontmatter_is_not_returned_as_heading_and_lines_match_original(self):
        text = _lines(
            "---",  # 1
            "# YAML のコメント",  # 2
            "title: 見出しではない",  # 3
            "doc_link_id: " + DOC_ID,  # 4
            "---",  # 5
            "# 本文の見出し",  # 6
            "",  # 7
            "本文。",  # 8
        )
        doc = markdown_parse.parse_markdown(text)
        self.assertEqual(doc.frontmatter_status, FrontmatterStatus.PARSED)
        self.assertEqual(
            doc.frontmatter, {"title": "見出しではない", "doc_link_id": DOC_ID}
        )
        self.assertEqual(doc.frontmatter_end_line, 5)
        self.assertEqual(doc.doc_link_id, DOC_ID)
        # 区切りの `---` が直前の行を setext 見出しにすることも、コメント行が ATX 見出しになることも無い
        self.assertEqual(
            [_summary(h) for h in doc.headings], [(6, 1, "本文の見出し", None, 6, 8)]
        )

    def test_empty_frontmatter_is_empty_mapping(self):
        for name, text in {
            "no_lines": _lines("---", "---", "# a"),
            "comment_only": _lines("---", "# c", "---", "# a"),
        }.items():
            with self.subTest(name=name):
                doc = markdown_parse.parse_markdown(text)
                self.assertEqual(doc.frontmatter_status, FrontmatterStatus.PARSED)
                self.assertEqual(doc.frontmatter, {})
                self.assertIsNone(doc.doc_link_id)
                self.assertEqual(
                    [h.line for h in doc.headings], [len(text.splitlines())]
                )

    def test_no_frontmatter_when_first_line_is_not_delimiter(self):
        cases = {
            "heading_first": _lines("# a", "---", "x: 1", "---"),
            "four_dashes": _lines("----", "doc_link_id: " + DOC_ID, "----", "# a"),
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                doc = markdown_parse.parse_markdown(text)
                self.assertEqual(doc.frontmatter_status, FrontmatterStatus.ABSENT)
                self.assertIsNone(doc.frontmatter)
                self.assertIsNone(doc.frontmatter_end_line)
                self.assertIsNone(doc.doc_link_id)
                self.assertIsNotNone(doc.headings)

    def test_leading_blank_lines_and_surrounding_spaces_are_allowed(self):
        cases = {
            "blank_first": (
                _lines("", "", "---", "doc_link_id: " + DOC_ID, "---", "# a"),
                5,
                6,
            ),
            "spaces_around_delimiters": (
                _lines(" --- ", "doc_link_id: " + DOC_ID, "---\t", "# a"),
                3,
                4,
            ),
        }
        for name, (text, end_line, heading_line) in cases.items():
            with self.subTest(name=name):
                doc = markdown_parse.parse_markdown(text)
                self.assertEqual(doc.frontmatter_status, FrontmatterStatus.PARSED)
                self.assertEqual(doc.doc_link_id, DOC_ID)
                self.assertEqual(doc.frontmatter_end_line, end_line)
                self.assertEqual([h.line for h in doc.headings], [heading_line])

    def test_unclosed_frontmatter_is_read_as_absent_but_distinguished(self):
        cases = {
            "unclosed": (_lines("---", "doc_link_id: " + DOC_ID, "", "# a"), [4]),
            "delimiter_only": ("---", []),
        }
        for name, (text, heading_lines) in cases.items():
            with self.subTest(name=name):
                doc = markdown_parse.parse_markdown(text)
                self.assertEqual(doc.frontmatter_status, FrontmatterStatus.UNCLOSED)
                self.assertIsNone(doc.frontmatter)
                self.assertIsNone(doc.frontmatter_end_line)
                self.assertIsNone(doc.doc_link_id)
                # frontmatter が無いものとして、文書全体を本文として解析する
                self.assertEqual([h.line for h in doc.headings], heading_lines)

    def test_yaml_errors_in_other_keys_do_not_hide_doc_link_id(self):
        # 最上位のキーだけを読むので、ほかのキーの誤りで文書 ID が読めなくならない
        cases = {
            "unclosed_flow": _lines("---", "tags: [a", "doc_link_id: " + DOC_ID, "---"),
            "bad_indent": _lines(
                "---", "a: 1", " b: 2", "doc_link_id: " + DOC_ID, "---"
            ),
            "invalid_date_value": _lines(
                "---", "date: 2026-13-01", "doc_link_id: " + DOC_ID, "---"
            ),
            "document_end_marker": _lines(
                "---", "a: 1", "...", "doc_link_id: " + DOC_ID, "---"
            ),
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                doc = markdown_parse.parse_markdown(text + "# a\n")
                self.assertEqual(doc.frontmatter_status, FrontmatterStatus.PARSED)
                self.assertEqual(doc.doc_link_id, DOC_ID)
                self.assertEqual(
                    [h.line for h in doc.headings], [len(text.splitlines()) + 1]
                )

    def test_frontmatter_values_are_read_like_docadvisor(self):
        text = _lines(
            "---",
            "# comment",
            "plain: value",
            'double: "a\\"b"',
            "single: 'it''s'",
            "inline: [x, 'y']",
            "empty_inline: []",
            "block:",
            "  - p",
            "  - q",
            "empty_block:",
            "folded: >",
            "  text",
            "nested:",
            "  child: c",
            "---",
            "# a",
        )
        doc = markdown_parse.parse_markdown(text)
        self.assertEqual(
            doc.frontmatter,
            {
                "plain": "value",
                "double": 'a"b',
                "single": "it's",
                "inline": ["x", "y"],
                "empty_inline": [],
                "block": ["p", "q"],
                "empty_block": [],
                "folded": None,
                "nested": [],
            },
        )

    def test_non_scalar_doc_link_id_is_not_recognized(self):
        cases = {
            "block_list": _lines("---", "doc_link_id:", "  - " + DOC_ID, "---"),
            "inline_list": _lines("---", "doc_link_id: [" + DOC_ID + "]", "---"),
            "block_scalar": _lines("---", "doc_link_id: |", "  " + DOC_ID, "---"),
            "nested": _lines("---", "meta:", "  doc_link_id: " + DOC_ID, "---"),
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                doc = markdown_parse.parse_markdown(text)
                self.assertEqual(doc.frontmatter_status, FrontmatterStatus.PARSED)
                self.assertIsNone(doc.doc_link_id)

    def test_doc_link_id_recognition(self):
        cases = {
            "valid": (DOC_ID, DOC_ID),
            "double_quoted": ('"' + DOC_ID + '"', DOC_ID),
            "single_quoted": ("'" + DOC_ID + "'", DOC_ID),
            "missing": (None, None),
            "null": ("null", None),
            "empty": ('""', None),
            "whitespace": ('"   "', None),
            "number": ("123456789012", None),
            "list": ("[" + DOC_ID + "]", None),
            "upper": ("DLID-7K3M9Q2X4P8R", None),
            "other_prefix": ("DLIX-7k3m9q2x4p8r", None),
        }
        for name, (value, expected) in cases.items():
            with self.subTest(name=name):
                body = ["title: t"] if value is None else ["doc_link_id: " + value]
                doc = markdown_parse.parse_markdown(_lines("---", *body, "---", "# a"))
                self.assertEqual(doc.frontmatter_status, FrontmatterStatus.PARSED)
                self.assertEqual(doc.doc_link_id, expected)

    def test_absent_frontmatter_has_no_doc_link_id(self):
        doc = markdown_parse.parse_markdown(_lines("doc_link_id: " + DOC_ID, "", "# a"))
        self.assertEqual(doc.frontmatter_status, FrontmatterStatus.ABSENT)
        self.assertIsNone(doc.doc_link_id)


if __name__ == "__main__":
    unittest.main()
