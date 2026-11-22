"""横断シナリオ 2（移動）・3（内容変更）（DES-009 §3、受け入れ基準 2・3）。

固定の文書を[確定 ToC]まで構築した後で、パスだけを変える（2）・参照先の本文を変える（3）。
AI の生成は固定値の差し込みで代替し、`toc-updater` への生成依頼の有無は、`build` が記録する依頼の[文書 ID]で確かめる。
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
)

from content_hash import RECORD_LENGTH  # noqa: E402

KEY = "k"
OLD_RECORD = "c" * RECORD_LENGTH


def a_text(c_path="c.md", record=OLD_RECORD, target=ID_C):
    """参照元 A。C を、パスと title の記録（[内容ハッシュ]と[DLID]）で参照する。"""
    return doc_text(ID_A, "A", f'[to c][c]\n\n[c]: {c_path} "{record} {target}"', S_A)


B_TEXT = doc_text(ID_B, "B", "body of b", S_B)
C_TEXT = doc_text(ID_C, "C", "body of c", S_C)
PATHS = ["docs/a.md", "docs/b.md", "docs/c.md"]


class MoveScenarioTest(ScenarioBase):
    """シナリオ 2: 同じ ID・同じ内容でパスだけ変更し、要約を再生成せず[ToC]の現在パスを更新する。"""

    def setUp(self):
        super().setUp()
        self.write("docs/a.md", a_text())
        self.write("docs/b.md", B_TEXT)
        self.write("docs/c.md", C_TEXT)

    def move_c(self):
        self.write("docs/sub/c.md", C_TEXT)
        (self.root / "docs" / "c.md").unlink()
        return ["docs/a.md", "docs/b.md", "docs/sub/c.md"]

    def test_scenario_2_move_updates_current_path_without_regenerating(self):
        self.build_ok(KEY, PATHS)
        info_before = self.info(ID_C)
        toc_before = self.toc(KEY)
        paths = self.move_c()

        # 再構築の前は、記録されたパスに無い
        self.assertEqual(
            self.resolve_one(ID_C)["status"],
            "not_at_recorded_path",
        )
        code, stale = self.check_toc(KEY, paths)
        self.assertEqual(code, 0, stale)
        self.assertEqual(stale["status"], "rebuild_needed")
        self.assertEqual(stale["scale"]["path_changed"], 1)
        self.assertEqual(stale["scale"]["ai_generation"], 0)

        documents_before = self.snapshot("docs")
        info_other_before = {doc_id: self.info(doc_id) for doc_id in (ID_A, ID_B)}
        result = self.build_ok(KEY, paths)

        # toc-updater への生成依頼は 0 件
        self.assertEqual(self.requested, [])
        self.assertEqual(result["generated_count"], 0)
        # [文書情報]は、パス以外が書き換わらない。ほかの文書の[文書情報]は変わらない
        info_after = self.info(ID_C)
        self.assertEqual(info_after["path"], "docs/sub/c.md")
        self.assertEqual(
            {k: v for k, v in info_after.items() if k != "path"},
            {k: v for k, v in info_before.items() if k != "path"},
        )
        for doc_id, before in info_other_before.items():
            self.assertEqual(self.info(doc_id), before)
        # [確定 ToC]の現在パス（対象指定のパス）だけが更新される。文書の集合・ハッシュは変わらない
        toc_after = self.toc(KEY)
        self.assertEqual(toc_before["target_spec"]["paths"], PATHS)
        self.assertEqual(toc_after["target_spec"]["paths"], paths)
        self.assertEqual(toc_after["documents"], toc_before["documents"])
        self.assertEqual(toc_after["sections"], toc_before["sections"])
        self.assertEqual(self.resolve_one(ID_C)["path"], "docs/sub/c.md")
        code, fresh = self.check_toc(KEY, paths)
        self.assertEqual((code, fresh["status"]), (0, "up_to_date"))

        # 参照元の古いパスは自動修正されない（参照元のバイトは変わらない）
        self.assertEqual(self.read("docs/a.md"), a_text())
        self.assertIn('[c]: c.md "', self.read("docs/a.md"))
        self.assertEqual(self.snapshot("docs").keys(), documents_before.keys())
        self.assertEqual(
            self.snapshot("docs")["docs/a.md"], documents_before["docs/a.md"]
        )
        # 参照元の記録は旧パスのまま[確定 ToC]に残り、実走査でも新パスへ書き換わらない
        recorded = {r["recorded_path"] for r in toc_after["references"]}
        self.assertEqual(recorded, {"c.md"})

    def test_scenario_2_rerun_after_move_changes_nothing(self):
        self.build_ok(KEY, PATHS)
        paths = self.move_c()
        self.build_ok(KEY, paths)
        state_before = self.state_snapshot()
        result = self.build_ok(KEY, paths)
        self.assertEqual(self.requested, [])
        self.assertFalse(result["published"])
        self.assertEqual(self.state_snapshot(), state_before)


class ContentChangeScenarioTest(ScenarioBase):
    """シナリオ 3: 参照先を変えると、参照元の記録は旧値のまま。記録を書き換えるまで毎回同じ参照を返す。"""

    def setUp(self):
        super().setUp()
        self.paths = ["docs/a.md", "docs/b.md", "docs/c.md"]
        self.write("docs/b.md", B_TEXT)
        self.write("docs/c.md", C_TEXT)
        # 参照元 A は、C の[内容ハッシュ]を title に記録する。記録は、構築後に resolve-dlid の値へ揃える
        self.write("docs/a.md", a_text())
        self.build_ok(KEY, self.paths)
        self.c_hash_before = self.resolve_one(ID_C)["content_hash"]
        self.write("docs/a.md", a_text(record=self.c_hash_before))
        self.build_ok(KEY, self.paths)

    def test_recorded_hash_matching_current_hash_is_not_returned(self):
        self.assertEqual(self.impact_documents(KEY, self.paths), [])

    def test_scenario_3_same_reference_until_the_record_is_rewritten(self):
        a_before = self.read("docs/a.md")
        self.write("docs/c.md", doc_text(ID_C, "C", "body of c, changed", S_C))
        # 本文が変わった文書は、要約の再生成が必要になる（記録の書き換えだけの場合と区別する）
        result = self.build_ok(KEY, self.paths)
        self.assertEqual(self.requested, [ID_C])
        self.assertEqual(result["generated_count"], 1)
        detail = json.loads(Path(result["detail_path"]).read_text(encoding="utf-8"))
        self.assertEqual(detail["generated_documents"], [ID_C])
        c_hash_after = self.resolve_one(ID_C)["content_hash"]
        self.assertNotEqual(c_hash_after, self.c_hash_before)

        # 構築後も、参照元の記録は旧値のまま
        self.assertEqual(self.read("docs/a.md"), a_before)
        self.assertIn(self.c_hash_before, self.read("docs/a.md"))
        self.assertEqual(
            {r["recorded_content_hash"] for r in self.toc(KEY)["references"]},
            {self.c_hash_before},
        )

        # check-impact は、記録を書き換えるまで、再構築・再実行を挟んでも毎回同じ参照を返す
        state_before = self.state_snapshot()
        documents_before = self.snapshot("docs")
        expected = [(ID_C, self.c_hash_before, c_hash_after)]
        self.assertEqual(self.impact_documents(KEY, self.paths), expected)
        self.assertEqual(self.impact_documents(KEY, self.paths), expected)
        code, changed = self.check_impact(KEY, self.paths)
        self.assertEqual(
            [
                (d["doc_link_id"], r["source_doc_id"])
                for d in changed["changed_documents"]
                for r in d["referrers"]
            ],
            [(ID_C, ID_A)],
        )
        self.assertEqual(self.state_snapshot(), state_before)
        self.assertEqual(self.snapshot("docs"), documents_before)
        # 再構築（変更が無いので生成依頼は 0 件）を挟んでも同じ
        self.build_ok(KEY, self.paths)
        self.assertEqual(self.requested, [])
        self.assertEqual(self.impact_documents(KEY, self.paths), expected)
        self.assertEqual(self.read("docs/a.md"), a_before)

        # 記録だけを書き換える（title の記録の語だけ）
        self.write("docs/a.md", a_text(record=c_hash_after))
        # ToC は古いと判定されず、index-docs を実行せずに、同じ参照が返らなくなる
        code, fresh = self.check_toc(KEY, self.paths)
        self.assertEqual((code, fresh["status"]), (0, "up_to_date"))
        self.assertEqual(self.impact_documents(KEY, self.paths), [])
        # 記録の書き換えのための再構築は、要約の生成を依頼しない（[確定 ToC]の記録だけが更新される）
        result = self.build_ok(KEY, self.paths)
        self.assertEqual(self.requested, [])
        self.assertEqual(result["generated_count"], 0)
        self.assertEqual(
            {r["recorded_content_hash"] for r in self.toc(KEY)["references"]},
            {c_hash_after},
        )
        self.assertEqual(self.impact_documents(KEY, self.paths), [])
        # 参照先 C の[文書情報]（要約）は、記録の書き換えでは再生成されない
        self.assertEqual(self.resolve_one(ID_C)["content_hash"], c_hash_after)

    def test_rewriting_a_record_does_not_change_the_referrer_hash(self):
        info_before = self.info(ID_A)
        self.write("docs/a.md", a_text(record="d" * RECORD_LENGTH))
        code, fresh = self.check_toc(KEY, self.paths)
        self.assertEqual((code, fresh["status"]), (0, "up_to_date"))
        self.build_ok(KEY, self.paths)
        self.assertEqual(self.requested, [])
        self.assertEqual(self.info(ID_A), info_before)


class FirstTitleScenarioTest(ScenarioBase):
    """参照の title を初めて書いても、書いた文書の内容ハッシュは変わらず、書いた記録は書いた直後から正しい。

    title に書く[内容ハッシュ]は、参照先の現在ハッシュ（`resolve-dlid` の値）である。title を書くことで書いた文書
    自身のハッシュが変わると、その文書を参照する文書の記録が古くなり、書き直しが要る。
    """

    def setUp(self):
        super().setUp()
        self.paths = ["docs/a.md", "docs/b.md", "docs/c.md"]
        self.write("docs/b.md", B_TEXT)
        self.write("docs/c.md", C_TEXT)
        # 参照元 A は、title の無い定義で C を指す（[正式な参照]ではない）
        self.write("docs/a.md", doc_text(ID_A, "A", "[to c][c]\n\n[c]: c.md", S_A))
        self.build_ok(KEY, self.paths)

    def test_first_title_keeps_the_referrer_hash_and_the_record_is_correct(self):
        info_before = self.info(ID_A)
        c_hash = self.resolve_one(ID_C)["content_hash"]

        self.write("docs/a.md", a_text(record=c_hash))
        # 参照が現れるので[ToC]は更新が要るが、A の本文は変わらないので要約の生成は要らない
        code, stale = self.check_toc(KEY, self.paths)
        self.assertEqual((code, stale["status"]), (0, "rebuild_needed"))
        self.assertEqual(stale["counts"]["content_changed"], 0)
        self.assertEqual(stale["counts"]["references_changed"], 1)
        result = self.build_ok(KEY, self.paths)
        self.assertEqual(self.requested, [])
        self.assertEqual(result["generated_count"], 0)
        self.assertEqual(self.info(ID_A), info_before)

        # 書いた記録は、書き直さずに、そのまま正しい
        code, fresh = self.check_toc(KEY, self.paths)
        self.assertEqual((code, fresh["status"]), (0, "up_to_date"))
        self.assertEqual(self.impact_documents(KEY, self.paths), [])

    def test_retargeting_the_title_is_detected_as_a_reference_change(self):
        c_hash = self.resolve_one(ID_C)["content_hash"]
        self.write("docs/a.md", a_text(record=c_hash))
        self.build_ok(KEY, self.paths)

        self.write("docs/a.md", a_text(record=c_hash, target=ID_B))
        code, stale = self.check_toc(KEY, self.paths)
        self.assertEqual((code, stale["status"]), (0, "rebuild_needed"))
        self.assertEqual(stale["counts"]["references_changed"], 1)
        self.assertEqual(stale["counts"]["content_changed"], 0)


if __name__ == "__main__":
    unittest.main()
