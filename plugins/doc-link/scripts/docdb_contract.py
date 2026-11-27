"""[doc-db]に求める契約（要件 FR-028）に基づいて、[doc-db]の失敗を分類する共通モジュール。

DES-011 §2.3・§5.3、REQ-006 FR-021・FR-028・AC-039・AC-040・AC-049 を実装する。入口 script ではないので、
PEP 723 とロックは持たない。何も読み書きしない（純粋な判定）。

## 分類

| `kind`      | 意味                                                                                  | 呼び出し側の動作                                |
| ----------- | ------------------------------------------------------------------------------------- | ----------------------------------------------- |
| `openai`    | OpenAI の失敗 (b)（検索のクエリの Embedding、または同期での文書の Embedding の失敗）  | [ToC]へ切り替える（理由 `docdb_openai_failed`） |
| `fault`     | 障害。上記以外の[doc-db]の失敗                                                        | 切り替えず、失敗として返す                      |

接続できない (a)（`TransportError`）は、ここでは扱わない（呼び出し側が、例外の型で判断する）。

## 判別は識別子だけで行う（要件 FR-028）

JSON-RPC のエラーの `error.data.code`（`ToolError.identifier`）と、同期ジョブの文書ごとの失敗の `code` である。

| 識別子             | 意味                                                                   | 分類                                        |
| ------------------ | ---------------------------------------------------------------------- | ------------------------------------------- |
| `EMBEDDING_FAILED` | OpenAI から Embedding を得られなかった（再試行を尽くした後）           | `openai`                                    |
| `INTERNAL_ERROR`   | 上記以外のサーバー内部の失敗                                           | `fault`                                     |
| `KEY_NOT_FOUND`    | KEY が存在しない（既存）                                               | `fault`（同期の直後に起きないはずのため）   |
| `KEY_TRASHED`      | KEY がゴミ箱にある（既存）                                             | `fault`                                     |
| 上記に無い識別子   | 契約に無い                                                             | `fault`                                     |

識別子が付いたエラーは、[doc-db]が契約を満たすかによらず、識別子で分類する。

## 契約を満たす[doc-db]かの判断（同期の応答の目印）

[doc-db]の `get_sync_status` の応答に、`document_errors`（文書ごとの失敗の配列。失敗が無ければ空）があれば、契約を
満たす[doc-db]である（`job_meets_contract`）。目印が無ければ、満たさない[doc-db]として扱う。版の番号では判断しない。
doc-link は、検索の前に必ず同期するので、同じ実行の同期の応答を、検索の判断にも使う。

- 契約を満たす[doc-db]: 識別子の無いエラーは、契約の違反であり、`fault` である（入力の不正の JSON-RPC `-32602` のように、
  識別子が付かないものを含む。いずれも障害として扱う）
- 契約を満たさない[doc-db]（当面の扱い）:
  - 識別子の無い、検索の内部エラー（JSON-RPC の `-32603`）は、`openai`（原因は推定）とする
  - 同期ジョブのエラーの文言が `embed:` で始まる（または `<path>: embed:` の形）ものは、`openai` とする
  - 結果の警告に、契約を満たさない[doc-db]であることを含める（呼び出し側。`WARNING_CONTRACT_UNMET`）

## 同期ジョブの失敗の読み方

ジョブの結果（`get_sync_status` の応答）は、`status`（`running`・`done`・`failed`）、件数（`processed`・`skipped`・
`failed`）、既存のエラーの文字列の一覧 `errors`、文書ごとの失敗 `document_errors`（`{"path", "code", "skipped_chunks"?}` の
配列。`done` でも、Embedding に失敗した文書が載る）を持つ。失敗したジョブ（`failed`）は、最上位に `code`（識別子）を持つ。
形は、[doc-db]の修正（契約の実装）で確かめた。
"""

import re

KIND_OPENAI = "openai"
KIND_FAULT = "fault"

IDENTIFIER_EMBEDDING_FAILED = "EMBEDDING_FAILED"
IDENTIFIER_INTERNAL_ERROR = "INTERNAL_ERROR"
IDENTIFIER_KEY_NOT_FOUND = "KEY_NOT_FOUND"
IDENTIFIER_KEY_TRASHED = "KEY_TRASHED"

JSON_RPC_INTERNAL_ERROR = -32603

#: 契約を満たす[doc-db]の目印（`get_sync_status` の応答のキー）
CONTRACT_MARKER = "document_errors"

WARNING_CONTRACT_UNMET = (
    "使った doc-db が、doc-link が求める契約（エラーの識別子、Embedding が欠けた文書の再同期）を"
    "満たすと確認できない（同期の応答に document_errors が無い）。Embedding が欠けた文書が、内容が変わるまで"
    "補われないことがある"
)

_EMBED_TEXT = re.compile(r"(?:^|: )embed: ")


def job_meets_contract(job) -> bool:
    """同期ジョブの応答が、契約を満たす[doc-db]の目印（`document_errors`）を持つか。"""
    return isinstance(job, dict) and CONTRACT_MARKER in job


def classify_identifier(identifier: str) -> str:
    """識別子の分類。契約に無い識別子は `fault`。"""
    return KIND_OPENAI if identifier == IDENTIFIER_EMBEDDING_FAILED else KIND_FAULT


def classify_tool_error(identifier: str | None, code: int | None, met: bool):
    """`ToolError` の分類。`(kind, 推定か)` を返す。推定は、識別子が無く、当面の扱いで `openai` とした場合だけ真。"""
    if identifier is not None:
        return classify_identifier(identifier), False
    if not met and code == JSON_RPC_INTERNAL_ERROR:
        return KIND_OPENAI, True
    return KIND_FAULT, False


def classify_job(job: dict):
    """完了した（`done`）同期ジョブの分類。`(kind または None, 推定か, 失敗の分類の語句の配列)`。

    契約を満たすか（目印の有無）は、`job` から判断する。`kind` が `None` のときは、失敗が無い。語句は、利用者向けの出力に
    載せてよい固定の分類（識別子・件数）だけで、エラーの文言そのものは含めない。
    """
    errors = job.get("errors")
    errors = errors if isinstance(errors, list) else []
    if job_meets_contract(job):
        details = job["document_errors"]
        details = details if isinstance(details, list) else []
        if details:
            codes = [
                item["code"]
                for item in details
                if isinstance(item, dict) and isinstance(item.get("code"), str)
            ]
            if len(codes) != len(details):
                return KIND_FAULT, False, ["識別子の無い失敗"]
            if any(classify_identifier(code) == KIND_OPENAI for code in codes):
                return KIND_OPENAI, False, sorted(set(codes))
            return KIND_FAULT, False, sorted(set(codes))
        if errors:
            return KIND_FAULT, False, [f"識別子の無い失敗 {len(errors)} 件"]
        return None, False, []
    if not errors:
        return None, False, []
    if any(isinstance(error, str) and _EMBED_TEXT.search(error) for error in errors):
        return KIND_OPENAI, True, ["embed:（エラーの文言による判別）"]
    return KIND_FAULT, False, [f"識別子の無い失敗 {len(errors)} 件"]
