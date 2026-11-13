"""横断シナリオ 6（範囲外参照）（DES-009 §3、受け入れ基準 1）。

[Index 対象文書]の外にある文書への参照でも、指定ディレクトリを実走査し、結果に範囲・時点を付ける。
対象範囲外へ移動した参照先の移動先は推測せず、不在として記録する。参照先のディレクトリが無い・読めない
ときも、構築は止まらず、不在として記録される（決定 U-020）。AI の生成は固定値の差し込みで代替する。
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scenario_support import (  # noqa: E402
    ID_A,
    S_A,
    ScenarioBase,
    doc_text,
)

KEY = "k"
PATHS = ["docs/a.md"]
ID_X = "DLID-0000000000x1"
ID_M = "DLID-0000000000m1"
ID_N = "DLID-0000000000n1"
ID_Y = "DLID-0000000000y1"
REFERENCES = (
    ("x", "../ext/x.md", ID_X),
    ("m", "../ext/m.md", ID_M),
    ("n", "../nodir/n.md", ID_N),
    ("y", "../locked/y.md", ID_Y),
)
A_TEXT = doc_text(
    ID_A,
    "A",
    " ".join(f"[{label}][{label}]" for label, _, _ in REFERENCES)
    + "\n\n"
    + "\n".join(f'[{label}]: {path} "{dlid}"' for label, path, dlid in REFERENCES),
    S_A,
)
X_TEXT = doc_text(ID_X, "X", "body of x")
M_TEXT = doc_text(ID_M, "M", "body of m")
Y_TEXT = doc_text(ID_Y, "Y", "body of y")


class OutOfScopeReferenceScenarioTest(ScenarioBase):
    def setUp(self):
        super().setUp()
        self.write("docs/a.md", A_TEXT)
        self.write("ext/x.md", X_TEXT)
        self.write("ext/m.md", M_TEXT)

    def references(self):
        return {r["target_doc_id"]: r for r in self.toc(KEY)["references"]}

    def lock(self, directory):
        locked = self.root / directory
        locked.chmod(0o000)
        self.addCleanup(locked.chmod, 0o755)

    def test_scenario_6_scan_result_has_scope_and_time_for_out_of_target_documents(
        self,
    ):
        before = self.snapshot("docs", "ext")
        result = self.build_ok(KEY, PATHS)
        # Index 対象外の ext/x.md は、[Index 対象リスト]に入らないが、実走査で見つかる
        self.assertEqual([d["doc_link_id"] for d in self.toc(KEY)["documents"]], [ID_A])
        found = self.references()[ID_X]["check"]
        self.assertEqual(found["result"], "match")
        self.assertEqual(found["found_path"], "ext/x.md")
        self.assertEqual(found["scope"], "ext")
        self.assertRegex(
            found["checked_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$"
        )
        # 同じ範囲・時点が、構築の結果にも付く
        for finding in result["reference_check"]["findings"]:
            self.assertIn("directory", finding["scope"])
            self.assertEqual(
                finding["scope"]["checked_at"],
                self.references()[finding["reference"]["dlid"]]["check"]["checked_at"],
            )
        # 参照元・参照先の文書は書き換わらない
        self.assertEqual(self.snapshot("docs", "ext"), before)

    def test_scenario_6_target_moved_outside_the_scope_is_absent_and_not_guessed(self):
        self.build_ok(KEY, PATHS)
        self.assertEqual(self.references()[ID_M]["check"]["result"], "match")
        # 指定ディレクトリの外へ移動する。移動先は、プロジェクト内にあっても探さない
        self.write("elsewhere/m.md", M_TEXT)
        (self.root / "ext" / "m.md").unlink()
        documents_before = self.snapshot("docs")
        result = self.build_ok(KEY, PATHS)
        absent = self.references()[ID_M]["check"]
        self.assertEqual(absent["result"], "absent")
        self.assertIsNone(absent["found_path"])
        self.assertEqual(absent["scope"], "ext")
        finding = next(
            f
            for f in result["reference_check"]["findings"]
            if f["reference"]["dlid"] == ID_M
        )
        self.assertEqual(finding["status"], "absent")
        self.assertEqual(finding["absent_reason"], "not_found")
        self.assertIsNone(finding["current_path"])
        # check-links も、移動先を現在のパスとして示さない
        code, links = self.check_links(KEY, PATHS)
        self.assertEqual(code, 0, links)
        reported = next(f for f in links["findings"] if f["dlid"] == ID_M)
        self.assertEqual(reported["category"], "absent")
        self.assertNotIn("elsewhere", str(reported))
        # 参照元は書き換わらない（移動先を書き込まない）
        self.assertEqual(self.snapshot("docs"), documents_before)

    def test_scenario_6_missing_directory_is_recorded_as_absent(self):
        result = self.build_ok(KEY, PATHS)
        absent = self.references()[ID_N]["check"]
        self.assertEqual(absent["result"], "absent")
        self.assertEqual(absent["scope"], "nodir")
        reasons = {
            f["reference"]["dlid"]: f["absent_reason"]
            for f in result["reference_check"]["findings"]
        }
        self.assertEqual(reasons[ID_N], "directory_missing")
        self.assertFalse((self.root / "nodir").exists())

    def test_scenario_6_unreadable_directory_does_not_stop_the_build(self):
        if os.geteuid() == 0:
            self.skipTest("root は権限で読めなくならない")
        self.write("locked/y.md", Y_TEXT)
        self.lock("locked")
        result = self.build_ok(KEY, PATHS)
        absent = self.references()[ID_Y]["check"]
        self.assertEqual(absent["result"], "absent")
        self.assertEqual(absent["scope"], "locked")
        reasons = {
            f["reference"]["dlid"]: f["absent_reason"]
            for f in result["reference_check"]["findings"]
        }
        self.assertEqual(reasons[ID_Y], "directory_unreadable")
        self.assertTrue(self.toc_bytes(KEY))

    def test_scenario_6_rerun_with_unchanged_scan_keeps_the_toc(self):
        self.build_ok(KEY, PATHS)
        state_before = self.state_snapshot()
        result = self.build_ok(KEY, PATHS)
        self.assertFalse(result["published"])
        self.assertEqual(self.state_snapshot(), state_before)


if __name__ == "__main__":
    unittest.main()
