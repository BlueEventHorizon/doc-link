"""変更影響候補の列挙を持つ共通モジュール（何も書き込まない）。

DES-007 §2・§3、DES-010 §1.2・§3.7、DES-009 §1（`check-impact`）、REQ-005 FR-013〜FR-015 と
REQ-001 D-033・D-038・D-039・D-043 を実装する。`check-impact` の入口 script が使う。入口 script ではないので、
PEP 723 とロックは持たない。[確定 ToC]・[文書情報]・参照元の文書を読むだけで、書き込まない。通知の状態を持たない。

[ToC]が最新であること（`toc_check.check_toc` が `up_to_date` を返すこと）は、呼び出し側が確かめる。このモジュールは
その確認をしない（`check-toc` の判定を別に実装しない）。

使う部品（再実装しない）: [確定 ToC]・[文書情報]の読取りは `state_store`、[正式な参照]の抽出と title の記録語の
読取りは `references`（`content_hash.read_recorded_hash` を経由）、文書の解析は `markdown_reader`。

## 列挙の規則

- 参照元は、[確定 ToC]の参照関係（`references`）から把握する。参照元の文書の位置は、参照元の[文書情報]の `path` である
- 参照元の現物を読み、[正式な参照]を定義の開始行の順に取り出す。[確定 ToC]の参照エントリの `position`（同じ順の
  0 始まりの通し番号）で、現物の参照と対応づける。title の記録は現物から読み、[確定 ToC]に保存した
  `recorded_content_hash` は使わない（記録だけを書き換えても[内容ハッシュ]は変わらず、[ToC]が古いと判定されない。D-039）
- 参照先の[現在ハッシュ]は、現物から計算せず、[確定 ToC]に記録した値を使う。参照先が[セクション ID]なら、[確定 ToC]の
  `sections` のそのセクションの `content_hash`。文書の[DLID]なら、`documents` のその[文書 ID]の `applied_hash`
- 記録と[現在ハッシュ]を、64 桁の文字列として完全一致で比べる。一致しない参照と、記録なしの参照を影響候補にする
- 参照先の[DLID]が[確定 ToC]の `sections` にも `documents` にも無い参照は、比べず、影響候補にしない（`check-links` が検出する）
- 間接の参照元は列挙しない（D-043）。直接の参照元だけを、変更された文書ごとにまとめる

## 仕様の解釈（設計書が値や形式を定めていない点）

- 参照先が[セクション ID]か文書の[DLID]かは、参照エントリの `kind` に頼らず、参照先の[DLID]を `sections` の
  `section_id`、次に `documents` の `doc_link_id` と照合して決める。`kind` が `unknown`（検査で参照先を見つけられなかった）
  でも、[確定 ToC]にその[DLID]があれば比べる
- 「変更された文書」は、参照先の所属文書である。[セクション ID]を指す参照は、そのセクションの所属文書の要素にまとめ、
  参照元ごとに `target_section_id`・`target_heading` を添える。変更された文書の `path` は、所属文書の[文書情報]の
  `path` である
- `line` は 1 始まりの行番号（定義の開始行）。`definition` は定義の原文（改行を除く）である
- 参照元に[確定 ToC]の参照エントリがあるのに、現物のその位置に参照が無い、または参照先の[DLID]が違うときは、
  [ToC]と現物が食い違っており列挙の根拠にならない。推測で補わず、失敗にする（`ImpactFailure`）
- 参照元の[文書情報]・現物・[確定 ToC]の読取りに失敗したときも、握りつぶさず `ImpactFailure` にする。
  このとき変更影響候補は返さない
- 並びは決定論的である: 変更された文書は[文書 ID]の昇順、参照元は（参照元のパス、行）の昇順
"""

from dataclasses import dataclass
from pathlib import Path

import state_store
from markdown_reader import read_document
from references import extract_from_document

TARGET_DOCUMENT = "document"
TARGET_SECTION = "section"


class ImpactFailure(Exception):
    """列挙を完了できなかった。`errors` は原因の自然文の配列。変更影響候補は返さない。"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class Referrer:
    """直接の参照元 1 件。`recorded_hash` は title に記録した[内容ハッシュ]（記録なしは `None`）。"""

    source_doc_id: str
    source_path: str
    line: int
    definition: str
    label: str
    link_path: str
    fragment: str | None
    target_dlid: str
    target_kind: str
    target_section_id: str | None
    target_heading: str | None
    recorded_hash: str | None
    current_hash: str

    def to_dict(self) -> dict:
        return {
            "source_doc_id": self.source_doc_id,
            "source_path": self.source_path,
            "line": self.line,
            "definition": self.definition,
            "label": self.label,
            "link_path": self.link_path,
            "fragment": self.fragment,
            "target_dlid": self.target_dlid,
            "target_kind": self.target_kind,
            "target_section_id": self.target_section_id,
            "target_heading": self.target_heading,
            "recorded_hash": self.recorded_hash,
            "current_hash": self.current_hash,
        }


@dataclass(frozen=True)
class ChangedDocument:
    """変更された文書（参照先の所属文書）と、その直接の参照元。"""

    doc_link_id: str
    path: str
    referrers: tuple[Referrer, ...]

    def to_dict(self) -> dict:
        return {
            "doc_link_id": self.doc_link_id,
            "path": self.path,
            "referrers": [referrer.to_dict() for referrer in self.referrers],
        }


@dataclass(frozen=True)
class ImpactResult:
    """列挙の結果。`scanned_documents` は参照を調べた参照元の文書（検査範囲）。"""

    toc_key: str
    toc_version: int | str
    target_spec: dict
    scanned_documents: tuple[str, ...]
    changed_documents: tuple[ChangedDocument, ...]


def _load_toc(root: Path, toc_key: str) -> dict:
    try:
        return state_store.load_confirmed_toc(root, toc_key)
    except state_store.StateStoreError as exc:
        raise ImpactFailure([f"[確定 ToC]を読めない（{exc.kind}）: {exc}"]) from exc


def _document_path(root: Path, doc_link_id: str) -> str:
    try:
        return state_store.load_document_info(root, doc_link_id)["path"]
    except state_store.StateStoreError as exc:
        raise ImpactFailure(
            [f"[文書情報]を読めない（{doc_link_id}、{exc.kind}）: {exc}"]
        ) from exc


def _read_source(root: Path, doc_link_id: str, path: str):
    try:
        text = (root / path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ImpactFailure(
            [f"参照元の文書を読めない（{doc_link_id}）: {path}: {exc}"]
        ) from exc
    document = read_document(text)
    return document, extract_from_document(document)


def _entry_dlid(entry: dict) -> str:
    return entry["target_section_id"] or entry["target_doc_id"]


def enumerate_impact(project_root: str | Path, toc_key: str) -> ImpactResult:
    """記録と[現在ハッシュ]が異なる参照を、変更された文書ごとにまとめて返す。何も書き込まない。"""
    root = Path(project_root)
    toc = _load_toc(root, toc_key)
    section_by_id = {entry["section_id"]: entry for entry in toc["sections"]}
    applied_by_id = {
        entry["doc_link_id"]: entry["applied_hash"] for entry in toc["documents"]
    }

    entries_by_source: dict[str, list[dict]] = {}
    for entry in toc["references"]:
        entries_by_source.setdefault(entry["source_doc_id"], []).append(entry)

    changed: dict[str, list[Referrer]] = {}
    scanned: list[str] = []
    for source_id in sorted(entries_by_source):
        source_path = _document_path(root, source_id)
        document, current = _read_source(root, source_id, source_path)
        scanned.append(source_path)
        end_lines = {d.start_line: d.end_line for d in document.references}
        for entry in sorted(entries_by_source[source_id], key=lambda e: e["position"]):
            position = entry["position"]
            dlid = _entry_dlid(entry)
            if position >= len(current) or current[position].dlid != dlid:
                raise ImpactFailure(
                    [
                        f"[確定 ToC]の参照と参照元の現物が食い違っている"
                        f"（{source_path}、位置 {position}、参照先 {dlid}）"
                    ]
                )
            reference = current[position]
            section = section_by_id.get(dlid)
            if section is not None:
                owner = section["doc_link_id"]
                current_hash = section["content_hash"]
                kind, section_id, heading = (
                    TARGET_SECTION,
                    dlid,
                    section["heading"],
                )
            elif dlid in applied_by_id:
                owner = dlid
                current_hash = applied_by_id[dlid]
                kind, section_id, heading = TARGET_DOCUMENT, None, None
            else:
                continue  # 参照先が[確定 ToC]に無い（check-links が検出する）
            if reference.recorded_hash == current_hash:
                continue
            definition = "".join(
                document.lines[reference.line : end_lines[reference.line]]
            ).rstrip("\r\n")
            changed.setdefault(owner, []).append(
                Referrer(
                    source_doc_id=source_id,
                    source_path=source_path,
                    line=reference.line + 1,
                    definition=definition,
                    label=reference.label,
                    link_path=reference.path,
                    fragment=reference.fragment,
                    target_dlid=dlid,
                    target_kind=kind,
                    target_section_id=section_id,
                    target_heading=heading,
                    recorded_hash=reference.recorded_hash,
                    current_hash=current_hash,
                )
            )

    documents = tuple(
        ChangedDocument(
            doc_link_id=owner,
            path=_document_path(root, owner),
            referrers=tuple(
                sorted(changed[owner], key=lambda r: (r.source_path, r.line))
            ),
        )
        for owner in sorted(changed)
    )
    return ImpactResult(
        toc_key=toc_key,
        toc_version=toc["version"],
        target_spec=toc["target_spec"],
        scanned_documents=tuple(scanned),
        changed_documents=documents,
    )
