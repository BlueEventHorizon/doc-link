import hashlib
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import content_hash  # noqa: E402
from content_hash import (  # noqa: E402
    RECORD_LENGTH,
    document_content_hash,
    is_record_word,
    record_matches,
    section_content_hashes,
    title_value,
)
from markdown_reader import read_document  # noqa: E402

ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
H1 = "a" * RECORD_LENGTH
H2 = "b" * RECORD_LENGTH


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def doc(record=None, body="本文\n", link_text="参照", dest="b.md"):
    title = f"{record} {ID_B}" if record else ID_B
    return f'# 題 {ID_A}\n\n{body}\n[{link_text}][r]\n\n[r]: {dest} "{title}"\n'


class RecordWordTest(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(is_record_word(H1))
        self.assertTrue(is_record_word("0123456789abcdef"[:RECORD_LENGTH]))

    def test_invalid(self):
        n = RECORD_LENGTH
        for word in (
            None,
            "",
            "A" * n,
            "a" * (n - 1),
            "a" * (n + 1),
            "g" * n,
            "a" * (n - 1) + "G",
        ):
            with self.subTest(word=word):
                self.assertFalse(is_record_word(word))

    def test_the_full_hash_is_not_a_record_word(self):
        self.assertFalse(is_record_word(sha("x")))

    def test_title_value_is_a_record_word_taken_from_the_head_of_the_hash(self):
        full = document_content_hash("# T\n")
        self.assertEqual(len(full), 64)
        self.assertEqual(title_value(full), full[:RECORD_LENGTH])
        self.assertTrue(is_record_word(title_value(full)))

    def test_record_matches_compares_with_the_head_of_the_hash(self):
        full = document_content_hash("# T\n")
        other = document_content_hash("# U\n")
        self.assertTrue(record_matches(title_value(full), full))
        self.assertFalse(record_matches(title_value(other), full))
        self.assertFalse(record_matches(None, full))
        self.assertFalse(record_matches(full, full))

    def test_read_recorded_hash(self):
        definition = read_document(f'[r]: b.md "{H1} {ID_B}"\n').references[0]
        self.assertEqual(content_hash.read_recorded_hash(definition), H1)
        definition = read_document(f'[r]: b.md "{ID_B}"\n').references[0]
        self.assertIsNone(content_hash.read_recorded_hash(definition))
        definition = read_document(
            f'[r]: b.md "{"A" * RECORD_LENGTH} {ID_B}"\n'
        ).references[0]
        self.assertIsNone(content_hash.read_recorded_hash(definition))


class DocumentHashTest(unittest.TestCase):
    def test_known_vector(self):
        text = "# T\n"
        self.assertEqual(document_content_hash(text), sha(text))
        self.assertEqual(
            document_content_hash(""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )

    def test_includes_frontmatter(self):
        a = f"---\ndoc_link_id: {ID_A}\n---\n# T\n"
        b = f"---\ndoc_link_id: {ID_B}\n---\n# T\n"
        self.assertEqual(document_content_hash(a), sha(a))
        self.assertNotEqual(document_content_hash(a), document_content_hash(b))

    def test_line_endings_are_kept(self):
        self.assertNotEqual(
            document_content_hash("# T\nx\n"), document_content_hash("# T\r\nx\r\n")
        )
        self.assertNotEqual(
            document_content_hash("# T\nx\n"), document_content_hash("# T\rx\r")
        )

    def test_changes_alter_hash(self):
        base = document_content_hash(doc())
        variants = {
            "body": doc(body="別の本文\n"),
            "heading": doc().replace("# 題", "# 別題"),
            "link text": doc(link_text="別の表示"),
            "link dest": doc(dest="c.md"),
            "dlid added": doc().replace("# 題", f"# 題 {ID_B}\n\n## 追加 {ID_A}\n# 題"),
        }
        for name, text in variants.items():
            with self.subTest(name=name):
                self.assertNotEqual(document_content_hash(text), base)

    def test_record_rewrite_does_not_change_hash(self):
        self.assertEqual(
            document_content_hash(doc(record=H1)), document_content_hash(doc(record=H2))
        )

    def test_title_dlid_rewrite_does_not_change_hash(self):
        # 参照先の付け替えは、参照記述の違いとして別に検出する。内容ハッシュには現れない。
        self.assertEqual(
            document_content_hash(doc()),
            document_content_hash(doc().replace(ID_B, "DLID-pqrstvwxyz01")),
        )

    def test_first_title_does_not_change_hash(self):
        # title の無い定義と、title を書いた定義は、同じ値になる。
        untitled = doc().replace(f' "{ID_B}"', "")
        self.assertNotIn(ID_B, untitled)
        for text in (doc(), doc(record=H1)):
            with self.subTest(text=text):
                self.assertEqual(
                    document_content_hash(text), document_content_hash(untitled)
                )
        self.assertEqual(document_content_hash(untitled), sha(untitled))

    def test_title_removed_bytes_only(self):
        for text, title in (
            (doc(record=H1), f' "{H1} {ID_B}"'),
            (doc(), f' "{ID_B}"'),
        ):
            with self.subTest(title=title):
                self.assertEqual(
                    document_content_hash(text), sha(text.replace(title, ""))
                )

    def test_free_text_in_formal_title_is_removed(self):
        text = f'[r]: b.md "説明 {H1} {ID_B}"\n'
        self.assertEqual(document_content_hash(text), sha("[r]: b.md\n"))

    def test_title_not_ending_in_dlid_is_not_removed(self):
        for title in ("説明", H1, f"{ID_B} 後ろ"):
            with self.subTest(title=title):
                text = f'[r]: b.md "{title}"\n'
                self.assertEqual(document_content_hash(text), sha(text))
                self.assertNotEqual(
                    document_content_hash(text), document_content_hash("[r]: b.md\n")
                )

    def test_link_destination_change_alters_hash(self):
        self.assertNotEqual(
            document_content_hash(f'[r]: b.md "{ID_B}"\n'),
            document_content_hash(f'[r]: c.md "{ID_B}"\n'),
        )

    def test_inline_link_title_is_not_removed(self):
        text = f'[x](b.md "{H1} {ID_B}")\n'
        other = f'[x](b.md "{H2} {ID_B}")\n'
        self.assertEqual(document_content_hash(text), sha(text))
        self.assertNotEqual(document_content_hash(text), document_content_hash(other))

    def test_title_quote_styles(self):
        for opener, closer in (("'", "'"), ("(", ")")):
            with self.subTest(opener=opener):
                title = f" {opener}{H1} {ID_B}{closer}"
                text = f"[r]: b.md{title}\n"
                self.assertEqual(
                    document_content_hash(text), sha(text.replace(title, ""))
                )

    def test_title_on_the_next_line_is_removed(self):
        text = f'[r]: b.md\n  "{H1} {ID_B}"\n'
        self.assertEqual(document_content_hash(text), sha("[r]: b.md\n"))

    def test_escaped_or_entity_title_is_removed(self):
        for title in (f'"a\\" {H1} {ID_B}"', f'"&#97;{"a" * 63} {ID_B}"'):
            with self.subTest(title=title):
                text = f"[r]: b.md {title}\n"
                self.assertEqual(document_content_hash(text), sha("[r]: b.md\n"))

    def test_line_ending_after_title_is_kept(self):
        text = f'[r]: b.md "{ID_B}"\r\n'
        self.assertEqual(document_content_hash(text), sha("[r]: b.md\r\n"))

    def test_two_documents_referencing_each_other_do_not_chain(self):
        a1 = f'# A {ID_A}\n\n[b][r]\n\n[r]: b.md "{H1} {ID_B}"\n'
        a2 = f'# A {ID_A}\n\n[b][r]\n\n[r]: b.md "{H2} {ID_B}"\n'
        b1 = f'# B {ID_B}\n\n[a][r]\n\n[r]: a.md "{document_content_hash(a1)} {ID_A}"\n'
        b2 = f'# B {ID_B}\n\n[a][r]\n\n[r]: a.md "{document_content_hash(a2)} {ID_A}"\n'
        self.assertEqual(document_content_hash(a1), document_content_hash(a2))
        self.assertEqual(document_content_hash(b1), document_content_hash(b2))
        a3 = f'# A {ID_A}\n\n[b][r]\n\n[r]: b.md "{document_content_hash(b1)} {ID_B}"\n'
        self.assertEqual(document_content_hash(a3), document_content_hash(a1))


def sections_doc(first="一\n", second="二\n", prefix="前\n", record=H1):
    return (
        f"{prefix}# 見出し1 {ID_A}\n\n{first}\n"
        f'## 見出し2 {ID_B}\n\n{second}\n[r]: b.md "{record} {ID_B}"\n'
        "# 見出し3\n\n三\n"
    )


class SectionHashTest(unittest.TestCase):
    def test_range_bytes(self):
        text = sections_doc(record="c" * RECORD_LENGTH)
        document = read_document(text)
        heading = document.headings[1]
        raw = "".join(document.lines[heading.start_line : heading.section_end_line])
        self.assertEqual(
            section_content_hashes(text)[1],
            sha(raw.replace(f' "{"c" * RECORD_LENGTH} {ID_B}"', "")),
        )

    def test_outside_change_keeps_hash(self):
        base = section_content_hashes(sections_doc())
        changed = section_content_hashes(sections_doc(prefix="前の変更\n"))
        self.assertEqual(base[1], changed[1])
        self.assertEqual(base[2], changed[2])
        self.assertNotEqual(
            base[0], section_content_hashes(sections_doc(first="x\n"))[0]
        )

    def test_sibling_change_keeps_hash(self):
        base = section_content_hashes(sections_doc())
        changed = section_content_hashes(sections_doc().replace("三", "別"))
        self.assertEqual(base[:2], changed[:2])
        self.assertNotEqual(base[2], changed[2])

    def test_inside_change_alters_hash(self):
        base = section_content_hashes(sections_doc())
        changed = section_content_hashes(sections_doc(second="変更\n"))
        self.assertNotEqual(base[1], changed[1])
        self.assertNotEqual(base[0], changed[0])

    def test_record_rewrite_keeps_section_hash(self):
        a = section_content_hashes(sections_doc(record=H1))
        b = section_content_hashes(sections_doc(record=H2))
        self.assertEqual(a, b)

    def test_record_outside_range_does_not_alter_section(self):
        # 見出し1 の範囲には見出し2 の定義が入るが、見出し3 の範囲外の記録は見出し3 に影響しない
        a = section_content_hashes(sections_doc(record=H1))
        b = section_content_hashes(sections_doc(record="d" * RECORD_LENGTH))
        self.assertEqual(a[2], b[2])


if __name__ == "__main__":
    unittest.main()
