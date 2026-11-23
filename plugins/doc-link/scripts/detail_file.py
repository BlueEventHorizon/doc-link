"""結果の全件（明細）を作業ファイルへ書く共通モジュール。

要件 D-059・D-061 を実装する。検査（`check-dlid`・`check-links`・`check-toc`・`check-impact`）、検索前検査
（`query-docs`）、構築（`index-docs`）の入口 script が使う。入口 script ではないので、PEP 723 とロックは持たない。

標準出力には、呼び出し元（[プロジェクト管理 AI]）の判断に要る項目と件数だけを返し、件数に比例して大きくなる明細
（検出事項、変更のある文書とセクション、変更影響候補など）は、ここで作業ファイルへ書く。文書を大量に移動・変更
したときも、標準出力の大きさが変わらないようにするためである。

## 置き場と名前

`.temp/doc-link/<SKILL の名前>/detail-<符号化した[ToC 識別キー]>.json`。SKILL と[ToC 識別キー]の組ごとに 1 つで、
同じ組の次の実行が置き換える。符号化は `state_store.encode_name`、直列化は `state_store.serialize`
（同じ内容から同じバイト列）、置き換えは `state_store.write_if_changed`（一時ファイルへ書き終えてから 1 回）を使う。

## 仕様の解釈

- 明細が 0 件でも書く。呼び出し元が、パスの有無で分岐しなくて済むようにするためである
- [Index 対象文書]と管理状態（`.doc-link/`）へは書き込まない。書くのは上の作業ファイルだけである
- プロジェクトルートが既存のディレクトリでないときは、書かない（書けない場合として扱う）。存在しないルートの下に
  ディレクトリを作らないためである
- 書けないときは、既定値で代替せず、`state_store.StateStoreError` を呼び出し側へ伝える。`emit_with_detail` は、
  それをエラーの JSON（終了コード 1）にする。明細を捨てて件数だけを返すことはしない
"""

import os
from pathlib import Path

import script_output
import state_store

DETAIL_PREFIX = "detail-"
DETAIL_PATH_FIELD = "detail_path"


def detail_path(project_root: str | Path, skill: str, toc_key: str) -> Path:
    """明細ファイルのパス。SKILL と[ToC 識別キー]の組ごとに 1 つである。"""
    return Path(project_root).joinpath(
        *state_store.TEMP_ROOT,
        skill,
        f"{DETAIL_PREFIX}{state_store.encode_name(toc_key)}{state_store.FILE_SUFFIX}",
    )


def write_detail(
    project_root: str | Path, skill: str, toc_key: str, detail: dict
) -> str:
    """明細を作業ファイルへ書き、その絶対パスを返す。書けないときは `StateStoreError`。"""
    root = Path(project_root)
    if not root.is_dir():
        raise state_store.StateStoreError(
            state_store.KIND_MISSING,
            f"プロジェクトルートが既存のディレクトリでない: {root}",
            root,
        )
    path = detail_path(root, skill, toc_key)
    state_store.write_if_changed(root, skill, path, state_store.serialize(detail))
    return os.path.abspath(path)


def emit_with_detail(
    project_root: str | Path, skill: str, toc_key: str, summary: dict, detail: dict
) -> int:
    """明細を書いてから、要約に明細ファイルのパスを足して標準出力へ返す。

    明細を書けないときは、要約を返さず、エラーの JSON と終了コード 1 を返す。
    """
    try:
        path = write_detail(project_root, skill, toc_key, detail)
    except state_store.StateStoreError as exc:
        return script_output.emit_error([f"明細ファイルを書けない: {exc}"])
    return script_output.emit_result({**summary, DETAIL_PATH_FIELD: path})
