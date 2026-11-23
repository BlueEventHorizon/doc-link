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
    PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "query-docs" / "scripts"
)
sys.path.insert(0, str(SKILL_SCRIPTS_DIR))

import query_docs  # noqa: E402

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
SEC_A = "DLID-00000000s001"
SEC_B = "DLID-00000000s002"
WHEN = "2026-11-13T00:00:00+00:00"
A_TEXT = f"---\ndoc_link_id: {ID_A}\n---\n# A {SEC_A}\n\nbody\n"
B_TEXT = f"---\ndoc_link_id: {ID_B}\n---\n# B {SEC_B}\n"
TASK = "検索のタスク"
TARGET = ("--key", KEY, "--paths", "a.md", "b.md")


class QueryTestBase(unittest.TestCase):
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
                    "title": f"title {path}",
                    "purpose": "p",
                    "summary": ["s"],
                    "tasks": ["t"],
                    "keywords": ["k"],
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
            if p.is_file() and p.relative_to(self.root).parts[0] != ".temp"
        }

    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = query_docs.main(
                [args[0], "--project-root", str(self.root), *args[1:]]
            )
        return code, json.loads(out.getvalue())

    def prepare(self, *extra):
        return self.run_main("prepare", "--task", TASK, *TARGET, *extra)


class PrepareOutcomeTest(QueryTestBase):
    def test_not_built_returns_initial_build_and_exits_0(self):
        self.write("a.md", A_TEXT)
        code, result = self.prepare()
        self.assertEqual(code, 0)
        self.assertEqual(result["action"], "initial_build_required")

    def test_up_to_date_fixes_current_version(self):
        self.build()
        code, result = self.prepare()
        self.assertEqual(code, 0)
        self.assertEqual(result["action"], "invoke_query_worker")
        self.assertEqual(result["freshness"], "current")
        self.assertEqual(
            result["toc_version"],
            state_store.load_confirmed_toc(self.root, KEY)["version"],
        )

    def test_rebuild_needed_returns_scale_and_two_options(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        self.write("c.md", "---\ndoc_link_id: DLID-pqrstvwxyz01\n---\n# C\n")
        code, result = self.run_main(
            "prepare", "--task", TASK, "--key", KEY, "--paths", "a.md", "b.md", "c.md"
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["action"], "confirm_rebuild")
        self.assertNotIn("search_id", result)
        scale = result["scale"]
        self.assertEqual(scale["content_changed"], 1)
        self.assertEqual(scale["new"], 1)
        for name in (
            "departed",
            "path_changed",
            "missing_id",
            "duplicate_id",
            "ai_generation",
        ):
            self.assertIn(name, scale)
        self.assertEqual(
            [o["choice"] for o in result["options"]], ["rebuild", "existing"]
        )
        # D-061: 標準出力は件数と規模までで、変更のある文書・セクションの全件は明細ファイルにある
        for name in ("documents", "sections", "excluded", "excluded_in_toc"):
            self.assertNotIn(name, result)
        self.assertEqual(result["counts"]["content_changed"], 1)
        path = Path(result["detail_path"])
        self.assertEqual(
            path,
            self.root / ".temp" / "doc-link" / "query-docs" / f"detail-{KEY}.json",
        )
        detail = json.loads(path.read_bytes().decode("utf-8"))
        self.assertEqual(len(detail["documents"]), 2)

    def test_undeterminable_is_a_failure_without_old_version_option(self):
        self.build()
        (self.root / "b.md").write_bytes(b"\xff\xfe\x00bad\n")
        before = self.snapshot()
        for extra in ((), ("--choice", "existing")):
            with self.subTest(extra=extra):
                code, result = self.prepare(*extra)
                self.assertEqual(code, 1)
                self.assertNotIn("options", result)
                self.assertNotIn("search_id", result)
                self.assertTrue(
                    any("b.md" in line for line in result["errors"]), result
                )
        self.assertEqual(self.snapshot(), before)


class ChoiceTest(QueryTestBase):
    def test_existing_choice_uses_old_version_and_marks_stale(self):
        self.build()
        old_version = state_store.load_confirmed_toc(self.root, KEY)["version"]
        self.write("a.md", A_TEXT + "more\n")
        before = self.snapshot()
        code, result = self.prepare("--choice", "existing")
        self.assertEqual(code, 0)
        self.assertEqual(result["action"], "invoke_query_worker")
        self.assertEqual(result["freshness"], "possibly_stale")
        self.assertEqual(result["toc_version"], old_version)
        sid = result["search_id"]
        self.run_main(
            "submit-item", "--search-id", sid, "--doc-id", ID_A, "--reason", "r"
        )
        self.run_main("submit-end", "--search-id", sid, "--exit-value", "0")
        code, found = self.run_main("collect", "--search-id", sid)
        self.assertEqual(code, 0)
        self.assertEqual(found["toc_version"], old_version)
        self.assertEqual(found["freshness"], "possibly_stale")
        self.assertIn("反映していない可能性", found["freshness_notice"])
        self.assertEqual(self.snapshot(), before)

    def test_rebuild_choice_after_rebuild_uses_new_version(self):
        self.build()  # index-docs による再構築の後の状態
        code, result = self.prepare("--choice", "rebuild")
        self.assertEqual(code, 0)
        self.assertEqual(result["freshness"], "current")

    def test_rebuild_choice_still_mismatching_is_an_error(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        code, result = self.prepare("--choice", "rebuild")
        self.assertEqual(code, 1)
        self.assertNotIn("search_id", result)

    def test_default_key_uses_the_saved_spec(self):
        self.build()
        code, result = self.run_main("prepare", "--task", TASK, "--key", KEY)
        self.assertEqual(code, 0)
        self.assertEqual(result["action"], "invoke_query_worker")

    def test_reserved_key_all_is_rejected_without_target_arguments(self):
        self.build()
        code, result = self.run_main("prepare", "--task", TASK, "--key", "all")
        self.assertEqual(code, 1)
        self.assertNotIn("search_id", result)
        self.assertTrue(any("予約語" in error for error in result["errors"]))


class ExchangeTest(QueryTestBase):
    def start(self):
        self.build()
        return self.prepare()[1]["search_id"]

    def test_full_flow_and_cleanup(self):
        sid = self.start()
        code, path = self.run_main("request-path", "--search-id", sid)
        self.assertEqual(code, 0)
        self.assertEqual(list(path), ["path"])
        request = json.loads(Path(path["path"]).read_text("utf-8"))
        self.assertEqual(request["task"], TASK)
        self.run_main(
            "submit-item",
            "--search-id",
            sid,
            "--doc-id",
            ID_A,
            "--reason",
            "理由",
            "--section-id",
            SEC_A,
        )
        self.run_main("submit-end", "--search-id", sid, "--exit-value", "0")
        code, found = self.run_main("collect", "--search-id", sid)
        self.assertEqual(code, 0)
        self.assertEqual(found["documents"][0]["recorded_path"], "a.md")
        self.assertEqual(found["documents"][0]["sections"][0]["heading"], "A")
        self.assertEqual(found["freshness"], "current")
        directory = self.root / ".temp" / "doc-link" / "query-docs"
        self.assertEqual(list(directory.iterdir()) if directory.is_dir() else [], [])

    def test_unknown_id_exits_3_and_cleans_up(self):
        sid = self.start()
        self.run_main(
            "submit-item",
            "--search-id",
            sid,
            "--doc-id",
            "DLID-zzzzzzzzzzzz",
            "--reason",
            "r",
        )
        self.run_main("submit-end", "--search-id", sid, "--exit-value", "0")
        code, result = self.run_main("collect", "--search-id", sid)
        self.assertEqual(code, 3)
        self.assertTrue(result["errors"])
        self.assertNotIn("documents", result)
        directory = self.root / ".temp" / "doc-link" / "query-docs"
        self.assertEqual(list(directory.iterdir()), [])

    def test_missing_exit_value_exits_3(self):
        sid = self.start()
        code, _ = self.run_main("collect", "--search-id", sid)
        self.assertEqual(code, 3)

    def test_explicit_cleanup_and_unknown_id(self):
        sid = self.start()
        code, result = self.run_main("cleanup", "--search-id", sid)
        self.assertEqual(code, 0)
        self.assertEqual(result["removed"], 3)
        code, _ = self.run_main("request-path", "--search-id", sid)
        self.assertEqual(code, 1)

    def test_state_and_documents_are_unchanged(self):
        sid = self.start()
        before = self.snapshot()
        self.run_main(
            "submit-item", "--search-id", sid, "--doc-id", ID_B, "--reason", "r"
        )
        self.run_main("submit-end", "--search-id", sid, "--exit-value", "0")
        self.run_main("collect", "--search-id", sid)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_argument_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                query_docs.main(["prepare", "--unknown"])
        self.assertEqual(caught.exception.code, 2)


@unittest.skipUnless(shutil.which("uv"), "uv が使えない環境では実行しない")
class EntryScriptWithUvTest(QueryTestBase):
    SCRIPT = SKILL_SCRIPTS_DIR / "query_docs.py"

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

    def test_prepare_and_collect_through_uv(self):
        self.build()
        before = self.snapshot()
        completed = self.uv_run(
            "prepare", "--project-root", str(self.root), "--task", TASK, *TARGET
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        sid = json.loads(completed.stdout)["search_id"]
        base = ("--project-root", str(self.root), "--search-id", sid)
        self.assertEqual(self.uv_run("request-path", *base).returncode, 0)
        self.assertEqual(
            self.uv_run(
                "submit-item", *base, "--doc-id", ID_A, "--reason", "r"
            ).returncode,
            0,
        )
        self.assertEqual(
            self.uv_run("submit-end", *base, "--exit-value", "0").returncode, 0
        )
        done = self.uv_run("collect", *base)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["documents"][0]["doc_link_id"], ID_A)
        self.assertEqual(self.snapshot(), before)

    def test_failed_search_exits_3(self):
        self.build()
        sid = json.loads(
            self.uv_run(
                "prepare", "--project-root", str(self.root), "--task", TASK, *TARGET
            ).stdout
        )["search_id"]
        completed = self.uv_run(
            "collect", "--project-root", str(self.root), "--search-id", sid
        )
        self.assertEqual(completed.returncode, 3)

    def test_invalid_argument_exits_2(self):
        self.assertEqual(self.uv_run("prepare", "--unknown").returncode, 2)


if __name__ == "__main__":
    unittest.main()
