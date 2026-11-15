# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "markdown-it-py>=4.2.0",
# ]
#
# [tool.uv]
# exclude-newer = "3 days"
# ///
"""実行環境（Python と markdown-it-py）が使えることを確かめ、版を JSON で返す。

plugins/doc-link/scripts/ に置く script の雛形を兼ねる。以降の script は次の形に倣う。

- PEP 723 のインラインメタデータと、script ごとのロックファイル（`<script>.py.lock`）を持つ
- 共通モジュール（同じディレクトリの `script_output.py`）を import して結果を出す
- 一時ファイルはプロジェクトルート直下の `.temp/doc-link/<skill>/` に置く（DES-002 §4）。
  OS の一時ディレクトリ（`tempfile.mkdtemp` の既定の置き場など）は使わない

## 終了コード

| code | 意味                             |
| ---- | -------------------------------- |
| 0    | 環境を確認し、版を返した         |
| 1    | 区別のないエラー                 |
| 2    | 引数を受理できない（`argparse`） |
"""

import argparse
import importlib.metadata
import sys

import script_output


def collect_environment() -> dict:
    """使っている Python と markdown-it-py の版を返す。解決できなければ例外を送出する。"""
    return {
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "markdown_it_py": importlib.metadata.version("markdown-it-py"),
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    try:
        environment = collect_environment()
    except importlib.metadata.PackageNotFoundError:
        return script_output.emit_error(["markdown-it-py が解決できない"])
    return script_output.emit_result(environment)


if __name__ == "__main__":
    sys.exit(main())
