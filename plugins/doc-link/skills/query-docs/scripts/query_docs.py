# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "markdown-it-py>=4.2.0",
# ]
# ///
"""文書を検索する（query-docs の入口 script）。検索前検査・[ToC]の写しの固定・`query-worker` との受け渡し・結果の検査。

[ToC]・管理状態（`.doc-link/`）・[Index 対象文書]へは書き込まない。書くのは `.temp/doc-link/query-docs/` の
作業ファイルだけである。処理は共通モジュール `search_prepare` が行う（検索前検査の判定は `check-toc` と同じ
`toc_check`）。受け渡しの型は Agent とのデータ受け渡し規約に従い、運ぶのは検索 ID（script が生成する）だけである。

## 呼び出し方

どのサブコマンドも `--project-root`（既定は現在のディレクトリ）を取る。値が `-` で始まる引数は、`--task=-値` のように
`=` でつなぐ。AI は JSON・パス・検索 ID を組み立てない（返された値をそのまま運ぶ）。

1. `prepare --task T [--choice rebuild|existing] [--key K] [対象指定の引数]`: 検索前検査を行い、次の行動（`action`）を返す。
   `--task` は検索のタスクで、値のまま依頼に書かれる。対象指定の引数（`--all`・`--paths`・`--dirs`・`--exclude` など。
   規則は `target_spec`）を 1 つも付けないときは、`--key`（省略時は予約キー `all`）の[確定 ToC]に保存された指定を使う。
   付けたときは、完全な指定として保存済みの指定より優先して比較する。`--choice` は、利用者の二択の選択結果である
   （`rebuild`: 再構築後に検索、`existing`: 既存版のまま検索）。
   - `initial_build_required`: 未構築。検索しない。SKILL は `index-docs` による初回構築が必要だと返す
   - `confirm_rebuild`: 再構築が必要。`scale`（新規・離脱・パス変更・内容変更・ID 未付与・ID 重複・AI 生成が必要な件数）と
     変更の一覧、`options`（二択）を返す。SKILL は規模を添えて利用者に二択を確認する（AskUserQuestion）。
     「再構築してから検索する」: `index-docs` を実行し、同じ引数に `--choice rebuild` を付けて `prepare` をやり直す。
     「既存の[ToC]のまま検索する」: 同じ引数に `--choice existing` を付けて `prepare` をやり直す
   - `invoke_query_worker`: 検索に使う[ToC]を固定した。`search_id`・`toc_key`・`toc_version`（使用版）・`freshness`
     （`current`: 最新、`possibly_stale`: 古い可能性。`freshness_notice` に文言）を返す。SKILL は `query-worker` を起動し、
     検索 ID だけを渡す。完了を待ってから `collect` を呼ぶ
   - 判定不能（[確定 ToC]・[文書情報]・対象文書を読めない、保存済みの対象指定を解釈できないなど）は、障害として停止する。
     終了コード 1 とエラーの JSON（判定できなかった対象と原因）を返し、旧版で検索する選択肢を出さない。
     `--choice rebuild` の後も再構築要否が「再構築必要」のままのときも、終了コード 1 を返す（旧版で黙って検索しない）
2. `request-path --search-id ID`: 依頼の絶対パス（`{"path": …}`）を返す。`query-worker` が使う。JSON 本文は標準出力に載せない。
   依頼は `search_id`・`task`・`toc_key`・`toc_copy_path`（[ToC]の写しの絶対パス）を持つ。写しは `documents` の配列で、
   要素は `doc_link_id`・`title`・`purpose`・`summary`（内容概要）・`tasks`（適用作業）・`keywords`・`sections`
   （`section_id`・`heading`）である。公開されていなければ失敗する
3. `submit-item --search-id ID --doc-id DOC_ID --reason R [--section-id S]...`: `query-worker` が、関連する文書を 1 件ずつ渡す。
   並べた順が結果の並びになる。値は変形されずに届く。検査は `collect` が行う
4. `submit-end --search-id ID --exit-value V`: 終了の値を渡す。正常は `"0"`。エラー値は無い。1 回だけで、上書きしない。
   すべての `submit-item` の後に呼ぶ。0 件でも呼ぶ
5. `collect --search-id ID`: 結果を検査して返す。SKILL は、検索結果として `documents`（`doc_link_id`・`recorded_path`・
   `reason`・`sections`）に、`toc_key`・`toc_version`・`freshness`・`freshness_notice`・`path_notice` を添えて呼び出し元へ返す。
   返した後に、検索 ID の依頼・結果・写し・固定した状態をすべて削除する（失敗を返した後も削除する）。
   終了の値が無い・定義外、固定した[ToC]の版に無い[文書 ID]・[セクション ID]を含む結果は、検索の失敗として
   終了コード 3 とエラーの JSON を返す。SKILL は失敗を呼び出し元へ返す（結果を補わない）
6. `cleanup --search-id ID`: 検索 ID の作業ファイルをすべて削除する（`query-worker` を起動できなかったときなど、
   `collect` を呼ばずに終えるとき）

## 標準出力

終了コード 0 のとき結果の JSON、それ以外（2 を除く）のときエラーの JSON（`errors` は自然文の配列）を返す。

## 終了コード

| code | 意味                                                                                                                         |
| ---- | ---------------------------------------------------------------------------------------------------------------------------- |
| 0    | 操作が完了した（`prepare` は次の行動を返した。未構築・再構築必要・固定のどれも 0。`collect` は検査済みの結果を返した）        |
| 1    | 区別のないエラー（対象指定の拒否、判定不能の障害、識別値・状態が合わない、再構築後も一致しない）                             |
| 2    | 引数を受理できない（`argparse`）                                                                                             |
| 3    | 検索が失敗した（終了の値が無い・定義外、固定した[ToC]の版に無い ID を含む結果）。検索結果は返さない                          |

## 仕様の解釈

- 対象指定の引数が無く `--key` だけのとき（または何も無いとき）は、保存済みの指定を使う（FR-006 の「保存された指定を基に検査する」）。
  `check-toc` は対象指定を必須とする点が異なる
- そのほかの解釈は `search_prepare` の docstring を参照
"""

import argparse
import os
import sys
from pathlib import Path

# 共通モジュールは、プラグイン直下の scripts/（このファイルの 3 つ上の scripts/）にある。
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import script_output  # noqa: E402
import search_prepare  # noqa: E402
import target_spec  # noqa: E402

EXIT_SEARCH_FAILED = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subcommands = parser.add_subparsers(dest="command", required=True)

    prepare = subcommands.add_parser("prepare", help="検索前検査を行い、次の行動を返す")
    prepare.add_argument("--project-root", default=os.getcwd())
    prepare.add_argument("--task", required=True)
    prepare.add_argument("--choice", choices=search_prepare.CHOICES, default=None)
    target_spec.add_target_arguments(prepare)

    request = subcommands.add_parser("request-path", help="依頼の絶対パスを返す")
    request.add_argument("--project-root", default=os.getcwd())
    request.add_argument("--search-id", required=True)

    item = subcommands.add_parser("submit-item", help="関連する文書を 1 件渡す")
    item.add_argument("--project-root", default=os.getcwd())
    item.add_argument("--search-id", required=True)
    item.add_argument("--doc-id", required=True)
    item.add_argument("--reason", required=True)
    item.add_argument("--section-id", action="append", default=[])

    end = subcommands.add_parser("submit-end", help="終了の値を渡す")
    end.add_argument("--project-root", default=os.getcwd())
    end.add_argument("--search-id", required=True)
    end.add_argument("--exit-value", required=True)

    collect = subcommands.add_parser("collect", help="結果を検査して返し、後始末する")
    collect.add_argument("--project-root", default=os.getcwd())
    collect.add_argument("--search-id", required=True)

    cleanup = subcommands.add_parser("cleanup", help="作業ファイルを削除する")
    cleanup.add_argument("--project-root", default=os.getcwd())
    cleanup.add_argument("--search-id", required=True)
    return parser


def _has_target_arguments(args: argparse.Namespace) -> bool:
    return args.all_targets or any(
        value is not None
        for value in (
            args.paths,
            args.paths_json,
            args.paths_file,
            args.dirs,
            args.dirs_json,
            args.exclude,
            args.exclude_json,
        )
    )


def _parse_search_target(args: argparse.Namespace, root: Path):
    """[ToC 識別キー]と、完全な対象指定（無ければ `None`）を返す。"""
    if not _has_target_arguments(args):
        return (target_spec.RESERVED_KEY if args.key is None else args.key), None
    try:
        spec = target_spec.parse_namespace(args, root)
    except target_spec.TargetSpecError as exc:
        raise search_prepare.SearchError(exc.errors) from exc
    return spec.key or target_spec.RESERVED_KEY, spec


def _prepare(args: argparse.Namespace, root: Path) -> int:
    toc_key, spec = _parse_search_target(args, root)
    return script_output.emit_result(
        search_prepare.prepare(root, toc_key, spec, args.task, args.choice)
    )


def _collect(args: argparse.Namespace, root: Path) -> int:
    try:
        payload = search_prepare.collect(root, args.search_id)
    except search_prepare.SearchFailed as exc:
        script_output.emit_result({"errors": exc.errors, "search_id": args.search_id})
        search_prepare.cleanup(root, args.search_id)
        return EXIT_SEARCH_FAILED
    script_output.emit_result(payload)
    search_prepare.cleanup(root, args.search_id)
    return script_output.EXIT_OK


def execute(args: argparse.Namespace) -> int:
    root = Path(os.path.abspath(args.project_root))
    try:
        if args.command == "prepare":
            return _prepare(args, root)
        if args.command == "request-path":
            return script_output.emit_result(
                {"path": search_prepare.request_path(root, args.search_id)}
            )
        if args.command == "submit-item":
            return script_output.emit_result(
                search_prepare.submit_item(
                    root, args.search_id, args.doc_id, args.reason, args.section_id
                )
            )
        if args.command == "submit-end":
            return script_output.emit_result(
                search_prepare.submit_end(root, args.search_id, args.exit_value)
            )
        if args.command == "collect":
            return _collect(args, root)
        removed = search_prepare.cleanup(root, args.search_id)
        return script_output.emit_result({"removed": removed})
    except search_prepare.SearchError as exc:
        return script_output.emit_error(exc.errors)


def main(argv: list[str] | None = None) -> int:
    return execute(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
