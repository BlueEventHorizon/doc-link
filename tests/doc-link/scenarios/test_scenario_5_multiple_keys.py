"""横断シナリオ 5（複数キー）（DES-009 §3、受け入れ基準 1）。

同一の[文書 ID]が 2 つの[ToC 識別キー] one・two に所属する状態で、一方の更新・離脱が他方の所属と版を
書き換えないこと、同じ文書の値が両キーで 1 つであること、検証済みの[文書情報]を再利用して生成依頼が 0 件に
なること、両キーの表示が一致することを確かめる。
AI の生成は固定値の差し込みで代替する。
"""

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
        members_two_before = sorted(
            d["doc_link_id"] for d in self.toc("two")["documents"]
        )

        # one で、共有の文書 B を更新する。two の[確定 ToC]のファイル（所属と版）は書き換わらない
        self.write("docs/b.md", B_CHANGED)
        result = self.build_ok("one", KEYS["one"])
        self.assertEqual(self.requested, [ID_B])
        self.assertEqual(result["version"], 2)
        self.assertEqual(self.toc_bytes("two"), two_before)

        # one から B が離脱する。two の[確定 ToC]のファイルは書き換わらず、B を含み続ける
        self.build_ok("one", ["docs/a.md"])
        self.assertEqual(self.requested, [])
        self.assertEqual(self.toc_bytes("two"), two_before)
        self.assertEqual(
            sorted(d["doc_link_id"] for d in self.toc("two")["documents"]),
            members_two_before,
        )
        self.assertEqual(self.toc("two")["version"], 1)
        self.assertEqual(
            [d["doc_link_id"] for d in self.toc("one")["documents"]], [ID_A]
        )
        # B の値は 1 つなので、one の構築が確定した値を two も使う。two は古くならない
        code, fresh = self.check_toc("two", KEYS["two"])
        self.assertEqual((code, fresh["status"]), (0, "up_to_date"))

    def test_scenario_5_adding_to_another_key_does_not_request_generation(self):
        self.build_ok("one", KEYS["one"])
        info_before = self.info(ID_B)
        info_bytes_before = self.snapshot(".doc-link/documents")
        # 同じ[文書 ID]・[内容ハッシュ]の検証済み[文書情報]がある文書だけを two に追加する
        result = self.build_ok("two", ["docs/b.md"])
        self.assertEqual(self.requested, [])
        self.assertEqual(result["generated_count"], 0)
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
            # 文書を 1 件ずつ受け取る（担当内はパスの昇順）。B が受け取る依頼に載る内容を比べる
            items = self.work_through(
                prepared["workers"][0], lambda item: {"relevance": "no"}
            )
            # position・total は担当内の位置なので、キーごとに違う。文書の内容だけを比べる
            copies[key] = {
                name: value
                for name, value in next(
                    item for item in items if item["title"] == self.info(ID_B)["title"]
                ).items()
                if name not in ("position", "total")
            }
            code, _ = self.run_script(
                query_docs, "--search-id", search_id, command="cleanup"
            )
            self.assertEqual(code, 0)
        self.assertEqual(copies["one"], copies["two"])
        self.assertEqual(copies["one"]["title"], self.info(ID_B)["title"])
        self.assertEqual(copies["one"]["purpose"], self.info(ID_B)["purpose"])

    def test_scenario_5_value_of_a_shared_document_is_one_for_both_keys(self):
        self.build_both()
        self.write("docs/b.md", B_CHANGED)
        self.build_ok("one", KEYS["one"])
        # 同じ文書の値は[ToC 識別キー]によらず 1 つである。one の構築が確定した B の値を、two も使う（D-024）
        latest = self.info(ID_B)["content_hash"]
        entries = {
            key: next(d for d in self.toc(key)["documents"] if d["doc_link_id"] == ID_B)
            for key in KEYS
        }
        self.assertEqual(entries["one"]["applied_hash"], latest)
        self.assertEqual(entries["two"], entries["one"])
        sections = {
            key: [s for s in self.toc(key)["sections"] if s["doc_link_id"] == ID_B]
            for key in KEYS
        }
        self.assertEqual(len(sections["one"]), 1)
        self.assertEqual(sections["two"], sections["one"])
        resolved = self.resolve_one(ID_B)
        self.assertEqual(resolved["content_hash"], title_value(latest))
        # two を再構築しても、B の生成は依頼されず、内容が同じなので版は変わらない
        result = self.build_ok("two", KEYS["two"])
        self.assertEqual(self.requested, [])
        self.assertEqual(result["generated_count"], 0)
        self.assertEqual((result["version"], result["published"]), (1, False))

    def test_scenario_5_change_in_another_key_reaches_the_referrer(self):
        # 参照元 R は refs にだけ、参照先 B は two にだけ所属する
        def referrer(document_record="", section_record=""):
            return doc_text(
                ID_A,
                "R",
                "[b][b] [s][s]\n\n"
                f'[b]: b.md "{document_record}{ID_B}"\n'
                f'[s]: b.md "{section_record}{S_B}"',
                S_A,
            )

        self.write("docs/r.md", referrer())
        refs = ["docs/r.md"]
        self.build_ok("two", KEYS["two"])
        self.build_ok("refs", refs)
        # 記録の無い参照は、参照先が別のキーにだけ所属していても、現在ハッシュとともに返る
        found = self.impact_documents("refs", refs)
        self.assertEqual(
            [(dlid, record) for dlid, record, _ in found], [(ID_B, None), (S_B, None)]
        )
        current = {dlid: value for dlid, _, value in found}
        self.assertEqual(current[ID_B], title_value(self.info(ID_B)["applied_hash"]))
        # 現在ハッシュを title に記録すると、影響候補は無くなる
        self.write("docs/r.md", referrer(current[ID_B] + " ", current[S_B] + " "))
        self.build_ok("refs", refs)
        self.assertEqual(self.impact_documents("refs", refs), [])
        # 参照先を変更して two だけを再構築する。refs は再構築しなくても最新のままで、変更が届く
        self.write("docs/b.md", B_CHANGED)
        self.build_ok("two", KEYS["two"])
        code, fresh = self.check_toc("refs", refs)
        self.assertEqual((code, fresh["status"]), (0, "up_to_date"))
        changed = self.impact_documents("refs", refs)
        self.assertEqual(
            [(dlid, record) for dlid, record, _ in changed],
            [(ID_B, current[ID_B]), (S_B, current[S_B])],
        )
        for dlid, record, value in changed:
            self.assertNotEqual(value, record)


if __name__ == "__main__":
    unittest.main()
