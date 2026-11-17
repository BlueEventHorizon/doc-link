"""[AI 生成フィールド]の検証器（ライブラリ用モジュール。入口 script ではない）。

生成結果（フィールド名と値の対応）の型・必須値・長さ・要素数を検査し、受理または拒否理由を返す
（DES-008 §4、REQ-003 §7.4、要件 D-044）。

- 記述上限 `L` は目的が 200 文字、内容概要・適用される作業・検索用キーワードが 10 要素である
- 内部許容上限は `H = floor(L × 1.3)`。`L` 超・`H` 以下を受理し、`H` 超を拒否する
- 文字数は Unicode のコードポイント数（`len(str)`）で数える
- 配列の各要素の文字数とタイトルの文字数は制限しない
- 要素数の下限は、内容概要 5、適用される作業 1、検索用キーワード 5 である
- 拒否理由には、フィールド名と記述上限 `L` だけを含める。`H`・係数・余白・実際の長さは含めない
  （DES-002 §3 の 2、NFR-008）
- 再試行の制御は持たない。拒否は、その文書の生成失敗として呼び出し側へ返す（DES-004 B-08）
- タイトルは、見出しから取得できなければ生成したものを受け取って検証する。見出しの読取りは行わない
"""

import math

# フィールドごとの記述上限 L（要件 D-044）。この値だけが情報生成 AI へ提示してよい値である。
PURPOSE_LIMIT = 200
ARRAY_LIMIT = 10

# 内部許容上限の係数。理由や報告の文字列へ出さない。
_TOLERANCE_FACTOR = 1.3

# 配列フィールドの要素数の下限（DES-008 §4）。
_ARRAY_MINIMUMS = {
    "summary": 5,
    "applicable_tasks": 1,
    "keywords": 5,
}

# フィールド名（生成結果のキー）と、拒否理由に書く表示名。
_FIELD_LABELS = {
    "title": "title",
    "purpose": "purpose",
    "summary": "summary",
    "applicable_tasks": "applicable_tasks",
    "keywords": "keywords",
}


def internal_limit(limit: int) -> int:
    """記述上限 L から内部許容上限 H を求める。"""
    return math.floor(limit * _TOLERANCE_FACTOR)


def _validate_title(value: object) -> list[str]:
    if not isinstance(value, str):
        return ["title must be a string"]
    if not value.strip():
        return ["title must not be empty"]
    return []


def _validate_purpose(value: object) -> list[str]:
    if not isinstance(value, str):
        return ["purpose must be a string"]
    if not value.strip():
        return ["purpose must not be empty"]
    if len(value) > internal_limit(PURPOSE_LIMIT):
        return [f"purpose must be at most {PURPOSE_LIMIT} characters"]
    return []


def _validate_array(name: str, value: object) -> list[str]:
    if not isinstance(value, list):
        return [f"{name} must be an array"]
    if any(not isinstance(item, str) for item in value):
        return [f"{name} must contain only strings"]
    if len(value) < _ARRAY_MINIMUMS[name]:
        return [f"{name} must have at least {_ARRAY_MINIMUMS[name]} items"]
    if len(value) > internal_limit(ARRAY_LIMIT):
        return [f"{name} must have at most {ARRAY_LIMIT} items"]
    return []


def validate_generated_fields(result: object) -> list[str]:
    """生成結果を検証し、拒否理由の一覧を返す。空なら受理である。

    `result` はフィールド名（title・purpose・summary・applicable_tasks・keywords）と値の対応。
    欠落したフィールドと、型違い・下限未満・`H` 超のフィールドを、フィールドごとに報告する。
    """
    if not isinstance(result, dict):
        return ["generated result must be an object"]
    reasons: list[str] = []
    for name in _FIELD_LABELS:
        if name not in result:
            reasons.append(f"{name} is required")
            continue
        value = result[name]
        if name == "title":
            reasons.extend(_validate_title(value))
        elif name == "purpose":
            reasons.extend(_validate_purpose(value))
        else:
            reasons.extend(_validate_array(name, value))
    return reasons
