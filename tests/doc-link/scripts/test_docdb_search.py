"""`docdb_search`（[doc-db]の検索と、[文書 ID]・[セクション ID]への対応づけ）のテスト。AC-039・AC-044。"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import docdb_client  # noqa: E402
import docdb_search as ds  # noqa: E402

ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
SEC_A1 = "DLID-00000000s001"
SEC_A2 = "DLID-00000000s002"
PATH_TO_DOC = {"docs/a.md": ID_A, "docs/b.md": ID_B}
PATHS = {ID_A: "docs/a.md", ID_B: "docs/b.md"}
SECTIONS = {ID_A: {SEC_A1: "概要", SEC_A2: "詳細"}, ID_B: {}}


def hit(path, heading_path="", score=0.5):
    return {"path": path, "heading_path": heading_path, "text": "t", "score": score}


def no_git(arguments, cwd):
    return 128, ""


class MapResultsTest(unittest.TestCase):
    def map(self, results):
        return ds.map_results({"results": results}, PATH_TO_DOC, PATHS, SECTIONS)

    def test_documents_follow_the_rank_of_their_best_chunk(self):
        found = self.map([hit("docs/b.md"), hit("docs/a.md"), hit("docs/b.md")])
        self.assertEqual([d["doc_link_id"] for d in found.documents], [ID_B, ID_A])
        self.assertEqual([d["rank"] for d in found.documents], [1, 2])
        self.assertIn("順位 1", found.documents[0]["reason"])
        self.assertIn("2 件", found.documents[0]["reason"])

    def test_relevance_is_always_maybe_and_the_reason_is_a_fixed_sentence(self):
        found = self.map([hit("docs/a.md")])
        document = found.documents[0]
        self.assertEqual(document["relevance"], "maybe")
        self.assertEqual(document["recorded_path"], "docs/a.md")
        self.assertTrue(document["reason"].startswith("doc-db の検索の上位に入った"))
        self.assertEqual(
            set(document),
            {"doc_link_id", "recorded_path", "relevance", "reason", "sections", "rank"},
        )

    def test_the_section_is_read_from_the_dlid_at_the_end_of_the_heading_path(self):
        found = self.map(
            [
                hit("docs/a.md", f"文書の題 DLID-zzzzzzzzzzzz > 概要 {SEC_A1}"),
                hit("docs/a.md", f"文書の題 DLID-zzzzzzzzzzzz > 詳細 {SEC_A2}"),
                hit("docs/a.md", f"文書の題 DLID-zzzzzzzzzzzz > 概要 {SEC_A1}"),
            ]
        )
        self.assertEqual(
            found.documents[0]["sections"],
            [
                {"section_id": SEC_A1, "heading": "概要"},
                {"section_id": SEC_A2, "heading": "詳細"},
            ],
        )

    def test_a_dlid_the_document_does_not_have_falls_back_to_the_document(self):
        # コードブロックの内側の `#` の行が見出しとして分割され、実際の見出しと食い違う場合など
        for heading_path in (
            "題 > # コメント",
            "題 > コード DLID-aaaaaaaaaaaa",
            f"題 > 別の文書の見出し {ID_B}",
            "",
        ):
            with self.subTest(heading_path=heading_path):
                found = self.map([hit("docs/a.md", heading_path)])
                self.assertEqual(found.documents[0]["sections"], [])

    def test_a_result_without_a_matching_path_is_counted_not_listed(self):
        found = self.map([hit("docs/old.md"), hit("docs/a.md")])
        self.assertEqual(found.unmapped, 1)
        self.assertEqual([d["doc_link_id"] for d in found.documents], [ID_A])
        self.assertEqual(found.documents[0]["rank"], 1)
        self.assertEqual(found.hits, 2)

    def test_no_results_is_an_empty_list(self):
        found = self.map([])
        self.assertEqual((found.documents, found.unmapped), ([], 0))

    def test_a_malformed_response_is_a_value_error(self):
        for response in ({}, {"results": "x"}, {"results": [{"heading_path": ""}]}, []):
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    ds.map_results(response, PATH_TO_DOC, PATHS, SECTIONS)


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def query(self, key, series, query, mode, top_n):
        self.calls.append((key, series, query, mode, top_n))
        if self.error is not None:
            raise self.error
        return self.response


class SearchTest(unittest.TestCase):
    def search(self, client, met=False):
        return ds.search(
            client,
            "/project",
            "specs",
            "検索のタスク",
            PATH_TO_DOC,
            PATHS,
            SECTIONS,
            met=met,
            runner=no_git,
        )

    def test_the_task_is_passed_as_is_in_all_mode_without_rerank(self):
        client = FakeClient({"results": [hit("docs/a.md")]})
        found = self.search(client)
        key, series, query, mode, top_n = client.calls[0]
        self.assertTrue(key.startswith("doc-link."))
        self.assertEqual((query, mode, top_n), ("検索のタスク", "all", ds.TOP_N))
        self.assertEqual(len(found.documents), 1)

    def error(self, exc):
        with self.assertRaises(ds.DocdbSearchError) as raised:
            self.search(FakeClient(error=exc))
        return raised.exception

    def test_embedding_failures_switch(self):
        exc = docdb_client.ToolError(
            "m", code=-32603, data={"code": "EMBEDDING_FAILED"}
        )
        raised = self.error(exc)
        self.assertTrue(raised.switch)
        self.assertEqual(raised.reason_code, "docdb_openai_failed")
        self.assertFalse(raised.presumed)

    def test_an_internal_error_without_an_identifier_switches_only_for_old_versions(
        self,
    ):
        exc = docdb_client.ToolError("m", code=-32603)
        raised = self.error(exc)
        self.assertTrue(raised.switch)
        self.assertTrue(raised.presumed)
        with self.assertRaises(ds.DocdbSearchError) as faulted:
            self.search(FakeClient(error=exc), met=True)
        self.assertFalse(faulted.exception.switch)

    def test_a_dropped_connection_switches_for_unreachable(self):
        raised = self.error(
            docdb_client.TransportError("x", "TransportError（OSError）")
        )
        self.assertTrue(raised.switch)
        self.assertEqual(raised.reason_code, "docdb_unreachable")

    def test_other_failures_do_not_switch(self):
        for exc in (
            docdb_client.ToolError("m", code=-31002, data={"code": "KEY_TRASHED"}),
            docdb_client.ToolError("m", code=-31001, data={"code": "KEY_NOT_FOUND"}),
            docdb_client.ToolError("m", code=-32603, data={"code": "INTERNAL_ERROR"}),
            docdb_client.HttpError(500, "body", "u"),
            docdb_client.ProtocolError("p"),
        ):
            with self.subTest(exc=type(exc).__name__):
                raised = self.error(exc)
                self.assertFalse(raised.switch)
                self.assertTrue(raised.errors)
                self.assertNotIn("body", " ".join(raised.errors))

    def test_a_malformed_response_is_a_fault(self):
        with self.assertRaises(ds.DocdbSearchError) as raised:
            self.search(FakeClient({"results": "x"}))
        self.assertFalse(raised.exception.switch)


if __name__ == "__main__":
    unittest.main()
