"""`query-docs` の[検索基盤]（[doc-db]・[ToC]・切り替え・自動更新）のテスト。AC-036〜AC-044・AC-048・AC-049。

[doc-db]は、`FakeDocDb` で模す。基盤判定（`backend_select.decide`）は、各テストが決める。
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import backend_select  # noqa: E402
import docdb_client  # noqa: E402
import state_store  # noqa: E402
from test_query_docs import (  # noqa: E402
    A_TEXT,
    ID_A,
    ID_B,
    KEY,
    SEC_A,
    TASK,
    TITLE_A,
    QueryTestBase,
)


class FakeDocDb:
    def __init__(
        self, job=None, query=None, query_error=None, sync_error=None, contract=False
    ):
        self.job = job or {"status": "done", "processed": 2, "skipped": 0, "failed": 0}
        if contract:
            # 契約を満たす doc-db は、同期の応答に document_errors を持つ
            self.job = {
                **self.job,
                "document_errors": self.job.get("document_errors", []),
            }
        self.query_response = query if query is not None else {"results": []}
        self.query_error = query_error
        self.sync_error = sync_error
        self.synced = []
        self.queried = []

    def sync_documents(self, key, series, documents):
        self.synced.append((key, series, documents))
        if self.sync_error is not None:
            raise self.sync_error
        return {"job_id": "J"}

    def get_sync_status(self, job_id):
        return self.job

    def query(self, key, series, query, mode, top_n):
        self.queried.append((key, series, query, mode, top_n))
        if self.query_error is not None:
            raise self.query_error
        return self.query_response


def hit(path, heading_path="", score=0.9):
    return {"path": path, "heading_path": heading_path, "text": "t", "score": score}


class Base(QueryTestBase):
    def use(self, decision):
        patcher = mock.patch.object(backend_select, "decide", return_value=decision)
        patcher.start()
        self.addCleanup(patcher.stop)

    def use_docdb(self, client):
        self.use(
            backend_select.Decision(
                backend_select.BACKEND_DOCDB, startup="not_attempted", client=client
            )
        )

    def use_toc(self, forced=True, switch=None):
        self.use(
            backend_select.Decision(
                backend_select.BACKEND_TOC, forced=forced, switch=switch
            )
        )

    def unfill(self, *doc_ids):
        """[doc-db]を使う構築が作る、[AI 生成フィールド]が未生成の[文書情報]にする。"""
        for doc_id in doc_ids:
            info = state_store.load_document_info(self.root, doc_id)
            info.update(
                {
                    "purpose": "",
                    "summary": [],
                    "tasks": [],
                    "keywords": [],
                    "content_hash": "",
                }
            )
            state_store.save_document_info(self.root, "test", info)

    def stale(self, doc_id):
        info = state_store.load_document_info(self.root, doc_id)
        info["content_hash"] = "0" * 64
        state_store.save_document_info(self.root, "test", info)


class DocdbSearchTest(Base):
    def test_up_to_date_syncs_then_searches_and_returns_mapped_documents(self):
        # AC-036・AC-044
        self.build()
        client = FakeDocDb(
            query={
                "results": [
                    hit("b.md"),
                    hit("a.md", f"A {SEC_A}"),
                    hit("old.md"),
                ]
            }
        )
        self.use_docdb(client)
        code, result = self.prepare()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "docdb_result")
        self.assertEqual(result["backend"], "doc-db")
        self.assertIsNone(result["backend_switch"])
        self.assertEqual(result["freshness"], "current")
        self.assertEqual(
            result["toc_version"],
            state_store.load_confirmed_toc(self.root, KEY)["version"],
        )
        documents = result["documents"]
        self.assertEqual([d["doc_link_id"] for d in documents], [ID_B, ID_A])
        self.assertEqual({d["relevance"] for d in documents}, {"maybe"})
        self.assertEqual(
            documents[1]["sections"], [{"section_id": SEC_A, "heading": "A"}]
        )
        self.assertEqual(result["unmapped"], 1)
        self.assertEqual(result["sync"]["listed"], 2)
        for name in ("order_notice", "limit_notice", "path_notice"):
            self.assertTrue(result[name])
        self.assertNotIn("search_id", result)
        self.assertEqual(len(client.synced), 1)
        self.assertEqual(client.queried[0][2:4], (TASK, "all"))
        self.assertTrue(any("契約" in w for w in result["warnings"]))

    def test_a_met_contract_has_no_warning(self):
        self.build()
        self.use_docdb(FakeDocDb(contract=True))
        _, result = self.prepare()
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["documents"], [])

    def test_a_search_changes_neither_the_state_nor_the_documents(self):
        self.build()
        self.use_docdb(FakeDocDb(query={"results": [hit("a.md")]}))
        before = self.snapshot()
        self.prepare()
        self.assertEqual(self.snapshot(), before)

    def test_no_working_files_are_left_for_a_doc_db_search(self):
        self.build()
        self.use_docdb(FakeDocDb())
        self.prepare()
        directory = self.root / ".temp" / "doc-link" / "query-docs"
        self.assertEqual(
            sorted(p.name for p in directory.glob("SEARCH-*"))
            if directory.is_dir()
            else [],
            [],
        )

    def test_not_built_still_asks_for_the_first_build(self):
        self.write("a.md", A_TEXT)
        client = FakeDocDb()
        self.use_docdb(client)
        code, result = self.prepare()
        self.assertEqual((code, result["action"]), (0, "initial_build_required"))
        self.assertEqual(client.synced, [])


class DocdbAutomaticUpdateTest(Base):
    def test_a_stale_toc_asks_for_a_rebuild_without_the_two_options(self):
        # AC-043: 二択を示さず、自動で更新する
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        client = FakeDocDb()
        self.use_docdb(client)
        code, result = self.prepare()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "rebuild_required")
        self.assertEqual(result["reason"], "toc_stale")
        self.assertNotIn("options", result)
        self.assertEqual(
            result["scale"]["ai_generation"], 0
        )  # doc-db の更新は AI 生成を伴わない
        self.assertEqual(result["scale"]["content_changed"], 1)
        self.assertIsNone(result["ai_fields_needed"])
        self.assertTrue(Path(result["target_file"]).is_file())
        self.assertTrue(Path(result["detail_path"]).is_file())
        self.assertEqual(client.synced, [])
        self.assertEqual(client.queried, [])

    def test_the_existing_choice_is_not_offered(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        self.use_docdb(FakeDocDb())
        code, result = self.prepare("--choice", "existing")
        self.assertEqual(code, 1)
        self.assertNotIn("search_id", result)

    def test_after_the_rebuild_the_search_runs(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        self.use_docdb(FakeDocDb(query={"results": [hit("a.md")]}))
        _, confirm = self.prepare()
        self.build()  # index-docs が同じ対象で再構築した後の状態
        code, result = self.run_main(
            "prepare",
            "--task",
            TASK,
            "--choice",
            "rebuild",
            "--target-file",
            confirm["target_file"],
        )
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "docdb_result")

    def test_a_rebuild_that_did_not_bring_the_toc_up_to_date_is_an_error(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        self.use_docdb(FakeDocDb())
        code, result = self.prepare("--choice", "rebuild")
        self.assertEqual(code, 1)

    def test_undeterminable_is_a_fault_for_doc_db_too(self):
        self.build()
        (self.root / "b.md").write_bytes(b"\xff\xfe\x00bad\n")
        client = FakeDocDb()
        self.use_docdb(client)
        code, result = self.prepare()
        self.assertEqual(code, 1)
        self.assertEqual(client.synced, [])


class DocdbFailureTest(Base):
    def switch_result(self, client):
        self.build()
        self.use_docdb(client)
        return self.prepare()

    def test_an_openai_failure_in_the_sync_continues_as_toc(self):
        # AC-039
        job = {"status": "done", "errors": ['path "a.md": embed: x']}
        code, result = self.switch_result(FakeDocDb(job=job))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "invoke_query_worker")
        self.assertEqual(result["backend"], "toc")
        self.assertEqual(result["backend_switch"]["reason_code"], "docdb_openai_failed")
        self.assertIn(
            "doc-db から ToC へ切り替えた", result["backend_switch"]["notice"]
        )
        self.assertTrue(result["backend_switch"]["cause_presumed"])

    def test_the_switch_is_carried_into_the_toc_result(self):
        job = {"status": "done", "errors": ['path "a.md": embed: x']}
        _, result = self.switch_result(FakeDocDb(job=job))
        self.work(result["workers"][0], {TITLE_A: []})
        code, found = self.run_main("collect", "--search-id", result["search_id"])
        self.assertEqual(code, 0, found)
        self.assertEqual(found["backend"], "toc")
        self.assertEqual(found["backend_switch"]["reason_code"], "docdb_openai_failed")

    def test_an_embedding_failure_in_the_search_continues_as_toc(self):
        error = docdb_client.ToolError(
            "m", code=-32603, data={"code": "EMBEDDING_FAILED"}
        )
        code, result = self.switch_result(FakeDocDb(query_error=error, contract=True))
        self.assertEqual(result["action"], "invoke_query_worker")
        self.assertFalse(result["backend_switch"]["cause_presumed"])

    def test_an_internal_error_without_an_identifier_is_presumed_for_old_versions_only(
        self,
    ):
        error = docdb_client.ToolError("m", code=-32603)
        _, result = self.switch_result(FakeDocDb(query_error=error))
        self.assertEqual(result["action"], "invoke_query_worker")
        self.assertTrue(result["backend_switch"]["cause_presumed"])
        self.assertIn("推定", result["backend_switch"]["notice"])
        code, result = self.switch_result(FakeDocDb(query_error=error, contract=True))
        self.assertEqual(code, 1)

    def test_a_dropped_connection_continues_as_toc(self):
        error = docdb_client.TransportError("x", "TransportError（OSError）")
        _, result = self.switch_result(FakeDocDb(sync_error=error))
        self.assertEqual(result["backend_switch"]["reason_code"], "docdb_unreachable")

    def test_other_failures_stop_without_switching(self):
        # AC-040
        cases = (
            FakeDocDb(
                job={
                    "status": "done",
                    "errors": ['path "a.md": local_path を解決できません'],
                }
            ),
            FakeDocDb(
                query_error=docdb_client.ToolError(
                    "m", code=-31002, data={"code": "KEY_TRASHED"}
                )
            ),
            FakeDocDb(
                query_error=docdb_client.ToolError(
                    "m", code=-32603, data={"code": "INTERNAL_ERROR"}
                )
            ),
            FakeDocDb(query_error=docdb_client.HttpError(500, "secret body", "u")),
            FakeDocDb(query={"results": "broken"}),
        )
        for client in cases:
            with self.subTest(client=client.job):
                code, result = self.switch_result(client)
                self.assertEqual(code, 1, result)
                self.assertNotIn("search_id", result)
                self.assertNotIn("backend_switch", result)
                self.assertNotIn("secret body", json.dumps(result, ensure_ascii=False))

    def test_a_switch_with_unfilled_documents_asks_for_a_build_without_the_two_options(
        self,
    ):
        # AC-041: AI 生成フィールドが未生成なら、二択を示さず構築を求める（ToC が無い場合を含む）
        self.build()
        self.unfill(ID_A, ID_B)
        job = {"status": "done", "errors": ['path "a.md": embed: x']}
        self.use_docdb(FakeDocDb(job=job))
        code, result = self.prepare()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "rebuild_required")
        self.assertEqual(result["reason"], "ai_fields_needed")
        self.assertNotIn("options", result)
        self.assertEqual(result["ai_fields_unfilled"], 2)
        self.assertEqual(result["backend_switch"]["ai_fields_needed"], 2)
        self.assertIn("2 件", result["backend_switch"]["notice"])

    def test_an_unreachable_doc_db_at_the_start_is_reported_in_the_toc_result(self):
        # AC-038・AC-042
        self.build()
        switch = backend_select.Switch(
            backend_select.REASON_UNREACHABLE, "executable_missing: 無い"
        )
        self.use_toc(forced=False, switch=switch)
        code, result = self.prepare()
        self.assertEqual(result["action"], "invoke_query_worker")
        self.assertEqual(result["backend_switch"]["reason_code"], "docdb_unreachable")
        self.assertNotIn("OPENAI", json.dumps(result))


class TocRuleTest(Base):
    def test_unfilled_members_force_a_build_and_refuse_the_existing_choice(self):
        # AC-041
        self.build()
        self.unfill(ID_A)
        self.use_toc()
        code, result = self.prepare()
        self.assertEqual((code, result["action"]), (0, "rebuild_required"))
        self.assertEqual(result["reason"], "ai_fields_needed")
        self.assertEqual(result["ai_fields_unfilled"], 1)
        self.assertNotIn("options", result)
        code, refused = self.prepare("--choice", "existing")
        self.assertEqual(code, 1)
        self.assertNotIn("search_id", refused)
        code, mismatch = self.prepare("--choice", "rebuild")
        self.assertEqual(code, 1)

    def test_stale_ai_fields_with_an_up_to_date_toc_force_a_build(self):
        # doc-db を使っている間に変わった文書。機械取得の情報は最新だが、AI 生成フィールドは古い
        self.build()
        self.stale(ID_B)
        self.use_toc()
        code, result = self.prepare()
        self.assertEqual(result["action"], "rebuild_required")
        self.assertEqual(result["ai_fields_needed"], 1)
        self.assertEqual(result["ai_fields_unfilled"], 0)

    def test_an_ordinary_stale_toc_keeps_the_two_options(self):
        # ToC を使うときの規則は変えない（既存の二択）
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        self.use_toc()
        code, result = self.prepare()
        self.assertEqual(result["action"], "confirm_rebuild")
        self.assertEqual(
            [o["choice"] for o in result["options"]], ["rebuild", "existing"]
        )

    def test_a_filled_up_to_date_toc_is_searched_by_workers(self):
        self.build()
        self.use_toc()
        code, result = self.prepare()
        self.assertEqual(result["action"], "invoke_query_worker")
        self.assertEqual((result["backend"], result["forced"]), ("toc", True))
        self.assertIsNone(result["backend_switch"])
        self.work(result["workers"][0], {TITLE_A: []})
        _, found = self.run_main("collect", "--search-id", result["search_id"])
        self.assertEqual(found["backend"], "toc")


class SettingTest(Base):
    def config(self, text):
        path = self.root / ".doc-link" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def setUp(self):
        super().setUp()
        mock.patch.stopall()  # 基盤判定の差し替えを外し、設定ファイルを読ませる
        self.addCleanup(mock.patch.stopall)

    def test_the_forced_switch_in_the_setting_is_used_without_connecting(self):
        # AC-037
        self.build()
        self.config('{"backend": "toc"}')
        import docdb_runtime

        with mock.patch.object(
            docdb_runtime, "ensure_available", side_effect=AssertionError("接続しない")
        ):
            code, result = self.prepare()
        self.assertEqual(code, 0, result)
        self.assertEqual((result["backend"], result["forced"]), ("toc", True))
        self.assertIsNone(result["backend_switch"])

    def test_an_invalid_setting_stops_the_search_with_the_reason(self):
        # AC-048
        self.build()
        self.config("not json")
        import docdb_runtime

        with mock.patch.object(
            docdb_runtime, "ensure_available", side_effect=AssertionError("接続しない")
        ):
            code, result = self.prepare()
        self.assertEqual(code, 1)
        self.assertIn(".doc-link/config.json", result["errors"][0])
        self.assertNotIn("search_id", result)


if __name__ == "__main__":
    unittest.main()
