"""[ToC]の公開状態（P-01〜P-03）と構築実行（B-01〜B-09）の状態遷移のガード。DES-004 §2・§3 の遷移表をデータとして持つ。

入口 script ではないので、PEP 723 とロックは持たない。遷移の機構（表にない遷移とガード不成立の拒否、状態を
変えない）は `transition_table` を使う（`embed_state_machine` と同じ機構）。この処理は状態とガードだけを持ち、
段階を実際に進める処理は入口 script（TASK-013）が、候補の組み立て・検査・公開は `toc_candidate` が行う。
拒否しても[確定 ToC]を作らず変えない（この処理は[確定 ToC]を読み書きしない）。

## 仕様の解釈（設計書が値や形式を定めていない点）

- 公開状態 `PublicationRun`（P-01〜P-03）: 事象は `publish`（P-01・P-02）と `fail`（P-03）。
  P-01 の元は未構築、P-02 の元は[確定 ToC]あり。どちらも、候補が検査済みで確定が成功したこと
  （`candidate_validated` と `commit_succeeded` の両方）をガードにする。P-03 は、元が未構築・[確定 ToC]ありの
  どちらでも、候補作成・検査・確定のいずれかが失敗したこと（`candidate_stage_failed`）をガードにし、
  状態を変えない（元のまま）
- 構築実行 `BuildRun`（B-01〜B-09）の事象は、`expand_scope`（B-01）・`confirm_ids`（B-02）・
  `compare`（B-03）・`acquire_info`（B-04）・`check_references`（B-05）・`validate_candidate`（B-06）・
  `commit`（B-07）・`fail`（B-08）・`restart`（B-09）とする。ガードの判定に使う事実は `BuildFacts` で
  渡す。値を渡さなかった事実は偽とみなす（ガードを満たしたと推測しない）
- B-08 は、開始・対象確定・ID 確定・変更確定・情報確定・参照検査確定・候補検査済みのそれぞれから、
  当該段階の処理が失敗したこと（`stage_failed`）をガードに、失敗へ遷移する。完了と失敗からは遷移しない。
  自動で再試行しない。失敗から開始へ戻るのは、B-09（再実行を明示的に開始した `rerun_requested`）だけである
- AI への生成依頼は変更確定以降に限る。B-04 の元が変更確定だけであることで表す
- B-07 は、確定が P-01 または P-02 で[確定 ToC]を切り替えることを伴う。`BuildSession` が `BuildRun` と
  `PublicationRun` を組み、`commit` を、B-07 と P-01・P-02 の両方が受理できるときだけ、同時に進める。
  どちらかが拒否したときは、どちらの状態も変えない。P-03 は、`BuildSession.fail_publication` で、
  公開状態だけに適用する（候補作成・検査・確定の失敗を B-08 と対にするかは、呼び出し側が段階で決める）
- 拒否は `TransitionRejected`（`transition_table`）で、理由は `no_transition`・`guard_unmet`
"""

from collections.abc import Iterable
from dataclasses import dataclass

from transition_table import (  # noqa: F401  再公開
    KEEP_STATE,
    REJECT_GUARD_UNMET,
    REJECT_NO_TRANSITION,
    StateRun,
    Transition,
    TransitionRejected,
)

# 公開状態
UNBUILT = "未構築"
PUBLISHED = "確定 ToC あり"

EVENT_PUBLISH = "publish"
EVENT_PUBLICATION_FAIL = "fail"

# 構築実行の状態
START = "開始"
SCOPE_READY = "対象確定"
IDS_READY = "ID 確定"
CHANGES_READY = "変更確定"
DATA_READY = "情報確定"
REFS_READY = "参照検査確定"
CANDIDATE_READY = "候補検査済み"
DONE = "完了"
FAILED = "失敗"

EVENT_EXPAND_SCOPE = "expand_scope"
EVENT_CONFIRM_IDS = "confirm_ids"
EVENT_COMPARE = "compare"
EVENT_ACQUIRE_INFO = "acquire_info"
EVENT_CHECK_REFERENCES = "check_references"
EVENT_VALIDATE_CANDIDATE = "validate_candidate"
EVENT_COMMIT = "commit"
EVENT_FAIL = "fail"
EVENT_RESTART = "restart"

FAILABLE_STATES = (
    START,
    SCOPE_READY,
    IDS_READY,
    CHANGES_READY,
    DATA_READY,
    REFS_READY,
    CANDIDATE_READY,
)


@dataclass(frozen=True)
class PublicationFacts:
    """公開状態のガードの判定に使う事実。渡さなかったものは偽。"""

    candidate_validated: bool = False
    commit_succeeded: bool = False
    candidate_stage_failed: bool = False


@dataclass(frozen=True)
class BuildFacts:
    """構築実行のガードの判定に使う事実。渡さなかったものは偽。"""

    scope_validated: bool = False
    frontmatter_read: bool = False
    comparison_succeeded: bool = False
    info_acquired: bool = False
    references_classified: bool = False
    required_and_consistent: bool = False
    commit_succeeded: bool = False
    stage_failed: bool = False
    rerun_requested: bool = False


def _published(state: str, facts: PublicationFacts) -> bool:
    return facts.candidate_validated and facts.commit_succeeded


PUBLICATION_TRANSITIONS: tuple[Transition, ...] = (
    Transition(
        "P-01",
        (UNBUILT,),
        EVENT_PUBLISH,
        _published,
        "初回候補が検査済みで構築実行の確定が成功",
        PUBLISHED,
    ),
    Transition(
        "P-02",
        (PUBLISHED,),
        EVENT_PUBLISH,
        _published,
        "再構築候補が検査済みで確定が成功",
        PUBLISHED,
    ),
    Transition(
        "P-03",
        (UNBUILT, PUBLISHED),
        EVENT_PUBLICATION_FAIL,
        lambda state, facts: facts.candidate_stage_failed,
        "候補作成・検査・確定のいずれかが失敗",
        KEEP_STATE,
    ),
)

BUILD_TRANSITIONS: tuple[Transition, ...] = (
    Transition(
        "B-01",
        (START,),
        EVENT_EXPAND_SCOPE,
        lambda state, facts: facts.scope_validated,
        "完全な対象指定を検証・展開した",
        SCOPE_READY,
    ),
    Transition(
        "B-02",
        (SCOPE_READY,),
        EVENT_CONFIRM_IDS,
        lambda state, facts: facts.frontmatter_read,
        "全対象の frontmatter を読み取れた",
        IDS_READY,
    ),
    Transition(
        "B-03",
        (IDS_READY,),
        EVENT_COMPARE,
        lambda state, facts: facts.comparison_succeeded,
        "旧[確定 ToC]と現物の比較が成功",
        CHANGES_READY,
    ),
    Transition(
        "B-04",
        (CHANGES_READY,),
        EVENT_ACQUIRE_INFO,
        lambda state, facts: facts.info_acquired,
        "必要情報の取得・AI 出力検証が成功",
        DATA_READY,
    ),
    Transition(
        "B-05",
        (DATA_READY,),
        EVENT_CHECK_REFERENCES,
        lambda state, facts: facts.references_classified,
        "参照先の必要な実走査と結果分類が完了",
        REFS_READY,
    ),
    Transition(
        "B-06",
        (REFS_READY,),
        EVENT_VALIDATE_CANDIDATE,
        lambda state, facts: facts.required_and_consistent,
        "必須情報と整合条件が満たされた",
        CANDIDATE_READY,
    ),
    Transition(
        "B-07",
        (CANDIDATE_READY,),
        EVENT_COMMIT,
        lambda state, facts: facts.commit_succeeded,
        "一括確定が成功",
        DONE,
    ),
    Transition(
        "B-08",
        FAILABLE_STATES,
        EVENT_FAIL,
        lambda state, facts: facts.stage_failed,
        "当該段階の処理が失敗",
        FAILED,
    ),
    Transition(
        "B-09",
        (FAILED,),
        EVENT_RESTART,
        lambda state, facts: facts.rerun_requested,
        "再実行を明示的に開始",
        START,
    ),
)


class PublicationRun(StateRun):
    """[確定 ToC]の公開状態（キーごと）。`apply` は表に従って遷移させ、拒否したときは状態を変えない。"""

    def __init__(
        self,
        transitions: Iterable[Transition] = PUBLICATION_TRANSITIONS,
        state: str = UNBUILT,
    ):
        super().__init__(transitions, state, PublicationFacts)


class BuildRun(StateRun):
    """構築実行 1 回の状態。`apply` は表に従って遷移させ、拒否したときは状態を変えない。"""

    def __init__(
        self,
        transitions: Iterable[Transition] = BUILD_TRANSITIONS,
        state: str = START,
    ):
        super().__init__(transitions, state, BuildFacts)


class BuildSession:
    """構築実行と公開状態の組。B-07 の確定が P-01 または P-02 で[確定 ToC]を切り替えることを表す。"""

    def __init__(
        self,
        publication_state: str = UNBUILT,
        build_state: str = START,
        build_transitions: Iterable[Transition] = BUILD_TRANSITIONS,
        publication_transitions: Iterable[Transition] = PUBLICATION_TRANSITIONS,
    ):
        self.build = BuildRun(build_transitions, build_state)
        self.publication = PublicationRun(publication_transitions, publication_state)

    def apply(self, event: str, facts: BuildFacts | None = None) -> Transition:
        """構築実行の事象を適用する。`commit` は B-07 と P-01・P-02 を同時に進める。"""
        if event != EVENT_COMMIT:
            return self.build.apply(event, facts)
        facts = facts if facts is not None else BuildFacts()
        # 両方が受理できるときだけ進める（どちらかが拒否したら、どちらの状態も変えない）。
        build_before, publication_before = self.build.state, self.publication.state
        try:
            transition = self.build.apply(EVENT_COMMIT, facts)
            self.publication.apply(
                EVENT_PUBLISH,
                PublicationFacts(
                    candidate_validated=build_before == CANDIDATE_READY,
                    commit_succeeded=facts.commit_succeeded,
                ),
            )
        except TransitionRejected:
            self.build.state = build_before
            self.publication.state = publication_before
            raise
        return transition

    def fail_publication(self, facts: PublicationFacts | None = None) -> Transition:
        """P-03: 候補作成・検査・確定のいずれかの失敗。公開状態は元のまま。"""
        return self.publication.apply(EVENT_PUBLICATION_FAIL, facts)
