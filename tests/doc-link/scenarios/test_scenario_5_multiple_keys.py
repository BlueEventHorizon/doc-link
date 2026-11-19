"""横断シナリオ 5（複数キー）（DES-009 §3、受け入れ基準 1）。

同一の[文書 ID]が 2 つの[ToC 識別キー] one・two に所属する状態で、一方の更新・離脱が他方の[確定 ToC]を
書き換えないこと、検証済みの[文書情報]を再利用して生成依頼が 0 件になること、両キーの表示が一致することを確かめる。
AI の生成は固定値の差し込みで代替する。
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scenario_support import (  # noqa: E402
    ID_A,
    ID_B,
    ID_C,
    S_A,
    S_B,
    S_C,
    ScenarioBase,
    doc_text,
    query_docs,
)

from content_hash import title_value  # noqa: E402

KEYS = {"one": ["docs/a.md", "docs/b.md"], "two": ["docs/b.md", "docs/c.md"]}
A_TEXT = doc_text(ID_A, "A", "body of a", S_A)
B_TEXT = doc_text(ID_B, "B", "body of b", S_B)
B_CHANGED = doc_text(ID_B, "B", "body of b, changed", S_B)
C_TEXT = doc_text(ID_C, "C", "body of c", S_C)


class MultipleKeysScenarioTest(ScenarioBase):
    def setUp(self):
        super().setUp()
        self.write("docs/a.md", A_TEXT)
        self.write("docs/b.md", B_TEXT)
        self.write("docs/c.md", C_TEXT)

    def build_both(self):
        for key, paths in KEYS.items():
            self.build_ok(key, paths)

    def test_scenario_5_update_and_departure_do_not_rewrite_the_other_key(self):
        self.build_both()
        two_before = self.toc_bytes("two")
        documents_two_before = [d for d in self.toc("two")["documents"]]

        # one で、共有の文書 B を更新する。two の[確定 ToC]は書き換わらない
        self.write("docs/b.md", B_CHANGED)
        result = self.build_ok("one", KEYS["one"])
        self.assertEqual(self.requested, [ID_B])
        self.assertEqual(result["version"], 2)
        self.assertEqual(self.toc_bytes("two"), two_before)

        # one から B が離脱する。two の[確定 ToC]は書き換わらず、B を含み続ける
        self.build_ok("one", ["docs/a.md"])
        self.assertEqual(self.requested, [])
        self.assertEqual(self.toc_bytes("two"), two_before)
        self.assertEqual(self.toc("two")["documents"], documents_two_before)
        self.assertEqual(
            [d["doc_link_id"] for d in self.toc("one")["documents"]], [ID_A]
        )
        # two は、one の更新で古くなっていることを、自分の対象指定で検査できる
        code, stale = self.check_toc("two", KEYS["two"])
        self.assertEqual((code, stale["status"]), (0, "rebuild_needed"))
        self.assertEqual(
            [(d["doc_link_id"], d["kinds"]) for d in stale["documents"]],
            [(ID_B, ["content_changed"])],
        )

    def test_scenario_5_adding_to_another_key_does_not_request_generation(self):
        self.build_ok("one", KEYS["one"])
        info_before = self.info(ID_B)
        info_bytes_before = self.snapshot(".doc-link/documents")
        # 同じ[文書 ID]・[内容ハッシュ]の検証済み[文書情報]がある文書だけを two に追加する
        result = self.build_ok("two", ["docs/b.md"])
        self.assertEqual(self.requested, [])
        self.assertEqual(result["generated_documents"], [])
        self.assertEqual(self.info(ID_B), info_before)
        self.assertEqual(self.snapshot(".doc-link/documents"), info_bytes_before)
        self.assertEqual(
            [d["doc_link_id"] for d in self.toc("two")["documents"]], [ID_B]
        )
        # 生成が要るのは、検証済みの情報が無い文書だけである
        self.build_ok("two", KEYS["two"])
        self.assertEqual(self.requested, [ID_C])

    def test_scenario_5_moving_a_document_between_keys_keeps_its_document_id(self):
        self.build_ok("one", KEYS["one"])
        b_before = self.read("docs/b.md")
        # B を one の対象から外し、two の対象に含める。B の[文書 ID]は書き換わらない
        self.build_ok("one", ["docs/a.md"])
        self.build_ok("two", KEYS["two"])
        self.assertEqual(self.read("docs/b.md"), b_before)
        self.assertEqual(
            [d["doc_link_id"] for d in self.toc("one")["documents"]], [ID_A]
        )
        self.assertEqual(
            [d["doc_link_id"] for d in self.toc("two")["documents"]], [ID_B, ID_C]
        )
        self.assertEqual(self.resolve_one(ID_B)["path"], "docs/b.md")

    def test_scenario_5_both_keys_show_the_same_document_info(self):
        self.build_both()
        copies = {}
        for key, paths in KEYS.items():
            code, prepared = self.run_script(
                query_docs,
                "--task",
                "調べもの",
                "--key",
                key,
                "--paths",
                *paths,
                command="prepare",
            )
            self.assertEqual((code, prepared["action"]), (0, "invoke_query_worker"))
            search_id = prepared["search_id"]
            code, located = self.run_script(
                query_docs, "--search-id", search_id, command="request-path"
            )
            self.assertEqual(code, 0, located)
            request = json.loads(Path(located["path"]).read_text(encoding="utf-8"))
            toc_copy = json.loads(
                Path(request["toc_copy_path"]).read_text(encoding="utf-8")
            )
            copies[key] = next(
                d for d in toc_copy["documents"] if d["doc_link_id"] == ID_B
            )
            code, _ = self.run_script(
                query_docs, "--search-id", search_id, command="cleanup"
            )
            self.assertEqual(code, 0)
        self.assertEqual(copies["one"], copies["two"])
        self.assertEqual(copies["one"]["title"], self.info(ID_B)["title"])
        self.assertEqual(copies["one"]["purpose"], self.info(ID_B)["purpose"])

    def test_scenario_5_a_stale_key_shows_the_latest_document_info(self):
        self.build_both()
        self.write("docs/b.md", B_CHANGED)
        self.build_ok("one", KEYS["one"])
        # two の[確定 ToC]は古いが、[文書情報]は両キーで同じ最新のものである（D-024）
        stale_entry = next(
            d for d in self.toc("two")["documents"] if d["doc_link_id"] == ID_B
        )
        latest = self.info(ID_B)["content_hash"]
        self.assertNotEqual(stale_entry["applied_hash"], latest)
        resolved = self.resolve_one(ID_B)
        self.assertEqual(resolved["content_hash"], title_value(latest))
        # two を再構築しても、B の生成は依頼されない（検証済みの[文書情報]を再利用する）
        result = self.build_ok("two", KEYS["two"])
        self.assertEqual(self.requested, [])
        self.assertEqual(result["generated_documents"], [])
        entry = next(
            d for d in self.toc("two")["documents"] if d["doc_link_id"] == ID_B
        )
        self.assertEqual(entry["applied_hash"], latest)


if __name__ == "__main__":
    unittest.main()
