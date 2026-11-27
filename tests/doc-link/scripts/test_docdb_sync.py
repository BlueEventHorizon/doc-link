"""`docdb_sync`（[確定 ToC]から作った一覧の[doc-db]への同期）のテスト。AC-039・AC-040・AC-043。"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import change_set  # noqa: E402
import docdb_client  # noqa: E402
import docdb_sync as sync  # noqa: E402
import state_store  # noqa: E402
import toc_candidate  # noqa: E402
from content_hash import document_content_hash  # noqa: E402
from reference_check import check_document  # noqa: E402
from target_spec import MODE_TARGETS, TargetSpec  # noqa: E402

KEY = "k"
ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
WHEN = "2026-11-13T00:00:00+00:00"
TEXTS = {
    "a.md": f"---\ndoc_link_id: {ID_A}\n---\n# A DLID-00000000s001\n\nbody\n",
    "b.md": f"---\ndoc_link_id: {ID_B}\n---\n# B DLID-00000000s002\n",
}


def no_git(arguments, cwd):
    return 128, ""


class FakeClient:
    """`sync_documents` と `get_sync_status` を模す。`jobs` は状態の応答（dict か例外）を順に返す。"""

    def __init__(self, jobs, start=None):
        self.jobs = list(jobs)
        self.start = start if start is not None else {"job_id": "J1"}
        self.synced = []

    def sync_documents(self, key, series, documents):
        self.synced.append((key, series, documents))
        if isinstance(self.start, Exception):
            raise self.start
        return self.start

    def get_sync_status(self, job_id):
        step = self.jobs.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.sleeps = []

    def build(self, paths=("a.md", "b.md")):
        for path in paths:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(TEXTS[path], encoding="utf-8")
        for path, doc_id in (("a.md", ID_A), ("b.md", ID_B)):
            if path not in paths:
                continue
            state_store.save_document_info(
                self.root,
                "test",
                {
                    "doc_link_id": doc_id,
                    "path": path,
                    "title": path,
                    "purpose": "",
                    "summary": [],
                    "tasks": [],
                    "keywords": [],
                    "content_hash": document_content_hash(TEXTS[path]),
                },
            )
        spec = TargetSpec(mode=MODE_TARGETS, key=KEY, paths=tuple(paths))
        cs = change_set.build_change_set(self.root, KEY, list(paths))
        results = {
            item.doc_link_id: check_document(self.root, item.path, checked_at=WHEN)
            for item in cs.confirmed_documents
        }
        toc_candidate.build_and_publish(self.root, "test", KEY, spec, cs, results)

    def run_sync(self, client, **kwargs):
        return sync.run_sync(
            client,
            self.root,
            KEY,
            sleep=self.sleeps.append,
            runner=no_git,
            **kwargs,
        )


class DocumentListTest(Base):
    def test_the_list_comes_from_the_confirmed_toc_with_relative_and_absolute_paths(
        self,
    ):
        self.build()
        listed = sync.build_document_list(self.root, KEY)
        self.assertEqual([d["path"] for d in listed.documents], ["a.md", "b.md"])
        self.assertEqual(listed.documents[0]["local_path"], str(self.root / "a.md"))
        self.assertEqual(listed.path_to_doc, {"a.md": ID_A, "b.md": ID_B})
        self.assertEqual(listed.missing, ())
        self.assertEqual(set(listed.documents[0]), {"path", "local_path"})

    def test_a_deleted_file_is_left_out_and_reported(self):
        self.build()
        (self.root / "b.md").unlink()
        listed = sync.build_document_list(self.root, KEY)
        self.assertEqual([d["path"] for d in listed.documents], ["a.md"])
        self.assertEqual(listed.missing, ("b.md",))

    def test_a_moved_file_is_listed_under_its_recorded_path_only(self):
        self.build()
        (self.root / "b.md").rename(self.root / "moved.md")
        listed = sync.build_document_list(self.root, KEY)
        self.assertEqual(listed.missing, ("b.md",))
        self.assertNotIn("moved.md", listed.path_to_doc)

    def test_a_missing_toc_is_a_state_error(self):
        with self.assertRaises(state_store.StateStoreError):
            sync.build_document_list(self.root, KEY)


class RunSyncTest(Base):
    def test_a_clean_job_is_synced_and_sends_the_whole_list(self):
        self.build()
        client = FakeClient(
            [{"status": "done", "processed": 2, "skipped": 0, "failed": 0}]
        )
        outcome = self.run_sync(client)
        self.assertEqual(outcome.status, sync.STATUS_SYNCED)
        self.assertEqual(outcome.listed, 2)
        self.assertEqual(outcome.counts, {"processed": 2, "skipped": 0, "failed": 0})
        key, series, documents = client.synced[0]
        self.assertTrue(key.startswith("doc-link."))
        self.assertEqual([d["path"] for d in documents], ["a.md", "b.md"])

    def test_the_empty_list_is_still_sent(self):
        self.build(paths=())
        client = FakeClient([{"status": "done"}])
        self.assertEqual(self.run_sync(client).status, sync.STATUS_SYNCED)
        self.assertEqual(client.synced[0][2], [])

    def test_it_waits_while_the_job_is_running(self):
        self.build()
        client = FakeClient(
            [{"status": "running"}, {"status": "running"}, {"status": "done"}]
        )
        clock = iter(range(100))
        outcome = self.run_sync(client, now=lambda: next(clock), wait_limit=50)
        self.assertEqual(outcome.status, sync.STATUS_SYNCED)
        self.assertEqual(len(self.sleeps), 2)

    def test_exceeding_the_wait_limit_is_a_fault_not_a_switch(self):
        self.build()
        client = FakeClient([{"status": "running"}] * 100)
        ticks = iter(range(0, 1000, 10))
        outcome = self.run_sync(client, now=lambda: next(ticks), wait_limit=25)
        self.assertEqual(outcome.status, sync.STATUS_FAILED)
        self.assertIn("完了しなかった", outcome.errors[0])

    def test_an_embedding_failure_in_a_done_job_switches_for_openai(self):
        self.build()
        job = {
            "status": "done",
            "failed": 0,
            "errors": ['path "a.md": embed: failed'],
        }
        outcome = self.run_sync(FakeClient([job]))
        self.assertEqual(outcome.status, sync.STATUS_SWITCH)
        self.assertEqual(outcome.reason_code, sync.REASON_OPENAI_FAILED)
        self.assertTrue(outcome.presumed)
        self.assertFalse(outcome.contract_met)
        self.assertNotIn("failed", outcome.cause.replace("失敗", ""))

    def test_identifiers_make_the_switch_certain(self):
        self.build()
        job = {
            "status": "done",
            "errors": ['path "a.md": embed: x'],
            "document_errors": [{"path": "a.md", "code": "EMBEDDING_FAILED"}],
        }
        outcome = self.run_sync(FakeClient([job]))
        self.assertEqual(outcome.status, sync.STATUS_SWITCH)
        self.assertFalse(outcome.presumed)
        self.assertTrue(outcome.contract_met)

    def test_a_failed_job_with_the_embedding_identifier_switches(self):
        self.build()
        outcome = self.run_sync(
            FakeClient([{"status": "failed", "code": "EMBEDDING_FAILED"}])
        )
        self.assertEqual(outcome.status, sync.STATUS_SWITCH)
        outcome = self.run_sync(
            FakeClient([{"status": "failed", "code": "INTERNAL_ERROR"}])
        )
        self.assertEqual(outcome.status, sync.STATUS_FAILED)
        self.assertIn("INTERNAL_ERROR", outcome.errors[0])

    def test_a_clean_job_with_the_marker_reports_the_contract_as_met(self):
        self.build()
        outcome = self.run_sync(FakeClient([{"status": "done", "document_errors": []}]))
        self.assertEqual(outcome.status, sync.STATUS_SYNCED)
        self.assertTrue(outcome.contract_met)
        self.assertTrue(outcome.to_dict()["contract_met"])

    def test_another_failure_in_a_done_job_is_a_fault(self):
        self.build()
        job = {"status": "done", "errors": ['path "a.md": local_path を解決できません']}
        outcome = self.run_sync(FakeClient([job]))
        self.assertEqual(outcome.status, sync.STATUS_FAILED)

    def test_a_failed_count_without_any_reason_is_a_fault(self):
        self.build()
        outcome = self.run_sync(FakeClient([{"status": "done", "failed": 2}]))
        self.assertEqual(outcome.status, sync.STATUS_FAILED)

    def test_a_failed_job_is_a_fault(self):
        self.build()
        outcome = self.run_sync(FakeClient([{"status": "failed", "errors": ["x"]}]))
        self.assertEqual(outcome.status, sync.STATUS_FAILED)

    def test_a_dropped_connection_switches_for_unreachable(self):
        self.build()
        for client in (
            FakeClient(
                [], start=docdb_client.TransportError("x", "TransportError（OSError）")
            ),
            FakeClient([docdb_client.TransportError("x", "TransportError（OSError）")]),
        ):
            with self.subTest():
                outcome = self.run_sync(client)
                self.assertEqual(outcome.status, sync.STATUS_SWITCH)
                self.assertEqual(outcome.reason_code, sync.REASON_UNREACHABLE)

    def test_tool_errors_follow_the_identifier(self):
        self.build()

        def error(identifier, code=-32603):
            return docdb_client.ToolError(
                "m",
                code=code,
                data=None if identifier is None else {"code": identifier},
            )

        # 同期の投入は Embedding を行わない。識別子だけで分類し、識別子の無い内部エラーは障害である
        cases = (
            ("EMBEDDING_FAILED", sync.STATUS_SWITCH),
            ("KEY_TRASHED", sync.STATUS_FAILED),
            ("INTERNAL_ERROR", sync.STATUS_FAILED),
            (None, sync.STATUS_FAILED),
        )
        for identifier, expected in cases:
            with self.subTest(identifier=identifier):
                outcome = self.run_sync(FakeClient([], start=error(identifier)))
                self.assertEqual(outcome.status, expected)

    def test_http_and_protocol_errors_are_faults(self):
        self.build()
        for exc in (
            docdb_client.HttpError(500, "body", "u"),
            docdb_client.ProtocolError("p"),
        ):
            with self.subTest(exc=type(exc).__name__):
                outcome = self.run_sync(FakeClient([], start=exc))
                self.assertEqual(outcome.status, sync.STATUS_FAILED)
                self.assertNotIn("body", " ".join(outcome.errors))

    def test_a_missing_job_id_is_a_fault(self):
        self.build()
        outcome = self.run_sync(FakeClient([], start={}))
        self.assertEqual(outcome.status, sync.STATUS_FAILED)

    def test_an_unknown_job_status_is_a_fault(self):
        self.build()
        outcome = self.run_sync(FakeClient([{"status": "weird"}]))
        self.assertEqual(outcome.status, sync.STATUS_FAILED)

    def test_an_unbuilt_toc_is_a_fault_with_the_state_kind(self):
        outcome = self.run_sync(FakeClient([]))
        self.assertEqual(outcome.status, sync.STATUS_FAILED)
        self.assertIn("missing", outcome.errors[0])

    def test_to_dict_reports_counts_and_missing_paths(self):
        self.build()
        (self.root / "b.md").unlink()
        outcome = self.run_sync(FakeClient([{"status": "done", "processed": 1}]))
        data = outcome.to_dict()
        self.assertEqual(data["listed"], 1)
        self.assertEqual(data["missing_count"], 1)
        self.assertEqual(data["missing_paths"], ["b.md"])

    def test_sync_does_not_write_state(self):
        self.build()
        before = {
            str(p): p.read_bytes()
            for p in sorted((self.root / ".doc-link").rglob("*"))
            if p.is_file()
        }
        self.run_sync(FakeClient([{"status": "done"}]))
        after = {
            str(p): p.read_bytes()
            for p in sorted((self.root / ".doc-link").rglob("*"))
            if p.is_file()
        }
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
