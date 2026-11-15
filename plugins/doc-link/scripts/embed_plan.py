"""embed-dlid の付与計画を、何も書き込まずに作る共通モジュール。

DES-005 §2.1 の 1〜4 を実装する。入口 script ではないので、PEP 723 とロックは持たない。書き込みと書き込み後の
検証・取消し（TASK-007）は持たない。この処理は対象文書と管理状態を読むだけである。

使う部品: 文書の解析は `markdown_reader.read_document`、重複の検出と発行は `dlid.find_duplicates`・
`dlid.issue_dlid`、管理状態の読取りは `state_store`。これらを再実装しない。

## 入力と出力

`build_plan(project_root, files, origins=None, issue=issue_dlid)` が `EmbedPlan` を返す。

- `files`: 対象文書のプロジェクトルート相対パス（`target_spec.expand` の `files`）
- `origins`: 利用者が確定した原本の指定。重複した[DLID]の値から、原本とする箇所（`DlidLocation`。
  `DuplicateReport.locations` の要素そのもの）への対応。無ければ空
- `issue`: [DLID]を 1 つ発行する関数。テストで固定値にできる

`EmbedPlan.items` が発行計画（書き込む[DLID]と位置）、`EmbedPlan.duplicates` が重複の報告（すべての該当箇所と
原本の候補）、`EmbedPlan.unresolved` が利用者の原本の指定をまだ受けていない重複である。`unresolved` が
空でないとき、計画は確定していない（DES-004 §5 の E-03 の原本確認待ち）。`unresolved` が空のとき、計画は確定
している（E-02 または E-04）。計画が出す重複しない欠落への発行は、`unresolved` の有無に関わらず `items` に出る。

失敗は `PlanFailure`（`kind`・`problems`）で、読めなかった文書と管理状態を空の結果や既定値で代替しない。

## 書き込む位置の表し方（TASK-007 が使う）

計画の各項目（`IssueItem`）の `position` は次の 2 種類に限る。リンク・リンクの title・本文を書き換える項目は
作らない。

- `FrontmatterPosition`（`kind` が `document`）: frontmatter の `doc_link_id`。
  - `frontmatter_present` が偽: markdown_reader が frontmatter を認識しなかった。frontmatter が無い場合と、
    閉じる行が無い場合を含み、計画では区別できない（閉じる行の無い frontmatter は frontmatter が無いものとして
    読まれる）。書き込む側が、先頭に frontmatter を新設する前に、必要なら区別する。`start_line`・`end_line` は `None`
  - `frontmatter_present` が真: `start_line` が開く `---` の行、`end_line` が閉じる `---` の行（0 始まりの行番号）。
    `key_present` が真なら `doc_link_id` のキーがあるが、認識できる値ではない（または複製の再発行で置き換える）ので、
    その行を置き換える。偽ならキーを足す
- `HeadingPosition`（`kind` が `section`）: 見出しの行の末尾。`start_line`・`end_line` は見出しの開始行と終了行の
  次の行（`[start, end)`、0 始まり、文書全体の行番号）。[セクション ID]を末尾に足す。再発行（`replaces` が値を持つ）では、
  見出しの末尾の語を置き換える

## 仕様の解釈（設計書が値や形式を定めていない点）

- 重複の検出は `dlid.find_duplicates` による、対象文書の中の複数の箇所である。管理状態は、重複した[DLID]の
  「記録されたパス」を得るために読む。対象文書に 1 箇所しかない[DLID]は、管理状態の記録のパスと違っても
  重複とせず、報告しない（文書の移動・セクションの移動は変更集合の仕事であり、付与操作の対象ではない）
- 管理状態の[DLID]の収集は、全キーの[確定 ToC]の `documents` の `doc_link_id` と `sections` の `section_id` である。
  [セクション ID]のパスは、その `doc_link_id` の文書のパスである。パスは[文書情報]（`state_store.load_document_info`
  の `path`）から得る。[文書情報]が無い（`missing`）か、記録の無い[DLID]は「記録されたパスが無い」とする。
  それ以外の管理状態の読取りの失敗は、`kind` を保って失敗にする。管理状態のキーが 1 件も無いことは、失敗でない
- 原本の候補は、記録されたパスのどれかと一致するパスの箇所である。候補が 1 つに絞れても、利用者が原本を指定する
  まで計画は確定しない（D-029、E-03 → E-04）。計画は候補を示すだけで、原本を決めない
- 原本の指定が、重複していない[DLID]を指す、または重複の箇所のどれにも当たらないとき、`PlanFailure` で拒否する。
  すべての重複について原本を指定するまで、`unresolved` は空にならない
- [文書 ID]の重複で、原本でない箇所の文書は、[文書 ID]を再発行し、その文書のすべての見出しの[セクション ID]
  （持たない見出しを含む）を再発行・新規発行する。再発行する文書の中の見出しを別の重複の原本に指定したときは、
  どちらかを決められないので拒否する
- 再発行する文書の外に重複の箇所が 1 つ以下しか残らない重複は、残る箇所が原本になるので、原本の指定を求めず
  `DuplicateReport.implied_by_reissue` を真にして、`unresolved` に含めない（`origin` は `None` のまま）。
  2 つ以上残る重複は、利用者の指定を求める。再発行する文書が決まるのは、その[文書 ID]の原本が指定されてからである
- 発行する値は、計画を作る時点で `issue` で発行する。同じ計画の中の値の重複や、既存の[DLID]との照合は
  しない（発行は確率的な一意性による。D-030）
- 同じパスの文書が `files` に複数回現れても、別の文書として数える（`dlid.find_duplicates` と同じ）
- 文書は UTF-8 で厳密に読む。デコードできない・読めない文書は、すべて集めて `PlanFailure` にする
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import state_store
from dlid import (
    KIND_DOCUMENT,
    KIND_SECTION,
    DlidLocation,
    DuplicateDlid,
    find_duplicates,
    issue_dlid,
)
from markdown_reader import MarkdownDocument, read_document

REASON_MISSING = "missing"
REASON_DUPLICATE = "duplicate"

FAILURE_DOCUMENT_UNREADABLE = "document_unreadable"
FAILURE_STATE_UNREADABLE = "state_unreadable"
FAILURE_INVALID_ORIGIN = "invalid_origin"


@dataclass(frozen=True)
class Problem:
    """失敗の 1 件。`path` は文書のパスまたは管理状態のパス、`state_kind` は管理状態の失敗の `kind`。"""

    path: str | None
    reason: str
    state_kind: str | None = None


class PlanFailure(Exception):
    """計画を作れなかった。`kind` は失敗の区別、`problems` は読めなかった文書・管理状態などの一覧。"""

    def __init__(self, kind: str, problems: Iterable[Problem]):
        self.problems = tuple(problems)
        super().__init__(
            f"{kind}: " + "; ".join(f"{p.path}: {p.reason}" for p in self.problems)
        )
        self.kind = kind


@dataclass(frozen=True)
class FrontmatterPosition:
    frontmatter_present: bool
    start_line: int | None
    end_line: int | None
    key_present: bool


@dataclass(frozen=True)
class HeadingPosition:
    start_line: int
    end_line: int


@dataclass(frozen=True)
class IssueItem:
    """発行計画の 1 項目。`replaces` は再発行で置き換える既存の[DLID]（新規なら `None`）。"""

    path: str
    kind: str
    dlid: str
    reason: str
    replaces: str | None
    position: FrontmatterPosition | HeadingPosition


@dataclass(frozen=True)
class DuplicateReport:
    """重複した[DLID]と、すべての該当箇所・記録されたパス・原本の候補。"""

    dlid: str
    locations: tuple[DlidLocation, ...]
    recorded_paths: tuple[str, ...]
    candidates: tuple[DlidLocation, ...]
    origin: DlidLocation | None
    implied_by_reissue: bool = False


@dataclass(frozen=True)
class EmbedPlan:
    items: tuple[IssueItem, ...]
    duplicates: tuple[DuplicateReport, ...]

    @property
    def unresolved(self) -> tuple[DuplicateReport, ...]:
        """原本の指定をまだ受けていない重複。[文書 ID]の再発行で決まった重複は含めない。"""
        return tuple(
            d for d in self.duplicates if d.origin is None and not d.implied_by_reissue
        )

    @property
    def confirmed(self) -> bool:
        """利用者への確認が残っていない（E-02 または E-04 の計画確定）。"""
        return not self.unresolved


def build_plan(
    project_root: str | Path,
    files: Iterable[str],
    origins: Mapping[str, DlidLocation] | None = None,
    issue: Callable[[], str] = issue_dlid,
) -> EmbedPlan:
    """付与計画を作る。対象文書と管理状態を読むだけで、何も書き込まない。"""
    root = Path(project_root)
    paths = list(files)
    texts = _read_texts(root, paths)
    documents = {index: read_document(text) for index, (_, text) in enumerate(texts)}

    duplicates = find_duplicates(texts)
    reports = _resolve_by_document_reissue(
        _report_duplicates(root, duplicates, dict(origins or {}))
    )
    reissue_locations, reissue_documents = _reissue_targets(
        reports, [path for path, _ in texts]
    )

    items: list[IssueItem] = []
    for index, (path, _) in enumerate(texts):
        items.extend(
            _items_for_document(
                path,
                documents[index],
                reissue_locations,
                path in reissue_documents,
                issue,
            )
        )
    return EmbedPlan(items=tuple(items), duplicates=tuple(reports))


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
        raise PlanFailure(FAILURE_DOCUMENT_UNREADABLE, problems)
    return texts


def _state_failure(exc: state_store.StateStoreError) -> PlanFailure:
    return PlanFailure(
        FAILURE_STATE_UNREADABLE,
        [Problem(str(exc.path) if exc.path else None, str(exc), exc.kind)],
    )


def _recorded_owners(root: Path) -> dict[str, set[str]]:
    """全キーの[確定 ToC]に記録された[DLID]から、所属する文書の[文書 ID]の集合への対応。"""
    owners: dict[str, set[str]] = {}
    try:
        for key in state_store.list_toc_keys(root):
            toc = state_store.load_confirmed_toc(root, key)
            for entry in toc["documents"]:
                owners.setdefault(entry["doc_link_id"], set()).add(entry["doc_link_id"])
            for entry in toc["sections"]:
                owners.setdefault(entry["section_id"], set()).add(entry["doc_link_id"])
    except state_store.StateStoreError as exc:
        raise _state_failure(exc) from exc
    return owners


def _recorded_paths(root: Path, owner_ids: set[str]) -> tuple[str, ...]:
    paths: set[str] = set()
    for doc_id in owner_ids:
        try:
            paths.add(state_store.load_document_info(root, doc_id)["path"])
        except state_store.StateStoreError as exc:
            if exc.kind == state_store.KIND_MISSING:
                continue  # [文書情報]が無い[DLID]は、記録されたパスが無い
            raise _state_failure(exc) from exc
    return tuple(sorted(paths))


def _report_duplicates(
    root: Path, duplicates: list[DuplicateDlid], origins: dict[str, DlidLocation]
) -> list[DuplicateReport]:
    by_dlid = {duplicate.dlid: duplicate for duplicate in duplicates}
    unknown = sorted(set(origins) - set(by_dlid))
    if unknown:
        raise PlanFailure(
            FAILURE_INVALID_ORIGIN,
            [
                Problem(None, f"重複していない[DLID]への原本の指定: {d}")
                for d in unknown
            ],
        )
    for dlid_value, origin in origins.items():
        if origin not in by_dlid[dlid_value].locations:
            raise PlanFailure(
                FAILURE_INVALID_ORIGIN,
                [
                    Problem(
                        origin.path, f"重複の箇所のどれにも当たらない原本: {dlid_value}"
                    )
                ],
            )
    if not duplicates:
        # 管理状態は重複の記録のパスを得るためだけに読む。重複が無いときも、読めないことは失敗にする。
        _recorded_owners(root)
        return []

    owners = _recorded_owners(root)
    reports = []
    for duplicate in duplicates:
        paths = _recorded_paths(root, owners.get(duplicate.dlid, set()))
        reports.append(
            DuplicateReport(
                dlid=duplicate.dlid,
                locations=duplicate.locations,
                recorded_paths=paths,
                candidates=tuple(l for l in duplicate.locations if l.path in paths),
                origin=origins.get(duplicate.dlid),
            )
        )
    return reports


def _resolve_by_document_reissue(
    reports: list[DuplicateReport],
) -> list[DuplicateReport]:
    """[文書 ID]の再発行が決まった文書の中の重複を、利用者の指定が要らないものにする。

    [文書 ID]を再発行する文書は、その文書のすべての見出しの[セクション ID]もあわせて再発行する
    （DES-005 §2.1 の 2）。再発行する文書の外に重複の箇所が 1 つ以下しか残らない重複は、残る箇所が
    原本になるので、別に原本の指定を求めない。2 つ以上残る重複は、これまでどおり利用者が指定する。
    """
    reissued = {
        location.path
        for report in reports
        if report.origin is not None
        for location in report.locations
        if location.kind == KIND_DOCUMENT and location != report.origin
    }
    if not reissued:
        return reports
    resolved = []
    for report in reports:
        remaining = [loc for loc in report.locations if loc.path not in reissued]
        if (
            report.origin is None
            and len(remaining) < len(report.locations)
            and len(remaining) <= 1
        ):
            report = replace(report, implied_by_reissue=True)
        resolved.append(report)
    return resolved


def _reissue_targets(
    reports: list[DuplicateReport], paths: list[str]
) -> tuple[set[tuple[str, str, int | None]], set[str]]:
    """原本が確定した重複の、原本でない箇所。（箇所の集合、文書ごと再発行する文書のパス）を返す。"""
    locations: set[tuple[str, str, int | None]] = set()
    documents: set[str] = set()
    origin_keys: set[tuple[str, str, int | None]] = set()
    for report in reports:
        if report.origin is None:
            continue
        origin_keys.add((report.origin.path, report.origin.kind, report.origin.line))
        for location in report.locations:
            if location == report.origin:
                continue
            locations.add((location.path, location.kind, location.line))
            if location.kind == KIND_DOCUMENT:
                documents.add(location.path)
    conflicts = sorted(
        {
            path
            for path, kind, _ in origin_keys
            if kind == KIND_SECTION and path in documents
        }
    )
    if conflicts:
        raise PlanFailure(
            FAILURE_INVALID_ORIGIN,
            [
                Problem(
                    path,
                    "[文書 ID]を再発行する文書の見出しが、別の重複の原本に指定された",
                )
                for path in conflicts
            ],
        )
    return locations, documents


def _items_for_document(
    path: str,
    document: MarkdownDocument,
    reissue_locations: set[tuple[str, str, int | None]],
    reissue_whole_document: bool,
    issue: Callable[[], str],
) -> list[IssueItem]:
    items: list[IssueItem] = []
    frontmatter = document.frontmatter
    doc_id = frontmatter.doc_link_id
    if doc_id is None or (path, KIND_DOCUMENT, None) in reissue_locations:
        items.append(
            IssueItem(
                path=path,
                kind=KIND_DOCUMENT,
                dlid=issue(),
                reason=REASON_MISSING if doc_id is None else REASON_DUPLICATE,
                replaces=doc_id,
                position=FrontmatterPosition(
                    frontmatter_present=frontmatter.present,
                    start_line=frontmatter.start_line if frontmatter.present else None,
                    end_line=frontmatter.end_line if frontmatter.present else None,
                    key_present=frontmatter.present
                    and "doc_link_id" in frontmatter.keys,
                ),
            )
        )
    for heading in document.headings:
        section_id = heading.section_id
        if section_id is None:
            reason = REASON_MISSING
        elif (
            reissue_whole_document
            or (
                path,
                KIND_SECTION,
                heading.start_line,
            )
            in reissue_locations
        ):
            reason = REASON_DUPLICATE
        else:
            continue
        items.append(
            IssueItem(
                path=path,
                kind=KIND_SECTION,
                dlid=issue(),
                reason=reason,
                replaces=section_id,
                position=HeadingPosition(
                    start_line=heading.start_line, end_line=heading.end_line
                ),
            )
        )
    return items
