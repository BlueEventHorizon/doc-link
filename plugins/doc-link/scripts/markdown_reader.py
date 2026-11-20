"""Markdown の読取り規則（frontmatter・見出しとセクション範囲・リファレンスリンクの定義・アンカー）を持つ共通モジュール。

DES-008 §1・§2 と DES-007 §1 の読取りの部分を実装する。embed-dlid・index-docs・check-links など複数の SKILL の
script が import して使う。入口 script ではないので、PEP 723 とロックは持たない（使う script が宣言する）。
標準ライブラリと markdown-it-py だけを使う。ブロック構造（コードブロック・見出し・リンク定義・HTML ブロック）は
markdown-it-py の解析結果を使い、独自の正規表現で判定しない。

このモジュールが持たないもの（別タスクの範囲）: DLID の発行、重複の検出、[内容ハッシュ]の算出、title の記録語
（12 桁の小文字 16 進）の形式判定、[正式な参照]の抽出と実走査、原本への書き込み。

行番号は、文書全体（frontmatter を含む）の 0 始まりの行番号である。範囲は `[start, end)`（end は含まない）で表す。

仕様の解釈（設計書が値や形式を定めていない点）

- 行は `\\r\\n`・`\\r`・`\\n` で区切る（markdown-it-py の改行の扱いと同じ）。frontmatter の判定は行の
  `str.strip()` が `---` になるかで行う
- frontmatter の最上位のキーは、行頭（インデントなし）から始まる `キー: 値` の行から読む。値は、引用符（`"` か
  `'`）で 1 行に閉じたもの、または引用符なしの 1 行の文字列（` #` から後ろはコメントとして除く）とする。
  複数行の値・ブロックスカラ（`|`・`>`）・コレクション・タグ・アンカー・エイリアスはスカラとして読まない。
  同じキーが複数あるときは、最初のものを採る
- `doc_link_id` は、上のスカラが DLID 形式に完全一致したときだけ[文書 ID]とする。それ以外はすべて `None`
  （[文書 ID]が存在しない）で、形式不正という別分類は作らない
- 見出しは、引用ブロックやリストの中のものも、markdown-it-py が見出しとして解析したものはすべて見出しとする。
  セクションの範囲は、文書内の出現順で、その見出し以後の最初の「同じ階層以上（レベルの数字が同じか小さい）」の
  見出しの直前まで（なければ文書の末尾まで）とする
- 見出しの[セクション ID]は、見出しのテキスト（ATX の閉じの `#` を除いたもの。setext は複数行の全体）を空白で
  区切った最後の語が DLID 形式のときのその語とする
- 見出しのアンカーの元になる表示文字列は、テキスト・コード・文字参照の展開結果・画像の代替テキストを連結し、
  行内の改行（setext の複数行）は `\\n` のまま残す。`\\n` は制御文字（Cc）なので取り除かれる。HTML のタグ
  （行内 HTML）は文字列に含めない
- Unicode の Alphabetic 特性は `unicodedata` にない。DES-008 §2 の「Alphabetic 特性を持つ文字は取り除かない」
  は、取り除く一般カテゴリのうち Alphabetic 特性を持つ文字を残すことを指す。該当するのは Symbol（So）のうち
  丸付き・四角付きの英字だけ（U+24B6〜U+24E9、U+1F130〜U+1F149、U+1F150〜U+1F169、U+1F170〜U+1F189）なので、
  この範囲を表として持ち、So のこの範囲の文字は取り除かない。その他のカテゴリは一般カテゴリだけで決める。
  表は、GitHub の規則（github-slugger）の除去対象の正規表現（Alphabetic を除いて生成されたもの）の、
  U+24B6〜U+24E9 を残す範囲と、U+1F130〜U+1F189 の残す範囲から導いた。
- リファレンスリンクの定義のラベルは、markdown-it-py が正規化した値（前後の空白の除去・空白の圧縮・case fold
  相当）で返す。同じラベルの定義が複数あるときは、最初の定義だけを返す（markdown-it-py の解析結果のとおり）
- スキーム付き宛先の判定は、英字で始まり英数字・`+`・`.`・`-` が続いて `:` で終わる接頭辞の有無で行う
"""

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.token import Token

DLID_PATTERN = re.compile(r"DLID-[0-9a-hjkmnp-tv-z]{12}")
DOC_LINK_ID_KEY = "doc_link_id"
FRONTMATTER_DELIMITER = "---"

_LINE_PATTERN = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
_SCHEME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")
_TOP_LEVEL_KEY_PATTERN = re.compile(
    r"([^\s#\-:'\"\[\]{}][^:]*?)[ \t]*:(?:[ \t]+(.*))?$"
)
_NON_SCALAR_STARTS = "|>[{&*!%@`"
_NULL_WORDS = frozenset({"null", "Null", "NULL", "~"})

# アンカー生成で取り除く一般カテゴリ（DES-008 §2）
_ANCHOR_REMOVED_CATEGORIES = frozenset(
    {"No", "Pe", "Pf", "Pi", "Ps", "Po", "Co", "Cc", "Cf", "Cn"}
)

# Symbol（So）のうち Alphabetic 特性を持つ文字の範囲（アンカーでは取り除かない）。
_ALPHABETIC_SYMBOL_RANGES = (
    (0x24B6, 0x24E9),
    (0x1F130, 0x1F149),
    (0x1F150, 0x1F169),
    (0x1F170, 0x1F189),
)


def is_dlid(value: str) -> bool:
    """`DLID-` と小文字の Crockford Base32 の 12 文字の完全一致だけを DLID とする（大文字は不可）。"""
    return DLID_PATTERN.fullmatch(value) is not None


@dataclass(frozen=True)
class Frontmatter:
    """frontmatter の判定結果。`present` が偽なら、ほかのフィールドは意味を持たない。"""

    present: bool
    start_line: int = 0
    end_line: int = 0
    body_start_line: int = 0
    keys: dict[str, str | None] = field(default_factory=dict)

    @property
    def doc_link_id(self) -> str | None:
        """DLID 形式の単一文字列として認識できたときだけ[文書 ID]を返す。それ以外は `None`。"""
        value = self.keys.get(DOC_LINK_ID_KEY)
        if value is not None and is_dlid(value):
            return value
        return None


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    start_line: int
    end_line: int
    section_end_line: int
    section_id: str | None
    anchor: str


@dataclass(frozen=True)
class ReferenceDefinition:
    """リファレンスリンクの定義。`dlid` は title の最後の語が DLID 形式のときだけ値を持つ。

    `preceding_word` は title の最後の語の直前の語（無ければ `None`）で、記録語かの形式判定は呼び出し側が行う。
    """

    label: str
    href: str
    title: str
    path: str
    fragment: str | None
    dlid: str | None
    preceding_word: str | None
    start_line: int
    end_line: int


@dataclass(frozen=True)
class Link:
    """インライン解析で得たリンク。画像は含めない。autolink は title を持たない。"""

    kind: str
    href: str
    title: str | None
    line: int


@dataclass(frozen=True)
class MarkdownDocument:
    lines: tuple[str, ...]
    frontmatter: Frontmatter
    headings: tuple[Heading, ...]
    references: tuple[ReferenceDefinition, ...]
    links: tuple[Link, ...]


def split_lines(text: str) -> list[str]:
    """改行を保ったまま行に分ける。"""
    return _LINE_PATTERN.findall(text)


def read_frontmatter(lines: list[str]) -> Frontmatter:
    """DES-008 §1 の規則で frontmatter を判定する。閉じる行が無ければ frontmatter ではない。"""
    start = 0
    while start < len(lines) and lines[start].strip() == "":
        start += 1
    if start >= len(lines) or lines[start].strip() != FRONTMATTER_DELIMITER:
        return Frontmatter(present=False)
    for end in range(start + 1, len(lines)):
        if lines[end].strip() == FRONTMATTER_DELIMITER:
            keys = _read_top_level_keys(lines[start + 1 : end])
            return Frontmatter(
                present=True,
                start_line=start,
                end_line=end,
                body_start_line=end + 1,
                keys=keys,
            )
    return Frontmatter(present=False)


def has_unclosed_frontmatter(lines) -> bool:
    """先頭の空行を除いた最初の行が `---` なのに、frontmatter として認識されない（閉じる行が無い）か。"""
    lines = list(lines)
    start = 0
    while start < len(lines) and lines[start].strip() == "":
        start += 1
    if start >= len(lines) or lines[start].strip() != FRONTMATTER_DELIMITER:
        return False
    return not read_frontmatter(lines).present


def _read_top_level_keys(lines: list[str]) -> dict[str, str | None]:
    keys: dict[str, str | None] = {}
    for line in lines:
        match = _TOP_LEVEL_KEY_PATTERN.match(line.rstrip("\r\n"))
        if match is None:
            continue
        key = match.group(1).strip()
        if key in keys:
            continue
        keys[key] = _read_scalar(match.group(2))
    return keys


def _read_scalar(raw: str | None) -> str | None:
    """1 行のスカラを読む。スカラとして読めない・空・null は `None`。"""
    if raw is None:
        return None
    value = raw.strip()
    if value == "" or value[0] in _NON_SCALAR_STARTS:
        return None
    if value[0] in "\"'":
        quote = value[0]
        close = value.find(quote, 1)
        if close < 0:
            return None
        rest = value[close + 1 :]
        if (
            rest != ""
            and not (rest[0] in " \t" and rest.lstrip().startswith("#"))
            and rest.strip() != ""
        ):
            return None
        return value[1:close]
    comment = re.search(r"[ \t]#", value)
    if comment is not None:
        value = value[: comment.start()].rstrip()
    if value in _NULL_WORDS or value == "":
        return None
    return value


def _markdown_parser() -> MarkdownIt:
    return MarkdownIt("commonmark")


def parse_markdown(text: str) -> tuple[list[Token], dict]:
    """markdown-it-py（CommonMark）で解析し、（トークン列、env）を返す。env の `references` が定義の表。"""
    env: dict = {}
    tokens = _markdown_parser().parse(text, env)
    return tokens, env


def read_document(text: str) -> MarkdownDocument:
    """文書を読み、frontmatter・見出し・リファレンスリンクの定義・リンクを返す。"""
    lines = split_lines(text)
    frontmatter = read_frontmatter(lines)
    offset = frontmatter.body_start_line if frontmatter.present else 0
    tokens, env = parse_markdown("".join(lines[offset:]))
    return MarkdownDocument(
        lines=tuple(lines),
        frontmatter=frontmatter,
        headings=_read_headings(tokens, offset, len(lines)),
        references=_read_references(env, offset),
        links=_read_links(tokens, offset),
    )


def _read_headings(
    tokens: list[Token], offset: int, line_count: int
) -> tuple[Heading, ...]:
    raw: list[tuple[int, str, int, int, str]] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        inline = tokens[index + 1]
        start, end = token.map
        raw.append(
            (
                int(token.tag[1:]),
                inline.content,
                start + offset,
                end + offset,
                _display_text(inline),
            )
        )

    anchors = AnchorGenerator()
    headings = []
    for position, (level, content, start, end, display) in enumerate(raw):
        section_end = line_count
        for later_level, _content, later_start, _end, _display in raw[position + 1 :]:
            if later_level <= level:
                section_end = later_start
                break
        words = content.split()
        section_id = words[-1] if words and is_dlid(words[-1]) else None
        headings.append(
            Heading(
                level=level,
                text=content,
                start_line=start,
                end_line=end,
                section_end_line=section_end,
                section_id=section_id,
                anchor=anchors.slug(display),
            )
        )
    return tuple(headings)


def _display_text(inline: Token) -> str:
    """強調・リンクなどの記号を除いた表示文字列（アンカーの元）。"""
    parts: list[str] = []
    for child in inline.children or []:
        if child.type in ("text", "text_special", "code_inline"):
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append("\n")
        elif child.type == "image":
            parts.append(
                "".join(
                    grand.content
                    for grand in child.children or []
                    if grand.type in ("text", "text_special", "code_inline")
                )
            )
    return "".join(parts)


def _read_references(env: dict, offset: int) -> tuple[ReferenceDefinition, ...]:
    definitions = []
    for label, entry in env.get("references", {}).items():
        title = entry.get("title") or ""
        words = title.split()
        last = words[-1] if words else None
        dlid = last if last is not None and is_dlid(last) else None
        preceding = words[-2] if len(words) >= 2 else None
        href = entry["href"]
        path, fragment = split_destination(href)
        start, end = entry["map"]
        definitions.append(
            ReferenceDefinition(
                label=label,
                href=href,
                title=title,
                path=path,
                fragment=fragment,
                dlid=dlid,
                preceding_word=preceding if dlid is not None else None,
                start_line=start + offset,
                end_line=end + offset,
            )
        )
    return tuple(definitions)


def _read_links(tokens: list[Token], offset: int) -> tuple[Link, ...]:
    links = []
    for token in tokens:
        if token.type != "inline":
            continue
        # 段落が複数行のとき、リンクの行は段落の先頭行に、それまでの改行の数を足したものである。
        line = (token.map[0] if token.map else 0) + offset
        for child in token.children or []:
            if child.type in ("softbreak", "hardbreak"):
                line += 1
                continue
            if child.type != "link_open":
                continue
            kind = "autolink" if child.markup == "autolink" else "link"
            links.append(
                Link(
                    kind=kind,
                    href=str(child.attrGet("href") or ""),
                    title=_title(child),
                    line=line,
                )
            )
    return tuple(links)


def _title(token: Token) -> str | None:
    value = token.attrGet("title")
    return None if value is None else str(value)


def has_scheme(href: str) -> bool:
    """スキームの付いた宛先（`https:` など）か。参照として扱わない（DES-008 §2 規則 6）。"""
    return _SCHEME_PATTERN.match(href) is not None


def split_destination(href: str) -> tuple[str, str | None]:
    """宛先を最初の `#` で、（パス、フラグメント）に分け、どちらもパーセント符号化をデコードして返す。

    `#` が無ければフラグメントは `None`。パスが空なら参照元の文書自身を指す（規則 7・8）。
    """
    path, separator, fragment = href.partition("#")
    return unquote(path), (unquote(fragment) if separator else None)


class AnchorGenerator:
    """見出しの表示文字列からアンカーを作る。同じ文書の重複には、2 つ目以降に `-1`、`-2` を付ける。"""

    def __init__(self) -> None:
        self._occurrences: dict[str, int] = {}

    def slug(self, display_text: str) -> str:
        base = anchor_base(display_text)
        slug = base
        while slug in self._occurrences:
            self._occurrences[base] += 1
            slug = f"{base}-{self._occurrences[base]}"
        self._occurrences[slug] = 0
        return slug


def anchor_base(display_text: str) -> str:
    """小文字にし、DES-008 §2 の文字を取り除き、半角空白を `-` に置き換える（重複の連番は付けない）。"""
    kept = []
    for char in display_text.lower():
        if _anchor_removes(char):
            continue
        kept.append("-" if char == " " else char)
    return "".join(kept)


def _anchor_removes(char: str) -> bool:
    category = unicodedata.category(char)
    if category in _ANCHOR_REMOVED_CATEGORIES:
        return True
    if category == "Pd":
        return char != "-"
    if category == "So" and any(
        low <= ord(char) <= high for low, high in _ALPHABETIC_SYMBOL_RANGES
    ):
        return False
    if category[0] == "S":
        return True
    if category[0] == "Z":
        return char != " "
    return False
