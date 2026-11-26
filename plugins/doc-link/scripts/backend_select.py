"""構築（`index-docs`）と検索（`query-docs`）の入口で、その実行の[検索基盤]を決める共通モジュール。

DES-011 §2・§8、REQ-006 FR-019〜FR-023・FR-027・AC-036〜AC-038・AC-042・AC-047・AC-048 を実装する。入口 script ではない
ので、PEP 723 とロックは持たない。[doc-db]を起動する（`docdb_runtime`）以外に、何も書き込まない。

## 判定（`decide`）

1. 設定ファイル `.doc-link/config.json`（`backend_config`）を読む。受理できないときは `BackendConfigError`
   （呼び出し側が、構築・検索を行わず、原因を返す）
2. `backend` が `toc`（強制スイッチ）のとき: [ToC]。[doc-db]へ接続せず、起動もせず、切り替えの通知も持たない
3. `auto` のとき: `docdb_runtime.ensure_available` で、接続の確認と、その場での起動・期限付きの再接続を行う
   - 接続できたとき: [doc-db]。`startup` は `not_attempted` か `succeeded`
   - 接続できなかったとき: [ToC]へ切り替える（接続できない (a)）。理由 `docdb_unreachable`、原因は `docdb_runtime` の `cause`

## 結果（`Decision`）

`backend`（`doc-db` か `toc`）、`forced`（強制スイッチか）、`startup`、`client`（[doc-db]のとき。標準出力に出さない）、`switch`（切り替えが起きたときの `Switch`）を持つ。
`to_dict()` が標準出力へ返す形である（`client` を含めない）。

## 切り替えの通知（`Switch`）

切り替えの通知の文は、script が組み立てる（DES-011 §8）。AI が通知の文を自分で書かないのは、理由・原因を推測で補う
ことを防ぐためである。項目は、切り替え・理由の分類・原因・影響・次の実行である。原因は、失敗の分類・終了コード・HTTP の
状態コード・識別子に限る（認証情報と、[doc-db]の応答の文言を含めない。要件 NFR-009）。原因が推定のとき（契約を満たさない版で、
識別子の無い検索の内部エラーを OpenAI の失敗とみなした）は、そのことを明記する。切り替えは保存しない。
"""

from dataclasses import dataclass

import backend_config
import docdb_runtime

BACKEND_DOCDB = "doc-db"
BACKEND_TOC = "toc"

REASON_UNREACHABLE = "docdb_unreachable"
REASON_OPENAI_FAILED = "docdb_openai_failed"

REASON_LABELS = {
    REASON_UNREACHABLE: "doc-db に接続できない",
    REASON_OPENAI_FAILED: "OpenAI の失敗（doc-db の検索または Embedding）",
}

NEXT_RUN = (
    "次の実行でも、doc-db を先に試す。ToC を使い続けるには、設定ファイル（`.doc-link/config.json`）の "
    '`backend` を `"toc"` にする'
)
PRESUMED_NOTE = "OpenAI の失敗と推定している（doc-db が契約を満たすと確認できず、エラーの識別子が無いため。原因は doc-db のログで確認する）"
UNREACHABLE_HINT = "doc-db を導入して起動できる状態にすると、既定で doc-db を使う"


@dataclass(frozen=True)
class Switch:
    """[ToC]への切り替え 1 件。`notice` は、AI が利用者へ伝える通知の文（script が組み立てる）。"""

    reason_code: str
    cause: str
    presumed: bool = False
    ai_fields_needed: int | None = None

    def with_impact(self, ai_fields_needed: int | None) -> "Switch":
        return Switch(self.reason_code, self.cause, self.presumed, ai_fields_needed)

    @property
    def notice(self) -> str:
        lines = [
            f"doc-db から ToC へ切り替えた（理由: {REASON_LABELS[self.reason_code]}）。",
            f"原因: {self.cause}",
        ]
        if self.presumed:
            lines.append(f"注意: {PRESUMED_NOTE}")
        if self.reason_code == REASON_UNREACHABLE and self.cause.startswith(
            docdb_runtime.CAUSE_EXECUTABLE_MISSING
        ):
            lines.append(UNREACHABLE_HINT + "。")
        impact = (
            "影響: ToC の検索では、AI が文書を読んで関連の強弱（yes・maybe）を判定する。"
            "上位の件数に限る doc-db の検索の制限は無くなる。"
        )
        if self.ai_fields_needed:
            impact += f" AI 生成フィールドを作る文書が {self.ai_fields_needed} 件ある。"
        lines.append(impact)
        lines.append(f"{NEXT_RUN}。")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "from": BACKEND_DOCDB,
            "to": BACKEND_TOC,
            "reason_code": self.reason_code,
            "reason": REASON_LABELS[self.reason_code],
            "cause": self.cause,
            "cause_presumed": self.presumed,
            "ai_fields_needed": self.ai_fields_needed,
            "next_run": NEXT_RUN,
            "notice": self.notice,
        }


@dataclass
class Decision:
    backend: str
    forced: bool = False
    startup: str | None = None
    client: object = None
    switch: Switch | None = None

    def to_dict(self) -> dict:
        """標準出力へ返す形。`client` を含めない。"""
        return {
            "backend": self.backend,
            "forced": self.forced,
            "startup": self.startup,
            "backend_switch": self.switch.to_dict() if self.switch else None,
        }

    def switched_to_toc(self, switch: Switch) -> "Decision":
        """[doc-db]を使っている途中で、[ToC]へ切り替えた判定を返す。"""
        return Decision(
            BACKEND_TOC,
            startup=self.startup,
            switch=switch,
        )


def decide(project_root, availability_provider=None) -> Decision:
    """その実行の[検索基盤]を決める。設定が受理できないときは `backend_config.BackendConfigError`。"""
    config = backend_config.load(project_root)
    if config.backend == backend_config.BACKEND_TOC:
        return Decision(BACKEND_TOC, forced=True)
    provider = availability_provider or docdb_runtime.ensure_available
    availability = provider()
    if availability.available:
        return Decision(
            BACKEND_DOCDB,
            startup=availability.startup,
            client=availability.client,
        )
    return Decision(
        BACKEND_TOC,
        startup=availability.startup,
        switch=Switch(
            REASON_UNREACHABLE,
            f"{availability.cause}: {availability.detail}",
        ),
    )
