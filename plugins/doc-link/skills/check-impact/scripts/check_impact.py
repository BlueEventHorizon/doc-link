# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "markdown-it-py>=4.2.0",
# ]
#
# [tool.uv]
# exclude-newer = "3 days"
# ///
"""変更影響候補を列挙する（check-impact の入口 script）。

何も書き込まない。[確定 ToC]・[文書情報]・参照元の文書を読むだけで、通知の状態を持たない。判断・修正・title の
[内容ハッシュ]の書き換えは[プロジェクト管理 AI]が行い、この script は行わない。対象は `index-docs` と同じ `--key` と
[Index 対象指定]（`--paths`・`--dirs`・`--exclude`・`--all` など）で決め、引数の検証と展開は共通モジュール
`target_spec` を使う。[ToC]が最新かの確認は共通モジュール `toc_check`（`check-toc` と同じもの）、列挙は共通モジュール
`impact_candidates` が行い、このファイルはそれらを再実装しない。

## 呼び出し方

`check_impact.py [--project-root DIR] <対象指定の引数>`。`--project-root` の既定は現在のディレクトリで、
対象指定のパスはここからの相対パスである。

## 標準出力

終了コード 0 のとき結果の JSON、1 のときエラーの JSON（`errors` は自然文の配列）を返す。

[ToC]が未構築（`not_built`）・再構築必要（`rebuild_needed`）のとき、変更影響候補を返さず、`check-toc` と同じ検査結果
（`check-toc` の標準出力と同じ項目）を返す。`changed_documents` と `guidance` は持たない。

[ToC]が最新（`up_to_date`）のとき、次を返す。

- `status`: `up_to_date`
- `changed_documents`: 変更された文書の配列。要素は `doc_link_id`・`path` と、直接の参照元の配列 `referrers`。
  各参照元は、参照元の `source_doc_id`・`source_path`・`line`（1 始まり）・`definition`（参照記述）・`label`・
  `link_path`・`fragment`、参照先の `target_dlid`・`target_kind`（`document`・`section`）・`target_section_id`・
  `target_heading`、title に記録した[内容ハッシュ] `recorded_hash`（記録なしは `null`）、参照先の[現在ハッシュ]
  `current_hash` を持つ。異なる参照が無いときは空の配列である
- `scope`: 検査範囲。`target`（対象指定）・`toc_key`・`toc_version`（[確定 ToC]の版）・`scanned_documents`（参照を
  調べた参照元の文書）・`checked_at`（時点）・`note`（走査した範囲に限られること）
- `excluded`・`problems`・`warnings`: `check-toc` と同じ意味
- `guidance`: 検出後にすべきことの案内（自然文の配列）

## 仕様の解釈

- 変更影響候補があっても、操作は完了しているので終了コードは 0 である
- 列挙・[ToC]の鮮度の判定のどちらかを完了できなかったとき（判定不能、参照元を読めない、[ToC]と現物の食い違い、など）は、
  エラーの JSON と終了コード 1 を返し、変更影響候補を返さない。判定不能を、最新・古いのどちらにも読み替えない
- 列挙の規則と解釈は `impact_candidates` の module docstring に従う

## 終了コード

| code | 意味                                                                                           |
| ---- | ---------------------------------------------------------------------------------------------- |
| 0    | 検査が完了した（[ToC]が古い・未構築で候補を返さない場合と、変更影響候補が 0 件以上の場合を含む） |
| 1    | 区別のないエラー（対象指定の拒否、判定不能、参照元を読めない、など）                           |
| 2    | 引数を受理できない（`argparse`）                                                               |
"""

import argparse
import os
import sys
from pathlib import Path

# 共通モジュールは、プラグイン直下の scripts/（このファイルの 3 つ上の scripts/）にある。
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import impact_candidates  # noqa: E402
from clock import utc_now  # noqa: E402
import script_output  # noqa: E402
import target_spec  # noqa: E402
import toc_check  # noqa: E402

GUIDANCE_IMPACT = (
    "変更箇所と参照元の文書を読み、参照元の修正が必要かを[プロジェクト管理 AI]が判断する。必要なら参照元を直し、"
    "確かめた参照の title に参照先の[現在ハッシュ]（`current_hash`）を書く。確かめていない参照の title は書き換えない。"
    "書いたあとは `check-impact` をもう一度実行し、`changed_documents` が空になるまで繰り返す"
)
NOTE_SCOPE = (
    "参照元は、[確定 ToC]の参照関係から把握した、走査した範囲の文書に限られる。"
    "範囲の外の文書に参照元が無いことは意味しない"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-root", default=os.getcwd())
    target_spec.add_target_arguments(parser)
    return parser


def _impact_output(check: toc_check.TocCheck, root: Path) -> dict:
    checked_at = utc_now()
    result = impact_candidates.enumerate_impact(root, check.toc_key)
    guidance = [GUIDANCE_IMPACT] if result.changed_documents else []
    return {
        "status": check.status,
        "changed_documents": [d.to_dict() for d in result.changed_documents],
        "scope": {
            "target": check.target_spec,
            "toc_key": result.toc_key,
            "toc_version": result.toc_version,
            "scanned_documents": list(result.scanned_documents),
            "checked_at": checked_at,
            "note": NOTE_SCOPE,
        },
        "excluded": [e.to_dict() for e in check.excluded],
        "problems": list(check.problems),
        "warnings": list(check.warnings),
        "guidance": guidance,
    }


def execute(args: argparse.Namespace) -> int:
    root = Path(os.path.abspath(args.project_root))
    try:
        spec = target_spec.parse_namespace(args, root)
    except target_spec.TargetSpecError as exc:
        return script_output.emit_error(exc.errors)

    toc_key = spec.key if spec.mode == target_spec.MODE_TARGETS else None
    check = toc_check.check_toc(root, toc_key, spec)
    if check.status == toc_check.STATUS_UNDETERMINABLE:
        return script_output.emit_error(
            ["[ToC]の鮮度を判定できないので、変更影響候補を返さない"]
            + [cause.describe() for cause in check.causes]
        )
    if check.status != toc_check.STATUS_UP_TO_DATE:
        return script_output.emit_result(check.to_dict())
    try:
        output = _impact_output(check, root)
    except impact_candidates.ImpactFailure as failure:
        return script_output.emit_error(["変更影響候補を列挙できない"] + failure.errors)
    return script_output.emit_result(output)


def main(argv: list[str] | None = None) -> int:
    return execute(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
