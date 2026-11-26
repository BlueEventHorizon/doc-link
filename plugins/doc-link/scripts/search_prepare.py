"""検索（query-docs）の script の部品。検索前検査の結果の扱い、検索の担当の固定、`query-worker` との受け渡し。

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

固定したときは `invoke_query_worker` を返し、検索 ID・[ToC 識別キー]・使用した[ToC]の版・鮮度・担当の識別値の並び
（`workers`）を添える。

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

## 検索基盤（DES-011、REQ-006）

`prepare` は、基盤判定（`backend_select.Decision`）を受け取る。渡さないときは `toc`（現在の動作）である。

- `doc-db`: 検索前検査（機械取得の情報の鮮度。`toc_check`）が再構築必要のとき、二択を示さず、`rebuild_required`
  （`reason` は `toc_stale`）を返す。SKILL は規模を利用者へ知らせ、呼び出し元に `index-docs`（機械取得の構築と[doc-db]の
  同期）の実行を求め、`--choice rebuild --target-file …` で `prepare` をやり直す。`--choice existing` は受け付けない。
  未構築は `initial_build_required`（対象指定が要る）、判定不能は障害である。再構築不要のとき、[doc-db]を同期して検索し、
  `docdb_result` を返す（`documents` は[ToC]の検索結果と同じ形。`relevance` は `maybe` の固定）。同期・検索が接続できない (a)・
  OpenAI の失敗 (b) になったときは、[ToC]へ切り替えて、`toc` の規則で続ける（`backend_switch` に通知）。ほかの失敗は障害である
- `toc`: [AI 生成フィールド]が未生成の文書（`toc_check` の `ai_unfilled`）があるとき、または、機械取得の情報は最新（再構築
  不要）なのに[AI 生成フィールド]が古い文書（`ai_needed`）があるときは、二択を示さず、`rebuild_required`（`reason` は
  `ai_fields_needed`）を返す（既存の[ToC]のままでは、検索できない・古い[AI 生成フィールド]を最新として検索するため）。それ以外は、
  現在のとおり（機械取得の情報が古いときは、[AI 生成フィールド]が古い文書があっても、二択を示す）

結果（`prepare`・`collect`）は、`backend`・`forced`・`startup`・`backend_switch`（切り替えが無ければ `null`）を持つ。

## `query-worker` との受け渡し

置き場は `.temp/doc-link/query-docs/` で、識別値は検索 ID（`SEARCH-<8 桁の 16 進>`。script が生成する）と、担当の識別値
（検索 ID に枝番を付けた `SEARCH-<8 桁の 16 進>-<k>`。k は 1 から。担当の数だけある）である。

固定した[ToC]の文書は、`_plan_workers` が担当に分ける。担当の数は、同時に起動する数の上限（`MAX_CONCURRENT_WORKERS`。
`index-docs` の生成と同じ 10）を超えず、文書の数を担当の数で割った件数ずつを割り当てる（余りは先頭の担当から 1 件ずつ）。
文書が少ないときは、1 本あたりの件数が `MIN_DOCUMENTS_PER_WORKER` 未満にならないよう、担当の数を減らす。文書が無いと
きは、担当も無い。担当と割り当ては、script が固定した状態に持つ。AI は文書の件数も担当の数も数えない。

検索 ID ごとに次のファイルを置く。

- `<ID>.fixed.json`: script が固定して持つもの。最後に公開する（作業ファイルを探す印でもある）。`task`・`toc_key`・
  `toc_version`・`freshness`、文書ごとの記録されたパス・タイトル・見せる内容（`purpose`・`summary`・`tasks`・`keywords`）・
  セクション（`section_id`・`heading`・名前 `name`）、担当ごとの文書の並び（`workers`。文書は[文書 ID]で持つ。並びは
  パスの昇順）。名前から[セクション ID]への対応は、ここだけが持つ
- `<ID>.w<k>.item-<NNNN>.json`: 担当 k の NNNN 件目の依頼。`next` が、その文書の答えが無いときに書いて公開する。
  `task`・`position`・`total`・`title`・`purpose`・`summary`・`tasks`・`keywords`・`sections`（見出しの名前の配列）を持つ。
  [文書 ID]・[セクション ID]・パス・[内容ハッシュ]・参照関係・検査結果は入れない。検索 AI は、ID・番号を見ず、書かない
  （書き写しの誤りを、構造で起こさない。Issue #17・#19）。`sections` の名前は、正規化（`_normalize`）して比べても
  一意になるよう、同じ見出しに `（同名 k/n）` を足す（`_unique_names`）
- `<ID>.w<k>.answer-<NNNN>.json`: 担当 k の NNNN 件目の文書への答え。検索 AI が標準入力で渡した答えを、script が検査して
  書く。`doc_link_id`・`relevance`・`reason`・`section_ids`（script が引き当てた[セクション ID]）を持つ。書いたら上書きしない。
  どの文書への答えかは、script が持つ位置（答えの数）で決まり、検索 AI は文書を指さない

答えの形は `{"relevance": "yes", "reason": "…", "headings": ["…"]}`（`"yes"`: 関連する、`"maybe"`: 判断がつかないが関連するかもしれない。
取りこぼさないために結果に含める）または `{"relevance": "no"}`（明らかに無関係）。`relevance` は、この 3 つの語のどれかだけである
（点数・順位は付けない）。`headings` は省略できる。`"no"` は `relevance` だけを持つ。

## 仕様の解釈（設計書が値や形式を定めていない点）

- 記録されたパス: [確定 ToC]の文書エントリはパスを持たない。[DES-003 §2]が[文書 ID]ごとに現在パスを持つと定める
  [文書情報]の `path` を、記録されたパスとして固定する時点で読む（D-024 の最新の[文書情報]）
- 見せる内容の `summary`・`tasks` の名前は[文書情報]のフィールド名に揃える
- 答えの検査: 形式（JSON として読めること、キーと型）と、見出しの引き当てを、答えを受け取る時点で行う。通らないときは、
  何も保存せず、直すべき箇所（見出しは、その文書の見出しの候補を添える）を返す（終了コード 1）。検索 AI は同じ文書に
  答え直せる。見出しは、その文書のセクションの中だけから、`_normalize`（全角半角・空白の正規化）した完全一致、または、
  その文書の中で一意に決まる前方一致で引く。近い見出しで読み替えて補わない。同じセクションを重ねて選んでも、選択は変わらない
- 結果（`collect`）: 担当の順、担当の中の順に、`"yes"` か `"maybe"` とされた文書を、`relevance` を付けて並べる。順は関連度の順
  ではない（強弱は `relevance` が持つ）。担当のどれかに答えの
  無い文書が残っているときは、関連する文書が無い正常な 0 件と見分けられないので、検索を失敗とする（`SearchFailed`）。
  すべてに答えがあり、関連する文書が 0 件のときは、正常な結果である
- 後始末（`cleanup`）は、`collect` が結果を返した後（失敗を返した後を含む）に走る。ほかの検索の作業ファイルは削除しない
- 値の内容（関連理由）を理由に答えを拒まない。値は変形せずに保持する
"""

import json
import os
import re
import secrets
import tempfile
import unicodedata
from pathlib import Path

import backend_select
import detail_file
import docdb_contract
import docdb_search
import docdb_sync
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
ACTION_REBUILD_REQUIRED = "rebuild_required"
ACTION_DOCDB_RESULT = "docdb_result"

REBUILD_REASON_TOC_STALE = "toc_stale"
REBUILD_REASON_AI_FIELDS = "ai_fields_needed"

TARGET_FILE_FIELD = "target_file"
TARGET_FILE_PREFIX = "target-"

# 1 回の検索で同時に起動する query-worker の上限。index-docs の生成（max_concurrent_agents）と同じ値にする
MAX_CONCURRENT_WORKERS = 10
# 1 本の query-worker に割り当てる文書の最小件数。TBD: 暫定値であり、実測で決める（DES-006 §2）
MIN_DOCUMENTS_PER_WORKER = 10

_SEARCH_ID = re.compile(r"SEARCH-[0-9a-f]{8}")
_WORKER_ID = re.compile(r"(SEARCH-[0-9a-f]{8})-([1-9][0-9]*)")
RELEVANCE_YES = "yes"  # 関連する
RELEVANCE_MAYBE = "maybe"  # 判断がつかないが、関連するかもしれない（取りこぼさないために、結果に含める）
RELEVANCE_NO = "no"  # 明らかに無関係
RELEVANCES = (RELEVANCE_YES, RELEVANCE_MAYBE, RELEVANCE_NO)
_ANSWER_KEYS = frozenset({"relevance", "reason", "headings"})

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
NOTICE_ORDER = (
    "documents の並びは、担当の順と担当の中の順（パスの昇順）であり、関連度の順ではない。"
    "関連の強弱は relevance が持つ（yes: 関連する、maybe: 判断がつかないが、関連するかもしれない）"
)


class SearchError(Exception):
    """入力・識別値・状態を受理できない、または検索前検査を完了できない（終了コード 1）。`errors` は自然文の配列。"""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class SearchFailed(Exception):
    """検索が失敗した（担当のどれかに答えの無い文書が残っている。終了コード 3）。"""

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


def split_worker_id(worker_id: str) -> tuple[str, int]:
    """担当の識別値を、検索 ID と担当の番号（1 から）に分ける。形式が正しくないときは `SearchError`。"""
    matched = _WORKER_ID.fullmatch(worker_id)
    if matched is None:
        raise SearchError([f"担当の識別値の形式が正しくない: {worker_id}"])
    return matched.group(1), int(matched.group(2))


def find_project_root(
    search_id: str, start: Path, project_dir: str | None = None
) -> Path:
    """検索 ID の作業ファイルがあるプロジェクトのルートを返す。

    `query-worker` は、プロジェクトのルートを引数で渡さない。環境変数 `project_dir`（あれば）と、`start`（作業ディレクトリ）
    とその親から、固定した状態のファイルがあるディレクトリを探す。見つからないときは `SearchError`。
    """
    _check_search_id(search_id)
    candidates = [Path(project_dir)] if project_dir else []
    candidates += [Path(start), *Path(start).parents]
    for candidate in candidates:
        if _file(candidate, search_id, "fixed").is_file():
            return candidate
    raise SearchError(
        [
            f"検索 ID の作業ファイルが、作業ディレクトリとその親の .temp/doc-link/query-docs/ に無い: {search_id}"
            "（後始末済みか、プロジェクトの外で実行している）"
        ]
    )


def _write(root: Path, path: Path, value) -> None:
    try:
        state_store.write_if_changed(root, SKILL, path, state_store.serialize(value))
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


def _publish_new(root: Path, path: Path, data: bytes) -> bool:
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
            stream.write(data)
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


def _serialize_item(value: dict) -> bytes:
    """依頼のバイト列を返す。キーは書いた順（task を先頭）に並べる。worker が Read で読む。"""
    try:
        return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:  # UnicodeEncodeError は ValueError の下位
        raise SearchError([f"JSON にできない内容: {exc}"]) from exc


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


def _normalize(text: str) -> str:
    """名前の照合に使う正規化。全角半角（NFKC）と、空白の種類・連続を揃える。"""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _unique_names(names: list[str]) -> list[str]:
    """検索 AI が答えるときの名前を、正規化して比べても一意にする。

    同名が n 個あるときは、それぞれに `（同名 k/n）` を足す（k は並びの順）。足したあとも一意にならないとき
    （名前そのものが同じ書式のとき）は、曖昧に引き当てないよう、`SearchError` にする。
    """
    groups: dict[str, list[int]] = {}
    for index, name in enumerate(names):
        groups.setdefault(_normalize(name), []).append(index)
    unique = list(names)
    for indexes in groups.values():
        if len(indexes) > 1:
            for order, index in enumerate(indexes, 1):
                unique[index] = f"{names[index]}（同名 {order}/{len(indexes)}）"
    if len({_normalize(name) for name in unique}) != len(unique):
        raise SearchError(
            ["見出しの名前を一意にできない（同名の目印と同じ書式の名前がある）"]
        )
    return unique


def _plan_workers(doc_ids: list[str]) -> list[list[str]]:
    """文書を、query-worker の担当に分ける。並びは保つ。文書が無いときは、担当も無い。

    担当の数は、`MAX_CONCURRENT_WORKERS` を超えず、1 本あたりが `MIN_DOCUMENTS_PER_WORKER` 未満にならない数（1 以上）。
    文書の数を担当の数で割った件数ずつを割り当て、余りは先頭の担当から 1 件ずつ足す。
    """
    count = len(doc_ids)
    if count == 0:
        return []
    workers = max(1, min(MAX_CONCURRENT_WORKERS, count // MIN_DOCUMENTS_PER_WORKER))
    base, extra = divmod(count, workers)
    plans: list[list[str]] = []
    start = 0
    for index in range(workers):
        size = base + (1 if index < extra else 0)
        plans.append(doc_ids[start : start + size])
        start += size
    return plans


def _backend_info(decision) -> dict:
    """結果に添える[検索基盤]の情報。判定を渡さないとき（既存の呼び出し）は[ToC]。"""
    if decision is None:
        return {
            "backend": backend_select.BACKEND_TOC,
            "forced": False,
            "startup": None,
            "backend_switch": None,
        }
    return decision.to_dict()


def _fix(
    root: Path,
    toc_key: str,
    task: str,
    freshness: str,
    status: str,
    info: dict | None = None,
) -> dict:
    """検索に使う版の[確定 ToC]と最新の[文書情報]から、見せる内容と担当を組み立て、版・鮮度とともに固定する。"""
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

    # 検索 AI は ID を見ず、書かない。セクションは見出しの名前で答え、名前から ID への対応は、固定した状態に持つ
    sections: dict[str, list[dict]] = {doc_id: [] for doc_id in infos}
    for entry in sorted(toc["sections"], key=lambda item: item["position"]):
        doc_id = entry["doc_link_id"]
        if doc_id in sections:
            sections[doc_id].append(
                {"section_id": entry["section_id"], "heading": entry["heading"]}
            )
    doc_ids = sorted(infos, key=lambda doc_id: (infos[doc_id]["path"], doc_id))
    for doc_id in doc_ids:
        names = _unique_names([section["heading"] for section in sections[doc_id]])
        for section, name in zip(sections[doc_id], names):
            section["name"] = name

    fixed_documents = {
        doc_id: {
            "path": infos[doc_id]["path"],
            "title": infos[doc_id]["title"],
            "purpose": infos[doc_id]["purpose"],
            "summary": infos[doc_id]["summary"],
            "tasks": infos[doc_id]["tasks"],
            "keywords": infos[doc_id]["keywords"],
            "sections": sections[doc_id],
        }
        for doc_id in doc_ids
    }

    search_id = "SEARCH-" + secrets.token_hex(4)
    while _file(root, search_id, "fixed").exists():
        search_id = "SEARCH-" + secrets.token_hex(4)
    workers = {
        f"{search_id}-{number}": plan
        for number, plan in enumerate(_plan_workers(doc_ids), 1)
    }

    _write(
        root,
        _file(root, search_id, "fixed"),
        {
            "search_id": search_id,
            "task": task,
            "toc_key": toc_key,
            "toc_version": toc["version"],
            "freshness": freshness,
            "documents": fixed_documents,
            "workers": workers,
            "backend_info": info or _backend_info(None),
        },
    )
    return {
        **(info or _backend_info(None)),
        "action": ACTION_INVOKE_WORKER,
        "search_id": search_id,
        "workers": list(workers),
        "toc_key": toc_key,
        "toc_version": toc["version"],
        "freshness": freshness,
        "freshness_notice": (
            NOTICE_POSSIBLY_STALE if freshness == FRESHNESS_POSSIBLY_STALE else None
        ),
        "precheck_status": status,
    }


def _write_rebuild_files(root: Path, result: toc_check.TocCheck) -> tuple[str, str]:
    """再構築の明細ファイルと対象指定ファイルを書き、（明細のパス, 対象指定ファイルのパス）を返す。"""
    try:
        detail_path = detail_file.write_detail(
            root, SKILL, result.toc_key, result.to_detail()
        )
    except state_store.StateStoreError as exc:
        raise SearchError([f"検索前検査の明細ファイルを書けない: {exc}"]) from exc
    return detail_path, _write_target_file(root, result.toc_key, result.target_spec)


def _rebuild_required(
    root: Path, result: toc_check.TocCheck, reason: str, info: dict
) -> dict:
    """二択を示さず、再構築（`index-docs`）を求める行動を返す。"""
    detail_path, target_file = _write_rebuild_files(root, result)
    summary = result.to_summary()
    if info["backend"] == backend_select.BACKEND_DOCDB:
        # [doc-db]を使う再構築は、機械取得の構築と同期だけで、[AI 生成フィールド]を作らない（DES-011 §7.1）
        summary["scale"] = {**summary["scale"], "ai_generation": 0}
        summary["ai_fields_needed"] = None
        summary["ai_fields_unfilled"] = None
    return {
        **info,
        "action": ACTION_REBUILD_REQUIRED,
        "reason": reason,
        **summary,
        detail_file.DETAIL_PATH_FIELD: detail_path,
        TARGET_FILE_FIELD: target_file,
        "next": (
            "利用者へ再構築の規模を知らせ（二択は示さない）、`index-docs` を `--target-file <target_file の値>` "
            "だけで実行した後、`--task` と `--choice rebuild --target-file <target_file の値>` で `prepare` をやり直す"
        ),
    }


def _rebuild_mismatch() -> SearchError:
    return SearchError(
        [
            "再構築を選んだが、再構築後も[ToC]が現物と一致していない（または[AI 生成フィールド]が未生成の文書が残っている）。"
            "旧版で黙って検索しない。`index-docs` の結果を確かめる"
        ]
    )


def _prepare_toc(
    root: Path,
    result: toc_check.TocCheck,
    task: str,
    choice: str | None,
    info: dict,
) -> dict:
    """[ToC]を[検索基盤]とするときの、検索前検査の結果の扱い。"""
    unfilled = result.ai_unfilled or 0
    ai_needed = result.ai_needed or 0
    up_to_date = result.status == toc_check.STATUS_UP_TO_DATE
    if unfilled > 0 or (up_to_date and ai_needed > 0):
        # 二択を示さず、構築を求める。[AI 生成フィールド]が未生成の文書は、既存の[ToC]のままでは検索できず、取りこぼす。
        # 機械取得の情報は最新なのに[AI 生成フィールド]が古い文書（[doc-db]を使っていた間に変わった文書）は、
        # 既存の[ToC]のままだと、古い[AI 生成フィールド]を最新として検索してしまう
        if choice == CHOICE_EXISTING:
            raise SearchError(
                [
                    f"[AI 生成フィールド]が要る文書が {ai_needed} 件ある（うち未生成が {unfilled} 件）。"
                    "既存の[ToC]のままでは、正しく検索できないので、「既存のまま検索する」を選べない"
                ]
            )
        if choice == CHOICE_REBUILD:
            raise _rebuild_mismatch()
        return _rebuild_required(root, result, REBUILD_REASON_AI_FIELDS, info)
    if result.status == toc_check.STATUS_UP_TO_DATE:
        return _fix(root, result.toc_key, task, FRESHNESS_CURRENT, result.status, info)

    # 再構築必要（機械取得の情報が古い）
    if choice == CHOICE_EXISTING:
        return _fix(
            root, result.toc_key, task, FRESHNESS_POSSIBLY_STALE, result.status, info
        )
    if choice == CHOICE_REBUILD:
        raise _rebuild_mismatch()
    detail_path, target_file = _write_rebuild_files(root, result)
    return {
        **info,
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


def _docdb_documents(root: Path, toc_key: str):
    """同期の一覧と、対応づけに使う（[文書 ID]→パス、[文書 ID]→（[セクション ID]→見出し））を返す。"""
    try:
        listed = docdb_sync.build_document_list(root, toc_key)
        toc = state_store.load_confirmed_toc(root, toc_key)
    except state_store.StateStoreError as exc:
        raise SearchError([f"[ToC]・[文書情報]を読めない: {exc}"]) from exc
    paths = {doc_id: path for path, doc_id in listed.path_to_doc.items()}
    sections: dict[str, dict[str, str]] = {}
    for entry in toc["sections"]:
        sections.setdefault(entry["doc_link_id"], {})[entry["section_id"]] = entry[
            "heading"
        ]
    return listed, toc, paths, sections


def _switch_to_toc(
    decision, result: toc_check.TocCheck, outcome
) -> "backend_select.Decision":
    """[doc-db]の同期・検索が切り替えになったときの、[ToC]の判定を返す。影響（[AI 生成フィールド]が要る文書の件数）を添える。"""
    switch = backend_select.Switch(
        outcome.reason_code, outcome.cause, outcome.presumed
    ).with_impact(result.ai_needed)
    return decision.switched_to_toc(switch)


def _prepare_docdb(
    root: Path,
    result: toc_check.TocCheck,
    task: str,
    choice: str | None,
    decision,
) -> dict:
    """[doc-db]を[検索基盤]とするときの、検索前検査の結果の扱いと、同期・検索。"""
    info = decision.to_dict()
    if choice == CHOICE_EXISTING:
        raise SearchError(
            [
                "[doc-db]を使うときは、「既存の[ToC]のまま検索する」を提供しない（古ければ、二択を示さず、"
                "再構築してから検索する）"
            ]
        )
    if result.status == toc_check.STATUS_REBUILD_NEEDED:
        if choice == CHOICE_REBUILD:
            raise _rebuild_mismatch()
        return _rebuild_required(root, result, REBUILD_REASON_TOC_STALE, info)

    listed, toc, paths, sections = _docdb_documents(root, result.toc_key)
    outcome = docdb_sync.run_sync(decision.client, root, result.toc_key, listed=listed)
    if outcome.status == docdb_sync.STATUS_FAILED:
        raise SearchError(outcome.errors)
    if outcome.status == docdb_sync.STATUS_SWITCH:
        return _prepare_toc(
            root,
            result,
            task,
            choice,
            _switch_to_toc(decision, result, outcome).to_dict(),
        )
    try:
        found = docdb_search.search(
            decision.client,
            root,
            result.toc_key,
            task,
            listed.path_to_doc,
            paths,
            sections,
            met=outcome.contract_met,
        )
    except docdb_search.DocdbSearchError as exc:
        if not exc.switch:
            raise SearchError(exc.errors) from exc
        switched = _switch_to_toc(decision, result, _SwitchCause(exc))
        return _prepare_toc(root, result, task, choice, switched.to_dict())
    warnings = [] if outcome.contract_met else [docdb_contract.WARNING_CONTRACT_UNMET]
    return {
        **info,
        "action": ACTION_DOCDB_RESULT,
        "toc_key": result.toc_key,
        "toc_version": toc["version"],
        "freshness": FRESHNESS_CURRENT,
        "freshness_notice": None,
        "path_notice": docdb_search.NOTICE_PATH,
        "order_notice": docdb_search.NOTICE_ORDER,
        "limit_notice": docdb_search.NOTICE_LIMIT,
        "documents": found.documents,
        "unmapped": found.unmapped,
        "sync": outcome.to_dict(),
        "warnings": warnings,
        "precheck_status": result.status,
    }


class _SwitchCause:
    """`DocdbSearchError`（切り替え）を、同期の結果と同じ項目（`reason_code`・`cause`・`presumed`）で見せる。"""

    def __init__(self, error: "docdb_search.DocdbSearchError"):
        self.reason_code = error.reason_code
        self.cause = error.cause
        self.presumed = error.presumed


def prepare(
    root: Path,
    toc_key: str,
    spec,
    task: str,
    choice: str | None = None,
    decision=None,
) -> dict:
    """検索前検査を行い、結果と二択の選択結果から次の行動を返す。[ToC]・管理状態・[Index 対象文書]は書き換えない。

    `decision` は基盤判定（`backend_select.Decision`）。渡さないときは[ToC]として扱う。
    """
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
    info = _backend_info(decision)
    if result.status == toc_check.STATUS_NOT_BUILT:
        return {
            **info,
            "action": ACTION_INITIAL_BUILD,
            "status": result.status,
            "toc_key": result.toc_key,
            "guidance": [GUIDANCE_INITIAL_BUILD],
        }
    if decision is not None and decision.backend == backend_select.BACKEND_DOCDB:
        return _prepare_docdb(root, result, task, choice, decision)
    return _prepare_toc(root, result, task, choice, info)


# --- query-worker との受け渡し -----------------------------------------------------


def _load_worker(root: Path, worker_id: str) -> tuple[dict, list[str], int]:
    """担当の識別値から、固定した状態と、その担当の文書の並びと、担当の番号を返す。"""
    search_id, number = split_worker_id(worker_id)
    fixed = _load_fixed(root, search_id)
    plan = fixed["workers"].get(worker_id)
    if plan is None:
        raise SearchError([f"識別値に対応する担当が無い: {worker_id}"])
    return fixed, plan, number


def _answer_name(number: int, position: int) -> str:
    return f"w{number}.answer-{position:04d}"


def _answered(root: Path, search_id: str, number: int) -> int:
    """担当に保存された答えの数（= 次に答える文書の位置）を返す。"""
    prefix = f"{search_id}.w{number}.answer-"
    return sum(
        1 for path in _published_files(root, search_id) if path.name.startswith(prefix)
    )


def _next_payload(
    root: Path, fixed: dict, number: int, plan: list[str], answered: int
) -> dict:
    """次に答える文書の依頼を（無ければ書いて）公開し、そのパスを返す。答えが揃っていれば、`done` を返す。"""
    total = len(plan)
    if answered >= total:
        return {"done": True, "item_path": None, "answered": answered, "total": total}
    search_id = fixed["search_id"]
    path = _file(root, search_id, f"w{number}.item-{answered + 1:04d}")
    if not path.is_file():
        document = fixed["documents"][plan[answered]]
        item = {
            "task": fixed["task"],
            "position": answered + 1,
            "total": total,
            "title": document["title"],
            "purpose": document["purpose"],
            "summary": document["summary"],
            "tasks": document["tasks"],
            "keywords": document["keywords"],
            "sections": [section["name"] for section in document["sections"]],
        }
        _publish_new(root, path, _serialize_item(item))
    return {
        "done": False,
        "item_path": str(path.resolve()),
        "answered": answered,
        "total": total,
    }


def next_item(root: Path, worker_id: str) -> dict:
    """次に答える文書の依頼のパスを返す。何度呼んでも同じ文書を返す（答えを保存するまで進まない）。"""
    fixed, plan, number = _load_worker(root, worker_id)
    answered = _answered(root, fixed["search_id"], number)
    return _next_payload(root, fixed, number, plan, answered)


def _parse_answer(text: str) -> dict:
    """渡された答えの形式（JSON として読めること、キーと型）だけを検査し、保持する形にする。

    通らないときは、直すべき箇所をすべて `SearchError` に入れる。値の内容（見出しが存在するか、など）は検査しない。
    """
    if not text.strip():
        raise SearchError(["標準入力が空である。答えの JSON を標準入力で渡すこと"])
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SearchError(
            [f"答えが JSON として読めない（{exc.lineno} 行 {exc.colno} 列）: {exc.msg}"]
        ) from exc
    if not isinstance(data, dict):
        raise SearchError(
            [
                '答えは {"relevance": "yes" か "maybe", "reason": "…", "headings": ["…"]} または '
                '{"relevance": "no"} の形でなければならない'
            ]
        )
    errors: list[str] = []
    unknown = sorted(set(data) - _ANSWER_KEYS)
    if unknown:
        errors.append(f"答えに定義に無いキーがある: {', '.join(unknown)}")
    relevance = data.get("relevance")
    if not isinstance(relevance, str) or relevance not in RELEVANCES:
        errors.append('relevance が "yes"・"maybe"・"no" のどれかでない')
        relevance = None
    reason: str | None = None
    headings: list[str] = []
    if relevance == RELEVANCE_NO:
        if "reason" in data or "headings" in data:
            errors.append(
                '無関係な答え（relevance が "no"）は、relevance だけを持つ。reason・headings を付けない'
            )
    elif relevance is not None:
        if not isinstance(data.get("reason"), str):
            errors.append(
                f'関連する答え（relevance が "{relevance}"）の reason が文字列でない'
            )
        else:
            reason = data["reason"]
        given = data.get("headings", [])
        if not isinstance(given, list) or not all(
            isinstance(heading, str) for heading in given
        ):
            errors.append("headings が文字列の配列でない")
        else:
            headings = list(given)
    if errors:
        raise SearchError(errors)
    return {"relevance": relevance, "reason": reason, "headings": headings}


def _resolve_headings(document: dict, headings: list[str]) -> list[str]:
    """答えの見出しを、その文書のセクションの[セクション ID]に引き当てる。順序を保ち、重ねては選ばない。

    正規化した完全一致、または、その文書の中で一意に決まる前方一致で引く。引き当てられない見出しがあるときは、
    すべてについて、その文書の見出しの候補を添えて `SearchError` にする（読み替えて補わない）。
    """
    sections = document["sections"]
    candidates = json.dumps(
        [section["name"] for section in sections], ensure_ascii=False
    )
    section_ids: list[str] = []
    errors: list[str] = []
    for heading in headings:
        key = _normalize(heading)
        matched = [s for s in sections if _normalize(s["name"]) == key]
        if not matched and key:
            matched = [s for s in sections if _normalize(s["name"]).startswith(key)]
        if len(matched) == 1:
            if matched[0]["section_id"] not in section_ids:
                section_ids.append(matched[0]["section_id"])
        elif matched:
            errors.append(
                f"見出し {heading!r} は、この文書の複数の見出しに当たる。"
                f"一意に決まる所まで書くこと。この文書の見出し: {candidates}"
            )
        else:
            errors.append(
                f"見出し {heading!r} は、この文書の見出しに無い。"
                f"この文書の見出しのどれかを、そのまま書くこと。この文書の見出し: {candidates}"
            )
    if errors:
        raise SearchError(errors)
    return section_ids


def submit_answer(root: Path, worker_id: str, text: str) -> dict:
    """[検索 AI]が標準入力で渡した答えを、次に答える文書への答えとして検査し、通れば保存して、次の依頼を返す。

    形式が合わない、または見出しを引き当てられないときは、何も保存せずに `SearchError` を送出する（答え直せる）。
    保存した答えは上書きしない。
    """
    fixed, plan, number = _load_worker(root, worker_id)
    search_id = fixed["search_id"]
    answered = _answered(root, search_id, number)
    if answered >= len(plan):
        raise SearchError(
            [f"担当のすべての文書に答えを保存した。これ以上は受け取らない: {worker_id}"]
        )
    doc_id = plan[answered]
    answer = _parse_answer(text)
    section_ids = (
        _resolve_headings(fixed["documents"][doc_id], answer["headings"])
        if answer["relevance"] != RELEVANCE_NO
        else []
    )
    stored = {
        "doc_link_id": doc_id,
        "relevance": answer["relevance"],
        "reason": answer["reason"],
        "section_ids": section_ids,
    }
    path = _file(root, search_id, _answer_name(number, answered + 1))
    if not _publish_new(root, path, state_store.serialize(stored)):
        raise SearchError(
            [f"この文書の答えを既に保存した（上書きしない）: {worker_id}"]
        )
    return {
        "stored": {"position": answered + 1, "total": len(plan)},
        **_next_payload(root, fixed, number, plan, answered + 1),
    }


def collect(root: Path, search_id: str) -> dict:
    """全担当の答えを束ねて、結果として整形する。[セクション ID]は、答えを受け取った時点で引き当て済みである。

    担当のどれかに答えの無い文書が残っている（Agent が答えを渡せなかった）ときは `SearchFailed`。
    """
    fixed = _load_fixed(root, search_id)
    unfinished: list[str] = []
    documents: list[dict] = []
    for worker_id, plan in fixed["workers"].items():
        _, number = split_worker_id(worker_id)
        answered = _answered(root, search_id, number)
        if answered < len(plan):
            unfinished.append(
                f"担当 {worker_id} は、{len(plan)} 件のうち {answered} 件までしか答えていない"
            )
            continue
        for position in range(1, len(plan) + 1):
            answer = _read(
                _file(root, search_id, _answer_name(number, position)),
                f"答えが読めない: {worker_id} の {position} 件目",
            )
            if answer["relevance"] == RELEVANCE_NO:
                continue
            known = fixed["documents"][answer["doc_link_id"]]
            headings = {
                section["section_id"]: section["heading"]
                for section in known["sections"]
            }
            documents.append(
                {
                    "doc_link_id": answer["doc_link_id"],
                    "recorded_path": known["path"],
                    "relevance": answer["relevance"],
                    "reason": answer["reason"],
                    "sections": [
                        {"section_id": section_id, "heading": headings[section_id]}
                        for section_id in answer["section_ids"]
                    ],
                }
            )
    if unfinished:
        raise SearchFailed(
            unfinished
            + [
                "答えの無い文書が残っているので、関連する文書が無い正常な 0 件と見分けられない。検索を失敗とした"
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
        "order_notice": NOTICE_ORDER,
        "documents": documents,
        **fixed.get("backend_info", _backend_info(None)),
    }


def cleanup(root: Path, search_id: str) -> int:
    """検索 ID の依頼・答え・固定した状態をすべて削除する。削除した数を返す（無ければ 0）。"""
    _check_search_id(search_id)
    removed = 0
    for path in _published_files(root, search_id):
        path.unlink(missing_ok=True)
        removed += 1
    return removed
