"""`index-docs` の[検索基盤]（[doc-db]・[ToC]・切り替え）のテスト。AC-036〜AC-042・AC-045・AC-048。

[doc-db]は、`FakeDocDb` で模す（接続・同期のジョブ・検索）。基盤判定（`backend_select.decide`）は、各テストが決める。
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(
    0, str(PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "index-docs" / "scripts")
)
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import backend_select  # noqa: E402
import docdb_client  # noqa: E402
import docdb_runtime  # noqa: E402
import index_docs  # noqa: E402
import state_store  # noqa: E402
import toc_check  # noqa: E402
from test_index_docs import (  # noqa: E402
    A_TEXT,
    B_TEXT,
    FIXED,
    ID_A,
    ID_B,
    submit_args,
)

ALL = ["docs/a.md", "docs/b.md"]


class FakeDocDb:
    """[doc-db]の同期の入口を模す。`jobs` は、状態の応答（dict か例外）を順に返す。"""

    def __init__(self, jobs=None, start=None, contract=False):
        self.contract = contract
        self.jobs = list(jobs) if jobs is not None else None
        self.start = start
        self.synced = []

    def sync_documents(self, key, series, documents):
        self.synced.append((key, series, documents))
        if isinstance(self.start, Exception):
            raise self.start
        return self.start or {"job_id": "J"}

    def get_sync_status(self, job_id):
        if self.jobs is None:
            job = {
                "status": "done",
                "processed": len(self.synced[-1][2]),
                "skipped": 0,
                "failed": 0,
            }
            if self.contract:
                job["document_errors"] = []
            return job
        step = self.jobs.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def docdb_decision(client):
    return backend_select.Decision(
        backend_select.BACKEND_DOCDB, startup="not_attempted", client=client
    )


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.write("docs/a.md", A_TEXT)
        self.write("docs/b.md", B_TEXT)
        self.decisions = []

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def decide_with(self, decision):
        def decide(root, startup=None):
            self.decisions.append(decision)
            return decision

        patcher = mock.patch.object(backend_select, "decide", side_effect=decide)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, command, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = index_docs.main([command, "--project-root", str(self.root), *args])
        return code, json.loads(out.getvalue())

    def advance(self, *extra, paths=ALL):
        return self.run_main("advance", "--key", "k", "--paths", *paths, *extra)

    def complete_generation(self, result):
        """`toc-updater` を模し、依頼された文書へ固定値を差し込む。"""
        build_id = result["build_id"]
        for batch in result["batches"]:
            for document in batch["documents"]:
                code, stored = self.run_main(
                    "submit",
                    "--key",
                    "k",
                    "--paths",
                    *ALL,
                    "--build-id",
                    build_id,
                    *submit_args(document["doc_link_id"]),
                )
                self.assertEqual(code, 0, stored)
        return self.advance("--build-id", build_id)

    def info(self, doc_id):
        return state_store.load_document_info(self.root, doc_id)

    def state_files(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted((self.root / ".doc-link").rglob("*"))
            if p.is_file()
        }


class DocdbBuildTest(Base):
    def test_the_default_builds_the_machine_toc_syncs_doc_db_and_generates_nothing(
        self,
    ):
        # AC-036: AI 生成フィールドを作らず、[doc-db]を更新する
        client = FakeDocDb()
        self.decide_with(docdb_decision(client))
        code, result = self.advance()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "done")
        self.assertEqual(result["backend"], "doc-db")
        self.assertIsNone(result["backend_switch"])
        self.assertEqual(result["generated_count"], 0)
        self.assertEqual(result["docdb_sync"]["status"], "synced")
        self.assertEqual(result["docdb_sync"]["listed"], 2)
        self.assertEqual(len(client.synced), 1)
        self.assertEqual([d["path"] for d in client.synced[0][2]], ALL)
        toc = state_store.load_confirmed_toc(self.root, "k")
        self.assertEqual({d["doc_link_id"] for d in toc["documents"]}, {ID_A, ID_B})
        self.assertTrue(toc["sections"])

    def test_documents_have_no_ai_fields_and_are_marked_unfilled(self):
        self.decide_with(docdb_decision(FakeDocDb()))
        self.advance()
        info = self.info(ID_A)
        self.assertEqual(
            (info["purpose"], info["summary"], info["tasks"], info["keywords"]),
            ("", [], [], []),
        )
        self.assertEqual(info["content_hash"], "")
        self.assertIsNotNone(info["applied_hash"])

    def test_the_contract_warning_is_added_unless_the_contract_is_met(self):
        self.decide_with(docdb_decision(FakeDocDb()))
        _, result = self.advance()
        self.assertTrue(any("契約" in w for w in result["warnings"]))
        self.decide_with(docdb_decision(FakeDocDb(contract=True)))
        _, result = self.advance()
        self.assertFalse(any("契約" in w for w in result["warnings"]))

    def test_a_rerun_without_changes_publishes_nothing_new_but_syncs_again(self):
        client = FakeDocDb()
        self.decide_with(docdb_decision(client))
        self.advance()
        before = self.state_files()
        _, result = self.advance()
        self.assertFalse(result["published"])
        self.assertEqual(self.state_files(), before)
        self.assertEqual(len(client.synced), 2)

    def test_a_moved_and_a_deleted_document_are_reflected_in_the_next_list(self):
        # AC-043: 一覧が[確定 ToC]の所属と現在のパスから作られる
        client = FakeDocDb()
        self.decide_with(docdb_decision(client))
        self.advance()
        (self.root / "docs" / "b.md").rename(self.root / "docs" / "moved.md")
        (self.root / "docs" / "a.md").unlink()
        code, result = self.advance(paths=["docs/moved.md"])
        self.assertEqual(code, 0, result)
        self.assertEqual([d["path"] for d in client.synced[-1][2]], ["docs/moved.md"])
        self.assertEqual(self.info(ID_B)["path"], "docs/moved.md")

    def test_a_content_change_keeps_the_old_ai_fields_and_leaves_them_stale(self):
        # AC-045: doc-db を使っている間に変更された文書の AI 生成フィールドは、ToC へ切り替えた後に再生成される
        toc_decision = backend_select.Decision(backend_select.BACKEND_TOC, forced=True)
        self.decide_with(toc_decision)
        code, result = self.advance()
        self.assertEqual(result["action"], "invoke_toc_updater")
        code, result = self.complete_generation(result)
        self.assertEqual(result["action"], "done")
        self.assertEqual(self.info(ID_B)["purpose"], FIXED["purpose"])

        self.decide_with(docdb_decision(FakeDocDb()))
        self.write("docs/b.md", B_TEXT + "\nmore\n")
        code, result = self.advance()
        self.assertEqual(result["action"], "done")
        info = self.info(ID_B)
        self.assertEqual(info["purpose"], FIXED["purpose"])  # 既存の値は残る
        self.assertNotEqual(info["content_hash"], info["applied_hash"])  # 古い

        self.decide_with(toc_decision)
        code, result = self.advance()
        self.assertEqual(result["action"], "invoke_toc_updater")
        generating = [
            d["doc_link_id"] for b in result["batches"] for d in b["documents"]
        ]
        self.assertEqual(generating, [ID_B])  # 変わった文書だけ。a は再生成しない

    def test_switching_to_toc_by_the_setting_generates_every_unfilled_document(self):
        self.decide_with(docdb_decision(FakeDocDb()))
        self.advance()
        self.decide_with(
            backend_select.Decision(backend_select.BACKEND_TOC, forced=True)
        )
        code, result = self.advance()
        self.assertEqual(result["action"], "invoke_toc_updater")
        self.assertEqual(result["backend"], "toc")
        self.assertTrue(result["forced"])
        self.assertIsNone(result["backend_switch"])
        generating = {
            d["doc_link_id"] for b in result["batches"] for d in b["documents"]
        }
        self.assertEqual(generating, {ID_A, ID_B})
        code, done = self.complete_generation(result)
        self.assertEqual(done["action"], "done")
        self.assertEqual(done["generated_count"], 2)
        self.assertEqual(self.info(ID_A)["purpose"], FIXED["purpose"])
        check = toc_check.check_toc(self.root, "k")
        self.assertEqual(
            (check.status, check.ai_needed, check.ai_unfilled), ("up_to_date", 0, 0)
        )


class SwitchDuringBuildTest(Base):
    def setUp(self):
        super().setUp()
        self.toc_calls = 0

    def test_an_openai_failure_in_the_sync_continues_as_toc_and_generates(self):
        # AC-039・AC-041: 切り替え後は、AI 生成フィールドが要る文書だけを生成し、確定 ToC は確定済み
        job = {"status": "done", "failed": 0, "errors": ['path "docs/a.md": embed: x']}
        self.decide_with(docdb_decision(FakeDocDb([job])))
        code, result = self.advance()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "invoke_toc_updater")
        self.assertEqual(result["backend"], "toc")
        switch = result["backend_switch"]
        self.assertEqual(switch["reason_code"], "docdb_openai_failed")
        self.assertEqual(switch["ai_fields_needed"], 2)
        self.assertIn("doc-db から ToC へ切り替えた", switch["notice"])
        self.assertIn("version", result["machine_toc"])
        self.assertTrue(state_store.confirmed_toc_path(self.root, "k").exists())
        code, done = self.complete_generation(result)
        self.assertEqual(done["action"], "done")
        self.assertEqual(done["backend"], "toc")
        self.assertEqual(done["backend_switch"]["reason_code"], "docdb_openai_failed")
        self.assertEqual(done["generated_count"], 2)
        self.assertEqual(len(self.decisions), 1, "構築の続きで、doc-db へ再接続しない")

    def test_a_dropped_connection_in_the_sync_switches_for_unreachable(self):
        error = docdb_client.TransportError("x", "TransportError（OSError）")
        self.decide_with(docdb_decision(FakeDocDb(start=error)))
        code, result = self.advance()
        self.assertEqual(result["backend_switch"]["reason_code"], "docdb_unreachable")
        self.assertEqual(result["action"], "invoke_toc_updater")

    def test_no_generation_is_needed_when_every_document_is_already_filled(self):
        self.decide_with(
            backend_select.Decision(backend_select.BACKEND_TOC, forced=True)
        )
        _, result = self.advance()
        self.complete_generation(result)
        job = {"status": "done", "errors": ['path "docs/a.md": embed: x']}
        self.decide_with(docdb_decision(FakeDocDb([job])))
        code, result = self.advance()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "done")
        self.assertEqual(result["backend"], "toc")
        self.assertEqual(result["backend_switch"]["reason_code"], "docdb_openai_failed")

    def test_a_fault_in_the_sync_exits_4_after_publishing_the_machine_toc(self):
        # AC-040: (a)(b) 以外では、切り替えず、失敗として返す
        job = {
            "status": "done",
            "errors": ['path "docs/a.md": local_path を解決できません'],
        }
        self.decide_with(docdb_decision(FakeDocDb([job])))
        code, result = self.advance()
        self.assertEqual(code, index_docs.EXIT_SYNC_FAILED)
        self.assertTrue(result["toc_published"])
        self.assertEqual(result["backend"], "doc-db")
        self.assertIsNone(result["backend_switch"])
        self.assertTrue(result["errors"])
        self.assertTrue(state_store.confirmed_toc_path(self.root, "k").exists())
        self.assertNotIn("build_id", result)

    def test_an_unreachable_doc_db_at_the_start_builds_as_toc_with_a_notice(self):
        # AC-038: 接続できないとき、ToC へ切り替えて構築を完了する
        switch = backend_select.Switch(
            backend_select.REASON_UNREACHABLE, "executable_missing: 無い"
        )
        decision = backend_select.Decision(
            backend_select.BACKEND_TOC, startup="failed", switch=switch
        )
        self.decide_with(decision)
        code, result = self.advance()
        self.assertEqual(result["action"], "invoke_toc_updater")
        self.assertEqual(result["backend_switch"]["reason_code"], "docdb_unreachable")
        code, done = self.complete_generation(result)
        self.assertEqual(done["action"], "done")
        self.assertEqual(done["backend"], "toc")
        self.assertEqual(done["backend_switch"]["reason_code"], "docdb_unreachable")
        self.assertEqual(done["generated_count"], 2)


class SettingTest(Base):
    def config(self, text):
        path = self.root / ".doc-link" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_the_forced_switch_in_the_setting_never_touches_doc_db(self):
        # AC-037
        self.config('{"backend": "toc"}')
        with mock.patch.object(
            docdb_runtime, "ensure_available", side_effect=AssertionError("接続しない")
        ):
            code, result = self.advance()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["backend"], "toc")
        self.assertTrue(result["forced"])
        self.assertIsNone(result["backend_switch"])
        self.assertEqual(result["action"], "invoke_toc_updater")

    def test_an_invalid_setting_stops_the_build_without_writing_anything(self):
        # AC-048
        self.config('{"backend": "doc-db"}')
        with mock.patch.object(
            docdb_runtime, "ensure_available", side_effect=AssertionError("接続しない")
        ):
            code, result = self.advance()
        self.assertEqual(code, 1)
        self.assertIn(".doc-link/config.json", result["errors"][0])
        self.assertFalse(state_store.confirmed_toc_path(self.root, "k").exists())
        self.assertEqual(
            sorted(p.name for p in (self.root / ".doc-link").rglob("*") if p.is_file()),
            ["config.json"],
        )

    def test_there_is_no_per_call_override_of_the_forced_switch(self):
        code = None
        with self.assertRaises(SystemExit) as raised:
            with contextlib.redirect_stderr(io.StringIO()):
                index_docs.main(
                    ["advance", "--key", "k", "--paths", "a.md", "--backend", "toc"]
                )
        self.assertEqual(raised.exception.code, 2)


#: 他のテストが `decide` を差し替える前の、実物
REAL_DECIDE = backend_select.decide


class StartupPermissionTest(Base):
    """AC-047: 接続できないとき、利用者の許可を得てから起動する。許可の前は、構築しない。"""

    def use_real_decide(self, availability):
        self.allowed = []

        def provider(allow_startup=False):
            self.allowed.append(allow_startup)
            return availability

        def decide(root, startup=None):
            return REAL_DECIDE(root, provider, startup)

        patcher = mock.patch.object(backend_select, "decide", side_effect=decide)
        patcher.start()
        self.addCleanup(patcher.stop)

    def required(self):
        return docdb_runtime.Availability(
            docdb_runtime.STATUS_STARTUP_REQUIRED,
            "not_attempted",
            detail="接続できない",
        )

    def test_without_an_answer_it_asks_and_writes_nothing(self):
        self.use_real_decide(self.required())
        code, result = self.advance()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "confirm_docdb_startup")
        self.assertEqual(
            [o["argument"] for o in result["options"]],
            ["--docdb-startup start", "--docdb-startup toc"],
        )
        self.assertEqual(self.allowed, [False])
        self.assertFalse((self.root / ".doc-link").exists())

    def test_the_permission_starts_and_the_build_uses_doc_db(self):
        client = FakeDocDb()
        self.use_real_decide(
            docdb_runtime.Availability(
                docdb_runtime.STATUS_AVAILABLE, "succeeded", client=client
            )
        )
        code, result = self.advance("--docdb-startup", "start")
        self.assertEqual(code, 0, result)
        self.assertEqual(self.allowed, [True])
        self.assertEqual((result["action"], result["backend"]), ("done", "doc-db"))
        self.assertEqual(result["startup"], "succeeded")

    def test_a_failed_start_stops_without_building_or_switching(self):
        self.use_real_decide(
            docdb_runtime.Availability(
                docdb_runtime.STATUS_UNAVAILABLE,
                "failed",
                docdb_runtime.CAUSE_RECONNECT_FAILED,
                "10 秒以内に接続できなかった",
            )
        )
        code, result = self.advance("--docdb-startup", "start")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "docdb_startup_failed")
        self.assertEqual(result["cause"], "reconnect_failed")
        self.assertNotIn("backend_switch", result)
        self.assertFalse((self.root / ".doc-link").exists())

    def test_declining_builds_as_toc_with_the_notice(self):
        self.use_real_decide(self.required())
        code, result = self.advance("--docdb-startup", "toc")
        self.assertEqual(code, 0, result)
        self.assertEqual(self.allowed, [])
        self.assertEqual(result["action"], "invoke_toc_updater")
        self.assertEqual(result["backend"], "toc")
        self.assertEqual(
            result["backend_switch"]["reason_code"], "docdb_startup_declined"
        )
        code, done = self.complete_generation(result)
        self.assertEqual(
            done["backend_switch"]["reason_code"], "docdb_startup_declined"
        )

    def test_the_answer_is_refused_on_a_continued_build(self):
        code, result = self.advance("--build-id", "x", "--docdb-startup", "start")
        self.assertEqual(code, 1)
        self.assertIn("--docdb-startup", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
