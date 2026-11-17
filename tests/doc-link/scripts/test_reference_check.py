import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import reference_check as rc  # noqa: E402
from references import extract_references  # noqa: E402

ID_SRC = "DLID-0123456789ab"
ID_DOC = "DLID-abcdefghjkmn"
ID_SEC = "DLID-pqrstvwxyz01"
ID_OTHER = "DLID-23456789abcd"
WHEN = "2026-11-13T00:00:00+00:00"


def target_doc(doc_id=ID_DOC, sec_id=ID_SEC, heading="概要"):
    return f"---\ndoc_link_id: {doc_id}\n---\n\n# 題\n\n## {heading} {sec_id}\n\n本文\n"


def source_doc(dest, title_id=ID_DOC, fragment=""):
    return (
        f"# 参照元 {ID_SRC}\n\n[x][r]\n\n"
        f'[r]: {dest}{fragment} "{"a" * 64} {title_id}"\n'
    )


class CheckBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def check(self, source="docs/src.md"):
        results = rc.check_document(self.root, source, checked_at=WHEN)
        self.assertEqual(len(results), 1)
        return results[0]


class StatusTest(CheckBase):
    def test_match_document(self):
        self.write("docs/b.md", target_doc())
        self.write("docs/src.md", source_doc("b.md"))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_MATCH)
        self.assertEqual(result.target_kind, rc.KIND_DOCUMENT)
        self.assertEqual(result.current_path, "docs/b.md")
        self.assertEqual(result.directory, "docs")
        self.assertEqual(result.checked_at, WHEN)
        self.assertEqual(result.reference.recorded_hash, "a" * 64)

    def test_match_section_compares_owner_document_path(self):
        self.write("docs/b.md", target_doc())
        self.write("docs/src.md", source_doc("b.md", ID_SEC))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_MATCH)
        self.assertEqual(result.target_kind, rc.KIND_SECTION)

    def test_section_path_mismatch_reports_owner_document(self):
        self.write("docs/other/b.md", target_doc())
        self.write("docs/src.md", source_doc("old.md", ID_SEC))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_PATH_MISMATCH)
        self.assertEqual(result.target_kind, rc.KIND_SECTION)
        self.assertEqual(result.current_path, "docs/other/b.md")

    def test_path_mismatch_in_subdirectory_of_designated_dir(self):
        self.write("docs/sub/deep/b.md", target_doc())
        self.write("docs/src.md", source_doc("old.md"))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_PATH_MISMATCH)
        self.assertEqual(result.current_path, "docs/sub/deep/b.md")

    def test_path_mismatch_renamed_in_same_directory(self):
        self.write("docs/renamed.md", target_doc())
        self.write("docs/src.md", source_doc("b.md"))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_PATH_MISMATCH)
        self.assertEqual(result.current_path, "docs/renamed.md")

    def test_absent_when_id_is_not_in_directory(self):
        self.write("docs/b.md", target_doc(doc_id=ID_OTHER, sec_id=ID_OTHER))
        self.write("docs/src.md", source_doc("b.md"))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_ABSENT)
        self.assertEqual(result.absent_reason, rc.ABSENT_NOT_FOUND)
        self.assertIsNone(result.current_path)

    def test_moved_outside_designated_directory_is_not_guessed(self):
        self.write("elsewhere/b.md", target_doc())
        self.write("docs/a/src.md", source_doc("b.md"))
        self.write("docs/a/keep.md", "# keep\n")
        result = self.check("docs/a/src.md")
        self.assertEqual(result.status, rc.STATUS_ABSENT)
        self.assertEqual(result.directory, "docs/a")
        self.assertIsNone(result.current_path)

    def test_directory_missing(self):
        self.write("docs/src.md", source_doc("nothing/b.md"))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_ABSENT)
        self.assertEqual(result.absent_reason, rc.ABSENT_DIRECTORY_MISSING)
        self.assertEqual(result.directory, "docs/nothing")

    def test_directory_is_a_file(self):
        self.write("docs/file", "x")
        self.write("docs/src.md", source_doc("file/b.md"))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_ABSENT)
        self.assertEqual(result.absent_reason, rc.ABSENT_NOT_DIRECTORY)

    def test_directory_unreadable(self):
        self.write("docs/locked/b.md", target_doc())
        self.write("docs/src.md", source_doc("locked/b.md"))
        locked = self.root / "docs" / "locked"
        locked.chmod(0)
        self.addCleanup(lambda: locked.chmod(stat.S_IRWXU))
        try:
            os.listdir(locked)
        except OSError:
            pass
        else:
            self.skipTest(
                "権限を落としても読めない環境（root など）なので確かめられない"
            )
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_ABSENT)
        self.assertEqual(result.absent_reason, rc.ABSENT_DIRECTORY_UNREADABLE)

    def test_fixed_excluded_directory_is_absent(self):
        self.write("docs/build/b.md", target_doc())
        self.write("docs/src.md", source_doc("build/b.md"))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_ABSENT)
        self.assertEqual(result.absent_reason, rc.ABSENT_DIRECTORY_EXCLUDED)

    def test_duplicate_does_not_guess_current_path(self):
        self.write("docs/b.md", target_doc())
        self.write("docs/copy/b.md", target_doc())
        self.write("docs/src.md", source_doc("b.md"))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_DUPLICATE)
        self.assertIsNone(result.current_path)
        self.assertEqual(result.duplicate_paths, ("docs/b.md", "docs/copy/b.md"))

    def test_duplicate_section_in_same_document(self):
        self.write(
            "docs/b.md",
            f"---\ndoc_link_id: {ID_DOC}\n---\n# a {ID_SEC}\n\n# b {ID_SEC}\n",
        )
        self.write("docs/src.md", source_doc("b.md", ID_SEC))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_DUPLICATE)
        self.assertEqual(result.duplicate_paths, ("docs/b.md",))

    def test_unreadable_candidate_is_reported_as_evidence(self):
        self.write("docs/b.md", target_doc())
        (self.root / "docs" / "bad.md").write_bytes(b"\xff\xfe\x00bad")
        self.write("docs/src.md", source_doc("b.md"))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_MATCH)
        self.assertEqual(result.unreadable_files, ("docs/bad.md",))
        self.assertEqual(result.scanned_file_count, 2)

    def test_self_reference(self):
        text = f'---\ndoc_link_id: {ID_DOC}\n---\n# T\n\n[x][r]\n\n[r]: #t "{ID_DOC}"\n'
        self.write("docs/src.md", text)
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_MATCH)
        self.assertEqual(result.current_path, "docs/src.md")


class UnresolvedTest(CheckBase):
    def test_outside_project_root(self):
        self.write("docs/src.md", source_doc("../../outside/b.md"))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_UNRESOLVED)
        self.assertEqual(result.unresolved_reason, rc.UNRESOLVED_OUTSIDE_ROOT)

    def test_absolute_path(self):
        self.write("docs/src.md", source_doc("/abs/b.md"))
        result = self.check()
        self.assertEqual(result.unresolved_reason, rc.UNRESOLVED_OUTSIDE_ROOT)

    def test_not_markdown(self):
        self.write("docs/src.md", source_doc("b.txt"))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_UNRESOLVED)
        self.assertEqual(result.unresolved_reason, rc.UNRESOLVED_NOT_MARKDOWN)

    def test_dotdot_inside_root_resolves(self):
        self.write("a/b.md", target_doc())
        self.write("docs/src.md", source_doc("../a/b.md"))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_MATCH)
        self.assertEqual(result.current_path, "a/b.md")

    def test_unreadable_source_raises(self):
        with self.assertRaises(rc.ReferenceCheckError):
            rc.check_document(self.root, "docs/none.md", checked_at=WHEN)


class FragmentTest(CheckBase):
    def setUp(self):
        super().setUp()
        self.write(
            "docs/b.md",
            f"---\ndoc_link_id: {ID_DOC}\n---\n# 題\n\n"
            f'<a id="explicit"></a>\n\n<a name="legacy"></a>\n\n'
            f'## 概要 {ID_SEC}\n\n## 別節\n\n```\n<a id="incode"></a>\n```\n',
        )

    def check_fragment(self, title_id, fragment):
        self.write("docs/src.md", source_doc("b.md", title_id, f"#{fragment}"))
        return self.check()

    def test_document_fragment_resolves_to_heading_anchor(self):
        result = self.check_fragment(ID_DOC, f"概要-{ID_SEC.lower()}")
        self.assertEqual(result.status, rc.STATUS_MATCH)

    def test_document_fragment_resolves_to_explicit_anchors(self):
        for fragment in ("explicit", "legacy", "別節"):
            with self.subTest(fragment=fragment):
                self.assertEqual(
                    self.check_fragment(ID_DOC, fragment).status, rc.STATUS_MATCH
                )

    def test_document_fragment_mismatch_has_no_current_anchor(self):
        for fragment in ("nothing", "incode"):
            with self.subTest(fragment=fragment):
                result = self.check_fragment(ID_DOC, fragment)
                self.assertEqual(result.status, rc.STATUS_FRAGMENT_MISMATCH)
                self.assertIsNone(result.current_anchor)
                self.assertEqual(result.current_path, "docs/b.md")

    def test_section_fragment_matches_its_heading_anchor(self):
        anchor = f"概要-{ID_SEC.lower()}"
        result = self.check_fragment(ID_SEC, anchor)
        self.assertEqual(result.status, rc.STATUS_MATCH)

    def test_section_fragment_after_rename_returns_current_anchor(self):
        # 見出しを改名した後の古いフラグメント
        result = self.check_fragment(ID_SEC, "旧見出し")
        self.assertEqual(result.status, rc.STATUS_FRAGMENT_MISMATCH)
        self.assertEqual(result.current_anchor, f"概要-{ID_SEC.lower()}")

    def test_section_fragment_resolving_to_other_heading_is_mismatch(self):
        for fragment in ("別節", "explicit"):
            with self.subTest(fragment=fragment):
                result = self.check_fragment(ID_SEC, fragment)
                self.assertEqual(result.status, rc.STATUS_FRAGMENT_MISMATCH)
                self.assertEqual(result.current_anchor, f"概要-{ID_SEC.lower()}")

    def test_no_fragment_skips_fragment_check(self):
        self.write("docs/src.md", source_doc("b.md", ID_SEC))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_MATCH)
        self.assertIsNone(result.current_anchor)

    def test_empty_fragment_is_treated_as_none(self):
        result = self.check_fragment(ID_SEC, "")
        self.assertEqual(result.status, rc.STATUS_MATCH)

    def test_path_mismatch_is_not_checked_for_fragment(self):
        self.write("docs/src.md", source_doc("old.md", ID_DOC, "#nothing"))
        result = self.check()
        self.assertEqual(result.status, rc.STATUS_PATH_MISMATCH)


class ScopeAndReadOnlyTest(CheckBase):
    def test_result_has_scope_and_time(self):
        self.write("docs/b.md", target_doc())
        self.write("docs/src.md", source_doc("b.md"))
        data = self.check().to_dict()
        self.assertEqual(data["scope"], {"directory": "docs", "checked_at": WHEN})
        self.assertEqual(data["evidence"]["scanned_file_count"], 2)
        self.assertEqual(data["status"], rc.STATUS_MATCH)

    def test_default_checked_at_is_given(self):
        self.write("docs/b.md", target_doc())
        self.write("docs/src.md", source_doc("b.md"))
        result = rc.check_document(self.root, "docs/src.md")[0]
        self.assertTrue(result.checked_at)

    def test_check_reference_with_extracted_reference(self):
        self.write("docs/b.md", target_doc())
        text = source_doc("b.md")
        self.write("docs/src.md", text)
        (reference,) = extract_references(text)
        result = rc.check_reference(
            self.root, "docs/src.md", reference, checked_at=WHEN
        )
        self.assertEqual(result.status, rc.STATUS_MATCH)

    def test_does_not_write_anything(self):
        self.write("docs/b.md", target_doc())
        self.write("docs/old/b.md", target_doc())
        self.write("docs/src.md", source_doc("b.md", ID_SEC, "#x"))
        self.write("docs/src2.md", source_doc("nothing/b.md"))
        self.write(".doc-link/state.json", '{"x": 1}\n')
        before = self.snapshot()
        rc.check_document(self.root, "docs/src.md", checked_at=WHEN)
        rc.check_document(self.root, "docs/src2.md", checked_at=WHEN)
        self.assertEqual(self.snapshot(), before)

    def snapshot(self):
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        } | {
            str(path.relative_to(self.root)): None
            for path in sorted(self.root.rglob("*"))
            if path.is_dir()
        }


if __name__ == "__main__":
    unittest.main()
