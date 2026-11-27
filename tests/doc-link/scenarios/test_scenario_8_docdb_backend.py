"""横断シナリオ 8: 検索基盤によらず、検査・解決の SKILL が同じ結果を返す（AC-045、DES-011 §9）。

[doc-db]を使って構築した状態と、[ToC]を使って構築した状態で、`check-toc`・`check-impact`・`resolve-dlid`・`check-links` が
同じ結果を返す。[doc-db]を使っている間に変わった文書は、[ToC]へ切り替えた後に再生成される。
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scenario_support import (  # noqa: E402  プラグインの script の置き場を、先に path へ足す
    ID_A,
    ID_B,
    S_A,
    S_B,
    ScenarioBase,
    doc_text,
)
import backend_select  # noqa: E402

KEY = "k"
PATHS = ["docs/a.md", "docs/b.md"]


class FakeDocDb:
    def __init__(self):
        self.synced = []

    def sync_documents(self, key, series, documents):
        self.synced.append(documents)
        return {"job_id": "J"}

    def get_sync_status(self, job_id):
        return {
            "status": "done",
            "processed": 2,
            "skipped": 0,
            "failed": 0,
            "document_errors": [],
        }


class DocdbBackendScenarioTest(ScenarioBase):
    def use(self, decision):
        patcher = mock.patch.object(backend_select, "decide", return_value=decision)
        patcher.start()
        self.addCleanup(patcher.stop)

    def docdb(self):
        self.client = FakeDocDb()
        self.use(
            backend_select.Decision(backend_select.BACKEND_DOCDB, client=self.client)
        )

    def toc(self):
        self.use(backend_select.Decision(backend_select.BACKEND_TOC, forced=True))

    def write_docs(self):
        self.write("docs/a.md", doc_text(ID_A, "A", "body of a", S_A))
        self.write("docs/b.md", doc_text(ID_B, "B", "body of b", S_B))

    def inspect(self):
        """検査・解決の結果のうち、基盤によって変わらないはずの項目。"""
        code, toc = self.check_toc(KEY, PATHS)
        self.assertEqual(code, 0, toc)
        code, impact = self.check_impact(KEY, PATHS)
        self.assertEqual(code, 0, impact)
        code, links = self.check_links(KEY, PATHS)
        self.assertEqual(code, 0, links)
        resolved = self.resolve_one(ID_B)
        return {
            "toc_status": toc["status"],
            "impact_status": impact["status"],
            "impact_documents": impact["changed_documents"],
            "links": links["summary"]["findings_by_category"],
            "resolved": {k: resolved[k] for k in ("status", "path") if k in resolved},
        }

    def inspect_built_by_toc(self):
        saved = self.root
        with tempfile.TemporaryDirectory() as directory:
            self.root = Path(directory)
            try:
                self.toc()
                self.write_docs()
                self.build_ok(KEY, PATHS)
                return self.inspect()
            finally:
                self.root = saved

    def test_the_inspection_skills_return_the_same_results_for_both_backends(self):
        self.write_docs()
        self.docdb()
        code, result = self.advance(KEY, PATHS)
        self.assertEqual(
            (code, result["action"], result["backend"]), (0, "done", "doc-db")
        )
        from_docdb = self.inspect()
        self.assertEqual(from_docdb["toc_status"], "up_to_date")
        self.assertEqual(
            from_docdb["resolved"], {"status": "resolved", "path": "docs/b.md"}
        )

        # 同じ文書を、[ToC]で構築した状態（別のプロジェクトのルート）と比べる
        from_toc = self.inspect_built_by_toc()
        self.assertEqual(from_docdb, from_toc)

    def test_a_change_made_while_using_doc_db_is_regenerated_after_switching_to_toc(
        self,
    ):
        self.write_docs()
        self.toc()
        self.build_ok(KEY, PATHS)  # [ToC]で、AI 生成フィールドを作る
        self.docdb()
        self.write("docs/b.md", doc_text(ID_B, "B", "body of b changed", S_B))
        code, result = self.advance(KEY, PATHS)
        self.assertEqual((code, result["action"]), (0, "done"))
        self.assertEqual(result["generated_count"], 0)  # doc-db のときは、生成しない
        self.toc()
        self.build_ok(KEY, PATHS)
        self.assertEqual(self.requested, [ID_B])  # 変わった文書だけが再生成される
        code, fresh = self.check_toc(KEY, PATHS)
        self.assertEqual(
            (fresh["status"], fresh["ai_fields_needed"], fresh["ai_fields_unfilled"]),
            ("up_to_date", 0, 0),
        )


if __name__ == "__main__":
    unittest.main()
