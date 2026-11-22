"""[Index 対象リスト]を[確定 ToC]と照合して、変更集合を確定する共通モジュール（何も書き込まない）。

DES-005 §2 の 3・§3、DES-004 §3（B-02・B-03）、DES-003 §2・§4、DES-002 §2、REQ-003 §10.2 を実装する。
入口 script ではないので、PEP 723 とロックは持たない。AI 要約・参照先の実走査・[ToC]と[文書情報]の書き込み・更新計画の
作成（TASK-011）は持たない。この処理は対象文書と管理状態を読むだけである。

使う部品: 文書の解析は `markdown_reader.read_document`、[内容ハッシュ]は `content_hash`（リファレンスリンクの定義の行を除く規則を含む）、
[正式な参照]の抽出は `references`、管理状態の読取りは `state_store`。これらを再実装しない。

## 入力と出力

`build_change_set(project_root, toc_key, files)` が `ChangeSet` を返す。

- `files`: 今回の[Index 対象リスト]のプロジェクトルート相対パス（`target_spec.expand` の `files`）
- `ChangeSet.confirmed_documents`: [確定 Index 対象リスト]（[文書 ID]・現在のパス）
- `ChangeSet.excluded`: 除外した文書（パス・理由・認識できた[文書 ID]。ID 未付与は `None`）
- `ChangeSet.documents`: 文書ごとの変更（`DocumentChange`）。現在の[確定 Index 対象リスト]の順、続けて対象離脱の
  文書を[文書 ID]の昇順で並べる。変更なしの文書も含み、`unchanged` で区別する
- `ChangeSet.sections`: セクションごとの変更（`SectionChange`）。変更のないセクションは含まない
- `ChangeSet.first_build`: [確定 ToC]が無く、初回構築として扱ったとき真

失敗は `ChangeFailure`（`kind`・`problems`）で、読めなかった文書・管理状態を空の結果や既定値で代替しない。

## 仕様の解釈（設計書が値や形式を定めていない点）

[確定 ToC]との対応（TASK-012 が[ToC 候補]を組み立てるときに、同じ書き方をする）:

- 参照記述の比較値: 参照元がその文書（`source_doc_id` が[文書 ID]）の参照エントリを、次の 3 つ組の並びで比べる。
  - `position`: その文書の[正式な参照]を、定義の開始行の順に並べたときの 0 始まりの通し番号。行番号ではない
    （上に行を足しただけで全参照が変わったことにしない）
  - 参照先の[DLID]: 文書の[DLID]か[セクション ID]かは走査しないと決まらないので、`target_section_id` が
    `None` でなければそれ、`None` なら `target_doc_id` を、現物の `FormalReference.dlid` と比べる
  - 記載パス: `recorded_path` は、パーセント符号化をデコードした宛先のパス部分に、フラグメントがあれば `#` と
    フラグメントを続けたもの（`FormalReference.path` + `#` + `fragment`）。フラグメントがなければ `path` だけ
  - `source_section_id`・`recorded_content_hash`・`kind`・`check` は比べない。`recorded_content_hash`（title の記録語）
    は比較値に含めない（D-039）。`source_section_id` は、参照の移動が文書・セクションの[内容ハッシュ]に現れるので比べない
- セクションの `heading`: 見出しのテキストから、行末の[セクション ID]（最後の語）を除き、前後の空白を除いたもの
- セクションの `position`: 文書の見出しのうち[セクション ID]を持つものだけを出現順に数えた 0 始まりの通し番号
  （[セクション ID]を持たない見出しは数えない）。途中にセクションを足すと、それ以後のセクションは位置が変わり
  「移動」に該当する。設計書が「位置が違う」を移動と定めるので、それに従う
- セクションの `content_hash`: `content_hash.section_content_hashes` の値（リファレンスリンクの定義の行を除く）

判定:

- 内容変更は、文書全体の[内容ハッシュ]（リファレンスリンクの定義の行を除く）が `applied_hash` と異なること。パス変更は、現在のパスが
  [文書情報]の `path` と異なること。[確定 ToC]にある[文書 ID]で、現在の[確定 Index 対象リスト]にもある文書に
  ついて、[文書情報]を読む。[文書情報]が無い・読めないときは、変更なしや新規で代替せず `ChangeFailure` にする
- 変更種別は排他でない。新規の文書は、ほかの種別を持たない（比べる対象がない）
- 対象離脱は、[確定 ToC]の[文書 ID]が、今回の[Index 対象リスト]から得た[文書 ID]（除外した文書の[文書 ID]を
  含む）のどれでもないこと。除外した文書の[文書 ID]は、[Index 対象リスト]に含まれているので離脱にしない。除外した
  文書の[文書 ID]は、変更も新規も離脱も判定せず `excluded` が持つ。その[確定 ToC]のセクションも、削除と判定しない
- ID 未付与・重複の除外は、`dlid` の検出（`find_duplicates`）を使う。構築で扱う重複は[文書 ID]だけで、[セクション ID]の
  重複は扱わない（REQ-002 FR-002）。文書の ID が 2 つ以上のファイルにあるとき、そのすべてのファイルを除外する。
  ファイルが 1 つだけの[文書 ID]が、見出しの[セクション ID]と同じ値でも、除外しない。[セクション ID]が複数の
  箇所にあるときは、現在のセクションとして最初の出現（ファイルの順、見出しの順）を採る
- セクションの追加・削除・移動・見出し変更・本文変更は DES-005 §3 の規則どおりで、独立に記録する。見出しが違うとき
  は、本文変更を併記しない
- 初回構築（[確定 ToC]が `missing`）は、現在の[確定 Index 対象リスト]の全文書を新規、全セクションを追加とする。
  読めない・壊れている[確定 ToC]は、`kind` を保って `ChangeFailure` にし、初回構築として扱わない
- 同じパスが `files` に複数回現れたときは、別の文書として数える（重複した[文書 ID]を持つので除外される）
- 文書は UTF-8 で厳密に読む。デコードできない・読めない文書は、すべて集めて `ChangeFailure` にする
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

import state_store
from content_hash import document_content_hash, section_content_hashes
from dlid import KIND_DOCUMENT, find_duplicates
from markdown_reader import read_document
from references import extract_from_document

REASON_MISSING = "missing"
REASON_DUPLICATE = "duplicate"

CHANGE_NEW = "new"
CHANGE_DEPARTED = "departed"
CHANGE_PATH = "path_changed"
CHANGE_CONTENT = "content_changed"
CHANGE_REFERENCES = "references_changed"

SECTION_ADDED = "added"
SECTION_DELETED = "deleted"
SECTION_MOVED = "moved"
SECTION_HEADING = "heading_changed"
SECTION_BODY = "body_changed"

# 件数に必ず持つ種別（該当が無くても 0 で持つ）。文書の `unchanged` は種別を持たない文書の数。
DOCUMENT_KINDS = (
    CHANGE_NEW,
    CHANGE_CONTENT,
    CHANGE_REFERENCES,
    CHANGE_PATH,
    CHANGE_DEPARTED,
)
SECTION_KINDS = (
    SECTION_ADDED,
    SECTION_DELETED,
    SECTION_MOVED,
    SECTION_HEADING,
    SECTION_BODY,
)
DOCUMENT_UNCHANGED = "unchanged"

FAILURE_DOCUMENT_UNREADABLE = "document_unreadable"
FAILURE_STATE_UNREADABLE = "state_unreadable"


@dataclass(frozen=True)
class Problem:
    """失敗の 1 件。`path` は文書のパスまたは管理状態のパス、`state_kind` は管理状態の失敗の `kind`。"""

    path: str | None
    reason: str
    state_kind: str | None = None


class ChangeFailure(Exception):
    """変更集合を確定できなかった。`kind` は失敗の区別、`problems` は読めなかったものの一覧。"""

    def __init__(self, kind: str, problems: Iterable[Problem]):
        self.problems = tuple(problems)
        super().__init__(
            f"{kind}: " + "; ".join(f"{p.path}: {p.reason}" for p in self.problems)
        )
        self.kind = kind


@dataclass(frozen=True)
class ConfirmedDocument:
    doc_link_id: str
    path: str

    def to_dict(self) -> dict:
        return {"doc_link_id": self.doc_link_id, "path": self.path}


@dataclass(frozen=True)
class ExcludedDocument:
    """[確定 Index 対象リスト]に入れなかった文書。`doc_link_id` は ID 未付与なら `None`。"""

    path: str
    reason: str
    doc_link_id: str | None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "reason": self.reason,
            "doc_link_id": self.doc_link_id,
        }


@dataclass(frozen=True)
class ReferenceValue:
    """参照記述の比較値（モジュールの docstring の対応を参照）。"""

    position: int
    target_dlid: str
    recorded_path: str

    def to_dict(self) -> dict:
        return {
            "position": self.position,
            "target_dlid": self.target_dlid,
            "recorded_path": self.recorded_path,
        }


@dataclass(frozen=True)
class DocumentChange:
    """文書ごとの変更。`kinds` は該当した種別のすべて。変更前の値は[確定 ToC]・[文書情報]の記録である。

    新規は変更前の値を持たず、対象離脱は変更後の値を持たない（`None`）。
    """

    doc_link_id: str
    kinds: tuple[str, ...]
    old_path: str | None
    new_path: str | None
    old_hash: str | None
    new_hash: str | None
    old_references: tuple[ReferenceValue, ...] | None
    new_references: tuple[ReferenceValue, ...] | None

    @property
    def unchanged(self) -> bool:
        return not self.kinds

    def to_dict(self) -> dict:
        return {
            "doc_link_id": self.doc_link_id,
            "kinds": list(self.kinds),
            "unchanged": self.unchanged,
            "old_path": self.old_path,
            "new_path": self.new_path,
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
            "old_references": _reference_dicts(self.old_references),
            "new_references": _reference_dicts(self.new_references),
        }


@dataclass(frozen=True)
class SectionValue:
    doc_link_id: str
    position: int
    heading: str
    content_hash: str

    def to_dict(self) -> dict:
        return {
            "doc_link_id": self.doc_link_id,
            "position": self.position,
            "heading": self.heading,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class SectionChange:
    """セクションごとの変更。追加は `old` が、削除は `new` が `None`。"""

    section_id: str
    kinds: tuple[str, ...]
    old: SectionValue | None
    new: SectionValue | None

    def to_dict(self) -> dict:
        return {
            "section_id": self.section_id,
            "kinds": list(self.kinds),
            "old": self.old.to_dict() if self.old else None,
            "new": self.new.to_dict() if self.new else None,
        }


@dataclass(frozen=True)
class ChangeSet:
    confirmed_documents: tuple[ConfirmedDocument, ...]
    excluded: tuple[ExcludedDocument, ...]
    documents: tuple[DocumentChange, ...]
    sections: tuple[SectionChange, ...]
    first_build: bool

    def to_dict(self) -> dict:
        return {
            "first_build": self.first_build,
            "confirmed_documents": [d.to_dict() for d in self.confirmed_documents],
            "excluded": [d.to_dict() for d in self.excluded],
            "documents": [d.to_dict() for d in self.documents],
            "sections": [s.to_dict() for s in self.sections],
        }

    def with_first_old_paths(self, first_old_paths: dict[str, str]) -> "ChangeSet":
        """構築の途中で[文書情報]のパスが新しくなった文書の移動を、変更集合へ合わせる。

        `first_old_paths` は、[文書 ID]から、構築で最初に検出した移動の前のパスへの対応である。
        文書ごとに、その前のパス（無ければ今の比較の前のパス）と現在のパスを比べ、違えば移動（`path_changed`）を
        持たせ、同じなら（移動して元に戻した場合）持たせない。新規と対象離脱の文書は、パスを比べないので変えない。
        種別の並びは、判定の順（移動・本文変更・参照変更）に保つ。
        """
        documents = []
        for document in self.documents:
            if CHANGE_NEW in document.kinds or CHANGE_DEPARTED in document.kinds:
                documents.append(document)
                continue
            old_path = first_old_paths.get(document.doc_link_id, document.old_path)
            kinds = set(document.kinds)
            if old_path != document.new_path:
                kinds.add(CHANGE_PATH)
            else:
                kinds.discard(CHANGE_PATH)
            ordered = tuple(
                kind
                for kind in (CHANGE_PATH, CHANGE_CONTENT, CHANGE_REFERENCES)
                if kind in kinds
            )
            documents.append(replace(document, kinds=ordered, old_path=old_path))
        return replace(self, documents=tuple(documents))

    def summary(self) -> dict:
        """種別ごとの件数。複数の種別に該当する文書・セクションは、それぞれの種別に数える。

        文書の `unchanged` は、種別を持たない文書の数である。該当が無い種別も 0 で持つ。
        `confirmed_documents` は[確定 Index 対象リスト]の件数で、対象離脱の文書を含まない。
        """
        documents = {kind: 0 for kind in (*DOCUMENT_KINDS, DOCUMENT_UNCHANGED)}
        for document in self.documents:
            if document.unchanged:
                documents[DOCUMENT_UNCHANGED] += 1
            for kind in document.kinds:
                documents[kind] += 1
        sections = {kind: 0 for kind in SECTION_KINDS}
        for section in self.sections:
            for kind in section.kinds:
                sections[kind] += 1
        return {
            "first_build": self.first_build,
            "confirmed_documents": len(self.confirmed_documents),
            "documents": documents,
            "sections": sections,
        }


def _reference_dicts(values: tuple[ReferenceValue, ...] | None) -> list[dict] | None:
    return None if values is None else [value.to_dict() for value in values]


def build_change_set(
    project_root: str | Path, toc_key: str, files: Iterable[str]
) -> ChangeSet:
    """変更集合を確定する。対象文書と管理状態を読むだけで、何も書き込まない。"""
    root = Path(project_root)
    texts = _read_texts(root, list(files))
    toc = _load_toc(root, toc_key)

    documents = [read_document(text) for _, text in texts]
    confirmed, excluded = _check_ids(texts, documents)
    excluded_ids = {item.doc_link_id for item in excluded if item.doc_link_id}

    confirmed_ids = {item.doc_link_id for item in confirmed}
    current = {}  # 文書 ID -> (パス, 解析結果, 本文)。確定した文書の[文書 ID]は一意
    for (path, text), document in zip(texts, documents):
        doc_id = document.frontmatter.doc_link_id
        if doc_id in confirmed_ids:
            current[doc_id] = (path, document, text)
    confirmed_documents = tuple(confirmed)

    recorded = _recorded_documents(toc)
    recorded_paths = _recorded_paths(root, sorted(set(current) & set(recorded)))

    changes: list[DocumentChange] = []
    for item in confirmed_documents:
        path, document, text = current[item.doc_link_id]
        new_hash = document_content_hash(text)
        new_references = _reference_values(document)
        if toc is None or item.doc_link_id not in recorded:
            changes.append(
                DocumentChange(
                    doc_link_id=item.doc_link_id,
                    kinds=(CHANGE_NEW,),
                    old_path=None,
                    new_path=path,
                    old_hash=None,
                    new_hash=new_hash,
                    old_references=None,
                    new_references=new_references,
                )
            )
            continue
        old_path = recorded_paths[item.doc_link_id]
        old_hash = recorded[item.doc_link_id]
        old_references = _recorded_references(toc, item.doc_link_id)
        kinds = []
        if path != old_path:
            kinds.append(CHANGE_PATH)
        if new_hash != old_hash:
            kinds.append(CHANGE_CONTENT)
        if new_references != old_references:
            kinds.append(CHANGE_REFERENCES)
        changes.append(
            DocumentChange(
                doc_link_id=item.doc_link_id,
                kinds=tuple(kinds),
                old_path=old_path,
                new_path=path,
                old_hash=old_hash,
                new_hash=new_hash,
                old_references=old_references,
                new_references=new_references,
            )
        )
    for doc_id in sorted(set(recorded) - set(current) - excluded_ids):
        changes.append(
            DocumentChange(
                doc_link_id=doc_id,
                kinds=(CHANGE_DEPARTED,),
                old_path=None,
                new_path=None,
                old_hash=recorded[doc_id],
                new_hash=None,
                old_references=_recorded_references(toc, doc_id),
                new_references=None,
            )
        )

    sections = _section_changes(toc, current, excluded_ids)
    return ChangeSet(
        confirmed_documents=confirmed_documents,
        excluded=tuple(excluded),
        documents=tuple(changes),
        sections=sections,
        first_build=toc is None,
    )


def _read_texts(root: Path, paths: list[str]) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    problems: list[Problem] = []
    for path in paths:
        try:
            raw = (root / path).read_bytes()
            texts.append((path, raw.decode("utf-8")))
        except UnicodeDecodeError as exc:
            problems.append(Problem(path, f"UTF-8 として読めない: {exc}"))
        except OSError as exc:
            problems.append(Problem(path, f"読めない: {exc}"))
    if problems:
        raise ChangeFailure(FAILURE_DOCUMENT_UNREADABLE, problems)
    return texts


def _state_failure(exc: state_store.StateStoreError) -> ChangeFailure:
    return ChangeFailure(
        FAILURE_STATE_UNREADABLE,
        [Problem(str(exc.path) if exc.path else None, str(exc), exc.kind)],
    )


def _load_toc(root: Path, toc_key: str) -> dict | None:
    """[確定 ToC]を読む。無い（初回構築）ときだけ `None`。読めない・壊れているは失敗にする。"""
    try:
        return state_store.load_confirmed_toc(root, toc_key)
    except state_store.StateStoreError as exc:
        if exc.kind == state_store.KIND_MISSING:
            return None
        raise _state_failure(exc) from exc


def _check_ids(texts, documents):
    """ID 未付与と[文書 ID]の重複の文書を除外する。（確定の一覧、除外の一覧）を返す。"""
    duplicated = {
        duplicate.dlid
        for duplicate in find_duplicates(texts)
        if sum(1 for loc in duplicate.locations if loc.kind == KIND_DOCUMENT) > 1
    }
    confirmed: list[ConfirmedDocument] = []
    excluded: list[ExcludedDocument] = []
    for (path, _), document in zip(texts, documents):
        doc_id = document.frontmatter.doc_link_id
        if doc_id is None:
            excluded.append(ExcludedDocument(path, REASON_MISSING, None))
        elif doc_id in duplicated:
            excluded.append(ExcludedDocument(path, REASON_DUPLICATE, doc_id))
        else:
            confirmed.append(ConfirmedDocument(doc_id, path))
    return confirmed, excluded


def _recorded_documents(toc: dict | None) -> dict[str, str]:
    """[確定 ToC]の[文書 ID]から `applied_hash` への対応。"""
    if toc is None:
        return {}
    return {entry["doc_link_id"]: entry["applied_hash"] for entry in toc["documents"]}


def _recorded_paths(root: Path, doc_ids: list[str]) -> dict[str, str]:
    paths: dict[str, str] = {}
    problems: list[Problem] = []
    for doc_id in doc_ids:
        try:
            paths[doc_id] = state_store.load_document_info(root, doc_id)["path"]
        except state_store.StateStoreError as exc:
            problems.append(
                Problem(
                    str(exc.path) if exc.path else doc_id,
                    f"[確定 ToC]の文書の[文書情報]を読めない: {exc}",
                    exc.kind,
                )
            )
    if problems:
        raise ChangeFailure(FAILURE_STATE_UNREADABLE, problems)
    return paths


def _reference_values(document) -> tuple[ReferenceValue, ...]:
    values = []
    for position, reference in enumerate(extract_from_document(document)):
        recorded_path = reference.path
        if reference.fragment is not None:
            recorded_path += "#" + reference.fragment
        values.append(ReferenceValue(position, reference.dlid, recorded_path))
    return tuple(
        sorted(values, key=lambda v: (v.position, v.target_dlid, v.recorded_path))
    )


def _recorded_references(toc: dict, doc_id: str) -> tuple[ReferenceValue, ...]:
    values = [
        ReferenceValue(
            position=entry["position"],
            target_dlid=entry["target_section_id"] or entry["target_doc_id"],
            recorded_path=entry["recorded_path"],
        )
        for entry in toc["references"]
        if entry["source_doc_id"] == doc_id
    ]
    return tuple(
        sorted(values, key=lambda v: (v.position, v.target_dlid, v.recorded_path))
    )


def current_sections(current) -> dict[str, SectionValue]:
    sections: dict[str, SectionValue] = {}
    for doc_id, (_, document, text) in current.items():
        hashes = section_content_hashes(text)
        position = 0
        for heading, content_hash in zip(document.headings, hashes):
            if heading.section_id is None:
                continue
            words = heading.text.split()
            title = heading.text.rstrip()
            title = title[: len(title) - len(words[-1])].strip()
            sections.setdefault(
                heading.section_id,
                SectionValue(doc_id, position, title, content_hash),
            )
            position += 1
    return sections


def _section_changes(toc, current, excluded_ids) -> tuple[SectionChange, ...]:
    now = current_sections(current)
    before: dict[str, SectionValue] = {}
    if toc is not None:
        for entry in toc["sections"]:
            if entry["doc_link_id"] in excluded_ids:
                continue
            before[entry["section_id"]] = SectionValue(
                entry["doc_link_id"],
                entry["position"],
                entry["heading"],
                entry["content_hash"],
            )
    changes: list[SectionChange] = []
    for section_id in sorted(set(now) | set(before)):
        old, new = before.get(section_id), now.get(section_id)
        if old is None:
            kinds = [SECTION_ADDED]
        elif new is None:
            kinds = [SECTION_DELETED]
        else:
            kinds = []
            if old.doc_link_id != new.doc_link_id or old.position != new.position:
                kinds.append(SECTION_MOVED)
            if old.heading != new.heading:
                kinds.append(SECTION_HEADING)
            elif old.content_hash != new.content_hash:
                kinds.append(SECTION_BODY)
        if kinds:
            changes.append(SectionChange(section_id, tuple(kinds), old, new))
    return tuple(changes)
