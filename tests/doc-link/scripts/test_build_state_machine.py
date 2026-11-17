import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import build_state_machine as sm  # noqa: E402
import state_store  # noqa: E402
from build_state_machine import BuildFacts, PublicationFacts  # noqa: E402

PUBLISH_OK = PublicationFacts(candidate_validated=True, commit_succeeded=True)

# DES-004 §3 の表（B-01〜B-07）: (遷移 ID, 元, 事象, ガード成立の事実, 次)
B_ROWS = [
    (
        "B-01",
        sm.START,
        sm.EVENT_EXPAND_SCOPE,
        BuildFacts(scope_validated=True),
        sm.SCOPE_READY,
    ),
    (
        "B-02",
        sm.SCOPE_READY,
        sm.EVENT_CONFIRM_IDS,
        BuildFacts(frontmatter_read=True),
        sm.IDS_READY,
    ),
    (
        "B-03",
        sm.IDS_READY,
        sm.EVENT_COMPARE,
        BuildFacts(comparison_succeeded=True),
        sm.CHANGES_READY,
    ),
    (
        "B-04",
        sm.CHANGES_READY,
        sm.EVENT_ACQUIRE_INFO,
        BuildFacts(info_acquired=True),
        sm.DATA_READY,
    ),
    (
        "B-05",
        sm.DATA_READY,
        sm.EVENT_CHECK_REFERENCES,
        BuildFacts(references_classified=True),
        sm.REFS_READY,
    ),
    (
        "B-06",
        sm.REFS_READY,
        sm.EVENT_VALIDATE_CANDIDATE,
        BuildFacts(required_and_consistent=True),
        sm.CANDIDATE_READY,
    ),
    (
        "B-07",
        sm.CANDIDATE_READY,
        sm.EVENT_COMMIT,
        BuildFacts(commit_succeeded=True),
        sm.DONE,
    ),
]
B_STATES = [
    sm.START,
    sm.SCOPE_READY,
    sm.IDS_READY,
    sm.CHANGES_READY,
    sm.DATA_READY,
    sm.REFS_READY,
    sm.CANDIDATE_READY,
    sm.DONE,
    sm.FAILED,
]
B_EVENTS = [row[2] for row in B_ROWS] + [sm.EVENT_FAIL, sm.EVENT_RESTART]
FAILABLE = B_STATES[:7]


class PublicationTableTest(unittest.TestCase):
    def test_p01_unbuilt_to_published(self):
        run = sm.PublicationRun(state=sm.UNBUILT)
        transition = run.apply(sm.EVENT_PUBLISH, PUBLISH_OK)
        self.assertEqual(transition.transition_id, "P-01")
        self.assertEqual(run.state, sm.PUBLISHED)

    def test_p02_published_to_published(self):
        run = sm.PublicationRun(state=sm.PUBLISHED)
        transition = run.apply(sm.EVENT_PUBLISH, PUBLISH_OK)
        self.assertEqual(transition.transition_id, "P-02")
        self.assertEqual(run.state, sm.PUBLISHED)

    def test_p03_failure_keeps_each_state(self):
        for state in (sm.UNBUILT, sm.PUBLISHED):
            with self.subTest(state=state):
                run = sm.PublicationRun(state=state)
                transition = run.apply(
                    sm.EVENT_PUBLICATION_FAIL,
                    PublicationFacts(candidate_stage_failed=True),
                )
                self.assertEqual(transition.transition_id, "P-03")
                self.assertEqual(run.state, state)

    def test_guard_unmet_is_rejected_without_changing_state(self):
        cases = [
            PublicationFacts(),
            PublicationFacts(candidate_validated=True),
            PublicationFacts(commit_succeeded=True),
            PublicationFacts(candidate_stage_failed=True),
        ]
        for state in (sm.UNBUILT, sm.PUBLISHED):
            for facts in cases:
                with self.subTest(state=state, facts=facts):
                    run = sm.PublicationRun(state=state)
                    with self.assertRaises(sm.TransitionRejected) as caught:
                        run.apply(sm.EVENT_PUBLISH, facts)
                    self.assertEqual(caught.exception.reason, sm.REJECT_GUARD_UNMET)
                    self.assertEqual(run.state, state)
        for state in (sm.UNBUILT, sm.PUBLISHED):
            run = sm.PublicationRun(state=state)
            with self.assertRaises(sm.TransitionRejected):
                run.apply(sm.EVENT_PUBLICATION_FAIL, PublicationFacts())
            with self.assertRaises(sm.TransitionRejected):
                run.apply(sm.EVENT_PUBLICATION_FAIL)  # 事実を渡さない = 偽
            self.assertEqual(run.state, state)

    def test_unknown_event_and_unknown_state_are_rejected(self):
        run = sm.PublicationRun(state=sm.UNBUILT)
        with self.assertRaises(sm.TransitionRejected) as caught:
            run.apply("rebuild", PUBLISH_OK)
        self.assertEqual(caught.exception.reason, sm.REJECT_NO_TRANSITION)
        stranger = sm.PublicationRun(state="完了")
        with self.assertRaises(sm.TransitionRejected) as caught:
            stranger.apply(sm.EVENT_PUBLISH, PUBLISH_OK)
        self.assertEqual(caught.exception.reason, sm.REJECT_NO_TRANSITION)

    def test_table_has_exactly_p01_to_p03(self):
        self.assertEqual(
            [t.transition_id for t in sm.PUBLICATION_TRANSITIONS],
            ["P-01", "P-02", "P-03"],
        )


class BuildTableTest(unittest.TestCase):
    def test_b01_to_b07_move_to_the_next_state(self):
        for transition_id, source, event, facts, target in B_ROWS:
            with self.subTest(transition=transition_id):
                run = sm.BuildRun(state=source)
                transition = run.apply(event, facts)
                self.assertEqual(transition.transition_id, transition_id)
                self.assertEqual(run.state, target)

    def test_b01_to_b07_guard_unmet_is_rejected(self):
        for transition_id, source, event, _facts, _target in B_ROWS:
            with self.subTest(transition=transition_id):
                for facts in (
                    None,
                    BuildFacts(stage_failed=True, rerun_requested=True),
                ):
                    run = sm.BuildRun(state=source)
                    with self.assertRaises(sm.TransitionRejected) as caught:
                        run.apply(event, facts)
                    self.assertEqual(caught.exception.reason, sm.REJECT_GUARD_UNMET)
                    self.assertEqual(run.state, source)

    def test_b08_fails_from_each_stage_before_completion(self):
        for state in FAILABLE:
            with self.subTest(state=state):
                run = sm.BuildRun(state=state)
                transition = run.apply(sm.EVENT_FAIL, BuildFacts(stage_failed=True))
                self.assertEqual(transition.transition_id, "B-08")
                self.assertEqual(run.state, sm.FAILED)

    def test_b08_guard_unmet_is_rejected(self):
        for state in FAILABLE:
            with self.subTest(state=state):
                run = sm.BuildRun(state=state)
                with self.assertRaises(sm.TransitionRejected) as caught:
                    run.apply(sm.EVENT_FAIL, BuildFacts())
                self.assertEqual(caught.exception.reason, sm.REJECT_GUARD_UNMET)
                self.assertEqual(run.state, state)

    def test_b08_is_not_allowed_from_done_or_failed(self):
        for state in (sm.DONE, sm.FAILED):
            with self.subTest(state=state):
                run = sm.BuildRun(state=state)
                with self.assertRaises(sm.TransitionRejected) as caught:
                    run.apply(sm.EVENT_FAIL, BuildFacts(stage_failed=True))
                self.assertEqual(caught.exception.reason, sm.REJECT_NO_TRANSITION)
                self.assertEqual(run.state, state)

    def test_b09_only_explicit_rerun_returns_from_failed(self):
        run = sm.BuildRun(state=sm.FAILED)
        with self.assertRaises(sm.TransitionRejected):
            run.apply(sm.EVENT_RESTART, BuildFacts())
        self.assertEqual(run.state, sm.FAILED)
        transition = run.apply(sm.EVENT_RESTART, BuildFacts(rerun_requested=True))
        self.assertEqual(transition.transition_id, "B-09")
        self.assertEqual(run.state, sm.START)

    def test_failure_is_not_retried_automatically(self):
        run = sm.BuildRun(state=sm.FAILED)
        for _row_id, _source, event, facts, _target in B_ROWS:
            with self.assertRaises(sm.TransitionRejected):
                run.apply(event, facts)
        self.assertEqual(run.state, sm.FAILED)

    def test_events_from_another_state_are_rejected(self):
        for _row_id, source, event, facts, _target in B_ROWS:
            for state in B_STATES:
                if state == source:
                    continue
                with self.subTest(event=event, state=state):
                    run = sm.BuildRun(state=state)
                    with self.assertRaises(sm.TransitionRejected) as caught:
                        run.apply(event, facts)
                    self.assertEqual(caught.exception.reason, sm.REJECT_NO_TRANSITION)
                    self.assertEqual(run.state, state)

    def test_restart_from_other_than_failed_is_rejected(self):
        for state in B_STATES:
            if state == sm.FAILED:
                continue
            run = sm.BuildRun(state=state)
            with self.assertRaises(sm.TransitionRejected):
                run.apply(sm.EVENT_RESTART, BuildFacts(rerun_requested=True))
            self.assertEqual(run.state, state)

    def test_no_state_skipping(self):
        # 表にない暗黙の遷移（例: 開始から候補検査済み）を認めない
        run = sm.BuildRun(state=sm.START)
        for event in B_EVENTS:
            if event == sm.EVENT_EXPAND_SCOPE:
                continue
            with self.assertRaises(sm.TransitionRejected):
                run.apply(
                    event,
                    BuildFacts(
                        **{
                            f: True
                            for f in BuildFacts.__dataclass_fields__
                            if f != "stage_failed" and f != "rerun_requested"
                        }
                    ),
                )
        self.assertEqual(run.state, sm.START)

    def test_table_ids(self):
        self.assertEqual(
            [t.transition_id for t in sm.BUILD_TRANSITIONS],
            [f"B-0{n}" for n in range(1, 10)],
        )

    def test_full_run_reaches_done(self):
        run = sm.BuildRun()
        for _row_id, _source, event, facts, target in B_ROWS:
            run.apply(event, facts)
            self.assertEqual(run.state, target)
        self.assertEqual(run.state, sm.DONE)


class SessionTest(unittest.TestCase):
    def test_commit_is_b07_with_p01_for_unbuilt(self):
        session = sm.BuildSession(
            publication_state=sm.UNBUILT, build_state=sm.CANDIDATE_READY
        )
        transition = session.apply(sm.EVENT_COMMIT, BuildFacts(commit_succeeded=True))
        self.assertEqual(transition.transition_id, "B-07")
        self.assertEqual(session.build.state, sm.DONE)
        self.assertEqual(session.publication.state, sm.PUBLISHED)

    def test_commit_is_b07_with_p02_for_published(self):
        session = sm.BuildSession(
            publication_state=sm.PUBLISHED, build_state=sm.CANDIDATE_READY
        )
        session.apply(sm.EVENT_COMMIT, BuildFacts(commit_succeeded=True))
        self.assertEqual(session.build.state, sm.DONE)
        self.assertEqual(session.publication.state, sm.PUBLISHED)

    def test_commit_rejected_changes_neither_state(self):
        for publication in (sm.UNBUILT, sm.PUBLISHED):
            for build in B_STATES:
                if build == sm.CANDIDATE_READY:
                    continue
                with self.subTest(publication=publication, build=build):
                    session = sm.BuildSession(publication, build)
                    with self.assertRaises(sm.TransitionRejected):
                        session.apply(
                            sm.EVENT_COMMIT, BuildFacts(commit_succeeded=True)
                        )
                    self.assertEqual(session.build.state, build)
                    self.assertEqual(session.publication.state, publication)
            session = sm.BuildSession(publication, sm.CANDIDATE_READY)
            with self.assertRaises(sm.TransitionRejected):
                session.apply(sm.EVENT_COMMIT, BuildFacts())
            self.assertEqual(session.build.state, sm.CANDIDATE_READY)
            self.assertEqual(session.publication.state, publication)

    def test_publication_rejection_rolls_back_build_state(self):
        # 公開状態の表が B-07 の確定を受理しないとき、構築実行の状態も変えない
        session = sm.BuildSession(
            sm.UNBUILT, sm.CANDIDATE_READY, publication_transitions=()
        )
        with self.assertRaises(sm.TransitionRejected):
            session.apply(sm.EVENT_COMMIT, BuildFacts(commit_succeeded=True))
        self.assertEqual(session.build.state, sm.CANDIDATE_READY)
        self.assertEqual(session.publication.state, sm.UNBUILT)

    def test_other_events_go_to_build_only(self):
        session = sm.BuildSession(sm.PUBLISHED, sm.START)
        session.apply(sm.EVENT_EXPAND_SCOPE, BuildFacts(scope_validated=True))
        self.assertEqual(session.build.state, sm.SCOPE_READY)
        self.assertEqual(session.publication.state, sm.PUBLISHED)
        session.apply(sm.EVENT_FAIL, BuildFacts(stage_failed=True))
        self.assertEqual(session.build.state, sm.FAILED)
        self.assertEqual(session.publication.state, sm.PUBLISHED)

    def test_fail_publication_keeps_publication_state(self):
        for state in (sm.UNBUILT, sm.PUBLISHED):
            session = sm.BuildSession(state, sm.CANDIDATE_READY)
            transition = session.fail_publication(
                PublicationFacts(candidate_stage_failed=True)
            )
            self.assertEqual(transition.transition_id, "P-03")
            self.assertEqual(session.publication.state, state)
            with self.assertRaises(sm.TransitionRejected):
                session.fail_publication()


class ConfirmedTocUnchangedByRejectionTest(unittest.TestCase):
    """拒否した遷移は[確定 ToC]を作らず、変えない（状態機械は[確定 ToC]を読み書きしない）。"""

    def toc(self):
        return {
            "toc_key": "main",
            "version": 1,
            "target_spec": {},
            "documents": [],
            "sections": [],
            "references": [],
            "reverse_references": [],
            "last_checks": [],
        }

    def test_rejections_leave_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_store.save_confirmed_toc(root, "test", self.toc())
            path = state_store.confirmed_toc_path(root, "main")
            before = path.read_bytes()
            listing = sorted(p for p in root.rglob("*"))
            session = sm.BuildSession(sm.PUBLISHED, sm.CANDIDATE_READY)
            for event in B_EVENTS:
                if event == sm.EVENT_COMMIT:
                    continue
                with self.assertRaises(sm.TransitionRejected):
                    session.apply(event, BuildFacts())
            with self.assertRaises(sm.TransitionRejected):
                session.apply(sm.EVENT_COMMIT, BuildFacts())
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(sorted(root.rglob("*")), listing)

    def test_rejection_with_no_toc_creates_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = sm.BuildSession(sm.UNBUILT, sm.START)
            with self.assertRaises(sm.TransitionRejected):
                session.apply(sm.EVENT_COMMIT, BuildFacts(commit_succeeded=True))
            self.assertEqual(list(Path(tmp).rglob("*")), [])


if __name__ == "__main__":
    unittest.main()
