# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "markdown-it-py>=4.2.0",
# ]
#
# [tool.uv]
# exclude-newer = "3 days"
# ///
"""対象文書の[DLID]を検査する（check-dlid の入口 script）。

[Index 対象文書]と管理状態（`.doc-link/`）へは書き込まない。読むだけである。書くのは、結果の明細の作業ファイル
（`.temp/doc-link/check-dlid/`）だけである。[文書 ID]の無い文書、[セクション ID]の無い見出し、重複する[DLID]を
報告し、検出があれば `embed-dlid` の実行を案内する。
対象は `index-docs` と同じ `--key` と[Index 対象指定]（`--paths`・`--dirs`・`--exclude`・`--all` など）で決め、
引数の検証と展開は共通モジュール `target_spec` を使う。検出は `embed_plan.build_plan`（付与計画。`embed-dlid`
が書き込みの前に使うものと同じ）の結果から取り出す。検出の規則を別に実装しない。

## 呼び出し方

`check_dlid.py [--project-root DIR] <対象指定の引数>`。`--project-root` の既定は現在のディレクトリで、
対象指定のパスはここからの相対パスである。

## 標準出力

終了コード 0 のとき結果の JSON、1 のときエラーの JSON（`errors` は自然文の配列）を返す。標準出力は件数までで、
検出事項の明細は明細ファイルへ書く（要件 D-061。[DLID]の無い見出しが多くても、標準出力の大きさが変わらないように
するため）。

- `clean`: 検出事項が 1 つも無く、指定された対象をすべて検査できたとき真。`problems` に、検査できなかった対象
  （読めないディレクトリ・存在しない指定・除外名のディレクトリの指定など）があるときは、偽である。
  利用者が `--exclude` で自分で除外したもの（`excluded`）は、検査の失敗ではないので、影響しない
- `counts`: `missing_document_id`（[文書 ID]が無い文書）・`missing_section_id`（[セクション ID]の無い見出し）・
  `duplicates`（重複する[DLID]）・`unclosed_frontmatter`（frontmatter の閉じる行が無い文書）の件数
- `problems`・`warnings`: 対象指定の展開が報告した、存在しない・Markdown でない指定、読めないディレクトリ、
  除外名のディレクトリの指定（`fixed_excluded`）など。残りの対象は検査する
- `guidance`: 検出後にすべきことの案内（自然文の配列）
- `detail_path`: 明細ファイルの絶対パス。検出が 0 件でも書く

## 明細ファイル

`.temp/doc-link/check-dlid/detail-<符号化した[ToC 識別キー]>.json`。同じ[ToC 識別キー]（`--all` と引数なしは `all`）
の次の実行が置き換える。行番号は 1 始まり。

- `missing_document_id`: [文書 ID]が無い文書。`path`、`unclosed_frontmatter`
- `missing_section_id`: [セクション ID]の無い見出し。`path`、`line`、`heading`
- `duplicates`: 重複する[DLID]。`dlid`、`locations`（すべての該当箇所。`path`・`kind`・`line`・`heading`）、
  `recorded_paths`（管理状態に記録されたパス）、`candidates`（記録されたパスと一致する原本の候補）

## 仕様の解釈

- 検出事項があっても、検査は完了している。終了コードは 0 である
- `doc_link_id` の欠落・null・空・単一文字列でない・認識できない値は、すべて「[文書 ID]が存在しない」として
  `missing_document_id` に入れる。形式不正という別の分類を作らない
- 閉じる行の無い frontmatter は、`markdown_reader` では frontmatter が無いものとして読まれ、`missing_document_id`
  に入る。先頭の空でない行が `---` のそのような文書には `unclosed_frontmatter` を真にして、`embed-dlid`
  がその文書へ書き込めない（書き込み失敗として報告される）ことを分かるようにする。分類は増やさない
- 重複には、`embed_plan` が持つ原本の候補（`candidates`）を添える。原本は決めない。確定は `embed-dlid` で
  利用者が行う
- 文書・管理状態を読めないときは、既定値で代替せず、`PlanFailure` の `kind` を保ってエラーにする
- 明細ファイルを書けないときは、件数だけを返さず、エラーにする

## 終了コード

| code | 意味                                                                                                         |
| ---- | ------------------------------------------------------------------------------------------------------------ |
| 0    | 検査が完了した（検出事項の有無に依らない。対象が 0 件でも完了である）                                        |
| 1    | 区別のないエラー（対象指定の拒否、文書・管理状態を読めない、明細ファイルを書けない）                         |
| 2    | 引数を受理できない（`argparse`）                                                                             |
"""

import argparse
import os
import sys
from pathlib import Path

# 共通モジュールは、プラグイン直下の scripts/（このファイルの 3 つ上の scripts/）にある。
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import detail_file  # noqa: E402
import embed_plan  # noqa: E402
import script_output  # noqa: E402
import target_spec  # noqa: E402
from dlid import KIND_DOCUMENT, KIND_SECTION, DlidLocation  # noqa: E402
from markdown_reader import has_unclosed_frontmatter, read_document  # noqa: E402

SKILL = "check-dlid"

GUIDANCE_DETAIL = (
    "検出事項の明細（文書・行・見出し、重複の該当箇所と原本の候補）は、明細ファイル（`detail_path`）にある。"
    "付与は `embed-dlid` が同じ検出を行って書き込むので、付与のために明細を読む必要は無い"
)
GUIDANCE_UNCHECKED = (
    "`problems` の対象は検査できていない。指定や権限を直して、もう一度実行する"
    "（検出事項が無くても、検査できていない対象があるので、[DLID]が揃っているとは言えない）"
)
GUIDANCE_UNCLOSED = (
    "`unclosed_frontmatter` が真の文書は、frontmatter の閉じる行が無いので、"
    "`embed-dlid` は書き込めない。先に frontmatter を直す"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-root", default=os.getcwd())
    target_spec.add_target_arguments(parser)
    return parser


def _location_to_dict(location: DlidLocation) -> dict:
    return {
        "path": location.path,
        "kind": location.kind,
        "line": None if location.line is None else location.line + 1,
        "heading": location.heading_text,
    }


def _duplicate_to_dict(report: embed_plan.DuplicateReport) -> dict:
    return {
        "dlid": report.dlid,
        "locations": [_location_to_dict(loc) for loc in report.locations],
        "recorded_paths": list(report.recorded_paths),
        "candidates": [_location_to_dict(loc) for loc in report.candidates],
    }


def detect(root: Path, files: list[str]) -> tuple[dict, dict]:
    """対象文書を検査し、（標準出力へ返す要約、明細ファイルへ書く全件）を返す。

    `embed_plan.PlanFailure` は呼び出し側へ伝える。
    """
    plan = embed_plan.build_plan(root, files)
    documents = {
        path: read_document((root / path).read_bytes().decode("utf-8"))
        for path in dict.fromkeys(files)
    }

    missing_documents: list[dict] = []
    missing_sections: list[dict] = []
    for item in plan.items:
        if item.reason != embed_plan.REASON_MISSING:
            continue
        document = documents[item.path]
        if item.kind == KIND_DOCUMENT:
            missing_documents.append(
                {
                    "path": item.path,
                    "unclosed_frontmatter": has_unclosed_frontmatter(document.lines),
                }
            )
        elif item.kind == KIND_SECTION:
            start = item.position.start_line
            heading = next(h for h in document.headings if h.start_line == start)
            missing_sections.append(
                {"path": item.path, "line": start + 1, "heading": heading.text}
            )

    duplicates = [_duplicate_to_dict(report) for report in plan.duplicates]
    unclosed = sum(1 for entry in missing_documents if entry["unclosed_frontmatter"])
    found = bool(missing_documents or missing_sections or duplicates)
    guidance: list[str] = []
    if found:
        guidance.append(GUIDANCE_DETAIL)
    if unclosed:
        guidance.append(GUIDANCE_UNCLOSED)

    summary = {
        "clean": not found,
        "counts": {
            "missing_document_id": len(missing_documents),
            "missing_section_id": len(missing_sections),
            "duplicates": len(duplicates),
            "unclosed_frontmatter": unclosed,
        },
        "guidance": guidance,
    }
    detail = {
        "missing_document_id": missing_documents,
        "missing_section_id": missing_sections,
        "duplicates": duplicates,
    }
    return summary, detail


def execute(args: argparse.Namespace) -> int:
    root = Path(os.path.abspath(args.project_root))
    try:
        spec = target_spec.parse_namespace(args, root)
    except target_spec.TargetSpecError as exc:
        return script_output.emit_error(exc.errors)

    expansion = target_spec.expand(spec, root)
    try:
        result, detail = detect(root, list(expansion.files))
    except embed_plan.PlanFailure as exc:
        return script_output.emit_error(
            [f"{problem.path}: {problem.reason}" for problem in exc.problems]
        )
    result["problems"] = [problem.to_dict() for problem in expansion.problems]
    result["warnings"] = list(expansion.warnings)
    if any(
        problem.reason != target_spec.PROBLEM_EXCLUDED for problem in expansion.problems
    ):
        result["clean"] = False
        result["guidance"].append(GUIDANCE_UNCHECKED)
    return detail_file.emit_with_detail(
        root, SKILL, target_spec.toc_key_of(spec), result, detail
    )


def main(argv: list[str] | None = None) -> int:
    return execute(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
