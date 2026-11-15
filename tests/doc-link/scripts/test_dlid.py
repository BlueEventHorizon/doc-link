import inspect
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import dlid  # noqa: E402
from markdown_reader import is_dlid, read_document  # noqa: E402

ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
ID_C = "DLID-pqrstvwxyz01"


class IssueTest(unittest.TestCase):
    def test_issued_passes_format_check(self):
        for _ in range(100):
            self.assertTrue(is_dlid(dlid.issue_dlid()))

    def test_ten_thousand_are_unique(self):
        issued = {dlid.issue_dlid() for _ in range(10000)}
        self.assertEqual(len(issued), 10000)

    def test_value_is_not_derived_from_document_attributes(self):
        # 発行は文書の属性（本文・ファイル名・パス・タイトル・要約）を入力に持たず、値は乱数だけで決まる
        self.assertEqual(inspect.signature(dlid.issue_dlid).parameters, {})
        for number in (0, 1, (1 << dlid.DLID_BITS) - 1):
            with self.subTest(number=number):
                with mock.patch.object(dlid.secrets, "randbits", return_value=number):
                    first = dlid.issue_dlid()
                    second = dlid.issue_dlid()
                self.assertEqual(first, second)
                self.assertEqual(
                    first,
                    dlid.DLID_PREFIX
                    + "".join(
                        dlid.CROCKFORD_ALPHABET[(number >> (5 * i)) & 0x1F]
                        for i in reversed(range(dlid.DLID_VALUE_LENGTH))
                    ),
                )


class RecognitionTest(unittest.TestCase):
    def doc_id(self, value_line):
        return read_document(f"---\n{value_line}\n---\n# T\n").frontmatter.doc_link_id

    def test_unrecognized_doc_link_id_is_none(self):
        for line in (
            "doc_link_id: DLID-0123456789AB",
            "doc_link_id: DLID-0123456789a",
            "doc_link_id: DLID-0123456789abc",
            "doc_link_id: DLID-0123456789il",
            "doc_link_id:",
            "doc_link_id: null",
            "doc_link_id: [DLID-0123456789ab]",
            "doc_link_id: |",
        ):
            with self.subTest(line=line):
                self.assertIsNone(self.doc_id(line))

    def test_recognized(self):
        self.assertEqual(self.doc_id(f"doc_link_id: {ID_A}"), ID_A)

    def test_unrecognized_heading_word_is_not_section_id(self):
        document = read_document("# T DLID-0123456789AB\n\n## U DLID-0123456789il\n")
        self.assertEqual([h.section_id for h in document.headings], [None, None])

    def test_recognized_heading_word(self):
        document = read_document(f"# T {ID_A}\n")
        self.assertEqual(document.headings[0].section_id, ID_A)


class DuplicateTest(unittest.TestCase):
    def test_no_duplicates(self):
        docs = [
            ("a.md", f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n"),
            ("b.md", f"---\ndoc_link_id: {ID_C}\n---\n# T\n"),
        ]
        self.assertEqual(dlid.find_duplicates(docs), [])

    def test_same_document_id_in_two_files(self):
        docs = [
            ("a.md", f"---\ndoc_link_id: {ID_A}\n---\n# T\n"),
            ("b.md", f"---\ndoc_link_id: {ID_A}\n---\n# T\n"),
            ("c.md", f"---\ndoc_link_id: {ID_B}\n---\n# T\n"),
        ]
        result = dlid.find_duplicates(docs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].dlid, ID_A)
        self.assertEqual([loc.path for loc in result[0].locations], ["a.md", "b.md"])
        self.assertTrue(
            all(loc.kind == dlid.KIND_DOCUMENT for loc in result[0].locations)
        )

    def test_same_section_id_in_two_files(self):
        docs = [
            ("a.md", f"# T\n\n## S {ID_A}\n"),
            ("b.md", f"## S2 {ID_A}\n"),
        ]
        result = dlid.find_duplicates(docs)
        self.assertEqual(len(result), 1)
        self.assertEqual(
            [(loc.path, loc.line, loc.heading_text) for loc in result[0].locations],
            [("a.md", 2, f"S {ID_A}"), ("b.md", 0, f"S2 {ID_A}")],
        )

    def test_same_section_id_within_one_document(self):
        result = dlid.find_duplicates([("a.md", f"# A {ID_A}\n\n## B {ID_A}\n")])
        self.assertEqual(len(result), 1)
        self.assertEqual([loc.line for loc in result[0].locations], [0, 2])

    def test_document_id_and_section_id_share_one_space(self):
        docs = [("a.md", f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_A}\n")]
        result = dlid.find_duplicates(docs)
        self.assertEqual(len(result), 1)
        self.assertEqual(
            [loc.kind for loc in result[0].locations],
            [dlid.KIND_DOCUMENT, dlid.KIND_SECTION],
        )

    def test_link_title_dlid_is_not_counted(self):
        docs = [
            ("a.md", f'# T {ID_A}\n\n[x]: b.md "{ID_A}"\n'),
        ]
        self.assertEqual(dlid.find_duplicates(docs), [])

    def test_unrecognized_ids_are_not_counted(self):
        docs = [
            (
                "a.md",
                "---\ndoc_link_id: DLID-0123456789AB\n---\n# T DLID-0123456789AB\n",
            ),
            ("b.md", "---\ndoc_link_id: DLID-0123456789AB\n---\n"),
        ]
        self.assertEqual(dlid.find_duplicates(docs), [])


if __name__ == "__main__":
    unittest.main()
