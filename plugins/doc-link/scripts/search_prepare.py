"""検索（query-docs）の script の部品。検索前検査の結果の扱い、[ToC]の写しの固定、`query-worker` との受け渡し。

DES-006 §1・§2、DES-010 §1・§3.3・§4（`query-worker` の列）、DES-003 §2、DES-002 §4、REQ-004 FR-006・AC-019、
REQ-001 D-024・D-026・D-027、Agent とのデータ受け渡し規約を実装する。入口は `query-docs` の `query_docs.py` で、
この module は入口 script ではないので PEP 723 とロックを持たない。[ToC]・管理状態（`.doc-link/`）・
[Index 対象文書]へは書き込まない。書き込むのは `.temp/doc-link/query-docs/` の作業ファイルだけである。

使う部品: 検索前検査は `toc_check.check_toc`（`check-toc` と同じ関数。判定を別に実装しない）、[確定 ToC]・[文書情報]の
読取りは `state_store`。

## 検索前検査の結果の扱い（`prepare`）

`prepare(...)` は、検索前検査の結果と利用者の二択の選択結果（`choice`）から、次を返す（次の行動は `action`）。

| 検査の結果 | `choice` なし                     | `choice=rebuild`（`index-docs` の後）  | `choice=existing`                    |
| ---------- | --------------------------------- | -------------------------------------- | ------------------------------------ |
| 未構築     | `initial_build_required`          | `initial_build_required`               | `initial_build_required`             |
| 判定不能   | 障害（`SearchError`）             | 障害（`SearchError`）                  | 障害（`SearchError`）                |
| 再構築必要 | `confirm_rebuild`（規模と二択）   | 障害（再構築後も一致しない。旧版で黙って検索しない） | 旧版を固定する（鮮度は `possibly_stale`） |
| 再構築不要 | 最新を固定する（鮮度は `current`） | 最新を固定する                         | 最新を固定する                       |

固定したときは `invoke_query_worker` を返し、検索 ID・[ToC 識別キー]・使用した[ToC]の版・鮮度を添える。

`confirm_rebuild` は、検索前検査の要約（`toc_check.TocCheck.to_summary`。件数と再構築の規模まで）と二択を返す。
変更のある文書・セクションの明細は、`.temp/doc-link/query-docs/detail-<符号化した[ToC 識別キー]>.json` へ書き、
その絶対パスを `detail_path` に返す（要件 D-061。文書を大量に変更しても、標準出力の大きさが変わらないようにする
ため）。同じ[ToC 識別キー]の次の検索前検査が置き換える。書けないときは、障害（`SearchError`）にする。

`confirm_rebuild` は、検査に使った[ToC 識別キー]と[Index 対象指定]（`target_spec.TargetSpec.to_dict` の形）も、
`.temp/doc-link/query-docs/target-<符号化した[ToC 識別キー]>.json` の対象指定ファイルへ書き、その絶対パスを
`target_file` に返す（要件 D-063）。再構築（`index-docs`）と、再構築の後の `prepare` は、このファイルを
`--target-file` で受け取る。AI が保存済みの指定を引数へ書き写さないので、検査した対象と再構築する対象が同じになる。
再構築が別の対象で行われたときは、`--choice rebuild` の `prepare` が、このファイルの指定と[確定 ToC]の指定の
違いを再構築必要として検出し、障害にする。対象指定ファイルは、同じ[ToC 識別キー]の次の確認が置き換える。

## `query-worker` との受け渡し

置き場は `.temp/doc-link/query-docs/` で、識別値は検索 ID（`SEARCH-<8 桁の 16 進>`。script が生成する）である。
検索 ID ごとに次のファイルを置く（すべて書き終えてから公開する。依頼は最後に公開する）。

- `<ID>.toc.json`: [ToC]の写し。`documents` の配列で、要素は `doc_link_id`・`title`・`purpose`・`summary`（内容概要）・
  `tasks`（適用作業）・`keywords`・`sections`（`section_id`・`heading` の配列）。パス・[内容ハッシュ]・参照関係・検査結果は入れない。
  読む量を減らすため、字下げを持たない（要素ごとの改行は残す）。ほかのファイルは管理状態と同じ字下げを持つ
- `<ID>.fixed.json`: script が固定して持つもの。`toc_key`・`toc_version`・`freshness`・文書ごとの記録されたパスとセクション
- `<ID>.request.json`: 依頼。`search_id`・`task`・`toc_key`・`toc_copy_path`（写しの絶対パス）
- `<ID>.item-<連番>.json`: Agent が渡した結果の 1 件（文書）
- `<ID>.result.json`: 終了の値（`exit_value`）。上書きしない。無い、または `"0"` 以外のとき、検索を失敗とする

## 仕様の解釈（設計書が値や形式を定めていない点）

- 記録されたパス: [確定 ToC]の文書エントリはパスを持たない。[DES-003 §2]が[文書 ID]ごとに現在パスを持つと定める
  [文書情報]の `path` を、記録されたパスとして固定する時点で読む（D-024 の最新の[文書情報]）
- 写しの `summary`・`tasks` の名前は[文書情報]のフィールド名に揃える
- 結果の検査: 返った[文書 ID]が固定した[ToC]の文書に無いとき、[セクション ID]がその文書のセクションに無いとき、同じ[文書 ID]を
  2 回返したときは、その ID だけを結果から外し、`rejected`（種別・文書 ID・セクション ID・説明）と `rejected_notice` に残す。
  ほかの正しい結果は返す。[セクション ID]が別の文書にあっても、その文書のセクションでなければ外す。外した ID を読み替えて補わない。
  検査に通った文書が 0 件で、外した ID がある（全件が誤り）ときだけ、関連する文書が無い正常な 0 件と見分けられないので、
  検索を失敗とする（`SearchFailed`）。終了の値の欠落・定義外も失敗である
- 結果が 0 件（終了の値が `"0"`）は、関連する文書が無いという正常な結果である
- 後始末（`cleanup`）は、`collect` が結果を返した後（失敗を返した後を含む）に走る。ほかの検索の作業ファイルは削除しない
- 値の内容を理由に受け渡しを拒まない。関連理由・文書 ID・終了の値は、変形せずに保持し、検査は `collect` で行う
"""

import json
import os
import re
import secrets
import tempfile
from pathlib import Path

import detail_file
import state_store
import toc_check

SKILL = "query-docs"

CHOICE_REBUILD = "rebuild"
CHOICE_EXISTING = "existing"
CHOICES = (CHOICE_REBUILD, CHOICE_EXISTING)

FRESHNESS_CURRENT = "current"
FRESHNESS_POSSIBLY_STALE = "possibly_stale"

ACTION_INITIAL_BUILD = "initial_build_required"
ACTION_CONFIRM_REBUILD = "confirm_rebuild"
ACTION_INVOKE_WORKER = "invoke_query_worker"

EXIT_VALUE_OK = "0"

TARGET_FILE_FIELD = "target_file"
TARGET_FILE_PREFIX = "target-"

_SEARCH_ID = re.compile(r"SEARCH-[0-9a-f]{8}")
_ITEM_NAME = re.compile(r"item-([0-9]{6})")

REJECTED_UNKNOWN_DOCUMENT = "unknown_document_id"
REJECTED_DUPLICATE_DOCUMENT = "duplicate_document_id"
REJECTED_UNKNOWN_SECTION = "unknown_section_id"

NOTICE_REJECTED = (
    "検索 AI が返した ID の一部が、固定した[ToC]の版の検査に通らず、結果に含めていない（`rejected`）。"
    "含めていない ID は補っていない。関連する文書が結果から漏れている可能性がある"
)

GUIDANCE_INITIAL_BUILD = "[ToC]が未構築のため検索しない"
NOTICE_POSSIBLY_STALE = (
    "この検索に使った[ToC]は、現在の[Index 対象リスト]を反映していない可能性がある"
    "（利用者が「既存版のまま検索」を選んだ。[ToC]は更新していない）。"
    "[文書情報]は最新のものを使っている"
)
NOTICE_PATH = (
    "path は[確定 ToC]の版に記録されたパスであり、現在の実体パスとは限らない"
    "（文書が移動・削除されている可能性がある）"
)


class SearchError(Exception):
    """入力・識別値・状態を受理できない、または検索前検査を完了できない（終了コード 1）。`errors` は自然文の配列。"""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class SearchFailed(Exception):
    """検索が失敗した（結果が届かない・終了の値が無い、定義外・固定した[ToC]に無い ID。終了コード 3）。"""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# --- 作業ファイル ---------------------------------------------------------------


def _work_dir(root: Path) -> Path:
    return Path(root).joinpath(*state_store.TEMP_ROOT, SKILL)


def _file(root: Path, search_id: str, name: str) -> Path:
    return _work_dir(root) / f"{search_id}.{name}{state_store.FILE_SUFFIX}"


def _check_search_id(search_id: str) -> None:
    if _SEARCH_ID.fullmatch(search_id) is None:
        raise SearchError([f"検索 ID の形式が正しくない: {search_id}"])


def _serialize_copy(value) -> bytes:
    """写しのバイト列を返す。字下げとキーの後の空白を省く。

    写しは worker が読むだけの作業ファイルであり、読む量を減らすために字下げを持たない。
    1 行にはせず、要素ごとに改行する（worker は Read で読むため、1 行を長くしない）。
    管理状態と共用する `state_store.serialize` は、差分を読みやすくするため字下げを持つ
    ので、書き換えない。
    """
    try:
        text = json.dumps(
            value, ensure_ascii=False, sort_keys=True, indent=0, separators=(",", ":")
        )
        return (text + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:  # UnicodeEncodeError は ValueError の下位
        raise state_store.StateStoreError(
            state_store.KIND_INVALID, f"JSON にできない内容: {exc}"
        ) from exc


def _write(root: Path, path: Path, value, *, compact: bool = False) -> None:
    try:
        data = _serialize_copy(value) if compact else state_store.serialize(value)
        state_store.write_if_changed(root, SKILL, path, data)
    except state_store.StateStoreError as exc:
        raise SearchError([f"作業ファイルを書けない: {path}: {exc}"]) from exc


def _write_target_file(root: Path, toc_key: str, spec: dict) -> str:
    """検査に使った[ToC 識別キー]と[Index 対象指定]を対象指定ファイルへ書き、その絶対パスを返す（要件 D-063）。

    [ToC 識別キー]ごとに 1 つで、同じ[ToC 識別キー]の次の確認が置き換える。検索 ID の作業ファイルではないので、
    `cleanup` は削除しない（再構築と、その後の検索前検査が読むため）。
    """
    path = _work_dir(root) / (
        f"{TARGET_FILE_PREFIX}{state_store.encode_name(toc_key)}{state_store.FILE_SUFFIX}"
    )
    _write(root, path, spec)
    return os.path.abspath(path)


def _publish_new(root: Path, path: Path, value) -> bool:
    """上書きしないで公開する。同名のファイルが既にあるとき、何も変えず `False` を返す。"""
    directory = _work_dir(root)
    temp_path: Path | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            dir=directory, prefix="state_", suffix=".tmp"
        )
        temp_path = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(state_store.serialize(value))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp_path, path)
        except FileExistsError:
            return False
        return True
    except OSError as exc:
        raise SearchError([f"作業ファイルを書けない: {path}: {exc}"]) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _read(path: Path, missing: str):
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise SearchError([missing]) from exc
    except OSError as exc:
        raise SearchError([f"作業ファイルを読めない: {path}: {exc}"]) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SearchError([f"作業ファイルが壊れている: {path}: {exc}"]) from exc


def _read_optional(path: Path):
    try:
        return _read(path, "")
    except SearchError:
        if path.exists():
            raise
        return None


def _load_fixed(root: Path, search_id: str) -> dict:
    _check_search_id(search_id)
    return _read(
        _file(root, search_id, "fixed"),
        f"識別値に対応する検索が無い（公開されていないか、後始末済み）: {search_id}",
    )


def _published_files(root: Path, search_id: str) -> list[Path]:
    directory = _work_dir(root)
    if not directory.is_dir():
        return []
    return sorted(
        path for path in directory.iterdir() if path.name.startswith(f"{search_id}.")
    )


# --- 検索前検査の結果の扱いと固定 -------------------------------------------------


def _fix(root: Path, toc_key: str, task: str, freshness: str, status: str) -> dict:
    """検索に使う版の[確定 ToC]と最新の[文書情報]から写しを組み立て、版・鮮度とともに固定して依頼を公開する。"""
    try:
        toc = state_store.load_confirmed_toc(root, toc_key)
        infos = {
            entry["doc_link_id"]: state_store.load_document_info(
                root, entry["doc_link_id"]
            )
            for entry in toc["documents"]
        }
    except state_store.StateStoreError as exc:
        raise SearchError([f"[ToC]・[文書情報]を読めない: {exc}"]) from exc

    sections: dict[str, list[dict]] = {doc_id: [] for doc_id in infos}
    for entry in sorted(toc["sections"], key=lambda item: item["position"]):
        if entry["doc_link_id"] in sections:
            sections[entry["doc_link_id"]].append(
                {"section_id": entry["section_id"], "heading": entry["heading"]}
            )

    copy = {
        "documents": [
            {
                "doc_link_id": doc_id,
                "title": infos[doc_id]["title"],
                "purpose": infos[doc_id]["purpose"],
                "summary": infos[doc_id]["summary"],
                "tasks": infos[doc_id]["tasks"],
                "keywords": infos[doc_id]["keywords"],
                "sections": sections[doc_id],
            }
            for doc_id in sorted(infos)
        ]
    }
    fixed_documents = {
        doc_id: {"path": infos[doc_id]["path"], "sections": sections[doc_id]}
        for doc_id in sorted(infos)
    }

    search_id = "SEARCH-" + secrets.token_hex(4)
    while _file(root, search_id, "fixed").exists():
        search_id = "SEARCH-" + secrets.token_hex(4)

    copy_path = _file(root, search_id, "toc")
    _write(root, copy_path, copy, compact=True)
    _write(
        root,
        _file(root, search_id, "fixed"),
        {
            "search_id": search_id,
            "toc_key": toc_key,
            "toc_version": toc["version"],
            "freshness": freshness,
            "documents": fixed_documents,
        },
    )
    _write(
        root,
        _file(root, search_id, "request"),
        {
            "search_id": search_id,
            "task": task,
            "toc_key": toc_key,
            "toc_copy_path": str(copy_path.resolve()),
        },
    )
    return {
        "action": ACTION_INVOKE_WORKER,
        "search_id": search_id,
        "toc_key": toc_key,
        "toc_version": toc["version"],
        "freshness": freshness,
        "freshness_notice": (
            NOTICE_POSSIBLY_STALE if freshness == FRESHNESS_POSSIBLY_STALE else None
        ),
        "precheck_status": status,
    }


def prepare(
    root: Path,
    toc_key: str,
    spec,
    task: str,
    choice: str | None = None,
) -> dict:
    """検索前検査を行い、結果と二択の選択結果から次の行動を返す。[ToC]・管理状態・[Index 対象文書]は書き換えない。"""
    if choice is not None and choice not in CHOICES:
        raise SearchError([f"二択の選択結果が正しくない: {choice!r}"])
    if task == "":
        raise SearchError(["検索のタスクが空である"])

    result = toc_check.check_toc(root, toc_key, spec)
    if result.status == toc_check.STATUS_UNDETERMINABLE:
        raise SearchError(
            [
                "[ToC]の再構築要否を判定できないため、障害として検索を停止した"
                "（判定できた版が無いので、既存の[ToC]のまま検索することもしない）"
            ]
            + [cause.describe() for cause in result.causes]
        )
    if result.status == toc_check.STATUS_NOT_BUILT:
        return {
            "action": ACTION_INITIAL_BUILD,
            "status": result.status,
            "toc_key": result.toc_key,
            "guidance": [GUIDANCE_INITIAL_BUILD],
        }
    if result.status == toc_check.STATUS_UP_TO_DATE:
        return _fix(root, result.toc_key, task, FRESHNESS_CURRENT, result.status)

    # 再構築必要
    if choice == CHOICE_EXISTING:
        return _fix(root, result.toc_key, task, FRESHNESS_POSSIBLY_STALE, result.status)
    if choice == CHOICE_REBUILD:
        raise SearchError(
            [
                "再構築を選んだが、再構築後も[ToC]が現物と一致していない。"
                "旧版で黙って検索しない。`index-docs` の結果を確かめる"
            ]
        )
    try:
        detail_path = detail_file.write_detail(
            root, SKILL, result.toc_key, result.to_detail()
        )
    except state_store.StateStoreError as exc:
        raise SearchError([f"検索前検査の明細ファイルを書けない: {exc}"]) from exc
    target_file = _write_target_file(root, result.toc_key, result.target_spec)
    return {
        "action": ACTION_CONFIRM_REBUILD,
        **result.to_summary(),
        detail_file.DETAIL_PATH_FIELD: detail_path,
        TARGET_FILE_FIELD: target_file,
        "options": [
            {
                "choice": CHOICE_REBUILD,
                "label": "再構築してから検索する",
                "next": (
                    "`index-docs` を `--target-file <target_file の値>` だけで実行した後、"
                    "`--task` と `--choice rebuild --target-file <target_file の値>` で `prepare` をやり直す"
                ),
            },
            {
                "choice": CHOICE_EXISTING,
                "label": "既存の[ToC]のまま検索する",
                "next": "`--choice existing` を付けて `prepare` をやり直す。[ToC]は更新しない",
            },
        ],
    }


# --- query-worker との受け渡し -----------------------------------------------------


def request_path(root: Path, search_id: str) -> str:
    """依頼の絶対パスを返す。読み出してよい状態（公開済み）でなければ失敗する。"""
    _load_fixed(root, search_id)
    path = _file(root, search_id, "request")
    if not path.is_file():
        raise SearchError([f"依頼が公開されていない: {search_id}"])
    return str(path.resolve())


def _check_open(root: Path, search_id: str) -> None:
    _load_fixed(root, search_id)
    if not _file(root, search_id, "request").is_file():
        raise SearchError([f"依頼が公開されていない: {search_id}"])
    if _file(root, search_id, "result").exists():
        raise SearchError(
            [f"終了の値を既に書いたので、結果を足せない（上書きしない）: {search_id}"]
        )


def submit_item(
    root: Path,
    search_id: str,
    doc_link_id: str,
    reason: str,
    section_ids: list[str],
) -> dict:
    """[検索 AI]が返した関連する文書 1 件を、値のまま保持する。検査は `collect` が行う。"""
    _check_open(root, search_id)
    item = {
        "doc_link_id": doc_link_id,
        "reason": reason,
        "section_ids": list(section_ids),
    }
    number = 1
    while not _publish_new(root, _file(root, search_id, f"item-{number:06d}"), item):
        number += 1
    return {"stored": {"search_id": search_id, "doc_link_id": doc_link_id}}


def submit_end(root: Path, search_id: str, exit_value: str) -> dict:
    """終了の値を書く。1 回だけで、上書きしない。値の内容は `collect` が判定する。"""
    _check_open(root, search_id)
    if not _publish_new(
        root,
        _file(root, search_id, "result"),
        {"search_id": search_id, "exit_value": exit_value},
    ):
        raise SearchError([f"終了の値を既に書いた（上書きしない）: {search_id}"])
    return {"stored": {"search_id": search_id}}


def _read_items(root: Path, search_id: str) -> list[dict]:
    numbered = []
    for path in _published_files(root, search_id):
        name = path.name[len(search_id) + 1 : -len(state_store.FILE_SUFFIX)]
        match = _ITEM_NAME.fullmatch(name)
        if match is not None:
            numbered.append((int(match.group(1)), path))
    return [_read(path, "") for _, path in sorted(numbered)]


def collect(root: Path, search_id: str) -> dict:
    """結果を検査して整形する。検査に通らない ID は結果から外して `rejected` に残す。

    終了の値の欠落・定義外、または検査に通った文書が 0 件で外した ID がある（全件が誤り）ときは `SearchFailed`。
    """
    fixed = _load_fixed(root, search_id)
    result = _read_optional(_file(root, search_id, "result"))
    if result is None:
        raise SearchFailed(["終了の値が無い（結果が届いていない）。検索を失敗とした"])
    if result["exit_value"] != EXIT_VALUE_OK:
        raise SearchFailed(
            [f"終了の値が定義外である: {result['exit_value']!r}。検索を失敗とした"]
        )

    rejected: list[dict] = []

    def reject(kind: str, doc_id: str, section_id: str | None, message: str) -> None:
        rejected.append(
            {
                "kind": kind,
                "doc_link_id": doc_id,
                "section_id": section_id,
                "message": message,
            }
        )

    seen: set[str] = set()
    documents = []
    for item in _read_items(root, search_id):
        doc_id = item["doc_link_id"]
        known = fixed["documents"].get(doc_id)
        if known is None:
            reject(
                REJECTED_UNKNOWN_DOCUMENT,
                doc_id,
                None,
                f"固定した[ToC]の版に無い[文書 ID]が返った: {doc_id}",
            )
            continue
        if doc_id in seen:
            reject(
                REJECTED_DUPLICATE_DOCUMENT,
                doc_id,
                None,
                f"同じ[文書 ID]が複数回返った: {doc_id}",
            )
            continue
        seen.add(doc_id)
        headings = {
            entry["section_id"]: entry["heading"] for entry in known["sections"]
        }
        sections = []
        for section_id in item["section_ids"]:
            if section_id not in headings:
                reject(
                    REJECTED_UNKNOWN_SECTION,
                    doc_id,
                    section_id,
                    f"文書 {doc_id} の固定した[ToC]の版に無い[セクション ID]が返った: {section_id}",
                )
                continue
            sections.append({"section_id": section_id, "heading": headings[section_id]})
        documents.append(
            {
                "doc_link_id": doc_id,
                "recorded_path": known["path"],
                "reason": item["reason"],
                "sections": sections,
            }
        )
    if rejected and not documents:
        # 全件が誤りの検索を、関連する文書が無いという正常な 0 件と見分けられなくなるため、失敗とする
        raise SearchFailed(
            [entry["message"] for entry in rejected]
            + [
                "検査に通った文書が無い。存在しない ID を補わないので、この検索の結果を採用しない"
            ]
        )

    stale = fixed["freshness"] == FRESHNESS_POSSIBLY_STALE
    return {
        "search_id": search_id,
        "toc_key": fixed["toc_key"],
        "toc_version": fixed["toc_version"],
        "freshness": fixed["freshness"],
        "freshness_notice": NOTICE_POSSIBLY_STALE if stale else None,
        "path_notice": NOTICE_PATH,
        "documents": documents,
        "rejected": rejected,
        "rejected_notice": NOTICE_REJECTED if rejected else None,
    }


def cleanup(root: Path, search_id: str) -> int:
    """検索 ID の依頼・結果・写し・固定した状態をすべて削除する。削除した数を返す（無ければ 0）。"""
    _check_search_id(search_id)
    removed = 0
    for path in _published_files(root, search_id):
        path.unlink(missing_ok=True)
        removed += 1
    return removed
