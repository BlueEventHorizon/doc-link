"""`backend_select`（[検索基盤]の判定と、切り替えの通知）のテスト。AC-036〜AC-038・AC-042。"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import backend_config  # noqa: E402
import backend_select as bs  # noqa: E402
import docdb_runtime  # noqa: E402


def available(startup="not_attempted"):
    return docdb_runtime.Availability(
        docdb_runtime.STATUS_AVAILABLE, startup, client=object()
    )


def unavailable(
    cause="executable_missing", detail="実行ファイル doc-db が検索パスに無い"
):
    return docdb_runtime.Availability(
        docdb_runtime.STATUS_UNAVAILABLE, "failed", cause, detail
    )


class DecideTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.probes = 0

    def write_config(self, text):
        path = backend_config.config_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def provider(self, result):
        def provide():
            self.probes += 1
            return result

        return provide

    def test_the_default_is_doc_db_when_it_works(self):
        decision = bs.decide(self.root, self.provider(available()))
        self.assertEqual(decision.backend, bs.BACKEND_DOCDB)
        self.assertFalse(decision.forced)
        self.assertIsNone(decision.switch)
        self.assertIsNotNone(decision.client)
        self.assertEqual(decision.startup, "not_attempted")

    def test_a_started_doc_db_is_used_without_a_switch(self):
        decision = bs.decide(self.root, self.provider(available("succeeded")))
        self.assertEqual(
            (decision.backend, decision.startup), (bs.BACKEND_DOCDB, "succeeded")
        )
        self.assertIsNone(decision.switch)

    def test_the_forced_switch_neither_connects_nor_starts_nor_notifies(self):
        self.write_config('{"backend": "toc"}')
        decision = bs.decide(self.root, self.provider(available()))
        self.assertEqual(decision.backend, bs.BACKEND_TOC)
        self.assertTrue(decision.forced)
        self.assertIsNone(decision.switch)
        self.assertEqual(self.probes, 0)

    def test_auto_in_the_config_probes_doc_db(self):
        self.write_config('{"backend": "auto"}')
        bs.decide(self.root, self.provider(available()))
        self.assertEqual(self.probes, 1)

    def test_an_invalid_config_is_an_error_and_does_not_probe(self):
        self.write_config('{"backend": "x"}')
        with self.assertRaises(backend_config.BackendConfigError):
            bs.decide(self.root, self.provider(available()))
        self.assertEqual(self.probes, 0)

    def test_an_unreachable_doc_db_switches_to_toc_with_a_notice(self):
        decision = bs.decide(self.root, self.provider(unavailable()))
        self.assertEqual(decision.backend, bs.BACKEND_TOC)
        self.assertFalse(decision.forced)
        self.assertEqual(decision.switch.reason_code, bs.REASON_UNREACHABLE)
        self.assertIn("executable_missing", decision.switch.cause)
        self.assertEqual(decision.startup, "failed")

    def test_the_decision_is_not_remembered(self):
        bs.decide(self.root, self.provider(unavailable()))
        again = bs.decide(self.root, self.provider(available()))
        self.assertEqual(again.backend, bs.BACKEND_DOCDB)
        self.assertEqual(self.probes, 2)

    def test_to_dict_has_no_client(self):
        decision = bs.decide(self.root, self.provider(available()))
        data = decision.to_dict()
        self.assertEqual(set(data), {"backend", "forced", "startup", "backend_switch"})
        self.assertIsNone(data["backend_switch"])


class SwitchTest(unittest.TestCase):
    def test_the_notice_names_the_switch_reason_cause_impact_and_next_run(self):
        switch = bs.Switch(
            bs.REASON_OPENAI_FAILED,
            "同期での文書の Embedding が失敗した（EMBEDDING_FAILED）",
        )
        switch = switch.with_impact(3)
        notice = switch.notice
        self.assertIn("doc-db から ToC へ切り替えた", notice)
        self.assertIn("OpenAI の失敗", notice)
        self.assertIn("EMBEDDING_FAILED", notice)
        self.assertIn("3 件", notice)
        self.assertIn("次の実行でも、doc-db を先に試す", notice)
        self.assertIn("config.json", notice)

    def test_a_presumed_cause_is_marked(self):
        notice = bs.Switch(bs.REASON_OPENAI_FAILED, "c", presumed=True).notice
        self.assertIn("推定", notice)
        self.assertNotIn("推定", bs.Switch(bs.REASON_OPENAI_FAILED, "c").notice)

    def test_the_unreachable_notice_suggests_installing_doc_db(self):
        notice = bs.Switch(bs.REASON_UNREACHABLE, "executable_missing").notice
        self.assertIn("導入", notice)

    def test_to_dict_carries_the_notice_and_no_secrets(self):
        data = (
            bs.Switch(bs.REASON_UNREACHABLE, "exited_early: 終了コード 1")
            .with_impact(0)
            .to_dict()
        )
        self.assertEqual((data["from"], data["to"]), ("doc-db", "toc"))
        self.assertEqual(data["reason_code"], "docdb_unreachable")
        self.assertEqual(
            data["notice"],
            bs.Switch(bs.REASON_UNREACHABLE, "exited_early: 終了コード 1")
            .with_impact(0)
            .notice,
        )
        self.assertNotIn("OPENAI", str(data))

    def test_switched_to_toc_keeps_the_startup_and_is_not_forced(self):
        decision = bs.Decision(bs.BACKEND_DOCDB, startup="succeeded", client=object())
        switched = decision.switched_to_toc(bs.Switch(bs.REASON_OPENAI_FAILED, "c"))
        self.assertEqual(switched.backend, bs.BACKEND_TOC)
        self.assertFalse(switched.forced)
        self.assertEqual(switched.startup, "succeeded")
        self.assertIsNone(switched.client)
        self.assertEqual(
            switched.to_dict()["backend_switch"]["reason_code"], "docdb_openai_failed"
        )


if __name__ == "__main__":
    unittest.main()
