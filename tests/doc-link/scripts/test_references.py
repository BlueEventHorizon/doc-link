import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

from references import extract_references  # noqa: E402

ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
H1 = "a" * 64


class ExtractTest(unittest.TestCase):
    def test_extracts_fields(self):
        text = f'# 題\n\n[x][r]\n\n[r]: sub/b%20c.md#sec%201 "{H1} {ID_B}"\n'
        (ref,) = extract_references(text)
        self.assertEqual(ref.dlid, ID_B)
        self.assertEqual(ref.recorded_hash, H1)
        self.assertEqual(ref.label, "R")  # 大文字小文字を畳んだ値
        self.assertEqual(ref.path, "sub/b c.md")
        self.assertEqual(ref.fragment, "sec 1")
        self.assertEqual(ref.line, 4)

    def test_record_word_variants(self):
        cases = {
            "none": (f'[r]: b.md "{ID_B}"\n', None),
            "valid": (f'[r]: b.md "{H1} {ID_B}"\n', H1),
            "upper": (f'[r]: b.md "{"A" * 64} {ID_B}"\n', None),
            "short": (f'[r]: b.md "{"a" * 63} {ID_B}"\n', None),
            "other": (f'[r]: b.md "メモ {ID_B}"\n', None),
        }
        for name, (text, expected) in cases.items():
            with self.subTest(name=name):
                (ref,) = extract_references(text)
                self.assertEqual(ref.recorded_hash, expected)
                self.assertEqual(ref.dlid, ID_B)

    def test_no_fragment_and_self_reference(self):
        (ref,) = extract_references(f'[r]: #top "{ID_B}"\n')
        self.assertEqual(ref.path, "")
        self.assertEqual(ref.fragment, "top")
        (ref,) = extract_references(f'[r]: b.md "{ID_B}"\n')
        self.assertIsNone(ref.fragment)

    def test_not_formal_references(self):
        cases = {
            "title without dlid": '[r]: b.md "説明"\n',
            "no title": "[r]: b.md\n",
            "inline link": f'[x](b.md "{ID_B}")\n',
            "image": f'![x](b.md "{ID_B}")\n',
            "autolink": "<https://example.com/>\n",
            "html anchor": f'<a href="b.md" title="{ID_B}">x</a>\n',
            "scheme": f'[r]: https://example.com/a.md "{ID_B}"\n',
            "mailto": f'[r]: mailto:a@example.com "{ID_B}"\n',
            "code block": f'```\n[r]: b.md "{ID_B}"\n```\n',
            "indented code": f'    [r]: b.md "{ID_B}"\n',
            "html block": f'<div>\n[r]: b.md "{ID_B}"\n</div>\n',
            "space in destination": f'[r]: b c.md "{ID_B}"\n',
            "uppercase dlid": '[r]: b.md "DLID-0123456789AB"\n',
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                self.assertEqual(extract_references(text), ())

    def test_label_without_definition_is_not_a_reference(self):
        self.assertEqual(extract_references("[x][nothing]\n"), ())

    def test_first_definition_wins(self):
        text = f'[r]: a.md "{ID_A}"\n[r]: b.md "{ID_B}"\n'
        (ref,) = extract_references(text)
        self.assertEqual(ref.dlid, ID_A)

    def test_order_follows_lines(self):
        text = f'[z]: z.md "{ID_A}"\n\n[a]: a.md "{ID_B}"\n'
        refs = extract_references(text)
        self.assertEqual([ref.path for ref in refs], ["z.md", "a.md"])

    def test_frontmatter_offsets_lines(self):
        text = f'---\ntitle: t\n---\n\n[r]: b.md "{ID_B}"\n'
        (ref,) = extract_references(text)
        self.assertEqual(ref.line, 4)


if __name__ == "__main__":
    unittest.main()
