"""現在の UTC の時刻を、秒までの ISO 8601 の文字列で返す共通モジュール。

`checked_at` など、結果に記録する時刻を得る。入口 script ではないので、PEP 723 とロックは持たない。
"""

from datetime import datetime, timezone


def utc_now() -> str:
    """現在の UTC の時刻を、秒までの ISO 8601 の文字列で返す。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
