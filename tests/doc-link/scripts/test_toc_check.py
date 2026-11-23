import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import change_set  # noqa: E402
import state_store  # noqa: E402
import toc_candidate  # noqa: E402
import toc_check  # noqa: E402
from content_hash import RECORD_LENGTH, document_content_hash  # noqa: E402
from reference_check import check_document  # noqa: E402
from target_spec import MODE_ALL, MODE_TARGETS, TargetSpec  # noqa: E402

KEY = "main"
ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
ID_C = "DLID-pqrstvwxyz01"
S1 = "DLID-00000000s001"
S2 = "DLID-00000000s002"
S3 = "DLID-00000000s003"
RECORD = "c" * RECORD_LENGTH
RECORD2 = "d" * RECORD_LENGTH
WHEN = "2026-11-13T00:00:00+00:00"
FILES = ["docs/a.md", "docs/b.md"]
SPEC = TargetSpec(mode=MODE_TARGETS, key=KEY, paths=tuple(FILES))


def a_text(record=RECORD, body="body", target=ID_B):
    title = f' "{record} {target}"' if record else f' "{target}"'
    return f"""---
doc_link_id: {ID_A}
---
# A {S1}

{body}

[to b][b]

## Sub {S2}

[b]: b.md{title}
"""


B_TEXT = f"""---
doc_link_id: {ID_B}
---
# B {S3}

text
"""

C_TEXT = f"""---
doc_link_id: {ID_C}
---
# C DLID-00000000s004
"""


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.write("docs/a.md", a_text())
        self.write("docs/b.md", B_TEXT)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def save_info(self, path, doc_id):
        text = (self.root / path).read_text(encoding="utf-8")
        state_store.save_document_info(
            self.root,
            "test",
            {
                "doc_link_id": doc_id,
                "path": path,
                "title": "t",
                "purpose": "p",
                "summary": [],
                "tasks": [],
                "keywords": [],
                "content_hash": document_content_hash(text),
            },
        )

    def build(self, files=FILES, spec=SPEC, key=KEY):
        """現物から[文書情報]と[確定 ToC]を保存する（index-docs が確定した状態を作る）。"""
        for path in files:
            text = (self.root / path).read_text(encoding="utf-8")
            doc_id = next(
                line.split(":", 1)[1].strip()
                for line in text.splitlines()
                if line.startswith("doc_link_id:")
            )
            self.save_info(path, doc_id)
        cs = change_set.build_change_set(self.root, key, files)
        results = {
            item.doc_link_id: check_document(self.root, item.path, checked_at=WHEN)
            for item in cs.confirmed_documents
        }
        toc_candidate.build_and_publish(self.root, "test", key, spec, cs, results, WHEN)

    def snapshot(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }

    def kinds(self, result):
        return {d.doc_link_id: set(d.kinds) for d in result.documents}


class StatusTest(Base):
    def test_not_built_when_there_is_no_confirmed_toc(self):
        result = toc_check.check_toc(self.root, KEY)
        self.assertEqual(result.status, toc_check.STATUS_NOT_BUILT)
        self.assertIsNone(result.scale)

    def test_up_to_date_with_the_saved_spec(self):
        self.build()
        result = toc_check.check_toc(self.root, KEY)
        self.assertEqual(result.status, toc_check.STATUS_UP_TO_DATE)
        self.assertEqual(result.spec_source, toc_check.SPEC_SOURCE_SAVED)
        self.assertEqual(result.documents, ())
        self.assertEqual(result.sections, ())
        self.assertIsNone(result.scale)

    def test_default_key_is_all(self):
        self.build(spec=TargetSpec(mode=MODE_ALL), key="all")
        result = toc_check.check_toc(self.root)
        self.assertEqual(result.toc_key, "all")
        self.assertEqual(result.status, toc_check.STATUS_UP_TO_DATE)

    def test_rebuild_needed_carries_the_scale(self):
        self.build()
        self.write("docs/a.md", a_text(body="changed"))
        result = toc_check.check_toc(self.root, KEY)
        self.assertEqual(result.status, toc_check.STATUS_REBUILD_NEEDED)
        self.assertEqual(self.kinds(result), {ID_A: {change_set.CHANGE_CONTENT}})
        self.assertEqual(
            result.scale.to_dict(),
            {
                "new": 0,
                "departed": 0,
                "path_changed": 0,
                "content_changed": 1,
                "missing_id": 0,
                "duplicate_id": 0,
                "ai_generation": 1,
            },
        )
        change = result.documents[0]
        self.assertNotEqual(change.old_hash, change.new_hash)

    def test_key_and_spec_must_correspond(self):
        with self.assertRaises(ValueError):
            toc_check.check_toc(self.root, "other", SPEC)
        with self.assertRaises(ValueError):
            toc_check.check_toc(self.root, KEY, TargetSpec(mode=MODE_ALL))


class ChangeListTest(Base):
    def setUp(self):
        super().setUp()
        self.build()

    def check(self, spec=None):
        return toc_check.check_toc(self.root, KEY, spec)

    def test_new_document(self):
        self.write("docs/c.md", C_TEXT)
        spec = TargetSpec(mode=MODE_TARGETS, key=KEY, paths=(*FILES, "docs/c.md"))
        result = self.check(spec)
        self.assertEqual(result.status, toc_check.STATUS_REBUILD_NEEDED)
        self.assertEqual(self.kinds(result), {ID_C: {change_set.CHANGE_NEW}})
        self.assertEqual(result.scale.new, 1)
        self.assertEqual(result.scale.ai_generation, 1)

    def test_new_document_with_verified_info_is_not_counted_for_ai(self):
        self.write("docs/c.md", C_TEXT)
        self.save_info("docs/c.md", ID_C)
        spec = TargetSpec(mode=MODE_TARGETS, key=KEY, paths=(*FILES, "docs/c.md"))
        result = self.check(spec)
        self.assertEqual(result.scale.new, 1)
        self.assertEqual(result.scale.ai_generation, 0)

    def test_departed_document_by_spec_and_by_removal(self):
        spec = TargetSpec(mode=MODE_TARGETS, key=KEY, paths=("docs/a.md",))
        result = self.check(spec)
        self.assertEqual(self.kinds(result), {ID_B: {change_set.CHANGE_DEPARTED}})
        (self.root / "docs/b.md").unlink()
        result = self.check()
        self.assertEqual(result.status, toc_check.STATUS_REBUILD_NEEDED)
        self.assertEqual(self.kinds(result), {ID_B: {change_set.CHANGE_DEPARTED}})
        self.assertEqual(result.scale.departed, 1)
        self.assertEqual([p["reason"] for p in result.problems], ["missing"])

    def test_moved_document(self):
        (self.root / "docs/b.md").rename(self.root / "docs/moved.md")
        spec = TargetSpec(
            mode=MODE_TARGETS, key=KEY, paths=("docs/a.md", "docs/moved.md")
        )
        result = self.check(spec)
        self.assertEqual(self.kinds(result), {ID_B: {change_set.CHANGE_PATH}})
        self.assertEqual(result.scale.path_changed, 1)
        self.assertEqual(result.scale.ai_generation, 0)
        self.assertEqual(result.documents[0].old_path, "docs/b.md")
        self.assertEqual(result.documents[0].new_path, "docs/moved.md")

    def test_content_change_lists_the_section_change(self):
        self.write("docs/b.md", B_TEXT + "\nmore\n")
        result = self.check()
        self.assertEqual(self.kinds(result), {ID_B: {change_set.CHANGE_CONTENT}})
        self.assertEqual(
            [(s.section_id, s.kinds) for s in result.sections],
            [(S3, (change_set.SECTION_BODY,))],
        )
        self.assertEqual(result.counts["sections"], 1)

    def test_reference_difference(self):
        self.write("docs/a.md", a_text(target=ID_C))
        result = self.check()
        self.assertIn(change_set.CHANGE_REFERENCES, self.kinds(result)[ID_A])
        self.assertEqual(result.counts["references_changed"], 1)
        self.assertEqual(result.status, toc_check.STATUS_REBUILD_NEEDED)

    def test_rewriting_only_the_recorded_word_is_not_stale(self):
        for text in (a_text(record=RECORD2), a_text(record=None), a_text()):
            with self.subTest(text=text[-80:]):
                self.write("docs/a.md", text)
                result = self.check()
                self.assertEqual(result.status, toc_check.STATUS_UP_TO_DATE)
                self.assertEqual(result.documents, ())

    def test_adding_a_record_word_for_the_first_time_is_not_stale(self):
        self.write("docs/a.md", a_text(record=None))
        self.build()  # 記録語の無い版を[確定 ToC]にする
        self.write("docs/a.md", a_text(record=RECORD))
        result = self.check()
        self.assertEqual(result.status, toc_check.STATUS_UP_TO_DATE)

    def test_same_judgement_as_the_change_set(self):
        self.write("docs/a.md", a_text(body="changed", target=ID_C))
        (self.root / "docs/b.md").rename(self.root / "docs/moved.md")
        self.write("docs/c.md", C_TEXT)
        spec = TargetSpec(
            mode=MODE_TARGETS,
            key=KEY,
            paths=("docs/a.md", "docs/moved.md", "docs/c.md"),
        )
        result = self.check(spec)
        expected = change_set.build_change_set(
            self.root, KEY, ["docs/a.md", "docs/c.md", "docs/moved.md"]
        )
        self.assertEqual(
            [d.to_dict() for d in result.documents],
            [d.to_dict() for d in expected.documents if not d.unchanged],
        )
        self.assertEqual(
            [s.to_dict() for s in result.sections],
            [s.to_dict() for s in expected.sections],
        )

    def test_given_spec_takes_priority_over_the_saved_one(self):
        self.write("docs/c.md", C_TEXT)
        spec = TargetSpec(mode=MODE_TARGETS, key=KEY, paths=(*FILES, "docs/c.md"))
        given = self.check(spec)
        saved = self.check()
        self.assertEqual(given.spec_source, toc_check.SPEC_SOURCE_GIVEN)
        self.assertEqual(given.status, toc_check.STATUS_REBUILD_NEEDED)
        self.assertEqual(saved.spec_source, toc_check.SPEC_SOURCE_SAVED)
        self.assertEqual(saved.status, toc_check.STATUS_UP_TO_DATE)
        self.assertEqual(saved.target_spec, SPEC.to_dict())


class ExcludedTest(Base):
    def test_duplicate_of_a_confirmed_document_is_not_overlooked(self):
        self.build()
        self.write("docs/copy.md", a_text())
        spec = TargetSpec(mode=MODE_TARGETS, key=KEY, paths=(*FILES, "docs/copy.md"))
        result = toc_check.check_toc(self.root, KEY, spec)
        self.assertEqual(result.status, toc_check.STATUS_REBUILD_NEEDED)
        self.assertEqual(result.documents, ())
        self.assertEqual(
            sorted(e.path for e in result.excluded_in_toc),
            ["docs/a.md", "docs/copy.md"],
        )
        self.assertEqual(result.scale.duplicate_id, 2)
        self.assertEqual(result.scale.departed, 0)

    def test_missing_id_outside_the_toc_does_not_make_it_stale(self):
        self.write("docs/noid.md", "# No id\n")
        spec = TargetSpec(mode=MODE_TARGETS, key=KEY, paths=(*FILES, "docs/noid.md"))
        self.build(spec=spec)
        result = toc_check.check_toc(self.root, KEY, spec)
        self.assertEqual(result.status, toc_check.STATUS_UP_TO_DATE)
        self.assertEqual([e.path for e in result.excluded], ["docs/noid.md"])
        self.assertEqual(result.counts["missing_id"], 1)

    def test_missing_id_is_counted_in_the_scale_when_rebuild_is_needed(self):
        self.build()
        self.write("docs/noid.md", "# No id\n")
        self.write("docs/a.md", a_text(body="changed"))
        spec = TargetSpec(mode=MODE_TARGETS, key=KEY, paths=(*FILES, "docs/noid.md"))
        result = toc_check.check_toc(self.root, KEY, spec)
        self.assertEqual(result.status, toc_check.STATUS_REBUILD_NEEDED)
        self.assertEqual(result.scale.missing_id, 1)


class TargetSpecChangeTest(Base):
    def test_same_spec_is_not_a_change(self):
        self.build()
        result = toc_check.check_toc(self.root, KEY, SPEC)
        self.assertEqual(result.status, toc_check.STATUS_UP_TO_DATE)
        self.assertFalse(result.target_spec_changed)
        self.assertIsNone(result.saved_target_spec)

    def test_saved_spec_is_not_compared_with_itself(self):
        self.build()
        result = toc_check.check_toc(self.root, KEY)
        self.assertEqual(result.status, toc_check.STATUS_UP_TO_DATE)
        self.assertFalse(result.target_spec_changed)

    def test_different_spec_with_the_same_documents_needs_a_rebuild(self):
        self.build()
        self.write("docs/empty/.keep", "")
        spec = TargetSpec(
            mode=MODE_TARGETS, key=KEY, paths=tuple(FILES), dirs=("docs/empty",)
        )
        result = toc_check.check_toc(self.root, KEY, spec)
        self.assertEqual(result.status, toc_check.STATUS_REBUILD_NEEDED)
        self.assertTrue(result.target_spec_changed)
        self.assertEqual(
            result.saved_target_spec,
            state_store.load_confirmed_toc(self.root, KEY)["target_spec"],
        )
        self.assertEqual(result.documents, ())
        self.assertEqual(result.scale.ai_generation, 0)
        self.assertEqual(result.to_summary()["target_spec_changed"], True)

    def test_summary_holds_counts_and_detail_holds_every_item(self):
        """D-061: 要約は件数までで、文書・セクション・除外した文書の全件は明細が持つ。"""
        self.build()
        self.write("docs/a.md", a_text(body="changed"))
        result = toc_check.check_toc(self.root, KEY, SPEC)
        self.assertEqual(result.status, toc_check.STATUS_REBUILD_NEEDED)
        summary, detail = result.to_summary(), result.to_detail()
        for name in ("documents", "sections", "excluded", "excluded_in_toc"):
            self.assertNotIn(name, summary)
            self.assertIn(name, detail)
        self.assertEqual(
            set(summary),
            {
                "status",
                "toc_key",
                "version",
                "target_spec_source",
                "target_spec",
                "target_spec_changed",
                "saved_target_spec",
                "counts",
                "scale",
                "causes",
                "problems",
                "warnings",
            },
        )
        self.assertEqual(
            [d["doc_link_id"] for d in detail["documents"]],
            [d.doc_link_id for d in result.documents],
        )
        self.assertEqual(summary["counts"]["content_changed"], len(detail["documents"]))
        self.assertEqual(summary["counts"]["excluded_in_toc"], 0)

    def test_a_rebuild_with_the_new_spec_ends_the_difference(self):
        self.build()
        self.write("docs/empty/.keep", "")
        spec = TargetSpec(
            mode=MODE_TARGETS, key=KEY, paths=tuple(FILES), dirs=("docs/empty",)
        )
        self.build(spec=spec)
        result = toc_check.check_toc(self.root, KEY, spec)
        self.assertEqual(result.status, toc_check.STATUS_UP_TO_DATE)
        self.assertFalse(result.target_spec_changed)


class DirectoryDisappearedTest(Base):
    def test_vanished_target_directory_is_departure_not_undeterminable(self):
        spec = TargetSpec(mode=MODE_TARGETS, key=KEY, dirs=("docs",))
        self.build(spec=spec)
        for path in (self.root / "docs").iterdir():
            path.unlink()
        (self.root / "docs").rmdir()
        result = toc_check.check_toc(self.root, KEY)
        self.assertEqual(result.status, toc_check.STATUS_REBUILD_NEEDED)
        self.assertEqual(
            self.kinds(result),
            {ID_A: {change_set.CHANGE_DEPARTED}, ID_B: {change_set.CHANGE_DEPARTED}},
        )
        self.assertEqual(result.scale.departed, 2)


class UndeterminableTest(Base):
    def assert_undeterminable(self, result, kind=None):
        self.assertEqual(result.status, toc_check.STATUS_UNDETERMINABLE)
        self.assertTrue(result.causes)
        self.assertIsNone(result.scale)
        if kind is not None:
            self.assertIn(kind, [c.kind for c in result.causes])

    def test_unparseable_saved_spec(self):
        self.build()
        path = state_store.confirmed_toc_path(self.root, KEY)
        toc = state_store.load_confirmed_toc(self.root, KEY)
        for spec in ({}, {"mode": "weird"}, {"mode": "targets", "paths": 5}):
            with self.subTest(spec=spec):
                toc["target_spec"] = spec
                state_store.save_confirmed_toc(self.root, "test", toc)
                result = toc_check.check_toc(self.root, KEY)
                self.assert_undeterminable(result)
        self.assertTrue(path.exists())

    def test_given_spec_is_used_and_an_unparseable_saved_one_needs_a_rebuild(self):
        self.build()
        toc = state_store.load_confirmed_toc(self.root, KEY)
        toc["target_spec"] = {}
        state_store.save_confirmed_toc(self.root, "test", toc)
        result = toc_check.check_toc(self.root, KEY, SPEC)
        # 渡された指定で走査でき（判定不能にしない）、解釈できない保存済みの指定は、違うものとして扱う
        self.assertEqual(result.status, toc_check.STATUS_REBUILD_NEEDED)
        self.assertTrue(result.target_spec_changed)
        self.assertEqual(result.documents, ())

    def test_corrupt_confirmed_toc(self):
        self.build()
        state_store.confirmed_toc_path(self.root, KEY).write_bytes(b"{broken")
        self.assert_undeterminable(
            toc_check.check_toc(self.root, KEY), state_store.KIND_CORRUPT
        )

    def test_unreadable_confirmed_toc(self):
        self.build()
        path = state_store.confirmed_toc_path(self.root, KEY)
        path.unlink()
        path.mkdir()
        self.assert_undeterminable(
            toc_check.check_toc(self.root, KEY), state_store.KIND_UNREADABLE
        )

    def test_unreadable_document(self):
        self.build()
        (self.root / "docs/b.md").write_bytes(b"\xff\xfe\x00bad\n")
        result = toc_check.check_toc(self.root, KEY)
        self.assert_undeterminable(result)
        self.assertEqual([c.target for c in result.causes], ["docs/b.md"])

    def test_unreadable_subdirectory_is_undeterminable_not_departure(self):
        if os.geteuid() == 0:
            self.skipTest("root は権限で読めなくならない")
        spec = TargetSpec(mode=MODE_TARGETS, key=KEY, dirs=("docs",))
        self.build(spec=spec)
        self.write("docs/locked/c.md", C_TEXT)
        locked = self.root / "docs" / "locked"
        locked.chmod(0o000)
        self.addCleanup(locked.chmod, 0o755)
        result = toc_check.check_toc(self.root, KEY)
        self.assert_undeterminable(result, toc_check.CAUSE_EXPANSION)
        self.assertEqual([c.target for c in result.causes], ["docs/locked"])
        self.assertEqual(result.documents, ())

    def test_missing_document_info_of_a_confirmed_document(self):
        self.build()
        state_store.document_info_path(self.root, ID_B).unlink()
        self.assert_undeterminable(
            toc_check.check_toc(self.root, KEY), state_store.KIND_MISSING
        )

    def test_corrupt_document_info_while_rebuild_is_needed(self):
        self.build()
        self.write("docs/a.md", a_text(body="changed"))
        state_store.document_info_path(self.root, ID_A).write_bytes(b"{broken")
        self.assert_undeterminable(
            toc_check.check_toc(self.root, KEY), state_store.KIND_CORRUPT
        )


class ReadOnlyTest(Base):
    def test_documents_and_state_are_unchanged(self):
        self.build()
        self.write("docs/a.md", a_text(body="changed"))
        self.write("docs/c.md", C_TEXT)
        self.write(".doc-link/note.txt", "state")
        spec = TargetSpec(mode=MODE_TARGETS, key=KEY, paths=(*FILES, "docs/c.md"))
        before = self.snapshot()
        for given in (None, spec):
            toc_check.check_toc(self.root, KEY, given)
            toc_check.check_toc(self.root, "unbuilt", None)
        self.assertEqual(self.snapshot(), before)

    def test_no_state_directory_is_created(self):
        toc_check.check_toc(self.root, KEY)
        self.assertFalse((self.root / ".doc-link").exists())


if __name__ == "__main__":
    unittest.main()
