# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "markdown-it-py>=4.2.0",
# ]
#
# [tool.uv]
# exclude-newer = "3 days"
# ///
"""[DLID]の並びを、管理状態に記録されたパスの現物で解決する（resolve-dlid の入口 script）。

何も書き込まない。管理状態（`.doc-link/`）と、記録されたパスの文書を読むだけである。記録されたパスの
外は探索しない。入力は[DLID]の並びだけで、[ToC 識別キー]は受け取らない。

## 呼び出し方

`resolve_dlid.py [--project-root DIR] DLID [DLID ...]`。`--project-root` の既定は現在のディレクトリ。

## 標準出力

終了コード 0 のとき結果の JSON、1 のときエラーの JSON（`errors` は自然文の配列）を返す。

- `results`: 入力の順（重複は最初の 1 つだけ）の、[DLID]ごとの結果の配列。各要素は次を持つ
  - `dlid`、`kind`（`document`・`section`。記録から決まる。`no_record` のときは `null`）
  - `status`: `resolved`（解決済み）・`not_at_recorded_path`（記録されたパスに無い）・`no_record`（記録が無い）
  - `resolved` のとき: `path`（記録されたパスで、現物の[DLID]と一致したもの）。`kind` が `section` なら
    `heading`（見出しの文字列。行末の[DLID]を含む。アンカーの元もこの文字列）と `anchor`
  - `not_at_recorded_path` のとき: `recorded_paths`（記録されたパスのすべて。現在の実体パスではない）
  - `resolved` のとき: `content_hash`（[内容ハッシュ]。得られないときは `null`）と `content_hash_state`
    （`recorded`・`differs`・`unavailable`）
- `guidance`: 後工程の案内（自然文の配列）。`not_at_recorded_path` があるとき `index-docs` の実行を案内する

## 仕様の解釈

- [DLID]として認識できない値（`DLID-` と小文字の Crockford Base32 の 12 文字でないもの）が 1 つでも
  あるとき、またはまったく渡されないときは、何も解決せず終了コード 1 のエラーにする。認識できない値を
  「記録が無い」と取り違えない
- 同じ[DLID]が複数回渡されたときは、結果を 1 つにする
- 文書の[DLID]は、その[文書情報]があれば文書とする。[文書情報]が無いとき、全キーの[確定 ToC]の
  セクションエントリに同じ[セクション ID]があれば、セクションとする。どちらにも無ければ `no_record`
- セクションの候補は、セクションエントリの所属文書（`doc_link_id`）のうち、[文書情報]を持つものすべて
  （記録の順に重複なし）。[文書情報]を持つ候補が無ければ `no_record`。記録されたパスは候補ごとに
  その[文書情報]の `path`
- 候補を順に、記録されたパスの現物と照合し、最初に一致した候補だけを解決済みにする。文書は frontmatter の
  `doc_link_id`、セクションは見出しの行の末尾の[DLID]（同じ文書に同じ[DLID]の見出しが複数あれば最初の
  もの）と照合する。ファイルが無い・読めない・UTF-8 でない・プロジェクトルートの外を指す・[DLID]が
  一致しない場合は不一致であり、どの候補も一致しなければ `not_at_recorded_path`
- [内容ハッシュ]は現物から計算しない。文書は[文書情報]の `content_hash`、セクションは一致した候補の文書に
  属する全キーのセクションエントリの `content_hash`。セクションのそれが記録によって異なるとき
  `content_hash` は `null` で `content_hash_state` は `differs`。空文字列で得られないときは `null` と
  `unavailable`。1 つに定まれば `recorded`
- 管理状態を読めない（`StateStoreError` の `missing` 以外の `kind`）ときは、全体を失敗にして終了コード 1 で
  `kind` と対象を返す。「無い」（`.doc-link/` や[文書情報]が存在しない）は `no_record` であり、失敗ではない

## 終了コード

| code | 意味                                                                                  |
| ---- | ------------------------------------------------------------------------------------- |
| 0    | 解決が完了した（`not_at_recorded_path`・`no_record` があっても完了である）            |
| 1    | 区別のないエラー（[DLID]として認識できない入力、入力が無い、管理状態を読めない）      |
| 2    | 引数を受理できない（`argparse`）                                                      |
"""

import argparse
import os
import sys
from pathlib import Path

# 共通モジュールは、プラグイン直下の scripts/（このファイルの 3 つ上の scripts/）にある。
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import script_output  # noqa: E402
import state_store  # noqa: E402
from markdown_reader import is_dlid, read_document  # noqa: E402

STATUS_RESOLVED = "resolved"
STATUS_NOT_AT_PATH = "not_at_recorded_path"
STATUS_NO_RECORD = "no_record"

HASH_RECORDED = "recorded"
HASH_DIFFERS = "differs"
HASH_UNAVAILABLE = "unavailable"

GUIDANCE_INDEX = (
    "記録されたパスに無い[DLID]がある。`index-docs` を実行して[ToC]を再構築すると、"
    "記録が現物に合わせて更新される（ユーザーまたはプロジェクト管理 AI が実行する）"
)


class _Records:
    """管理状態の記録。読めないときは `StateStoreError` を送出する。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.tocs = [
            state_store.load_confirmed_toc(root, key)
            for key in state_store.list_toc_keys(root)
        ]
        self._infos: dict[str, dict | None] = {}

    def document_info(self, doc_id: str) -> dict | None:
        if doc_id not in self._infos:
            try:
                self._infos[doc_id] = state_store.load_document_info(self.root, doc_id)
            except state_store.StateStoreError as exc:
                if exc.kind != state_store.KIND_MISSING:
                    raise
                self._infos[doc_id] = None
        return self._infos[doc_id]

    def section_entries(self, section_id: str) -> list[dict]:
        return [
            entry
            for toc in self.tocs
            for entry in toc["sections"]
            if entry["section_id"] == section_id
        ]


class _Documents:
    """記録されたパスの現物を読む。同じパスは 1 回だけ読む。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[str, object] = {}

    def read(self, recorded_path: str):
        """解析した文書を返す。読めないときは `None`（確かめられない）。"""
        if recorded_path not in self._cache:
            self._cache[recorded_path] = self._read(recorded_path)
        return self._cache[recorded_path]

    def _read(self, recorded_path: str):
        # 記録されたパスが、字面でプロジェクトの外へ出るときは読まない。
        # プロジェクト内のパスがシンボリックリンクで外の実体を指すときは、読む
        # （index-docs が同じ実体を読んで記録しており、確かめられなくなるため）。
        normalized = os.path.normpath(recorded_path)
        if (
            os.path.isabs(normalized)
            or normalized == os.pardir
            or normalized.startswith(os.pardir + os.sep)
        ):
            return None
        try:
            target = self.root / normalized
            return read_document(target.read_bytes().decode("utf-8"))
        except (OSError, ValueError):
            return None


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _resolve_document(dlid: str, info: dict, documents: _Documents) -> dict:
    document = documents.read(info["path"])
    if document is None or document.frontmatter.doc_link_id != dlid:
        return _not_at_path(dlid, "document", [info["path"]])
    recorded = info["content_hash"]
    return {
        "dlid": dlid,
        "kind": "document",
        "status": STATUS_RESOLVED,
        "path": info["path"],
        "content_hash": recorded or None,
        "content_hash_state": HASH_RECORDED if recorded else HASH_UNAVAILABLE,
    }


def _resolve_section(
    dlid: str, entries: list[dict], records: _Records, documents: _Documents
) -> dict:
    candidates = []
    for doc_id in _unique([entry["doc_link_id"] for entry in entries]):
        info = records.document_info(doc_id)
        if info is not None:
            candidates.append((doc_id, info["path"]))
    if not candidates:
        return _no_record(dlid)
    for doc_id, path in candidates:
        document = documents.read(path)
        if document is None:
            continue
        heading = next((h for h in document.headings if h.section_id == dlid), None)
        if heading is None:
            continue
        hashes = {
            entry["content_hash"] for entry in entries if entry["doc_link_id"] == doc_id
        }
        if len(hashes) > 1:
            content_hash, state = None, HASH_DIFFERS
        elif hashes == {""} or not hashes:
            content_hash, state = None, HASH_UNAVAILABLE
        else:
            (content_hash,) = hashes
            state = HASH_RECORDED
        return {
            "dlid": dlid,
            "kind": "section",
            "status": STATUS_RESOLVED,
            "path": path,
            "heading": heading.text,
            "anchor": heading.anchor,
            "content_hash": content_hash,
            "content_hash_state": state,
        }
    return _not_at_path(dlid, "section", _unique([path for _, path in candidates]))


def _not_at_path(dlid: str, kind: str, recorded_paths: list[str]) -> dict:
    return {
        "dlid": dlid,
        "kind": kind,
        "status": STATUS_NOT_AT_PATH,
        "recorded_paths": recorded_paths,
    }


def _no_record(dlid: str) -> dict:
    return {"dlid": dlid, "kind": None, "status": STATUS_NO_RECORD}


def resolve(root: Path, dlids: list[str]) -> dict:
    """[DLID]を解決する。`StateStoreError` は呼び出し側へ伝える。"""
    records = _Records(root)
    documents = _Documents(root)
    results = []
    for dlid in dict.fromkeys(dlids):
        info = records.document_info(dlid)
        if info is not None:
            results.append(_resolve_document(dlid, info, documents))
            continue
        entries = records.section_entries(dlid)
        if entries:
            results.append(_resolve_section(dlid, entries, records, documents))
        else:
            results.append(_no_record(dlid))
    guidance = []
    if any(result["status"] == STATUS_NOT_AT_PATH for result in results):
        guidance.append(GUIDANCE_INDEX)
    return {"results": results, "guidance": guidance}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-root", default=os.getcwd())
    parser.add_argument("dlids", nargs="*", metavar="DLID")
    return parser


def execute(args: argparse.Namespace) -> int:
    if not args.dlids:
        return script_output.emit_error(["[DLID]が 1 つも渡されていない"])
    invalid = [value for value in args.dlids if not is_dlid(value)]
    if invalid:
        return script_output.emit_error(
            [f"[DLID]として認識できない値: {value!r}" for value in invalid]
        )
    root = Path(os.path.abspath(args.project_root))
    try:
        result = resolve(root, args.dlids)
    except state_store.StateStoreError as exc:
        target = "" if exc.path is None else f"（対象: {exc.path}）"
        return script_output.emit_error(
            [f"管理状態を読めない: kind={exc.kind}{target}: {exc}"]
        )
    return script_output.emit_result(result)


def main(argv: list[str] | None = None) -> int:
    return execute(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
