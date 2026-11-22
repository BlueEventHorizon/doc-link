"""[内容ハッシュ]の算出（リファレンスリンクの定義の行を除く）と、title の記録語の形式判定を持つ共通モジュール。

DES-008 §3・DES-009 §1 と REQ-001 D-039 を実装する。入口 script ではないので、PEP 723 とロックは持たない。
文書の解析は `markdown_reader.read_document` の結果を使い、独自の正規表現でブロック構造を判定しない。

このモジュールが持たないもの（別タスクの範囲）: [正式な参照]の抽出、[ToC]との照合、原本への書き込み。

[内容ハッシュ]は、原文の UTF-8 バイト列の SHA-256 を小文字の 16 進 64 文字で表したもの。正規化はしない。
title に記録するのは、その先頭 12 文字（REQ-001 D-058）。title に書く値は `title_value`、記録との比較は
`record_matches` だけが行う。[ToC]・管理状態は 64 文字のままである。
文書全体はファイル全体（frontmatter を含む）、セクションは `Heading.start_line` から `Heading.section_end_line`
の直前までの原文を対象にする。

除く範囲（DES-008 §3）

- 除くのは、リファレンスリンクの定義の行 `[start_line, end_line)` の全体である（行末の改行を含む）。
  [正式な参照]かどうか、title の有無、リンク先のスキームの有無を問わない。title が次の行に続く定義は、
  その行も `end_line` の内側なので除く
- 算出の範囲と定義の行が一部だけ重なるときは、重なった行だけを除く
- 定義の前後の空行と、本文のリンク（インラインリンクの title を含む）は除かない
- 同じラベルの 2 つ目以降の定義は、`MarkdownDocument.references` に現れないので、除かない
"""

import hashlib
import re

from markdown_reader import MarkdownDocument, ReferenceDefinition, read_document

RECORD_LENGTH = 12
_RECORD_WORD_PATTERN = re.compile(r"[0-9a-f]{%d}" % RECORD_LENGTH)


def is_record_word(word: str | None) -> bool:
    """title に記録した[内容ハッシュ]の語か（12 桁の小文字 16 進。大文字は不可）。"""
    return word is not None and _RECORD_WORD_PATTERN.fullmatch(word) is not None


def title_value(content_hash: str) -> str:
    """[内容ハッシュ]（64 桁）から、title に書く値を得る。title に書く値は、この関数だけが決める（REQ-001 D-058）。"""
    return content_hash[:RECORD_LENGTH]


def record_matches(record: str | None, content_hash: str) -> bool:
    """title に記録した値が、[内容ハッシュ]（64 桁）と一致するか。記録なし（`None`）は一致しない。"""
    return record is not None and record == title_value(content_hash)


def read_recorded_hash(definition: ReferenceDefinition) -> str | None:
    """定義の title に記録した[内容ハッシュ]を返す。記録なしは `None`。"""
    word = definition.preceding_word
    return word if is_record_word(word) else None


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def document_content_hash(text: str) -> str:
    """文書全体の[内容ハッシュ]（リファレンスリンクの定義の行を除く）。"""
    document = read_document(text)
    return _hash_range(document, 0, len(document.lines))


def section_content_hashes(text: str) -> list[str]:
    """文書の見出しごと（出現順）のセクションの[内容ハッシュ]（リファレンスリンクの定義の行を除く）。"""
    document = read_document(text)
    return [
        _hash_range(document, heading.start_line, heading.section_end_line)
        for heading in document.headings
    ]


def _hash_range(document: MarkdownDocument, start: int, end: int) -> str:
    lines = document.lines
    pieces: list[str] = []
    cursor = start
    for definition in sorted(document.references, key=lambda item: item.start_line):
        first = max(definition.start_line, cursor)
        last = min(definition.end_line, end)
        if first >= last:
            continue
        pieces.append("".join(lines[cursor:first]))
        cursor = last
    pieces.append("".join(lines[cursor:end]))
    return hash_bytes("".join(pieces).encode("utf-8"))
