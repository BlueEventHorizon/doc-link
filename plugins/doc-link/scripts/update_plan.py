"""変更集合から更新計画を作り、検証済みの生成結果を[文書情報]として文書ごとに保存する共通モジュール。

DES-005 §4・§5、DES-003 §2・§4、DES-004 §3（B-04・B-08）、DES-008 §4、REQ-003 §11.2〜11.2.2、
REQ-001 D-024・D-044 を実装する。入口 script ではないので、PEP 723 とロックは持たない。AI の起動・依頼の組み立て・
Agent の結果の受け取り（TASK-014）、[ToC 候補]の組み立てと公開（TASK-012）は持たない。

使う部品: 変更集合は `change_set.ChangeSet`、[文書情報]の保存・読取りは `state_store`、生成結果の検証は
`ai_output_validator.validate_generated_fields`、文書の解析は `markdown_reader.read_document`。再実装しない。

## 入力と出力

- `build_update_plan(project_root, change_set)` が `UpdatePlan` を返す。文書と[文書情報]を読むだけで、何も書き込まない。
  入力は変更集合と[文書情報]だけであり、指定されていないキーの[ToC]は読まない
- `apply_path_updates(project_root, skill, plan)` が、パスだけの更新を保存する
- `store_generated(project_root, skill, plan, generated)` が、検証済みの生成結果を文書ごとに保存する
- 失敗は `change_set.ChangeFailure`（計画を作れない。`kind` を保つ。例外クラスと失敗の区別は `change_set` のものを使う）、または保存結果 `StoreOutcome` の `failed`（文書ごと）で返す

## 検証器のキー名と[文書情報]のフィールド名の対応（TASK-012・TASK-014 もこの対応に従う）

`ai_output_validator` の生成結果のキーと、[文書情報]の要約のフィールド名は、次の 1 つを除いて同じである。

| 生成結果（検証器）  | [文書情報]  |
| ------------------- | ----------- |
| `title`             | `title`     |
| `purpose`           | `purpose`   |
| `summary`           | `summary`   |
| `applicable_tasks`  | `tasks`     |
| `keywords`          | `keywords`  |

機械取得の `doc_link_id`・`path`・`content_hash` は、計画（変更集合から引き継いだ値）から書く。
この処理が書くのは要約の 8 項目だけである。構築が確定した値（`applied_hash`・`sections`・`references`・
`last_check`）は、`state_store.save_document_info` が保存済みの値を保ち、[ToC 候補]の公開が書く。

## 仕様の解釈（設計書が値や形式を定めていない点）

更新計画（文書ごとの `action`）:

- 対象は変更集合の[確定 Index 対象リスト]の文書。各文書について `state_store.load_document_info` を読み、次で決める
  - `missing`（[文書 ID]自体が新規、または[文書情報]が無い）: `generate`（理由 `new_document`）
  - 読めた[文書情報]の `content_hash` が現在の[内容ハッシュ]と違う: `generate`（理由 `content_changed`）
  - 同じ: AI に生成させない。`path` が現在のパスと違えば `update_path`（現在パスだけを更新）、同じなら `reuse`
  - `corrupt`・`unreadable`・`invalid` は新規で代替せず、`kind` を保って `change_set.ChangeFailure` にする。
    失敗はすべて集めて 1 つの失敗にする。文書を読めない失敗（`document_unreadable`）と[文書情報]を読めない失敗
    （`state_unreadable`）が両方あるときは、`kind` を `document_unreadable` とし、`problems` に両方を並べる
    （[文書情報]の失敗は `Problem.state_kind` を持つ）
- 「指定キーの[ToC]では新規」（`new`）でも、[文書 ID]と[内容ハッシュ]に対応する[文書情報]があれば `reuse` または
  `update_path` であり、生成対象にならない（D-024）。判定に[確定 ToC]の `applied_hash` を使わない
- 参照変更だけで[内容ハッシュ]が同じ文書は、`reuse`（または `update_path`）である
- 対象離脱は、指定キーの[ToC]から除くことだけであり、[文書情報]を消さない。`UpdatePlan.departed` に[文書 ID]を
  並べ、TASK-012 が[ToC 候補]から除く。ここでは何も書かない
- タイトル: 文書の最初のレベル 1 の見出しのテキストから、行末の[セクション ID]を除き前後の空白を除いたもの。
  空になる、または H1 が無いときは `title` を `None` とし、生成対象のフィールドに `title` を含める
- 依頼に必要な情報として、生成対象の文書のパスと、フィールドごとの記述上限 `L`（`limits`）だけを持つ。
  `H`・係数・余白は、計画にも結果にも含めない（NFR-008）
- `documents` の順は、変更集合の[確定 Index 対象リスト]の順

保存:

- 生成対象の文書の結果は、H1 から取れたタイトルがあるとき、検証の前に `title` をそのタイトルで置き換える
  （タイトルは機械取得を優先し、AI の値を採らない）。H1 が無いときは、生成したタイトルを検証して受け取る
- 検証に通らない結果と、生成結果が渡されなかった文書は保存せず、その文書の失敗（フィールド・理由）として返す。再試行しない
- 文書ごとに保存し、失敗した文書があっても残りの文書の保存を続ける。保存済みの[文書情報]は、後の失敗で戻さない
- 保存の失敗（`StateStoreError`）は、握りつぶさず、その文書の失敗として `kind` を保って返す
- 内容が変わらない[文書情報]は書き換えない（`status` が `unchanged`）
- 生成結果に計画にない文書の[文書 ID]があるとき、または生成対象でない文書の結果があるときは、保存せずその文書の失敗にする
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import state_store
from ai_output_validator import ARRAY_LIMIT, PURPOSE_LIMIT, validate_generated_fields
from change_set import (
    FAILURE_DOCUMENT_UNREADABLE,
    FAILURE_STATE_UNREADABLE,
    ChangeFailure,
    ChangeSet,
    Problem,
)
from markdown_reader import read_document

ACTION_GENERATE = "generate"
ACTION_UPDATE_PATH = "update_path"
ACTION_REUSE = "reuse"

REASON_NEW_DOCUMENT = "new_document"
REASON_CONTENT_CHANGED = "content_changed"

STATUS_SAVED = "saved"
STATUS_UNCHANGED = "unchanged"
STATUS_FAILED = "failed"

KIND_REJECTED = "rejected"
KIND_NOT_PLANNED = "not_planned"
KIND_NOT_GENERATED = "not_generated"

# 生成結果のキーと、[文書情報]のフィールド名の対応（モジュールの docstring を参照）。
GENERATED_TO_INFO = {
    "title": "title",
    "purpose": "purpose",
    "summary": "summary",
    "applicable_tasks": "tasks",
    "keywords": "keywords",
}

# 依頼に渡してよい記述上限 L（要件 D-044）。
FIELD_LIMITS = {
    "purpose": PURPOSE_LIMIT,
    "summary": ARRAY_LIMIT,
    "applicable_tasks": ARRAY_LIMIT,
    "keywords": ARRAY_LIMIT,
}


@dataclass(frozen=True)
class DocumentPlan:
    """文書ごとの更新計画。`generate_fields` は AI に生成させるフィールド（生成結果のキー名）。

    `generate` でない文書は空。`title` は H1 から取れたタイトル（無ければ `None`）。
    """

    doc_link_id: str
    path: str
    content_hash: str
    kinds: tuple[str, ...]
    action: str
    reason: str | None
    title: str | None
    generate_fields: tuple[str, ...]

    @property
    def limits(self) -> dict[str, int]:
        """依頼に渡す、生成するフィールドごとの記述上限 `L`。"""
        return {
            name: FIELD_LIMITS[name]
            for name in self.generate_fields
            if name in FIELD_LIMITS
        }

    def to_dict(self) -> dict:
        return {
            "doc_link_id": self.doc_link_id,
            "path": self.path,
            "content_hash": self.content_hash,
            "kinds": list(self.kinds),
            "action": self.action,
            "reason": self.reason,
            "title": self.title,
            "generate_fields": list(self.generate_fields),
            "limits": self.limits,
        }


@dataclass(frozen=True)
class UpdatePlan:
    documents: tuple[DocumentPlan, ...]
    departed: tuple[str, ...]

    @property
    def generation_targets(self) -> tuple[DocumentPlan, ...]:
        return tuple(d for d in self.documents if d.action == ACTION_GENERATE)

    def to_dict(self) -> dict:
        return {
            "documents": [d.to_dict() for d in self.documents],
            "departed": list(self.departed),
        }


@dataclass(frozen=True)
class FieldFailure:
    """失敗の 1 件。`field` は特定できたフィールド名（できなければ `None`）。"""

    field: str | None
    reason: str

    def to_dict(self) -> dict:
        return {"field": self.field, "reason": self.reason}


@dataclass(frozen=True)
class StoreOutcome:
    """文書ごとの保存結果。失敗のとき `kind`（失敗の区別）と `failures` を持つ。"""

    doc_link_id: str
    path: str | None
    status: str
    kind: str | None = None
    failures: tuple[FieldFailure, ...] = ()

    def to_dict(self) -> dict:
        return {
            "doc_link_id": self.doc_link_id,
            "path": self.path,
            "status": self.status,
            "kind": self.kind,
            "failures": [f.to_dict() for f in self.failures],
        }


# --- 更新計画 ----------------------------------------------------------------


def _h1_title(text: str) -> str | None:
    for heading in read_document(text).headings:
        if heading.level != 1:
            continue
        title = heading.text.rstrip()
        if heading.section_id is not None:
            words = title.split()
            title = title[: len(title) - len(words[-1])]
        title = title.strip()
        return title or None
    return None


def build_update_plan(project_root: str | Path, change_set: ChangeSet) -> UpdatePlan:
    """変更集合から更新計画を作る。文書と[文書情報]を読むだけで、何も書き込まない。"""
    root = Path(project_root)
    kinds = {change.doc_link_id: change.kinds for change in change_set.documents}
    documents: list[DocumentPlan] = []
    problems: list[Problem] = []
    state_problems: list[Problem] = []
    for item in change_set.confirmed_documents:
        change = next(
            c for c in change_set.documents if c.doc_link_id == item.doc_link_id
        )
        try:
            text = (root / item.path).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(Problem(item.path, f"読めない: {exc}"))
            continue
        title = _h1_title(text)
        try:
            info = state_store.load_document_info(root, item.doc_link_id)
        except state_store.StateStoreError as exc:
            if exc.kind != state_store.KIND_MISSING:
                state_problems.append(
                    Problem(
                        str(exc.path) if exc.path else item.doc_link_id,
                        f"[文書情報]を読めない: {exc}",
                        exc.kind,
                    )
                )
                continue
            info = None
        if info is None:
            action, reason = ACTION_GENERATE, REASON_NEW_DOCUMENT
        elif info["content_hash"] != change.new_hash:
            action, reason = ACTION_GENERATE, REASON_CONTENT_CHANGED
        elif info["path"] != item.path:
            action, reason = ACTION_UPDATE_PATH, None
        else:
            action, reason = ACTION_REUSE, None
        generate_fields: tuple[str, ...] = ()
        if action == ACTION_GENERATE:
            generate_fields = tuple(
                name for name in GENERATED_TO_INFO if name != "title" or title is None
            )
        documents.append(
            DocumentPlan(
                doc_link_id=item.doc_link_id,
                path=item.path,
                content_hash=change.new_hash,
                kinds=kinds[item.doc_link_id],
                action=action,
                reason=reason,
                title=title,
                generate_fields=generate_fields,
            )
        )
    if problems or state_problems:
        kind = FAILURE_DOCUMENT_UNREADABLE if problems else FAILURE_STATE_UNREADABLE
        raise ChangeFailure(kind, [*problems, *state_problems])
    departed = tuple(
        change.doc_link_id for change in change_set.documents if change.new_path is None
    )
    return UpdatePlan(documents=tuple(documents), departed=departed)


# --- 保存 --------------------------------------------------------------------


def _failed(plan_doc: DocumentPlan, kind: str, failures) -> StoreOutcome:
    return StoreOutcome(
        plan_doc.doc_link_id, plan_doc.path, STATUS_FAILED, kind, tuple(failures)
    )


def _save(project_root: Path, skill: str, plan_doc: DocumentPlan, info: dict):
    try:
        written = state_store.save_document_info(project_root, skill, info)
    except state_store.StateStoreError as exc:
        return _failed(plan_doc, exc.kind, [FieldFailure(None, str(exc))])
    status = STATUS_SAVED if written else STATUS_UNCHANGED
    return StoreOutcome(plan_doc.doc_link_id, plan_doc.path, status)


def apply_path_updates(
    project_root: str | Path, skill: str, plan: UpdatePlan
) -> list[StoreOutcome]:
    """パスだけの変更の文書について、現在パスだけを更新して[文書情報]を保存する。

    要約などの AI 生成情報は既存のまま。文書ごとに保存し、失敗しても残りを続ける。
    """
    root = Path(project_root)
    outcomes: list[StoreOutcome] = []
    for plan_doc in plan.documents:
        if plan_doc.action != ACTION_UPDATE_PATH:
            continue
        try:
            info = state_store.load_document_info(root, plan_doc.doc_link_id)
        except state_store.StateStoreError as exc:
            outcomes.append(_failed(plan_doc, exc.kind, [FieldFailure(None, str(exc))]))
            continue
        info["path"] = plan_doc.path
        outcomes.append(_save(root, skill, plan_doc, info))
    return outcomes


def _field_of(reason: str) -> str | None:
    name = reason.split(" ", 1)[0]
    return name if name in GENERATED_TO_INFO else None


def store_generated(
    project_root: str | Path,
    skill: str,
    plan: UpdatePlan,
    generated: Mapping[str, object],
) -> list[StoreOutcome]:
    """生成対象の文書の結果を検証し、通ったものを[文書情報]として文書ごとに保存する。

    `generated` は[文書 ID]から生成結果（検証器のキー名の対応）への対応。結果は計画の生成対象の順に返し、
    計画にない[文書 ID]・生成対象でない文書の結果は、末尾に失敗として並べる。
    """
    root = Path(project_root)
    outcomes: list[StoreOutcome] = []
    targets = {d.doc_link_id: d for d in plan.generation_targets}
    for plan_doc in plan.generation_targets:
        if plan_doc.doc_link_id not in generated:
            outcomes.append(
                _failed(
                    plan_doc,
                    KIND_NOT_GENERATED,
                    [FieldFailure(None, "generated result was not provided")],
                )
            )
            continue
        result = generated[plan_doc.doc_link_id]
        if plan_doc.title is not None and isinstance(result, dict):
            result = {**result, "title": plan_doc.title}
        reasons = validate_generated_fields(result)
        if reasons:
            outcomes.append(
                _failed(
                    plan_doc,
                    KIND_REJECTED,
                    [FieldFailure(_field_of(reason), reason) for reason in reasons],
                )
            )
            continue
        info = {
            "doc_link_id": plan_doc.doc_link_id,
            "path": plan_doc.path,
            "content_hash": plan_doc.content_hash,
            **{
                info_name: result[name] for name, info_name in GENERATED_TO_INFO.items()
            },
        }
        outcomes.append(_save(root, skill, plan_doc, info))
    for doc_id in generated:
        if doc_id not in targets:
            outcomes.append(
                StoreOutcome(
                    doc_id,
                    None,
                    STATUS_FAILED,
                    KIND_NOT_PLANNED,
                    (FieldFailure(None, "not a generation target in the plan"),),
                )
            )
    return outcomes
