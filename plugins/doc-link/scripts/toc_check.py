"""[確定 ToC]と現物を照合して、[ToC]の鮮度を判定する共通モジュール（何も書き込まない）。

DES-006 §1、DES-010 §1.2・§3.6、DES-005 §3、REQ-004 FR-006・AC-019、REQ-003 §10.2・FR-011、REQ-005 FR-016、
REQ-001 D-026・D-027・D-036・D-039 を実装する。`check-toc` と `query-docs` の検索前検査の両方が使う。
入口 script ではないので、PEP 723 とロックは持たない。[ToC]・[文書情報]・[Index 対象文書]へは書き込まず、
読むだけである。

使う部品: 対象指定の再解釈と展開は `target_spec`、変更集合（新規・離脱・パス変更・内容変更・参照記述の変更・
セクション）は `change_set.build_change_set`、生成が必要な文書の件数は `update_plan.build_update_plan`、管理状態の
読取りは `state_store`。これらを再実装しない。

## 入力と出力

`check_toc(project_root, toc_key=None, spec=None)` が `TocCheck` を返す。

- `toc_key`: [ToC 識別キー]。省略時は予約キー `all`（単体モード）
- `spec`: 呼び出し元が渡す完全な[Index 対象指定]（`TargetSpec`）。渡されたときは、[確定 ToC]に保存した指定より
  優先して現在の一覧を走査する。渡されないときは、保存した `target_spec` を `TargetSpec.from_dict` で再解釈する。
  `spec` と `toc_key` が対応しない（`all` モードのキーは `all`、`targets` モードの `spec.key` は `toc_key`）ときは
  `ValueError` である（呼び出し側の誤り）
- `TocCheck.status` は次の 4 つを区別する。「判定できなかった」を、ほかの 3 つのどれにも読み替えない
  - `not_built`（未構築）: 指定キーの[確定 ToC]が無い
  - `up_to_date`（再構築不要）: 照合して差が無い
  - `rebuild_needed`（再構築必要）: 差がある。`scale` に再構築の規模の件数（D-027）を持つ
  - `undeterminable`（判定不能）: 判定できなかった。`causes` に、判定できなかった対象と原因を持つ
- `documents`: 変更のある文書の一覧（`change_set.DocumentChange`）。新規・離脱・移動（パス変更）・内容変更・
  参照の違いを `kinds` に持ち、[反映済みハッシュ]（`old_hash`）と[現在ハッシュ]（`new_hash`）の違いは
  内容変更として一覧に現れる。変更のない文書は含めない
- `sections`: セクションごとの変更（`change_set.SectionChange`）
- `excluded`: ID 未付与・ID 重複で[確定 Index 対象リスト]に入れなかった文書。`excluded_in_toc` は、そのうち
  [確定 ToC]に入っている[文書 ID]の文書
- `target_spec_changed`: 渡された対象指定が、[確定 ToC]に保存した指定と違うか。`saved_target_spec` は、違うときの
  保存済みの指定（違わないとき、渡されないときは `None`）
- `counts`: 変更種別ごとの件数。`scale`: 再構築が必要なときの規模の件数
- `problems`・`warnings`: 対象指定の展開が報告した、存在しない・Markdown でない指定など

何も書き込まない。この処理の前後で、対象文書と管理状態（`.doc-link/` の全ファイル）はバイト単位で変わらない。

## 仕様の解釈（設計書が値や形式を定めていない点）

- 照合は `change_set.build_change_set` の判定をそのまま使う。title の記録語（D-039）を除いた[内容ハッシュ]と
  参照記述の比較値で比べるので、記録語だけの書き換えは差にならない
- 再構築必要の条件は、次のどれかがあること。
  - 渡された対象指定が、保存した指定と違う（要件 REQ-003 §7）。文書に差が無くても、再構築すると新しい指定が
    保存される。保存した指定が解釈できないときも、違うものとして扱う。規模の件数は、すべて 0 でありうる
  - 変更集合に、変更のある文書（新規・離脱・パス変更・内容変更・参照の違い）がある
  - セクションの変更がある
  - [確定 ToC]に入っている文書で、今回 ID 重複として除外されたものがある。再構築すると[確定 ToC]から除かれる。
    `change_set` はこれを離脱にしない（除外した文書の[文書 ID]は離脱としない）ので、この照合が見落とさないよう、
    ここで再構築必要にする。件数の区分は `duplicate_id` に入れる（離脱には数えない）
- ID 未付与・ID 重複で除外された文書は、[確定 ToC]に入っていなければ、それだけでは再構築必要にしない。再構築しても
  除外のままであり、毎回「古い」と判定されてしまうためである。再構築必要のときの規模には、すべての除外した文書の件数
  （`missing_id`・`duplicate_id`）を入れる。再構築で報告されるものであり、D-027 の件数である
- 規模の `ai_generation` は、`update_plan.build_update_plan` の生成対象（[文書 ID]と[内容ハッシュ]に対応する
  検証済み[文書情報]が無い文書）の数である。再構築必要のときだけ数える
- 規模の `new`・`departed`・`path_changed`・`content_changed` は、変更集合の文書のうち、その種別を持つ文書の数。
  1 つの文書が複数の種別に該当するとき、それぞれに数える。`counts` は、これに `references_changed`・`sections` を
  加えた件数である
- 判定不能にするもの: [確定 ToC]が `missing` 以外の理由で読めない・壊れている、渡されていない保存済みの対象指定を
  解釈できない、対象指定を展開できない（`OSError`）、対象文書を読めない（UTF-8 でない・権限不足など）、変更集合や
  更新計画が必要とする[文書情報]を読めない。frontmatter の解析不能は ID 未付与として扱い、判定不能にしない。
  対象ディレクトリ・対象ファイルの消失は、展開の `problems` に現れ、対象離脱として再構築必要にする。
  走査中に読めなかったディレクトリ（権限不足など。展開の `problems` の `unreadable`）は、配下の文書が一覧に入らず、
  対象離脱と区別できないので、判定不能にする（D-026）
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import state_store
import target_spec as target_spec_module
import update_plan
from change_set import (
    CHANGE_CONTENT,
    CHANGE_DEPARTED,
    CHANGE_NEW,
    CHANGE_PATH,
    CHANGE_REFERENCES,
    REASON_DUPLICATE,
    REASON_MISSING,
    ChangeFailure,
    DocumentChange,
    ExcludedDocument,
    SectionChange,
    build_change_set,
)
from target_spec import TargetSpec, TargetSpecError

STATUS_NOT_BUILT = "not_built"
STATUS_UP_TO_DATE = "up_to_date"
STATUS_REBUILD_NEEDED = "rebuild_needed"
STATUS_UNDETERMINABLE = "undeterminable"

SPEC_SOURCE_GIVEN = "given"
SPEC_SOURCE_SAVED = "saved"

CAUSE_STATE = "state"
CAUSE_TARGET_SPEC = "target_spec"
CAUSE_EXPANSION = "expansion"

DEFAULT_KEY = target_spec_module.RESERVED_KEY


@dataclass(frozen=True)
class Cause:
    """判定不能の原因 1 件。`target` は判定できなかった対象（パス・文書 ID など）、`kind` は原因の区別。"""

    target: str | None
    reason: str
    kind: str | None = None

    def to_dict(self) -> dict:
        return {"target": self.target, "reason": self.reason, "kind": self.kind}

    def describe(self) -> str:
        return f"{self.target}: {self.reason}" if self.target else self.reason


@dataclass(frozen=True)
class Scale:
    """再構築の規模（D-027）。参照先の走査結果と生成にかかる時間は含めない。"""

    new: int
    departed: int
    path_changed: int
    content_changed: int
    missing_id: int
    duplicate_id: int
    ai_generation: int

    def to_dict(self) -> dict:
        return {
            "new": self.new,
            "departed": self.departed,
            "path_changed": self.path_changed,
            "content_changed": self.content_changed,
            "missing_id": self.missing_id,
            "duplicate_id": self.duplicate_id,
            "ai_generation": self.ai_generation,
        }


@dataclass(frozen=True)
class TocCheck:
    status: str
    toc_key: str
    version: int | str | None = None
    spec_source: str | None = None
    target_spec: dict | None = None
    target_spec_changed: bool = False
    saved_target_spec: dict | None = None
    documents: tuple[DocumentChange, ...] = ()
    sections: tuple[SectionChange, ...] = ()
    excluded: tuple[ExcludedDocument, ...] = ()
    excluded_in_toc: tuple[ExcludedDocument, ...] = ()
    counts: dict | None = None
    scale: Scale | None = None
    causes: tuple[Cause, ...] = ()
    problems: tuple[dict, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "toc_key": self.toc_key,
            "version": self.version,
            "target_spec_source": self.spec_source,
            "target_spec": self.target_spec,
            "target_spec_changed": self.target_spec_changed,
            "saved_target_spec": self.saved_target_spec,
            "documents": [d.to_dict() for d in self.documents],
            "sections": [s.to_dict() for s in self.sections],
            "excluded": [e.to_dict() for e in self.excluded],
            "excluded_in_toc": [e.to_dict() for e in self.excluded_in_toc],
            "counts": self.counts,
            "scale": self.scale.to_dict() if self.scale else None,
            "causes": [c.to_dict() for c in self.causes],
            "problems": list(self.problems),
            "warnings": list(self.warnings),
        }


def _undeterminable(toc_key: str, causes: Iterable[Cause], **kwargs) -> TocCheck:
    return TocCheck(
        status=STATUS_UNDETERMINABLE,
        toc_key=toc_key,
        causes=tuple(causes),
        **kwargs,
    )


def _failure_causes(failure: ChangeFailure) -> list[Cause]:
    return [
        Cause(problem.path, problem.reason, problem.state_kind or failure.kind)
        for problem in failure.problems
    ]


def _check_key_and_spec(toc_key: str, spec: TargetSpec | None) -> None:
    if spec is None:
        return
    if spec.mode == target_spec_module.MODE_ALL:
        consistent = toc_key == DEFAULT_KEY
    else:
        consistent = spec.key == toc_key
    if not consistent:
        raise ValueError(
            f"対象指定が[ToC 識別キー]と対応しない: key={toc_key!r}, spec.mode={spec.mode!r}, spec.key={spec.key!r}"
        )


def _same_target_spec(saved: object, given: TargetSpec) -> bool:
    """渡された対象指定が、保存した指定と同じか。保存した指定を解釈できないときは、違うものとする。"""
    try:
        return TargetSpec.from_dict(saved).to_dict() == given.to_dict()
    except (TargetSpecError, KeyError, TypeError, AttributeError):
        return False


def _count(documents: Iterable[DocumentChange], kind: str) -> int:
    return sum(1 for document in documents if kind in document.kinds)


def check_toc(
    project_root: str | Path,
    toc_key: str | None = None,
    spec: TargetSpec | None = None,
) -> TocCheck:
    """[確定 ToC]と現物を照合する。対象文書と管理状態を読むだけで、何も書き込まない。"""
    root = Path(project_root)
    key = DEFAULT_KEY if toc_key is None else toc_key
    _check_key_and_spec(key, spec)

    try:
        toc = state_store.load_confirmed_toc(root, key)
    except state_store.StateStoreError as exc:
        if exc.kind == state_store.KIND_MISSING:
            return TocCheck(status=STATUS_NOT_BUILT, toc_key=key)
        return _undeterminable(
            key,
            [Cause(str(exc.path) if exc.path else key, str(exc), exc.kind)],
        )

    if spec is not None:
        used, source = spec, SPEC_SOURCE_GIVEN
    else:
        try:
            used = TargetSpec.from_dict(toc["target_spec"])
        except (TargetSpecError, KeyError, TypeError, AttributeError) as exc:
            reason = (
                "; ".join(exc.errors)
                if isinstance(exc, TargetSpecError)
                else f"保存済みの対象指定を解釈できない: {type(exc).__name__}: {exc}"
            )
            return _undeterminable(
                key,
                [Cause(f"{key} の target_spec", reason, CAUSE_TARGET_SPEC)],
                version=toc["version"],
            )
        source = SPEC_SOURCE_SAVED
    spec_changed = spec is not None and not _same_target_spec(
        toc.get("target_spec"), spec
    )
    common = {
        "version": toc["version"],
        "spec_source": source,
        "target_spec": used.to_dict(),
    }

    try:
        expansion = target_spec_module.expand(used, root)
    except OSError as exc:
        return _undeterminable(
            key,
            [
                Cause(
                    str(exc.filename) if exc.filename else None,
                    f"対象指定を展開できない: {exc}",
                    CAUSE_EXPANSION,
                )
            ],
            **common,
        )

    unreadable = [
        problem
        for problem in expansion.problems
        if problem.reason == target_spec_module.PROBLEM_UNREADABLE
    ]
    if unreadable:
        # 読めないディレクトリの配下の文書は一覧に入らない。対象離脱や空として扱わず、判定不能にする（D-026）
        return _undeterminable(
            key,
            [
                Cause(problem.path, "ディレクトリを読めない", CAUSE_EXPANSION)
                for problem in unreadable
            ],
            **common,
        )

    try:
        change_set = build_change_set(root, key, expansion.files)
    except ChangeFailure as failure:
        return _undeterminable(key, _failure_causes(failure), **common)

    changed = tuple(d for d in change_set.documents if not d.unchanged)
    recorded_ids = {entry["doc_link_id"] for entry in toc["documents"]}
    excluded_in_toc = tuple(
        item
        for item in change_set.excluded
        if item.reason == REASON_DUPLICATE and item.doc_link_id in recorded_ids
    )
    counts = {
        "new": _count(changed, CHANGE_NEW),
        "departed": _count(changed, CHANGE_DEPARTED),
        "path_changed": _count(changed, CHANGE_PATH),
        "content_changed": _count(changed, CHANGE_CONTENT),
        "references_changed": _count(changed, CHANGE_REFERENCES),
        "sections": len(change_set.sections),
        "missing_id": sum(
            1 for item in change_set.excluded if item.reason == REASON_MISSING
        ),
        "duplicate_id": sum(
            1 for item in change_set.excluded if item.reason == REASON_DUPLICATE
        ),
    }
    result = {
        **common,
        "target_spec_changed": spec_changed,
        "saved_target_spec": toc.get("target_spec") if spec_changed else None,
        "documents": changed,
        "sections": change_set.sections,
        "excluded": change_set.excluded,
        "excluded_in_toc": excluded_in_toc,
        "counts": counts,
        "problems": tuple(problem.to_dict() for problem in expansion.problems),
        "warnings": tuple(expansion.warnings),
    }

    if not (changed or change_set.sections or excluded_in_toc or spec_changed):
        return TocCheck(status=STATUS_UP_TO_DATE, toc_key=key, **result)

    try:
        plan = update_plan.build_update_plan(root, change_set)
    except ChangeFailure as failure:
        return _undeterminable(key, _failure_causes(failure), **common)
    scale = Scale(
        new=counts["new"],
        departed=counts["departed"],
        path_changed=counts["path_changed"],
        content_changed=counts["content_changed"],
        missing_id=counts["missing_id"],
        duplicate_id=counts["duplicate_id"],
        ai_generation=len(plan.generation_targets),
    )
    return TocCheck(status=STATUS_REBUILD_NEEDED, toc_key=key, scale=scale, **result)
