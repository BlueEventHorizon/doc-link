# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "markdown-it-py>=4.2.0",
# ]
#
# [tool.uv]
# exclude-newer = "3 days"
# ///
"""文書を検索する（query-docs の入口 script）。検索前検査・検索の担当の固定・全担当の答えを束ねた結果の返却。

[ToC]・管理状態（`.doc-link/`）・[Index 対象文書]へは書き込まない。書くのは `.temp/doc-link/query-docs/` の
作業ファイルだけである。処理は共通モジュール `search_prepare` が行う（検索前検査の判定は `check-toc` と同じ
`toc_check`）。受け渡しの型は Agent とのデータ受け渡し規約に従い、運ぶのは検索 ID と担当の識別値（script が生成する）
だけである。

## 検索基盤（DES-011、REQ-006）

`prepare` は、検索前検査の前に、[検索基盤]を決める（`backend_select`。設定ファイル `.doc-link/config.json` の `backend` と、
[doc-db]への接続の可否）。[強制スイッチ]の呼び出しごとの指定（引数）は無い。設定ファイルを受理できないときは、検索せず、
終了コード 1 で原因を返す。[doc-db]に接続できないとき（実行ファイルはある）は、[doc-db]を起動せずに止まり、`action` が
`confirm_docdb_startup`（利用者に、起動してよいかを聞く）の結果を返す（終了コード 0。何も書き込まない）。利用者の回答は
`--docdb-startup`（`start`＝起動してよい、`toc`＝今回は[ToC]で続ける）で渡して、`prepare` をやり直す。許可を得て起動した
のに接続できなかったときは、切り替えずに `action` が `docdb_startup_failed`（起動できなかったこと・原因の分類・起動の
command・選択肢）の結果を返す。実行ファイルが無い・[doc-db]の設定から `port` を得られないときは、許可を求めずに[ToC]へ切り替える。結果は、`backend`・`forced`・`startup`・`backend_switch`（切り替えが無ければ
`null`。あれば `notice` に、AI が利用者へ伝える通知の文）を持つ。

## 呼び出し方

どのサブコマンドも `--project-root`（既定は現在のディレクトリ）を取る。値が `-` で始まる引数は、`--task=-値` のように
`=` でつなぐ。AI は JSON・パス・検索 ID を組み立てない（返された値をそのまま運ぶ）。

1. `prepare --task T [--choice rebuild|existing] [--key K] [対象指定の引数]`: 検索前検査を行い、次の行動（`action`）を返す。
   `--task` は検索のタスクで、値のまま依頼に書かれる。対象指定の引数（`--all`・`--paths`・`--dirs`・`--exclude` など。
   規則は `target_spec`）を 1 つも付けないときは、`--key`（省略時は予約キー `all`）の[確定 ToC]に保存された指定を使う。
   付けたときは、完全な指定として保存済みの指定より優先して比較する。`--choice` は、利用者の二択の選択結果である
   （`rebuild`: 再構築後に検索、`existing`: 既存版のまま検索。[doc-db]を使うときは `existing` を受け付けない）。
   - `initial_build_required`: 未構築。検索しない。SKILL は `index-docs` による初回構築が必要だと返す
   - `confirm_rebuild`: 再構築が必要。`scale`（新規・離脱・パス変更・内容変更・ID 未付与・ID 重複・AI 生成が必要な件数）と
     変更の種別ごとの件数、`options`（二択）、`detail_path`、`target_file` を返す。変更のある文書・セクションごとの
     明細は標準出力に載せず、`detail_path` の明細ファイルにある（要件 D-061）。`target_file` は、検査に使った
     [ToC 識別キー]と[Index 対象指定]を script が書いた対象指定ファイルの絶対パスである（要件 D-063）。SKILL は規模を
     添えて利用者に二択を確認する（AskUserQuestion）。
     「再構築してから検索する」: `index-docs` を `--target-file <target_file の値>` で実行し、`prepare` を `--task` と
     `--choice rebuild --target-file <target_file の値>` でやり直す。対象指定を引数へ書き写さない。
     「既存の[ToC]のまま検索する」: 同じ引数に `--choice existing` を付けて `prepare` をやり直す
   - `rebuild_required`: 二択を示さず、再構築を求める。`reason` は `toc_stale`（[doc-db]を使うときの、機械取得の情報の古さ）か
     `ai_fields_needed`（[ToC]を使うときに、[AI 生成フィールド]が要る文書がある）。`scale`・`ai_fields_needed`・`detail_path`・
     `target_file` を返す。SKILL は、規模を利用者へ知らせ（確認は求めない）、`index-docs` を `--target-file <target_file の値>`
     で実行してもらった後、`prepare` を `--task` と `--choice rebuild --target-file <target_file の値>` でやり直す
   - `docdb_result`: [doc-db]で検索した結果。`documents`（[ToC]の検索結果と同じ項目。`relevance` は `maybe` の固定、`reason` は
     script が組み立てた文、`rank`）・`toc_key`・`toc_version`・`freshness`（`current`）・`path_notice`・`order_notice`・
     `limit_notice`（上位の結果に限る）・`unmapped`（対応づけられなかった結果の件数）・`sync`（同期の結果）・`warnings` を返す。
     `collect` は要らない。SKILL は、この結果を呼び出し元へ返す
   - `invoke_query_worker`: 検索に使う[ToC]を固定し、文書を担当に分けた。`search_id`・`workers`（担当の識別値の並び。
     文書が無いときは空）・`toc_key`・`toc_version`（使用版）・`freshness`（`current`: 最新、`possibly_stale`: 古い可能性。
     `freshness_notice` に文言）を返す。SKILL は `workers` の 1 件ごとに `query-worker` を起動し（同時に起動する数は、
     script が上限以内に分けてある）、担当の識別値だけを渡す。すべての完了を待ってから `collect` を呼ぶ
   - 判定不能（[確定 ToC]・[文書情報]・対象文書を読めない、保存済みの対象指定を解釈できないなど）は、障害として停止する。
     終了コード 1 とエラーの JSON（判定できなかった対象と原因）を返し、旧版で検索する選択肢を出さない。
     `--choice rebuild` の後も再構築要否が「再構築必要」のままのときも、終了コード 1 を返す（旧版で黙って検索しない）
2. `collect --search-id ID`: 全担当の答えを束ねて返す。SKILL は、検索結果として `documents`（`doc_link_id`・
   `recorded_path`・`relevance`（`yes`: 関連する、`maybe`: 判断がつかないが、関連するかもしれない）・`reason`・`sections`）に、`toc_key`・`toc_version`・`freshness`・`freshness_notice`・`path_notice`・
   `order_notice` を添えて呼び出し元へ返す。`documents` の並びは、担当の順と担当の中の順であり、関連度の順ではない。
   返した後に、検索 ID の依頼・答え・固定した状態をすべて削除する（失敗を返した後も削除する）。
   `query-worker` は、ID を見ず、書かない。文書を 1 件ずつ受け取って答え、セクションは見出しの文字列で答える。script が、
   答えを受け取る時点で、見出しを[セクション ID]に引き当てる（見出しに引き当てられなければ、保存せずに候補を返す）。
   担当のどれかに答えの無い文書が残っている（`query-worker` が答えを渡せなかった）ときは、関連する文書が無い正常な
   0 件と見分けられないので、検索の失敗として終了コード 3 とエラーの JSON を返す。SKILL は失敗を呼び出し元へ返す
   （結果を補わない）
3. `cleanup --search-id ID`: 検索 ID の作業ファイルをすべて削除する（`query-worker` を起動できなかったときなど、
   `collect` を呼ばずに終えるとき）

`query-worker` が使う入口は、この script ではなく、同じディレクトリのラッパー `worker_io.py` である（次の文書の依頼の
パスを得る `next`、答えを標準入力で渡す `answer`）。引数は担当の識別値だけで、プロジェクトのルートは作業ディレクトリから探す。

## 標準出力

終了コード 0 のとき結果の JSON、それ以外（2 を除く）のときエラーの JSON（`errors` は自然文の配列）を返す。

## 終了コード

| code | 意味                                                                                                                         |
| ---- | ---------------------------------------------------------------------------------------------------------------------------- |
| 0    | 操作が完了した（`prepare` は次の行動を返した。未構築・再構築必要・固定のどれも 0。`collect` は検査済みの結果を返した）        |
| 1    | 区別のないエラー（対象指定の拒否、判定不能の障害、識別値・状態が合わない、再構築後も一致しない）                             |
| 2    | 引数を受理できない（`argparse`）                                                                                             |
| 3    | 検索が失敗した（担当のどれかに答えの無い文書が残っている）。検索結果は返さない                                               |

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

import backend_config  # noqa: E402
import backend_select  # noqa: E402
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
    prepare.add_argument(
        "--docdb-startup",
        choices=backend_select.STARTUP_CHOICES,
        default=None,
        help="doc-db に接続できないときの利用者の回答（start＝起動してよい、toc＝今回は ToC で続ける）",
    )
    target_spec.add_target_arguments(prepare)

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
            args.target_file,
        )
    )


def _parse_search_target(args: argparse.Namespace, root: Path):
    """[ToC 識別キー]と、完全な対象指定（無ければ `None`）を返す。"""
    if not _has_target_arguments(args):
        if args.key == target_spec.RESERVED_KEY:
            # index-docs・check-toc と同じく、予約キーを --key に指定させない（要件 D-014）
            raise search_prepare.SearchError(
                [
                    "--key all は予約語なので指定できない（既定の ToC は --key を省いて検索する）"
                ]
            )
        return (target_spec.RESERVED_KEY if args.key is None else args.key), None
    try:
        spec = target_spec.parse_namespace(args, root)
    except target_spec.TargetSpecError as exc:
        raise search_prepare.SearchError(exc.errors) from exc
    return spec.key or target_spec.RESERVED_KEY, spec


def _prepare(args: argparse.Namespace, root: Path) -> int:
    toc_key, spec = _parse_search_target(args, root)
    try:
        decision = backend_select.decide(root, startup=args.docdb_startup)
    except backend_config.BackendConfigError as exc:
        raise search_prepare.SearchError(exc.errors) from exc
    if decision.pending is not None:
        # 利用者の回答を待つ。検索前検査・検索をしない（何も書き込まない）
        return script_output.emit_result(decision.pending.to_dict())
    return script_output.emit_result(
        search_prepare.prepare(root, toc_key, spec, args.task, args.choice, decision)
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
