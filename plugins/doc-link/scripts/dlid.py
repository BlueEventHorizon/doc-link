"""DLID の発行と、複数の文書にまたがる DLID の重複の検出を持つ共通モジュール。

DES-008 §1 と REQ-001 D-028・D-029 の、発行と重複検出の部分を実装する。入口 script ではないので、PEP 723 と
ロックは持たない。DLID の形式の認識は `markdown_reader.is_dlid` を使い、ここでは再実装しない。

このモジュールが持たないもの（別タスクの範囲）: 管理状態の全キーとの照合、原本の候補の判定・提示、再発行、
原本への書き込み。重複は報告するだけである。

仕様の解釈（設計書が値や形式を定めていない点）

- 発行は `secrets.randbits(60)` を、小文字の Crockford Base32（`i`・`l`・`o`・`u` を除く 32 文字）の 12 文字に
  表し、`DLID-` を前置する。発行時に既存の ID と照合せず、文書の内容・パス・タイトルから計算しない（D-030）
- [DLID]として扱う箇所は、frontmatter の `doc_link_id` と、見出しの行の末尾の語（`Heading.section_id`）だけである。
  リンクの title の[DLID]は含めない
- [文書 ID]と[セクション ID]は同じ[DLID]の空間にあるものとして扱う（D-029 は「同じ[DLID]（文書の ID または
  セクションの ID）が複数の箇所にある」と定める）。文書の ID と見出しの ID が同じ値でも重複として報告する
- 同じ文書の中の複数の見出しが同じ[DLID]を持つ場合も重複として報告する。同じパスの文書が入力に複数回現れたとき
  は、別の文書として数える
- 文書の ID の位置の `line` は `None` にする（frontmatter の中の位置は読取りの結果が持たない）。見出しの `line` は
  見出しの開始行（0 始まり）である
"""

import secrets
from collections.abc import Iterable
from dataclasses import dataclass

from markdown_reader import is_dlid, read_document

DLID_PREFIX = "DLID-"
CROCKFORD_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
DLID_VALUE_LENGTH = 12
DLID_BITS = 60

KIND_DOCUMENT = "document"
KIND_SECTION = "section"


def issue_dlid() -> str:
    """60 ビットの暗号論的乱数から DLID を 1 つ発行する。"""
    number = secrets.randbits(DLID_BITS)
    chars = []
    for _ in range(DLID_VALUE_LENGTH):
        chars.append(CROCKFORD_ALPHABET[number & 0x1F])
        number >>= 5
    value = DLID_PREFIX + "".join(reversed(chars))
    if not is_dlid(value):
        raise RuntimeError(f"発行した値が DLID の形式を満たさない: {value}")
    return value


@dataclass(frozen=True)
class DlidLocation:
    """[DLID]のある箇所。`kind` は `document`（doc_link_id）か `section`（見出しの末尾の語）。"""

    path: str
    kind: str
    line: int | None
    heading_text: str | None


@dataclass(frozen=True)
class DuplicateDlid:
    dlid: str
    locations: tuple[DlidLocation, ...]


def find_duplicates(documents: Iterable[tuple[str, str]]) -> list[DuplicateDlid]:
    """（パス、本文）の組から、複数の箇所にある[DLID]を、該当するすべての箇所を添えて返す。

    返す順は、[DLID]の昇順。箇所は入力の順と見出しの出現順。
    """
    found: dict[str, list[DlidLocation]] = {}
    for path, text in documents:
        document = read_document(text)
        doc_id = document.frontmatter.doc_link_id
        if doc_id is not None:
            found.setdefault(doc_id, []).append(
                DlidLocation(
                    path=path, kind=KIND_DOCUMENT, line=None, heading_text=None
                )
            )
        for heading in document.headings:
            if heading.section_id is not None:
                found.setdefault(heading.section_id, []).append(
                    DlidLocation(
                        path=path,
                        kind=KIND_SECTION,
                        line=heading.start_line,
                        heading_text=heading.text,
                    )
                )
    return [
        DuplicateDlid(dlid=dlid, locations=tuple(locations))
        for dlid, locations in sorted(found.items())
        if len(locations) > 1
    ]
