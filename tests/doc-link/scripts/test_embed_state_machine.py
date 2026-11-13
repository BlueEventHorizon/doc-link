import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import embed_state_machine as sm  # noqa: E402
from embed_state_machine import Facts  # noqa: E402


def run_in(state):
    return sm.EmbedRun(state=state)


class AllowedTransitionsTest(unittest.TestCase):
    def check(self, state, event, facts, expected_id, expected_state):
        run = run_in(state)
        transition = run.apply(event, facts)
        self.assertEqual(transition.transition_id, expected_id)
        self.assertEqual(run.state, expected_state)

    def test_e01(self):
        self.check(
            sm.START,
            sm.EVENT_EXPAND,
            Facts(scope_expanded=True),
            "E-01",
            sm.SCOPE_READY,
        )

    def test_e02(self):
        self.check(
            sm.SCOPE_READY,
            sm.EVENT_RECONCILE,
            Facts(reconciled=True),
            "E-02",
            sm.PLAN_CONFIRMED,
        )

    def test_e03(self):
        self.check(
            sm.SCOPE_READY,
            sm.EVENT_RECONCILE,
            Facts(reconciled=True, duplicates_found=True),
            "E-03",
            sm.AWAITING_ORIGIN,
        )

    def test_e04(self):
        self.check(
            sm.AWAITING_ORIGIN,
            sm.EVENT_CONFIRM_ORIGIN,
            Facts(origin_confirmed=True),
            "E-04",
            sm.PLAN_CONFIRMED,
        )

    def test_e06_stage_failure_from_each_stage(self):
        for state in (sm.START, sm.SCOPE_READY, sm.AWAITING_ORIGIN):
            with self.subTest(state=state):
                self.check(
                    state, sm.EVENT_FAIL, Facts(stage_failed=True), "E-06", sm.FAILED
                )

    def test_e06_abandoned_while_awaiting_origin(self):
        self.check(
            sm.AWAITING_ORIGIN,
            sm.EVENT_FAIL,
            Facts(origin_abandoned=True),
            "E-06",
            sm.FAILED,
        )


class RejectedTransitionsTest(unittest.TestCase):
    def reject(self, state, event, facts, reason):
        run = run_in(state)
        with self.assertRaises(sm.TransitionRejected) as caught:
            run.apply(event, facts)
        self.assertEqual(caught.exception.reason, reason)
        self.assertEqual(run.state, state)

    def test_guard_unmet(self):
        cases = [
            (sm.START, sm.EVENT_EXPAND, Facts()),
            (sm.SCOPE_READY, sm.EVENT_RECONCILE, Facts()),
            (sm.SCOPE_READY, sm.EVENT_RECONCILE, Facts(duplicates_found=True)),
            (sm.AWAITING_ORIGIN, sm.EVENT_CONFIRM_ORIGIN, Facts()),
            (sm.START, sm.EVENT_FAIL, Facts()),
            (sm.SCOPE_READY, sm.EVENT_FAIL, Facts(origin_abandoned=True)),
            (sm.START, sm.EVENT_FAIL, Facts(origin_abandoned=True)),
        ]
        for state, event, facts in cases:
            with self.subTest(state=state, event=event, facts=facts):
                self.reject(state, event, facts, sm.REJECT_GUARD_UNMET)

    def test_duplicates_with_e02_and_no_duplicates_with_e03_are_both_distinct(self):
        run = run_in(sm.SCOPE_READY)
        self.assertEqual(
            run.apply(sm.EVENT_RECONCILE, Facts(reconciled=True)).transition_id, "E-02"
        )
        run = run_in(sm.SCOPE_READY)
        self.assertEqual(
            run.apply(
                sm.EVENT_RECONCILE, Facts(reconciled=True, duplicates_found=True)
            ).transition_id,
            "E-03",
        )

    def test_unknown_event(self):
        self.reject(
            sm.START, "bogus", Facts(scope_expanded=True), sm.REJECT_NO_TRANSITION
        )

    def test_event_from_other_state(self):
        full = Facts(
            scope_expanded=True,
            reconciled=True,
            origin_confirmed=True,
            stage_failed=True,
        )
        cases = [
            (sm.SCOPE_READY, sm.EVENT_EXPAND),
            (sm.AWAITING_ORIGIN, sm.EVENT_RECONCILE),
            (sm.SCOPE_READY, sm.EVENT_CONFIRM_ORIGIN),
            (sm.START, sm.EVENT_CONFIRM_ORIGIN),
            (sm.START, sm.EVENT_RECONCILE),
        ]
        for state, event in cases:
            with self.subTest(state=state, event=event):
                self.reject(state, event, full, sm.REJECT_NO_TRANSITION)

    def test_transitions_owned_by_later_task_are_rejected(self):
        full = Facts(
            scope_expanded=True,
            reconciled=True,
            origin_confirmed=True,
            stage_failed=True,
            origin_abandoned=True,
        )
        for event in (
            sm.EVENT_EXPAND,
            sm.EVENT_RECONCILE,
            sm.EVENT_CONFIRM_ORIGIN,
            sm.EVENT_FAIL,
            "write_done",
            "restart",
        ):
            for state in (sm.PLAN_CONFIRMED, sm.DONE, sm.FAILED):
                with self.subTest(state=state, event=event):
                    self.reject(state, event, full, sm.REJECT_NO_TRANSITION)

    def test_default_facts_are_false(self):
        run = run_in(sm.START)
        with self.assertRaises(sm.TransitionRejected):
            run.apply(sm.EVENT_EXPAND)
        self.assertEqual(run.state, sm.START)

    def test_table_can_be_extended(self):
        extra = sm.Transition(
            "E-07", (sm.FAILED,), "restart", lambda s, f: True, "再実行", sm.START
        )
        run = sm.EmbedRun(sm.TRANSITIONS + (extra,), state=sm.FAILED)
        run.apply("restart")
        self.assertEqual(run.state, sm.START)


class FlowTest(unittest.TestCase):
    def test_path_with_duplicates(self):
        run = sm.EmbedRun()
        run.apply(sm.EVENT_EXPAND, Facts(scope_expanded=True))
        run.apply(sm.EVENT_RECONCILE, Facts(reconciled=True, duplicates_found=True))
        run.apply(sm.EVENT_CONFIRM_ORIGIN, Facts(origin_confirmed=True))
        self.assertEqual(run.state, sm.PLAN_CONFIRMED)


if __name__ == "__main__":
    unittest.main()
