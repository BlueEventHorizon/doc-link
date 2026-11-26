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


def startup_required(detail="接続できない（接続の失敗）"):
    return docdb_runtime.Availability(
        docdb_runtime.STATUS_STARTUP_REQUIRED, "not_attempted", detail=detail
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
        self.allowed = []

    def write_config(self, text):
        path = backend_config.config_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def provider(self, result):
        def provide(allow_startup=False):
            self.probes += 1
            self.allowed.append(allow_startup)
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

    def test_an_unreachable_doc_db_with_an_executable_stops_to_ask_for_permission(self):
        # 起動の許可を得ていない。起動せず、構築・検索をしない
        decision = bs.decide(self.root, self.provider(startup_required()))
        self.assertIsNone(decision.backend)
        self.assertIsNone(decision.switch)
        self.assertEqual(self.allowed, [False])
        data = decision.pending.to_dict()
        self.assertEqual(data["action"], "confirm_docdb_startup")
        self.assertEqual(data["command"], "doc-db")
        self.assertEqual(
            [(o["id"], o["argument"]) for o in data["options"]],
            [("start", "--docdb-startup start"), ("toc", "--docdb-startup toc")],
        )

    def test_the_permission_to_start_is_passed_to_the_runtime(self):
        bs.decide(self.root, self.provider(available("succeeded")), startup="start")
        self.assertEqual(self.allowed, [True])

    def test_declining_continues_as_toc_without_connecting(self):
        decision = bs.decide(self.root, self.provider(available()), startup="toc")
        self.assertEqual(decision.backend, bs.BACKEND_TOC)
        self.assertFalse(decision.forced)
        self.assertEqual(decision.switch.reason_code, bs.REASON_STARTUP_DECLINED)
        self.assertEqual(self.probes, 0)
        self.assertIn("今回は ToC", decision.switch.notice)

    def test_a_failed_start_stops_without_switching_and_does_not_mention_the_sandbox(
        self,
    ):
        for cause in ("exited_early", "spawn_failed", "reconnect_failed"):
            with self.subTest(cause=cause):
                decision = bs.decide(
                    self.root,
                    self.provider(unavailable(cause, "詳細")),
                    startup="start",
                )
                self.assertIsNone(decision.backend)
                self.assertIsNone(decision.switch)
                data = decision.pending.to_dict()
                self.assertEqual(data["action"], "docdb_startup_failed")
                self.assertEqual(data["cause"], cause)
                self.assertEqual(data["command"], "doc-db")
                self.assertEqual([o["id"] for o in data["options"]], ["retry", "toc"])
                self.assertIsNone(data["options"][0]["argument"])
                text = str(data)
                self.assertNotIn("sandbox", text.lower())
                self.assertNotIn("サンドボックス", text)

    def test_an_executable_that_does_not_exist_switches_even_with_permission(self):
        decision = bs.decide(self.root, self.provider(unavailable()), startup="start")
        self.assertEqual(decision.backend, bs.BACKEND_TOC)
        self.assertEqual(decision.switch.reason_code, bs.REASON_UNREACHABLE)

    def test_the_forced_switch_ignores_the_answer(self):
        self.write_config('{"backend": "toc"}')
        decision = bs.decide(self.root, self.provider(available()), startup="start")
        self.assertTrue(decision.forced)
        self.assertEqual(self.probes, 0)

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
