"""状態遷移の機構（遷移表をデータとして持ち、表にない遷移とガード不成立を拒否して状態を変えない）。

`embed_state_machine`（DES-004 §5、E-01〜E-07）と `build_state_machine`（DES-004 §2・§3、P-01〜P-03、
B-01〜B-09）が共通で使う。入口 script ではないので、PEP 723 とロックは持たない。表の中身（状態名・事象・
ガード）は持たない。

## 仕様の解釈（設計書が値や形式を定めていない点）

- 事象は文字列で、ガードの判定に使う事実は呼び出し側が定める型（`Facts`）で渡す。値を渡さなかった事実は
  偽とみなす（ガードを満たしたと推測しない）。このため `StateRun` は、事実を渡さないときの既定を作る関数を
  受け取る
- 同じ元状態・同じ事象の行が複数あるときは、表の順に最初にガードが成立した行を採る
- 拒否は `TransitionRejected` で、状態を変えない。拒否の理由は `reason` に、表にない事象・元状態は
  `no_transition`、ガード不成立は `guard_unmet` とする
- `Transition.target` が `None`（`KEEP_STATE`）の行は、状態を変えない（P-03 の「元のまま」）
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

REJECT_NO_TRANSITION = "no_transition"
REJECT_GUARD_UNMET = "guard_unmet"

KEEP_STATE = None


@dataclass(frozen=True)
class Transition:
    """遷移表の 1 行。`target` が `KEEP_STATE` のときは元の状態のまま。"""

    transition_id: str
    sources: tuple[str, ...]
    event: str
    guard: Callable[[str, Any], bool]
    guard_text: str
    target: str | None


class TransitionRejected(Exception):
    """表にない遷移、またはガード不成立。状態は変わらない。"""

    def __init__(self, reason: str, state: str, event: str):
        super().__init__(f"{reason}: 状態 {state} で事象 {event}")
        self.reason = reason
        self.state = state
        self.event = event


class StateRun:
    """状態 1 つ。`apply` は表に従って遷移させ、拒否したときは状態を変えない。"""

    def __init__(
        self,
        transitions: Iterable[Transition],
        state: str,
        default_facts: Callable[[], Any],
    ):
        self._transitions = tuple(transitions)
        self._default_facts = default_facts
        self.state = state

    def apply(self, event: str, facts: Any | None = None) -> Transition:
        facts = facts if facts is not None else self._default_facts()
        candidates = [
            t for t in self._transitions if t.event == event and self.state in t.sources
        ]
        if not candidates:
            raise TransitionRejected(REJECT_NO_TRANSITION, self.state, event)
        for transition in candidates:
            if transition.guard(self.state, facts):
                if transition.target is not KEEP_STATE:
                    self.state = transition.target
                return transition
        raise TransitionRejected(REJECT_GUARD_UNMET, self.state, event)
