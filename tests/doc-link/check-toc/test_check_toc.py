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
    PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "check-toc" / "scripts"
)
sys.path.insert(0, str(SKILL_SCRIPTS_DIR))

import check_toc  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))
import change_set  # noqa: E402
import state_store  # noqa: E402
import toc_candidate  # noqa: E402
from content_hash import document_content_hash  # noqa: E402
from reference_check import check_document  # noqa: E402
from target_spec import MODE_TARGETS, TargetSpec  # noqa: E402

KEY = "k"
ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
WHEN = "2026-11-13T00:00:00+00:00"
A_TEXT = f"---\ndoc_link_id: {ID_A}\n---\n# A DLID-00000000s001\n\nbody\n"
B_TEXT = f"---\ndoc_link_id: {ID_B}\n---\n# B DLID-00000000s002\n"


class CheckTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def build(self, key=KEY, paths=("a.md", "b.md")):
        """[文書情報]と[確定 ToC]を、index-docs が確定した状態として保存する。"""
        self.write("a.md", A_TEXT)
        self.write("b.md", B_TEXT)
        for path, doc_id in (("a.md", ID_A), ("b.md", ID_B)):
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
                    "content_hash": document_content_hash(
                        (self.root / path).read_text(encoding="utf-8")
                    ),
                },
            )
        spec = TargetSpec(mode=MODE_TARGETS, key=key, paths=tuple(paths))
        cs = change_set.build_change_set(self.root, key, list(paths))
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

    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_toc.main(["--project-root", str(self.root), *args])
        return code, json.loads(out.getvalue())


class StatusTest(CheckTestBase):
    ARGS = ("--key", KEY, "--paths", "a.md", "b.md")

    def test_not_built_exits_0(self):
        self.write("a.md", A_TEXT)
        code, result = self.run_main(*self.ARGS)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "not_built")

    def test_up_to_date_exits_0(self):
        self.build()
        code, result = self.run_main(*self.ARGS)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "up_to_date")
        self.assertEqual(result["documents"], [])

    def test_rebuild_needed_exits_0_with_list_and_scale(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        code, result = self.run_main(*self.ARGS)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "rebuild_needed")
        self.assertEqual(
            [(d["doc_link_id"], d["kinds"]) for d in result["documents"]],
            [(ID_A, ["content_changed"])],
        )
        self.assertEqual(result["scale"]["content_changed"], 1)
        self.assertEqual(result["scale"]["ai_generation"], 1)

    def test_given_spec_takes_priority_over_the_saved_one(self):
        self.build()
        self.write("c.md", f"---\ndoc_link_id: DLID-pqrstvwxyz01\n---\n# C\n")
        code, result = self.run_main("--key", KEY, "--paths", "a.md", "b.md", "c.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "rebuild_needed")
        self.assertEqual(result["target_spec_source"], "given")
        self.assertEqual(result["scale"]["new"], 1)

    def test_all_mode_without_arguments_uses_the_reserved_key(self):
        code, result = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "not_built")
        self.assertEqual(result["toc_key"], "all")

    def test_different_spec_needs_a_rebuild(self):
        self.build()
        self.write("c.md", "# No id\n")
        code, result = self.run_main("--key", KEY, "--paths", "a.md", "b.md", "c.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "rebuild_needed")
        self.assertTrue(result["target_spec_changed"])
        self.assertEqual(result["saved_target_spec"]["paths"], ["a.md", "b.md"])


class ReadOnlyTest(CheckTestBase):
    def test_documents_and_state_are_unchanged(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        self.write(".doc-link/note.txt", "state")
        before = self.snapshot()
        self.run_main("--key", KEY, "--paths", "a.md", "b.md")
        self.run_main("--key", "unbuilt", "--paths", "a.md")
        self.assertEqual(self.snapshot(), before)


class FailureTest(CheckTestBase):
    def test_conflicting_target_arguments_exit_1(self):
        self.write("a.md", A_TEXT)
        before = self.snapshot()
        for args in (
            ("--paths", "a.md"),
            ("--key", "all", "--paths", "a.md"),
            ("--key", KEY),
            ("--key", KEY, "--all", "--paths", "a.md"),
        ):
            with self.subTest(args=args):
                code, result = self.run_main(*args)
                self.assertEqual(code, 1)
                self.assertTrue(result["errors"])
        self.assertEqual(self.snapshot(), before)

    def test_undeterminable_is_an_error_not_a_result(self):
        self.build()
        (self.root / "b.md").write_bytes(b"\xff\xfe\x00bad\n")
        before = self.snapshot()
        code, result = self.run_main("--key", KEY, "--paths", "a.md", "b.md")
        self.assertEqual(code, 1)
        self.assertNotIn("status", result)
        self.assertTrue(any("b.md" in line for line in result["errors"]), result)
        self.assertEqual(self.snapshot(), before)

    def test_broken_confirmed_toc_is_an_error(self):
        self.build()
        state_store.confirmed_toc_path(self.root, KEY).write_bytes(b"{broken")
        code, result = self.run_main("--key", KEY, "--paths", "a.md", "b.md")
        self.assertEqual(code, 1)
        self.assertTrue(result["errors"])

    def test_unknown_argument_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                check_toc.main(["--unknown"])
        self.assertEqual(caught.exception.code, 2)


@unittest.skipUnless(shutil.which("uv"), "uv が使えない環境では実行しない")
class EntryScriptWithUvTest(CheckTestBase):
    SCRIPT = SKILL_SCRIPTS_DIR / "check_toc.py"

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

    def test_exits_0_with_json_when_rebuild_is_needed(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        before = self.snapshot()
        completed = self.uv_run(
            "--project-root",
            str(self.root),
            "--key",
            KEY,
            "--paths",
            "a.md",
            "b.md",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "rebuild_needed")
        self.assertEqual(self.snapshot(), before)

    def test_rejected_target_exits_1(self):
        completed = self.uv_run("--project-root", str(self.root), "--paths", "a.md")
        self.assertEqual(completed.returncode, 1)
        self.assertTrue(json.loads(completed.stdout)["errors"])

    def test_invalid_argument_exits_2(self):
        self.assertEqual(self.uv_run("--unknown").returncode, 2)


if __name__ == "__main__":
    unittest.main()
