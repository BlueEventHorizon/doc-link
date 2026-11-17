"""script の標準出力の契約を実装する共通モジュール。

終了コードと標準出力は、`0` のとき結果の JSON、`1` のときエラーの JSON（`errors` は常に配列で、
要素は自然文）とする。`2` は `argparse` が自ら返すので、ここでは扱わない。`3` 以上は、それを
返す script が自身の docstring で宣言する。このモジュールは `0` と `1` だけを返す。
"""

import json
import sys

EXIT_OK = 0
EXIT_ERROR = 1


def emit_result(result: dict) -> int:
    """結果の JSON を標準出力へ書き、終了コード 0 を返す。"""
    sys.stdout.write(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
    return EXIT_OK


def emit_error(errors: list[str]) -> int:
    """エラーの JSON を標準出力へ書き、終了コード 1 を返す。"""
    sys.stdout.write(
        json.dumps({"errors": errors}, ensure_ascii=False, indent=2) + "\n"
    )
    return EXIT_ERROR
