"""構築（`index-docs`）と検索（`query-docs`）の入口で、その実行の[検索基盤]を決める共通モジュール。

DES-011 §2・§8、REQ-006 FR-019〜FR-023・FR-027・AC-036〜AC-038・AC-042・AC-047・AC-048 を実装する。入口 script ではない
ので、PEP 723 とロックは持たない。[doc-db]を起動する（`docdb_runtime`）以外に、何も書き込まない。

## 判定（`decide`）

1. 設定ファイル `.doc-link/config.json`（`backend_config`）を読む。受理できないときは `BackendConfigError`
   （呼び出し側が、構築・検索を行わず、原因を返す）
2. `backend` が `toc`（強制スイッチ）のとき: [ToC]。[doc-db]へ接続せず、起動もせず、切り替えの通知も持たない
3. `auto` のとき: `docdb_runtime.ensure_available` で、接続の確認と、利用者の許可を得た起動・期限付きの再接続を行う。
   利用者の許可は、呼び出しの引数 `startup`（`start`＝起動してよい、`toc`＝起動せず今回は[ToC]で続ける、無し＝未回答）で受ける
   - 接続できたとき: [doc-db]。`startup` は `not_attempted` か `succeeded`
   - 接続できず、実行ファイルがあり、`startup` が無いとき: 起動せずに止まる（`pending`。`confirm_docdb_startup`）。
     利用者に起動の許可を求める。許可は、`startup=start` で再度呼ぶ
   - `startup=toc` のとき: [doc-db]へ接続せず、起動もせず、[ToC]へ切り替える。理由 `docdb_startup_declined`
   - 許可を得て起動したが接続できなかったとき（起動できない・接続の前に終了した・期限内に接続できない）: 切り替えずに止まる
     （`pending`。`docdb_startup_failed`）。起動できなかったこと・原因の分類・起動の command を示し、利用者に「今回は[ToC]で続ける」
     か「起動してやり直す」かを選んでもらう
   - 実行ファイルが無い・設定から `port` を得られないとき: 起動できず、許可を求めても意味が無いので、[ToC]へ切り替える
     （接続できない (a)）。理由 `docdb_unreachable`、原因は `docdb_runtime` の `cause`

## 結果（`Decision`）

`backend`（`doc-db` か `toc`。`pending` のときは `None`）、`forced`（強制スイッチか）、`startup`、`client`（[doc-db]のとき。標準出力に出さない）、
`switch`（切り替えが起きたときの `Switch`）、`pending`（利用者の回答を待って止まるとき。`StartupPending`）を持つ。
`to_dict()` が標準出力へ返す形である（`client` を含めない）。`pending` のとき、入口 script は `pending.to_dict()` を結果として返し、
構築・検索を行わない（何も書き込まない）。

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

#: 呼び出しの引数 `--docdb-startup` の値
STARTUP_START = "start"
STARTUP_TOC = "toc"
STARTUP_CHOICES = (STARTUP_START, STARTUP_TOC)

REASON_UNREACHABLE = "docdb_unreachable"
REASON_OPENAI_FAILED = "docdb_openai_failed"
REASON_STARTUP_DECLINED = "docdb_startup_declined"

REASON_LABELS = {
    REASON_UNREACHABLE: "doc-db に接続できない",
    REASON_OPENAI_FAILED: "OpenAI の失敗（doc-db の検索または Embedding）",
    REASON_STARTUP_DECLINED: "利用者が doc-db を起動せず、今回は ToC で続けることを選んだ",
}

#: 止まって利用者に聞くときの `action`
ACTION_CONFIRM_STARTUP = "confirm_docdb_startup"
ACTION_STARTUP_FAILED = "docdb_startup_failed"

#: 起動の command（引数なし。ポート・ログの出力先は doc-db 自身の設定に任せる）
STARTUP_COMMAND = docdb_runtime.DOCDB_EXECUTABLE
DECLINE_CAUSE = "利用者の選択（doc-db を起動せず、ToC で続ける）"

NEXT_RUN = (
    "次の実行でも、doc-db を先に試す（接続できなければ、起動してよいかを聞く）。ToC を使い続けるには、設定ファイル（`.doc-link/config.json`）の "
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


#: 許可を得て起動したのに接続できなかった原因。切り替えず、利用者に続け方を選んでもらう
STARTUP_FAILURE_CAUSES = (
    docdb_runtime.CAUSE_SPAWN_FAILED,
    docdb_runtime.CAUSE_EXITED_EARLY,
    docdb_runtime.CAUSE_RECONNECT_FAILED,
)


@dataclass(frozen=True)
class StartupPending:
    """利用者の回答を待って止まる結果。文は script が組み立てる（AI が理由・原因を推測で補わないため）。

    - `confirm`: 接続できず、起動していない。起動してよいかを聞く
    - `failed`: 許可を得て起動したが、接続できなかった。起動できなかったことを示し、続け方を選んでもらう
    """

    kind: str
    cause: str | None = None
    detail: str | None = None

    def _toc_option(self) -> dict:
        return {
            "id": "toc",
            "label": "今回は ToC で続ける",
            "argument": f"--docdb-startup {STARTUP_TOC}",
            "effect": (
                "doc-db へ接続せず、起動もせず、今回は ToC で続ける。次の実行は、再び doc-db を先に試す。"
                "ToC で続けるときの影響（AI 生成フィールドの作成・検索の性質）は、続けた結果の通知で伝える"
            ),
        }

    def to_dict(self) -> dict:
        if self.kind == "confirm":
            return {
                "action": ACTION_CONFIRM_STARTUP,
                "startup": docdb_runtime.STARTUP_NOT_ATTEMPTED,
                "command": STARTUP_COMMAND,
                "detail": self.detail,
                "question": (
                    f"doc-db に接続できない。doc-db（`{STARTUP_COMMAND}`）を起動してよいか。"
                    "起動した doc-db は、doc-link の実行の後も動き続ける（doc-link は停止しない）"
                ),
                "options": [
                    {
                        "id": "start",
                        "label": "doc-db を起動する",
                        "argument": f"--docdb-startup {STARTUP_START}",
                        "effect": (
                            "doc-db を起動し、期限内に接続できれば doc-db で続ける。"
                            "接続できなければ、起動できなかったことを示して、続け方を選んでもらう"
                        ),
                    },
                    self._toc_option(),
                ],
            }
        return {
            "action": ACTION_STARTUP_FAILED,
            "startup": docdb_runtime.STARTUP_FAILED,
            "command": STARTUP_COMMAND,
            "cause": self.cause,
            "detail": self.detail,
            "message": (
                f"doc-db を起動できなかった（原因の分類: {self.cause}）。{self.detail}。"
                f"利用者が自分で起動するときの command は `{STARTUP_COMMAND}`（引数なし）である"
            ),
            "options": [
                {
                    "id": "retry",
                    "label": "起動してやり直す",
                    "argument": None,
                    "effect": (
                        f"利用者が `{STARTUP_COMMAND}` を起動した後、同じ呼び出しを `--docdb-startup` なしでやり直す。"
                        "接続できれば doc-db で続ける。接続できなければ、再び起動の許可を求める"
                    ),
                },
                self._toc_option(),
            ],
        }


@dataclass
class Decision:
    backend: str | None
    forced: bool = False
    startup: str | None = None
    client: object = None
    switch: Switch | None = None
    pending: StartupPending | None = None

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


def decide(
    project_root, availability_provider=None, startup: str | None = None
) -> Decision:
    """その実行の[検索基盤]を決める。設定が受理できないときは `backend_config.BackendConfigError`。

    `startup` は、利用者の回答（`STARTUP_CHOICES` のいずれか、または無し）。`availability_provider` は、
    `allow_startup`（起動の許可）を受け取り、`docdb_runtime.Availability` を返す。
    """
    config = backend_config.load(project_root)
    if config.backend == backend_config.BACKEND_TOC:
        return Decision(BACKEND_TOC, forced=True)
    if startup == STARTUP_TOC:
        return Decision(
            BACKEND_TOC,
            startup=docdb_runtime.STARTUP_NOT_ATTEMPTED,
            switch=Switch(REASON_STARTUP_DECLINED, DECLINE_CAUSE),
        )
    provider = availability_provider or docdb_runtime.ensure_available
    availability = provider(allow_startup=startup == STARTUP_START)
    if availability.available:
        return Decision(
            BACKEND_DOCDB,
            startup=availability.startup,
            client=availability.client,
        )
    if availability.status == docdb_runtime.STATUS_STARTUP_REQUIRED:
        return Decision(
            None,
            startup=availability.startup,
            pending=StartupPending("confirm", detail=availability.detail),
        )
    if availability.cause in STARTUP_FAILURE_CAUSES:
        return Decision(
            None,
            startup=availability.startup,
            pending=StartupPending(
                "failed", cause=availability.cause, detail=availability.detail
            ),
        )
    return Decision(
        BACKEND_TOC,
        startup=availability.startup,
        switch=Switch(
            REASON_UNREACHABLE,
            f"{availability.cause}: {availability.detail}",
        ),
    )
