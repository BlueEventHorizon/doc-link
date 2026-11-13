"""embed-dlid（DLID 付与操作）の状態遷移のガード。DES-004 §5 の遷移表をデータとして持つ。

入口 script ではないので、PEP 723 とロックは持たない。表は E-01〜E-07 の全行を持つ。書き込みを伴う
E-05 と計画確定からの E-06、再実行の E-07 は、書き込みの部品（`dlid_writer`）の結果を事実として受ける。
`EmbedRun(transitions=...)` で表を差し替えられる。

## 仕様の解釈（設計書が値や形式を定めていない点）

- 事象は文字列で、`expand`（E-01）・`reconcile`（E-02・E-03）・`confirm_origin`（E-04）・`write`（E-05）・
  `fail`（E-06）・`restart`（E-07）とする。ガードの判定に使う事実は `Facts` で渡す。値を渡さなかった事実は
  偽とみなす（ガードを満たしたと推測しない）
- E-02 と E-03 は同じ事象 `reconcile` で、`duplicates_found` の真偽で分かれる。どちらも `reconciled`
  （全対象の[DLID]と見出しを読み、既存の[DLID]と照合した）が真であることを要する
- E-06 のガードは、`stage_failed`（当該段階の処理が失敗した）か、`origin_abandoned`（利用者が原本を確定せずに
  終えた。原本確認待ちのときだけ有効）である。計画確定からの E-06 は、別の行（同じ ID）で、`stage_failed` か
  `documents_unwritten`（書き込めなかった文書が 1 件でもある）をガードにする
- E-05 のガードは `written_and_verified`（全対象に書き込み、再解析で差分が[DLID]だけと確かめた）であり、
  `documents_unwritten` が偽であることも要する。E-07 のガードは `rerun_requested`（再実行を明示的に開始した）
  である。E-07 の効果の「書き込み済みの[DLID]を既存の[DLID]として照合し直す」は、再実行が文書を読み直して
  付与計画を作ること自体であり、状態表には持たない
- 拒否は `TransitionRejected` で、状態を変えない。拒否の理由は `reason` に、表にない事象・元状態は
  `no_transition`、ガード不成立は `guard_unmet` とする
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

START = "開始"
SCOPE_READY = "対象確定"
AWAITING_ORIGIN = "原本確認待ち"
PLAN_CONFIRMED = "計画確定"
DONE = "完了"
FAILED = "失敗"

EVENT_EXPAND = "expand"
EVENT_RECONCILE = "reconcile"
EVENT_CONFIRM_ORIGIN = "confirm_origin"
EVENT_WRITE = "write"
EVENT_FAIL = "fail"
EVENT_RESTART = "restart"

REJECT_NO_TRANSITION = "no_transition"
REJECT_GUARD_UNMET = "guard_unmet"


@dataclass(frozen=True)
class Facts:
    """ガードの判定に使う事実。渡さなかったものは偽。"""

    scope_expanded: bool = False
    reconciled: bool = False
    duplicates_found: bool = False
    origin_confirmed: bool = False
    stage_failed: bool = False
    origin_abandoned: bool = False
    written_and_verified: bool = False
    documents_unwritten: bool = False
    rerun_requested: bool = False


@dataclass(frozen=True)
class Transition:
    transition_id: str
    sources: tuple[str, ...]
    event: str
    guard: Callable[[str, Facts], bool]
    guard_text: str
    target: str


TRANSITIONS: tuple[Transition, ...] = (
    Transition(
        "E-01",
        (START,),
        EVENT_EXPAND,
        lambda state, facts: facts.scope_expanded,
        "[Index 対象指定]を検証し、展開した",
        SCOPE_READY,
    ),
    Transition(
        "E-02",
        (SCOPE_READY,),
        EVENT_RECONCILE,
        lambda state, facts: facts.reconciled and not facts.duplicates_found,
        "全対象の[DLID]と見出しを読み、既存の[DLID]と照合した。重複が無い",
        PLAN_CONFIRMED,
    ),
    Transition(
        "E-03",
        (SCOPE_READY,),
        EVENT_RECONCILE,
        lambda state, facts: facts.reconciled and facts.duplicates_found,
        "照合した結果、重複がある",
        AWAITING_ORIGIN,
    ),
    Transition(
        "E-04",
        (AWAITING_ORIGIN,),
        EVENT_CONFIRM_ORIGIN,
        lambda state, facts: facts.origin_confirmed,
        "利用者が原本を確定した",
        PLAN_CONFIRMED,
    ),
    Transition(
        "E-06",
        (START, SCOPE_READY, AWAITING_ORIGIN),
        EVENT_FAIL,
        lambda state, facts: (
            facts.stage_failed or (facts.origin_abandoned and state == AWAITING_ORIGIN)
        ),
        "当該段階の処理が失敗した、または利用者が原本を確定せずに終えた",
        FAILED,
    ),
    Transition(
        "E-05",
        (PLAN_CONFIRMED,),
        EVENT_WRITE,
        lambda state, facts: (
            facts.written_and_verified and not facts.documents_unwritten
        ),
        "全対象に[DLID]を書き込み、再解析で差分が[DLID]だけと確かめた",
        DONE,
    ),
    Transition(
        "E-06",
        (PLAN_CONFIRMED,),
        EVENT_FAIL,
        lambda state, facts: facts.stage_failed or facts.documents_unwritten,
        "当該段階の処理が失敗した（書き込めなかった文書が 1 件でもある場合を含む）",
        FAILED,
    ),
    Transition(
        "E-07",
        (FAILED,),
        EVENT_RESTART,
        lambda state, facts: facts.rerun_requested,
        "再実行を明示的に開始した",
        START,
    ),
)


class TransitionRejected(Exception):
    """表にない遷移、またはガード不成立。状態は変わらない。"""

    def __init__(self, reason: str, state: str, event: str):
        super().__init__(f"{reason}: 状態 {state} で事象 {event}")
        self.reason = reason
        self.state = state
        self.event = event


class EmbedRun:
    """付与操作 1 回の状態。`apply` は表に従って遷移させ、拒否したときは状態を変えない。"""

    def __init__(
        self, transitions: Iterable[Transition] = TRANSITIONS, state: str = START
    ):
        self._transitions = tuple(transitions)
        self.state = state

    def apply(self, event: str, facts: Facts | None = None) -> Transition:
        facts = facts if facts is not None else Facts()
        candidates = [
            t for t in self._transitions if t.event == event and self.state in t.sources
        ]
        if not candidates:
            raise TransitionRejected(REJECT_NO_TRANSITION, self.state, event)
        for transition in candidates:
            if transition.guard(self.state, facts):
                self.state = transition.target
                return transition
        raise TransitionRejected(REJECT_GUARD_UNMET, self.state, event)
