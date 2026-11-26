"""[doc-db]での識別（KEY と series）を決める共通モジュール。

DES-011 §4 を実装する。入口 script ではないので、PEP 723 とロックは持たない。

| [doc-db]の項目 | 値                                                                                                         |
| -------------- | ---------------------------------------------------------------------------------------------------------- |
| KEY            | `doc-link.<プロジェクト名>.<8 桁>.<符号化した ToC 識別キー>`                                              |
| series         | `<ワークツリーのディレクトリ名>.<8 桁>`                                                                    |

- プロジェクト名は、共通の git ディレクトリ（`git rev-parse --git-common-dir`）の親ディレクトリ名である。git でない、
  または git を実行できないときは、プロジェクトルートの名前にする。KEY に使える文字の制限を[doc-db]の実装で確認して
  いないので、英数字・`_`・`-` 以外は `_` に置き換え、40 文字までにする（同名の別プロジェクトとの区別は 8 桁が持つ）
- KEY の 8 桁は、共通の git ディレクトリ（git でなければプロジェクトルート）の絶対パスの SHA-256 の先頭である。同じ
  プロジェクトの全ワークツリーが、同じ KEY を使う
- series の 8 桁は、プロジェクトルートの絶対パスの SHA-256 の先頭である。ワークツリーごとに別の series になる
- [ToC 識別キー]の符号化は、管理状態のファイル名と同じ規則（`state_store.encode_name`）である
"""

import hashlib
import re
import subprocess
from pathlib import Path

import state_store

KEY_PREFIX = "doc-link"
DIGEST_LENGTH = 8
NAME_LIMIT = 40
GIT_TIMEOUT_SECONDS = 5

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def run_git(arguments: list[str], cwd: Path):
    """git を実行し、`(終了コード, 標準出力)` を返す。実行できないときは `(None, "")`。テストが差し替える境界。"""
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return completed.returncode, completed.stdout


def _digest(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:DIGEST_LENGTH]


def _safe(name: str) -> str:
    cleaned = _UNSAFE.sub("_", name)[:NAME_LIMIT]
    return cleaned or "project"


def _common_git_dir(root: Path, runner) -> Path | None:
    code, output = runner(["rev-parse", "--git-common-dir"], root)
    line = output.strip()
    if code != 0 or not line:
        return None
    path = Path(line)
    return (path if path.is_absolute() else root / path).resolve()


def project_identity(project_root: str | Path, runner=run_git) -> tuple[str, str]:
    """プロジェクトの（名前, 8 桁）を返す。同じプロジェクトの全ワークツリーで同じになる。"""
    root = Path(project_root).resolve()
    common = _common_git_dir(root, runner)
    if common is None:
        return _safe(root.name), _digest(root)
    base = common.parent if common.name == ".git" else common
    return _safe(base.name), _digest(common)


def key_for(project_root: str | Path, toc_key: str, runner=run_git) -> str:
    """[doc-db]の KEY。符号化できない[ToC 識別キー]（空・長すぎる）は `state_store.StateStoreError`。"""
    name, digest = project_identity(project_root, runner)
    return f"{KEY_PREFIX}.{name}.{digest}.{state_store.encode_name(toc_key)}"


def series_for(project_root: str | Path) -> str:
    """[doc-db]の series。ワークツリー（プロジェクトルート）ごとに決まる。"""
    root = Path(project_root).resolve()
    return f"{_safe(root.name)}.{_digest(root)}"
