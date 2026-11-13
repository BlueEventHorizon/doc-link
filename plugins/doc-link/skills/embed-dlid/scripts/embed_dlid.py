# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "markdown-it-py>=4.2.0",
# ]
# ///
"""対象文書へ[DLID]を付与する（embed-dlid の入口 script）。

利用者の文書へ書き込む唯一の入口である。書き込むのは[DLID]だけで（frontmatter の `doc_link_id` と、見出しの
行の末尾）、管理状態（`.doc-link/`）は書き換えない。対象は `index-docs` と同じ `--key` と[Index 対象指定]
（`--paths`・`--dirs`・`--exclude`・`--all` など）で決め、引数の検証と展開は共通モジュール `target_spec` を使う。
付与計画は `embed_plan`、書き込みと検証・取消しは `dlid_writer`、遷移のガードは `embed_state_machine` を使う。

## 呼び出し方

2 つのサブコマンドに分ける。利用者に確認するのは、重複する[DLID]の原本の確定だけであり、確認は SKILL が行う。
script は確認せず、AI が JSON を組み立てない。

- `plan <対象指定の引数>`: 付与計画を作る。何も書き込まない。重複する[DLID]があれば、すべての該当箇所と原本の
  候補を返す（状態は `原本確認待ち`）。重複が無い、または原本が決まっていれば、状態は `計画確定` である
- `apply <対象指定の引数> [--origin DLID PATH KIND LINE]...`: 付与計画を作り、書き込み、検証する。
  `--origin` は重複した[DLID]の原本の指定で、重複ごとに 1 回渡す。`DLID` は重複した値、`PATH`・`KIND`・`LINE` は
  原本とする箇所である。`KIND` は `document`（`doc_link_id`）か `section`（見出しの行の末尾）、`LINE` は見出しの
  行番号（1 始まり。`document` は `-`）。`plan` の出力の `origin_args` が、そのまま渡せる 4 つの値を持つ。
  原本の指定を求める重複が残るとき、何も書き込まず、終了コード 3 で返す

`--project-root` はプロジェクトルート（既定は現在のディレクトリ）。対象指定のパスは、ここからの相対パスである。

`apply` の各実行は `開始` から始まる。失敗した実行の再実行（E-07）は、新しい実行として文書を読み直し、
書き込み済みの[DLID]を既存の[DLID]として付与計画を作り直す。

## 標準出力

終了コード 0 のとき結果の JSON、それ以外（2 を除く）のときエラーの JSON（`errors` は自然文の配列）を返す。
終了コード 3・4 のエラーの JSON は、`errors` に加えて、利用者へ返す情報（`duplicates`、`written`、`failed`）を持つ。
位置の行番号はすべて 1 始まりである。

## 終了コード

| code | 意味                                                                                                                         |
| ---- | ---------------------------------------------------------------------------------------------------------------------------- |
| 0    | 操作が完了した（`plan` は計画を返した。`apply` は全対象を書き込み、検証した。対象が 0 件でも完了である）                     |
| 1    | 区別のないエラー（対象指定の拒否、文書・管理状態を読めない、原本の指定が不正）                                               |
| 2    | 引数を受理できない（`argparse`）                                                                                             |
| 3    | `apply` で、原本の指定を求める重複が残っているので、何も書き込まなかった                                                     |
| 4    | `apply` で、書き込めなかった文書がある（検証を通って書き込んだ[DLID]は戻らず、`written` に発行済みとして含む）               |
"""

import argparse
import os
import sys
from pathlib import Path

# 共通モジュールは、プラグイン直下の scripts/（このファイルの 3 つ上の scripts/）にある。
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import dlid_writer  # noqa: E402
import embed_plan  # noqa: E402
import embed_state_machine as sm  # noqa: E402
import script_output  # noqa: E402
import target_spec  # noqa: E402
from dlid import KIND_DOCUMENT, KIND_SECTION, DlidLocation  # noqa: E402
from markdown_reader import is_dlid  # noqa: E402

EXIT_AWAITING_ORIGIN = 3
EXIT_NOT_WRITTEN = 4

_KINDS = (KIND_DOCUMENT, KIND_SECTION)


class InputRejected(Exception):
    """引数・原本の指定を受理できない。`errors` に自然文の理由を持つ。"""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("plan", "付与計画を作る（何も書き込まない）"),
        ("apply", "付与計画を作り、[DLID]を書き込み、検証する"),
    ):
        sub = subcommands.add_parser(name, help=help_text)
        sub.add_argument("--project-root", default=os.getcwd())
        target_spec.add_target_arguments(sub)
        if name == "apply":
            sub.add_argument(
                "--origin",
                nargs=4,
                action="append",
                default=None,
                metavar=("DLID", "PATH", "KIND", "LINE"),
                help="重複した[DLID]の原本の指定（重複ごとに 1 回）",
            )
    return parser


def _parse_origins(root: Path, raw: list[list[str]] | None) -> dict[str, tuple]:
    """`--origin` を、重複した[DLID]の値から（パス、種別、行）への対応にする。"""
    origins: dict[str, tuple] = {}
    errors: list[str] = []
    for dlid_value, path, kind, line in raw or []:
        if not is_dlid(dlid_value):
            errors.append(f"--origin の DLID が[DLID]の形式でない: {dlid_value}")
            continue
        if kind not in _KINDS:
            errors.append(f"--origin の KIND は document か section である: {kind}")
            continue
        number: int | None
        if kind == KIND_DOCUMENT:
            if line != "-":
                errors.append(f"--origin の document の LINE は - である: {line}")
                continue
            number = None
        else:
            if not line.isdigit() or int(line) < 1:
                errors.append(
                    f"--origin の section の LINE は 1 以上の整数である: {line}"
                )
                continue
            number = int(line) - 1
        if dlid_value in origins:
            errors.append(f"同じ[DLID]の原本が複数指定された: {dlid_value}")
            continue
        try:
            normalized = target_spec.normalize_path(str(root), path)
        except target_spec.TargetSpecError as exc:
            errors.extend(exc.errors)
            continue
        origins[dlid_value] = (normalized, kind, number)
    if errors:
        raise InputRejected(errors)
    return origins


def _resolve_origins(
    plan: embed_plan.EmbedPlan, origins: dict[str, tuple]
) -> dict[str, DlidLocation]:
    """原本の指定を、計画が報告した重複の箇所（`DlidLocation`）へ対応させる。"""
    reports = {report.dlid: report for report in plan.duplicates}
    resolved: dict[str, DlidLocation] = {}
    errors: list[str] = []
    for dlid_value, (path, kind, line) in origins.items():
        report = reports.get(dlid_value)
        if report is None:
            errors.append(f"重複していない[DLID]への原本の指定: {dlid_value}")
            continue
        matches = [
            location
            for location in report.locations
            if (location.path, location.kind, location.line) == (path, kind, line)
        ]
        if not matches:
            errors.append(
                f"重複の箇所のどれにも当たらない原本の指定: {dlid_value} {path} {kind}"
            )
            continue
        resolved[dlid_value] = matches[0]
    if errors:
        raise InputRejected(errors)
    return resolved


def _location_to_dict(dlid_value: str, location: DlidLocation) -> dict:
    line = None if location.line is None else location.line + 1
    return {
        "path": location.path,
        "kind": location.kind,
        "line": line,
        "heading": location.heading_text,
        "origin_args": [
            dlid_value,
            location.path,
            location.kind,
            "-" if line is None else str(line),
        ],
    }


def _duplicate_to_dict(report: embed_plan.DuplicateReport) -> dict:
    return {
        "dlid": report.dlid,
        "locations": [_location_to_dict(report.dlid, loc) for loc in report.locations],
        "recorded_paths": list(report.recorded_paths),
        "candidates": [
            _location_to_dict(report.dlid, loc) for loc in report.candidates
        ],
        "origin": (
            None
            if report.origin is None
            else _location_to_dict(report.dlid, report.origin)
        ),
        "implied_by_reissue": report.implied_by_reissue,
        "needs_origin": report.origin is None and not report.implied_by_reissue,
    }


def _item_to_dict(item: embed_plan.IssueItem) -> dict:
    position = item.position
    line = (
        position.start_line + 1
        if isinstance(position, embed_plan.HeadingPosition)
        else None
    )
    return {
        "path": item.path,
        "kind": item.kind,
        "reason": item.reason,
        "replaces": item.replaces,
        "line": line,
    }


def _written_to_dict(item: dlid_writer.WrittenItem) -> dict:
    return {
        "path": item.path,
        "kind": item.kind,
        "dlid": item.dlid,
        "replaced": item.replaced,
        "line": item.line,
        "heading": item.heading,
    }


def _failure_to_dict(failure: dlid_writer.DocumentFailure) -> dict:
    return {
        "path": failure.path,
        "location": failure.location,
        "cause": failure.cause,
        "reverted": failure.reverted,
    }


def _emit(payload: dict, code: int) -> int:
    """結果・エラーの JSON を `script_output` の形式で出し、指定の終了コードを返す。

    `script_output.emit_error` は `errors` だけを出して 1 を返すので、終了コード 3・4 で追加の情報
    （`duplicates`・`written`・`failed`）を返すために、同じ書式の `emit_result` を使い、返り値は使わない。
    """
    script_output.emit_result(payload)
    return code


def _fail_run(run: sm.EmbedRun, errors: list[str], extra: dict | None = None) -> dict:
    payload = {"errors": errors, "state": run.state}
    payload.update(extra or {})
    return payload


def execute(args: argparse.Namespace) -> int:
    root = Path(os.path.abspath(args.project_root))
    run = sm.EmbedRun()

    try:
        spec = target_spec.parse_namespace(args, root)
        origins = _parse_origins(root, getattr(args, "origin", None))
    except (target_spec.TargetSpecError, InputRejected) as exc:
        run.apply(sm.EVENT_FAIL, sm.Facts(stage_failed=True))
        return _emit(_fail_run(run, exc.errors), script_output.EXIT_ERROR)

    expansion = target_spec.expand(spec, root)
    run.apply(sm.EVENT_EXPAND, sm.Facts(scope_expanded=True))

    try:
        plan = embed_plan.build_plan(root, expansion.files)
        if origins:
            plan = embed_plan.build_plan(
                root, expansion.files, origins=_resolve_origins(plan, origins)
            )
    except embed_plan.PlanFailure as exc:
        run.apply(sm.EVENT_FAIL, sm.Facts(stage_failed=True))
        return _emit(
            _fail_run(
                run,
                [f"{problem.path}: {problem.reason}" for problem in exc.problems],
            ),
            script_output.EXIT_ERROR,
        )
    except InputRejected as exc:
        run.apply(sm.EVENT_FAIL, sm.Facts(stage_failed=True))
        return _emit(_fail_run(run, exc.errors), script_output.EXIT_ERROR)

    duplicates_found = bool(plan.duplicates)
    run.apply(
        sm.EVENT_RECONCILE,
        sm.Facts(reconciled=True, duplicates_found=duplicates_found),
    )
    if duplicates_found and plan.confirmed:
        run.apply(sm.EVENT_CONFIRM_ORIGIN, sm.Facts(origin_confirmed=True))

    common = {
        "problems": [problem.to_dict() for problem in expansion.problems],
        "warnings": list(expansion.warnings),
        "duplicates": [_duplicate_to_dict(report) for report in plan.duplicates],
    }

    if args.command == "plan":
        return _emit(
            {
                "state": run.state,
                "needs_origin": not plan.confirmed,
                "items": [_item_to_dict(item) for item in plan.items],
                **common,
            },
            script_output.EXIT_OK,
        )

    if not plan.confirmed:
        run.apply(sm.EVENT_FAIL, sm.Facts(origin_abandoned=True))
        return _emit(
            _fail_run(
                run,
                [
                    "原本の指定を求める重複が残っているので、何も書き込まなかった: "
                    + ", ".join(report.dlid for report in plan.unresolved)
                ],
                common,
            ),
            EXIT_AWAITING_ORIGIN,
        )

    result = dlid_writer.apply_plan(root, plan)
    written = [_written_to_dict(item) for item in result.written]
    if result.succeeded:
        run.apply(sm.EVENT_WRITE, sm.Facts(written_and_verified=True))
        return _emit(
            {"state": run.state, "written": written, **common}, script_output.EXIT_OK
        )

    run.apply(sm.EVENT_FAIL, sm.Facts(documents_unwritten=True))
    return _emit(
        _fail_run(
            run,
            [
                f"{failure.path}: {failure.location}: {failure.cause}"
                for failure in result.failed
            ],
            {
                "written": written,
                "failed": [_failure_to_dict(failure) for failure in result.failed],
                **common,
            },
        ),
        EXIT_NOT_WRITTEN,
    )


def main(argv: list[str] | None = None) -> int:
    return execute(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
