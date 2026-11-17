import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import change_set  # noqa: E402
import state_store  # noqa: E402
import toc_candidate  # noqa: E402
from content_hash import document_content_hash, section_content_hashes  # noqa: E402
from reference_check import check_document  # noqa: E402
from target_spec import MODE_TARGETS, TargetSpec  # noqa: E402

KEY = "main"
OTHER_KEY = "other"
ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
ID_C = "DLID-pqrstvwxyz01"
ID_D = "DLID-pqrstvwxyz02"
ID_E = "DLID-pqrstvwxyz03"
ID_F = "DLID-pqrstvwxyz04"
S1 = "DLID-00000000s001"
S2 = "DLID-00000000s002"
S3 = "DLID-00000000s003"
RECORD = "c" * 64
WHEN = "2026-11-13T00:00:00+00:00"
FILES = ["docs/a.md", "docs/b.md"]
SPEC = TargetSpec(mode=MODE_TARGETS, key=KEY, paths=tuple(FILES))

A_TEXT = f"""---
doc_link_id: {ID_A}
---
# A {S1}

[to b][b]

## Sub {S2}

[sec][s3] [gone][g] [nodir][n] [moved][m] [frag][f] [out][u]

[b]: b.md "{RECORD} {ID_B}"
[s3]: b.md "{S3}"
[g]: missing.md "{ID_C}"
[n]: nodir/x.md "{ID_D}"
[m]: sub/x.md "{ID_E}"
[f]: b.md#nonexistent "{ID_B}"
[u]: ../../x.md "{ID_F}"
"""

B_TEXT = f"""---
doc_link_id: {ID_B}
---
# B {S3}

[back][a]

[a]: a.md "{ID_A}"
"""

Y_TEXT = f"""---
doc_link_id: {ID_E}
---
# Y
"""


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.write("docs/a.md", A_TEXT)
        self.write("docs/b.md", B_TEXT)
        self.write("docs/sub/y.md", Y_TEXT)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def read(self, path):
        return (self.root / path).read_text(encoding="utf-8")

    def save_infos(self, files=FILES):
        for path in files:
            text = self.read(path)
            doc_id = state_store_doc_id(text)
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

    def change_set(self, files=FILES, key=KEY):
        return change_set.build_change_set(self.root, key, files)

    def results(self, cs):
        return {
            item.doc_link_id: check_document(self.root, item.path, checked_at=WHEN)
            for item in cs.confirmed_documents
        }

    def inputs(self, files=FILES, key=KEY):
        self.save_infos(files)
        cs = self.change_set(files, key)
        return cs, self.results(cs)

    def assemble(self, files=FILES, key=KEY):
        cs, results = self.inputs(files, key)
        return toc_candidate.assemble_candidate(self.root, key, SPEC, cs, results, WHEN)

    def publish(self, files=FILES, key=KEY, skill="test"):
        cs, results = self.inputs(files, key)
        return toc_candidate.build_and_publish(
            self.root, skill, key, SPEC, cs, results, WHEN
        )

    def toc_bytes(self, key=KEY):
        path = state_store.confirmed_toc_path(self.root, key)
        return path.read_bytes() if path.exists() else None

    def info_bytes(self):
        return {
            doc_id: state_store.document_info_path(self.root, doc_id).read_bytes()
            for doc_id in state_store.list_document_ids(self.root)
        }

    def snapshot(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }


def state_store_doc_id(text):
    for line in text.splitlines():
        if line.startswith("doc_link_id:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("no id")


class AssembleTest(Base):
    def test_candidate_has_exactly_the_confirmed_toc_fields(self):
        candidate = self.assemble()
        self.assertEqual(set(candidate), set(state_store.CONFIRMED_TOC_FIELDS))
        state_store.validate_confirmed_toc(candidate)
        self.assertEqual(candidate["toc_key"], KEY)
        self.assertEqual(candidate["version"], 1)
        self.assertEqual(candidate["target_spec"], SPEC.to_dict())

    def test_documents_have_applied_hash_of_whole_document(self):
        candidate = self.assemble()
        self.assertEqual(
            candidate["documents"],
            [
                {"doc_link_id": ID_A, "applied_hash": document_content_hash(A_TEXT)},
                {"doc_link_id": ID_B, "applied_hash": document_content_hash(B_TEXT)},
            ],
        )

    def test_sections_have_heading_position_and_section_hash(self):
        candidate = self.assemble()
        hashes = section_content_hashes(A_TEXT)
        self.assertEqual(
            candidate["sections"],
            [
                {
                    "doc_link_id": ID_A,
                    "section_id": S1,
                    "heading": "A",
                    "position": 0,
                    "content_hash": hashes[0],
                },
                {
                    "doc_link_id": ID_A,
                    "section_id": S2,
                    "heading": "Sub",
                    "position": 1,
                    "content_hash": hashes[1],
                },
                {
                    "doc_link_id": ID_B,
                    "section_id": S3,
                    "heading": "B",
                    "position": 0,
                    "content_hash": section_content_hashes(B_TEXT)[0],
                },
            ],
        )

    def test_references_record_results_without_stopping(self):
        candidate = self.assemble()
        refs = [r for r in candidate["references"] if r["source_doc_id"] == ID_A]
        self.assertEqual([r["position"] for r in refs], list(range(7)))
        by_path = {r["recorded_path"]: r for r in refs}
        results = {path: r["check"]["result"] for path, r in by_path.items()}
        self.assertEqual(
            results,
            {
                "b.md": "match",
                "missing.md": "absent",
                "nodir/x.md": "absent",
                "sub/x.md": "path_mismatch",
                "b.md#nonexistent": "fragment_mismatch",
                "../../x.md": "unresolved",
            },
        )
        # b.md が 2 件（記録語あり・セクション参照）ある
        self.assertEqual(sum(1 for r in refs if r["recorded_path"] == "b.md"), 2)

    def test_reference_entry_fields(self):
        candidate = self.assemble()
        refs = {(r["source_doc_id"], r["position"]): r for r in candidate["references"]}
        document_ref = refs[(ID_A, 0)]
        self.assertEqual(
            document_ref,
            {
                "source_doc_id": ID_A,
                "source_section_id": None,
                "position": 0,
                "target_doc_id": ID_B,
                "target_section_id": None,
                "recorded_path": "b.md",
                "recorded_content_hash": RECORD,
                "kind": "document",
                "check": {
                    "scope": "docs",
                    "checked_at": WHEN,
                    "result": "match",
                    "found_path": "docs/b.md",
                },
            },
        )
        section_ref = refs[(ID_A, 1)]
        self.assertEqual(section_ref["kind"], "section")
        self.assertEqual(section_ref["target_section_id"], S3)
        self.assertEqual(section_ref["target_doc_id"], ID_B)
        self.assertIsNone(section_ref["recorded_content_hash"])
        absent = refs[(ID_A, 2)]
        self.assertEqual(absent["kind"], "unknown")
        self.assertEqual(absent["target_doc_id"], ID_C)
        self.assertIsNone(absent["target_section_id"])
        self.assertIsNone(absent["check"]["found_path"])
        no_dir = refs[(ID_A, 3)]
        self.assertEqual(no_dir["check"]["scope"], "docs/nodir")
        moved = refs[(ID_A, 4)]
        self.assertEqual(moved["check"]["found_path"], "docs/sub/y.md")
        unresolved = refs[(ID_A, 6)]
        self.assertEqual(unresolved["check"]["scope"], "")

    def test_reverse_references_are_derived_from_references(self):
        candidate = self.assemble()
        derived = {
            (
                r["target_doc_id"],
                r["target_section_id"],
                r["source_doc_id"],
                r["source_section_id"],
            )
            for r in candidate["references"]
        }
        recorded = {
            (
                r["target_doc_id"],
                r["target_section_id"],
                r["source_doc_id"],
                r["source_section_id"],
            )
            for r in candidate["reverse_references"]
        }
        self.assertEqual(derived, recorded)
        self.assertEqual(len(candidate["reverse_references"]), len(recorded))
        # A が B を 3 件（文書・断片不一致の 2 件は同じ組）、B が A を参照
        self.assertIn((ID_B, None, ID_A, None), recorded)
        self.assertIn((ID_B, S3, ID_A, None), recorded)
        self.assertIn((ID_A, None, ID_B, None), recorded)

    def test_last_checks(self):
        candidate = self.assemble()
        self.assertEqual(
            candidate["last_checks"],
            [
                # A は解決できない参照を含むので failure
                {"doc_link_id": ID_A, "checked_at": WHEN, "result": "failure"},
                {"doc_link_id": ID_B, "checked_at": WHEN, "result": "success"},
            ],
        )

    def test_absent_and_mismatch_alone_are_success(self):
        self.write(
            "docs/a.md",
            A_TEXT.replace(f'[u]: ../../x.md "{ID_F}"\n', ""),
        )
        candidate = self.assemble()
        checks = {c["doc_link_id"]: c["result"] for c in candidate["last_checks"]}
        self.assertEqual(checks, {ID_A: "success", ID_B: "success"})

    def test_departed_and_excluded_documents_are_not_in_candidate(self):
        candidate = self.assemble(files=["docs/a.md"])
        self.assertEqual([d["doc_link_id"] for d in candidate["documents"]], [ID_A])
        self.assertEqual({s["doc_link_id"] for s in candidate["sections"]}, {ID_A})

    def test_candidate_does_not_contain_document_info(self):
        candidate = self.assemble()
        self.assertNotIn("title", repr(candidate.keys()))
        for entry in candidate["documents"]:
            self.assertEqual(set(entry), {"doc_link_id", "applied_hash"})

    def test_deterministic(self):
        first = self.assemble()
        second = self.assemble()
        self.assertEqual(first, second)
        self.assertEqual(state_store.serialize(first), state_store.serialize(second))

    def test_missing_reference_results_fail_assembly(self):
        cs, results = self.inputs()
        del results[ID_B]
        with self.assertRaises(toc_candidate.CandidateFailure) as caught:
            toc_candidate.assemble_candidate(self.root, KEY, SPEC, cs, results, WHEN)
        report = caught.exception.report
        self.assertEqual(report.stage, toc_candidate.STAGE_ASSEMBLY)
        self.assertEqual(report.problems[0].doc_link_id, ID_B)
        self.assertEqual(report.problems[0].path, "docs/b.md")
        self.assertEqual(report.problems[0].field, "references")
        self.assertFalse(report.confirmed_toc_present)

    def test_reference_results_of_another_source_fail_assembly(self):
        cs, results = self.inputs()
        results[ID_B] = results[ID_A]
        with self.assertRaises(toc_candidate.CandidateFailure) as caught:
            toc_candidate.assemble_candidate(self.root, KEY, SPEC, cs, results, WHEN)
        self.assertEqual(caught.exception.report.stage, toc_candidate.STAGE_ASSEMBLY)

    def test_unreadable_document_fails_assembly(self):
        cs, results = self.inputs()
        (self.root / "docs/b.md").unlink()
        with self.assertRaises(toc_candidate.CandidateFailure) as caught:
            toc_candidate.assemble_candidate(self.root, KEY, SPEC, cs, results, WHEN)
        problem = caught.exception.report.problems[0]
        self.assertEqual((problem.doc_link_id, problem.path), (ID_B, "docs/b.md"))

    def test_assembly_does_not_write(self):
        self.save_infos()
        before = self.snapshot()
        cs = self.change_set()
        toc_candidate.assemble_candidate(
            self.root, KEY, SPEC, cs, self.results(cs), WHEN
        )
        self.assertEqual(self.snapshot(), before)


class VersionTest(Base):
    def test_version_unchanged_for_same_content_and_incremented_for_change(self):
        first = self.publish().candidate
        self.assertEqual(first["version"], 1)
        before = self.toc_bytes()
        again = self.publish()
        self.assertEqual(again.candidate["version"], 1)
        self.assertFalse(again.written)
        self.assertEqual(self.toc_bytes(), before)
        self.write("docs/b.md", B_TEXT + "\n追記\n")
        changed = self.publish()
        self.assertEqual(changed.candidate["version"], 2)
        self.assertTrue(changed.written)

    def test_non_integer_previous_version_fails_assembly(self):
        candidate = self.assemble()
        state_store.save_confirmed_toc(
            self.root, "test", {**candidate, "version": "release-1"}
        )
        cs, results = self.inputs()
        with self.assertRaises(toc_candidate.CandidateFailure) as caught:
            toc_candidate.assemble_candidate(self.root, KEY, SPEC, cs, results, WHEN)
        report = caught.exception.report
        self.assertEqual(report.stage, toc_candidate.STAGE_ASSEMBLY)
        self.assertEqual(report.problems[0].field, "version")
        self.assertTrue(report.confirmed_toc_present)

    def test_corrupt_previous_toc_fails_assembly(self):
        cs, results = self.inputs()
        path = state_store.confirmed_toc_path(self.root, KEY)
        path.parent.mkdir(parents=True)
        path.write_text("{", encoding="utf-8")
        with self.assertRaises(toc_candidate.CandidateFailure) as caught:
            toc_candidate.assemble_candidate(self.root, KEY, SPEC, cs, results, WHEN)
        self.assertEqual(caught.exception.report.stage, toc_candidate.STAGE_ASSEMBLY)


class ValidateTest(Base):
    def setUp(self):
        super().setUp()
        self.cs, results = self.inputs()
        self.candidate = toc_candidate.assemble_candidate(
            self.root, KEY, SPEC, self.cs, results, WHEN
        )

    def validate(self, candidate=None, confirmed=None):
        toc_candidate.validate_candidate(
            self.root,
            self.candidate if candidate is None else candidate,
            self.cs.confirmed_documents if confirmed is None else confirmed,
        )

    def fails(self, candidate, field=None, confirmed=None):
        with self.assertRaises(toc_candidate.CandidateFailure) as caught:
            self.validate(candidate, confirmed)
        report = caught.exception.report
        self.assertEqual(report.stage, toc_candidate.STAGE_VALIDATION)
        if field is not None:
            self.assertIn(field, [p.field for p in report.problems])
        return report

    def test_assembled_candidate_passes(self):
        self.validate()

    def test_absent_and_path_mismatch_do_not_fail_validation(self):
        results = {r["check"]["result"] for r in self.candidate["references"]}
        self.assertTrue({"absent", "path_mismatch", "fragment_mismatch"} <= results)
        self.validate()

    def test_duplicate_document_id_rejected(self):
        candidate = {
            **self.candidate,
            "documents": self.candidate["documents"] + [self.candidate["documents"][0]],
        }
        report = self.fails(candidate, "documents")
        self.assertEqual(report.problems[0].doc_link_id, ID_A)

    def test_mismatch_with_confirmed_list_rejected(self):
        candidate = {**self.candidate, "documents": self.candidate["documents"][:1]}
        report = self.fails(candidate, "documents")
        self.assertIn(ID_B, [p.doc_link_id for p in report.problems])
        extra = {
            **self.candidate,
            "documents": self.candidate["documents"]
            + [{"doc_link_id": ID_C, "applied_hash": "h"}],
        }
        self.fails(extra, "documents")
        self.fails(
            self.candidate, "documents", confirmed=self.cs.confirmed_documents[:1]
        )

    def test_duplicate_section_id_rejected(self):
        sections = self.candidate["sections"] + [self.candidate["sections"][0]]
        self.fails({**self.candidate, "sections": sections}, "sections")

    def test_reverse_reference_mismatch_rejected(self):
        dropped = {
            **self.candidate,
            "reverse_references": self.candidate["reverse_references"][1:],
        }
        self.fails(dropped, "reverse_references")
        extra = {
            "target_doc_id": ID_C,
            "target_section_id": None,
            "source_doc_id": ID_A,
            "source_section_id": None,
        }
        added = {
            **self.candidate,
            "reverse_references": self.candidate["reverse_references"] + [extra],
        }
        self.fails(added, "reverse_references")
        duplicated = {
            **self.candidate,
            "reverse_references": self.candidate["reverse_references"]
            + [self.candidate["reverse_references"][0]],
        }
        self.fails(duplicated, "reverse_references")

    def test_reference_from_unknown_source_rejected(self):
        reference = {**self.candidate["references"][0], "source_doc_id": ID_C}
        candidate = {
            **self.candidate,
            "references": self.candidate["references"] + [reference],
        }
        self.fails(candidate, "references")

    def test_last_checks_must_cover_each_document_once(self):
        self.fails({**self.candidate, "last_checks": []}, "last_checks")
        doubled = self.candidate["last_checks"] + [self.candidate["last_checks"][0]]
        self.fails({**self.candidate, "last_checks": doubled}, "last_checks")

    def test_required_field_missing_rejected(self):
        candidate = dict(self.candidate)
        del candidate["last_checks"]
        report = self.fails(candidate)
        self.assertIn("必須フィールド", report.problems[0].cause)

    def test_missing_document_info_rejected(self):
        state_store.document_info_path(self.root, ID_B).unlink()
        report = self.fails(self.candidate, "document_info")
        self.assertEqual(report.problems[0].doc_link_id, ID_B)
        self.assertEqual(report.problems[0].path, "docs/b.md")

    def test_document_info_with_other_hash_rejected(self):
        info = state_store.load_document_info(self.root, ID_A)
        info["content_hash"] = "0" * 64
        state_store.save_document_info(self.root, "test", info)
        self.fails(self.candidate, "document_info")

    def test_validation_does_not_write(self):
        before = self.snapshot()
        self.validate()
        self.assertEqual(self.snapshot(), before)


class PublishTest(Base):
    def test_published_toc_has_sections_hashes_and_last_checks(self):
        result = self.publish()
        loaded = state_store.load_confirmed_toc(self.root, KEY)
        self.assertEqual(loaded["version"], 1)
        self.assertEqual(
            {s["section_id"]: s["content_hash"] for s in loaded["sections"]},
            {
                S1: section_content_hashes(A_TEXT)[0],
                S2: section_content_hashes(A_TEXT)[1],
                S3: section_content_hashes(B_TEXT)[0],
            },
        )
        self.assertEqual(len(loaded["last_checks"]), 2)
        self.assertTrue(result.written)
        self.assertEqual(
            sorted(d["doc_link_id"] for d in loaded["documents"]), [ID_A, ID_B]
        )

    def test_published_toc_gives_no_change_against_same_files(self):
        self.publish()
        result = self.change_set()
        self.assertFalse(result.first_build)
        for change in result.documents:
            self.assertEqual(change.kinds, (), change.doc_link_id)
            self.assertTrue(change.unchanged)
        self.assertEqual(result.sections, ())

    def test_published_toc_gives_no_change_after_republish_with_second_target(self):
        self.publish()
        self.publish(files=["docs/a.md"])
        result = self.change_set(["docs/a.md"])
        self.assertEqual(
            [c.kinds for c in result.documents if c.doc_link_id == ID_A], [()]
        )
        self.assertEqual(result.sections, ())

    def test_failed_publish_keeps_old_toc_and_leaves_no_temp_file(self):
        self.publish()
        old = self.toc_bytes()
        self.write("docs/b.md", B_TEXT + "\n追記\n")
        cs, results = self.inputs()
        infos = self.info_bytes()
        with mock.patch("state_store.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(toc_candidate.CandidateFailure) as caught:
                toc_candidate.build_and_publish(
                    self.root, "test", KEY, SPEC, cs, results, WHEN
                )
        report = caught.exception.report
        self.assertEqual(report.stage, toc_candidate.STAGE_PUBLISH)
        self.assertTrue(report.confirmed_toc_present)
        self.assertEqual(self.toc_bytes(), old)
        # 確定済みの[文書情報]は戻らない（追記後の[内容ハッシュ]のまま）
        self.assertEqual(self.info_bytes(), infos)
        self.assertEqual(
            state_store.load_document_info(self.root, ID_B)["content_hash"],
            document_content_hash(B_TEXT + "\n追記\n"),
        )
        leftovers = list((self.root / ".temp").rglob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_failed_first_publish_creates_no_toc(self):
        cs, results = self.inputs()
        with mock.patch("state_store.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(toc_candidate.CandidateFailure) as caught:
                toc_candidate.build_and_publish(
                    self.root, "test", KEY, SPEC, cs, results, WHEN
                )
        self.assertEqual(caught.exception.report.stage, toc_candidate.STAGE_PUBLISH)
        self.assertFalse(caught.exception.report.confirmed_toc_present)
        self.assertIsNone(self.toc_bytes())

    def test_each_stage_failure_is_distinguished_and_keeps_old_toc(self):
        self.publish()
        old = self.toc_bytes()
        cs, results = self.inputs()

        # 組み立ての失敗
        broken = dict(results)
        del broken[ID_A]
        with self.assertRaises(toc_candidate.CandidateFailure) as caught:
            toc_candidate.build_and_publish(
                self.root, "test", KEY, SPEC, cs, broken, WHEN
            )
        self.assertEqual(caught.exception.report.stage, toc_candidate.STAGE_ASSEMBLY)
        self.assertEqual(self.toc_bytes(), old)

        # 検査の失敗（[文書情報]が無い）
        state_store.document_info_path(self.root, ID_B).unlink()
        with self.assertRaises(toc_candidate.CandidateFailure) as caught:
            toc_candidate.build_and_publish(
                self.root, "test", KEY, SPEC, cs, results, WHEN
            )
        report = caught.exception.report
        self.assertEqual(report.stage, toc_candidate.STAGE_VALIDATION)
        self.assertTrue(report.confirmed_toc_present)
        self.assertEqual(self.toc_bytes(), old)
        self.assertEqual(
            sorted(report.to_dict()), ["confirmed_toc_present", "problems", "stage"]
        )

    def test_publish_rejects_invalid_candidate_and_keeps_old(self):
        self.publish()
        old = self.toc_bytes()
        candidate = state_store.load_confirmed_toc(self.root, KEY)
        del candidate["documents"]
        with self.assertRaises(toc_candidate.CandidateFailure) as caught:
            toc_candidate.publish_candidate(self.root, "test", candidate)
        self.assertEqual(caught.exception.report.stage, toc_candidate.STAGE_PUBLISH)
        self.assertEqual(self.toc_bytes(), old)

    def test_unspecified_key_is_untouched_by_success_and_failure(self):
        self.publish(key=OTHER_KEY)
        other = self.toc_bytes(OTHER_KEY)
        self.publish()
        self.assertEqual(self.toc_bytes(OTHER_KEY), other)
        self.write("docs/b.md", B_TEXT + "\n追記\n")
        cs, results = self.inputs()
        with mock.patch("state_store.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(toc_candidate.CandidateFailure):
                toc_candidate.build_and_publish(
                    self.root, "test", KEY, SPEC, cs, results, WHEN
                )
        self.assertEqual(self.toc_bytes(OTHER_KEY), other)
        self.write("docs/b.md", B_TEXT)

    def test_other_key_toc_is_not_read(self):
        # 他のキーの[確定 ToC]が壊れていても、指定したキーの構築に影響しない
        path = state_store.confirmed_toc_path(self.root, OTHER_KEY)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{", encoding="utf-8")
        self.publish()
        self.assertEqual(path.read_text(encoding="utf-8"), "{")


class ReportTest(unittest.TestCase):
    def test_report_to_dict(self):
        report = toc_candidate.FailureReport(
            stage=toc_candidate.STAGE_PUBLISH,
            problems=(toc_candidate.CandidateProblem("id", "p.md", "f", "原因"),),
            confirmed_toc_present=True,
        )
        self.assertEqual(
            report.to_dict(),
            {
                "stage": "publish",
                "problems": [
                    {"doc_link_id": "id", "path": "p.md", "field": "f", "cause": "原因"}
                ],
                "confirmed_toc_present": True,
            },
        )

    def test_confirmed_toc_present_for_invalid_key_is_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(toc_candidate.confirmed_toc_present(tmp, ""))


if __name__ == "__main__":
    unittest.main()
