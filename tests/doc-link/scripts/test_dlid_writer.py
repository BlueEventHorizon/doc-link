import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import dlid_writer  # noqa: E402
import embed_plan  # noqa: E402
from dlid import KIND_DOCUMENT, KIND_SECTION  # noqa: E402

D1 = "DLID-000000000001"
D2 = "DLID-000000000002"
D3 = "DLID-000000000003"
D4 = "DLID-000000000004"
ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
ID_C = "DLID-pqrstvwxyz01"
ID_D = "DLID-zzzzzzzzzzzy"


def fixed_issuer():
    values = iter(f"DLID-{n:012d}" for n in range(1, 1000))
    return lambda: next(values)


class WriterTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def read(self, path):
        return (self.root / path).read_bytes().decode("utf-8")

    def plan(self, files, origins=None):
        return embed_plan.build_plan(
            self.root, files, origins=origins, issue=fixed_issuer()
        )

    def embed(self, text, name="a.md"):
        """1 つの文書へ付与し、書き込み後の文書を返す。"""
        self.write(name, text)
        result = dlid_writer.apply_plan(self.root, self.plan([name]))
        self.assertTrue(result.succeeded, result.failed)
        return self.read(name)

    def snapshot(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }

    def temp_files(self):
        directory = self.root / ".temp" / "doc-link" / "embed-dlid"
        return sorted(directory.iterdir()) if directory.exists() else []


class ExactBytesTest(WriterTestBase):
    """書き込み後の差分が[DLID]だけである。期待するバイト列は設計書の規則から導いて固定する。"""

    def test_atx_without_frontmatter(self):
        self.assertEqual(
            self.embed("# Title\n\nbody\n"),
            f"---\ndoc_link_id: {D1}\n---\n# Title {D2}\n\nbody\n",
        )

    def test_atx_with_closing_hashes_keeps_them_after_the_dlid(self):
        text = "---\ntitle: x\n---\n## Title ##\n\n## Other   ##   \n"
        self.assertEqual(
            self.embed(text),
            f"---\ntitle: x\ndoc_link_id: {D1}\n---\n## Title {D2} ##\n\n## Other {D3}   ##   \n",
        )

    def test_atx_empty_heading(self):
        self.assertEqual(self.embed("##\n"), f"---\ndoc_link_id: {D1}\n---\n## {D2}\n")

    def test_setext_headings(self):
        text = "Title\n=====\n\nSub\nline two\n---\n"
        self.assertEqual(
            self.embed(text),
            f"---\ndoc_link_id: {D1}\n---\nTitle {D2}\n=====\n\nSub\nline two {D3}\n---\n",
        )

    def test_setext_keeps_trailing_spaces_after_the_dlid(self):
        self.assertEqual(
            self.embed("Title  \n=====\n"),
            f"---\ndoc_link_id: {D1}\n---\nTitle {D2}  \n=====\n",
        )

    def test_heading_in_code_block_is_not_written(self):
        text = "# T\n\n```\n# not a heading\n```\n\n    # indented code\n\n<div>\n# html block\n</div>\n"
        self.assertEqual(
            self.embed(text),
            f"---\ndoc_link_id: {D1}\n---\n# T {D2}\n\n```\n# not a heading\n```\n\n    # indented code\n\n<div>\n# html block\n</div>\n",
        )

    def test_without_frontmatter_creates_one_at_the_top(self):
        self.assertEqual(
            self.embed("text only\n"), f"---\ndoc_link_id: {D1}\n---\ntext only\n"
        )

    def test_existing_unrecognised_value_is_replaced(self):
        text = "---\ndoc_link_id: bogus\nother: 1\n---\n# T\n"
        self.assertEqual(
            self.embed(text),
            f"---\ndoc_link_id: {D1}\nother: 1\n---\n# T {D2}\n",
        )

    def test_existing_ids_are_kept(self):
        text = f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n\n## U\n"
        self.assertEqual(
            self.embed(text),
            f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n\n## U {D1}\n",
        )

    def test_crlf_is_kept(self):
        self.assertEqual(
            self.embed("# T\r\n\r\nbody\r\n"),
            f"---\r\ndoc_link_id: {D1}\r\n---\r\n# T {D2}\r\n\r\nbody\r\n",
        )
        self.assertEqual(
            self.embed("---\r\nx: 1\r\n---\r\n# T\r\n", name="b.md"),
            f"---\r\nx: 1\r\ndoc_link_id: {D1}\r\n---\r\n# T {D2}\r\n",
        )

    def test_cr_only_is_kept(self):
        self.assertEqual(
            self.embed("# T\rbody\r"),
            f"---\rdoc_link_id: {D1}\r---\r# T {D2}\rbody\r",
        )

    def test_no_trailing_newline(self):
        self.assertEqual(self.embed("# T"), f"---\ndoc_link_id: {D1}\n---\n# T {D2}")

    def test_links_html_and_text_are_untouched(self):
        text = (
            "# T\n\n"
            '<a id="x"></a>\n'
            '[inline](other.md "title") and [ref][r] <https://example.com>\n\n'
            f'[r]: other.md "{"a" * 64} {ID_C}"\n'
        )
        self.assertEqual(
            self.embed(text),
            f"---\ndoc_link_id: {D1}\n---\n# T {D2}\n\n"
            '<a id="x"></a>\n'
            '[inline](other.md "title") and [ref][r] <https://example.com>\n\n'
            f'[r]: other.md "{"a" * 64} {ID_C}"\n',
        )

    def test_utf8_text_is_kept(self):
        self.assertEqual(
            self.embed("# 見出し\n\n本文 ✓\n"),
            f"---\ndoc_link_id: {D1}\n---\n# 見出し {D2}\n\n本文 ✓\n",
        )

    def test_blockquote_heading(self):
        self.assertEqual(
            self.embed("> ## Quoted\n"),
            f"---\ndoc_link_id: {D1}\n---\n> ## Quoted {D2}\n",
        )

    def test_written_items_report_position_in_the_written_document(self):
        self.write("a.md", "# T\n\n## U\n")
        result = dlid_writer.apply_plan(self.root, self.plan(["a.md"]))
        self.assertEqual(
            [(i.kind, i.dlid, i.replaced, i.line, i.heading) for i in result.written],
            [
                (KIND_DOCUMENT, D1, None, None, None),
                (KIND_SECTION, D2, None, 4, f"T {D2}"),
                (KIND_SECTION, D3, None, 6, f"U {D3}"),
            ],
        )


class RefusalTest(WriterTestBase):
    def test_unclosed_frontmatter_is_not_written(self):
        text = "---\ntitle: x\n# T\n"
        self.write("a.md", text)
        before = self.snapshot()
        result = dlid_writer.apply_plan(self.root, self.plan(["a.md"]))
        self.assertFalse(result.succeeded)
        self.assertEqual(result.written, ())
        self.assertEqual([f.path for f in result.failed], ["a.md"])
        self.assertEqual(result.failed[0].location, "frontmatter")
        self.assertEqual(self.snapshot(), before)

    def test_unclosed_frontmatter_after_blank_lines_is_not_written(self):
        self.write("a.md", "\n\n---\ntitle: x\n")
        result = dlid_writer.apply_plan(self.root, self.plan(["a.md"]))
        self.assertEqual([f.path for f in result.failed], ["a.md"])
        self.assertEqual(self.read("a.md"), "\n\n---\ntitle: x\n")

    def test_bom_document_is_not_written(self):
        self.write("a.md", "﻿---\ntitle: x\n---\n# T\n")
        result = dlid_writer.apply_plan(self.root, self.plan(["a.md"]))
        self.assertEqual([f.path for f in result.failed], ["a.md"])
        self.assertEqual(self.read("a.md"), "﻿---\ntitle: x\n---\n# T\n")

    def test_unconfirmed_plan_writes_nothing(self):
        text = f"---\ndoc_link_id: {ID_A}\n---\n# T\n"
        self.write("a.md", text)
        self.write("b.md", text)
        plan = self.plan(["a.md", "b.md"])
        self.assertFalse(plan.confirmed)
        before = self.snapshot()
        with self.assertRaises(dlid_writer.PlanNotConfirmed):
            dlid_writer.apply_plan(self.root, plan)
        self.assertEqual(self.snapshot(), before)

    def test_stale_plan_is_refused(self):
        self.write("a.md", "# T\n")
        plan = self.plan(["a.md"])
        self.write("a.md", "new line\n\n# T\n")
        result = dlid_writer.apply_plan(self.root, plan)
        self.assertEqual([f.path for f in result.failed], ["a.md"])
        self.assertEqual(self.read("a.md"), "new line\n\n# T\n")

    def test_stale_frontmatter_is_refused(self):
        self.write("a.md", "# T\n")
        plan = self.plan(["a.md"])
        self.write("a.md", f"---\ndoc_link_id: {ID_A}\n---\n# T\n")
        result = dlid_writer.apply_plan(self.root, plan)
        self.assertEqual([f.path for f in result.failed], ["a.md"])
        self.assertEqual(self.read("a.md"), f"---\ndoc_link_id: {ID_A}\n---\n# T\n")


class RevertTest(WriterTestBase):
    def tampering_writer(self, transform):
        def write(project_root, target, data):
            dlid_writer._atomic_write(project_root, target, transform(data))

        return write

    def test_non_dlid_difference_reverts_the_document(self):
        original = "# T\n\nbody\n"
        self.write("a.md", original)
        result = dlid_writer.apply_plan(
            self.root,
            self.plan(["a.md"]),
            write=self.tampering_writer(lambda d: d.replace(b"body", b"BODY")),
        )
        self.assertEqual([f.path for f in result.failed], ["a.md"])
        self.assertTrue(result.failed[0].reverted)
        self.assertEqual(result.written, ())
        self.assertEqual(self.read("a.md"), original)
        self.assertEqual(self.temp_files(), [])

    def test_link_title_change_reverts(self):
        original = f'# T\n\n[r]: other.md "{ID_C}"\n'
        self.write("a.md", original)
        result = dlid_writer.apply_plan(
            self.root,
            self.plan(["a.md"]),
            write=self.tampering_writer(lambda d: d.replace(ID_C.encode(), b"x")),
        )
        self.assertTrue(result.failed[0].reverted)
        self.assertEqual(self.read("a.md"), original)

    def test_dlid_in_wrong_place_reverts(self):
        original = "# Title\n"
        self.write("a.md", original)
        result = dlid_writer.apply_plan(
            self.root,
            self.plan(["a.md"]),
            write=self.tampering_writer(
                lambda d: d.replace(f"Title {D2}".encode(), f"{D2} Title".encode())
            ),
        )
        self.assertTrue(result.failed[0].reverted)
        self.assertEqual(self.read("a.md"), original)

    def test_extra_line_reverts(self):
        original = "# T\n"
        self.write("a.md", original)
        result = dlid_writer.apply_plan(
            self.root,
            self.plan(["a.md"]),
            write=self.tampering_writer(lambda d: d + b"extra\n"),
        )
        self.assertTrue(result.failed[0].reverted)
        self.assertEqual(self.read("a.md"), original)

    def test_revert_of_one_document_keeps_the_others(self):
        self.write("a.md", "# A\n")
        self.write("b.md", "# B\n")

        def write(project_root, target, data):
            if target.name == "a.md":
                data = data + b"extra\n"
            dlid_writer._atomic_write(project_root, target, data)

        result = dlid_writer.apply_plan(
            self.root, self.plan(["a.md", "b.md"]), write=write
        )
        self.assertEqual([f.path for f in result.failed], ["a.md"])
        self.assertEqual(self.read("a.md"), "# A\n")
        self.assertIn(D3, self.read("b.md"))
        self.assertEqual({i.path for i in result.written}, {"b.md"})

    def test_failed_revert_is_reported_as_not_reverted(self):
        original = "# T\n"
        self.write("a.md", original)
        real = dlid_writer._atomic_write

        def write(project_root, target, data):
            real(project_root, target, data + b"extra\n")

        def broken(project_root, target, data):
            raise OSError("disk gone")

        dlid_writer._atomic_write = broken
        try:
            result = dlid_writer.apply_plan(self.root, self.plan(["a.md"]), write=write)
        finally:
            dlid_writer._atomic_write = real
        self.assertFalse(result.failed[0].reverted)
        self.assertIn("取り消しにも失敗", result.failed[0].cause)


class PartialFailureTest(WriterTestBase):
    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0, "root は読み取り専用を迂回する"
    )
    def test_read_only_document_fails_and_others_are_kept(self):
        self.write("a.md", "# A\n")
        self.write("b.md", "# B\n")
        (self.root / "a.md").chmod(0o444)
        result = dlid_writer.apply_plan(self.root, self.plan(["a.md", "b.md"]))
        self.assertFalse(result.succeeded)
        self.assertEqual([f.path for f in result.failed], ["a.md"])
        self.assertEqual(self.read("a.md"), "# A\n")
        self.assertEqual(self.read("b.md"), f"---\ndoc_link_id: {D3}\n---\n# B {D4}\n")
        self.assertEqual({i.path for i in result.written}, {"b.md"})

    def test_os_error_on_one_document_is_reported_per_document(self):
        self.write("a.md", "# A\n")
        self.write("b.md", "# B\n")

        def write(project_root, target, data):
            if target.name == "a.md":
                raise OSError("no space")
            dlid_writer._atomic_write(project_root, target, data)

        result = dlid_writer.apply_plan(
            self.root, self.plan(["a.md", "b.md"]), write=write
        )
        self.assertFalse(result.succeeded)
        failure = result.failed[0]
        self.assertEqual((failure.path, failure.location), ("a.md", "文書全体"))
        self.assertIn("no space", failure.cause)
        self.assertFalse(failure.reverted)
        self.assertEqual(self.read("a.md"), "# A\n")
        # 成功した文書の[DLID]は戻らず、発行済みとして報告される
        self.assertEqual(
            [(i.path, i.kind) for i in result.written],
            [("b.md", KIND_DOCUMENT), ("b.md", KIND_SECTION)],
        )
        self.assertEqual(self.read("b.md"), f"---\ndoc_link_id: {D3}\n---\n# B {D4}\n")

    def test_unreadable_target_is_reported(self):
        self.write("a.md", "# A\n")
        plan = self.plan(["a.md"])
        (self.root / "a.md").unlink()
        result = dlid_writer.apply_plan(self.root, plan)
        self.assertEqual([f.path for f in result.failed], ["a.md"])


class IdempotenceAndFilesTest(WriterTestBase):
    def test_second_run_makes_no_difference(self):
        self.write("a.md", "---\ntitle: x\n---\n# T\n\nSub\n---\n")
        first = dlid_writer.apply_plan(self.root, self.plan(["a.md"]))
        self.assertTrue(first.succeeded)
        after_first = self.snapshot()
        plan = self.plan(["a.md"])
        self.assertEqual(plan.items, ())
        second = dlid_writer.apply_plan(self.root, plan)
        self.assertTrue(second.succeeded)
        self.assertEqual(second.written, ())
        self.assertEqual(self.snapshot(), after_first)

    def test_permissions_are_kept(self):
        self.write("a.md", "# T\n")
        (self.root / "a.md").chmod(0o640)
        dlid_writer.apply_plan(self.root, self.plan(["a.md"]))
        self.assertEqual(stat.S_IMODE((self.root / "a.md").stat().st_mode), 0o640)

    def test_temp_files_are_not_left(self):
        self.write("a.md", "# T\n")
        dlid_writer.apply_plan(self.root, self.plan(["a.md"]))
        self.assertEqual(self.temp_files(), [])
        self.assertTrue((self.root / ".temp" / "doc-link" / "embed-dlid").is_dir())

    def test_symlink_is_kept_and_target_is_written(self):
        real = self.root / "real" / "t.md"
        real.parent.mkdir()
        real.write_text("# T\n", encoding="utf-8")
        link = self.root / "link.md"
        link.symlink_to(real)
        result = dlid_writer.apply_plan(self.root, self.plan(["link.md"]))
        self.assertTrue(result.succeeded)
        self.assertTrue(link.is_symlink())
        self.assertEqual(
            real.read_text(encoding="utf-8"),
            f"---\ndoc_link_id: {D1}\n---\n# T {D2}\n",
        )

    def test_failed_write_does_not_leave_temp_files(self):
        self.write("a.md", "# T\n")

        def write(project_root, target, data):
            raise OSError("boom")

        dlid_writer.apply_plan(self.root, self.plan(["a.md"]), write=write)
        self.assertEqual(self.temp_files(), [])


class ReissueTest(WriterTestBase):
    DOC = (
        f"---\ndoc_link_id: {ID_A}\n---\n"
        f"# T {ID_B}\n\n"
        f"Sub {ID_D}\n---\n\n"
        '[inline](other.md "title") <https://example.com>\n'
        f'[r]: other.md "{"a" * 64} {ID_C}"\n'
    )

    def test_copy_is_reissued_and_original_is_unchanged(self):
        self.write("orig.md", self.DOC)
        self.write("copy.md", self.DOC)
        files = ["orig.md", "copy.md"]
        unresolved = self.plan(files)
        self.assertFalse(unresolved.confirmed)
        origins = {
            report.dlid: next(loc for loc in report.locations if loc.path == "orig.md")
            for report in unresolved.duplicates
        }
        plan = self.plan(files, origins=origins)
        self.assertTrue(plan.confirmed)

        result = dlid_writer.apply_plan(self.root, plan)
        self.assertTrue(result.succeeded, result.failed)
        self.assertEqual(self.read("orig.md"), self.DOC)
        expected = self.DOC.replace(ID_A, D1).replace(ID_B, D2).replace(ID_D, D3)
        self.assertEqual(self.read("copy.md"), expected)
        self.assertEqual(
            [(i.kind, i.replaced, i.dlid) for i in result.written],
            [
                (KIND_DOCUMENT, ID_A, D1),
                (KIND_SECTION, ID_B, D2),
                (KIND_SECTION, ID_D, D3),
            ],
        )

    def test_rerun_after_reissue_finds_no_duplicates(self):
        self.write("orig.md", self.DOC)
        self.write("copy.md", self.DOC)
        files = ["orig.md", "copy.md"]
        first = self.plan(files)
        origins = {
            report.dlid: next(loc for loc in report.locations if loc.path == "orig.md")
            for report in first.duplicates
        }
        dlid_writer.apply_plan(self.root, self.plan(files, origins=origins))
        again = self.plan(files)
        self.assertEqual(again.duplicates, ())
        self.assertEqual(again.items, ())


class RerunReconcilesWrittenIdsTest(WriterTestBase):
    """E-07: 失敗した実行の再実行は、書き込み済みの[DLID]を既存の[DLID]として照合し直す。"""

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0, "root は読み取り専用を迂回する"
    )
    def test_written_ids_are_not_reissued_or_reported_as_duplicates(self):
        self.write("a.md", "# A\n")
        self.write("b.md", "# B\n")
        (self.root / "a.md").chmod(0o444)
        first = dlid_writer.apply_plan(self.root, self.plan(["a.md", "b.md"]))
        self.assertFalse(first.succeeded)
        written_b = self.read("b.md")

        (self.root / "a.md").chmod(0o644)
        plan = self.plan(["a.md", "b.md"])
        self.assertEqual(plan.duplicates, ())
        self.assertEqual({item.path for item in plan.items}, {"a.md"})
        second = dlid_writer.apply_plan(self.root, plan)
        self.assertTrue(second.succeeded)
        self.assertEqual(self.read("b.md"), written_b)
        self.assertTrue(self.read("a.md").startswith("---\ndoc_link_id: DLID-"))


class VerifyWrittenTest(unittest.TestCase):
    def test_accepts_only_the_planned_difference(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.md").write_text("# T\n", encoding="utf-8")
            plan = embed_plan.build_plan(tmp, ["a.md"], issue=fixed_issuer())
        after = f"---\ndoc_link_id: {D1}\n---\n# T {D2}\n"
        self.assertEqual(
            dlid_writer.verify_written("# T\n", after, list(plan.items)), []
        )

    def test_rejects_text_change_in_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.md").write_text("# T\n", encoding="utf-8")
            plan = embed_plan.build_plan(tmp, ["a.md"], issue=fixed_issuer())
        after = f"---\ndoc_link_id: {D1}\n---\n# U {D2}\n"
        self.assertNotEqual(
            dlid_writer.verify_written("# T\n", after, list(plan.items)), []
        )

    def test_rejects_changed_frontmatter_key(self):
        before = "---\ntitle: x\n---\n# T\n"
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.md").write_text(before, encoding="utf-8")
            plan = embed_plan.build_plan(tmp, ["a.md"], issue=fixed_issuer())
        after = f"---\ntitle: y\ndoc_link_id: {D1}\n---\n# T {D2}\n"
        self.assertNotEqual(
            dlid_writer.verify_written(before, after, list(plan.items)), []
        )

    def test_rejects_removed_heading(self):
        before = "# T\n\n## U\n"
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.md").write_text(before, encoding="utf-8")
            plan = embed_plan.build_plan(tmp, ["a.md"], issue=fixed_issuer())
        after = f"---\ndoc_link_id: {D1}\n---\n# T {D2}\n"
        self.assertNotEqual(
            dlid_writer.verify_written(before, after, list(plan.items)), []
        )


if __name__ == "__main__":
    unittest.main()
