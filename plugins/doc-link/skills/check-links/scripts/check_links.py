# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "markdown-it-py>=4.2.0",
# ]
#
# [tool.uv]
# exclude-newer = "3 days"
# ///
"""対象文書の参照を検査して、検出事項を報告する（check-links の入口 script）。

何も書き込まない。対象文書・管理状態（`.doc-link/`）のどちらも読み書きせず、リンクを直すのは
[プロジェクト管理 AI]である。対象は `index-docs` と同じ `--key` と[Index 対象指定]で決め、引数の検証と展開は
共通モジュール `target_spec` を使う。[正式な参照]の抽出は `references`、指定ディレクトリの実走査による検査は
`reference_check`、文書の解析は `markdown_reader` を使い、このファイルは抽出・走査・分類を再実装しない。

## 呼び出し方

`check_links.py [--project-root DIR] [--key KEY] <対象指定の引数>`。`--project-root` はプロジェクトルート
（既定は現在のディレクトリ）で、対象指定のパスはここからの相対パスである。

## 参照元

参照元は、対象の[Index 対象リスト]のすべての文書である（[文書 ID]の有無に関わらず、リンクを持つ文書）。
読めない（存在しない・UTF-8 として復号できない）文書は、握りつぶさず、`unreadable_documents` に残して検査を続ける。

## 検出事項（`findings` の `category`）

[正式な参照]（リファレンスリンクの定義で、title の最後の語が[DLID]）の、`reference_check` の分類から導く。
一致（`match`）は異常ではないので、件数（`summary.matched_references`）だけを返す。

- `path_mismatch`: [DLID]とパスの不一致。`current_path` に実走査で確認できた現在のパス
- `fragment_mismatch`: フラグメントが参照先のセクションへ解決しない。`current_anchor` に、その[DLID]のセクションへ
  届く現在のアンカー（title が文書の[DLID]のときは `null`）
- `missing_section`: 存在しないセクションへの参照（下の解釈を参照）
- `absent`: 指定ディレクトリ内に見つからない。`absent_reason` に理由の区別
  （`not_found`・`directory_missing`・`directory_unreadable`・`not_directory`・`directory_excluded`）
- `duplicate`: 同じ[DLID]が複数見つかった。`duplicate_paths` に見つけたもの
- `unresolved`: リンク先パスを参照元から解決できない。`unresolved_reason` は `outside_root`・`not_markdown`

[正式な参照]でないリンク

- `link_without_dlid`: `doc_link_id` を持つ Markdown を指しているが、title に[DLID]の無いリンク（リファレンスリンクの
  定義・インラインリンクのどちらも）。`kind` は `definition`・`inline`。title に書く値 `suggested_title`
  （`<内容ハッシュ> DLID-…`）を添える。値は検査時点の参照先の現物から決め（管理状態は読まない）、フラグメントが
  見出しから生成されるアンカーに解決すればそのセクションの[セクション ID]と内容ハッシュ、フラグメントが無いか明示
  アンカーに解決すれば参照先文書の[文書 ID]と内容ハッシュである。どちらにも解決しないとき（`fragment_unresolved`）と、
  解決した見出しに[DLID]が無いとき（`heading_without_dlid`）は、`suggested_title` を添えず
  `suggested_title_unavailable_reason` に理由を添える。値を文書へ書くのは[プロジェクト管理 AI]である
- `inline_link_with_dlid`: [DLID]入りの title を持つが、リファレンスリンクの定義でないリンク（インラインリンク）

検査できなかったもの

- `unverified_links`: `link_without_dlid` の判定のためにリンク先の文書を読めなかったリンク（判定できなかったもの）
- `unreadable_documents`: 読めなかった参照元の文書

各検出事項は、参照元のパス `source_path`・行 `line`（1 始まり）・リンク先 `target`（記載されたパスとフラグメント）を持つ。
[正式な参照]の検出事項は、加えて `dlid`・`recorded_hash`（title に記録した[内容ハッシュ]。記録なしは `null`）・
`resolved_path` を持つ。title の記録と参照先の[現在ハッシュ]の比較は check-impact の仕事で、ここではしない。
検査範囲は `scope`（走査したディレクトリ `directories` と時点 `checked_at`）である。検出後の案内は `guidance`。

## 仕様の解釈（設計書が値や形式を定めていない点）

- 存在しないセクション: `reference_check` が `absent`（`not_found`）とした参照のうち、リンク先パスの文書が指定ディレクトリの
  実走査で見つかったものを `missing_section` にする。リンク先の文書が無いものは `absent` のままである。[DLID]が不在のとき、
  それが[文書 ID]か[セクション ID]かは見分けられない。リンク先の文書が存在するのにその[DLID]がどこにも無い、という
  DES-007 §4 の条件に当たるものを、まとめて `missing_section` とする。`target_doc_link_id` に、その文書の現在の
  `doc_link_id`（無ければ `null`）を添えて、文書の ID が書き換わった場合を見分けられるようにする
- `link_without_dlid` の対象外: スキーム付きの宛先、画像、autolink、HTML の `<a>`、リンク先のパスが空（同じ文書の
  フラグメントだけ）のリンク、プロジェクトルートの外に出るリンク、Markdown でない（拡張子が `.md` でない）リンク先、
  存在しない・ファイルでないリンク先。リンク先が `doc_link_id` を持つかは、リンク先の文書の frontmatter を読んで判定する
  （保存済みの管理状態は根拠にしない）。同じリンク先は 1 回だけ読む
- `inline_link_with_dlid` の対象外: スキーム付きの宛先、画像、autolink
- インラインリンクは、リファレンスリンクの定義の行を空行に置き換えた文書を `markdown_reader` で読んで得る（定義に依存する
  参照形式の利用は、定義が無いのでリンクにならず、インラインリンクだけが残る）。`line` は、そのリンクを含む段落などの
  開始行である。同じラベルの定義が複数ある文書では、2 つ目以降の定義が有効になるので、その利用はインラインリンクとして
  現れることがある
- リファレンスリンクの定義は、使われているかに関わらず、定義 1 つにつき 1 件として検査する
- 参照元の文書を読めない、リンク先の文書を読めないことは、終了コード 1 にせず結果に残す。検査できなかった範囲が
  利用者に見えるようにするためである。対象指定の拒否だけを終了コード 1 にする

## 標準出力

終了コード 0 のとき結果の JSON、それ以外（2 を除く）のときエラーの JSON（`errors` は自然文の配列）を返す。
検出事項があっても、検査を完了しているので終了コードは 0 である。

## 終了コード

| code | 意味                                                                                                  |
| ---- | ----------------------------------------------------------------------------------------------------- |
| 0    | 検査を完了した（検出事項の有無に関わらない。対象が 0 件でも完了である。読めない文書は結果に残す）     |
| 1    | 区別のないエラー（対象指定の拒否）                                                                    |
| 2    | 引数を受理できない（`argparse`）                                                                      |
"""

import argparse
import os
import posixpath
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# 共通モジュールは、プラグイン直下の scripts/（このファイルの 3 つ上の scripts/）にある。
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import reference_check  # noqa: E402
import script_output  # noqa: E402
import target_spec  # noqa: E402
from content_hash import (  # noqa: E402
    document_content_hash,
    is_record_word,
    section_content_hashes,
)
from markdown_reader import (  # noqa: E402
    MarkdownDocument,
    has_scheme,
    is_dlid,
    read_document,
    split_destination,
)
from references import extract_from_document  # noqa: E402

CATEGORY_PATH_MISMATCH = reference_check.STATUS_PATH_MISMATCH
CATEGORY_FRAGMENT_MISMATCH = reference_check.STATUS_FRAGMENT_MISMATCH
CATEGORY_MISSING_SECTION = "missing_section"
CATEGORY_ABSENT = reference_check.STATUS_ABSENT
CATEGORY_DUPLICATE = reference_check.STATUS_DUPLICATE
CATEGORY_UNRESOLVED = reference_check.STATUS_UNRESOLVED
CATEGORY_LINK_WITHOUT_DLID = "link_without_dlid"
CATEGORY_INLINE_LINK_WITH_DLID = "inline_link_with_dlid"

KIND_DEFINITION = "definition"
KIND_INLINE = "inline"

_GUIDANCE_FIX_LINKS = (
    "リンクを直すのは[プロジェクト管理 AI]である。パスの不一致には `current_path`、フラグメント不一致には"
    " `current_anchor` を使う。参照先が見つからない（`absent`・`missing_section`）場合は、移動か削除かを"
    "[プロジェクト管理 AI]が判断する"
)
_GUIDANCE_RESOLVE = (
    "title に DLID の無いリンク（`link_without_dlid`）には、検出事項の `suggested_title`（参照先の内容ハッシュと"
    ' DLID）を title に書く（`"<内容ハッシュ> DLID-…"`）。`suggested_title` が無いものは'
    " `suggested_title_unavailable_reason` に理由がある。インラインリンク（`inline_link_with_dlid`）は、"
    "リファレンスリンクの定義に書き換える"
)

REASON_FRAGMENT_UNRESOLVED = "fragment_unresolved"
REASON_HEADING_WITHOUT_DLID = "heading_without_dlid"
_GUIDANCE_INDEX = "リンクを直した後は `index-docs` を実行する"

_FORMAL_CATEGORIES = frozenset(
    {
        CATEGORY_PATH_MISMATCH,
        CATEGORY_FRAGMENT_MISMATCH,
        CATEGORY_MISSING_SECTION,
        CATEGORY_ABSENT,
        CATEGORY_DUPLICATE,
        CATEGORY_UNRESOLVED,
    }
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-root", default=os.getcwd())
    target_spec.add_target_arguments(parser)
    return parser


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _target(path: str, fragment: str | None) -> str:
    return path if fragment is None else f"{path}#{fragment}"


@dataclass
class _Targets:
    """リンク先の文書の `doc_link_id` を読む。同じリンク先は 1 回だけ読む。"""

    root: str

    def __post_init__(self) -> None:
        self._cache: dict[str, tuple[str, str | None]] = {}
        self._texts: dict[str, str] = {}

    def resolve(self, source: str, link_path: str) -> str | None:
        """参照元を基準にリンク先を解決する。ルートの外に出るときは `None`。"""
        link = unicodedata.normalize("NFC", link_path)
        if link.startswith("/"):
            return None
        target = posixpath.normpath(posixpath.join(posixpath.dirname(source), link))
        if target == ".." or target.startswith("../"):
            return None
        return target

    def doc_link_id(self, target: str) -> tuple[str, str | None]:
        """（状態、値）を返す。状態は `skip`（対象外）・`read`（値は `doc_link_id`、無ければ `None`）・
        `unreadable`（値は理由）。"""
        if target not in self._cache:
            self._cache[target] = self._read(target)
        return self._cache[target]

    def _read(self, target: str) -> tuple[str, str | None]:
        if not target_spec.is_markdown(target):
            return "skip", None
        absolute = os.path.join(self.root, target)
        if not os.path.isfile(absolute):
            return "skip", None
        try:
            text = Path(absolute).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            return "unreadable", str(error)
        self._texts[target] = text
        return "read", read_document(text).frontmatter.doc_link_id

    def suggested_title(self, target: str, fragment: str | None, doc_id: str) -> dict:
        """title に書く値を、検査時点の現物から決める（DES-007 §1）。`doc_link_id` を読めたリンク先に使う。

        フラグメントが見出しから生成されるアンカーに解決すればそのセクションの値、無いか明示アンカーに
        解決すれば文書の値。どちらにも解決しないときと、解決した見出しに DLID が無いときは、値を返さず理由を返す。
        """
        text = self._texts[target]
        document = read_document(text)
        if fragment is not None:
            for index, heading in enumerate(document.headings):
                if heading.anchor != fragment:
                    continue
                if heading.section_id is None:
                    return {
                        "suggested_title_unavailable_reason": REASON_HEADING_WITHOUT_DLID
                    }
                value = section_content_hashes(text)[index]
                return {"suggested_title": f"{value} {heading.section_id}"}
            if fragment not in reference_check.explicit_anchors(text):
                return {
                    "suggested_title_unavailable_reason": REASON_FRAGMENT_UNRESOLVED
                }
        return {"suggested_title": f"{document_content_hash(text)} {doc_id}"}


def _inline_links(document: MarkdownDocument):
    """リファレンスリンクの定義の行を空行にして読み直し、定義に依存しないリンクだけを得る。"""
    lines = list(document.lines)
    for definition in document.references:
        for index in range(definition.start_line, definition.end_line):
            lines[index] = "\n"
    return [link for link in read_document("".join(lines)).links if link.kind == "link"]


def _formal_finding(
    result: reference_check.ReferenceCheckResult,
    scanner: reference_check.DirectoryScanner,
) -> dict | None:
    """[正式な参照]の検査結果を検出事項にする。一致は `None`。"""
    if result.status == reference_check.STATUS_MATCH:
        return None
    reference = result.reference
    category = result.status
    finding = {
        "category": category,
        "source_path": result.source_path,
        "line": reference.line + 1,
        "target": _target(reference.path, reference.fragment),
        "dlid": reference.dlid,
        "recorded_hash": reference.recorded_hash,
        "resolved_path": result.resolved_path,
    }
    if category == CATEGORY_PATH_MISMATCH:
        finding["current_path"] = result.current_path
        finding["target_kind"] = result.target_kind
    elif category == CATEGORY_FRAGMENT_MISMATCH:
        finding["fragment"] = reference.fragment
        finding["current_anchor"] = result.current_anchor
        finding["target_kind"] = result.target_kind
    elif category == CATEGORY_DUPLICATE:
        finding["duplicate_paths"] = list(result.duplicate_paths)
    elif category == CATEGORY_UNRESOLVED:
        finding["unresolved_reason"] = result.unresolved_reason
    elif category == CATEGORY_ABSENT:
        finding["absent_reason"] = result.absent_reason
        finding["unreadable_files"] = list(result.unreadable_files)
        scanned = scanner.scan(result.directory)
        document = scanned.documents.get(result.resolved_path)
        if result.absent_reason == reference_check.ABSENT_NOT_FOUND and document:
            finding["category"] = CATEGORY_MISSING_SECTION
            finding["target_doc_link_id"] = document.doc_id
            del finding["absent_reason"]
    return finding


def _check_source(
    source: str,
    document: MarkdownDocument,
    *,
    scanner: reference_check.DirectoryScanner,
    targets: _Targets,
    checked_at: str,
    findings: list[dict],
    unverified: list[dict],
    directories: set[str],
) -> int:
    """参照元 1 文書を検査する。一致した[正式な参照]の数を返す。

    この文書で見つけた検出事項と未検証には、参照元の[文書 ID]（`source_doc_id`。持たなければ `None`）
    を添える（要件 FR-010 の通知項目）。
    """
    first_finding, first_unverified = len(findings), len(unverified)
    matched = _check_references(
        source,
        document,
        scanner=scanner,
        targets=targets,
        checked_at=checked_at,
        findings=findings,
        unverified=unverified,
        directories=directories,
    )
    source_doc_id = document.frontmatter.doc_link_id
    for item in findings[first_finding:] + unverified[first_unverified:]:
        item["source_doc_id"] = source_doc_id
    return matched


def _check_references(
    source: str,
    document: MarkdownDocument,
    *,
    scanner: reference_check.DirectoryScanner,
    targets: _Targets,
    checked_at: str,
    findings: list[dict],
    unverified: list[dict],
    directories: set[str],
) -> int:
    """参照元 1 文書の参照を検査する。一致した[正式な参照]の数を返す。"""
    matched = 0
    for reference in extract_from_document(document):
        result = reference_check.check_reference(
            scanner.root, source, reference, checked_at=checked_at, scanner=scanner
        )
        if result.directory is not None:
            directories.add(result.directory)
        finding = _formal_finding(result, scanner)
        if finding is None:
            matched += 1
        else:
            findings.append(finding)

    candidates = [
        (KIND_DEFINITION, d.path, d.fragment, d.href, d.title, d.start_line)
        for d in document.references
        if d.dlid is None
    ]
    for link in _inline_links(document):
        path, fragment = split_destination(link.href)
        candidates.append(
            (KIND_INLINE, path, fragment, link.href, link.title or "", link.line)
        )

    for kind, path, fragment, href, title, line in candidates:
        if has_scheme(href):
            continue
        words = title.split()
        if words and is_dlid(words[-1]):
            if kind == KIND_INLINE:
                recorded = words[-2] if len(words) >= 2 else None
                findings.append(
                    {
                        "category": CATEGORY_INLINE_LINK_WITH_DLID,
                        "source_path": source,
                        "line": line + 1,
                        "target": _target(path, fragment),
                        "dlid": words[-1],
                        "recorded_hash": recorded if is_record_word(recorded) else None,
                    }
                )
            continue
        if path == "":
            continue
        resolved = targets.resolve(source, path)
        if resolved is None:
            continue
        state, value = targets.doc_link_id(resolved)
        entry = {
            "source_path": source,
            "line": line + 1,
            "target": _target(path, fragment),
            "resolved_path": resolved,
        }
        if state == "unreadable":
            unverified.append({**entry, "kind": kind, "reason": value})
        elif state == "read" and value is not None:
            findings.append(
                {
                    **entry,
                    "category": CATEGORY_LINK_WITHOUT_DLID,
                    "kind": kind,
                    "target_doc_link_id": value,
                    **targets.suggested_title(resolved, fragment, value),
                }
            )
    return matched


def _guidance(findings: list[dict]) -> list[str]:
    categories = {finding["category"] for finding in findings}
    guidance = []
    if categories & _FORMAL_CATEGORIES:
        guidance.append(_GUIDANCE_FIX_LINKS)
    if categories & {CATEGORY_LINK_WITHOUT_DLID, CATEGORY_INLINE_LINK_WITH_DLID}:
        guidance.append(_GUIDANCE_RESOLVE)
    if guidance:
        guidance.append(_GUIDANCE_INDEX)
    return guidance


def execute(args: argparse.Namespace) -> int:
    root = Path(os.path.abspath(args.project_root))
    try:
        spec = target_spec.parse_namespace(args, root)
    except target_spec.TargetSpecError as exc:
        return script_output.emit_error(exc.errors)

    expansion = target_spec.expand(spec, root)
    scanner = reference_check.DirectoryScanner(root)
    targets = _Targets(str(root))
    checked_at = _now()

    findings: list[dict] = []
    unverified: list[dict] = []
    unreadable: list[dict] = []
    directories: set[str] = set()
    matched = 0
    for source in expansion.files:
        try:
            text = (root / source).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            unreadable.append({"path": source, "reason": str(error)})
            continue
        matched += _check_source(
            source,
            read_document(text),
            scanner=scanner,
            targets=targets,
            checked_at=checked_at,
            findings=findings,
            unverified=unverified,
            directories=directories,
        )

    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["category"]] = counts.get(finding["category"], 0) + 1
    return script_output.emit_result(
        {
            "findings": findings,
            "unverified_links": unverified,
            "unreadable_documents": unreadable,
            "summary": {
                "checked_documents": len(expansion.files) - len(unreadable),
                "matched_references": matched,
                "findings_by_category": counts,
            },
            "scope": {
                "target": spec.to_dict(),
                "directories": sorted(directories),
                "checked_at": checked_at,
            },
            "problems": [problem.to_dict() for problem in expansion.problems],
            "warnings": list(expansion.warnings),
            "guidance": _guidance(findings),
        }
    )


def main(argv: list[str] | None = None) -> int:
    return execute(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
