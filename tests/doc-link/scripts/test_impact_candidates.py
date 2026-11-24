import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import change_set  # noqa: E402
import impact_candidates  # noqa: E402
import state_store  # noqa: E402
import toc_candidate  # noqa: E402
import toc_check  # noqa: E402
from content_hash import RECORD_LENGTH, document_content_hash, title_value  # noqa: E402
from reference_check import check_document  # noqa: E402
from target_spec import MODE_TARGETS, TargetSpec  # noqa: E402

KEY = "k"
ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
ID_C = "DLID-pqrstvwxyz01"
ID_NONE = "DLID-zzzzzzzzzzzz"
S_A = "DLID-00000000s001"
S_B1 = "DLID-00000000s002"
S_B2 = "DLID-00000000s003"
S_C = "DLID-00000000s004"
WHEN = "2026-11-13T00:00:00+00:00"
OLD = "e" * RECORD_LENGTH


def title(target, record=None):
    return f"{record} {target}" if record else target


def a_text(doc=None, sec=None, extra=""):
    return (
        f"---\ndoc_link_id: {ID_A}\n---\n# A {S_A}\n\nbody\n\n"
        f'[b]: b.md "{title(ID_B, doc)}"\n'
        f'[b2]: b.md "{title(S_B2, sec)}"\n{extra}'
    )


def b_text(intro="intro", part="part"):
    return f"---\ndoc_link_id: {ID_B}\n---\n# B1 {S_B1}\n\n{intro}\n\n# B2 {S_B2}\n\n{part}\n"


class ImpactTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def build(self, files, key=KEY):
        """`files` は {パス: (文書 ID, 本文)}。[文書情報]と[確定 ToC]を index-docs が確定した状態にする。"""
        for path, (doc_id, text) in files.items():
            self.write(path, text)
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
        paths = list(files)
        spec = TargetSpec(mode=MODE_TARGETS, key=key, paths=tuple(paths))
        cs = change_set.build_change_set(self.root, key, paths)
        results = {
            item.doc_link_id: check_document(self.root, item.path, checked_at=WHEN)
            for item in cs.confirmed_documents
        }
        toc_candidate.build_and_publish(self.root, "test", key, spec, cs, results, WHEN)
        self.paths = paths
        self.spec = spec

    def hashes(self, key=KEY):
        """title に書く値（[確定 ToC]の完全なハッシュの先頭 12 桁）。"""
        toc = state_store.load_confirmed_toc(self.root, key)
        return (
            {
                e["doc_link_id"]: title_value(e["applied_hash"])
                for e in toc["documents"]
            },
            {e["section_id"]: title_value(e["content_hash"]) for e in toc["sections"]},
        )

    def enumerate(self, key=KEY):
        return impact_candidates.enumerate_impact(self.root, key)

    def referrers(self, result):
        return [
            (d.doc_link_id, r.source_doc_id, r.target_dlid, r.recorded_hash)
            for d in result.changed_documents
            for r in d.referrers
        ]

    def snapshot(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }


class ComparisonTest(ImpactTestBase):
    def files(self, a=None):
        return {
            "a.md": (ID_A, a if a is not None else a_text()),
            "b.md": (ID_B, b_text()),
        }

    def test_references_without_a_record_are_returned_with_current_hashes(self):
        self.build(self.files())
        docs, secs = self.hashes()
        result = self.enumerate()
        self.assertEqual(
            self.referrers(result),
            [(ID_B, ID_A, ID_B, None), (ID_B, ID_A, S_B2, None)],
        )
        (changed,) = result.changed_documents
        self.assertEqual(changed.path, "b.md")
        document_ref, section_ref = changed.referrers
        self.assertEqual(document_ref.current_hash, docs[ID_B])
        self.assertEqual(document_ref.target_kind, "document")
        self.assertEqual(section_ref.current_hash, secs[S_B2])
        self.assertEqual(section_ref.target_kind, "section")
        self.assertEqual(section_ref.target_section_id, S_B2)
        self.assertEqual(section_ref.target_heading, "B2")

    def test_different_record_is_returned_and_matching_record_is_not(self):
        self.build(self.files())
        docs, secs = self.hashes()
        self.write("a.md", a_text(doc=OLD, sec=secs[S_B2]))
        # a.md の記録だけを書き換えた現物は、[ToC]が最新のままで、旧い記録の参照だけを返す
        result = self.enumerate()
        self.assertEqual(self.referrers(result), [(ID_B, ID_A, ID_B, OLD)])
        self.assertEqual(
            result.changed_documents[0].referrers[0].current_hash, docs[ID_B]
        )

    def test_record_equal_to_current_returns_nothing_and_toc_stays_up_to_date(self):
        self.build(self.files())
        docs, secs = self.hashes()
        before_hash = document_content_hash(a_text())
        self.write("a.md", a_text(doc=docs[ID_B], sec=secs[S_B2]))
        self.assertEqual(
            document_content_hash(a_text(doc=docs[ID_B], sec=secs[S_B2])), before_hash
        )
        check = toc_check.check_toc(self.root, KEY, self.spec)
        self.assertEqual(check.status, toc_check.STATUS_UP_TO_DATE)
        result = self.enumerate()
        self.assertEqual(result.changed_documents, ())
        self.assertEqual(result.scanned_documents, ("a.md",))
        self.assertEqual(result.toc_key, KEY)

    def test_same_references_are_returned_every_time_until_rewritten(self):
        self.build(self.files())
        first = self.referrers(self.enumerate())
        self.assertEqual(first, self.referrers(self.enumerate()))
        self.assertEqual(first, self.referrers(self.enumerate()))

    def test_record_in_state_is_not_used(self):
        self.build(self.files())
        docs, secs = self.hashes()
        # [確定 ToC]に保存した記録は旧いまま、現物の記録だけが一致している
        self.write("a.md", a_text(doc=docs[ID_B], sec=secs[S_B2]))
        toc = state_store.load_confirmed_toc(self.root, KEY)
        self.assertTrue(
            all(e["recorded_content_hash"] is None for e in toc["references"])
        )
        self.assertEqual(self.enumerate().changed_documents, ())


class ScopeOfChangeTest(ImpactTestBase):
    def recorded_build(self):
        self.build({"a.md": (ID_A, a_text()), "b.md": (ID_B, b_text())})
        docs, secs = self.hashes()
        self.write("a.md", a_text(doc=docs[ID_B], sec=secs[S_B2]))
        self.assertEqual(self.enumerate().changed_documents, ())

    def rebuild_with(self, b):
        a = (self.root / "a.md").read_text(encoding="utf-8")
        self.build({"a.md": (ID_A, a), "b.md": (ID_B, b)})

    def test_document_reference_follows_any_change_section_reference_only_its_range(
        self,
    ):
        self.recorded_build()
        self.rebuild_with(b_text(intro="intro changed"))
        result = self.enumerate()
        self.assertEqual(self.referrers(result), [(ID_B, ID_A, ID_B, self.old_doc())])

    def old_doc(self):
        text = (self.root / "a.md").read_text(encoding="utf-8")
        from references import extract_references

        return extract_references(text)[0].recorded_hash

    def test_section_reference_is_returned_when_its_range_changes(self):
        self.recorded_build()
        self.rebuild_with(b_text(part="part changed"))
        result = self.enumerate()
        self.assertEqual(
            sorted(self.referrers(result), key=lambda item: item[2]),
            sorted(
                [
                    (ID_B, ID_A, ID_B, self.old_doc()),
                    (ID_B, ID_A, S_B2, self.old_record_section()),
                ],
                key=lambda item: item[2],
            ),
        )

    def old_record_section(self):
        from references import extract_references

        text = (self.root / "a.md").read_text(encoding="utf-8")
        return extract_references(text)[1].recorded_hash


class StructureTest(ImpactTestBase):
    def test_indirect_referrers_are_not_included(self):
        c_text = (
            f'---\ndoc_link_id: {ID_C}\n---\n# C {S_C}\n\n[a]: a.md "{{rec}} {ID_A}"\n'
        )
        files = {
            "a.md": (ID_A, a_text()),
            "b.md": (ID_B, b_text()),
            "c.md": (ID_C, c_text.replace("{rec} ", "")),
        }
        self.build(files)
        docs, secs = self.hashes()
        files["a.md"] = (ID_A, a_text(doc=docs[ID_B], sec=secs[S_B2]))
        files["c.md"] = (ID_C, c_text.replace("{rec}", docs[ID_A]))
        self.build(files)
        self.assertEqual(self.enumerate().changed_documents, ())
        files["b.md"] = (ID_B, b_text(intro="changed"))
        self.build(files)
        result = self.enumerate()
        self.assertEqual([d.doc_link_id for d in result.changed_documents], [ID_B])
        self.assertEqual(
            {r.source_doc_id for r in result.changed_documents[0].referrers}, {ID_A}
        )

    def test_changed_documents_group_their_referrers(self):
        c_text = f'---\ndoc_link_id: {ID_C}\n---\n# C {S_C}\n\n[b]: b.md "{ID_B}"\n[a]: a.md "{ID_A}"\n'
        self.build(
            {
                "a.md": (ID_A, a_text()),
                "b.md": (ID_B, b_text()),
                "c.md": (ID_C, c_text),
            }
        )
        result = self.enumerate()
        by_doc = {
            d.doc_link_id: [(r.source_path, r.line) for r in d.referrers]
            for d in result.changed_documents
        }
        self.assertEqual(
            by_doc,
            {
                ID_A: [("c.md", 7)],
                ID_B: [("a.md", 8), ("a.md", 9), ("c.md", 6)],
            },
        )
        self.assertEqual(
            [d.doc_link_id for d in result.changed_documents], sorted(by_doc)
        )
        first = result.changed_documents[1].referrers[0]
        self.assertEqual(first.definition, f'[b]: b.md "{ID_B}"')

    def test_reference_whose_target_is_not_in_the_toc_is_not_returned(self):
        a = a_text(extra=f'[x]: x.md "{ID_NONE}"\n[y]: b.md "{"DLID-00000000s999"}"\n')
        self.build({"a.md": (ID_A, a), "b.md": (ID_B, b_text())})
        result = self.enumerate()
        self.assertEqual(
            {target for _, _, target, _ in self.referrers(result)}, {ID_B, S_B2}
        )

    def test_no_references_gives_empty_result_with_scope(self):
        self.build({"b.md": (ID_B, b_text())})
        result = self.enumerate()
        self.assertEqual(result.changed_documents, ())
        self.assertEqual(result.scanned_documents, ())
        self.assertEqual(result.toc_version, 1)
        self.assertEqual(result.target_spec["key"], KEY)


class OtherKeyTargetTest(ImpactTestBase):
    """参照先が、検査する[ToC 識別キー]に所属せず、別のキーにだけ所属する（Issue #14）。"""

    def build_two_keys(self, a=None, b=None):
        self.build({"b.md": (ID_B, b if b is not None else b_text())}, key="two")
        self.build({"a.md": (ID_A, a if a is not None else a_text())}, key="one")

    def test_reference_to_a_document_of_another_key_is_compared(self):
        self.build_two_keys()
        docs, secs = self.hashes("two")
        result = self.enumerate("one")
        self.assertEqual(
            self.referrers(result),
            [(ID_B, ID_A, ID_B, None), (ID_B, ID_A, S_B2, None)],
        )
        (changed,) = result.changed_documents
        self.assertEqual(changed.path, "b.md")
        document_ref, section_ref = changed.referrers
        self.assertEqual(document_ref.current_hash, docs[ID_B])
        self.assertEqual(document_ref.target_kind, "document")
        self.assertEqual(section_ref.current_hash, secs[S_B2])
        self.assertEqual(section_ref.target_section_id, S_B2)
        self.assertEqual(section_ref.target_heading, "B2")

    def test_matching_record_is_not_returned(self):
        self.build_two_keys()
        docs, secs = self.hashes("two")
        self.build_two_keys(a=a_text(doc=docs[ID_B], sec=secs[S_B2]))
        self.assertEqual(self.enumerate("one").changed_documents, ())

    def test_change_confirmed_by_the_other_key_is_returned(self):
        self.build_two_keys()
        docs, secs = self.hashes("two")
        recorded = a_text(doc=docs[ID_B], sec=secs[S_B2])
        self.build_two_keys(a=recorded)
        # 参照先だけを変えて、参照先を含むキーだけを再構築する。参照元のキーは再構築しない
        self.build({"b.md": (ID_B, b_text(part="part changed"))}, key="two")
        new_docs, new_secs = self.hashes("two")
        result = self.enumerate("one")
        self.assertEqual(
            self.referrers(result),
            [(ID_B, ID_A, ID_B, docs[ID_B]), (ID_B, ID_A, S_B2, secs[S_B2])],
        )
        document_ref, section_ref = result.changed_documents[0].referrers
        self.assertEqual(document_ref.current_hash, new_docs[ID_B])
        self.assertEqual(section_ref.current_hash, new_secs[S_B2])

    def test_document_info_not_yet_in_any_toc_is_not_compared(self):
        # 要約だけが保存され、どの[確定 ToC]にもまだ入っていない文書は、確定した値を持たない
        self.build({"a.md": (ID_A, a_text())}, key="one")
        state_store.save_document_info(
            self.root,
            "test",
            {
                "doc_link_id": ID_B,
                "path": "b.md",
                "title": "t",
                "purpose": "p",
                "summary": [],
                "tasks": [],
                "keywords": [],
                "content_hash": "h",
            },
        )
        self.assertEqual(self.enumerate("one").changed_documents, ())

    def test_section_recorded_in_several_documents_outside_the_key(self):
        # セクションを別の文書へ移した後、移動元の文書を含むキーを再構築していない状態
        self.build_two_keys()
        moved = f"---\ndoc_link_id: {ID_C}\n---\n# C {S_C}\n\n# B2 {S_B2}\n\nmoved\n"
        self.build({"c.md": (ID_C, moved)}, key="three")
        _, secs_two = self.hashes("two")
        _, secs_three = self.hashes("three")
        self.write("a.md", a_text(sec=secs_three[S_B2]))
        self.build({"a.md": (ID_A, a_text(sec=secs_three[S_B2]))}, key="one")
        result = self.enumerate("one")
        section_refs = [item for item in self.referrers(result) if item[2] == S_B2]
        # 記録と異なる所属文書（移動元）についてだけ、影響候補になる
        self.assertEqual(section_refs, [(ID_B, ID_A, S_B2, secs_three[S_B2])])
        self.assertNotEqual(secs_two[S_B2], secs_three[S_B2])

    def test_broken_document_info_outside_the_key_fails(self):
        self.build_two_keys()
        state_store.document_info_path(self.root, ID_B).write_bytes(b"{broken")
        with self.assertRaises(impact_candidates.ImpactFailure) as caught:
            self.enumerate("one")
        self.assertTrue(any("corrupt" in line for line in caught.exception.errors))


class FailureTest(ImpactTestBase):
    def test_missing_toc_fails(self):
        with self.assertRaises(impact_candidates.ImpactFailure) as caught:
            self.enumerate()
        self.assertTrue(caught.exception.errors)

    def test_unreadable_source_fails(self):
        self.build({"a.md": (ID_A, a_text()), "b.md": (ID_B, b_text())})
        (self.root / "a.md").write_bytes(b"\xff\xfe\x00bad\n")
        with self.assertRaises(impact_candidates.ImpactFailure) as caught:
            self.enumerate()
        self.assertTrue(any("a.md" in line for line in caught.exception.errors))

    def test_missing_source_fails(self):
        self.build({"a.md": (ID_A, a_text()), "b.md": (ID_B, b_text())})
        (self.root / "a.md").unlink()
        with self.assertRaises(impact_candidates.ImpactFailure):
            self.enumerate()

    def test_toc_and_source_that_disagree_fail(self):
        self.build({"a.md": (ID_A, a_text()), "b.md": (ID_B, b_text())})
        self.write("a.md", f"---\ndoc_link_id: {ID_A}\n---\n# A {S_A}\n")
        with self.assertRaises(impact_candidates.ImpactFailure):
            self.enumerate()

    def test_missing_document_info_fails(self):
        self.build({"a.md": (ID_A, a_text()), "b.md": (ID_B, b_text())})
        state_store.document_info_path(self.root, ID_A).unlink()
        with self.assertRaises(impact_candidates.ImpactFailure):
            self.enumerate()


class ReadOnlyTest(ImpactTestBase):
    def test_nothing_is_written(self):
        self.build({"a.md": (ID_A, a_text()), "b.md": (ID_B, b_text())})
        self.write(".doc-link/note.txt", "state")
        before = self.snapshot()
        self.enumerate()
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
