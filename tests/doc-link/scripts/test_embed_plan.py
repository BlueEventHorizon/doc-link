import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import embed_plan  # noqa: E402
import state_store  # noqa: E402
from dlid import KIND_DOCUMENT, KIND_SECTION, DlidLocation  # noqa: E402

ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
ID_C = "DLID-pqrstvwxyz01"
ID_UNUSED = "DLID-zzzzzzzzzzzz"


def fixed_issuer():
    values = iter(f"DLID-{n:012d}" for n in range(1, 1000))
    return lambda: next(values)


class PlanTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def record(self, key, doc_id, path, section_ids=(), previous_format=False):
        # 配列のフィールドには最小の 1 件を入れる（sections は走査しない[セクション ID]）。
        reference = {
            "source_doc_id": doc_id,
            "source_section_id": None,
            "position": 0,
            "target_doc_id": doc_id,
            "target_section_id": None,
            "recorded_path": path,
            "recorded_content_hash": None,
            "kind": "doc",
            "check": {
                "scope": "s",
                "result": "match",
                "found_path": None,
            },
        }
        state_store.save_document_info(
            self.root,
            "embed-dlid",
            {
                "doc_link_id": doc_id,
                "path": path,
                "title": "t",
                "purpose": "p",
                "summary": [],
                "tasks": [],
                "keywords": [],
                "content_hash": "h",
            },
        )
        toc = {
            "toc_key": key,
            "version": 1,
            "target_spec": {},
            "documents": [{"doc_link_id": doc_id, "applied_hash": "h"}],
            "sections": [
                {
                    "doc_link_id": doc_id,
                    "section_id": sid,
                    "heading": "h",
                    "position": index,
                    "content_hash": "h",
                }
                for index, sid in enumerate(section_ids or [ID_UNUSED])
            ],
            "references": [reference],
            "reverse_references": [
                {
                    "target_doc_id": doc_id,
                    "target_section_id": None,
                    "source_doc_id": doc_id,
                    "source_section_id": None,
                }
            ],
            "last_checks": [{"doc_link_id": doc_id, "result": "unprocessed"}],
        }
        if previous_format:
            # ひとつ前の保存形式（文書ごとの値を[確定 ToC]のファイルが持つ）
            toc_path = state_store.confirmed_toc_path(self.root, key)
            toc_path.parent.mkdir(parents=True, exist_ok=True)
            toc_path.write_bytes(state_store.serialize(toc))
        else:
            state_store.save_confirmed_toc(self.root, "embed-dlid", toc)

    def snapshot(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }


class MissingIdsTest(PlanTestBase):
    def test_document_and_headings_without_ids(self):
        self.write("a.md", "# Title\n\n## Sub\n")
        plan = embed_plan.build_plan(self.root, ["a.md"], issue=fixed_issuer())
        self.assertEqual(
            [(i.kind, i.reason, i.dlid, i.replaces) for i in plan.items],
            [
                (KIND_DOCUMENT, "missing", "DLID-000000000001", None),
                (KIND_SECTION, "missing", "DLID-000000000002", None),
                (KIND_SECTION, "missing", "DLID-000000000003", None),
            ],
        )
        self.assertEqual(
            plan.items[0].position,
            embed_plan.FrontmatterPosition(False, None, None, False),
        )
        self.assertEqual(plan.items[1].position, embed_plan.HeadingPosition(0, 1))
        self.assertEqual(plan.items[2].position, embed_plan.HeadingPosition(2, 3))
        self.assertTrue(plan.confirmed)
        self.assertEqual(plan.duplicates, ())

    def test_existing_ids_are_not_issued_again(self):
        self.write("a.md", f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n\n## U\n")
        plan = embed_plan.build_plan(self.root, ["a.md"], issue=fixed_issuer())
        self.assertEqual(
            [(i.kind, i.path) for i in plan.items], [(KIND_SECTION, "a.md")]
        )
        self.assertEqual(plan.items[0].position.start_line, 5)

    def test_frontmatter_positions(self):
        self.write("a.md", "---\ntitle: x\n---\n# T\n")
        self.write("b.md", "---\ndoc_link_id: bogus\n---\n# T\n")
        self.write("c.md", "---\ntitle: x\n# T\n")  # 閉じる行が無い
        plan = embed_plan.build_plan(self.root, ["a.md", "b.md", "c.md"])
        docs = {i.path: i.position for i in plan.items if i.kind == KIND_DOCUMENT}
        self.assertEqual(
            docs["a.md"], embed_plan.FrontmatterPosition(True, 0, 2, False)
        )
        self.assertEqual(docs["b.md"], embed_plan.FrontmatterPosition(True, 0, 2, True))
        self.assertEqual(
            docs["c.md"], embed_plan.FrontmatterPosition(False, None, None, False)
        )

    def test_positions_are_only_frontmatter_or_heading(self):
        self.write("a.md", '# T\n\n[x][r]\n\n[r]: b.md "title"\n')
        plan = embed_plan.build_plan(self.root, ["a.md"])
        for item in plan.items:
            self.assertIsInstance(
                item.position,
                (embed_plan.FrontmatterPosition, embed_plan.HeadingPosition),
            )


class DuplicateTest(PlanTestBase):
    def location(self, path, kind, line=None, text=None):
        return DlidLocation(path=path, kind=kind, line=line, heading_text=text)

    def test_duplicate_document_id_unresolved_without_candidate(self):
        text = f"---\ndoc_link_id: {ID_A}\n---\n# T\n"
        self.write("a.md", text)
        self.write("b.md", text)
        plan = embed_plan.build_plan(self.root, ["a.md", "b.md"], issue=fixed_issuer())
        self.assertEqual(len(plan.duplicates), 1)
        report = plan.duplicates[0]
        self.assertEqual(report.dlid, ID_A)
        self.assertEqual([l.path for l in report.locations], ["a.md", "b.md"])
        self.assertEqual(report.recorded_paths, ())
        self.assertEqual(report.candidates, ())
        self.assertFalse(plan.confirmed)
        self.assertEqual(plan.unresolved, plan.duplicates)
        # 原本が決まるまで、重複の箇所へは発行しない（見出しの欠落への発行だけ）
        self.assertEqual([i.kind for i in plan.items], [KIND_SECTION, KIND_SECTION])

    def test_recorded_path_makes_a_single_candidate_but_does_not_decide(self):
        text = f"---\ndoc_link_id: {ID_A}\n---\n# T\n"
        self.write("a.md", text)
        self.write("b.md", text)
        self.record("k", ID_A, "b.md")
        plan = embed_plan.build_plan(self.root, ["a.md", "b.md"])
        report = plan.duplicates[0]
        self.assertEqual(report.recorded_paths, ("b.md",))
        self.assertEqual([c.path for c in report.candidates], ["b.md"])
        self.assertIsNone(report.origin)
        self.assertFalse(plan.confirmed)

    def test_section_id_duplicate_across_and_within_documents(self):
        self.write("a.md", f"# T {ID_B}\n\n## U {ID_C}\n")
        self.write("b.md", f"# T {ID_B}\n\n## U {ID_C}\n\n## V {ID_C}\n")
        plan = embed_plan.build_plan(self.root, ["a.md", "b.md"])
        found = {
            d.dlid: [(l.path, l.line) for l in d.locations] for d in plan.duplicates
        }
        self.assertEqual(
            found,
            {
                ID_B: [("a.md", 0), ("b.md", 0)],
                ID_C: [("a.md", 2), ("b.md", 2), ("b.md", 4)],
            },
        )

    def test_same_section_id_twice_in_one_document(self):
        self.write("a.md", f"# T {ID_B}\n\n## U {ID_B}\n")
        plan = embed_plan.build_plan(self.root, ["a.md"])
        self.assertEqual(
            [(l.path, l.line) for l in plan.duplicates[0].locations],
            [("a.md", 0), ("a.md", 2)],
        )

    def test_document_id_equal_to_section_id_is_duplicate(self):
        self.write("a.md", f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_A}\n")
        plan = embed_plan.build_plan(self.root, ["a.md"])
        self.assertEqual(
            [l.kind for l in plan.duplicates[0].locations],
            [KIND_DOCUMENT, KIND_SECTION],
        )

    def test_section_recorded_path_uses_owning_document(self):
        self.write("a.md", f"# T {ID_B}\n")
        self.write("b.md", f"# T {ID_B}\n")
        self.record("k", ID_A, "b.md", section_ids=[ID_B])
        plan = embed_plan.build_plan(self.root, ["a.md", "b.md"])
        self.assertEqual([c.path for c in plan.duplicates[0].candidates], ["b.md"])

    def test_origin_confirmed_reissues_non_origin_document_and_its_sections(self):
        a = f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n\n## U {ID_C}\n"
        self.write("a.md", a)
        self.write("b.md", a + "\n## W\n")
        first = embed_plan.build_plan(self.root, ["a.md", "b.md"])
        origins = {
            d.dlid: next(l for l in d.locations if l.path == "a.md")
            for d in first.duplicates
        }
        plan = embed_plan.build_plan(
            self.root, ["a.md", "b.md"], origins=origins, issue=fixed_issuer()
        )
        self.assertTrue(plan.confirmed)
        self.assertTrue(all(i.path == "b.md" for i in plan.items))
        self.assertEqual(
            [(i.kind, i.reason, i.replaces) for i in plan.items],
            [
                (KIND_DOCUMENT, "duplicate", ID_A),
                (KIND_SECTION, "duplicate", ID_B),
                (KIND_SECTION, "duplicate", ID_C),
                (KIND_SECTION, "missing", None),
            ],
        )
        self.assertEqual(len({i.dlid for i in plan.items}), 4)

    def test_document_origin_alone_resolves_the_copied_documents_sections(self):
        copy = f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n\n## U {ID_C}\n"
        self.write("a.md", copy)
        self.write("b.md", copy)
        before = embed_plan.build_plan(self.root, ["a.md", "b.md"])
        self.assertEqual(
            sorted(d.dlid for d in before.unresolved), sorted([ID_A, ID_B, ID_C])
        )
        plan = embed_plan.build_plan(
            self.root,
            ["a.md", "b.md"],
            origins={ID_A: self.location("a.md", KIND_DOCUMENT)},
            issue=fixed_issuer(),
        )
        self.assertTrue(plan.confirmed)
        self.assertEqual(plan.unresolved, ())
        implied = {d.dlid: d for d in plan.duplicates}
        for dlid_value in (ID_B, ID_C):
            self.assertIsNone(implied[dlid_value].origin)
            self.assertTrue(implied[dlid_value].implied_by_reissue)
        self.assertFalse(implied[ID_A].implied_by_reissue)
        self.assertTrue(all(i.path == "b.md" for i in plan.items))
        self.assertEqual(
            [(i.kind, i.reason, i.replaces) for i in plan.items],
            [
                (KIND_DOCUMENT, "duplicate", ID_A),
                (KIND_SECTION, "duplicate", ID_B),
                (KIND_SECTION, "duplicate", ID_C),
            ],
        )

    def test_section_duplicate_with_two_remaining_documents_still_needs_origin(self):
        self.write("a.md", f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n")
        self.write("b.md", f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n")
        self.write("c.md", f"# T {ID_B}\n")
        plan = embed_plan.build_plan(
            self.root,
            ["a.md", "b.md", "c.md"],
            origins={ID_A: self.location("a.md", KIND_DOCUMENT)},
        )
        self.assertEqual([d.dlid for d in plan.unresolved], [ID_B])
        self.assertFalse(plan.confirmed)

    def test_origin_is_not_reissued(self):
        text = f"---\ndoc_link_id: {ID_A}\n---\n# T\n"
        self.write("a.md", text)
        self.write("b.md", text)
        origin = self.location("b.md", KIND_DOCUMENT)
        plan = embed_plan.build_plan(
            self.root, ["a.md", "b.md"], origins={ID_A: origin}
        )
        docs = [i for i in plan.items if i.kind == KIND_DOCUMENT]
        self.assertEqual([i.path for i in docs], ["a.md"])
        self.assertEqual(plan.duplicates[0].origin, origin)

    def test_section_duplicate_in_same_document_reissues_only_non_origin(self):
        self.write("a.md", f"# T {ID_B}\n\n## U {ID_B}\n")
        plan = embed_plan.build_plan(
            self.root,
            ["a.md"],
            origins={ID_B: self.location("a.md", KIND_SECTION, 0, f"T {ID_B}")},
        )
        self.assertTrue(plan.confirmed)
        self.assertEqual(
            [
                (i.kind, i.position.start_line)
                for i in plan.items
                if i.kind == KIND_SECTION
            ],
            [(KIND_SECTION, 2)],
        )

    def test_partial_origins_leave_the_rest_unresolved(self):
        self.write("a.md", f"# T {ID_B}\n\n## U {ID_C}\n")
        self.write("b.md", f"# T {ID_B}\n\n## U {ID_C}\n")
        plan = embed_plan.build_plan(
            self.root,
            ["a.md", "b.md"],
            origins={ID_B: self.location("a.md", KIND_SECTION, 0, f"T {ID_B}")},
        )
        self.assertEqual([d.dlid for d in plan.unresolved], [ID_C])
        self.assertFalse(plan.confirmed)

    def test_invalid_origin_is_rejected(self):
        self.write("a.md", f"# T {ID_B}\n")
        self.write("b.md", f"# T {ID_B}\n")
        bogus = self.location("c.md", KIND_SECTION, 0, "x")
        for origins in (
            {ID_B: bogus},
            {ID_C: self.location("a.md", KIND_SECTION, 0, f"T {ID_B}")},
        ):
            with self.subTest(origins=origins):
                with self.assertRaises(embed_plan.PlanFailure) as caught:
                    embed_plan.build_plan(self.root, ["a.md", "b.md"], origins=origins)
                self.assertEqual(
                    caught.exception.kind, embed_plan.FAILURE_INVALID_ORIGIN
                )

    def test_conflicting_origin_inside_reissued_document_is_rejected(self):
        doc = f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n"
        self.write("a.md", doc)
        self.write("b.md", doc)
        origins = {
            ID_A: self.location("a.md", KIND_DOCUMENT),
            ID_B: self.location("b.md", KIND_SECTION, 3, f"T {ID_B}"),
        }
        with self.assertRaises(embed_plan.PlanFailure) as caught:
            embed_plan.build_plan(self.root, ["a.md", "b.md"], origins=origins)
        self.assertEqual(caught.exception.kind, embed_plan.FAILURE_INVALID_ORIGIN)


class FailureTest(PlanTestBase):
    def test_unreadable_documents_are_all_reported(self):
        self.write("a.md", "# T\n")
        (self.root / "bad.md").write_bytes(b"\xff\xfe\x00bad")
        with self.assertRaises(embed_plan.PlanFailure) as caught:
            embed_plan.build_plan(self.root, ["a.md", "bad.md", "gone.md"])
        failure = caught.exception
        self.assertEqual(failure.kind, embed_plan.FAILURE_DOCUMENT_UNREADABLE)
        self.assertEqual([p.path for p in failure.problems], ["bad.md", "gone.md"])

    def test_corrupt_state_fails_with_kind_kept(self):
        self.write("a.md", "# T\n")
        tocs = self.root / ".doc-link" / "tocs"
        tocs.mkdir(parents=True)
        (tocs / "k.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(embed_plan.PlanFailure) as caught:
            embed_plan.build_plan(self.root, ["a.md"])
        self.assertEqual(caught.exception.kind, embed_plan.FAILURE_STATE_UNREADABLE)
        self.assertEqual(
            caught.exception.problems[0].state_kind, state_store.KIND_CORRUPT
        )

    def test_no_state_is_not_a_failure(self):
        self.write("a.md", "# T\n")
        plan = embed_plan.build_plan(self.root, ["a.md"])
        self.assertEqual(len(plan.items), 2)

    def test_unreadable_document_info_other_than_missing_fails(self):
        text = f"---\ndoc_link_id: {ID_A}\n---\n# T\n"
        self.write("a.md", text)
        self.write("b.md", text)
        self.record("k", ID_A, "a.md")
        info = state_store.document_info_path(self.root, ID_A)
        info.write_text("{broken", encoding="utf-8")
        with self.assertRaises(embed_plan.PlanFailure) as caught:
            embed_plan.build_plan(self.root, ["a.md", "b.md"])
        self.assertEqual(
            caught.exception.problems[0].state_kind, state_store.KIND_CORRUPT
        )

    def test_missing_document_info_means_no_recorded_path(self):
        # ひとつ前の保存形式では、[確定 ToC]のファイルだけがあり[文書情報]が無い状態がありうる
        text = f"---\ndoc_link_id: {ID_A}\n---\n# T\n"
        self.write("a.md", text)
        self.write("b.md", text)
        self.record("k", ID_A, "a.md", previous_format=True)
        state_store.document_info_path(self.root, ID_A).unlink()
        plan = embed_plan.build_plan(self.root, ["a.md", "b.md"])
        self.assertEqual(plan.duplicates[0].recorded_paths, ())
        self.assertEqual(plan.duplicates[0].candidates, ())

    def test_missing_document_info_of_a_toc_document_fails(self):
        text = f"---\ndoc_link_id: {ID_A}\n---\n# T\n"
        self.write("a.md", text)
        self.write("b.md", text)
        self.record("k", ID_A, "a.md")
        state_store.document_info_path(self.root, ID_A).unlink()
        with self.assertRaises(embed_plan.PlanFailure) as caught:
            embed_plan.build_plan(self.root, ["a.md", "b.md"])
        self.assertEqual(caught.exception.kind, embed_plan.FAILURE_STATE_UNREADABLE)
        self.assertEqual(
            caught.exception.problems[0].state_kind, state_store.KIND_CORRUPT
        )


class ReadOnlyTest(PlanTestBase):
    def test_plan_does_not_change_documents_or_state(self):
        text = f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n\n## U\n"
        self.write("a.md", text)
        self.write("b.md", text)
        self.write("c.md", "# no id\n")
        self.record("k", ID_A, "a.md", section_ids=[ID_B])
        before = self.snapshot()
        embed_plan.build_plan(self.root, ["a.md", "b.md", "c.md"])
        embed_plan.build_plan(
            self.root,
            ["a.md", "b.md", "c.md"],
            origins={ID_A: DlidLocation("a.md", KIND_DOCUMENT, None, None)},
        )
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
