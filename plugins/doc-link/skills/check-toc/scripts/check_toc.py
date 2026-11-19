# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "markdown-it-py>=4.2.0",
# ]
#
# [tool.uv]
# exclude-newer = "3 days"
# ///
"""[ToC]の鮮度を検査する（check-toc の入口 script）。

何も書き込まない。[確定 ToC]・[文書情報]・対象文書を読むだけである。[確定 ToC]と現物を照合して、未構築・再構築不要・
再構築必要・判定不能を区別し、再構築が必要なときは変更の一覧と再構築の規模の件数を返す。照合は共通モジュール
`toc_check`（`query-docs` の検索前検査と同じもの）が行う。対象は `index-docs` と同じ `--key` と[Index 対象指定]
（`--paths`・`--dirs`・`--exclude`・`--all` など）で決め、引数の検証と展開は共通モジュール `target_spec` を使う。
渡した完全な対象指定は、[確定 ToC]に保存した指定より優先して比較される。

## 呼び出し方

`check_toc.py [--project-root DIR] <対象指定の引数>`。`--project-root` の既定は現在のディレクトリで、
対象指定のパスはここからの相対パスである。

## 標準出力

終了コード 0 のとき結果の JSON、1 のときエラーの JSON（`errors` は自然文の配列）を返す。

- `status`: `not_built`（未構築）・`up_to_date`（再構築不要）・`rebuild_needed`（再構築必要）のいずれか
- `documents`: 変更のある文書。`kinds`（`new`・`departed`・`path_changed`・`content_changed`・`references_changed`）、
  変更前後のパス・ハッシュ（`old_hash` が[反映済みハッシュ]、`new_hash` が[現在ハッシュ]）・参照
- `sections`: セクションごとの変更
- `excluded`・`excluded_in_toc`: ID 未付与・ID 重複で[確定 Index 対象リスト]に入れなかった文書と、そのうち[確定 ToC]に
  入っている文書（再構築すると[確定 ToC]から除かれる）
- `counts`: 変更種別ごとの件数
- `target_spec_changed`・`saved_target_spec`: 渡した対象指定が、保存した指定と違うか、違うときの保存済みの指定
- `scale`: `rebuild_needed` のときの再構築の規模（`new`・`departed`・`path_changed`・`content_changed`・`missing_id`・
  `duplicate_id`・`ai_generation`）。それ以外は `null`
- `problems`・`warnings`: 対象指定の展開が報告した、存在しない・Markdown でない指定など

## 仕様の解釈

- 未構築・再構築不要・再構築必要は、検査として完了しているので、終了コードは 0 である
- 判定不能（[確定 ToC]・[文書情報]・対象文書を読めない、保存済みの対象指定を解釈できない、など）は、検査を完了できて
  いないので、0 を返さない。判定できなかった対象と原因を `errors` に書いて 1 を返す。再構築不要・再構築必要のどちらにも
  読み替えない

## 終了コード

| code | 意味                                                                                                         |
| ---- | ------------------------------------------------------------------------------------------------------------ |
| 0    | 検査が完了した（未構築・再構築不要・再構築必要のいずれか）                                                   |
| 1    | 区別のないエラー（対象指定の拒否、判定不能）                                                                 |
| 2    | 引数を受理できない（`argparse`）                                                                             |
"""

import argparse
import os
import sys
from pathlib import Path

# 共通モジュールは、プラグイン直下の scripts/（このファイルの 3 つ上の scripts/）にある。
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import script_output  # noqa: E402
import target_spec  # noqa: E402
import toc_check  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-root", default=os.getcwd())
    target_spec.add_target_arguments(parser)
    return parser


def execute(args: argparse.Namespace) -> int:
    root = Path(os.path.abspath(args.project_root))
    try:
        spec = target_spec.parse_namespace(args, root)
    except target_spec.TargetSpecError as exc:
        return script_output.emit_error(exc.errors)

    toc_key = spec.key if spec.mode == target_spec.MODE_TARGETS else None
    result = toc_check.check_toc(root, toc_key, spec)
    if result.status == toc_check.STATUS_UNDETERMINABLE:
        return script_output.emit_error(
            ["[ToC]の鮮度を判定できない"]
            + [cause.describe() for cause in result.causes]
        )
    return script_output.emit_result(result.to_dict())


def main(argv: list[str] | None = None) -> int:
    return execute(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
