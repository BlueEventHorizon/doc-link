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
    PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "check-dlid" / "scripts"
)
sys.path.insert(0, str(SKILL_SCRIPTS_DIR))

import check_dlid  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))
import state_store  # noqa: E402

ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
ID_C = "DLID-cdefghjkmnpq"
DOC = f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n\nbody\n"


class CheckTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def record(self, key, doc_id, path, section_ids):
        """管理状態に、文書とその[セクション ID]を記録する（`state_store` の検証を通る最小の内容）。"""
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
        state_store.save_confirmed_toc(
            self.root,
            "embed-dlid",
            {
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
                    for index, sid in enumerate(section_ids)
                ],
                "references": [],
                "reverse_references": [],
                "last_checks": [
                    {"doc_link_id": doc_id, "checked_at": None, "result": "unprocessed"}
                ],
            },
        )

    def snapshot(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }

    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_dlid.main(["--project-root", str(self.root), *args])
        return code, json.loads(out.getvalue())


class DetectionTest(CheckTestBase):
    def test_missing_document_and_section_ids(self):
        self.write("a.md", "# T\n\n## U\n")
        self.write("b.md", f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n")
        code, result = self.run_main("--key", "k", "--paths", "a.md", "b.md")
        self.assertEqual(code, 0)
        self.assertFalse(result["clean"])
        self.assertEqual(
            result["missing_document_id"],
            [{"path": "a.md", "unclosed_frontmatter": False}],
        )
        self.assertEqual(
            result["missing_section_id"],
            [
                {"path": "a.md", "line": 1, "heading": "T"},
                {"path": "a.md", "line": 3, "heading": "U"},
            ],
        )
        self.assertEqual(result["duplicates"], [])
        self.assertEqual(
            result["counts"],
            {"missing_document_id": 1, "missing_section_id": 2, "duplicates": 0},
        )

    def test_unrecognized_doc_link_id_is_missing_document_id(self):
        for value in ("", "null", "[a, b]", "not-a-dlid", "DLID-short"):
            with self.subTest(value=value):
                self.write("a.md", f"---\ndoc_link_id: {value}\n---\n# T {ID_B}\n")
                _, result = self.run_main("--key", "k", "--paths", "a.md")
                self.assertEqual(
                    [d["path"] for d in result["missing_document_id"]], ["a.md"]
                )
                self.assertEqual(result["missing_section_id"], [])
                self.assertEqual(result["duplicates"], [])

    def test_document_and_section_duplicates_carry_all_paths(self):
        self.write("orig.md", DOC)
        self.write("copy.md", DOC)
        code, result = self.run_main("--key", "k", "--paths", "orig.md", "copy.md")
        self.assertEqual(code, 0)
        by_dlid = {d["dlid"]: d for d in result["duplicates"]}
        self.assertEqual(set(by_dlid), {ID_A, ID_B})
        self.assertEqual(
            [
                (loc["path"], loc["kind"], loc["line"])
                for loc in by_dlid[ID_A]["locations"]
            ],
            [("copy.md", "document", None), ("orig.md", "document", None)],
        )
        self.assertEqual(
            [
                (loc["path"], loc["kind"], loc["line"], loc["heading"])
                for loc in by_dlid[ID_B]["locations"]
            ],
            [
                ("copy.md", "section", 4, f"T {ID_B}"),
                ("orig.md", "section", 4, f"T {ID_B}"),
            ],
        )
        self.assertEqual(result["counts"]["duplicates"], 2)
        self.assertEqual(result["missing_document_id"], [])

    def test_section_duplicate_within_the_same_document(self):
        self.write(
            "a.md", f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n\n## U {ID_B}\n"
        )
        _, result = self.run_main("--key", "k", "--paths", "a.md")
        self.assertEqual(len(result["duplicates"]), 1)
        locations = result["duplicates"][0]["locations"]
        self.assertEqual(
            [(l["path"], l["line"]) for l in locations], [("a.md", 4), ("a.md", 6)]
        )

    def test_candidates_come_from_the_recorded_paths(self):
        self.write("orig.md", DOC)
        self.write("copy.md", DOC)
        self.record("k", ID_A, "orig.md", [ID_B])
        _, result = self.run_main("--key", "k", "--paths", "orig.md", "copy.md")
        by_dlid = {d["dlid"]: d for d in result["duplicates"]}
        for duplicate in by_dlid.values():
            self.assertEqual(duplicate["recorded_paths"], ["orig.md"])
            self.assertEqual([c["path"] for c in duplicate["candidates"]], ["orig.md"])
        self.assertEqual(len(by_dlid[ID_A]["locations"]), 2)

    def test_unclosed_frontmatter_is_noted(self):
        self.write("a.md", "---\ntitle: x\n# T\n")
        _, result = self.run_main("--key", "k", "--paths", "a.md")
        self.assertEqual(
            result["missing_document_id"],
            [{"path": "a.md", "unclosed_frontmatter": True}],
        )
        self.assertTrue(
            any("frontmatter" in line for line in result["guidance"]), result
        )

    def test_clean_result_exits_0(self):
        self.write("a.md", DOC)
        code, result = self.run_main("--key", "k", "--paths", "a.md")
        self.assertEqual(code, 0)
        self.assertTrue(result["clean"])
        self.assertEqual(result["missing_document_id"], [])
        self.assertEqual(result["missing_section_id"], [])
        self.assertEqual(result["duplicates"], [])
        self.assertEqual(result["guidance"], [])

    def test_findings_still_exit_0_and_guide_to_embed_dlid(self):
        self.write("a.md", "# T\n")
        code, result = self.run_main("--key", "k", "--paths", "a.md")
        self.assertEqual(code, 0)
        self.assertTrue(any("embed-dlid" in line for line in result["guidance"]))

    def test_duplicates_guide_to_origin_confirmation(self):
        self.write("orig.md", DOC)
        self.write("copy.md", DOC)
        _, result = self.run_main("--key", "k", "--paths", "orig.md", "copy.md")
        self.assertTrue(any("原本" in line for line in result["guidance"]))

    def test_missing_target_is_reported_and_processing_continues(self):
        self.write("a.md", "# T\n")
        code, result = self.run_main("--key", "k", "--paths", "a.md", "nope.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["problems"], [{"path": "nope.md", "reason": "missing"}])
        self.assertEqual([d["path"] for d in result["missing_document_id"]], ["a.md"])

    def test_all_mode_without_arguments(self):
        self.write("docs/a.md", "# T\n")
        code, result = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(
            [d["path"] for d in result["missing_document_id"]], ["docs/a.md"]
        )


class ReadOnlyTest(CheckTestBase):
    def test_documents_and_state_are_unchanged(self):
        self.write("a.md", "# T\n")
        self.write("orig.md", DOC)
        self.write("copy.md", DOC)
        self.write(".doc-link/note.txt", "state")
        before = self.snapshot()
        self.run_main("--key", "k", "--paths", "a.md", "orig.md", "copy.md")
        self.assertEqual(self.snapshot(), before)

    def test_no_state_directory_is_created(self):
        self.write("a.md", "# T\n")
        self.run_main("--key", "k", "--paths", "a.md")
        self.assertFalse((self.root / ".doc-link").exists())


class FailureTest(CheckTestBase):
    def test_conflicting_target_arguments_exit_1(self):
        self.write("a.md", "# T\n")
        before = self.snapshot()
        for args in (
            ("--paths", "a.md"),
            ("--key", "all", "--paths", "a.md"),
            ("--key", "k"),
            ("--key", "k", "--all", "--paths", "a.md"),
        ):
            with self.subTest(args=args):
                code, result = self.run_main(*args)
                self.assertEqual(code, 1)
                self.assertTrue(result["errors"])
        self.assertEqual(self.snapshot(), before)

    def test_unreadable_document_exits_1(self):
        self.write("a.md", "# T\n")
        (self.root / "bad.md").write_bytes(b"\xff\xfe\x00bad\n")
        code, result = self.run_main("--key", "k", "--paths", "a.md", "bad.md")
        self.assertEqual(code, 1)
        self.assertIn("bad.md", result["errors"][0])

    def test_broken_management_state_exits_1(self):
        self.write("a.md", "# T\n")
        self.write(".doc-link/tocs/k.json", "{broken")
        before = self.snapshot()
        code, result = self.run_main("--key", "k", "--paths", "a.md")
        self.assertEqual(code, 1, result)
        self.assertTrue(result["errors"])
        self.assertEqual(self.snapshot(), before)

    def test_unknown_argument_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                check_dlid.main(["--unknown"])
        self.assertEqual(caught.exception.code, 2)


@unittest.skipUnless(shutil.which("uv"), "uv が使えない環境では実行しない")
class EntryScriptWithUvTest(CheckTestBase):
    SCRIPT = SKILL_SCRIPTS_DIR / "check_dlid.py"

    def uv_run(self, *args):
        return subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                "--exclude-newer",
                "3 days",
                str(self.SCRIPT),
                *args,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_exits_0_with_json_when_findings_exist(self):
        self.write("a.md", "# T\n")
        completed = self.uv_run(
            "--project-root", str(self.root), "--key", "k", "--paths", "a.md"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(json.loads(completed.stdout)["clean"])
        self.assertEqual(self.snapshot(), {"a.md": b"# T\n"})

    def test_rejected_target_exits_1(self):
        completed = self.uv_run("--project-root", str(self.root), "--paths", "a.md")
        self.assertEqual(completed.returncode, 1)
        self.assertTrue(json.loads(completed.stdout)["errors"])

    def test_invalid_argument_exits_2(self):
        self.assertEqual(self.uv_run("--unknown").returncode, 2)


if __name__ == "__main__":
    unittest.main()
