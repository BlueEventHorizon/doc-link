"""[確定 ToC]から作った文書の一覧を[doc-db]へ同期する共通モジュール。

DES-011 §5、REQ-006 FR-024・AC-043（D-069）を実装する。入口 script ではないので、PEP 723 とロックは持たない。
[Index 対象文書]と管理状態へは書き込まない。読むのは、[確定 ToC]・[文書情報]（パス）・対象文書の存在だけである。

## 一覧の作成（DES-011 §5.1）

- 対象は、[確定 ToC]に所属するすべての[文書 ID]。パスは、各[文書 ID]の[文書情報]の現在のパス
- 一覧の各文書で、ファイルが存在し読めることを確かめる。存在しない文書は、一覧から除き、パスを報告する
  （削除された文書を[doc-db]の検索に残さない）
- 一覧は、現在の完全な状態として渡す（[doc-db]は、一覧に無いパスを series から切り離す）。0 件でも渡す
- 各文書は `{"path": プロジェクトルートからの相対パス, "local_path": 絶対パス}` である。本文は渡さない
  （全文書の本文を 1 回の呼び出しに載せると、大きさの上限に達しうるため）

## 同期の実行と完了の判定（DES-011 §5.2・§5.3）

投入（`sync_documents`）はジョブの識別値を即時に返す。完了（`done`）か失敗（`failed`）まで、状態（`get_sync_status`）を
繰り返し取得する。完了待ちの上限と間隔は TBD である（定数。実測で決める。暫定値）。上限を超えたときは、障害である。
完了したジョブの失敗は `docdb_contract.classify_job` で分類する。ジョブの応答の `document_errors` の有無で、契約を満たす
[doc-db]かを判断し（`SyncOutcome.contract_met`）、検索の判断にも使う。同期の呼び出し（投入・状態の取得）が返したエラーは、
識別子だけで分類する（`-32603` を、識別子が無くても OpenAI の失敗とみなすのは、検索の内部エラーだけである。同期の投入と
状態の取得は、Embedding を行わない）。

## 結果（`SyncOutcome.status`）

| `status`  | 意味                                                                                                            |
| --------- | --------------------------------------------------------------------------------------------------------------- |
| `synced`  | [doc-db]が一覧に一致した（S-03）                                                                                |
| `switch`  | [ToC]へ切り替える。`reason_code` は `docdb_unreachable`（接続できない）か `docdb_openai_failed`（OpenAI の失敗） |
| `failed`  | 障害。切り替えない（S-06）。`errors` に原因                                                                     |

`cause` は、通知の「原因」に載せてよい、固定の語句である。エラーの文言・HTTP の本文は載せない（要件 NFR-009）。
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import docdb_client
import docdb_contract
import docdb_identity
import state_store

STATUS_SYNCED = "synced"
STATUS_SWITCH = "switch"
STATUS_FAILED = "failed"

REASON_UNREACHABLE = "docdb_unreachable"
REASON_OPENAI_FAILED = "docdb_openai_failed"

#: 完了待ちの上限と間隔（秒）。TBD: 実測で決める値の暫定
WAIT_LIMIT_SECONDS = 600
POLL_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True)
class DocumentList:
    """同期の一覧。`documents` は[doc-db]へ渡す要素、`path_to_doc` はパスから[文書 ID]、`missing` は除いたパス。"""

    documents: tuple[dict, ...]
    path_to_doc: dict
    missing: tuple[str, ...]

    @property
    def listed(self) -> int:
        return len(self.documents)


@dataclass
class SyncOutcome:
    status: str
    listed: int = 0
    missing: tuple[str, ...] = ()
    reason_code: str | None = None
    cause: str | None = None
    presumed: bool = False
    errors: list[str] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    contract_met: bool = False

    def to_dict(self) -> dict:
        """標準出力へ返す同期の結果（`sync`）。件数までで、パスの一覧は `missing_paths` に持つ。"""
        return {
            "status": self.status,
            "listed": self.listed,
            "missing_count": len(self.missing),
            "missing_paths": list(self.missing),
            "counts": dict(self.counts),
            "contract_met": self.contract_met,
        }


def _readable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.R_OK)


def build_document_list(project_root: str | Path, toc_key: str) -> DocumentList:
    """[確定 ToC]から一覧を作る。管理状態を読めないときは `state_store.StateStoreError`。"""
    root = Path(os.path.abspath(project_root))
    toc = state_store.load_confirmed_toc(root, toc_key)
    entries: list[tuple[str, str]] = []
    for member in toc["documents"]:
        info = state_store.load_document_info(root, member["doc_link_id"])
        entries.append((info["path"], member["doc_link_id"]))
    entries.sort()
    documents: list[dict] = []
    path_to_doc: dict[str, str] = {}
    missing: list[str] = []
    for path, doc_id in entries:
        absolute = root / path
        if not _readable(absolute):
            missing.append(path)
            continue
        documents.append({"path": path, "local_path": str(absolute)})
        path_to_doc[path] = doc_id
    return DocumentList(tuple(documents), path_to_doc, tuple(missing))


def _from_exception(exc: docdb_client.DocDbClientError, listed: DocumentList):
    """接続・呼び出しの例外を、`SyncOutcome` にする。"""
    base = {"listed": listed.listed, "missing": listed.missing}
    if isinstance(exc, docdb_client.TransportError):
        return SyncOutcome(
            STATUS_SWITCH,
            reason_code=REASON_UNREACHABLE,
            cause=f"同期の途中で接続が断たれた（{exc.detail}）",
            **base,
        )
    if isinstance(exc, docdb_client.ToolError):
        # 同期の投入・状態の取得は、Embedding を行わない。識別子だけで分類する
        kind, _ = docdb_contract.classify_tool_error(exc.identifier, exc.code, True)
        if kind == docdb_contract.KIND_OPENAI:
            return SyncOutcome(
                STATUS_SWITCH,
                reason_code=REASON_OPENAI_FAILED,
                cause=f"同期が OpenAI の失敗で失敗した（{exc.detail}）",
                **base,
            )
    return SyncOutcome(
        STATUS_FAILED,
        errors=[f"doc-db の同期が失敗した（{exc.detail}）"],
        **base,
    )


def run_sync(
    client,
    project_root: str | Path,
    toc_key: str,
    *,
    listed: DocumentList | None = None,
    sleep=time.sleep,
    now=time.monotonic,
    wait_limit: float = WAIT_LIMIT_SECONDS,
    interval: float = POLL_INTERVAL_SECONDS,
    runner=docdb_identity.run_git,
) -> SyncOutcome:
    """一覧を作って[doc-db]へ同期し、完了まで待って、結果を分類する。`listed` を渡すと、一覧を作り直さない。"""
    try:
        if listed is None:
            listed = build_document_list(project_root, toc_key)
        key = docdb_identity.key_for(project_root, toc_key, runner)
    except state_store.StateStoreError as exc:
        return SyncOutcome(
            STATUS_FAILED, errors=[f"同期の一覧を作れない（{exc.kind}）: {exc}"]
        )
    series = docdb_identity.series_for(project_root)
    try:
        started = client.sync_documents(key, series, list(listed.documents))
    except docdb_client.DocDbClientError as exc:
        return _from_exception(exc, listed)
    job_id = started.get("job_id") if isinstance(started, dict) else None
    if not isinstance(job_id, str) or not job_id:
        return SyncOutcome(
            STATUS_FAILED,
            listed=listed.listed,
            missing=listed.missing,
            errors=["doc-db が同期のジョブの識別値を返さなかった"],
        )

    start = now()
    while True:
        try:
            job = client.get_sync_status(job_id)
        except docdb_client.DocDbClientError as exc:
            return _from_exception(exc, listed)
        status = job.get("status") if isinstance(job, dict) else None
        if status in ("done", "failed"):
            break
        if status != "running":
            return SyncOutcome(
                STATUS_FAILED,
                listed=listed.listed,
                missing=listed.missing,
                errors=["doc-db の同期のジョブの状態を解釈できない"],
            )
        if now() - start >= wait_limit:
            return SyncOutcome(
                STATUS_FAILED,
                listed=listed.listed,
                missing=listed.missing,
                errors=[
                    f"doc-db の同期が {wait_limit} 秒以内に完了しなかった（ジョブは doc-db 側で続いている）"
                ],
            )
        sleep(interval)

    counts = {
        name: job[name]
        for name in ("processed", "skipped", "failed")
        if isinstance(job.get(name), int)
    }
    met = docdb_contract.job_meets_contract(job)
    base = {
        "listed": listed.listed,
        "missing": listed.missing,
        "counts": counts,
        "contract_met": met,
    }
    if status == "failed":
        code = job.get("code")
        if isinstance(code, str) and (
            docdb_contract.classify_identifier(code) == docdb_contract.KIND_OPENAI
        ):
            return SyncOutcome(
                STATUS_SWITCH,
                reason_code=REASON_OPENAI_FAILED,
                cause=f"同期のジョブが OpenAI の失敗で失敗した（{code}）",
                **base,
            )
        detail = f"（{code}）" if isinstance(code, str) else ""
        return SyncOutcome(
            STATUS_FAILED, errors=[f"doc-db の同期のジョブが失敗した{detail}"], **base
        )
    kind, presumed, labels = docdb_contract.classify_job(job)
    if kind is None:
        if counts.get("failed", 0) > 0:
            return SyncOutcome(
                STATUS_FAILED,
                errors=[
                    f"doc-db の同期で {counts['failed']} 件の文書が失敗した（原因を示す情報が無い）"
                ],
                **base,
            )
        return SyncOutcome(STATUS_SYNCED, **base)
    if kind == docdb_contract.KIND_OPENAI:
        return SyncOutcome(
            STATUS_SWITCH,
            reason_code=REASON_OPENAI_FAILED,
            cause="同期での文書の Embedding が OpenAI の失敗で失敗した（"
            + "、".join(labels)
            + "）",
            presumed=presumed,
            **base,
        )
    return SyncOutcome(
        STATUS_FAILED,
        errors=["doc-db の同期が失敗した（" + "、".join(labels) + "）"],
        **base,
    )
