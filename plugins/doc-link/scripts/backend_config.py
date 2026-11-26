"""検索基盤の強制スイッチの設定ファイル（`.doc-link/config.json`）を読む共通モジュール（読むだけで、書かない）。

DES-011 §2.1、REQ-006 FR-020・AC-048（D-065）を実装する。入口 script ではないので、PEP 723 とロックは持たない。
読むのは、基盤判定（`backend_select`）だけである。

## 設定ファイル

プロジェクトルート直下の `.doc-link/config.json`。JSON のオブジェクト 1 つで、キーは `backend` だけである。
値は `"auto"`（[doc-db]を先に試す）か `"toc"`（[doc-db]へ接続も起動もせず、[ToC]を使う）。

- ファイルが無い、またはキー `backend` が無いときは、`auto` である
- 読めない（権限・ディレクトリである）、UTF-8 でない、JSON として解釈できない、オブジェクトでない、
  未知のキーがある、`backend` の値が定義外のときは、`BackendConfigError` である。既定へ黙って戻さない
  （誤記のまま[doc-db]へ接続しないため）。原因（ファイルと箇所）を自然文の配列で持つ
- 管理状態（`.doc-link/documents/`・`.doc-link/tocs/`）の走査は、この直下のファイルを読まない
"""

import json
from dataclasses import dataclass
from pathlib import Path

import state_store

CONFIG_NAME = "config.json"
KEY_BACKEND = "backend"

BACKEND_AUTO = "auto"
BACKEND_TOC = "toc"
BACKENDS = (BACKEND_AUTO, BACKEND_TOC)

ALLOWED_KEYS = frozenset({KEY_BACKEND})


class BackendConfigError(Exception):
    """設定ファイルを受理できない。`errors` は自然文の配列。"""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class BackendConfig:
    """読んだ設定。`backend` は `auto` か `toc`。`present` は、設定ファイルがあったか。"""

    backend: str
    present: bool


def config_path(project_root: str | Path) -> Path:
    return Path(project_root) / state_store.STATE_DIR_NAME / CONFIG_NAME


def load(project_root: str | Path) -> BackendConfig:
    """設定を読む。ファイルが無い・キーが無いときは `auto`。受理できないときは `BackendConfigError`。"""
    path = config_path(project_root)
    shown = f"{state_store.STATE_DIR_NAME}/{CONFIG_NAME}"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return BackendConfig(BACKEND_AUTO, False)
    except OSError as exc:
        raise BackendConfigError([f"{shown} を読めない: {exc}"]) from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise BackendConfigError([f"{shown} が UTF-8 でない: {exc}"]) from exc
    except json.JSONDecodeError as exc:
        raise BackendConfigError(
            [
                f"{shown} が JSON として解釈できない（{exc.lineno} 行 {exc.colno} 列）: {exc.msg}"
            ]
        ) from exc
    if not isinstance(data, dict):
        raise BackendConfigError([f"{shown} は JSON のオブジェクトでなければならない"])
    unknown = sorted(set(data) - ALLOWED_KEYS)
    if unknown:
        raise BackendConfigError(
            [
                f"{shown} に定義に無いキーがある: {', '.join(unknown)}（使えるキーは {KEY_BACKEND} だけ）"
            ]
        )
    if KEY_BACKEND not in data:
        return BackendConfig(BACKEND_AUTO, True)
    value = data[KEY_BACKEND]
    if not isinstance(value, str) or value not in BACKENDS:
        raise BackendConfigError(
            [
                f'{shown} の {KEY_BACKEND} は "{BACKEND_AUTO}" か "{BACKEND_TOC}" でなければならない'
            ]
        )
    return BackendConfig(value, True)
