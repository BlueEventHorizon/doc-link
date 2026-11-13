import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import embed_state_machine  # noqa: E402
import transition_table as tt  # noqa: E402


@dataclass(frozen=True)
class Facts:
    ok: bool = False


TABLE = (
    tt.Transition("T-1", ("a",), "go", lambda s, f: f.ok, "ok", "b"),
    tt.Transition("T-2", ("a",), "go", lambda s, f: not f.ok and s == "a", "no", "c"),
    tt.Transition("T-3", ("b",), "stay", lambda s, f: f.ok, "ok", tt.KEEP_STATE),
)


def run(state):
    return tt.StateRun(TABLE, state, Facts)


class StateRunTest(unittest.TestCase):
    def test_first_row_with_met_guard_is_taken(self):
        r = run("a")
        self.assertEqual(r.apply("go", Facts(ok=True)).transition_id, "T-1")
        self.assertEqual(r.state, "b")
        r = run("a")
        self.assertEqual(r.apply("go", Facts(ok=False)).transition_id, "T-2")
        self.assertEqual(r.state, "c")

    def test_default_facts_are_false(self):
        r = run("a")
        self.assertEqual(r.apply("go").transition_id, "T-2")

    def test_keep_state_row_does_not_change_state(self):
        r = run("b")
        self.assertEqual(r.apply("stay", Facts(ok=True)).transition_id, "T-3")
        self.assertEqual(r.state, "b")

    def test_rejections_keep_state_and_give_reason(self):
        r = run("b")
        with self.assertRaises(tt.TransitionRejected) as caught:
            r.apply("stay", Facts(ok=False))
        self.assertEqual(caught.exception.reason, tt.REJECT_GUARD_UNMET)
        with self.assertRaises(tt.TransitionRejected) as caught:
            r.apply("go", Facts(ok=True))
        self.assertEqual(caught.exception.reason, tt.REJECT_NO_TRANSITION)
        self.assertEqual(r.state, "b")


class EmbedStateMachineSharesTheMechanismTest(unittest.TestCase):
    def test_embed_run_uses_the_shared_mechanism(self):
        self.assertTrue(issubclass(embed_state_machine.EmbedRun, tt.StateRun))
        self.assertIs(embed_state_machine.Transition, tt.Transition)
        self.assertIs(embed_state_machine.TransitionRejected, tt.TransitionRejected)


if __name__ == "__main__":
    unittest.main()
