"""`docdb_contract`（[doc-db]に求める契約に基づく失敗の分類）のテスト。AC-039・AC-040・AC-049。"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import docdb_contract as c  # noqa: E402


class MarkerTest(unittest.TestCase):
    def test_the_marker_is_document_errors_in_the_job(self):
        self.assertTrue(c.job_meets_contract({"status": "done", "document_errors": []}))
        self.assertFalse(c.job_meets_contract({"status": "done", "errors": []}))
        self.assertFalse(c.job_meets_contract(None))
        self.assertFalse(c.job_meets_contract("x"))


class ToolErrorTest(unittest.TestCase):
    def test_identifiers_classify_regardless_of_the_contract(self):
        for met in (True, False):
            with self.subTest(met=met):
                self.assertEqual(
                    c.classify_tool_error("EMBEDDING_FAILED", -32603, met),
                    (c.KIND_OPENAI, False),
                )
                for identifier in (
                    "INTERNAL_ERROR",
                    "KEY_NOT_FOUND",
                    "KEY_TRASHED",
                    "SOMETHING_NEW",
                ):
                    self.assertEqual(
                        c.classify_tool_error(identifier, -32603, met),
                        (c.KIND_FAULT, False),
                    )

    def test_an_internal_error_without_an_identifier_depends_on_the_contract(self):
        self.assertEqual(
            c.classify_tool_error(None, -32603, False), (c.KIND_OPENAI, True)
        )
        self.assertEqual(
            c.classify_tool_error(None, -32603, True), (c.KIND_FAULT, False)
        )

    def test_other_errors_without_an_identifier_are_faults(self):
        # 入力の不正（-32602）には識別子が付かない
        for met in (True, False):
            self.assertEqual(
                c.classify_tool_error(None, -32602, met), (c.KIND_FAULT, False)
            )
            self.assertEqual(
                c.classify_tool_error(None, None, met), (c.KIND_FAULT, False)
            )


class JobTest(unittest.TestCase):
    def test_a_job_without_failures_is_clean(self):
        for job in (
            {"status": "done"},
            {"status": "done", "errors": []},
            {"status": "done", "errors": [], "document_errors": []},
        ):
            self.assertEqual(c.classify_job(job)[0], None)

    def test_document_errors_are_read_by_their_codes(self):
        job = {
            "document_errors": [
                {"path": "a.md", "code": "EMBEDDING_FAILED", "skipped_chunks": [0]}
            ]
        }
        self.assertEqual(
            c.classify_job(job), (c.KIND_OPENAI, False, ["EMBEDDING_FAILED"])
        )
        job = {"document_errors": [{"path": "a.md", "code": "INTERNAL_ERROR"}]}
        self.assertEqual(c.classify_job(job)[0], c.KIND_FAULT)

    def test_an_embedding_failure_wins_over_other_codes(self):
        job = {
            "document_errors": [
                {"path": "a.md", "code": "INTERNAL_ERROR"},
                {"path": "b.md", "code": "EMBEDDING_FAILED"},
            ]
        }
        self.assertEqual(c.classify_job(job)[0], c.KIND_OPENAI)

    def test_document_errors_without_codes_are_faults(self):
        job = {"document_errors": [{"path": "a.md"}]}
        self.assertEqual(c.classify_job(job)[0], c.KIND_FAULT)

    def test_text_errors_of_a_job_that_meets_the_contract_are_faults(self):
        job = {"document_errors": [], "errors": ['path "docs/a.md": embed: x']}
        self.assertEqual(c.classify_job(job)[0], c.KIND_FAULT)

    def test_text_errors_are_read_only_when_the_marker_is_absent(self):
        job = {
            "errors": ['path "docs/a.md": embed: Embedding API を呼び出せませんでした']
        }
        self.assertEqual(c.classify_job(job)[:2], (c.KIND_OPENAI, True))

    def test_other_text_errors_are_faults(self):
        job = {"errors": ['path "a.md": local_path を解決できません']}
        self.assertEqual(c.classify_job(job)[0], c.KIND_FAULT)

    def test_labels_never_contain_the_error_text(self):
        for job in (
            {"errors": ['path "a.md": embed: secret detail']},
            {"errors": ["secret detail"]},
            {"document_errors": [], "errors": ["secret detail"]},
        ):
            labels = c.classify_job(job)[2]
            self.assertNotIn("secret", "".join(labels))


if __name__ == "__main__":
    unittest.main()
