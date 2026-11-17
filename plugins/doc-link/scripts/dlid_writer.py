"""付与計画を、利用者の文書へ[DLID]だけとして書き込み、書き込み後に差分を検証する共通モジュール。

DES-005 §2.1、DES-008 §1、REQ-001 D-031・NFR-004 を実装する。利用者の文書へ書き込む唯一の処理なので、
「[DLID]以外を書き込まない」ことを最優先にする。入口 script ではないので、PEP 723 とロックは持たない
（使う script が宣言する）。

使う部品: 付与計画は `embed_plan`（`EmbedPlan`・`IssueItem`・`FrontmatterPosition`・`HeadingPosition`）、
文書の解析は `markdown_reader`、一時ファイルの置き場の規約は `state_store.TEMP_ROOT`。これらを再実装しない。

## 入出力

`apply_plan(project_root, plan, write=...)` が `WriteResult` を返す。

- `plan.confirmed` が偽（利用者が原本を確定していない重複がある）とき、何も書き込まず `PlanNotConfirmed` を送出する
- 文書ごとに「書き込み → 読み直して再解析 → 差分の検証」を行う。検証を通れば、その文書の[DLID]は
  `WriteResult.written` に入り、ロールバックしない（発行済み）。検証を通らなければ、その文書を元のバイト列へ戻し
  （取消し）、`WriteResult.failed` に入れる。ある文書の失敗は、ほかの文書の書き込みを止めない
- `WriteResult.failed` が 1 件でもあれば、操作は失敗である（`succeeded` が偽）。文書ごとに、パス・問題箇所・
  原因を持つ
- `write` は文書へ書き込む関数（`write(project_root, target, data)`、失敗は `OSError`）。既定は原子的な置き換え
  `_atomic_write`。テストが、検証前の書き込みを差し替えるためにある。取消しは常に `_atomic_write` で行う

## 書き込む位置（DES-008 §1、D-031）

書き込むのは、計画の項目（`IssueItem`）が指す次の 2 種類だけである。HTML・リンク・リンクの title・見出しのテキスト・
本文は書き込まず、書き換えない。コードブロック・HTML ブロック内は、計画が `markdown_reader` の解析した見出しだけを
指すので、書き込まれない。

- frontmatter の `doc_link_id`: キーがあればその行を `doc_link_id: <DLID>` に置き換え、無ければ閉じる行の直前へ
  足す。frontmatter が無い文書は、先頭に `doc_link_id` だけの frontmatter を新設する
- 見出しの行の末尾: 見出しのテキストの末尾に、空白 1 つで区切って[DLID]を置く。ATX 見出しに閉じの `#` の列が
  あればその前に置く。setext 見出しはテキストの最後の行の末尾に置く。再発行（`replaces` が値を持つ）では、見出しの
  末尾の語を置き換える

## 仕様の解釈（設計書が値や形式を定めていない点）

- 改行コード（`\\n`・`\\r\\n`・`\\r`）は変えない。足す行の改行は、足す位置の隣の行（キーを足すときは frontmatter を
  開く行、新設するときは文書の最初の改行のある行）に合わせる。文書に改行が 1 つも無いときは `\\n` とする
- frontmatter を新設する位置は、文書の先頭（先頭の空行より前）とする。新設する frontmatter は
  `---`・`doc_link_id: <DLID>`・`---` の 3 行である。文書の先頭の行が空行でないときは、その後に空行を
  1 行足す（要件 D-051。frontmatter の直後に本文を置かない）
- 既存の `doc_link_id` の行を置き換えるときは、その行全体を `doc_link_id: <DLID>` にする（古い値と、その行末の
  コメントは残らない。この行が[DLID]の位置であり、認識できない値を置き換える位置だからである）
- 行末の空白: ATX 見出しは、見出しのテキストの直後に ` <DLID>` を挿入し、後続の空白・閉じの `#` はそのまま残す。
  setext 見出しは、最後のテキスト行の末尾の空白を除いた位置の直後に挿入し、末尾の空白は残す
- 閉じる行の無い frontmatter の文書には書き込まず、失敗として報告する。計画（`FrontmatterPosition`）は、
  frontmatter が無い場合と閉じる行が無い場合を区別できないので、原文の先頭の空行を除いた最初の行が `---` かで
  書き込む側が区別する（`markdown_reader.read_frontmatter` の判定と同じ基準）
- UTF-8 の BOM（U+FEFF）で始まる文書には書き込まない（失敗として報告する）。`markdown_reader` は BOM の後の
  `---` を frontmatter と認識しないため、先頭へ frontmatter を新設すると、BOM と既存の frontmatter の前に
  別の frontmatter を足して文書を壊すからである
- 計画の作成後に文書が変わり、計画の位置・既存の[DLID]・frontmatter の有無が今の文書と合わないときは、
  その文書に書き込まず、失敗として報告する（古い計画で[DLID]以外を壊さないため）
- 書き込み先がシンボリックリンクのときは、リンクの実体へ置き換える（リンクを通常のファイルで置き換えない）。
  読み取り専用（`os.access` で書き込めない）の文書には書き込まず、失敗として報告する
- 原子的な置き換えは `state_store.write_if_changed` を使わず、このモジュールで持つ。理由は、`write_if_changed` が
  元のファイルの権限を保たない（一時ファイルの権限 0600 のまま置き換わる）ためである。一時ファイルは
  `state_store.TEMP_ROOT` の下の `embed-dlid` に置き、失敗しても残さない。管理状態の保存層（共用部品）は、
  この都合では書き換えない
- 検証（`verify_written`）は、書き込み前後の文書を、行単位と再解析の両方で比べる。許す差分は、計画の項目が指す
  [DLID]の追加・置換だけで、それ以外の行・見出し・frontmatter のキー・リンク・リファレンスリンクの定義
  （行番号を除く）に違いがあれば不合格とする
"""

import os
import stat
import tempfile
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import state_store
from dlid import KIND_DOCUMENT, KIND_SECTION
from embed_plan import EmbedPlan, FrontmatterPosition, HeadingPosition, IssueItem
from markdown_reader import (
    DOC_LINK_ID_KEY,
    FRONTMATTER_DELIMITER,
    MarkdownDocument,
    has_unclosed_frontmatter,
    parse_markdown,
    read_document,
    read_frontmatter,
    split_lines,
)

SKILL_NAME = "embed-dlid"
_BOM = "﻿"
_NEWLINES = ("\r\n", "\r", "\n")

Writer = Callable[[Path, Path, bytes], None]


class PlanNotConfirmed(Exception):
    """計画が確定していない（原本が未確定の重複がある）。何も書き込まない。"""


@dataclass(frozen=True)
class WrittenItem:
    """検証を通って書き込んだ[DLID]。`line` は書き込み後の文書の 1 始まりの見出しの行（文書の[DLID]は `None`）。"""

    path: str
    kind: str
    dlid: str
    replaced: str | None
    line: int | None
    heading: str | None


@dataclass(frozen=True)
class DocumentFailure:
    """書き込めなかった文書。`reverted` は、書き込んだ後に取り消して元のバイト列へ戻したか。"""

    path: str
    location: str
    cause: str
    reverted: bool = False


@dataclass(frozen=True)
class WriteResult:
    written: tuple[WrittenItem, ...]
    failed: tuple[DocumentFailure, ...]

    @property
    def succeeded(self) -> bool:
        return not self.failed


class _Refused(Exception):
    """この文書には書き込まない（書き込む前の拒否）。"""

    def __init__(self, location: str, cause: str):
        super().__init__(f"{location}: {cause}")
        self.location = location
        self.cause = cause


def apply_plan(
    project_root: str | Path, plan: EmbedPlan, write: Writer | None = None
) -> WriteResult:
    """確定した付与計画を、文書ごとに書き込み・検証し、結果を返す。"""
    if not plan.confirmed:
        raise PlanNotConfirmed(
            "原本が確定していない重複があるので、何も書き込まない: "
            + ", ".join(report.dlid for report in plan.unresolved)
        )
    root = Path(project_root)
    writer = write if write is not None else _atomic_write
    by_path: OrderedDict[str, list[IssueItem]] = OrderedDict()
    for item in plan.items:
        by_path.setdefault(item.path, []).append(item)

    written: list[WrittenItem] = []
    failed: list[DocumentFailure] = []
    for path, items in by_path.items():
        try:
            written.extend(_write_document(root, path, items, writer))
        except _Refused as refusal:
            failed.append(DocumentFailure(path, refusal.location, refusal.cause))
        except _VerificationFailed as failure:
            failed.append(
                DocumentFailure(
                    path, failure.location, failure.cause, reverted=failure.reverted
                )
            )
    return WriteResult(written=tuple(written), failed=tuple(failed))


class _VerificationFailed(Exception):
    def __init__(self, location: str, cause: str, reverted: bool):
        super().__init__(f"{location}: {cause}")
        self.location = location
        self.cause = cause
        self.reverted = reverted


def _write_document(
    root: Path, path: str, items: list[IssueItem], writer: Writer
) -> list[WrittenItem]:
    target = Path(os.path.realpath(root / path))
    try:
        original = target.read_bytes()
    except OSError as exc:
        raise _Refused("文書全体", f"読めない: {exc}") from exc
    try:
        before_text = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _Refused("文書全体", f"UTF-8 として読めない: {exc}") from exc

    _check_writable_document(before_text, target)
    before = read_document(before_text)
    after_text = _render(before_text, before, items)

    try:
        writer(root, target, after_text.encode("utf-8"))
    except OSError as exc:
        # 原子的な置き換えなので、書き込めなかったときは元のバイト列のまま残る
        raise _Refused("文書全体", f"書き込めない: {exc}") from exc

    try:
        problems = _verify_file(target, before_text, items)
    except OSError as exc:
        problems = [f"書き込み後の文書を読み直せない: {exc}"]
    if problems:
        raise _revert(root, target, original, "書き込み後の検証", problems)

    after = read_document(after_text)
    return _written_items(before, after, items)


def _check_writable_document(text: str, target: Path) -> None:
    if text.startswith(_BOM):
        raise _Refused(
            "文書の先頭",
            "UTF-8 の BOM で始まる文書には書き込まない（frontmatter を認識できない）",
        )
    if has_unclosed_frontmatter(split_lines(text)):
        raise _Refused(
            "frontmatter", "frontmatter を閉じる行（`---`）が無いので書き込まない"
        )
    if not os.access(target, os.W_OK):
        raise _Refused("文書全体", "書き込み権限が無い（読み取り専用）")


def _verify_file(target: Path, before_text: str, items: list[IssueItem]) -> list[str]:
    after_text = target.read_bytes().decode("utf-8", errors="strict")
    return verify_written(before_text, after_text, items)


def _revert(
    root: Path, target: Path, original: bytes, location: str, problems: list[str]
) -> _VerificationFailed:
    cause = "; ".join(problems)
    try:
        _atomic_write(root, target, original)
        if target.read_bytes() != original:
            return _VerificationFailed(
                location,
                f"{cause}。取り消したが元のバイト列と一致しない（文書を確認すること）",
                reverted=False,
            )
    except OSError as exc:
        return _VerificationFailed(
            location,
            f"{cause}。取り消しにも失敗した（文書を確認すること）: {exc}",
            reverted=False,
        )
    return _VerificationFailed(
        location, f"{cause}。書き込みを取り消して元に戻した", reverted=True
    )


def _atomic_write(project_root: Path, target: Path, data: bytes) -> None:
    """一時ファイルへ書いてから `os.replace` で置き換える。元の権限を保ち、失敗しても一時ファイルを残さない。"""
    temp_dir = Path(project_root).joinpath(*state_store.TEMP_ROOT, SKILL_NAME)
    temp_path: Path | None = None
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        mode = stat.S_IMODE(target.stat().st_mode)
        descriptor, name = tempfile.mkstemp(
            dir=temp_dir, prefix="embed_", suffix=".tmp"
        )
        temp_path = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


# --- 書き込む文面の組み立て ----------------------------------------------------


def _split_newline(line: str) -> tuple[str, str]:
    for newline in _NEWLINES:
        if line.endswith(newline):
            return line[: -len(newline)], newline
    return line, ""


def _document_newline(lines: list[str]) -> str:
    for line in lines:
        _, newline = _split_newline(line)
        if newline:
            return newline
    return "\n"


def _heading_markups(text: str, document: MarkdownDocument) -> list[str]:
    """見出しごとの markdown-it-py の `markup`（ATX は `#` の列、setext は `=` か `-`）を出現順に返す。"""
    frontmatter = document.frontmatter
    offset = frontmatter.body_start_line if frontmatter.present else 0
    tokens, _env = parse_markdown("".join(document.lines[offset:]))
    return [token.markup for token in tokens if token.type == "heading_open"]


def _heading_index(document: MarkdownDocument) -> dict[int, int]:
    return {
        heading.start_line: index for index, heading in enumerate(document.headings)
    }


def _find_key_line(document: MarkdownDocument) -> int | None:
    """frontmatter の中で、`markdown_reader` が `doc_link_id` のキーとして読む最初の行の番号。"""
    frontmatter = document.frontmatter
    for index in range(frontmatter.start_line + 1, frontmatter.end_line):
        probe = read_frontmatter(
            [
                f"{FRONTMATTER_DELIMITER}\n",
                _split_newline(document.lines[index])[0] + "\n",
                f"{FRONTMATTER_DELIMITER}\n",
            ]
        )
        if DOC_LINK_ID_KEY in probe.keys:
            return index
    return None


def _render(text: str, document: MarkdownDocument, items: list[IssueItem]) -> str:
    lines = list(document.lines)
    markups = _heading_markups(text, document)
    headings = _heading_index(document)

    for item in items:
        if item.kind != KIND_SECTION:
            continue
        position = item.position
        assert isinstance(position, HeadingPosition)
        index = headings.get(position.start_line)
        heading = document.headings[index] if index is not None else None
        location = f"見出し（{position.start_line + 1} 行目）"
        if heading is None or heading.end_line != position.end_line:
            raise _Refused(
                location, "計画の位置に見出しが無い（計画の作成後に文書が変わった）"
            )
        if heading.section_id != item.replaces:
            raise _Refused(
                location,
                "見出しの[セクション ID]が計画と違う（計画の作成後に文書が変わった）",
            )
        line_index, new_line = _edit_heading(lines, heading, markups[index], item)
        lines[line_index] = new_line

    for item in items:
        if item.kind != KIND_DOCUMENT:
            continue
        position = item.position
        assert isinstance(position, FrontmatterPosition)
        _edit_frontmatter(lines, document, item, position)
    return "".join(lines)


def _edit_heading(
    lines: list[str], heading, markup: str, item: IssueItem
) -> tuple[int, str]:
    location = f"見出し（{heading.start_line + 1} 行目）"
    if markup.startswith("#"):
        index = heading.start_line
        body, newline = _split_newline(lines[index])
        opening = body.find(markup)
        if opening < 0:
            raise _Refused(location, "ATX 見出しの開始の `#` の列を行から特定できない")
        position = opening + len(markup)
        content = heading.text
        if content == "":
            new_body = body[:position] + " " + item.dlid + body[position:]
            return index, new_body + newline
        while position < len(body) and body[position] in " \t":
            position += 1
        if not body.startswith(content, position):
            raise _Refused(location, "見出しのテキストを行から特定できない")
        end = position + len(content)
    else:
        index = heading.end_line - 2
        if index < heading.start_line:
            raise _Refused(location, "setext 見出しのテキストの行を特定できない")
        body, newline = _split_newline(lines[index])
        end = len(body.rstrip(" \t"))
        content = body[:end]
    if item.replaces is not None:
        if not content.endswith(item.replaces):
            raise _Refused(location, "見出しの末尾の語が置き換える[DLID]と違う")
        new_body = body[: end - len(item.replaces)] + item.dlid + body[end:]
    else:
        new_body = body[:end] + " " + item.dlid + body[end:]
    return index, new_body + newline


def _edit_frontmatter(
    lines: list[str],
    document: MarkdownDocument,
    item: IssueItem,
    position: FrontmatterPosition,
) -> None:
    frontmatter = document.frontmatter
    location = "frontmatter の doc_link_id"
    if document.frontmatter.doc_link_id != item.replaces:
        raise _Refused(
            location, "[文書 ID]が計画と違う（計画の作成後に文書が変わった）"
        )
    if (
        position.frontmatter_present != frontmatter.present
        or (
            frontmatter.present
            and (
                position.start_line != frontmatter.start_line
                or position.end_line != frontmatter.end_line
            )
        )
        or position.key_present
        != (frontmatter.present and DOC_LINK_ID_KEY in frontmatter.keys)
    ):
        raise _Refused(
            location, "frontmatter の位置が計画と違う（計画の作成後に文書が変わった）"
        )

    value = f"{DOC_LINK_ID_KEY}: {item.dlid}"
    if not frontmatter.present:
        newline = _document_newline(lines)
        new_lines = [
            FRONTMATTER_DELIMITER + newline,
            value + newline,
            FRONTMATTER_DELIMITER + newline,
        ]
        if _needs_separator(lines):
            new_lines.append(newline)
        lines[0:0] = new_lines
    elif position.key_present:
        index = _find_key_line(document)
        if index is None:
            raise _Refused(location, "doc_link_id の行を特定できない")
        _, newline = _split_newline(lines[index])
        lines[index] = value + newline
    else:
        _, newline = _split_newline(lines[frontmatter.start_line])
        lines.insert(frontmatter.end_line, value + newline)


def _needs_separator(lines: list[str]) -> bool:
    """新設する frontmatter の後に、空行を 1 行足すか。

    文書の先頭の行が空行でなければ足す（frontmatter の直後に本文を置かない。整形ツールが
    frontmatter の直後に空行を求めるため）。文書が空、または先頭の行がすでに空行なら足さない。
    """
    return bool(lines) and _split_newline(lines[0])[0].strip() != ""


def _written_items(
    before: MarkdownDocument, after: MarkdownDocument, items: list[IssueItem]
) -> list[WrittenItem]:
    headings = _heading_index(before)
    written = []
    for item in items:
        line = None
        heading_text = None
        if item.kind == KIND_SECTION:
            index = headings[item.position.start_line]
            line = after.headings[index].start_line + 1
            heading_text = after.headings[index].text
        written.append(
            WrittenItem(
                path=item.path,
                kind=item.kind,
                dlid=item.dlid,
                replaced=item.replaces,
                line=line,
                heading=heading_text,
            )
        )
    return written


# --- 書き込み後の検証 ----------------------------------------------------------


def verify_written(
    before_text: str, after_text: str, items: list[IssueItem]
) -> list[str]:
    """書き込み前後の文書を比べ、差分が計画の項目が指す[DLID]の追加・置換だけかを検証する。

    問題の一覧を返す（空なら合格）。行単位の比較と、再解析した構造の比較の両方を行う。
    """
    before = read_document(before_text)
    after = read_document(after_text)
    problems: list[str] = []

    if len(before.headings) != len(after.headings):
        return [
            f"見出しの数が変わった（{len(before.headings)} → {len(after.headings)}）"
        ]
    problems.extend(_verify_lines(before_text, before, after, items))
    problems.extend(_verify_structure(before, after, items))
    return problems


def _verify_lines(
    before_text: str,
    before: MarkdownDocument,
    after: MarkdownDocument,
    items: list[IssueItem],
) -> list[str]:
    problems: list[str] = []
    old = list(before.lines)
    new = list(after.lines)
    doc_items = [item for item in items if item.kind == KIND_DOCUMENT]
    doc_item = doc_items[0] if doc_items else None

    inserted = 0
    insert_at: int | None = None
    replaced_key_line: int | None = None
    if doc_item is not None:
        if not before.frontmatter.present:
            inserted, insert_at = (4 if _needs_separator(old) else 3), 0
        elif doc_item.position.key_present:
            replaced_key_line = _find_key_line(before)
        else:
            inserted, insert_at = 1, before.frontmatter.end_line
    if len(new) != len(old) + inserted:
        return [f"行数が想定と違う（{len(old)} 行 + {inserted} 行 → {len(new)} 行）"]

    def new_index(index: int) -> int:
        if insert_at is not None and index >= insert_at:
            return index + inserted
        return index

    heading_last_lines: dict[int, IssueItem] = {}
    markups = _heading_markups(before_text, before)
    headings = _heading_index(before)
    for item in items:
        if item.kind != KIND_SECTION:
            continue
        index = headings.get(item.position.start_line)
        if index is None:
            problems.append(
                f"計画の見出しが無い（{item.position.start_line + 1} 行目）"
            )
            continue
        heading = before.headings[index]
        last = (
            heading.start_line
            if markups[index].startswith("#")
            else heading.end_line - 2
        )
        heading_last_lines[last] = item

    if doc_item is not None and inserted:
        problems.extend(_verify_inserted_lines(old, new, doc_item, insert_at, inserted))

    for index, old_line in enumerate(old):
        new_line = new[new_index(index)]
        if index == replaced_key_line:
            problems.extend(_verify_key_line(old_line, new_line, doc_item))
        elif index in heading_last_lines:
            problems.extend(
                _verify_heading_line(
                    old_line, new_line, heading_last_lines[index], index
                )
            )
        elif new_line != old_line:
            problems.append(f"計画にない行が変わった（{index + 1} 行目）")
    return problems


def _verify_inserted_lines(
    old: list[str],
    new: list[str],
    item: IssueItem,
    insert_at: int | None,
    inserted: int,
) -> list[str]:
    value = f"{DOC_LINK_ID_KEY}: {item.dlid}"
    if inserted in (3, 4):
        expected_newline = _split_newline(new[0])[1]
        expected = [FRONTMATTER_DELIMITER, value, FRONTMATTER_DELIMITER]
        if inserted == 4:
            expected.append("")  # frontmatter の直後の空行
        actual = [_split_newline(line)[0] for line in new[:inserted]]
        newlines = {_split_newline(line)[1] for line in new[:inserted]}
        if actual != expected or newlines != {expected_newline} or not expected_newline:
            return [
                "新設した frontmatter が `---`・doc_link_id・`---`"
                "（と、後の空行 1 行）でない"
            ]
        return []
    assert insert_at is not None
    body, newline = _split_newline(new[insert_at])
    if body != value or newline == "":
        return ["足した行が `doc_link_id: <DLID>` だけでない"]
    return []


def _verify_key_line(old_line: str, new_line: str, item: IssueItem | None) -> list[str]:
    assert item is not None
    body, newline = _split_newline(new_line)
    if newline != _split_newline(old_line)[1]:
        return ["doc_link_id の行の改行コードが変わった"]
    probe = read_frontmatter(
        [f"{FRONTMATTER_DELIMITER}\n", body + "\n", f"{FRONTMATTER_DELIMITER}\n"]
    )
    if probe.keys.get(DOC_LINK_ID_KEY) != item.dlid:
        return ["doc_link_id の行の値が計画の[DLID]でない"]
    return []


def _strip_dlid(body: str, dlid: str) -> str | None:
    """行から[DLID]（と、直前の空白 1 つ）を 1 回だけ除く。ちょうど 1 回現れなければ `None`。"""
    if body.count(dlid) != 1:
        return None
    spaced = " " + dlid
    return body.replace(spaced, "", 1) if spaced in body else body.replace(dlid, "", 1)


def _verify_heading_line(
    old_line: str, new_line: str, item: IssueItem, index: int
) -> list[str]:
    old_body, old_newline = _split_newline(old_line)
    new_body, new_newline = _split_newline(new_line)
    if old_newline != new_newline:
        return [f"見出しの行の改行コードが変わった（{index + 1} 行目）"]
    if item.replaces is not None:
        stripped_old = _strip_dlid(old_body, item.replaces)
    else:
        stripped_old = old_body
    stripped_new = _strip_dlid(new_body, item.dlid)
    if stripped_old is None or stripped_new is None or stripped_old != stripped_new:
        return [f"見出しの行の差分が[DLID]の追加・置換だけでない（{index + 1} 行目）"]
    return []


def _verify_structure(
    before: MarkdownDocument, after: MarkdownDocument, items: list[IssueItem]
) -> list[str]:
    problems: list[str] = []
    doc_items = [item for item in items if item.kind == KIND_DOCUMENT]
    section_items = {
        item.position.start_line: item for item in items if item.kind == KIND_SECTION
    }

    if not after.frontmatter.present:
        problems.append("書き込み後の文書で frontmatter が認識されない")
    else:
        expected_id = doc_items[0].dlid if doc_items else before.frontmatter.doc_link_id
        if after.frontmatter.doc_link_id != expected_id:
            problems.append("書き込み後の文書の[文書 ID]が計画と違う")
        other_before = {
            key: value
            for key, value in before.frontmatter.keys.items()
            if key != DOC_LINK_ID_KEY
        }
        other_after = {
            key: value
            for key, value in after.frontmatter.keys.items()
            if key != DOC_LINK_ID_KEY
        }
        if other_before != other_after:
            problems.append("frontmatter の doc_link_id 以外のキーが変わった")

    for old, new in zip(before.headings, after.headings):
        item = section_items.get(old.start_line)
        if old.level != new.level:
            problems.append(f"見出しの階層が変わった（{old.start_line + 1} 行目）")
        if item is None:
            if old.text != new.text or old.section_id != new.section_id:
                problems.append(
                    f"計画にない見出しが変わった（{old.start_line + 1} 行目）"
                )
            continue
        if item.replaces is not None:
            expected_text = old.text[: -len(item.replaces)] + item.dlid
        elif old.text:
            expected_text = old.text + " " + item.dlid
        else:
            expected_text = item.dlid
        if new.text != expected_text or new.section_id != item.dlid:
            problems.append(
                f"見出し（{old.start_line + 1} 行目）の末尾の語が計画の[DLID]として読めない"
            )

    if _references(before) != _references(after):
        problems.append("リファレンスリンクの定義が変わった")
    if _links(before) != _links(after):
        problems.append("リンクが変わった")
    return problems


def _references(document: MarkdownDocument) -> list[tuple]:
    return [
        (
            ref.label,
            ref.href,
            ref.title,
            ref.path,
            ref.fragment,
            ref.dlid,
            ref.preceding_word,
        )
        for ref in document.references
    ]


def _links(document: MarkdownDocument) -> list[tuple]:
    return [(link.kind, link.href, link.title) for link in document.links]
