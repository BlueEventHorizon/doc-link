# /// script
# requires-python = ">=3.15"
# dependencies = []
# ///
"""DLID の認識と発行を行うプラグイン共通の部品。

DLID は、固定プレフィックス `DLID-` と、小文字の Crockford Base32（`0-9` と、
`a-z` から `i`・`l`・`o`・`u` を除いた 32 文字）12 文字から成る
（DES-008 §1、REQ-002 FR-001、D-028）。

- 認識: 値が単一の文字列で、上の形式に完全一致するときだけ DLID とする。
  大文字小文字を区別し、前後の空白も許さない。それ以外の値（キーの欠落・null・
  空文字列・空白だけ・str 以外の型・長さ違い・プレフィックス違い・不正文字・
  大文字）はすべて「文書 ID が存在しない」の 1 分類とし、形式不正という別分類を
  作らない（DES-008 §1、REQ-002 FR-002・AC-012、D-003）。
- 発行: `secrets` による 60 ビットの暗号論的乱数を 12 文字で表し、`DLID-` を
  前置する。値に文書の意味を持たせず、発行時に既存の ID と照合しない（D-028、D-030）。

frontmatter の切り出しと解析、アンカー行の抽出は本部品の範囲外であり（`markdown_parse`
が行う）、呼び出し側が取り出した値を `recognize_dlid` に渡す。
"""

import re
import secrets

DLID_PREFIX = "DLID-"
"""DLID の固定プレフィックス。"""

CROCKFORD_BASE32_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
"""小文字の Crockford Base32 の 32 文字（`i`・`l`・`o`・`u` を除く）。"""

DLID_VALUE_LENGTH = 12
"""DLID の値部分の文字数。"""

_BITS_PER_CHAR = 5
_RANDOM_BITS = DLID_VALUE_LENGTH * _BITS_PER_CHAR  # 60 ビット

_DLID_PATTERN = re.compile(
    re.escape(DLID_PREFIX)
    + "["
    + re.escape(CROCKFORD_BASE32_ALPHABET)
    + "]{"
    + str(DLID_VALUE_LENGTH)
    + "}"
)


def recognize_dlid(value: object) -> str | None:
    """値を DLID として認識する。

    Args:
        value: frontmatter の最上位のキーだけを読む最小限の解析（`markdown_parse`）で
            取り出した `doc_link_id` の値、または
            アンカー行の id 属性の文字列。キーが欠落しているときは None を渡す。

    Returns:
        認識できたときは、その DLID の文字列。認識できないときは None
        （「文書 ID が存在しない」を表す。認識できない理由は区別しない）。
    """
    if not isinstance(value, str):
        return None
    if _DLID_PATTERN.fullmatch(value) is None:
        return None
    return value


def issue_dlid() -> str:
    """新しい DLID を発行する。

    Returns:
        `DLID-` と、60 ビットの暗号論的乱数を小文字の Crockford Base32 で
        12 文字に表した値部分を連結した文字列。
    """
    number = secrets.randbits(_RANDOM_BITS)
    chars = []
    for shift in range(_RANDOM_BITS - _BITS_PER_CHAR, -1, -_BITS_PER_CHAR):
        chars.append(CROCKFORD_BASE32_ALPHABET[(number >> shift) & 0b11111])
    return DLID_PREFIX + "".join(chars)
