"""管理状態の保存層。`.doc-link/` の[文書情報]と[確定 ToC]を決定論的な JSON で保存・読取りする。

標準ライブラリだけで動くライブラリ用モジュールであり、入口 script を持たない。これを使う
script が PEP 723 の宣言とロックを持つ。保存と読取り、置き換えの機構だけを持ち、[ToC 候補]の検査や
確定の判定は持たない（DES-002 §4、DES-003 §2、DES-005 §5）。

## 配置

- `.doc-link/documents/<符号化した文書 ID>.json`: [文書情報]。文書 ID ごとに 1 ファイル
- `.doc-link/tocs/<符号化した ToC 識別キー>.json`: [確定 ToC]のうち、キーごとに決まる値。キーごとに 1 ファイル

## 保存の持ち方

文書ごとに決まる値は、すべて[文書情報]のファイルが持つ。同じ文書の値は、[ToC 識別キー]が違っても 1 つである。

- [文書情報]のファイル: 要約の 8 項目（`doc_link_id`・`path`・`title`・`purpose`・`summary`・`tasks`・`keywords`・
  `content_hash`）と、構築が確定した 4 項目（`applied_hash`・`sections`・`references`・`last_check`）。
  `content_hash` は要約を生成した時点、`applied_hash` は構築が確定した時点の[内容ハッシュ]である。
  どの[確定 ToC]にもまだ入っていない文書は、確定した 4 項目が `UNCONFIRMED_FACTS` の値である
- [確定 ToC]のファイル: `toc_key`・`version`・`target_spec`・`documents`（所属する文書 ID の配列）・
  `reverse_references`

`load_confirmed_toc` は、[確定 ToC]のファイルと、所属する文書の[文書情報]から、`CONFIRMED_TOC_FIELDS` の形の
[確定 ToC]を組み立てて返す。`save_confirmed_toc` は、同じ形の[確定 ToC]を受け取り、文書ごとの値を[文書情報]へ
書いてから、[確定 ToC]のファイルを置き換える。途中で失敗したときは[確定 ToC]のファイルを置き換えない。
書き終えた[文書情報]は戻さない。

`save_document_info` は、確定した 4 項目を持たない[文書情報]（要約の 8 項目だけ）を受け取ったとき、保存済みの
4 項目を保つ。保存が無ければ `UNCONFIRMED_FACTS` の値にする。

## ひとつ前の保存形式

ひとつ前の形式は、文書ごとの値を[確定 ToC]のファイルが持ち、[文書情報]のファイルが要約の 8 項目だけを持つ。
同じ情報を欠けなく持つので、そのまま読む。[確定 ToC]のファイルは `CONFIRMED_TOC_FIELDS` の形そのものであり、
[文書情報]は確定した 4 項目が無いものとして読む。保存はつねに現在の形式で行うので、次の構築で書き直される。

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
`reverse_references`・`sections`・`last_checks`、[文書情報]の `sections`・`references`）は、正規の JSON 文字列の
順に並べて保存し、読取りでも同じ順に並べて返すので、読取り時の順序は保存時の順序と異なりうる。`sections` の
順序は `position` で判断する。それ以外の配列（`summary`・`tasks`・`keywords`）の順序は内容なので保つ。

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


def _is_opt_object(value) -> bool:
    return value is None or isinstance(value, dict)


# 各フィールドを検査関数で表す。ここに無いフィールドは受け付けない。
_SUMMARY_FIELDS = {
    "doc_link_id": _is_str,
    "path": _is_str,
    "title": _is_str,
    "purpose": _is_str,
    "summary": _is_str_list,
    "tasks": _is_str_list,
    "keywords": _is_str_list,
    "content_hash": _is_str,
}
_FACT_FIELDS = {
    "applied_hash": _is_opt_str,
    "sections": _is_list,
    "references": _is_list,
    "last_check": _is_opt_object,
}
DOCUMENT_INFO_FIELDS = {**_SUMMARY_FIELDS, **_FACT_FIELDS}

# どの[確定 ToC]にもまだ入っていない文書の、確定した 4 項目の値。
UNCONFIRMED_FACTS = {
    "applied_hash": None,
    "sections": [],
    "references": [],
    "last_check": None,
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

# 保存するファイルの形。文書ごとの値は[文書情報]のファイルが持つので、所属文書を名指す項目を除く。
_TOC_FILE_FIELDS = {
    "toc_key": _is_str,
    "version": _is_version,
    "target_spec": _is_object,
    "documents": _is_str_list,
    "reverse_references": _is_list,
}
_INFO_SECTION_FIELDS = {
    name: check for name, check in _SECTION_FIELDS.items() if name != "doc_link_id"
}
_INFO_REFERENCE_FIELDS = {
    name: check for name, check in _REFERENCE_FIELDS.items() if name != "source_doc_id"
}
_INFO_LAST_CHECK_FIELDS = {
    name: check for name, check in _LAST_CHECK_FIELDS.items() if name != "doc_link_id"
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
    for index, entry in enumerate(info["sections"]):
        _check_fields(entry, _INFO_SECTION_FIELDS, f"文書情報の sections[{index}]")
    for index, entry in enumerate(info["references"]):
        _check_fields(entry, _INFO_REFERENCE_FIELDS, f"文書情報の references[{index}]")
        _check_fields(
            entry["check"],
            _REFERENCE_CHECK_FIELDS,
            f"文書情報の references[{index}].check",
        )
    if info["last_check"] is not None:
        _check_fields(
            info["last_check"], _INFO_LAST_CHECK_FIELDS, "文書情報の last_check"
        )


def _validate_toc_file(toc) -> None:
    _check_fields(toc, _TOC_FILE_FIELDS, "確定 ToC")
    for index, entry in enumerate(toc["reverse_references"]):
        _check_fields(
            entry,
            _REVERSE_REFERENCE_FIELDS,
            f"確定 ToC の reverse_references[{index}]",
        )


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


_TOC_SET_LISTS = (
    "documents",
    "sections",
    "references",
    "reverse_references",
    "last_checks",
)


def _normalize_toc(toc: dict) -> dict:
    normalized = dict(toc)
    for name in _TOC_SET_LISTS:
        normalized[name] = _sorted_set_list(toc[name])
    return normalized


def _normalize_info(info: dict) -> dict:
    normalized = dict(info)
    for name in ("sections", "references"):
        normalized[name] = _sorted_set_list(info[name])
    return normalized


def _without(entry: dict, name: str) -> dict:
    return {key: value for key, value in entry.items() if key != name}


def _facts_from_toc(toc: dict, doc_link_id: str, applied_hash: str) -> dict:
    """[確定 ToC]のうち、その文書に決まる値を、[文書情報]の確定した 4 項目の形で返す。"""
    checks = [
        _without(entry, "doc_link_id")
        for entry in toc["last_checks"]
        if entry["doc_link_id"] == doc_link_id
    ]
    return {
        "applied_hash": applied_hash,
        "sections": [
            _without(entry, "doc_link_id")
            for entry in toc["sections"]
            if entry["doc_link_id"] == doc_link_id
        ],
        "references": [
            _without(entry, "source_doc_id")
            for entry in toc["references"]
            if entry["source_doc_id"] == doc_link_id
        ],
        "last_check": checks[0] if checks else None,
    }


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


def _without_legacy_times(value):
    """旧形式の記録にある検査の時点（`checked_at`）を取り除く。

    かつては、文書ごとの `last_check` と、参照ごとの `check` に、検査の時点を記録していた。
    今は記録しないので、旧形式のファイルは、時点を無視して読む。書くときは時点を持たせない
    （検証が定義外として拒否する）。
    """
    if not isinstance(value, dict):
        return value

    def _drop(entry):
        if isinstance(entry, dict) and "checked_at" in entry:
            return {key: item for key, item in entry.items() if key != "checked_at"}
        return entry

    converted = dict(value)
    if "last_check" in converted:
        converted["last_check"] = _drop(converted["last_check"])
    if isinstance(converted.get("last_checks"), list):
        converted["last_checks"] = [_drop(entry) for entry in converted["last_checks"]]
    if isinstance(converted.get("references"), list):
        converted["references"] = [
            (
                {**entry, "check": _drop(entry["check"])}
                if isinstance(entry, dict) and "check" in entry
                else entry
            )
            for entry in converted["references"]
        ]
    return converted


def _load_validated(path: Path, validate, id_field: str, expected_id: str):
    value = _without_legacy_times(_read_json(path))
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


def _with_facts(value):
    """ひとつ前の形式の[文書情報]（要約の 8 項目だけ）に、確定した 4 項目が無いことを表す値を足す。"""
    if isinstance(value, dict) and set(value) == set(_SUMMARY_FIELDS):
        return {**value, **_unconfirmed_facts()}
    return value


def _unconfirmed_facts() -> dict:
    return {
        name: list(value) if isinstance(value, list) else value
        for name, value in UNCONFIRMED_FACTS.items()
    }


def _recorded_facts(path: Path) -> dict:
    """保存済みの[文書情報]の確定した 4 項目。保存が無い・壊れている（置き換えで直る）ときは、無いことを表す値。"""
    try:
        existing = _with_facts(_without_legacy_times(_read_json(path)))
        validate_document_info(existing)
    except StateStoreError as exc:
        if exc.kind in (KIND_MISSING, KIND_CORRUPT):
            return _unconfirmed_facts()
        raise
    return {name: existing[name] for name in _FACT_FIELDS}


def save_document_info(project_root: Path, skill: str, info: dict) -> bool:
    """[文書情報]を文書 ID ごとのファイルへ保存する。書き換えたとき `True`。

    確定した 4 項目を 1 つも持たない `info`（要約の 8 項目だけ）は、保存済みの 4 項目を保って保存する。
    """
    if isinstance(info, dict) and not set(info) & set(_FACT_FIELDS):
        doc_link_id = info.get("doc_link_id")
        if isinstance(doc_link_id, str) and doc_link_id != "":
            info = {
                **info,
                **_recorded_facts(document_info_path(project_root, doc_link_id)),
            }
        else:
            info = {**info, **_unconfirmed_facts()}
    try:
        validate_document_info(info)
    except StateStoreError as exc:
        raise StateStoreError(KIND_INVALID, str(exc)) from exc
    path = document_info_path(project_root, info["doc_link_id"])
    _check_existing_identity(path, "doc_link_id", info["doc_link_id"])
    return write_if_changed(project_root, skill, path, serialize(_normalize_info(info)))


def load_document_info(project_root: Path, doc_link_id: str) -> dict:
    """[文書情報]を読む。無い・読めない・壊れているは `StateStoreError` で区別して失敗する。"""
    path = document_info_path(project_root, doc_link_id)
    value = _load_validated(
        path,
        lambda raw: validate_document_info(_with_facts(raw)),
        "doc_link_id",
        doc_link_id,
    )
    return _normalize_info(_with_facts(value))


def _member_ids(toc: dict) -> list[str]:
    """[確定 ToC]の所属文書の文書 ID。文書ごとの値が所属文書のものでなければ `invalid` で失敗する。"""
    members = [entry["doc_link_id"] for entry in toc["documents"]]
    if len(set(members)) != len(members):
        raise StateStoreError(
            KIND_INVALID, "確定 ToC の documents の文書 ID が重複している"
        )
    known = set(members)
    for name, id_field in (
        ("sections", "doc_link_id"),
        ("references", "source_doc_id"),
        ("last_checks", "doc_link_id"),
    ):
        for entry in toc[name]:
            if entry[id_field] not in known:
                raise StateStoreError(
                    KIND_INVALID,
                    f"確定 ToC の {name} の文書が documents に無い: {entry[id_field]}",
                )
    checked = [entry["doc_link_id"] for entry in toc["last_checks"]]
    if len(set(checked)) != len(checked):
        raise StateStoreError(
            KIND_INVALID, "確定 ToC の last_checks の文書 ID が重複している"
        )
    return members


def save_confirmed_toc(project_root: Path, skill: str, toc: dict) -> bool:
    """[確定 ToC]を保存する。[文書情報]か[確定 ToC]のファイルを 1 つでも書き換えたとき `True`。

    文書ごとの値を、所属する文書の[文書情報]へ書いてから、[確定 ToC]のファイルを置き換える。所属する文書の
    [文書情報]が無いときは、何も書かずに `invalid` で失敗する。
    """
    try:
        validate_confirmed_toc(toc)
    except StateStoreError as exc:
        raise StateStoreError(KIND_INVALID, str(exc)) from exc
    members = _member_ids(toc)
    path = confirmed_toc_path(project_root, toc["toc_key"])
    _check_existing_identity(path, "toc_key", toc["toc_key"])
    applied = {
        entry["doc_link_id"]: entry["applied_hash"] for entry in toc["documents"]
    }
    infos: list[dict] = []
    for doc_link_id in members:
        try:
            info = load_document_info(project_root, doc_link_id)
        except StateStoreError as exc:
            kind = KIND_INVALID if exc.kind == KIND_MISSING else exc.kind
            raise StateStoreError(
                kind,
                f"確定 ToC に入れる文書の文書情報を読めない（{doc_link_id}）: {exc}",
                exc.path,
            ) from exc
        infos.append(
            _normalize_info(
                {**info, **_facts_from_toc(toc, doc_link_id, applied[doc_link_id])}
            )
        )
    toc_file = {
        "toc_key": toc["toc_key"],
        "version": toc["version"],
        "target_spec": toc["target_spec"],
        "documents": sorted(members),
        "reverse_references": _sorted_set_list(toc["reverse_references"]),
    }
    written = False
    for info in infos:
        written |= write_if_changed(
            project_root,
            skill,
            document_info_path(project_root, info["doc_link_id"]),
            serialize(info),
        )
    written |= write_if_changed(project_root, skill, path, serialize(toc_file))
    return written


def _assemble_toc(project_root: Path, toc_file: dict) -> dict:
    """[確定 ToC]のファイルと、所属する文書の[文書情報]から、[確定 ToC]を組み立てる。"""
    toc = {
        "toc_key": toc_file["toc_key"],
        "version": toc_file["version"],
        "target_spec": toc_file["target_spec"],
        "documents": [],
        "sections": [],
        "references": [],
        "reverse_references": toc_file["reverse_references"],
        "last_checks": [],
    }
    for doc_link_id in toc_file["documents"]:
        try:
            info = load_document_info(project_root, doc_link_id)
        except StateStoreError as exc:
            # 所属する文書の[文書情報]が無いことは、[確定 ToC]が無い（未構築）こととは違う。
            kind = KIND_CORRUPT if exc.kind == KIND_MISSING else exc.kind
            raise StateStoreError(
                kind,
                f"確定 ToC の文書の文書情報を読めない（{doc_link_id}）: {exc}",
                exc.path,
            ) from exc
        if info["applied_hash"] is None:
            raise StateStoreError(
                KIND_CORRUPT,
                f"確定 ToC の文書の文書情報に、確定した値が無い（{doc_link_id}）",
                document_info_path(project_root, doc_link_id),
            )
        toc["documents"].append(
            {"doc_link_id": doc_link_id, "applied_hash": info["applied_hash"]}
        )
        toc["sections"] += [
            {"doc_link_id": doc_link_id, **entry} for entry in info["sections"]
        ]
        toc["references"] += [
            {"source_doc_id": doc_link_id, **entry} for entry in info["references"]
        ]
        if info["last_check"] is not None:
            toc["last_checks"].append(
                {"doc_link_id": doc_link_id, **info["last_check"]}
            )
    return _normalize_toc(toc)


def load_confirmed_toc(project_root: Path, toc_key: str) -> dict:
    """[確定 ToC]を読む。初回構築前は `missing` で失敗する（空の ToC は返さない）。

    返すのは `CONFIRMED_TOC_FIELDS` の形で、文書ごとの値は所属する文書の[文書情報]から組み立てる。
    """
    path = confirmed_toc_path(project_root, toc_key)
    value = _read_json(path)
    if isinstance(value, dict) and set(value) == set(CONFIRMED_TOC_FIELDS):
        # ひとつ前の保存形式。文書ごとの値をこのファイルが持つ。
        return _load_validated(path, validate_confirmed_toc, "toc_key", toc_key)
    toc_file = _load_validated(path, _validate_toc_file, "toc_key", toc_key)
    return _assemble_toc(project_root, toc_file)


def load_all_document_infos(project_root: Path) -> list[dict]:
    """保存済みの[文書情報]をすべて、文書 ID の昇順で返す。1 つでも読めなければ失敗する。"""
    return [
        load_document_info(project_root, doc_link_id)
        for doc_link_id in list_document_ids(project_root)
    ]


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
