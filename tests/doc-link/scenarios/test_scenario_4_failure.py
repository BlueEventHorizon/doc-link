"""横断シナリオ 4（失敗）（DES-009 §3、受け入れ基準 1）。

AI 生成・参照走査・候補確定の各失敗位置で、旧[確定 ToC]の扱いを区別する。それまでに確定した[文書情報]は
戻さず、[ToC]が旧版のキーからも最新の[文書情報]が見える（要件 D-024）。失敗は、入口 script
（`index_docs`）を通して起こす。AI の生成は固定値の差し込みで代替する。
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scenario_support import (  # noqa: E402
    FIXED,
    ID_A,
    ID_B,
    ID_C,
    S_A,
    S_B,
    S_C,
    ScenarioBase,
    doc_text,
    index_docs,
    state_store,
)

import toc_candidate  # noqa: E402
from reference_check import ReferenceCheckError  # noqa: E402

KEY = "k"
PATHS = ["docs/a.md", "docs/b.md", "docs/c.md"]
A_TEXT = doc_text(ID_A, "A", "body of a", S_A)
B_TEXT = doc_text(ID_B, "B", "body of b", S_B)
B_CHANGED = doc_text(ID_B, "B", "body of b, changed", S_B)
C_TEXT = doc_text(ID_C, "C", "body of c", S_C)
NEW_VALUES = {**FIXED, "purpose": "新しい目的"}
TOO_LONG = {**FIXED, "purpose": "あ" * 300}


class FailureScenarioBase(ScenarioBase):
    def setUp(self):
        super().setUp()
        self.write("docs/a.md", A_TEXT)
        self.write("docs/b.md", B_TEXT)
        self.write("docs/c.md", C_TEXT)

    def request_generation(self, expected=(ID_B,)):
        """B を変更して構築を始め、依頼された構築 ID を返す。`expected` は依頼される[文書 ID]。"""
        self.write("docs/b.md", B_CHANGED)
        code, invoked = self.advance(KEY, PATHS)
        self.assertEqual(code, 0, invoked)
        self.assertEqual(
            [d["doc_link_id"] for b in invoked["batches"] for d in b["documents"]],
            list(expected),
        )
        return invoked["build_id"]

    def failure_result(self, build_id, failure_patch):
        """B の生成結果を差し込み、`failure_patch` の下で構築を完了させようとする。"""
        code, stored = self.submit(KEY, PATHS, build_id, ID_B, NEW_VALUES)
        self.assertEqual(code, 0, stored)
        with failure_patch:
            return self.advance(KEY, PATHS, "--build-id", build_id)

    def assert_failed_keeping_old_toc(self, code, result, stage, toc_before):
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED, result)
        self.assertEqual(result["stage"], stage)
        self.assertEqual(result["state"], "失敗")
        self.assertTrue(result["confirmed_toc_present"])
        self.assertEqual(self.toc_bytes(KEY), toc_before)

    def assert_latest_info_is_visible(self, toc_before_version):
        """確定済みの[文書情報]は戻らず、旧版の[確定 ToC]のキーからも最新の[文書情報]が見える（D-024）。"""
        info = self.info(ID_B)
        self.assertEqual(info["purpose"], "新しい目的")
        resolved = self.resolve_one(ID_B)
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["content_hash"], info["content_hash"])
        # 旧版の[確定 ToC]が反映している[内容ハッシュ]は、最新の[文書情報]と異なる
        entry = next(d for d in self.toc(KEY)["documents"] if d["doc_link_id"] == ID_B)
        self.assertNotEqual(entry["applied_hash"], info["content_hash"])
        self.assertEqual(self.toc(KEY)["version"], toc_before_version)


class GenerationFailureScenarioTest(FailureScenarioBase):
    """AI 生成の失敗（生成結果の拒否・欠落）。"""

    def test_scenario_4_rejected_generation_keeps_old_toc_and_saved_info(self):
        self.build_ok(KEY, PATHS)
        toc_before = self.toc_bytes(KEY)
        self.write("docs/c.md", doc_text(ID_C, "C", "body of c, changed", S_C))
        build_id = self.request_generation((ID_B, ID_C))
        # 検証に通った B は保存され、通らなかった C は旧版のまま
        info_c_before = self.info(ID_C)
        code, _ = self.submit(KEY, PATHS, build_id, ID_B, NEW_VALUES)
        self.assertEqual(code, 0)
        code, rejected = self.submit(KEY, PATHS, build_id, ID_C, TOO_LONG)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertEqual(rejected["stage"], "information")
        code, result = self.advance(KEY, PATHS, "--build-id", build_id)
        self.assert_failed_keeping_old_toc(code, result, "information", toc_before)
        self.assertEqual([p["doc_link_id"] for p in result["problems"]], [ID_C])
        self.assert_latest_info_is_visible(1)
        self.assertEqual(self.info(ID_C), info_c_before)

    def test_scenario_4_first_build_rejection_creates_no_toc(self):
        build_id = self.advance(KEY, PATHS)[1]["build_id"]
        code, _ = self.submit(KEY, PATHS, build_id, ID_A)
        self.assertEqual(code, 0)
        code, _ = self.submit(KEY, PATHS, build_id, ID_B, TOO_LONG)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        code, result = self.advance(KEY, PATHS, "--build-id", build_id)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED, result)
        self.assertEqual(result["stage"], "information")
        self.assertFalse(result["confirmed_toc_present"])
        self.assertFalse(state_store.confirmed_toc_path(self.root, KEY).exists())
        # 検証に通った A の[文書情報]は戻らない
        self.assertEqual(self.info(ID_A)["purpose"], FIXED["purpose"])
        code, resolved = self.resolve(ID_A)
        self.assertEqual(resolved["results"][0]["status"], "resolved")

    def test_scenario_4_missing_generation_keeps_old_toc(self):
        self.build_ok(KEY, PATHS)
        toc_before = self.toc_bytes(KEY)
        build_id = self.request_generation()
        # 生成結果が届かないまま、構築を進めようとする
        code, result = self.advance(KEY, PATHS, "--build-id", build_id)
        self.assert_failed_keeping_old_toc(code, result, "information", toc_before)
        self.assertEqual([p["doc_link_id"] for p in result["problems"]], [ID_B])

    def test_scenario_4_first_build_missing_generation_creates_no_toc(self):
        build_id = self.advance(KEY, PATHS)[1]["build_id"]
        self.submit(KEY, PATHS, build_id, ID_A)
        code, result = self.advance(KEY, PATHS, "--build-id", build_id)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertFalse(result["confirmed_toc_present"])
        self.assertFalse(state_store.confirmed_toc_path(self.root, KEY).exists())

    def test_scenario_4_source_unreadable_exit_value_fails_the_generation(self):
        self.build_ok(KEY, PATHS)
        toc_before = self.toc_bytes(KEY)
        build_id = self.request_generation()
        code, delivered = self.run_script(
            index_docs,
            "--build-id",
            build_id,
            "--doc-id",
            ID_B,
            "--exit-value",
            "source_unreadable",
            command="deliver",
        )
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED, delivered)
        code, result = self.advance(KEY, PATHS, "--build-id", build_id)
        self.assert_failed_keeping_old_toc(code, result, "information", toc_before)

    def test_scenario_4_rerun_after_failure_resumes_without_regenerating_stored_info(
        self,
    ):
        self.build_ok(KEY, PATHS)
        build_id = self.request_generation()
        self.submit(KEY, PATHS, build_id, ID_B, NEW_VALUES)
        code, _ = self.advance(KEY, PATHS)
        # 結果を受け取り済みなので、生成を依頼せずに確定する（B-09）
        self.assertEqual(code, 0)
        self.assertEqual(self.toc(KEY)["version"], 2)
        self.assertEqual(self.info(ID_B)["purpose"], "新しい目的")


class ReferenceScanFailureScenarioTest(FailureScenarioBase):
    """参照走査の失敗。"""

    def scan_failure(self):
        return mock.patch.object(
            index_docs,
            "check_document",
            side_effect=ReferenceCheckError("参照元を読めない"),
        )

    def test_scenario_4_scan_failure_keeps_old_toc(self):
        self.build_ok(KEY, PATHS)
        toc_before = self.toc_bytes(KEY)
        build_id = self.request_generation()
        code, result = self.failure_result(build_id, self.scan_failure())
        self.assert_failed_keeping_old_toc(code, result, "reference_check", toc_before)
        self.assertEqual(result["failed_from"], "情報確定")
        self.assert_latest_info_is_visible(1)

    def test_scenario_4_first_build_scan_failure_creates_no_toc(self):
        build_id = self.advance(KEY, PATHS)[1]["build_id"]
        for doc_id in (ID_A, ID_B, ID_C):
            self.submit(KEY, PATHS, build_id, doc_id, NEW_VALUES)
        with self.scan_failure():
            code, result = self.advance(KEY, PATHS, "--build-id", build_id)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED, result)
        self.assertEqual(result["stage"], "reference_check")
        self.assertFalse(result["confirmed_toc_present"])
        self.assertFalse(state_store.confirmed_toc_path(self.root, KEY).exists())
        self.assertEqual(self.info(ID_C)["purpose"], "新しい目的")


class CandidateFailureScenarioTest(FailureScenarioBase):
    """候補確定（検査・公開）の失敗。"""

    def validation_failure(self, confirmed_toc_present):
        failure = toc_candidate.CandidateFailure(
            toc_candidate.FailureReport(
                toc_candidate.STAGE_VALIDATION,
                (toc_candidate.CandidateProblem(ID_B, "docs/b.md", None, "検査失敗"),),
                confirmed_toc_present,
            )
        )
        return mock.patch.object(
            toc_candidate, "validate_candidate", side_effect=failure
        )

    def test_scenario_4_candidate_validation_failure_keeps_old_toc(self):
        self.build_ok(KEY, PATHS)
        toc_before = self.toc_bytes(KEY)
        build_id = self.request_generation()
        code, result = self.failure_result(build_id, self.validation_failure(True))
        self.assert_failed_keeping_old_toc(
            code, result, "candidate_validation", toc_before
        )
        self.assertEqual(result["failed_from"], "参照検査確定")
        self.assert_latest_info_is_visible(1)
        # 再実行（B-09）で、生成せずに確定し、[確定 ToC]が最新の[文書情報]に追いつく
        result = self.build_ok(KEY, PATHS)
        self.assertEqual(self.requested, [])
        self.assertEqual(result["version"], 2)
        entry = next(d for d in self.toc(KEY)["documents"] if d["doc_link_id"] == ID_B)
        self.assertEqual(entry["applied_hash"], self.info(ID_B)["content_hash"])

    def test_scenario_4_publish_failure_keeps_old_toc(self):
        self.build_ok(KEY, PATHS)
        toc_before = self.toc_bytes(KEY)
        build_id = self.request_generation()
        error = state_store.StateStoreError(state_store.KIND_WRITE, "置き換え失敗")
        code, result = self.failure_result(
            build_id,
            mock.patch.object(state_store, "save_confirmed_toc", side_effect=error),
        )
        self.assert_failed_keeping_old_toc(code, result, "publish", toc_before)
        self.assertEqual(result["failed_from"], "候補検査済み")
        self.assert_latest_info_is_visible(1)

    def test_scenario_4_first_build_candidate_failure_creates_no_toc(self):
        build_id = self.advance(KEY, PATHS)[1]["build_id"]
        for doc_id in (ID_A, ID_B, ID_C):
            self.submit(KEY, PATHS, build_id, doc_id, NEW_VALUES)
        with self.validation_failure(False):
            code, result = self.advance(KEY, PATHS, "--build-id", build_id)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED, result)
        self.assertEqual(result["stage"], "candidate_validation")
        self.assertFalse(result["confirmed_toc_present"])
        self.assertFalse(state_store.confirmed_toc_path(self.root, KEY).exists())
        self.assertEqual(self.info(ID_A)["purpose"], "新しい目的")

    def test_scenario_4_first_build_publish_failure_creates_no_toc(self):
        build_id = self.advance(KEY, PATHS)[1]["build_id"]
        for doc_id in (ID_A, ID_B, ID_C):
            self.submit(KEY, PATHS, build_id, doc_id, NEW_VALUES)
        error = state_store.StateStoreError(state_store.KIND_WRITE, "置き換え失敗")
        with mock.patch.object(state_store, "save_confirmed_toc", side_effect=error):
            code, result = self.advance(KEY, PATHS, "--build-id", build_id)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED, result)
        self.assertEqual(result["stage"], "publish")
        self.assertFalse(result["confirmed_toc_present"])
        self.assertFalse(state_store.confirmed_toc_path(self.root, KEY).exists())


if __name__ == "__main__":
    unittest.main()
