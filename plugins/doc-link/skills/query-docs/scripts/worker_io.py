# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "markdown-it-py>=4.2.0",
# ]
#
# [tool.uv]
# exclude-newer = "3 days"
# ///
"""`query-worker` の入口（ラッパー）。次の文書の依頼のパスを得る `next` と、答えを標準入力で渡す `answer`。

`query-worker` が打つコマンドを短くするため、`uv run`・プロジェクトのルート・サブコマンドの細部を `query_docs.py` から
切り離した、別の入口である。処理は共通モジュール `search_prepare` が行う。

## 呼び出し方

```
worker_io.py next SEARCH-xxxxxxxx-1
worker_io.py answer SEARCH-xxxxxxxx-1 <<'EOF'
{"relevance": "yes", "reason": "…", "headings": ["…"]}
EOF
```

引数は、サブコマンドと担当の識別値（検索 ID に枝番を付けたもの。`prepare` が返し、SKILL が `query-worker` の prompt に書く）
だけである。プロジェクトのルートは、環境変数 `CLAUDE_PROJECT_DIR`（あれば）と、作業ディレクトリとその親から、検索 ID の
作業ファイルを探して決める（見つからなければ失敗する）。

`query-worker` は、担当の文書を 1 件ずつ受け取り、その文書に答える。どの文書への答えかは script が持つ位置で決まり、
`query-worker` は、文書を指す名前も、[文書 ID]・[セクション ID]・番号も、見ず、書かない。

1. `next`: 次に答える文書の依頼の絶対パス（`item_path`）を返す。JSON 本文は標準出力に載せない。依頼は `task`・`position`・
   `total`・`title`・`purpose`・`summary`（内容概要）・`tasks`（適用作業）・`keywords`・`sections`（見出しの名前の配列）を
   持つ。答えを保存するまで、何度呼んでも同じ文書を返す。担当のすべての文書に答えを保存済みなら、`done` が真になり
   `item_path` は無い。公開されていなければ失敗する
2. `answer`: その文書への答えを標準入力の JSON で渡す。形は `{"relevance": "yes", "reason": "…", "headings": ["…"]}`
   （`headings` は省略できる。その文書の見出しの名前。`"maybe"` も同じ形）または `{"relevance": "no"}`（無関係な答えは `relevance` だけ）
   である。`relevance` は、`"yes"`（関連する）・`"maybe"`（判断がつかないが、関連するかもしれない。取りこぼさないために結果に含める）・
   `"no"`（明らかに無関係）の 3 つの語のどれかだけである。
   形式（JSON として読めること、キーと型）が合わない、または見出しを引き当てられない（その文書の見出しに、正規化した完全一致も、
   一意に決まる前方一致も無い）ときは、何も保存せずに、直すべき箇所（見出しはその文書の見出しの候補）を返す
   （同じ文書に答え直せる）。保存したら、次の文書の `item_path` を返す（答えの保存と次の依頼を、1 回で行う）。
   保存した答えは上書きしない

## 標準出力

終了コード 0 のとき結果の JSON（`next`: `done`・`item_path`・`answered`・`total`、`answer`: `stored`（保存した位置と
総数）と、`next` と同じ項目）、1 のときエラーの JSON（`errors` は自然文の配列）を返す。

## 終了コード

`0`（完了）・`1`（区別のないエラー。識別値・状態が合わない、形式が合わない、見出しを引き当てられない）・`2`（引数を
受理できない）。
"""

import argparse
import os
import sys
from pathlib import Path

# 共通モジュールは、プラグイン直下の scripts/（このファイルの 3 つ上の scripts/）にある。
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import script_output  # noqa: E402
import search_prepare  # noqa: E402

COMMANDS = ("next", "answer")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("worker_id")
    return parser


def execute(
    args: argparse.Namespace, stdin, start: Path, project_dir: str | None
) -> int:
    try:
        search_id, _ = search_prepare.split_worker_id(args.worker_id)
        root = search_prepare.find_project_root(search_id, start, project_dir)
        if args.command == "next":
            return script_output.emit_result(
                search_prepare.next_item(root, args.worker_id)
            )
        return script_output.emit_result(
            search_prepare.submit_answer(root, args.worker_id, stdin.read())
        )
    except search_prepare.SearchError as exc:
        return script_output.emit_error(exc.errors)


def main(argv: list[str] | None = None, stdin=None) -> int:
    args = build_parser().parse_args(argv)
    if stdin is None:
        stdin = sys.stdin
        if hasattr(stdin, "reconfigure"):
            stdin.reconfigure(encoding="utf-8")
    return execute(args, stdin, Path(os.getcwd()), os.environ.get("CLAUDE_PROJECT_DIR"))


if __name__ == "__main__":
    sys.exit(main())
