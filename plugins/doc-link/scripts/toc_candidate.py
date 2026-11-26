"""[ToC 候補]の組み立て・検査と、検査済みの候補だけの一括公開を持つ共通モジュール。

DES-005 §4・§5・§6、DES-003 §2・§4、DES-004 §2・§3（B-06〜B-08、P-01〜P-03）、DES-007 §1、DES-009 §1 と
REQ-003 §11.2.3・§11.2.4・FR-004・AC-017・AC-018・AC-020、REQ-001 D-024・D-025・D-038 を実装する。
入口 script ではないので、PEP 723 とロックは持たない。`index-docs` の入口 script（TASK-013）が、段階を進める
ときにこのモジュールの 3 つの操作を呼ぶ。状態遷移のガードは `build_state_machine` が持つ。

使う部品（再実装しない）: 変更集合は `change_set`、[確定 ToC]の保存・読取り・検査・一括置き換えは `state_store`、
参照の検査結果は `reference_check`、対象指定は `target_spec`。[文書情報]の要約の保存は `update_plan` が先に行う。
この処理が組み立てる候補は `state_store.CONFIRMED_TOC_FIELDS` の形であり、文書ごとに決まる値（[反映済みハッシュ]・
セクションエントリ・参照・最終検査状態）を[文書情報]のファイルへ、キーごとに決まる値を[確定 ToC]のファイルへ
分けて書くのは `state_store.save_confirmed_toc` である。

## 操作

- `assemble_candidate(...)`: [ToC 候補]（`state_store.CONFIRMED_TOC_FIELDS` を過不足なく持つ dict）を組み立てる。
  何も書き込まない。失敗は `CandidateFailure`（段階 `candidate_assembly`）
- `validate_candidate(...)`: 候補を検査する。何も書き込まない。失敗は `CandidateFailure`（段階 `candidate_validation`）
- `publish_candidate(...)`: 検査済みの候補を、`state_store.save_confirmed_toc` で公開する。文書ごとの値を
  [文書情報]へ書いてから、[確定 ToC]のファイルを置き換える。失敗は `CandidateFailure`（段階 `publish`）。
  [確定 ToC]のファイルは置き換わらず、書き終えた[文書情報]は戻らない（残りは次の検査が変更として検出する）
- `build_and_publish(...)`: 上の 3 つを順に行う

DES-004 §3 の段階との対応: 組み立てと検査は B-06（参照検査確定 → 候補検査済み）の処理であり、その失敗は参照検査確定からの
B-08 にあたる。公開は B-07（候補検査済み → 完了）の処理であり、その失敗は候補検査済みからの B-08 にあたる。
どの失敗でも候補は公開されず、旧[確定 ToC]は変わらず、それまでに確定した[文書情報]は戻らない（B-08、DES-005 §5）。

## 失敗の報告（DES-005 §6）

`CandidateFailure.report`（`FailureReport`）が、失敗した段階（`stage`）、対象の[文書 ID]・パス・フィールド・原因
（`problems`）、失敗の時点で[確定 ToC]のファイルがあるか（`confirmed_toc_present`）を持つ。原因を既定値で代替しない。

## 仕様の解釈（設計書が値や形式を定めていない点）

[確定 ToC]との対応は、`change_set.py` の module docstring の「仕様の解釈」に従う（次回の構築が、公開した
[確定 ToC]を同じ現物と比べて「変更なし」と判定するための前提）。

- `documents`: [確定 Index 対象リスト]の各文書の[文書 ID]と、変更集合から引き継いだ文書全体の[内容ハッシュ]
  （`DocumentChange.new_hash`。[反映済みハッシュ]）。ハッシュを再計算しない
- `sections`: `change_set.current_sections`（[セクション ID]を持つ見出しごとの所属文書・位置・見出し・
  セクションの[内容ハッシュ]）と同じ値。同じ規則で現物から取るため、変更集合の判定と同じ書き方になる。
  同じ[セクション ID]が複数箇所にあるときは、change_set と同じく最初の出現を採る
- `references`: 参照検査の結果（`reference_check.check_document` の返す `ReferenceCheckResult`）から作る。
  `position` は、文書の[正式な参照]を定義の開始行の順に並べたときの 0 始まりの通し番号。
  `recorded_path` は、デコード済みの宛先のパスに、フラグメントがあれば `#` とフラグメントを続けたもの。
  `recorded_content_hash` は title の記録語（無ければ `None`）
  - `kind`: 検査で参照先が見つかったときの `target_kind`（`document`・`section`）。見つからない（不在・重複・
    解決不能）ときは、文書か[セクション ID]かが分からないので `unknown`
  - `target_section_id` / `target_doc_id`: `kind` が `section` なら、`target_section_id` に参照先の[DLID]を入れ、
    `target_doc_id` に、その[セクション ID]を持つ所属文書の[文書 ID]を入れる。所属文書は、この候補の `sections`
    から先に引く。そこに無いときは、候補に入らない文書の[文書情報]に確定した値として記録されたセクションエントリ
    から引く。記録がどこにも無い、または複数の文書に記録されていて 1 つに決められないときは、所属文書を知る手段が
    ないので参照先の[DLID]をそのまま入れる。
    `kind` が `document` または `unknown` なら、`target_doc_id` に参照先の[DLID]を、`target_section_id` に
    `None` を入れる
  - `source_section_id`: `None`。設計書は、セクション単位の参照元の追跡を求めていない（REQ-003 §7.3 の「条件付き」）
  - `check`: `scope` は検査したディレクトリ（プロジェクトルート相対）で、走査しなかった（解決不能の）ときは空文字、
    `checked_at` は参照検査の結果が持つ時点、`result` は検査結果の区分（`match`・`path_mismatch`・
    `fragment_mismatch`・`absent`・`duplicate`・`unresolved`）、`found_path` は確認できた現在のパス（無ければ `None`）。
    `absent` の細かい理由（ディレクトリが無い・読めない等）は、保存のスキーマに持たないので記録しない
- `reverse_references`: `references` から機械的に作る（参照先 → 参照元）。同じ組は 1 件にまとめる
- `last_checks`: 文書ごとに 1 件。`checked_at` は呼び出し側から渡された検査の時点（全文書に共通の 1 つの値、
  または[文書 ID]から時点への対応）。`result` は、その文書の全参照の
  検査結果が `unresolved`（リンク先を解決できず走査できなかった）を含まなければ `success`、含めば `failure`。
  不在・パス不一致・フラグメント不一致・重複は、検査を完了した結果なので `success` である（D-025）。
  この処理は `unprocessed` を作らない（検査結果が渡されない文書は組み立ての失敗にする）
- `version`: 前の版（`state_store.load_confirmed_toc`）から決める。前の版が無ければ `1`。前の版があり、`version`
  を除く内容が同じなら前の版のまま（再実行で不要な差分を作らない。NFR-003）。違えば前の版に 1 を足す。前の版が
  整数でないときは次の版を決められないので、組み立ての失敗にする
- `target_spec`: 渡された[Index 対象指定]の `to_dict()`
- [文書情報]の要約（タイトル・目的・概要・適用作業・キーワード）は候補に含めない（D-024）。指定されていない
  キーの[確定 ToC]のファイルは、読まず・書かず・根拠にしない
- 離脱した文書（`UpdatePlan.departed`）と、ID 未付与・重複で除外した文書は、[確定 Index 対象リスト]に無いので
  候補に入らない

検査（`validate_candidate`。DES-005 §4）:

- [文書 ID]の一意性（`documents`）、[セクション ID]の一意性、参照の（参照元、位置）の一意性
- [確定 Index 対象リスト]との対応: `documents` が[確定 Index 対象リスト]と過不足なく対応すること。`sections`・
  `references`・`last_checks` の[文書 ID]が `documents` にあり、`last_checks` が文書ごとにちょうど 1 件であること
- 参照エントリと逆参照の対応: `references` から作る逆参照の集合と `reverse_references` が一致すること
- 必須フィールドの充足: `state_store.validate_confirmed_toc`。加えて、各文書の[文書情報]が確定済み（読める）で、
  その `content_hash` が[反映済みハッシュ]と一致すること（B-06 の「必須情報」。[文書情報]が無い文書を[ToC]に
  入れると、検索が[文書情報]を得られない）
- 参照先の不在・パス不一致・フラグメント不一致・ディレクトリを読めない・ディレクトリ自体が無い、は検査の対象にしない
  （記録すべき検査結果であって、確定の失敗ではない。D-025）

公開（`publish_candidate`）: 検査・公開のどちらかが失敗したときは候補を公開しない。構築中に現物が変わった場合の
再評価はしない（その変更は次の `check-toc` が検出する）。
"""

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import state_store
from change_set import ChangeSet, ConfirmedDocument, current_sections
from markdown_reader import read_document
from reference_check import STATUS_UNRESOLVED, ReferenceCheckResult
from target_spec import TargetSpec

STAGE_ASSEMBLY = "candidate_assembly"
STAGE_VALIDATION = "candidate_validation"
STAGE_PUBLISH = "publish"

RESULT_SUCCESS = "success"
RESULT_FAILURE = "failure"

KIND_UNKNOWN = "unknown"

FIRST_VERSION = 1


@dataclass(frozen=True)
class CandidateProblem:
    """失敗の 1 件。対象の[文書 ID]・パス・フィールドが特定できなければ `None`。"""

    doc_link_id: str | None
    path: str | None
    field: str | None
    cause: str

    def to_dict(self) -> dict:
        return {
            "doc_link_id": self.doc_link_id,
            "path": self.path,
            "field": self.field,
            "cause": self.cause,
        }


@dataclass(frozen=True)
class FailureReport:
    """失敗時の報告（DES-005 §6）。`confirmed_toc_present` は、失敗の時点で[確定 ToC]のファイルがあるか。"""

    stage: str
    problems: tuple[CandidateProblem, ...]
    confirmed_toc_present: bool

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "problems": [problem.to_dict() for problem in self.problems],
            "confirmed_toc_present": self.confirmed_toc_present,
        }


class CandidateFailure(Exception):
    """候補の組み立て・検査・公開のいずれかが失敗した。候補は公開されていない。"""

    def __init__(self, report: FailureReport):
        self.report = report
        super().__init__(
            f"{report.stage}: "
            + "; ".join(
                f"{p.doc_link_id or p.path or '-'}: {p.cause}" for p in report.problems
            )
        )


@dataclass(frozen=True)
class PublishResult:
    """公開に成功した候補。`written` は、[確定 ToC]のファイルを書き換えたとき真（同じ内容なら偽）。"""

    candidate: dict
    written: bool


def confirmed_toc_present(project_root: str | Path, toc_key: str) -> bool:
    """そのキーの[確定 ToC]のファイルがあるか。不正なキーはファイルを持ち得ないので偽。"""
    try:
        return state_store.confirmed_toc_path(Path(project_root), toc_key).is_file()
    except state_store.StateStoreError:
        return False


def _failure(
    project_root, toc_key: str, stage: str, problems: Iterable[CandidateProblem]
) -> CandidateFailure:
    return CandidateFailure(
        FailureReport(
            stage=stage,
            problems=tuple(problems),
            confirmed_toc_present=confirmed_toc_present(project_root, toc_key),
        )
    )


# --- 組み立て ----------------------------------------------------------------


def _load_previous(root: Path, toc_key: str) -> dict | None:
    try:
        return state_store.load_confirmed_toc(root, toc_key)
    except state_store.StateStoreError as exc:
        if exc.kind == state_store.KIND_MISSING:
            return None
        raise _failure(
            root,
            toc_key,
            STAGE_ASSEMBLY,
            [
                CandidateProblem(
                    None,
                    str(exc.path) if exc.path else None,
                    "version",
                    f"前の[確定 ToC]を読めない（{exc.kind}）: {exc}",
                )
            ],
        ) from exc


def _read_current(root: Path, toc_key: str, confirmed: Sequence[ConfirmedDocument]):
    current = {}
    problems: list[CandidateProblem] = []
    for item in confirmed:
        try:
            text = (root / item.path).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(
                CandidateProblem(item.doc_link_id, item.path, None, f"読めない: {exc}")
            )
            continue
        current[item.doc_link_id] = (item.path, read_document(text), text)
    if problems:
        raise _failure(root, toc_key, STAGE_ASSEMBLY, problems)
    return current


def _outside_section_owners(
    root: Path, toc_key: str, member_ids: set[str], section_ids: set[str]
) -> dict[str, str]:
    """候補に入らない文書の[文書情報]から、[セクション ID]の所属文書を引く。1 つに決まるものだけを返す。"""
    if not section_ids:
        return {}
    try:
        infos = state_store.load_all_document_infos(root)
    except state_store.StateStoreError as exc:
        raise _failure(
            root,
            toc_key,
            STAGE_ASSEMBLY,
            [
                CandidateProblem(
                    None,
                    str(exc.path) if exc.path else None,
                    "references",
                    f"[文書情報]を読めない（{exc.kind}）: {exc}",
                )
            ],
        ) from exc
    owners: dict[str, set[str]] = {}
    for info in infos:
        if info["doc_link_id"] in member_ids or info["applied_hash"] is None:
            continue
        for entry in info["sections"]:
            if entry["section_id"] in section_ids:
                owners.setdefault(entry["section_id"], set()).add(info["doc_link_id"])
    return {
        section_id: next(iter(found))
        for section_id, found in owners.items()
        if len(found) == 1
    }


def _reference_entry(
    doc_id: str, position: int, result: ReferenceCheckResult, section_owner: dict
) -> dict:
    reference = result.reference
    recorded_path = reference.path
    if reference.fragment is not None:
        recorded_path += "#" + reference.fragment
    kind = result.target_kind or KIND_UNKNOWN
    if kind == "section":
        target_section_id = reference.dlid
        target_doc_id = section_owner.get(reference.dlid, reference.dlid)
    else:
        target_section_id = None
        target_doc_id = reference.dlid
    return {
        "source_doc_id": doc_id,
        "source_section_id": None,
        "position": position,
        "target_doc_id": target_doc_id,
        "target_section_id": target_section_id,
        "recorded_path": recorded_path,
        "recorded_content_hash": reference.recorded_hash,
        "kind": kind,
        "check": {
            "scope": result.directory or "",
            "checked_at": result.checked_at,
            "result": result.status,
            "found_path": result.current_path,
        },
    }


def _reverse_entries(references: list[dict]) -> list[dict]:
    keys = {_reverse_key(entry) for entry in references}
    return [
        {
            "target_doc_id": key[0],
            "target_section_id": key[1],
            "source_doc_id": key[2],
            "source_section_id": key[3],
        }
        for key in sorted(
            keys, key=lambda key: tuple("" if v is None else v for v in key)
        )
    ]


def _reverse_key(entry: Mapping) -> tuple:
    return (
        entry["target_doc_id"],
        entry["target_section_id"],
        entry["source_doc_id"],
        entry["source_section_id"],
    )


def _comparable(toc: Mapping) -> dict:
    """`version` を除き、集合として意味を持つ配列を並べ替えた、比較用の写し。"""
    result = {name: value for name, value in toc.items() if name != "version"}
    for name in (
        "documents",
        "sections",
        "references",
        "reverse_references",
        "last_checks",
    ):
        result[name] = sorted(
            result[name],
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    return result


def _next_version(root: Path, toc_key: str, previous: dict | None, candidate: dict):
    if previous is None:
        return FIRST_VERSION
    version = previous["version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise _failure(
            root,
            toc_key,
            STAGE_ASSEMBLY,
            [
                CandidateProblem(
                    None,
                    None,
                    "version",
                    f"前の版が整数でないので次の版を決められない: {version!r}",
                )
            ],
        )
    if _comparable(previous) == _comparable(candidate):
        return version
    return version + 1


def assemble_candidate(
    project_root: str | Path,
    toc_key: str,
    target_spec: TargetSpec,
    change_set: ChangeSet,
    reference_results: Mapping[str, Sequence[ReferenceCheckResult]],
    checked_at: str | Mapping[str, str],
) -> dict:
    """[ToC 候補]を組み立てる。何も書き込まない。同じ入力から常に同じ候補を返す。

    `reference_results` は[文書 ID]から、その文書の[正式な参照]の検査結果（定義の行の順）への対応。
    [確定 Index 対象リスト]の全文書の結果を渡す（参照が無い文書は空の並び）。`checked_at` は検査の時点で、
    全文書に共通の 1 つの値か、[文書 ID]から時点への対応である。
    """
    root = Path(project_root)
    confirmed = change_set.confirmed_documents
    previous = _load_previous(root, toc_key)
    current = _read_current(root, toc_key, confirmed)

    hashes = {
        change.doc_link_id: change.new_hash
        for change in change_set.documents
        if change.new_hash is not None
    }
    problems: list[CandidateProblem] = []
    documents = []
    for item in confirmed:
        if item.doc_link_id not in hashes:
            problems.append(
                CandidateProblem(
                    item.doc_link_id,
                    item.path,
                    "applied_hash",
                    "変更集合に文書の[内容ハッシュ]が無い",
                )
            )
            continue
        documents.append(
            {"doc_link_id": item.doc_link_id, "applied_hash": hashes[item.doc_link_id]}
        )

    section_values = current_sections(current)
    section_owner = {sid: value.doc_link_id for sid, value in section_values.items()}
    member_ids = {item.doc_link_id for item in confirmed}
    outside_ids = {
        result.reference.dlid
        for doc_id, results in reference_results.items()
        if doc_id in member_ids
        for result in results
        if result.target_kind == "section"
        and result.reference.dlid not in section_owner
    }
    section_owner = {
        **_outside_section_owners(root, toc_key, member_ids, outside_ids),
        **section_owner,
    }
    sections = [
        {
            "doc_link_id": value.doc_link_id,
            "section_id": section_id,
            "heading": value.heading,
            "position": value.position,
            "content_hash": value.content_hash,
        }
        for section_id, value in sorted(
            section_values.items(), key=lambda kv: (kv[1].doc_link_id, kv[1].position)
        )
    ]

    references: list[dict] = []
    last_checks: list[dict] = []
    for item in confirmed:
        if item.doc_link_id not in reference_results:
            problems.append(
                CandidateProblem(
                    item.doc_link_id,
                    item.path,
                    "references",
                    "参照の検査結果が渡されていない",
                )
            )
            continue
        results = sorted(
            reference_results[item.doc_link_id], key=lambda r: r.reference.line
        )
        mismatched = [r for r in results if r.source_path != item.path]
        if mismatched:
            problems.append(
                CandidateProblem(
                    item.doc_link_id,
                    item.path,
                    "references",
                    f"参照の検査結果の参照元が文書のパスと違う: {mismatched[0].source_path}",
                )
            )
            continue
        for position, result in enumerate(results):
            references.append(
                _reference_entry(item.doc_link_id, position, result, section_owner)
            )
        failed = any(result.status == STATUS_UNRESOLVED for result in results)
        last_checks.append(
            {
                "doc_link_id": item.doc_link_id,
                "checked_at": (
                    checked_at
                    if isinstance(checked_at, str)
                    else checked_at[item.doc_link_id]
                ),
                "result": RESULT_FAILURE if failed else RESULT_SUCCESS,
            }
        )
    if problems:
        raise _failure(root, toc_key, STAGE_ASSEMBLY, problems)

    candidate = {
        "toc_key": toc_key,
        "version": FIRST_VERSION,
        "target_spec": target_spec.to_dict(),
        "documents": documents,
        "sections": sections,
        "references": references,
        "reverse_references": _reverse_entries(references),
        "last_checks": last_checks,
    }
    candidate["version"] = _next_version(root, toc_key, previous, candidate)
    return candidate


# --- 検査 --------------------------------------------------------------------


def _duplicates(values: Iterable) -> list:
    return sorted(
        (value for value, count in Counter(values).items() if count > 1),
        key=lambda value: json.dumps(value, ensure_ascii=False),
    )


def _consistency_problems(
    candidate: dict, confirmed: Sequence[ConfirmedDocument]
) -> list[CandidateProblem]:
    paths = {item.doc_link_id: item.path for item in confirmed}
    problems: list[CandidateProblem] = []

    def add(doc_id, field, cause):
        problems.append(CandidateProblem(doc_id, paths.get(doc_id), field, cause))

    doc_ids = [entry["doc_link_id"] for entry in candidate["documents"]]
    for doc_id in _duplicates(doc_ids):
        add(doc_id, "documents", "[文書 ID]が重複している")
    in_candidate = set(doc_ids)
    expected = set(paths)
    for doc_id in sorted(expected - in_candidate):
        add(doc_id, "documents", "[確定 Index 対象リスト]にあるが候補に無い")
    for doc_id in sorted(in_candidate - expected):
        add(doc_id, "documents", "候補にあるが[確定 Index 対象リスト]に無い")
    if len(confirmed) != len(expected):
        add(None, "documents", "[確定 Index 対象リスト]の[文書 ID]が重複している")

    for section_id in _duplicates(e["section_id"] for e in candidate["sections"]):
        add(None, "sections", f"[セクション ID]が重複している: {section_id}")
    for entry in candidate["sections"]:
        if entry["doc_link_id"] not in in_candidate:
            add(entry["doc_link_id"], "sections", "所属文書が候補の documents に無い")

    for source, position in _duplicates(
        (e["source_doc_id"], e["position"]) for e in candidate["references"]
    ):
        add(source, "references", f"参照の位置が重複している: {position}")
    for entry in candidate["references"]:
        if entry["source_doc_id"] not in in_candidate:
            add(entry["source_doc_id"], "references", "参照元が候補の documents に無い")

    check_ids = [entry["doc_link_id"] for entry in candidate["last_checks"]]
    for doc_id in _duplicates(check_ids):
        add(doc_id, "last_checks", "最終検査状態が重複している")
    for doc_id in sorted(in_candidate - set(check_ids)):
        add(doc_id, "last_checks", "最終検査状態が無い")
    for doc_id in sorted(set(check_ids) - in_candidate):
        add(doc_id, "last_checks", "最終検査状態の文書が候補の documents に無い")

    derived = {_reverse_key(entry) for entry in candidate["references"]}
    recorded = [_reverse_key(entry) for entry in candidate["reverse_references"]]
    for key in _duplicates(recorded):
        add(key[2], "reverse_references", f"逆参照が重複している: {key}")
    for key in sorted(derived - set(recorded), key=repr):
        add(key[2], "reverse_references", f"参照に対応する逆参照が無い: {key}")
    for key in sorted(set(recorded) - derived, key=repr):
        add(key[2], "reverse_references", f"逆参照に対応する参照が無い: {key}")
    return problems


def _document_info_problems(
    root: Path,
    candidate: dict,
    confirmed: Sequence[ConfirmedDocument],
    require_ai_fields: bool = True,
) -> list[CandidateProblem]:
    paths = {item.doc_link_id: item.path for item in confirmed}
    problems: list[CandidateProblem] = []
    for entry in candidate["documents"]:
        doc_id = entry["doc_link_id"]
        try:
            info = state_store.load_document_info(root, doc_id)
        except state_store.StateStoreError as exc:
            problems.append(
                CandidateProblem(
                    doc_id,
                    paths.get(doc_id),
                    "document_info",
                    f"[文書情報]を読めない（{exc.kind}）: {exc}",
                )
            )
            continue
        if require_ai_fields and info["content_hash"] != entry["applied_hash"]:
            problems.append(
                CandidateProblem(
                    doc_id,
                    paths.get(doc_id),
                    "document_info",
                    "[文書情報]の[内容ハッシュ]が[反映済みハッシュ]と一致しない",
                )
            )
    return problems


def validate_candidate(
    project_root: str | Path,
    candidate: dict,
    confirmed_documents: Iterable[ConfirmedDocument],
    require_ai_fields: bool = True,
) -> None:
    """候補を検査する（モジュールの docstring の「検査」）。何も書き込まない。通らなければ `CandidateFailure`。

    `require_ai_fields` が偽のとき（[doc-db]を使う構築。[AI 生成フィールド]を作らない）は、[文書情報]の
    [内容ハッシュ]が[反映済みハッシュ]と一致することを求めない。[文書情報]が読めることは、求める
    （要件 REQ-006 FR-019・D-064、DES-011 §6）。
    """
    root = Path(project_root)
    confirmed = tuple(confirmed_documents)
    toc_key = candidate.get("toc_key") if isinstance(candidate, dict) else None
    try:
        state_store.validate_confirmed_toc(candidate)
    except state_store.StateStoreError as exc:
        raise _failure(
            root,
            toc_key if isinstance(toc_key, str) else "",
            STAGE_VALIDATION,
            [CandidateProblem(None, None, None, f"必須フィールドを満たさない: {exc}")],
        ) from exc
    problems = _consistency_problems(candidate, confirmed)
    problems += _document_info_problems(root, candidate, confirmed, require_ai_fields)
    if problems:
        raise _failure(root, candidate["toc_key"], STAGE_VALIDATION, problems)


# --- 公開 --------------------------------------------------------------------


def publish_candidate(project_root: str | Path, skill: str, candidate: dict) -> bool:
    """検査済みの候補を公開する。[文書情報]か[確定 ToC]のファイルを書き換えたとき真。

    文書ごとの値を[文書情報]へ書いてから、[確定 ToC]のファイルを置き換える。失敗したときは `CandidateFailure`
    （段階 `publish`）で、[確定 ToC]のファイルは置き換わらない。
    """
    root = Path(project_root)
    try:
        return state_store.save_confirmed_toc(root, skill, candidate)
    except state_store.StateStoreError as exc:
        toc_key = candidate.get("toc_key") if isinstance(candidate, dict) else None
        raise _failure(
            root,
            toc_key if isinstance(toc_key, str) else "",
            STAGE_PUBLISH,
            [
                CandidateProblem(
                    None,
                    str(exc.path) if exc.path else None,
                    None,
                    f"公開に失敗した（{exc.kind}）: {exc}",
                )
            ],
        ) from exc


def build_and_publish(
    project_root: str | Path,
    skill: str,
    toc_key: str,
    target_spec: TargetSpec,
    change_set: ChangeSet,
    reference_results: Mapping[str, Sequence[ReferenceCheckResult]],
    checked_at: str | Mapping[str, str],
) -> PublishResult:
    """組み立て → 検査 → 公開を順に行う。どの段階の失敗も `CandidateFailure`。"""
    candidate = assemble_candidate(
        project_root, toc_key, target_spec, change_set, reference_results, checked_at
    )
    validate_candidate(project_root, candidate, change_set.confirmed_documents)
    written = publish_candidate(project_root, skill, candidate)
    return PublishResult(candidate, written)
