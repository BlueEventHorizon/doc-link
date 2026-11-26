"""`docdb_runtime`（接続の確認 → その場での起動 → 期限付きの再接続）のテスト。AC-047。

実行ファイル・実プロセス・実サーバー・実時間に依存しない。`which`・`spawn`・`sleep`・`now`・`client_factory` を注入する。
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import docdb_client  # noqa: E402
import docdb_runtime as rt  # noqa: E402


class FakeClient:
    def __init__(self, plan):
        self.plan = plan  # initialize のたびに、例外（失敗）か None（成功）を取り出す

    def initialize(self):
        step = self.plan.pop(0) if self.plan else None
        if step is not None:
            raise step


class FakeProcess:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code

    def poll(self):
        return self.exit_code


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def refused():
    return docdb_client.TransportError("x", "TransportError（ConnectionRefusedError）")


class EnsureAvailableTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config = Path(self._tmp.name) / "doc-db.yaml"
        self.config.write_text("server:\n  port: 58081\n", encoding="utf-8")
        self.clock = Clock()
        self.spawned = []

    def run_ensure(self, plan, which=lambda name: "/bin/doc-db", spawn=None, **kwargs):
        client = FakeClient(plan)
        if spawn is None:

            def spawn(executable):
                self.spawned.append(executable)
                return FakeProcess()

        return rt.ensure_available(
            config_path=self.config,
            client_factory=lambda timeout: client,
            which=which,
            spawn=spawn,
            sleep=self.clock.sleep,
            now=self.clock.now,
            **kwargs,
        )

    def test_a_running_doc_db_is_used_without_starting(self):
        result = self.run_ensure([None])
        self.assertTrue(result.available)
        self.assertEqual(result.startup, rt.STARTUP_NOT_ATTEMPTED)
        self.assertEqual(self.spawned, [])
        self.assertEqual(result.port, 58081)

    def test_a_missing_config_means_neither_connecting_nor_starting(self):
        self.config.unlink()
        result = self.run_ensure([None])
        self.assertFalse(result.available)
        self.assertEqual(result.cause, rt.CAUSE_CONFIG_UNREADABLE)
        self.assertEqual(self.spawned, [])

    def test_it_starts_doc_db_and_reconnects_within_the_deadline(self):
        result = self.run_ensure([refused(), refused(), refused(), None])
        self.assertTrue(result.available)
        self.assertEqual(result.startup, rt.STARTUP_SUCCEEDED)
        self.assertEqual(self.spawned, ["/bin/doc-db"])
        self.assertTrue(
            all(s <= rt.RECONNECT_INTERVAL_SECONDS for s in self.clock.sleeps)
        )

    def test_a_missing_executable_is_reported_without_starting(self):
        result = self.run_ensure([refused()], which=lambda name: None)
        self.assertFalse(result.available)
        self.assertEqual(result.cause, rt.CAUSE_EXECUTABLE_MISSING)
        self.assertEqual(result.startup, rt.STARTUP_FAILED)
        self.assertEqual(self.spawned, [])

    def test_without_permission_it_does_not_start_and_asks(self):
        # 起動の許可が無いときは、実行ファイルがあっても起動しない
        result = self.run_ensure([refused()], allow_startup=False)
        self.assertFalse(result.available)
        self.assertEqual(result.status, rt.STATUS_STARTUP_REQUIRED)
        self.assertEqual(result.startup, rt.STARTUP_NOT_ATTEMPTED)
        self.assertEqual(self.spawned, [])

    def test_without_permission_a_running_doc_db_is_still_used(self):
        result = self.run_ensure([None], allow_startup=False)
        self.assertTrue(result.available)
        self.assertEqual(result.startup, rt.STARTUP_NOT_ATTEMPTED)

    def test_without_permission_a_missing_executable_is_not_a_question(self):
        # 起動できないので、許可を求めても意味が無い
        result = self.run_ensure(
            [refused()], which=lambda name: None, allow_startup=False
        )
        self.assertEqual(result.status, rt.STATUS_UNAVAILABLE)
        self.assertEqual(result.cause, rt.CAUSE_EXECUTABLE_MISSING)

    def test_a_spawn_failure_is_reported(self):
        def failing(executable):
            raise PermissionError("denied")

        result = self.run_ensure([refused()], spawn=failing)
        self.assertEqual(result.cause, rt.CAUSE_SPAWN_FAILED)
        self.assertNotIn("denied", result.detail)

    def test_an_early_exit_gets_exactly_one_more_try(self):
        calls = []

        def spawn(executable):
            return FakeProcess(exit_code=1)

        client = FakeClient([refused(), refused(), refused(), refused()])
        original = client.initialize

        def counting():
            calls.append(1)
            original()

        client.initialize = counting
        result = rt.ensure_available(
            config_path=self.config,
            client_factory=lambda timeout: client,
            which=lambda name: "/bin/doc-db",
            spawn=spawn,
            sleep=self.clock.sleep,
            now=self.clock.now,
        )
        self.assertEqual(result.cause, rt.CAUSE_EXITED_EARLY)
        self.assertIn("1", result.detail)
        self.assertEqual(len(calls), 3)  # 最初の確認、起動後の確認、猶予の 1 回

    def test_an_early_exit_is_forgiven_when_another_instance_answers(self):
        result = self.run_ensure(
            [refused(), refused(), None],
            spawn=lambda executable: FakeProcess(exit_code=1),
        )
        self.assertTrue(result.available)
        self.assertEqual(result.startup, rt.STARTUP_SUCCEEDED)

    def test_the_deadline_stops_the_retries(self):
        result = self.run_ensure([refused()] * 1000, deadline=1.0, interval=0.25)
        self.assertEqual(result.cause, rt.CAUSE_RECONNECT_FAILED)
        self.assertLessEqual(self.clock.t, 1.0 + 1e-9)

    def test_the_failure_detail_has_no_exception_message(self):
        error = docdb_client.TransportError(
            "secret-message", "TransportError（OSError）"
        )
        result = self.run_ensure([error] * 1000, deadline=0.5, interval=0.25)
        self.assertNotIn("secret-message", result.detail)


class SpawnServerTest(unittest.TestCase):
    def test_it_starts_a_new_session_without_arguments_or_inherited_streams(self):
        import subprocess
        from unittest import mock

        with mock.patch.object(subprocess, "Popen") as popen:
            rt.spawn_server("/bin/doc-db")
        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["/bin/doc-db"])
        self.assertTrue(kwargs["start_new_session"])
        for name in ("stdin", "stdout", "stderr"):
            self.assertEqual(kwargs[name], subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
