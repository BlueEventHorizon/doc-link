import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "plugins" / "doc-link" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import markdown_reader  # noqa: E402
from markdown_reader import is_dlid, read_document, read_frontmatter, split_lines  # noqa: E402

ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
ID_C = "DLID-pqrstvwxyz01"


def frontmatter_of(text):
    return read_frontmatter(split_lines(text))


class DlidFormatTest(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(is_dlid(ID_A))
        self.assertTrue(is_dlid(ID_B))
        self.assertTrue(is_dlid(ID_C))

    def test_uppercase_is_not_recognized(self):
        self.assertFalse(is_dlid("DLID-0123456789AB"))
        self.assertFalse(is_dlid("dlid-0123456789ab"))

    def test_excluded_letters_and_length(self):
        for value in (
            "DLID-0123456789il",
            "DLID-0123456789ou",
            "DLID-0123456789a",
            "DLID-0123456789abc",
            "0123456789ab",
            "DLID-0123456789ab ",
        ):
            with self.subTest(value=value):
                self.assertFalse(is_dlid(value))


class FrontmatterTest(unittest.TestCase):
    def test_with_doc_link_id(self):
        fm = frontmatter_of(f"---\ntitle: T\ndoc_link_id: {ID_A}\n---\n\n# H\n")
        self.assertTrue(fm.present)
        self.assertEqual((fm.start_line, fm.end_line, fm.body_start_line), (0, 3, 4))
        self.assertEqual(fm.doc_link_id, ID_A)
        self.assertEqual(fm.keys["title"], "T")

    def test_without_frontmatter(self):
        fm = frontmatter_of("# H\n\ntext\n")
        self.assertFalse(fm.present)
        self.assertIsNone(fm.doc_link_id)

    def test_no_closing_line_is_not_frontmatter(self):
        text = f"---\ndoc_link_id: {ID_A}\n\n# H\n"
        fm = frontmatter_of(text)
        self.assertFalse(fm.present)
        self.assertIsNone(fm.doc_link_id)

    def test_leading_blank_lines_are_skipped(self):
        fm = frontmatter_of(f"\n\n  ---  \ndoc_link_id: {ID_A}\n---\n")
        self.assertTrue(fm.present)
        self.assertEqual(fm.start_line, 2)
        self.assertEqual(fm.doc_link_id, ID_A)

    def test_not_first_nonblank_line_is_not_frontmatter(self):
        fm = frontmatter_of(f"text\n---\ndoc_link_id: {ID_A}\n---\n")
        self.assertFalse(fm.present)

    def test_frontmatter_without_doc_link_id(self):
        fm = frontmatter_of("---\ntitle: T\n---\nbody\n")
        self.assertTrue(fm.present)
        self.assertIsNone(fm.doc_link_id)

    def test_unrecognized_values_are_all_missing(self):
        cases = {
            "absent": "title: T",
            "empty": "doc_link_id:",
            "empty_with_space": "doc_link_id:   ",
            "null": "doc_link_id: null",
            "tilde": "doc_link_id: ~",
            "sequence": "doc_link_id: [DLID-0123456789ab]",
            "block_sequence": "doc_link_id:\n  - DLID-0123456789ab",
            "mapping": "doc_link_id: {a: DLID-0123456789ab}",
            "block_scalar": "doc_link_id: |\n  DLID-0123456789ab",
            "uppercase": "doc_link_id: DLID-0123456789AB",
            "short": "doc_link_id: DLID-0123456789a",
            "no_prefix": "doc_link_id: 0123456789ab",
            "unclosed_quote": 'doc_link_id: "DLID-0123456789ab',
            "trailing_garbage": 'doc_link_id: "DLID-0123456789ab"x',
            "indented_key": "  doc_link_id: DLID-0123456789ab",
        }
        for name, body in cases.items():
            with self.subTest(name=name):
                fm = frontmatter_of(f"---\n{body}\n---\n")
                self.assertTrue(fm.present)
                self.assertIsNone(fm.doc_link_id)

    def test_quoted_and_commented_values_are_recognized(self):
        for body in (
            f'doc_link_id: "{ID_A}"',
            f"doc_link_id: '{ID_A}'",
            f"doc_link_id: {ID_A} # memo",
            f'doc_link_id: "{ID_A}" # memo',
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    frontmatter_of(f"---\n{body}\n---\n").doc_link_id, ID_A
                )

    def test_yaml_syntax_error_does_not_hide_doc_link_id(self):
        text = f"---\ntitle: [unclosed\n: broken: : :\n\tbad indent\ndoc_link_id: {ID_A}\n---\n"
        self.assertEqual(frontmatter_of(text).doc_link_id, ID_A)

    def test_first_of_duplicate_keys_is_used(self):
        text = f"---\ndoc_link_id: {ID_A}\ndoc_link_id: {ID_B}\n---\n"
        self.assertEqual(frontmatter_of(text).doc_link_id, ID_A)

    def test_crlf_lines(self):
        text = f"---\r\ndoc_link_id: {ID_A}\r\n---\r\n# H\r\n"
        fm = frontmatter_of(text)
        self.assertTrue(fm.present)
        self.assertEqual(fm.doc_link_id, ID_A)


class HeadingTest(unittest.TestCase):
    def headings(self, text):
        return read_document(text).headings

    def test_atx_setext_and_closing_hashes(self):
        text = f"# One {ID_A}\n\n## Two {ID_B} ##\n\nThree\n=====\n\nFour\n----\n"
        headings = self.headings(text)
        self.assertEqual(
            [(h.level, h.start_line, h.end_line) for h in headings],
            [(1, 0, 1), (2, 2, 3), (1, 4, 6), (2, 7, 9)],
        )
        self.assertEqual([h.section_id for h in headings], [ID_A, ID_B, None, None])
        self.assertEqual(headings[1].text, f"Two {ID_B}")

    def test_multiline_setext_takes_last_word_of_last_line(self):
        headings = self.headings(f"Line one\nLine two {ID_A}\n---\n")
        self.assertEqual(len(headings), 1)
        self.assertEqual(headings[0].section_id, ID_A)
        self.assertEqual((headings[0].start_line, headings[0].end_line), (0, 3))

    def test_section_id_must_be_last_word(self):
        headings = self.headings(f"# {ID_A} tail\n\n# only {ID_B.upper()}\n")
        self.assertEqual([h.section_id for h in headings], [None, None])

    def test_section_ranges(self):
        text = "# A\nbody\n## B\nb\n### C\nc\n## D\nd\n# E\ne\n"
        headings = self.headings(text)
        self.assertEqual(
            [(h.start_line, h.section_end_line) for h in headings],
            [(0, 8), (2, 6), (4, 6), (6, 8), (8, 10)],
        )

    def test_section_range_with_frontmatter_offset(self):
        text = f"---\ndoc_link_id: {ID_A}\n---\n# A\n## B\n"
        headings = self.headings(text)
        self.assertEqual(
            [(h.start_line, h.section_end_line) for h in headings], [(3, 5), (4, 5)]
        )

    def test_headings_in_code_blocks_are_not_headings(self):
        text = (
            "# Real\n\n```\n# fenced\n```\n\n    # indented\n\n~~~md\n## tilde\n~~~\n"
        )
        self.assertEqual([h.text for h in self.headings(text)], ["Real"])

    def test_headings_in_html_blocks_are_not_headings(self):
        text = "# Real\n\n<div>\n# in html\n</div>\n\n<!--\n## in comment\n-->\n"
        self.assertEqual([h.text for h in self.headings(text)], ["Real"])

    def test_atx_without_space_is_not_heading(self):
        self.assertEqual(self.headings("#nospace\n"), ())

    def test_unclosed_frontmatter_dashes_do_not_become_headings_spuriously(self):
        text = "---\ntitle: T\n\n# H\n"
        headings = self.headings(text)
        self.assertEqual([(h.level, h.text) for h in headings], [(1, "H")])

    def test_heading_text_excludes_closing_hashes(self):
        headings = self.headings(f"## Title {ID_A} ###\n")
        self.assertEqual(headings[0].text, f"Title {ID_A}")
        self.assertEqual(headings[0].section_id, ID_A)


class ReferenceDefinitionTest(unittest.TestCase):
    def definitions(self, text):
        return read_document(text).references

    def test_title_last_word_and_preceding_word(self):
        hashed = "a" * 64
        text = f'[x]: ./a.md "{hashed} {ID_A}"\n[y]: ./b.md "{ID_B}"\n[z]: ./c.md "note"\n[w]: ./d.md\n'
        defs = {d.label: d for d in self.definitions(text)}
        self.assertEqual((defs["X"].dlid, defs["X"].preceding_word), (ID_A, hashed))
        self.assertEqual((defs["Y"].dlid, defs["Y"].preceding_word), (ID_B, None))
        self.assertEqual((defs["Z"].dlid, defs["Z"].preceding_word), (None, None))
        self.assertEqual((defs["W"].title, defs["W"].dlid), ("", None))

    def test_preceding_word_is_not_judged(self):
        text = f'[x]: ./a.md "not-a-hash {ID_A}"\n'
        self.assertEqual(self.definitions(text)[0].preceding_word, "not-a-hash")

    def test_uppercase_dlid_is_not_a_dlid(self):
        self.assertIsNone(self.definitions(f'[x]: ./a.md "{ID_A.upper()}"\n')[0].dlid)

    def test_path_and_fragment_are_decoded(self):
        d = self.definitions(
            f'[x]: ./dir/a%20b.md#%E8%A6%8B%E5%87%BA%E3%81%97 "{ID_A}"\n'
        )[0]
        self.assertEqual(d.path, "./dir/a b.md")
        self.assertEqual(d.fragment, "見出し")

    def test_self_reference_has_empty_path(self):
        d = self.definitions(f'[x]: #sec "{ID_A}"\n')[0]
        self.assertEqual((d.path, d.fragment), ("", "sec"))

    def test_definition_position(self):
        text = f'---\ndoc_link_id: {ID_A}\n---\n\ntext\n\n[x]: ./a.md "{ID_B}"\n'
        d = self.definitions(text)[0]
        self.assertEqual((d.start_line, d.end_line), (6, 7))

    def test_definition_in_code_block_is_not_a_definition(self):
        text = f'```\n[x]: ./a.md "{ID_A}"\n```\n'
        self.assertEqual(self.definitions(text), ())


class LinkRulesTest(unittest.TestCase):
    """DES-008 §2 の規則 1〜10 を、markdown-it-py の解析結果で確かめる（各規則に少なくとも 1 つの fixture）。"""

    def read(self, text):
        return read_document(text)

    def test_rule_1_label_without_definition_is_not_a_link(self):
        doc = self.read("[text][nolabel] and [nolabel2]\n\n[other]: ./a.md\n")
        self.assertEqual(doc.links, ())

    def test_rule_2_first_definition_wins(self):
        text = f'[foo]: ./first.md "{ID_A}"\n[foo]: ./second.md "{ID_B}"\n\n[foo]\n'
        doc = self.read(text)
        self.assertEqual(
            [(d.href, d.dlid) for d in doc.references], [("./first.md", ID_A)]
        )
        self.assertEqual(
            [(link.href, link.title) for link in doc.links], [("./first.md", ID_A)]
        )

    def test_rule_3_label_normalization_and_case_fold(self):
        text = '[  Foo   Bar  ]: ./a.md "t"\n\n[foo bar] [FOO\tBAR] [ẞ] [Ｆoo bar]\n\n[SS]: ./ss.md "t"\n'
        doc = self.read(text)
        self.assertEqual([d.label for d in doc.references], ["FOO BAR", "SS"])
        self.assertEqual(
            [link.href for link in doc.links], ["./a.md", "./a.md", "./ss.md"]
        )

    def test_rule_3_fullwidth_and_halfwidth_are_different(self):
        doc = self.read("[Ａ]: ./full.md\n\n[A] [Ａ]\n")
        self.assertEqual([link.href for link in doc.links], ["./full.md"])

    def test_rule_4_escapes_and_entities_are_expanded(self):
        text = '[x]: ./a\\_b&amp;c.md "t&amp;\\*u &#35;"\n\n[x]\n'
        doc = self.read(text)
        self.assertEqual(doc.references[0].title, "t&*u #")
        self.assertEqual(doc.references[0].href, "./a_b&c.md")
        self.assertEqual(doc.links[0].title, "t&*u #")

    def test_rule_5_unbracketed_destination_with_space_is_not_a_definition(self):
        doc = self.read('[x]: ./a b.md "t"\n\n[x]\n')
        self.assertEqual(doc.references, ())
        self.assertEqual(doc.links, ())

    def test_rule_6_scheme_destination_is_not_a_reference(self):
        text = f'[x]: https://example.com/a.md "{ID_A}"\n[y]: mailto:a@example.com "{ID_B}"\n[z]: ./a.md "{ID_C}"\n'
        doc = self.read(text)
        self.assertEqual(
            [(d.label, markdown_reader.has_scheme(d.href)) for d in doc.references],
            [("X", True), ("Y", True), ("Z", False)],
        )
        self.assertFalse(markdown_reader.has_scheme("./a:b.md"))
        self.assertFalse(markdown_reader.has_scheme("a.md#x:y"))

    def test_rule_7_percent_encoding_is_decoded(self):
        self.assertEqual(
            markdown_reader.split_destination("dir/%E6%97%A5%E6%9C%AC.md#a%20b"),
            ("dir/日本.md", "a b"),
        )
        doc = self.read("[x]: ./日本 語.md#見出し 1\n")
        self.assertEqual(doc.references, ())
        doc = self.read('[x]: <./日本 語.md#見出し> "t"\n')
        self.assertIn("%", doc.references[0].href)
        self.assertEqual(
            (doc.references[0].path, doc.references[0].fragment),
            ("./日本 語.md", "見出し"),
        )

    def test_rule_8_fragment_splits_document_and_heading(self):
        self.assertEqual(markdown_reader.split_destination("a.md#sec"), ("a.md", "sec"))
        self.assertEqual(markdown_reader.split_destination("a.md"), ("a.md", None))
        self.assertEqual(markdown_reader.split_destination("#sec"), ("", "sec"))
        self.assertEqual(markdown_reader.split_destination("a.md#"), ("a.md", ""))
        self.assertEqual(markdown_reader.split_destination("a.md#x#y"), ("a.md", "x#y"))

    def test_rule_9_image_is_not_a_link(self):
        doc = self.read(
            f'![alt](a.png "{ID_A}") ![ref][img]\n\n[img]: ./i.png "{ID_B}"\n'
        )
        self.assertEqual(doc.links, ())

    def test_rule_10_autolink_and_html_anchor_have_no_title(self):
        text = '<https://example.com/a.md> <a href="./a.md" title="t">h</a>\n\n<div><a href="./b.md" title="t">h</a></div>\n'
        doc = self.read(text)
        self.assertEqual(
            [(link.kind, link.title) for link in doc.links], [("autolink", None)]
        )
        self.assertEqual(doc.references, ())

    def test_inline_link_has_title_but_is_not_a_definition(self):
        doc = self.read(f'[x](./a.md "{ID_A}")\n')
        self.assertEqual(
            [(link.kind, link.title) for link in doc.links], [("link", ID_A)]
        )
        self.assertEqual(doc.references, ())

    def test_inline_link_line_is_the_line_of_the_link_in_a_multiline_paragraph(self):
        doc = self.read(
            "---\nk: v\n---\n# T\n\n"
            "l1 [a](./a.md)\n"
            "l2 [b](./b.md)\\\n"
            "l3 [c](./c.md) [d](./d.md)\n"
            "[e\nf](./e.md)\n"
        )
        self.assertEqual(
            [(link.href, link.line) for link in doc.links],
            [
                ("./a.md", 5),
                ("./b.md", 6),
                ("./c.md", 7),
                ("./d.md", 7),
                ("./e.md", 8),
            ],
        )

    def test_inline_link_line_in_separate_blocks_is_the_block_line(self):
        doc = self.read("[a](./a.md)\n\n- [b](./b.md)\n\n> [c](./c.md)\n")
        self.assertEqual([link.line for link in doc.links], [0, 2, 4])


class AnchorTest(unittest.TestCase):
    def anchors(self, text):
        return [h.anchor for h in read_document(text).headings]

    def test_basic(self):
        self.assertEqual(self.anchors("# Hello World\n"), ["hello-world"])

    def test_punctuation_is_removed(self):
        self.assertEqual(self.anchors("# Foo: Bar (baz)!\n"), ["foo-bar-baz"])

    def test_hyphen_is_kept_and_other_dashes_removed(self):
        self.assertEqual(self.anchors("# A - B\n"), ["a---b"])
        self.assertEqual(self.anchors("# a–b—c\n"), ["abc"])

    def test_symbols_are_removed(self):
        self.assertEqual(self.anchors("# a+b=c $5 ©\n"), ["abc-5-"])

    def test_underscore_is_kept(self):
        self.assertEqual(self.anchors("# snake_case\n"), ["snake_case"])

    def test_letters_are_kept_and_lowercased(self):
        self.assertEqual(self.anchors("# 日本語 見出し Ünï\n"), ["日本語-見出し-ünï"])

    def test_ideographic_space_is_removed(self):
        self.assertEqual(self.anchors("# 日本語　見出し\n"), ["日本語見出し"])

    def test_fullwidth_punctuation_is_removed(self):
        self.assertEqual(self.anchors("# 見出し（注）：説明。\n"), ["見出し注説明"])

    def test_letter_number_is_kept_other_number_removed(self):
        self.assertEqual(self.anchors("# Ⅻ x²\n"), ["ⅻ-x"])

    def test_alphabetic_symbols_are_kept(self):
        # Ⓐ（U+24B6）は Symbol だが Alphabetic 特性を持つので取り除かない（小文字化されて ⓐ になる）
        self.assertEqual(self.anchors("# Ⓐ ⓩ\n"), ["ⓐ-ⓩ"])
        self.assertEqual(
            self.anchors("# \U0001f130 \U0001f170\n"), ["\U0001f130-\U0001f170"]
        )

    def test_non_alphabetic_symbols_next_to_the_kept_ranges_are_removed(self):
        # U+24B5 と U+24EA は範囲の外、U+1F14A は 1F130〜1F149 の外
        self.assertEqual(self.anchors("# a⒵b⓪c\U0001f14ad\n"), ["abcd"])

    def test_emoji_is_removed(self):
        self.assertEqual(self.anchors("# \U0001f600 hi\n"), ["-hi"])

    def test_markdown_markup_is_not_in_the_text(self):
        self.assertEqual(
            self.anchors("# **bold** `code` [link](x.md) ![img alt](i.png)\n"),
            ["bold-code-link-img-alt"],
        )

    def test_entity_is_expanded_before_removal(self):
        self.assertEqual(self.anchors("# &amp; x &copy;\n"), ["-x-"])

    def test_section_id_is_part_of_the_text(self):
        self.assertEqual(self.anchors(f"# Title {ID_A}\n"), ["title-dlid-0123456789ab"])

    def test_setext_multiline_newline_is_removed(self):
        self.assertEqual(
            self.anchors("Line one\nLine two\n===\n"), ["line-oneline-two"]
        )

    def test_duplicates_get_numbers(self):
        self.assertEqual(
            self.anchors("# Foo\n# Foo\n# Foo\n"), ["foo", "foo-1", "foo-2"]
        )

    def test_duplicate_numbers_collide_like_the_original_rule(self):
        self.assertEqual(
            self.anchors("# Foo\n# Foo\n# Foo-1\n# Foo 1\n"),
            ["foo", "foo-1", "foo-1-1", "foo-1-2"],
        )

    def test_anchor_base_has_no_numbering(self):
        self.assertEqual(markdown_reader.anchor_base("Foo Bar"), "foo-bar")

    def test_headings_in_code_blocks_do_not_take_numbers(self):
        self.assertEqual(
            self.anchors("# Foo\n\n```\n# Foo\n```\n\n# Foo\n"), ["foo", "foo-1"]
        )


if __name__ == "__main__":
    unittest.main()
