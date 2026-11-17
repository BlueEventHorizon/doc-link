"""横断シナリオ 1（初回。DES-009 §3、受け入れ基準 1）。

DLID 付与操作 → 対象指定 → ID 確認 → 変更集合 → 必要情報 → 参照実走査 → [ToC]確定 → 検索可能、を
各 SKILL の入口 script を通して 1 本の流れで確かめる。AI の生成は固定値の差し込みで代替する。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scenario_support import (  # noqa: E402
    FIXED,
    ScenarioBase,
    query_docs,
    strip_dlids,
)

KEY = "k"
PATHS = ["docs/a.md", "docs/b.md"]
A_ORIGINAL = "# Alpha\n\nalpha body\n\n## Part\n\npart body\n"
B_ORIGINAL = "# Beta\n\nsee [alpha](a.md)\n"


class FirstTimeScenarioTest(ScenarioBase):
    def setUp(self):
        super().setUp()
        self.write("docs/a.md", A_ORIGINAL)
        self.write("docs/b.md", B_ORIGINAL)

    def written_ids(self, result):
        documents = {}
        sections = {}
        for item in result["written"]:
            if item["kind"] == "document":
                documents[item["path"]] = item["dlid"]
            else:
                sections[(item["path"], item["heading"].rsplit(" ", 1)[0])] = item[
                    "dlid"
                ]
        return documents, sections

    def test_scenario_1_from_embedding_to_searchable(self):
        # 1. DLID 付与操作。書き込まれた差分は[DLID]だけで、管理状態は作られない
        code, embedded = self.embed(KEY, PATHS)
        self.assertEqual(code, 0, embedded)
        self.assertEqual(embedded["state"], "完了")
        self.assertEqual(strip_dlids(self.read("docs/a.md")), A_ORIGINAL)
        self.assertEqual(strip_dlids(self.read("docs/b.md")), B_ORIGINAL)
        self.assertTrue(self.read("docs/a.md").startswith("---\ndoc_link_id: DLID-"))
        self.assertEqual(self.state_snapshot(), {})
        documents, sections = self.written_ids(embedded)
        id_a, id_b = documents["docs/a.md"], documents["docs/b.md"]
        section_part = sections[("docs/a.md", "Part")]
        self.assertEqual(len({id_a, id_b, section_part}), 3)

        # 2. 構築前は未構築と判定され、検索はできない
        code, stale = self.check_toc(KEY, PATHS)
        self.assertEqual((code, stale["status"]), (0, "not_built"))
        code, prepared = self.run_script(
            query_docs,
            "--task",
            "調べもの",
            "--key",
            KEY,
            "--paths",
            *PATHS,
            command="prepare",
        )
        self.assertEqual((code, prepared["action"]), (0, "initial_build_required"))

        # 3. index-docs を、対象指定から確定まで進める
        docs_before = self.snapshot("docs")
        code, invoked = self.advance(KEY, PATHS)
        self.assertEqual(code, 0, invoked)
        self.assertEqual(invoked["action"], "invoke_toc_updater")
        requested = [
            d["doc_link_id"] for b in invoked["batches"] for d in b["documents"]
        ]
        self.assertEqual(sorted(requested), sorted([id_a, id_b]))
        self.assertFalse((self.root / ".doc-link" / "tocs").exists())
        for doc_id in requested:
            code, stored = self.submit(KEY, PATHS, invoked["build_id"], doc_id)
            self.assertEqual(code, 0, stored)
        code, done = self.advance(KEY, PATHS, "--build-id", invoked["build_id"])
        self.assertEqual(code, 0, done)
        self.assertEqual(done["action"], "done")
        self.assertEqual(done["state"], "完了")
        self.assertEqual(done["publication_state"], "確定 ToC あり")
        self.assertEqual((done["version"], done["published"]), (1, True))
        self.assertEqual(done["excluded"], [])
        self.assertEqual(done["reference_check"]["summary"], {})
        self.assertEqual(self.snapshot("docs"), docs_before)

        toc = self.toc(KEY)
        self.assertEqual(
            sorted(d["doc_link_id"] for d in toc["documents"]), sorted([id_a, id_b])
        )
        self.assertIn(section_part, [s["section_id"] for s in toc["sections"]])
        info = self.info(id_a)
        self.assertEqual(info["title"], "Alpha")
        self.assertEqual(info["path"], "docs/a.md")
        self.assertEqual(info["purpose"], FIXED["purpose"])

        # 4. check-toc は最新と判定する
        code, fresh = self.check_toc(KEY, PATHS)
        self.assertEqual((code, fresh["status"]), (0, "up_to_date"))
        self.assertEqual(fresh["documents"], [])

        # 5. query-docs の検索前検査は、検索可能（invoke_query_worker）を返し、結果を返せる
        state_before = self.state_snapshot()
        code, prepared = self.run_script(
            query_docs,
            "--task",
            "調べもの",
            "--key",
            KEY,
            "--paths",
            *PATHS,
            command="prepare",
        )
        self.assertEqual(code, 0, prepared)
        self.assertEqual(prepared["action"], "invoke_query_worker")
        self.assertEqual(prepared["freshness"], "current")
        self.assertEqual(prepared["toc_version"], 1)
        search_id = prepared["search_id"]
        code, _ = self.run_script(
            query_docs,
            "--search-id",
            search_id,
            "--doc-id",
            id_a,
            "--reason",
            "固定の理由",
            "--section-id",
            section_part,
            command="submit-item",
        )
        self.assertEqual(code, 0)
        code, _ = self.run_script(
            query_docs,
            "--search-id",
            search_id,
            "--exit-value",
            "0",
            command="submit-end",
        )
        self.assertEqual(code, 0)
        code, found = self.run_script(
            query_docs, "--search-id", search_id, command="collect"
        )
        self.assertEqual(code, 0, found)
        self.assertEqual(
            [(d["doc_link_id"], d["recorded_path"]) for d in found["documents"]],
            [(id_a, "docs/a.md")],
        )
        self.assertEqual(self.state_snapshot(), state_before)
        self.assertEqual(self.snapshot("docs"), docs_before)

        # 6. resolve-dlid が、文書と[セクション ID]を解決できる
        document = self.resolve_one(id_a)
        self.assertEqual(
            (document["status"], document["kind"], document["path"]),
            ("resolved", "document", "docs/a.md"),
        )
        self.assertEqual(document["content_hash"], info["content_hash"])
        section = self.resolve_one(section_part)
        self.assertEqual(
            (section["status"], section["kind"], section["path"]),
            ("resolved", "section", "docs/a.md"),
        )
        self.assertEqual(section["heading"], f"Part {section_part}")
        self.assertEqual(self.snapshot("docs"), docs_before)
        self.assertEqual(self.state_snapshot(), state_before)


if __name__ == "__main__":
    unittest.main()
