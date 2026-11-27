"""[doc-db]で検索し、結果を[文書 ID]・[セクション ID]へ対応づけて、[ToC]の検索結果と同じ形にする共通モジュール。

DES-011 §7.2〜§7.4、REQ-006 FR-025・AC-044 を実装する。入口 script ではないので、PEP 723 とロックは持たない。
何も書き込まない。

## 検索（DES-011 §7.2）

検索の文は、検索のタスクをそのまま渡す。モードは `all`（Embedding・語彙・全文一致の併用）である。`rerank` は使わない
（rerank の失敗は[doc-db]の内部で順序の保持に縮退し、失敗として届かないため）。上位の件数 `TOP_N` は TBD である
（定数。実測で決める。暫定値）。検索の失敗は `docdb_contract.classify_tool_error` で分類する。

## 対応づけ（DES-011 §7.3）

[doc-db]の結果は、チャンクごとの `path`・`heading_path`・`text`・`score` で、[DLID]の欄を持たない。

1. 文書: `path` を、同期した一覧のパスと照合し、一致した[文書 ID]を文書とする。一致しない結果は、文書に含めず、
   `unmapped` の件数に数える
2. セクション: `heading_path` の末尾の[DLID]（見出しの行の末尾の[セクション ID]）を取り出し、その[文書 ID]の
   セクションエントリにあれば、該当セクションにする。無ければ、文書だけを返す。[doc-db]の分割は、コードブロックの
   内側の `#` の行も見出しとして扱うので、`heading_path` は実際の見出しと食い違いうる。管理状態との照合が、食い違いを
   文書だけの結果に落とす。見出しの無い先頭のチャンク（`heading_path` が空）は、文書だけの結果とする
3. 同じ文書の複数のチャンクは 1 件にまとめる。順位は、その文書の最上位のチャンクの順位（1 から）で、該当セクションは、
   順位の順に重複なく集める

## 結果の項目（DES-011 §7.4）

`documents` の各要素は、`doc_link_id`・`recorded_path`・`relevance`（`maybe` の固定）・`reason`（script が事実から
組み立てる定型の文）・`sections`（`section_id`・`heading`）・`rank` である。`relevance` に `yes` を付けない。
`reason` は AI が書かない。
"""

import re
from dataclasses import dataclass, field

import dlid
import docdb_client
import docdb_contract
import docdb_identity
import docdb_sync

MODE = "all"
#: 検索の上位の件数。TBD: 実測で決める値の暫定
TOP_N = 20

RELEVANCE_MAYBE = "maybe"

_SECTION_DLID = re.compile(
    re.escape(dlid.DLID_PREFIX)
    + f"[{dlid.CROCKFORD_ALPHABET}]{{{dlid.DLID_VALUE_LENGTH}}}$"
)

NOTICE_ORDER = (
    "documents の並びは、doc-db が返した順位の順である。関連の強弱（relevance）は、doc-db が意味的な判定を"
    "返さないので、すべて maybe（判断がつかないが、関連するかもしれない）である"
)
NOTICE_LIMIT = (
    "doc-db の検索は、上位の結果に限られる。関連するかどうか迷う文書を結果に含める検索ではなく、"
    "関連する文書を取りこぼしうる"
)
NOTICE_PATH = (
    "recorded_path は、doc-db へ同期した時点の[確定 ToC]に記録されたパスであり、現在の実体パスとは限らない"
    "（文書が移動・削除されている可能性がある）"
)


class DocdbSearchError(Exception):
    """検索を完了できない。`switch` が真のとき、[ToC]へ切り替える。

    `reason_code`（`docdb_unreachable`・`docdb_openai_failed`）・`cause`（固定の語句）・`presumed`（原因が推定か）・
    `errors`（障害のときの自然文）を持つ。
    """

    def __init__(
        self,
        *,
        switch: bool,
        reason_code: str | None = None,
        cause: str | None = None,
        presumed: bool = False,
        errors: list[str] | None = None,
    ):
        super().__init__(cause or "; ".join(errors or []))
        self.switch = switch
        self.reason_code = reason_code
        self.cause = cause
        self.presumed = presumed
        self.errors = errors or []


@dataclass
class SearchResult:
    documents: list[dict] = field(default_factory=list)
    unmapped: int = 0
    hits: int = 0


def _reason(rank: int, chunks: int) -> str:
    return f"doc-db の検索の上位に入った（順位 {rank}、一致したチャンク {chunks} 件）"


def map_results(
    response: dict,
    path_to_doc: dict[str, str],
    paths: dict[str, str],
    sections: dict[str, dict[str, str]],
) -> SearchResult:
    """[doc-db]の応答を、[文書 ID]・[セクション ID]へ対応づける。

    `path_to_doc` は同期した一覧のパスから[文書 ID]、`paths` は[文書 ID]から記録されたパス、`sections` は
    [文書 ID]から（[セクション ID]→見出し）。応答の形が契約と違うときは `ValueError`。
    """
    results = response.get("results") if isinstance(response, dict) else None
    if not isinstance(results, list):
        raise ValueError("doc-db の検索の応答に results の配列が無い")
    outcome = SearchResult(hits=len(results))
    ordered: list[str] = []
    ranks: dict[str, int] = {}
    chunks: dict[str, int] = {}
    found: dict[str, list[str]] = {}
    for position, hit in enumerate(results, 1):
        if not isinstance(hit, dict) or not isinstance(hit.get("path"), str):
            raise ValueError("doc-db の検索の結果に path を持たない要素がある")
        doc_id = path_to_doc.get(hit["path"])
        if doc_id is None:
            outcome.unmapped += 1
            continue
        if doc_id not in ranks:
            ordered.append(doc_id)
            ranks[doc_id] = position
            chunks[doc_id] = 0
            found[doc_id] = []
        chunks[doc_id] += 1
        heading_path = hit.get("heading_path")
        if isinstance(heading_path, str):
            matched = _SECTION_DLID.search(heading_path.strip())
            if (
                matched is not None
                and matched.group(0) in sections.get(doc_id, {})
                and matched.group(0) not in found[doc_id]
            ):
                found[doc_id].append(matched.group(0))
    for rank_order, doc_id in enumerate(ordered, 1):
        outcome.documents.append(
            {
                "doc_link_id": doc_id,
                "recorded_path": paths[doc_id],
                "relevance": RELEVANCE_MAYBE,
                "reason": _reason(ranks[doc_id], chunks[doc_id]),
                "sections": [
                    {"section_id": section_id, "heading": sections[doc_id][section_id]}
                    for section_id in found[doc_id]
                ],
                "rank": rank_order,
            }
        )
    return outcome


def search(
    client,
    project_root,
    toc_key: str,
    task: str,
    path_to_doc: dict[str, str],
    paths: dict[str, str],
    sections: dict[str, dict[str, str]],
    *,
    met: bool = False,
    top_n: int = TOP_N,
    runner=docdb_identity.run_git,
) -> SearchResult:
    """[doc-db]で検索して、対応づけた結果を返す。完了できないときは `DocdbSearchError`。"""
    key = docdb_identity.key_for(project_root, toc_key, runner)
    series = docdb_identity.series_for(project_root)
    try:
        response = client.query(key, series, task, MODE, top_n)
    except docdb_client.TransportError as exc:
        raise DocdbSearchError(
            switch=True,
            reason_code=docdb_sync.REASON_UNREACHABLE,
            cause=f"検索の途中で接続が断たれた（{exc.detail}）",
        ) from exc
    except docdb_client.ToolError as exc:
        kind, presumed = docdb_contract.classify_tool_error(
            exc.identifier, exc.code, met
        )
        if kind == docdb_contract.KIND_OPENAI:
            raise DocdbSearchError(
                switch=True,
                reason_code=docdb_sync.REASON_OPENAI_FAILED,
                cause=f"検索が OpenAI の失敗で失敗した（{exc.detail}）",
                presumed=presumed,
            ) from exc
        raise DocdbSearchError(
            switch=False, errors=[f"doc-db の検索が失敗した（{exc.detail}）"]
        ) from exc
    except docdb_client.DocDbClientError as exc:
        raise DocdbSearchError(
            switch=False, errors=[f"doc-db の検索が失敗した（{exc.detail}）"]
        ) from exc
    try:
        return map_results(response, path_to_doc, paths, sections)
    except ValueError as exc:
        raise DocdbSearchError(switch=False, errors=[str(exc)]) from exc
