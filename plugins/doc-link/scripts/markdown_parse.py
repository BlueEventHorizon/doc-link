# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "markdown-it-py>=4.2.0",
# ]
# ///
"""Markdown 文書の frontmatter・見出し・アンカー行・セクション範囲を解析するプラグイン共通の部品。

複数の SKILL の script が import して使う。CLI は持たない。

- frontmatter（DES-008 §1、REQ-002 FR-002・AC-012）: 区切りの判定は DocAdvisor と同じ。
  文書の先頭の空行を読み飛ばし、前後の空白を除くと `---` になる最初の行で始まり、次の
  同じ行で閉じる。区切りの判定では、DocAdvisor と同じく `\n` だけで行を分ける。閉じる
  行が無い文書は frontmatter が無いものとして読むが、書き込みを拒否できるよう、無い場合と
  区別して返す。中身は DocAdvisor と同じく最上位のキーだけを読む最小限の解析で読み
  （スカラ・ブロック配列・インライン配列。ブロックスカラは None）、YAML の構文の誤りで
  frontmatter 全体を読めなくすることはしない。
  `doc_link_id` の値は `dlid.recognize_dlid` で認識し、解析できない文書の文書 ID は
  「文書 ID が存在しない」（None）とする。
- 本文（DES-008 §2）: frontmatter を除いた本文を markdown-it-py（CommonMark）で解析し、
  独自の正規表現でブロック構造を判定しない。見出しは heading トークン（ATX・setext）
  から取るので、コードブロック・HTML ブロック内の見出し様の行は見出しにならない。
- アンカー行（DES-008 §1・§2）: `<a id="…">` と `</a>` の二つの html_inline だけから成る
  段落で、次のブロックが見出しであるものを、その見出しのアンカー行とする。id 属性の
  値は `dlid.recognize_dlid` で認識し、認識できなければセクション ID は無しとする。
- セクション範囲（D-033）: 見出しの行から、同じ階層以上の次の見出しの直前の行まで。
  そのような見出しが無ければ文書の末尾の行まで。

行番号はすべて元の文書（frontmatter を含む）の 1 始まりの行番号で返す。行の区切りは
CommonMark と同じく `\\r\\n`・`\\r`・`\\n` とする。
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from markdown_it import MarkdownIt

from dlid import recognize_dlid

FRONTMATTER_DELIMITER = "---"
"""frontmatter の開始と終了を示す行の、前後の空白を除いた内容。"""

DOC_LINK_ID_KEY = "doc_link_id"
"""文書 ID を記載する frontmatter のキー（D-001）。"""

_LINE_BREAK = re.compile(r"\r\n|\r|\n")

# アンカー行の開始タグ。DES-008 §1・§2 が定める `<a id="…">` の形だけを受け付ける。
_ANCHOR_OPEN_TAG = re.compile(r'<a id="([^"]*)">')
_ANCHOR_CLOSE_TAG = "</a>"


class FrontmatterStatus(StrEnum):
    """frontmatter の状態。"""

    ABSENT = "absent"
    """先頭の空行を除いた最初の行が区切りの行でない（frontmatter が無い）。"""

    UNCLOSED = "unclosed"
    """始まりの区切りの行はあるが、閉じる行が無い。frontmatter が無いものとして読む。"""

    PARSED = "parsed"
    """frontmatter がある（閉じる行がある）。"""


@dataclass(frozen=True)
class Heading:
    """見出し 1 つと、そのセクションの情報。行番号は元の文書の 1 始まり。"""

    line: int
    """見出しの行番号（setext 見出しでは見出しの文字列の最初の行）。"""

    level: int
    """見出しのレベル（1〜6）。"""

    text: str
    """見出しのテキスト（インラインの内容。Markdown の記法はそのまま残る）。"""

    anchor_line: int | None
    """直前のアンカー行の行番号。アンカー行が無ければ None。"""

    anchor_id: str | None
    """直前のアンカー行の id 属性の値（認識前の値）。アンカー行が無ければ None。"""

    section_dlid: str | None
    """直前のアンカー行から認識したセクション ID。無い・認識できなければ None。"""

    section_start: int
    """セクション範囲の最初の行（見出しの行）。"""

    section_end: int
    """セクション範囲の最後の行（同じ階層以上の次の見出しの直前の行、または文書の末尾の行）。"""


@dataclass(frozen=True)
class ParsedDocument:
    """文書 1 つの解析結果。"""

    frontmatter_status: FrontmatterStatus
    """frontmatter の状態。"""

    frontmatter: dict | None
    """frontmatter の最上位のキーと値（文字列・文字列の list・None）。PARSED 以外では None。"""

    frontmatter_end_line: int | None
    """frontmatter を閉じる区切りの行の行番号。frontmatter が無ければ None。"""

    doc_link_id: str | None
    """認識した文書 ID。「文書 ID が存在しない」ときは None。"""

    headings: tuple[Heading, ...]
    """本文の見出しを文書の順に並べたもの（見出しが 0 件のときは空のタプル）。"""

    line_count: int
    """元の文書の行数。"""


def _split_lines(text: str) -> list[str]:
    """行の区切りを含めたまま、文書を行に分ける。"""
    lines = []
    start = 0
    for match in _LINE_BREAK.finditer(text):
        lines.append(text[start : match.end()])
        start = match.end()
    if start < len(text):
        lines.append(text[start:])
    return lines


def _unquote_value(value: str) -> str:
    """引用符付きのスカラを素の文字列へ戻す（DocAdvisor の `unquote_yaml_value` と同じ）。"""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        inner = value[1:-1]
        result = []
        i = 0
        while i < len(inner):
            char = inner[i]
            if char == "\\" and i + 1 < len(inner):
                nxt = inner[i + 1]
                mapping = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}
                if nxt in mapping:
                    result.append(mapping[nxt])
                    i += 2
                    continue
            result.append(char)
            i += 1
        return "".join(result)

    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")

    return value


def _parse_frontmatter(source: str) -> dict:
    """frontmatter の最上位のキーを読む（DocAdvisor の `parse_frontmatter` と同じ）。

    スカラ（引用符付きも可）、ブロック配列、インライン配列を読む。ブロックスカラ
    （`|`・`>`）の値は None とし、最上位のキーの下のネストは読まない。
    """
    result: dict = {}
    current_list: list | None = None

    for line in source.split("\n"):
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        # ブロック配列の要素（インデントの有無は問わない）
        if stripped.startswith("- ") or stripped == "-":
            if current_list is not None:
                current_list.append(_unquote_value(stripped[1:].strip()))
            continue

        # 最上位のキー以外（ネストした mapping 等）は読まない
        if line[:1].isspace():
            continue

        if ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        current_list = None

        if not value:
            # 次の行からのブロック配列を受け付ける（要素が無ければ空の配列）
            current_list = []
            result[key] = current_list
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            result[key] = (
                [_unquote_value(item.strip()) for item in inner.split(",")]
                if inner
                else []
            )
        elif value[0] in ("|", ">"):
            result[key] = None
        else:
            result[key] = _unquote_value(value)

    return result


def _anchor_id(inline_token) -> str | None:
    """段落の inline トークンがアンカー行の形なら id 属性の値を、そうでなければ None を返す。"""
    children = inline_token.children or []
    if len(children) != 2:
        return None
    first, second = children
    if first.type != "html_inline" or second.type != "html_inline":
        return None
    if second.content != _ANCHOR_CLOSE_TAG:
        return None
    match = _ANCHOR_OPEN_TAG.fullmatch(first.content)
    if match is None:
        return None
    return match.group(1)


def _parse_body(body: str, line_offset: int, line_count: int) -> tuple[Heading, ...]:
    """本文を解析して見出しを返す。

    Args:
        body: frontmatter を除いた本文。
        line_offset: 本文の 1 行目より前にある元の文書の行数。
        line_count: 元の文書の行数。
    """
    tokens = MarkdownIt("commonmark").parse(body)

    found = []  # (行, レベル, テキスト, アンカー行, アンカーの id)
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        level = int(token.tag[1:])
        text = tokens[index + 1].content
        line = token.map[0] + line_offset + 1

        anchor_line = None
        anchor_id = None
        # 直前のブロックが段落（paragraph_open, inline, paragraph_close）で、アンカー行の形か
        if (
            index >= 3
            and tokens[index - 1].type == "paragraph_close"
            and tokens[index - 2].type == "inline"
            and tokens[index - 3].type == "paragraph_open"
        ):
            anchor_id = _anchor_id(tokens[index - 2])
            if anchor_id is not None:
                anchor_line = tokens[index - 3].map[0] + line_offset + 1
        found.append((line, level, text, anchor_line, anchor_id))

    headings = []
    for position, (line, level, text, anchor_line, anchor_id) in enumerate(found):
        section_end = line_count
        for next_line, next_level, *_ in found[position + 1 :]:
            if next_level <= level:
                section_end = next_line - 1
                break
        headings.append(
            Heading(
                line=line,
                level=level,
                text=text,
                anchor_line=anchor_line,
                anchor_id=anchor_id,
                section_dlid=recognize_dlid(anchor_id)
                if anchor_id is not None
                else None,
                section_start=line,
                section_end=section_end,
            )
        )
    return tuple(headings)


def parse_markdown(text: str) -> ParsedDocument:
    """Markdown 文書を解析する。

    Args:
        text: 文書の全文（frontmatter を含む）。

    Returns:
        frontmatter の状態と値、文書 ID、見出しとセクション範囲を持つ解析結果。
    """
    lines = _split_lines(text)
    line_count = len(lines)

    # 区切りの判定は DocAdvisor と同じく `\n` だけで行を分けて行う
    raw_lines = text.split("\n")
    opening_index = 0
    while opening_index < len(raw_lines) and raw_lines[opening_index].strip() == "":
        opening_index += 1

    if (
        opening_index >= len(raw_lines)
        or raw_lines[opening_index].strip() != FRONTMATTER_DELIMITER
    ):
        status = FrontmatterStatus.ABSENT
        closing_index = None
    else:
        status = FrontmatterStatus.UNCLOSED
        closing_index = next(
            (
                index
                for index in range(opening_index + 1, len(raw_lines))
                if raw_lines[index].strip() == FRONTMATTER_DELIMITER
            ),
            None,
        )

    if closing_index is None:
        return ParsedDocument(
            frontmatter_status=status,
            frontmatter=None,
            frontmatter_end_line=None,
            doc_link_id=None,
            headings=_parse_body(text, 0, line_count),
            line_count=line_count,
        )

    frontmatter = _parse_frontmatter(
        "\n".join(raw_lines[opening_index + 1 : closing_index])
    )
    # 閉じる行までの文字数から、元の文書（CommonMark の行の区切り）での行数を求める
    prefix = "\n".join(raw_lines[: closing_index + 1])
    if closing_index + 1 < len(raw_lines):
        prefix += "\n"
    body_offset = len(_split_lines(prefix))
    headings = _parse_body(text[len(prefix) :], body_offset, line_count)

    return ParsedDocument(
        frontmatter_status=FrontmatterStatus.PARSED,
        frontmatter=frontmatter,
        frontmatter_end_line=body_offset,
        doc_link_id=recognize_dlid(frontmatter.get(DOC_LINK_ID_KEY)),
        headings=headings,
        line_count=line_count,
    )
