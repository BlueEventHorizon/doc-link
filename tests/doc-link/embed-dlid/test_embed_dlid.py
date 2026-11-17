import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_SCRIPTS_DIR = (
    PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "embed-dlid" / "scripts"
)
sys.path.insert(0, str(SKILL_SCRIPTS_DIR))

import embed_dlid  # noqa: E402

ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
DOC = f"---\ndoc_link_id: {ID_A}\n---\n# T {ID_B}\n\nbody\n"


class EntryTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def read(self, path):
        return (self.root / path).read_bytes().decode("utf-8")

    def snapshot(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }

    def run_main(self, *args):
        """入口 script を同じプロセスで実行し、（終了コード、標準出力の JSON）を返す。"""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = embed_dlid.main(
                [args[0], "--project-root", str(self.root), *args[1:]]
            )
        return code, json.loads(out.getvalue())


class PlanCommandTest(EntryTestBase):
    def test_plan_without_duplicates_is_confirmed_and_writes_nothing(self):
        self.write("a.md", "# T\n\n## U\n")
        before = self.snapshot()
        code, result = self.run_main("plan", "--key", "k", "--paths", "a.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["state"], "計画確定")
        self.assertFalse(result["needs_origin"])
        self.assertEqual(
            [(i["path"], i["kind"], i["line"]) for i in result["items"]],
            [
                ("a.md", "document", None),
                ("a.md", "section", 1),
                ("a.md", "section", 3),
            ],
        )
        self.assertNotIn("dlid", result["items"][0])
        self.assertEqual(self.snapshot(), before)

    def test_plan_with_duplicates_awaits_origin_and_shows_origin_args(self):
        self.write("orig.md", DOC)
        self.write("copy.md", DOC)
        before = self.snapshot()
        code, result = self.run_main(
            "plan", "--key", "k", "--paths", "orig.md", "copy.md"
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["state"], "原本確認待ち")
        self.assertTrue(result["needs_origin"])
        by_dlid = {d["dlid"]: d for d in result["duplicates"]}
        self.assertEqual(set(by_dlid), {ID_A, ID_B})
        self.assertTrue(all(d["needs_origin"] for d in by_dlid.values()))
        self.assertEqual(
            [loc["origin_args"] for loc in by_dlid[ID_A]["locations"]],
            [[ID_A, "copy.md", "document", "-"], [ID_A, "orig.md", "document", "-"]],
        )
        self.assertEqual(
            [loc["origin_args"] for loc in by_dlid[ID_B]["locations"]],
            [[ID_B, "copy.md", "section", "4"], [ID_B, "orig.md", "section", "4"]],
        )
        self.assertEqual(self.snapshot(), before)

    def test_all_mode_without_arguments(self):
        self.write("docs/a.md", "# T\n")
        self.write(".temp/x/ignored.md", "# I\n")
        code, result = self.run_main("plan")
        self.assertEqual(code, 0)
        self.assertEqual({i["path"] for i in result["items"]}, {"docs/a.md"})

    def test_missing_target_is_reported_and_processing_continues(self):
        self.write("a.md", "# T\n")
        code, result = self.run_main("plan", "--key", "k", "--paths", "a.md", "nope.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["problems"], [{"path": "nope.md", "reason": "missing"}])
        self.assertEqual({i["path"] for i in result["items"]}, {"a.md"})


class RejectedArgumentsTest(EntryTestBase):
    def test_conflicting_target_arguments_are_rejected_with_exit_1(self):
        self.write("a.md", "# T\n")
        before = self.snapshot()
        for args in (
            ("--paths", "a.md"),
            ("--key", "all", "--paths", "a.md"),
            ("--key", "k"),
            ("--key", "k", "--all", "--paths", "a.md"),
        ):
            for command in ("plan", "apply"):
                with self.subTest(command=command, args=args):
                    code, result = self.run_main(command, *args)
                    self.assertEqual(code, 1)
                    self.assertIsInstance(result["errors"], list)
                    self.assertTrue(result["errors"])
        self.assertEqual(self.snapshot(), before)

    def test_unknown_argument_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                embed_dlid.main(["plan", "--unknown"])
        self.assertEqual(caught.exception.code, 2)

    def test_subcommand_is_required(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                embed_dlid.main([])
        self.assertEqual(caught.exception.code, 2)

    def test_malformed_origin_exits_2_or_1(self):
        self.write("a.md", "# T\n")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                embed_dlid.main(
                    [
                        "apply",
                        "--project-root",
                        str(self.root),
                        "--key",
                        "k",
                        "--paths",
                        "a.md",
                        "--origin",
                        "only-one-value",
                    ]
                )
        self.assertEqual(caught.exception.code, 2)

    def test_invalid_origin_values_exit_1_and_write_nothing(self):
        self.write("orig.md", DOC)
        self.write("copy.md", DOC)
        before = self.snapshot()
        cases = (
            [ID_A, "orig.md", "bogus", "-"],
            ["not-a-dlid", "orig.md", "document", "-"],
            [ID_A, "orig.md", "document", "3"],
            [ID_B, "orig.md", "section", "0"],
            [ID_B, "orig.md", "section", "x"],
            [ID_A, "elsewhere.md", "document", "-"],
            ["DLID-zzzzzzzzzzzz", "orig.md", "document", "-"],
            [ID_B, "orig.md", "section", "5"],
        )
        for origin in cases:
            with self.subTest(origin=origin):
                code, result = self.run_main(
                    "apply",
                    "--key",
                    "k",
                    "--paths",
                    "orig.md",
                    "copy.md",
                    "--origin",
                    *origin,
                )
                self.assertEqual(code, 1)
                self.assertTrue(result["errors"])
                self.assertEqual(self.snapshot(), before)

    def test_same_origin_twice_exit_1(self):
        self.write("orig.md", DOC)
        self.write("copy.md", DOC)
        code, result = self.run_main(
            "apply",
            "--key",
            "k",
            "--paths",
            "orig.md",
            "copy.md",
            "--origin",
            ID_A,
            "orig.md",
            "document",
            "-",
            "--origin",
            ID_A,
            "copy.md",
            "document",
            "-",
        )
        self.assertEqual(code, 1)

    def test_unreadable_document_exits_1(self):
        self.write("a.md", "# T\n")
        (self.root / "bad.md").write_bytes(b"\xff\xfe\x00bad\n")
        code, result = self.run_main("apply", "--key", "k", "--paths", "a.md", "bad.md")
        self.assertEqual(code, 1)
        self.assertEqual(result["state"], "失敗")
        self.assertIn("bad.md", result["errors"][0])
        self.assertEqual(self.read("a.md"), "# T\n")


class ApplyCommandTest(EntryTestBase):
    def test_apply_writes_and_reports(self):
        self.write("a.md", "# T\n")
        code, result = self.run_main("apply", "--key", "k", "--paths", "a.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["state"], "完了")
        self.assertEqual(
            [(w["path"], w["kind"], w["replaced"]) for w in result["written"]],
            [("a.md", "document", None), ("a.md", "section", None)],
        )
        text = self.read("a.md")
        doc_id = result["written"][0]["dlid"]
        section_id = result["written"][1]["dlid"]
        self.assertEqual(text, f"---\ndoc_link_id: {doc_id}\n---\n\n# T {section_id}\n")
        self.assertEqual(result["written"][1]["line"], 5)

    def test_apply_does_not_touch_management_state(self):
        self.write("a.md", "# T\n")
        self.run_main("apply", "--key", "k", "--paths", "a.md")
        self.assertFalse((self.root / ".doc-link").exists())

    def test_apply_is_idempotent(self):
        self.write("a.md", "# T\n\n## U\n")
        self.run_main("apply", "--key", "k", "--paths", "a.md")
        after_first = self.snapshot()
        code, result = self.run_main("apply", "--key", "k", "--paths", "a.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["written"], [])
        self.assertEqual(self.snapshot(), after_first)

    def test_apply_with_duplicates_and_no_origin_exits_3_and_writes_nothing(self):
        self.write("orig.md", DOC)
        self.write("copy.md", DOC)
        before = self.snapshot()
        code, result = self.run_main(
            "apply", "--key", "k", "--paths", "orig.md", "copy.md"
        )
        self.assertEqual(code, embed_dlid.EXIT_AWAITING_ORIGIN)
        self.assertEqual(result["state"], "失敗")
        self.assertTrue(result["errors"])
        self.assertEqual({d["dlid"] for d in result["duplicates"]}, {ID_A, ID_B})
        self.assertEqual(self.snapshot(), before)

    def test_apply_with_origin_args_from_plan_reissues_the_copy(self):
        self.write("orig.md", DOC)
        self.write("copy.md", DOC)
        _, plan = self.run_main("plan", "--key", "k", "--paths", "orig.md", "copy.md")
        origin_options = []
        for duplicate in plan["duplicates"]:
            location = next(
                loc for loc in duplicate["locations"] if loc["path"] == "orig.md"
            )
            origin_options += ["--origin", *location["origin_args"]]
        code, result = self.run_main(
            "apply", "--key", "k", "--paths", "orig.md", "copy.md", *origin_options
        )
        self.assertEqual(code, 0, result)
        self.assertEqual(self.read("orig.md"), DOC)
        self.assertEqual(
            sorted((w["kind"], w["replaced"]) for w in result["written"]),
            [("document", ID_A), ("section", ID_B)],
        )
        copy = self.read("copy.md")
        self.assertNotIn(ID_A, copy)
        self.assertNotIn(ID_B, copy)
        self.assertEqual(copy.count("DLID-"), 2)

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0, "root は読み取り専用を迂回する"
    )
    def test_partial_failure_exits_4_and_keeps_issued_dlids(self):
        self.write("a.md", "# A\n")
        self.write("b.md", "# B\n")
        (self.root / "a.md").chmod(0o444)
        code, result = self.run_main("apply", "--key", "k", "--paths", "a.md", "b.md")
        self.assertEqual(code, embed_dlid.EXIT_NOT_WRITTEN)
        self.assertEqual(result["state"], "失敗")
        self.assertEqual([f["path"] for f in result["failed"]], ["a.md"])
        self.assertEqual(
            set(result["failed"][0]), {"path", "location", "cause", "reverted"}
        )
        self.assertEqual({w["path"] for w in result["written"]}, {"b.md"})
        self.assertTrue(result["errors"][0].startswith("a.md: "))
        self.assertEqual(self.read("a.md"), "# A\n")
        self.assertTrue(self.read("b.md").startswith("---\ndoc_link_id: DLID-"))

        # 再実行は、書き込み済みの[DLID]を既存の[DLID]として照合し直し、残りの文書だけを処理する
        (self.root / "a.md").chmod(0o644)
        code, result = self.run_main("apply", "--key", "k", "--paths", "a.md", "b.md")
        self.assertEqual(code, 0)
        self.assertEqual({w["path"] for w in result["written"]}, {"a.md"})

    def test_unclosed_frontmatter_exits_4(self):
        self.write("a.md", "---\ntitle: x\n# T\n")
        code, result = self.run_main("apply", "--key", "k", "--paths", "a.md")
        self.assertEqual(code, embed_dlid.EXIT_NOT_WRITTEN)
        self.assertEqual(result["written"], [])
        self.assertEqual(result["failed"][0]["location"], "frontmatter")
        self.assertEqual(self.read("a.md"), "---\ntitle: x\n# T\n")


@unittest.skipUnless(shutil.which("uv"), "uv が使えない環境では実行しない")
class EntryScriptWithUvTest(EntryTestBase):
    SCRIPT = SKILL_SCRIPTS_DIR / "embed_dlid.py"

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

    def test_plan_exits_0_with_json(self):
        self.write("a.md", "# T\n")
        completed = self.uv_run(
            "plan", "--project-root", str(self.root), "--key", "k", "--paths", "a.md"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["state"], "計画確定")

    def test_apply_exits_0_and_writes(self):
        self.write("a.md", "# T\n")
        completed = self.uv_run(
            "apply", "--project-root", str(self.root), "--key", "k", "--paths", "a.md"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["state"], "完了")
        self.assertTrue(self.read("a.md").startswith("---\ndoc_link_id: DLID-"))

    def test_apply_exits_3_when_origin_is_needed(self):
        self.write("orig.md", DOC)
        self.write("copy.md", DOC)
        completed = self.uv_run(
            "apply",
            "--project-root",
            str(self.root),
            "--key",
            "k",
            "--paths",
            "orig.md",
            "copy.md",
        )
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertIn("errors", json.loads(completed.stdout))
        self.assertEqual(self.read("copy.md"), DOC)

    def test_rejected_target_exits_1(self):
        completed = self.uv_run(
            "plan", "--project-root", str(self.root), "--paths", "a.md"
        )
        self.assertEqual(completed.returncode, 1)
        self.assertTrue(json.loads(completed.stdout)["errors"])

    def test_invalid_argument_exits_2(self):
        completed = self.uv_run("plan", "--unknown")
        self.assertEqual(completed.returncode, 2)


if __name__ == "__main__":
    unittest.main()
