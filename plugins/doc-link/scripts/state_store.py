"""管理状態の保存層。`.doc-link/` の[文書情報]と[確定 ToC]を決定論的な JSON で保存・読取りする。

標準ライブラリだけで動くライブラリ用モジュールであり、入口 script を持たない。これを使う
script が PEP 723 の宣言とロックを持つ。保存と読取り、置き換えの機構だけを持ち、[ToC 候補]の検査や
確定の判定は持たない（DES-002 §4、DES-003 §2、DES-005 §5）。

## 配置

- `.doc-link/documents/<符号化した文書 ID>.json`: [文書情報]。文書 ID ごとに 1 ファイル
- `.doc-link/tocs/<符号化した ToC 識別キー>.json`: [確定 ToC]。キーごとに 1 ファイル

## ファイル名への対応

文書 ID と ToC 識別キーは opaque な文字列として扱い、意味を推測しない。ファイル名には、UTF-8 の
バイト列のうち `[A-Za-z0-9_-]` 以外をすべて `%XX`（大文字 16 進）にした文字列を使う。`.` も符号化
するので、`.`・`..`・先頭ドットのファイル名は生じない。対応は単射で、符号化した名前から元の文字列に
戻せる。大文字小文字だけが異なる 2 つの文字列は、大文字小文字を区別しないファイルシステムで同じ
ファイルに当たる。これを黙って上書きしないよう、ファイル内に保存した ID・キーと要求した値の一致を
保存時と読取り時に確かめ、食い違えば失敗にする。符号化後が 200 バイトを超える ID・キーは受け付けない。

## 出力規則

UTF-8、オブジェクトのキーを並べ替え、インデント 2、末尾に改行 1 つ。内容が変わらないファイルは
書き換えない。集合として意味を持つ配列（[確定 ToC] の `documents`・`references`・
`reverse_references`・`sections`・`last_checks`）は、正規の JSON 文字列の順に並べて保存するので、読取り時の順序は
保存時の順序と異なりうる。`sections` の順序は `position` で判断する。それ以外の配列
（`summary`・`tasks`・`keywords`）の順序は内容なので保つ。

## 失敗

読取りの失敗は `StateStoreError` で、`kind` が次のいずれかである。「無い」を空の結果として返さない。

| kind         | 意味                                                                 |
| ------------ | -------------------------------------------------------------------- |
| `missing`    | ファイルが無い                                                       |
| `unreadable` | ファイルがあるが読めない（権限、ディレクトリである、入出力の失敗等） |
| `corrupt`    | 読めたが、UTF-8・JSON・スキーマ・ID の一致のどれかが壊れている       |
| `invalid`    | 呼び出しが不正（ID・キー・skill 名・保存する内容の誤り）             |
| `write`      | 書き込みまたは置き換えに失敗した（旧ファイルは残り、一時ファイルは残らない） |
"""

import json
import os
import re
import tempfile
from pathlib import Path

STATE_DIR_NAME = ".doc-link"
DOCUMENTS_DIR_NAME = "documents"
TOCS_DIR_NAME = "tocs"
FILE_SUFFIX = ".json"
TEMP_ROOT = (".temp", "doc-link")

MAX_ENCODED_NAME_BYTES = 200
_SAFE_BYTES = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)
_SKILL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_ENCODED_NAME = re.compile(r"(?:[A-Za-z0-9_-]|%[0-9A-F]{2})+")

KIND_MISSING = "missing"
KIND_UNREADABLE = "unreadable"
KIND_CORRUPT = "corrupt"
KIND_INVALID = "invalid"
KIND_WRITE = "write"


class StateStoreError(Exception):
    """管理状態の保存・読取りの失敗。`kind` が原因の区別、`path` が対象（無ければ `None`）。"""

    def __init__(self, kind: str, message: str, path: Path | None = None):
        super().__init__(message)
        self.kind = kind
        self.path = path


# --- ファイル名への対応 ---------------------------------------------------


def encode_name(value: str) -> str:
    """文書 ID・ToC 識別キーを、ファイル名に使える文字列へ可逆に符号化する。"""
    if not isinstance(value, str) or value == "":
        raise StateStoreError(
            KIND_INVALID, "ID・キーは空でない文字列でなければならない"
        )
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise StateStoreError(
            KIND_INVALID, f"ID・キーを UTF-8 にできない: {exc}"
        ) from exc
    encoded = "".join(
        chr(byte) if byte in _SAFE_BYTES else f"%{byte:02X}" for byte in raw
    )
    if len(encoded.encode("ascii")) > MAX_ENCODED_NAME_BYTES:
        raise StateStoreError(
            KIND_INVALID,
            f"ID・キーが長すぎる（符号化後 {MAX_ENCODED_NAME_BYTES} バイトまで）",
        )
    return encoded


def decode_name(encoded: str) -> str:
    """`encode_name` の逆。符号化の形でない名前は `corrupt` として失敗する。"""
    if _ENCODED_NAME.fullmatch(encoded) is None:
        raise StateStoreError(KIND_CORRUPT, f"符号化の形でないファイル名: {encoded}")
    raw = bytearray()
    index = 0
    while index < len(encoded):
        if encoded[index] == "%":
            raw.append(int(encoded[index + 1 : index + 3], 16))
            index += 3
        else:
            raw.append(ord(encoded[index]))
            index += 1
    try:
        value = bytes(raw).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StateStoreError(
            KIND_CORRUPT, f"UTF-8 でないファイル名: {encoded}"
        ) from exc
    if encode_name(value) != encoded:
        raise StateStoreError(KIND_CORRUPT, f"正規の符号化でないファイル名: {encoded}")
    return value


def document_info_path(project_root: Path, doc_link_id: str) -> Path:
    return (
        Path(project_root)
        / STATE_DIR_NAME
        / DOCUMENTS_DIR_NAME
        / (encode_name(doc_link_id) + FILE_SUFFIX)
    )


def confirmed_toc_path(project_root: Path, toc_key: str) -> Path:
    return (
        Path(project_root)
        / STATE_DIR_NAME
        / TOCS_DIR_NAME
        / (encode_name(toc_key) + FILE_SUFFIX)
    )


# --- スキーマ（DES-003 §2、REQ-003 §7.1〜7.3 にあるフィールドだけ） ---------


def _is_str(value) -> bool:
    return isinstance(value, str)


def _is_opt_str(value) -> bool:
    return value is None or isinstance(value, str)


def _is_str_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_version(value) -> bool:
    return _is_int(value) or isinstance(value, str)


def _is_object(value) -> bool:
    return isinstance(value, dict)


def _is_list(value) -> bool:
    return isinstance(value, list)


# 各フィールドを (検査関数, 必須か) で表す。ここに無いフィールドは受け付けない。
DOCUMENT_INFO_FIELDS = {
    "doc_link_id": _is_str,
    "path": _is_str,
    "title": _is_str,
    "purpose": _is_str,
    "summary": _is_str_list,
    "tasks": _is_str_list,
    "keywords": _is_str_list,
    "content_hash": _is_str,
}

_DOCUMENT_ENTRY_FIELDS = {"doc_link_id": _is_str, "applied_hash": _is_str}
_SECTION_FIELDS = {
    "doc_link_id": _is_str,
    "section_id": _is_str,
    "heading": _is_str,
    "position": _is_int,
    "content_hash": _is_str,
}
_REFERENCE_CHECK_FIELDS = {
    "scope": _is_str,
    "checked_at": _is_str,
    "result": _is_str,
    "found_path": _is_opt_str,
}
_REFERENCE_FIELDS = {
    "source_doc_id": _is_str,
    "source_section_id": _is_opt_str,
    "position": _is_int,
    "target_doc_id": _is_str,
    "target_section_id": _is_opt_str,
    "recorded_path": _is_str,
    "recorded_content_hash": _is_opt_str,
    "kind": _is_str,
    "check": _is_object,
}
_REVERSE_REFERENCE_FIELDS = {
    "target_doc_id": _is_str,
    "target_section_id": _is_opt_str,
    "source_doc_id": _is_str,
    "source_section_id": _is_opt_str,
}
_LAST_CHECK_RESULTS = frozenset({"success", "failure", "unprocessed"})
_LAST_CHECK_FIELDS = {
    "doc_link_id": _is_str,
    "checked_at": _is_opt_str,
    "result": lambda value: isinstance(value, str) and value in _LAST_CHECK_RESULTS,
}

CONFIRMED_TOC_FIELDS = {
    "toc_key": _is_str,
    "version": _is_version,
    "target_spec": _is_object,
    "documents": _is_list,
    "sections": _is_list,
    "references": _is_list,
    "reverse_references": _is_list,
    "last_checks": _is_list,
}


def _check_fields(value, fields: dict, label: str) -> None:
    if not isinstance(value, dict):
        raise StateStoreError(KIND_CORRUPT, f"{label} がオブジェクトでない")
    missing = sorted(set(fields) - set(value))
    extra = sorted(set(value) - set(fields))
    if missing or extra:
        raise StateStoreError(
            KIND_CORRUPT,
            f"{label} のフィールドが定義と合わない（不足: {missing}、定義外: {extra}）",
        )
    for name, check in fields.items():
        if not check(value[name]):
            raise StateStoreError(KIND_CORRUPT, f"{label} の {name} の型・値が不正")


def validate_document_info(info) -> None:
    """[文書情報]が DES-003 §2 のフィールドを過不足なく持つことを確かめる。"""
    _check_fields(info, DOCUMENT_INFO_FIELDS, "文書情報")


def validate_confirmed_toc(toc) -> None:
    """[確定 ToC]が DES-003 §2 のフィールドを過不足なく持つことを確かめる。"""
    _check_fields(toc, CONFIRMED_TOC_FIELDS, "確定 ToC")
    for name, entry_fields in (
        ("documents", _DOCUMENT_ENTRY_FIELDS),
        ("sections", _SECTION_FIELDS),
        ("references", _REFERENCE_FIELDS),
        ("reverse_references", _REVERSE_REFERENCE_FIELDS),
        ("last_checks", _LAST_CHECK_FIELDS),
    ):
        for index, entry in enumerate(toc[name]):
            _check_fields(entry, entry_fields, f"確定 ToC の {name}[{index}]")
    for index, entry in enumerate(toc["references"]):
        _check_fields(
            entry["check"],
            _REFERENCE_CHECK_FIELDS,
            f"確定 ToC の references[{index}].check",
        )


# --- 決定論的なバイト列 -----------------------------------------------------


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _sorted_set_list(items: list) -> list:
    return sorted(
        items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True)
    )


def serialize(value) -> bytes:
    """同じ内容から常に同じバイト列を返す（UTF-8、キー整列、インデント 2、末尾改行）。"""
    try:
        return (_canonical(value) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise StateStoreError(KIND_INVALID, f"JSON にできない内容: {exc}") from exc


def _normalize_toc(toc: dict) -> dict:
    normalized = dict(toc)
    for name in (
        "documents",
        "sections",
        "references",
        "reverse_references",
        "last_checks",
    ):
        normalized[name] = _sorted_set_list(toc[name])
    return normalized


# --- 置き換えの機構 ----------------------------------------------------------


def _temp_dir(project_root: Path, skill: str) -> Path:
    if not isinstance(skill, str) or _SKILL_NAME.fullmatch(skill) is None:
        raise StateStoreError(KIND_INVALID, f"skill 名が不正: {skill!r}")
    return Path(project_root).joinpath(*TEMP_ROOT, skill)


def write_if_changed(project_root: Path, skill: str, target: Path, data: bytes) -> bool:
    """`data` を `target` へ原子的に置き換える。同じバイト列なら書き換えず `False` を返す。

    一時ファイルは `.temp/doc-link/<skill>/` に書いて `os.replace` で置き換える。失敗したときは
    旧ファイルを残し、一時ファイルを削除して `StateStoreError(write)` を送出する。
    """
    temp_dir = _temp_dir(project_root, skill)
    temp_path: Path | None = None
    try:
        try:
            if target.read_bytes() == data:
                return False
        except FileNotFoundError:
            pass
        temp_dir.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            dir=temp_dir, prefix="state_", suffix=".tmp"
        )
        temp_path = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target)
        temp_path = None
    except OSError as exc:
        raise StateStoreError(
            KIND_WRITE, f"書き込み・置き換えに失敗した: {exc}", target
        ) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return True


def _read_json(path: Path):
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise StateStoreError(KIND_MISSING, f"ファイルが無い: {path}", path) from exc
    except OSError as exc:
        raise StateStoreError(
            KIND_UNREADABLE, f"ファイルを読めない: {path}: {exc}", path
        ) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateStoreError(
            KIND_CORRUPT, f"UTF-8 の JSON として読めない: {path}: {exc}", path
        ) from exc


def _load_validated(path: Path, validate, id_field: str, expected_id: str):
    value = _read_json(path)
    try:
        validate(value)
        if value[id_field] != expected_id:
            raise StateStoreError(
                KIND_CORRUPT,
                f"ファイル内の {id_field} が要求した値と違う: {value[id_field]!r}",
            )
    except StateStoreError as exc:
        if exc.path is not None:
            raise
        raise StateStoreError(exc.kind, f"{exc}: {path}", path) from exc
    return value


def _check_existing_identity(path: Path, id_field: str, expected_id: str) -> None:
    """既存ファイルが別の ID・キーのものなら失敗にする（大文字小文字の衝突の検出）。"""
    try:
        existing = _read_json(path)
    except StateStoreError as exc:
        if exc.kind in (KIND_MISSING, KIND_CORRUPT):
            return  # 無い、または壊れている（置き換えで直る）
        raise
    if (
        isinstance(existing, dict)
        and id_field in existing
        and existing[id_field] != expected_id
    ):
        raise StateStoreError(
            KIND_INVALID,
            f"同じファイル名に別の {id_field} が保存されている: {existing[id_field]!r}",
            path,
        )


# --- 公開する操作 -------------------------------------------------------------


def save_document_info(project_root: Path, skill: str, info: dict) -> bool:
    """[文書情報]を文書 ID ごとのファイルへ保存する。書き換えたとき `True`。"""
    try:
        validate_document_info(info)
    except StateStoreError as exc:
        raise StateStoreError(KIND_INVALID, str(exc)) from exc
    path = document_info_path(project_root, info["doc_link_id"])
    _check_existing_identity(path, "doc_link_id", info["doc_link_id"])
    return write_if_changed(project_root, skill, path, serialize(info))


def load_document_info(project_root: Path, doc_link_id: str) -> dict:
    """[文書情報]を読む。無い・読めない・壊れているは `StateStoreError` で区別して失敗する。"""
    path = document_info_path(project_root, doc_link_id)
    return _load_validated(path, validate_document_info, "doc_link_id", doc_link_id)


def save_confirmed_toc(project_root: Path, skill: str, toc: dict) -> bool:
    """[確定 ToC]をキーごとのファイルへ保存する。書き換えたとき `True`。"""
    try:
        validate_confirmed_toc(toc)
    except StateStoreError as exc:
        raise StateStoreError(KIND_INVALID, str(exc)) from exc
    path = confirmed_toc_path(project_root, toc["toc_key"])
    _check_existing_identity(path, "toc_key", toc["toc_key"])
    return write_if_changed(project_root, skill, path, serialize(_normalize_toc(toc)))


def load_confirmed_toc(project_root: Path, toc_key: str) -> dict:
    """[確定 ToC]を読む。初回構築前は `missing` で失敗する（空の ToC は返さない）。"""
    path = confirmed_toc_path(project_root, toc_key)
    return _load_validated(path, validate_confirmed_toc, "toc_key", toc_key)


def _list_ids(directory: Path) -> list[str]:
    try:
        names = sorted(entry.name for entry in directory.iterdir())
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise StateStoreError(
            KIND_UNREADABLE, f"ディレクトリを読めない: {directory}: {exc}", directory
        ) from exc
    # 管理状態は `.json` のファイルだけで構成する。それ以外の名前（`.DS_Store`、エディタの
    # 一時ファイルなど）は管理状態ではないので、読み飛ばす。
    return [
        decode_name(name[: -len(FILE_SUFFIX)])
        for name in names
        if name.endswith(FILE_SUFFIX)
    ]


def list_document_ids(project_root: Path) -> list[str]:
    """保存済みの[文書情報]の文書 ID を、ファイル名から昇順で返す。保存が一つも無ければ空。

    ディレクトリごと無いことと、ファイルが一つも無いことは同じ「保存なし」であり、読めない
    ディレクトリは失敗にする。`.json` でない名前のファイルは管理状態ではないので数えない。
    """
    return _list_ids(Path(project_root) / STATE_DIR_NAME / DOCUMENTS_DIR_NAME)


def list_toc_keys(project_root: Path) -> list[str]:
    """保存済みの[確定 ToC]の[ToC 識別キー]を、ファイル名から昇順で返す。"""
    return _list_ids(Path(project_root) / STATE_DIR_NAME / TOCS_DIR_NAME)
