import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_SCRIPTS_DIR = (
    PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "query-docs" / "scripts"
)
sys.path.insert(0, str(SKILL_SCRIPTS_DIR))

import query_docs  # noqa: E402
import worker_io  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))
import backend_select  # noqa: E402
import change_set  # noqa: E402
import search_prepare  # noqa: E402
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
TITLE_A = "title a.md"
TITLE_B = "title b.md"
HEAD_A = "A"
HEAD_B = "B"
TASK = "検索のタスク"
TARGET = ("--key", KEY, "--paths", "a.md", "b.md")


def _force_toc_backend(testcase):
    """既存の検査が、実機の doc-db へ接続・起動しないよう、基盤判定を[ToC]の強制スイッチに固定する。"""
    patcher = mock.patch.object(
        backend_select,
        "decide",
        return_value=backend_select.Decision(backend_select.BACKEND_TOC, forced=True),
    )
    patcher.start()
    testcase.addCleanup(patcher.stop)


class QueryTestBase(unittest.TestCase):
    def setUp(self):
        _force_toc_backend(self)
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

    def worker(self, command, worker_id, stdin_text="", start=None, project_dir=None):
        """`query-worker` の入口（worker_io）を、`start`（既定はプロジェクトのルート）を作業ディレクトリとして呼ぶ。"""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = worker_io.execute(
                worker_io.build_parser().parse_args([command, worker_id]),
                io.StringIO(stdin_text),
                self.root if start is None else start,
                project_dir,
            )
        return code, json.loads(out.getvalue())

    def answer(self, worker_id, answer):
        """答え（dict）を、標準入力の JSON として `answer` へ渡す。"""
        return self.worker("answer", worker_id, json.dumps(answer, ensure_ascii=False))

    def work(self, worker_id, relevant=None, reason="r", maybe=None):
        """`query-worker` を模す。`next` で依頼を受け、依頼のファイルを読み、答えを `answer` で渡すことを `done` まで繰り返す。

        `relevant` は、関連する（yes）と答えるタイトルから、選ぶ見出しの並びへの対応。`maybe` は、判断がつかない（maybe）と
        答えるタイトルから、選ぶ見出しの並びへの対応。それ以外のタイトルは関連しない（no）と答える。
        依頼を受け取った順のタイトルを返す。
        """
        relevant = relevant or {}
        maybe = maybe or {}
        titles = []
        code, step = self.worker("next", worker_id)
        self.assertEqual(code, 0, step)
        while not step["done"]:
            item = json.loads(Path(step["item_path"]).read_text(encoding="utf-8"))
            titles.append(item["title"])
            if item["title"] in relevant:
                answer = {
                    "relevance": "yes",
                    "reason": reason,
                    "headings": list(relevant[item["title"]]),
                }
            elif item["title"] in maybe:
                answer = {
                    "relevance": "maybe",
                    "reason": reason,
                    "headings": list(maybe[item["title"]]),
                }
            else:
                answer = {"relevance": "no"}
            code, step = self.answer(worker_id, answer)
            self.assertEqual(code, 0, step)
        return titles


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
        self.work(result["workers"][0], {TITLE_A: []})
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

    def test_target_file_from_the_confirmation_is_taken_after_the_rebuild(self):
        # D-063: 確認が返した対象指定ファイルを、再構築の後の検索前検査へ渡す
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        code, confirm = self.run_main("prepare", "--task", TASK, "--key", KEY)
        self.assertEqual(confirm["action"], "confirm_rebuild")
        target_file = confirm["target_file"]
        self.build()  # index-docs が同じ対象で再構築した後の状態
        code, result = self.run_main(
            "prepare",
            "--task",
            TASK,
            "--choice",
            "rebuild",
            "--target-file",
            target_file,
        )
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "invoke_query_worker")
        self.assertEqual(result["toc_key"], KEY)

    def test_rebuild_of_another_target_is_an_error_with_the_target_file(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        _, confirm = self.run_main("prepare", "--task", TASK, "--key", KEY)
        self.build(paths=("a.md",))  # 検査した対象と違う対象で再構築された
        code, result = self.run_main(
            "prepare",
            "--task",
            TASK,
            "--choice",
            "rebuild",
            "--target-file",
            confirm["target_file"],
        )
        self.assertEqual(code, 1)
        self.assertNotIn("search_id", result)

    def test_target_file_with_a_key_is_rejected(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        _, confirm = self.run_main("prepare", "--task", TASK, "--key", KEY)
        code, result = self.run_main(
            "prepare",
            "--task",
            TASK,
            "--key",
            KEY,
            "--target-file",
            confirm["target_file"],
        )
        self.assertEqual(code, 1)
        self.assertTrue(any("--target-file" in error for error in result["errors"]))

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
        """検索を固定し、（検索 ID、担当の識別値の並び）を返す。"""
        self.build()
        prepared = self.prepare()[1]
        return prepared["search_id"], prepared["workers"]

    def work_directory(self):
        return self.root / ".temp" / "doc-link" / "query-docs"

    def test_full_flow_and_cleanup(self):
        sid, workers = self.start()
        self.assertEqual(workers, [f"{sid}-1"])  # 文書が少ないので担当は 1 つ
        code, first = self.worker("next", workers[0])
        self.assertEqual(code, 0)
        self.assertEqual(
            first,
            {
                "done": False,
                "item_path": first["item_path"],
                "answered": 0,
                "total": 2,
            },
        )
        request = json.loads(Path(first["item_path"]).read_text("utf-8"))
        self.assertEqual(request["task"], TASK)
        self.assertEqual(request["title"], TITLE_A)  # 担当の中はパスの昇順
        code, stored = self.answer(
            workers[0], {"relevance": "yes", "reason": "理由", "headings": [HEAD_A]}
        )
        self.assertEqual(code, 0)
        self.assertEqual(stored["stored"], {"position": 1, "total": 2})
        self.assertFalse(stored["done"])
        code, last = self.answer(workers[0], {"relevance": "no"})
        self.assertEqual((code, last["done"], last["item_path"]), (0, True, None))
        code, found = self.run_main("collect", "--search-id", sid)
        self.assertEqual(code, 0)
        self.assertEqual([d["doc_link_id"] for d in found["documents"]], [ID_A])
        self.assertEqual(found["documents"][0]["recorded_path"], "a.md")
        self.assertEqual(found["documents"][0]["relevance"], "yes")
        self.assertEqual(found["documents"][0]["reason"], "理由")
        self.assertEqual(found["documents"][0]["sections"][0]["heading"], "A")
        self.assertEqual(found["freshness"], "current")
        self.assertIn("関連度の順ではない", found["order_notice"])
        self.assertNotIn("rejected", found)
        directory = self.work_directory()
        self.assertEqual(list(directory.iterdir()) if directory.is_dir() else [], [])

    def test_partly_answered_search_exits_3_and_cleans_up(self):
        sid, workers = self.start()
        code, _ = self.answer(workers[0], {"relevance": "yes", "reason": "r"})
        self.assertEqual(code, 0)  # 2 件のうち 1 件だけ答えた
        code, result = self.run_main("collect", "--search-id", sid)
        self.assertEqual(code, 3)
        self.assertTrue(result["errors"])
        self.assertNotIn("documents", result)
        self.assertEqual(list(self.work_directory().iterdir()), [])

    def test_missing_result_exits_3(self):
        # Issue #19: 答えを渡せなかった検索は、関連する文書が無い正常な 0 件にならず、失敗になる
        sid, _ = self.start()
        code, result = self.run_main("collect", "--search-id", sid)
        self.assertEqual(code, 3)
        self.assertNotIn("documents", result)

    def test_all_irrelevant_is_a_normal_zero_result(self):
        sid, workers = self.start()
        self.work(workers[0])
        code, found = self.run_main("collect", "--search-id", sid)
        self.assertEqual((code, found["documents"]), (0, []))

    def test_maybe_documents_are_kept_with_their_relevance(self):
        sid, workers = self.start()
        self.work(workers[0], {TITLE_A: [HEAD_A]}, maybe={TITLE_B: []})
        code, found = self.run_main("collect", "--search-id", sid)
        self.assertEqual(code, 0)
        self.assertEqual(
            [(d["doc_link_id"], d["relevance"]) for d in found["documents"]],
            [(ID_A, "yes"), (ID_B, "maybe")],
        )

    def test_every_worker_must_answer_before_collect_succeeds(self):
        # 担当を 2 つにするため、1 本あたりの最小件数を下げる（プロセス内のテストだけ）
        self.build()
        with mock.patch.object(search_prepare, "MIN_DOCUMENTS_PER_WORKER", 1):
            failing = self.prepare()[1]
            complete = self.prepare()[1]
        self.assertEqual(len(failing["workers"]), 2)
        self.assertEqual(len(complete["workers"]), 2)
        # 1 つの担当だけが答え終えた検索は失敗する
        self.work(failing["workers"][0], {TITLE_A: []})
        code, result = self.run_main("collect", "--search-id", failing["search_id"])
        self.assertEqual(code, 3)
        self.assertNotIn("documents", result)
        # 全担当が答えると成功し、担当の順に並ぶ（担当 1 が a.md、担当 2 が b.md）。答える順は担当の順と逆にする
        first, second = complete["workers"]
        self.assertEqual(self.work(second, {TITLE_B: []}), [TITLE_B])
        self.assertEqual(self.work(first, {TITLE_A: []}), [TITLE_A])
        code, found = self.run_main("collect", "--search-id", complete["search_id"])
        self.assertEqual(code, 0)
        self.assertEqual([d["doc_link_id"] for d in found["documents"]], [ID_A, ID_B])
        self.assertEqual(list(self.work_directory().iterdir()), [])

    def test_explicit_cleanup_and_unknown_id(self):
        sid, workers = self.start()
        self.assertEqual(self.worker("next", workers[0])[0], 0)  # 依頼を公開した
        code, result = self.run_main("cleanup", "--search-id", sid)
        self.assertEqual(code, 0)
        self.assertEqual(result["removed"], 2)  # 固定した状態と、公開した依頼
        code, _ = self.worker("next", workers[0])
        self.assertEqual(code, 1)

    def test_state_and_documents_are_unchanged(self):
        sid, workers = self.start()
        before = self.snapshot()
        self.work(workers[0], {TITLE_B: [HEAD_B]})
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

    def setUp(self):
        super().setUp()
        # 別プロセスで動くので、基盤判定の差し替えは届かない。設定ファイルで[ToC]を強制し、実機の doc-db に触れない
        config = self.root / ".doc-link" / "config.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('{"backend": "toc"}\n', encoding="utf-8")

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

    def uv_run_worker(self, command, worker_id, stdin_text=""):
        """`query-worker` の呼び方のとおり、プロジェクトのルートを作業ディレクトリとして、引数 2 つだけで呼ぶ。"""
        return subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                str(SKILL_SCRIPTS_DIR / "worker_io.py"),
                command,
                worker_id,
            ],
            input=stdin_text,
            cwd=self.root,
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
        prepared = json.loads(completed.stdout)
        sid = prepared["search_id"]
        worker_id = prepared["workers"][0]
        base = ("--project-root", str(self.root), "--search-id", sid)
        # 文書を 1 件ずつ受け取って答える（1 件目は a.md。2 件目は関連しない）
        first = self.uv_run_worker("next", worker_id)
        self.assertEqual(first.returncode, 0, first.stderr)
        item = json.loads(
            Path(json.loads(first.stdout)["item_path"]).read_text("utf-8")
        )
        self.assertEqual(item["title"], TITLE_A)
        answer = {
            "relevance": "yes",
            "reason": "理由\n\"引用符\" と 'apostrophe'",
            "headings": [HEAD_A],
        }
        stored = self.uv_run_worker(
            "answer", worker_id, stdin_text=json.dumps(answer, ensure_ascii=False)
        )
        self.assertEqual(stored.returncode, 0, stored.stderr)
        self.assertFalse(json.loads(stored.stdout)["done"])
        last = self.uv_run_worker(
            "answer", worker_id, stdin_text=json.dumps({"relevance": "no"})
        )
        self.assertEqual(last.returncode, 0, last.stderr)
        self.assertTrue(json.loads(last.stdout)["done"])
        done = self.uv_run("collect", *base)
        self.assertEqual(done.returncode, 0, done.stderr)
        documents = json.loads(done.stdout)["documents"]
        self.assertEqual([d["doc_link_id"] for d in documents], [ID_A])
        self.assertEqual(documents[0]["relevance"], "yes")
        self.assertEqual(documents[0]["reason"], answer["reason"])
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
