"""[正式な参照]の抽出を持つ共通モジュール（何も書き込まない）。

DES-007 §1・DES-008 §2 と REQ-001 D-032 を実装する。check-links・check-impact・index-docs など複数の SKILL の
script が import して使う。入口 script ではないので、PEP 723 とロックは持たない（使う script が宣言する）。
文書の解析は `markdown_reader.read_document` の結果を使い、title の記録語の形式判定は
`content_hash.read_recorded_hash` を使う。独自の正規表現でブロック構造を判定しない。

[正式な参照]は、リファレンスリンクの定義のうち、title の最後の語が[DLID]であるものである。
次のものは[正式な参照]にしない（判定は `markdown_reader` の結果に従う）: title に[DLID]の無い定義、インラインリンク、
画像、autolink・HTML の `<a>`、スキーム付きの宛先、コードブロック・HTML ブロック内の定義、定義の無いラベルを使った
リンク、宛先に空白を含むなど成立しない書き方。[DLID]入りの title を持つインラインリンクは check-links が報告する。

このモジュールが持たないもの（別の部品の範囲）: 指定ディレクトリの実走査による検査（`reference_check`）、
参照記述の比較、[ToC]との照合。

仕様の解釈（設計書が値や形式を定めていない点）

- 参照先が文書の[DLID]か[セクション ID]かは、抽出では区別しない（走査の結果で決まる）
- `line` は、定義の開始行の 0 始まりの行番号（文書全体。frontmatter を含む）
- 参照は定義の開始行の順に返す
"""

from dataclasses import dataclass

from content_hash import read_recorded_hash
from markdown_reader import MarkdownDocument, has_scheme, read_document


@dataclass(frozen=True)
class FormalReference:
    """[正式な参照]。`recorded_hash` は title に記録した[内容ハッシュ]で、無ければ `None`（記録なし）。

    `path`・`fragment` は、パーセント符号化をデコードした値。`path` が空なら参照元の文書自身を指す。
    `fragment` は `#` が無ければ `None`。
    """

    dlid: str
    recorded_hash: str | None
    label: str
    path: str
    fragment: str | None
    line: int

    def to_dict(self) -> dict:
        return {
            "dlid": self.dlid,
            "recorded_hash": self.recorded_hash,
            "label": self.label,
            "path": self.path,
            "fragment": self.fragment,
            "line": self.line,
        }


def extract_from_document(document: MarkdownDocument) -> tuple[FormalReference, ...]:
    """解析済みの文書から[正式な参照]を取り出す。"""
    found = []
    for definition in document.references:
        if definition.dlid is None or has_scheme(definition.href):
            continue
        found.append(
            FormalReference(
                dlid=definition.dlid,
                recorded_hash=read_recorded_hash(definition),
                label=definition.label,
                path=definition.path,
                fragment=definition.fragment,
                line=definition.start_line,
            )
        )
    found.sort(key=lambda reference: reference.line)
    return tuple(found)


def extract_references(text: str) -> tuple[FormalReference, ...]:
    """文書の原文から[正式な参照]を取り出す。"""
    return extract_from_document(read_document(text))
