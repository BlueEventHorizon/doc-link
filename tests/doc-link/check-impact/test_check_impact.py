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
    PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "check-impact" / "scripts"
)
sys.path.insert(0, str(SKILL_SCRIPTS_DIR))

import check_impact  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))
import change_set  # noqa: E402
import state_store  # noqa: E402
import toc_candidate  # noqa: E402
import toc_check  # noqa: E402
from content_hash import document_content_hash, title_value  # noqa: E402
from reference_check import check_document  # noqa: E402
from target_spec import MODE_TARGETS, TargetSpec  # noqa: E402

KEY = "k"
ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
S_A = "DLID-00000000s001"
S_B1 = "DLID-00000000s002"
S_B2 = "DLID-00000000s003"
WHEN = "2026-11-13T00:00:00+00:00"
ARGS = ("--key", KEY, "--paths", "a.md", "b.md")


def title(target, record=None):
    return f"{record} {target}" if record else target


def a_text(doc=None, sec=None):
    return (
        f"---\ndoc_link_id: {ID_A}\n---\n# A {S_A}\n\nbody\n\n"
        f'[b]: b.md "{title(ID_B, doc)}"\n'
        f'[b2]: b.md "{title(S_B2, sec)}"\n'
    )


def b_text(intro="intro", part="part"):
    return f"---\ndoc_link_id: {ID_B}\n---\n# B1 {S_B1}\n\n{intro}\n\n# B2 {S_B2}\n\n{part}\n"


class CheckImpactTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def build(self, a=None, b=None, extra_paths=()):
        """[文書情報]と[確定 ToC]を、index-docs が確定した状態として保存する。"""
        files = {
            "a.md": (ID_A, a if a is not None else a_text()),
            "b.md": (ID_B, b if b is not None else b_text()),
        }
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
        paths = [*files, *extra_paths]
        spec = TargetSpec(mode=MODE_TARGETS, key=KEY, paths=tuple(paths))
        cs = change_set.build_change_set(self.root, KEY, paths)
        results = {
            item.doc_link_id: check_document(self.root, item.path, checked_at=WHEN)
            for item in cs.confirmed_documents
        }
        toc_candidate.build_and_publish(self.root, "test", KEY, spec, cs, results, WHEN)
        self.spec = spec

    def hashes(self):
        """title に書く値（[確定 ToC]の完全なハッシュの先頭 12 桁）。"""
        toc = state_store.load_confirmed_toc(self.root, KEY)
        return (
            {
                e["doc_link_id"]: title_value(e["applied_hash"])
                for e in toc["documents"]
            },
            {e["section_id"]: title_value(e["content_hash"]) for e in toc["sections"]},
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
            code = check_impact.main(["--project-root", str(self.root), *args])
        return code, json.loads(out.getvalue())

    @staticmethod
    def pairs(result):
        return [
            (d["doc_link_id"], r["source_doc_id"], r["target_dlid"], r["recorded_hash"])
            for d in result["changed_documents"]
            for r in d["referrers"]
        ]


class ImpactResultTest(CheckImpactTestBase):
    def test_returns_changed_documents_with_referrers_and_scope(self):
        self.build()
        docs, secs = self.hashes()
        code, result = self.run_main(*ARGS)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "up_to_date")
        (changed,) = result["changed_documents"]
        self.assertEqual((changed["doc_link_id"], changed["path"]), (ID_B, "b.md"))
        first, second = changed["referrers"]
        self.assertEqual(first["source_path"], "a.md")
        self.assertEqual(first["line"], 8)
        self.assertEqual(first["definition"], f'[b]: b.md "{ID_B}"')
        self.assertIsNone(first["recorded_hash"])
        self.assertEqual(first["current_hash"], docs[ID_B])
        self.assertEqual(second["target_kind"], "section")
        self.assertEqual(second["current_hash"], secs[S_B2])
        self.assertEqual(result["scope"]["toc_key"], KEY)
        self.assertEqual(result["scope"]["toc_version"], 1)
        self.assertEqual(result["scope"]["scanned_documents"], ["a.md"])
        self.assertEqual(result["scope"]["target"]["key"], KEY)
        self.assertTrue(result["scope"]["checked_at"])

    def test_empty_result_after_the_records_are_rewritten(self):
        self.build()
        docs, secs = self.hashes()
        self.write("a.md", a_text(doc=docs[ID_B], sec=secs[S_B2]))
        check = toc_check.check_toc(self.root, KEY, self.spec)
        self.assertEqual(check.status, toc_check.STATUS_UP_TO_DATE)
        code, result = self.run_main(*ARGS)
        self.assertEqual(code, 0)
        self.assertEqual(result["changed_documents"], [])
        self.assertEqual(result["scope"]["scanned_documents"], ["a.md"])
        self.assertEqual(result["guidance"], [])

    def test_mutual_references_settle_after_one_rewrite(self):
        b = b_text() + f'\n[a]: a.md "{ID_A}"\n'
        self.build(b=b)
        code, result = self.run_main(*ARGS)
        self.assertEqual(code, 0)
        found = {(src, target) for _, src, target, _ in self.pairs(result)}
        self.assertEqual(found, {(ID_A, ID_B), (ID_A, S_B2), (ID_B, ID_A)})
        by_target = {
            r["target_dlid"]: r["current_hash"]
            for d in result["changed_documents"]
            for r in d["referrers"]
        }
        self.write("a.md", a_text(doc=by_target[ID_B], sec=by_target[S_B2]))
        self.write(
            "b.md",
            b_text() + f'\n[a]: a.md "{by_target[ID_A]} {ID_A}"\n',
        )
        code, again = self.run_main(*ARGS)
        self.assertEqual(code, 0)
        self.assertEqual(again["status"], "up_to_date")
        self.assertEqual(again["changed_documents"], [])

    def test_same_references_are_returned_every_time(self):
        self.build()
        _, first = self.run_main(*ARGS)
        _, second = self.run_main(*ARGS)
        self.assertEqual(first["changed_documents"], second["changed_documents"])

    def test_document_without_id_is_reported_as_excluded(self):
        self.write("c.md", "# C\n\nno document id\n")
        self.build(extra_paths=("c.md",))
        code, result = self.run_main("--key", KEY, "--paths", "a.md", "b.md", "c.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "up_to_date")
        (excluded,) = result["excluded"]
        self.assertIn("c.md", json.dumps(excluded))
        self.assertTrue(result["changed_documents"])


class StaleTocTest(CheckImpactTestBase):
    def test_stale_result_keeps_the_excluded_documents(self):
        self.write("c.md", "# C\n\nno document id\n")
        self.build(extra_paths=("c.md",))
        self.write("b.md", b_text(intro="changed"))
        code, result = self.run_main("--key", KEY, "--paths", "a.md", "b.md", "c.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "rebuild_needed")
        self.assertNotIn("changed_documents", result)
        self.assertEqual(len(result["excluded"]), 1)

    def test_changed_document_returns_the_check_toc_result_without_candidates(self):
        self.build()
        self.write("b.md", b_text(intro="changed"))
        code, result = self.run_main(*ARGS)
        expected = toc_check.check_toc(self.root, KEY, self.spec).to_dict()
        self.assertEqual(code, 0)
        self.assertNotIn("changed_documents", result)
        self.assertEqual(result["status"], "rebuild_needed")
        self.assertEqual(result, expected)

    def test_not_built_returns_the_check_toc_result(self):
        self.write("a.md", a_text())
        code, result = self.run_main(*ARGS)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "not_built")
        self.assertNotIn("changed_documents", result)

    def test_record_only_rewrite_is_not_stale(self):
        self.build()
        docs, secs = self.hashes()
        self.write("a.md", a_text(doc=docs[ID_B], sec=secs[S_B2]))
        _, result = self.run_main(*ARGS)
        self.assertEqual(result["status"], "up_to_date")


class ReadOnlyTest(CheckImpactTestBase):
    def test_documents_and_state_are_unchanged(self):
        self.build()
        self.write(".doc-link/note.txt", "state")
        before = self.snapshot()
        self.run_main(*ARGS)
        self.write("b.md", b_text(intro="changed"))
        stale = self.snapshot()
        self.run_main(*ARGS)
        self.run_main("--key", "unbuilt", "--paths", "a.md")
        self.assertEqual(self.snapshot(), stale)
        self.assertNotEqual(before, stale)


class FailureTest(CheckImpactTestBase):
    def test_conflicting_target_arguments_exit_1(self):
        self.build()
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
                self.assertNotIn("changed_documents", result)
        self.assertEqual(self.snapshot(), before)

    def test_undeterminable_is_an_error_without_candidates(self):
        self.build()
        (self.root / "b.md").write_bytes(b"\xff\xfe\x00bad\n")
        before = self.snapshot()
        code, result = self.run_main(*ARGS)
        self.assertEqual(code, 1)
        self.assertNotIn("changed_documents", result)
        self.assertNotIn("status", result)
        self.assertTrue(any("b.md" in line for line in result["errors"]), result)
        self.assertEqual(self.snapshot(), before)

    def test_broken_confirmed_toc_is_an_error(self):
        self.build()
        state_store.confirmed_toc_path(self.root, KEY).write_bytes(b"{broken")
        code, result = self.run_main(*ARGS)
        self.assertEqual(code, 1)
        self.assertNotIn("changed_documents", result)

    def test_missing_document_info_is_an_error_without_candidates(self):
        self.build()
        state_store.document_info_path(self.root, ID_A).unlink()
        before = self.snapshot()
        code, result = self.run_main(*ARGS)
        self.assertEqual(code, 1)
        self.assertNotIn("changed_documents", result)
        self.assertTrue(result["errors"])
        self.assertEqual(self.snapshot(), before)

    def test_unknown_argument_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                check_impact.main(["--unknown"])
        self.assertEqual(caught.exception.code, 2)


@unittest.skipUnless(shutil.which("uv"), "uv が使えない環境では実行しない")
class EntryScriptWithUvTest(CheckImpactTestBase):
    SCRIPT = SKILL_SCRIPTS_DIR / "check_impact.py"

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

    def test_exits_0_with_json_when_candidates_exist(self):
        self.build()
        before = self.snapshot()
        completed = self.uv_run("--project-root", str(self.root), *ARGS)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "up_to_date")
        self.assertEqual(len(result["changed_documents"]), 1)
        self.assertEqual(self.snapshot(), before)

    def test_rejected_target_exits_1(self):
        completed = self.uv_run("--project-root", str(self.root), "--paths", "a.md")
        self.assertEqual(completed.returncode, 1)
        self.assertTrue(json.loads(completed.stdout)["errors"])

    def test_invalid_argument_exits_2(self):
        self.assertEqual(self.uv_run("--unknown").returncode, 2)


if __name__ == "__main__":
    unittest.main()
