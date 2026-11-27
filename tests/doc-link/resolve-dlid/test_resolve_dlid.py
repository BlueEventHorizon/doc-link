import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_SCRIPTS_DIR = (
    PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "resolve-dlid" / "scripts"
)
sys.path.insert(0, str(SKILL_SCRIPTS_DIR))

import resolve_dlid  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))
import state_store  # noqa: E402

DOC_A = "DLID-0123456789ab"
DOC_B = "DLID-abcdefghjkmn"
SEC_1 = "DLID-cdefghjkmnpq"
SEC_2 = "DLID-qrstvwxyz012"
UNKNOWN = "DLID-345678901234"


def doc_text(doc_id, *sections):
    body = "".join(f"\n## {title} {sid}\n\ntext\n" for title, sid in sections)
    return f"---\ndoc_link_id: {doc_id}\n---\n# Top\n{body}"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def save_info(self, doc_id, path, content_hash="doc-hash"):
        state_store.save_document_info(
            self.root,
            "index-docs",
            {
                "doc_link_id": doc_id,
                "path": path,
                "title": "t",
                "purpose": "p",
                "summary": [],
                "tasks": [],
                "keywords": [],
                "content_hash": content_hash,
            },
        )

    def toc_of(self, key, sections):
        """sections は (所属する文書 ID, セクション ID, 見出し, ハッシュ) の並び。"""
        doc_ids = sorted({doc_id for doc_id, *_ in sections})
        return {
            "toc_key": key,
            "version": 1,
            "target_spec": {},
            "documents": [{"doc_link_id": d, "applied_hash": "h"} for d in doc_ids],
            "sections": [
                {
                    "doc_link_id": doc_id,
                    "section_id": sid,
                    "heading": heading,
                    "position": index,
                    "content_hash": content_hash,
                }
                for index, (doc_id, sid, heading, content_hash) in enumerate(sections)
            ],
            "references": [],
            "reverse_references": [],
            "last_checks": [
                {"doc_link_id": d, "result": "unprocessed"} for d in doc_ids
            ],
        }

    def save_toc(self, key, sections):
        state_store.save_confirmed_toc(
            self.root, "index-docs", self.toc_of(key, sections)
        )

    def write_previous_toc(self, key, sections):
        """ひとつ前の保存形式（文書ごとの値を[確定 ToC]のファイルが持つ）で書く。"""
        path = state_store.confirmed_toc_path(self.root, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(state_store.serialize(self.toc_of(key, sections)))

    def snapshot(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }

    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = resolve_dlid.main(["--project-root", str(self.root), *args])
        return code, json.loads(out.getvalue())

    def one(self, dlid):
        code, result = self.run_main(dlid)
        self.assertEqual(code, 0, result)
        self.assertEqual(len(result["results"]), 1)
        return result["results"][0], result

    def basic_state(self):
        self.write("docs/a.md", doc_text(DOC_A, ("Sec One", SEC_1)))
        self.save_info(DOC_A, "docs/a.md", "doc-hash-a")
        self.save_toc("k", [(DOC_A, SEC_1, "Sec One", "sec-hash-1")])


class ResolvedTest(Base):
    def test_document_is_resolved_with_path_and_content_hash(self):
        self.basic_state()
        item, _ = self.one(DOC_A)
        self.assertEqual(
            item,
            {
                "dlid": DOC_A,
                "kind": "document",
                "status": "resolved",
                "path": "docs/a.md",
                "content_hash": "doc-hash-a",
                "content_hash_state": "recorded",
            },
        )

    def test_section_is_resolved_with_heading_anchor_and_hash(self):
        self.basic_state()
        item, _ = self.one(SEC_1)
        self.assertEqual(
            item,
            {
                "dlid": SEC_1,
                "kind": "section",
                "status": "resolved",
                "path": "docs/a.md",
                "heading": f"Sec One {SEC_1}",
                "anchor": f"sec-one-{SEC_1.lower()}",
                "content_hash": "sec-hash-1",
                "content_hash_state": "recorded",
            },
        )

    def test_results_follow_the_input_order_and_dedupe(self):
        self.basic_state()
        code, result = self.run_main(SEC_1, DOC_A, SEC_1, UNKNOWN)
        self.assertEqual(code, 0)
        self.assertEqual(
            [(r["dlid"], r["status"]) for r in result["results"]],
            [(SEC_1, "resolved"), (DOC_A, "resolved"), (UNKNOWN, "no_record")],
        )


class MovedDocumentTest(Base):
    def test_moved_document_is_not_resolved_until_rebuilt(self):
        """AC-031: 移動後の再構築の前は記録されたパスに無い。再構築後は新しいパスで解決される。"""
        self.basic_state()
        (self.root / "docs" / "b").mkdir()
        shutil.move(self.root / "docs/a.md", self.root / "docs/b/a.md")
        for dlid, kind in ((DOC_A, "document"), (SEC_1, "section")):
            with self.subTest(dlid=dlid):
                item, _ = self.one(dlid)
                self.assertEqual(item["status"], "not_at_recorded_path")
                self.assertEqual(item["kind"], kind)
                self.assertEqual(item["recorded_paths"], ["docs/a.md"])
                self.assertNotIn("path", item)

        self.save_info(DOC_A, "docs/b/a.md", "doc-hash-a")
        for dlid in (DOC_A, SEC_1):
            with self.subTest(rebuilt=dlid):
                item, _ = self.one(dlid)
                self.assertEqual(item["status"], "resolved")
                self.assertEqual(item["path"], "docs/b/a.md")

    def test_dlid_mismatch_at_recorded_path(self):
        self.basic_state()
        self.write("docs/a.md", doc_text(DOC_B, ("Other", SEC_2)))
        for dlid in (DOC_A, SEC_1):
            with self.subTest(dlid=dlid):
                item, _ = self.one(dlid)
                self.assertEqual(item["status"], "not_at_recorded_path")

    def test_other_location_is_not_searched(self):
        self.basic_state()
        (self.root / "docs/a.md").unlink()
        self.write("elsewhere/copy.md", doc_text(DOC_A, ("Sec One", SEC_1)))
        for dlid in (DOC_A, SEC_1):
            with self.subTest(dlid=dlid):
                item, _ = self.one(dlid)
                self.assertEqual(item["status"], "not_at_recorded_path")
                self.assertEqual(item["recorded_paths"], ["docs/a.md"])

    def test_unreadable_file_is_not_at_recorded_path(self):
        self.basic_state()
        (self.root / "docs/a.md").write_bytes(b"\xff\xfe\x00bad\n")
        item, _ = self.one(DOC_A)
        self.assertEqual(item["status"], "not_at_recorded_path")
        (self.root / "docs/a.md").unlink()
        (self.root / "docs/a.md").mkdir()  # ディレクトリは読めない
        item, _ = self.one(SEC_1)
        self.assertEqual(item["status"], "not_at_recorded_path")

    def test_path_outside_the_project_root_is_not_read(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "x.md").write_bytes(doc_text(DOC_A).encode("utf-8"))
        project = self.root / "project"
        project.mkdir()
        self.root, saved = project, self.root
        self.save_info(DOC_A, "../outside/x.md")
        item, _ = self.one(DOC_A)
        self.root = saved
        self.assertEqual(item["status"], "not_at_recorded_path")

    def test_symlink_to_a_file_outside_the_project_root_is_read(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "x.md").write_bytes(doc_text(DOC_A).encode("utf-8"))
        project = self.root / "project"
        (project / "docs").mkdir(parents=True)
        (project / "docs" / "x.md").symlink_to(outside / "x.md")
        self.root, saved = project, self.root
        self.save_info(DOC_A, "docs/x.md")
        item, _ = self.one(DOC_A)
        self.root = saved
        self.assertEqual(item["status"], "resolved")
        self.assertEqual(item["path"], "docs/x.md")


class NoRecordTest(Base):
    def test_unrecorded_dlid(self):
        self.basic_state()
        item, _ = self.one(UNKNOWN)
        self.assertEqual(item, {"dlid": UNKNOWN, "kind": None, "status": "no_record"})

    def test_no_state_directory_means_no_record(self):
        item, _ = self.one(DOC_A)
        self.assertEqual(item["status"], "no_record")
        self.assertFalse((self.root / ".doc-link").exists())

    def test_section_whose_documents_have_no_info_is_no_record(self):
        # ひとつ前の保存形式では、[確定 ToC]のファイルだけがあり[文書情報]が無い状態がありうる
        self.write("docs/a.md", doc_text(DOC_A, ("Sec One", SEC_1)))
        self.write_previous_toc("k", [(DOC_A, SEC_1, "Sec One", "h")])
        item, _ = self.one(SEC_1)
        self.assertEqual(item["status"], "no_record")


class ContentHashTest(Base):
    def test_section_hash_differing_between_records(self):
        # 同じ文書の値は[ToC 識別キー]によらず 1 つである。記録が食い違うのは、ひとつ前の保存形式の
        # [確定 ToC]が残っているときだけである
        self.basic_state()
        self.write_previous_toc("k2", [(DOC_A, SEC_1, "Sec One", "other-hash")])
        item, _ = self.one(SEC_1)
        self.assertEqual(item["status"], "resolved")
        self.assertIsNone(item["content_hash"])
        self.assertEqual(item["content_hash_state"], "differs")

    def test_same_section_hash_in_several_records(self):
        self.basic_state()
        self.save_toc("k2", [(DOC_A, SEC_1, "Sec One", "sec-hash-1")])
        item, _ = self.one(SEC_1)
        self.assertEqual(item["content_hash"], "sec-hash-1")
        self.assertEqual(item["content_hash_state"], "recorded")

    def test_section_hash_saved_from_another_key_is_the_one_value(self):
        # 別の[ToC 識別キー]の構築が保存した値が、その文書のただ 1 つの値になる
        self.basic_state()
        self.save_toc("k2", [(DOC_A, SEC_1, "Sec One", "newer-hash")])
        item, _ = self.one(SEC_1)
        self.assertEqual(item["content_hash"], "newer-hash")
        self.assertEqual(item["content_hash_state"], "recorded")

    def test_unavailable_hash(self):
        self.basic_state()
        self.save_toc("k", [(DOC_A, SEC_1, "Sec One", "")])
        self.save_info(DOC_A, "docs/a.md", "")
        for dlid in (DOC_A, SEC_1):
            with self.subTest(dlid=dlid):
                item, _ = self.one(dlid)
                self.assertEqual(item["status"], "resolved")
                self.assertIsNone(item["content_hash"])
                self.assertEqual(item["content_hash_state"], "unavailable")


class MovedSectionCandidatesTest(Base):
    """セクションを別の文書へ移したあと、一部のキーだけを再構築した状態。"""

    def setUp(self):
        super().setUp()
        self.save_info(DOC_A, "docs/a.md")
        self.save_info(DOC_B, "docs/b.md")
        self.save_toc("old", [(DOC_A, SEC_1, "Sec One", "old-hash")])
        self.save_toc("new", [(DOC_B, SEC_1, "Sec One", "new-hash")])

    def test_only_the_matching_candidate_is_resolved(self):
        self.write("docs/a.md", doc_text(DOC_A))
        self.write("docs/b.md", doc_text(DOC_B, ("Sec One", SEC_1)))
        item, _ = self.one(SEC_1)
        self.assertEqual(item["status"], "resolved")
        self.assertEqual(item["path"], "docs/b.md")
        self.assertEqual(item["content_hash"], "new-hash")
        self.assertEqual(item["content_hash_state"], "recorded")

    def test_no_match_lists_all_recorded_paths(self):
        self.write("docs/a.md", doc_text(DOC_A))
        self.write("docs/b.md", doc_text(DOC_B))
        item, _ = self.one(SEC_1)
        self.assertEqual(item["status"], "not_at_recorded_path")
        self.assertEqual(sorted(item["recorded_paths"]), ["docs/a.md", "docs/b.md"])


class FailureTest(Base):
    def test_broken_state_is_a_failure_not_no_record(self):
        self.basic_state()
        for relative in (
            ".doc-link/documents/" + state_store.encode_name(UNKNOWN) + ".json",
            ".doc-link/tocs/broken.json",
        ):
            with self.subTest(path=relative):
                self.write(relative, "{broken")
                before = self.snapshot()
                code, result = self.run_main(UNKNOWN)
                self.assertEqual(code, 1)
                self.assertIn("corrupt", result["errors"][0])
                self.assertIn(Path(relative).name, result["errors"][0])
                self.assertEqual(self.snapshot(), before)
                (self.root / relative).unlink()

    def test_missing_document_info_of_a_toc_document_is_a_failure(self):
        self.basic_state()
        state_store.document_info_path(self.root, DOC_A).unlink()
        code, result = self.run_main(SEC_1)
        self.assertEqual(code, 1)
        self.assertIn("corrupt", result["errors"][0])

    def test_unreadable_state_is_a_failure(self):
        self.basic_state()
        (self.root / ".doc-link" / "tocs" / "dir.json").mkdir()
        code, result = self.run_main(DOC_A)
        self.assertEqual(code, 1)
        self.assertIn("unreadable", result["errors"][0])

    def test_unrecognized_dlid_is_rejected(self):
        self.basic_state()
        for args in (("DLID-short",), (DOC_A, "not-a-dlid"), ("DLID-0123456789AB",)):
            with self.subTest(args=args):
                code, result = self.run_main(*args)
                self.assertEqual(code, 1)
                self.assertTrue(result["errors"])
                self.assertNotIn("results", result)

    def test_no_dlid_is_rejected(self):
        code, result = self.run_main()
        self.assertEqual(code, 1)
        self.assertTrue(result["errors"])

    def test_unknown_option_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                resolve_dlid.main(["--unknown", DOC_A])
        self.assertEqual(caught.exception.code, 2)


class ReadOnlyTest(Base):
    def test_documents_and_state_are_unchanged(self):
        self.basic_state()
        self.write(".doc-link/note.txt", "state")
        (self.root / "docs/gone.md").parent.mkdir(exist_ok=True)
        self.save_info(DOC_B, "docs/gone.md")
        before = self.snapshot()
        code, result = self.run_main(DOC_A, SEC_1, DOC_B, UNKNOWN)
        self.assertEqual(code, 0)
        self.assertEqual(
            [r["status"] for r in result["results"]],
            ["resolved", "resolved", "not_at_recorded_path", "no_record"],
        )
        self.assertEqual(self.snapshot(), before)


@unittest.skipUnless(shutil.which("uv"), "uv が使えない環境では実行しない")
class EntryScriptWithUvTest(Base):
    SCRIPT = SKILL_SCRIPTS_DIR / "resolve_dlid.py"

    def uv_run(self, *args):
        return subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                str(self.SCRIPT),
                *args,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_exits_0_with_json_and_writes_nothing(self):
        self.basic_state()
        before = self.snapshot()
        completed = self.uv_run("--project-root", str(self.root), DOC_A, SEC_1, UNKNOWN)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        results = json.loads(completed.stdout)["results"]
        self.assertEqual(
            [r["status"] for r in results], ["resolved", "resolved", "no_record"]
        )
        self.assertEqual(self.snapshot(), before)

    def test_invalid_dlid_exits_1(self):
        completed = self.uv_run("--project-root", str(self.root), "bad")
        self.assertEqual(completed.returncode, 1)
        self.assertTrue(json.loads(completed.stdout)["errors"])

    def test_invalid_argument_exits_2(self):
        self.assertEqual(self.uv_run("--unknown").returncode, 2)


if __name__ == "__main__":
    unittest.main()
