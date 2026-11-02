# /// script
# requires-python = ">=3.15"
# dependencies = []
# ///
"""doc-link の管理状態（`.doc-link/` 配下の JSON）を読み書きするプラグイン共通の部品。

後続の script が import して使う。CLI は持たない。

## ファイルの配置（DES-002 §4）

管理状態はプロジェクトルート直下の `.doc-link/` に置き、次の 3 種類のファイルに分ける。

| パス                                     | 内容                                       |
| ---------------------------------------- | ------------------------------------------ |
| `.doc-link/documents/<文書ID>.json`      | 文書情報。文書 ID（DLID）ごとに 1 ファイル |
| `.doc-link/keys/<slug>-<キーのハッシュ>.json` | 確定 ToC。ToC 識別キーごとに 1 ファイル    |
| `.doc-link/baselines.json`               | 通知済みハッシュ。全体で 1 ファイル        |

### ToC 識別キーからファイル名への対応

ToC 識別キーは opaque な文字列で、ファイル名に使えない文字を含みうる。DocAdvisor が
キーから ToC の保存先ディレクトリ名を作る規則（`toc_store.py` の `_slugify`・`_key_hash`・
`resolve_store_dir`）と同じ規則で `<slug>-<ハッシュ>` を作り、`.json` を付けてファイル名とする。

- slug: キーを NFC に正規化して小文字にし、`a-z`・`0-9`・`-` 以外の文字（`_` を含む）を
  `_` に置き換え、連続する `_` を 1 つに縮める。先頭・末尾の `_` を除き、40 文字で切り詰め、
  もう一度先頭・末尾の `_` を除く。空になれば `k` とする
- ハッシュ: NFC に正規化したキー全体を UTF-8 にした sha256 の 16 進表記の先頭 12 文字
- slug は情報を落とすので、別のキーの区別はハッシュが担う。同じキーは常に同じファイル名に
  なり、NFC で同じになるキーどうしは同じファイル名になる。出力は小文字だけから成るので、
  大文字小文字を区別しないファイルシステムでも、大文字小文字だけが違うキーはハッシュで分かれる
- ファイル名からキーへは逆変換しない。キーそのものはファイルの中身（`key`）に書き、
  ファイルの中身からキーを復元する
- キーの検証（空キー・任意指定の予約キー `all` の拒否）と NFC 化は、DocAdvisor と同じく
  引数を受け取る側（`target_spec`。NFC 化したキーを返す）が行う。ここでは検証も NFC 化も
  せず、渡されたキーをそのまま変換・保存・照合する（`resolve_store_dir` と同じく、変換の
  中の NFC 化だけは行う）

文書情報のファイル名は文書 ID そのものとする。DLID は `DLID-` と小文字の Crockford
Base32 だけから成るので、ファイル名にそのまま使える。DLID と認識できない値
（`dlid.recognize_dlid`）は受け付けない。

## 論理情報とスキーマの対応（DES-003 §2）

| 論理情報         | 収まる場所                                                                                      |
| ---------------- | ----------------------------------------------------------------------------------------------- |
| 文書同一性       | 文書情報の `doc_link_id`（ファイル名と一致）。ToCの `documents[].doc_link_id`       |
| Index 対象指定     | ToCの `key` と `target_spec`（正規化した指定。再展開できる形のまま保存する。D-020） |
| Index 対象の観測   | 永続化しない（候補作成に使う一時的な観測結果。DES-003 §2）                                      |
| 文書情報         | `.doc-link/documents/<文書ID>.json` の全体（キー別に複写しない。D-024）                          |
| 参照記述         | ToCの `references[]`（`check` を除く部分）                                         |
| 参照検査結果     | ToCの `references[].check`（検査した参照記述と 1 対 1 に対応する）                  |
| 確定 ToC     | `.doc-link/keys/<slug>-<キーのハッシュ>.json` の全体。版の識別は `version`、検査状態は `check_state`     |
| 通知済みハッシュ | `.doc-link/baselines.json` の `entries[]`                                                       |
| 構築実行         | 永続化しない（下記）                                                                            |

逆参照は参照記述から得る派生情報（DES-003 §3）なので、保存せず `references[]` から引く。

構築実行（構築 ID、操作、キー、開始時刻）は、カスタム Agent との依頼と結果を 1 回の構築の
間だけ識別するための情報である（DES-010 §4）。受け渡しの置き場は `.temp/doc-link/<skill>/`
にあり、構築が終われば削除する。git で追跡する `.doc-link/` に置くと、構築のたびに
意味の無い差分と並行ブランチでの衝突を生むので、永続化しない。

## 各ファイルのフィールド

文書情報（`DocumentInfo`）:

| フィールド         | 型              | 意味                                       |
| ------------------ | --------------- | ------------------------------------------ |
| `doc_link_id`      | 文字列（DLID）  | 文書 ID                                    |
| `path`             | 文字列          | 現在パス（プロジェクトルート相対、`/` 区切り） |
| `title`            | 文字列          | タイトル                                   |
| `purpose`          | 文字列          | 目的                                       |
| `content_details`  | 文字列の配列    | 内容概要（DocAdvisor の ToC と同じ名前）   |
| `applicable_tasks` | 文字列の配列    | 適用される作業                             |
| `keywords`         | 文字列の配列    | 検索用キーワード                           |
| `content_hash`     | 文字列          | この文書情報を生成した内容ハッシュ         |

ToC（`KeyIndex`）:

| フィールド    | 型                     | 意味                                                         |
| ------------- | ---------------------- | ------------------------------------------------------------ |
| `key`         | 文字列                 | ToC 識別キー                                                     |
| `version`     | 文字列                 | 版の識別。値は確定する呼び出し元が決める                     |
| `target_spec` | JSON オブジェクト      | 正規化した Index 対象指定。対象指定の展開 script の形のまま保存する |
| `check_state` | オブジェクト           | 検査状態（`status`: 文字列、`checked_at`: 文字列）           |
| `documents`   | 配列                   | 所属する文書（`doc_link_id`、反映済みハッシュ `reflected_hash`） |
| `sections`    | 配列                   | セクションエントリ（下記）                                   |
| `references`  | 配列                   | 参照記述と参照検査結果（下記）                               |

セクションエントリ（REQ-003 §7.2、DES-006 §3）: `section_id`（セクション ID）、
`doc_link_id`（所属する文書 ID）、`heading`（見出し）、`line`（見出しの行番号。1 始まり）、
`section_hash`（セクションのハッシュ）。

参照記述（DES-003 §2、DES-007 §1）: `source_doc_id`（参照元文書 ID）、
`source_section_id`（参照元セクション ID。無ければ null）、`line`（記載位置の行番号。
1 始まり）、`target_id`（参照先の文書またはセクション ID）、`written_path`（記載パス）、
`fragment`（記載されたフラグメント。無ければ null）、`check`（参照検査結果）。
同じ参照先への複数箇所の参照は、別の要素として並べる。

参照検査結果: `directory`（検査範囲のディレクトリ）、`checked_at`（検査時点）、
`result`（結果区分）、`found_paths`（発見したパスの配列）。

通知済みハッシュ（`Baseline`、DES-003 §2、DES-007 §3）: `target_id`（対象の文書または
セクション ID）、`source_id`（参照元文書 ID。「参照元なし」は null）、
`content_hash`（報告済みの内容ハッシュ）。(`target_id`, `source_id`) の組は一意である。

## 書き込みと読み取り（DES-002 §4、DES-005 §5）

- JSON は UTF-8、オブジェクトのキーを並べ替え、インデント 2、末尾に改行 1 つで書く。
  配列の要素も一定の順に並べ替えて書くので、同じ内容から常に同じバイト列になる
  （内容概要などの文字列の配列は、内容の一部なので並べ替えない）
- 書く内容が既存のファイルとバイト列で同じなら書き換えない（更新時刻も変えない）
- 書き込みは `.temp/doc-link/<skill>/` に一時ファイルを作り、`os.replace` で置き換える。
  プロジェクトの外には作らない。ロックは設けない
- ファイルが無いときは「記録が無い」として扱う（`None` または空）。ファイルを読めない、
  JSON として壊れている、上の形に合わないときは `StateError` を送出する。既定値に落とさない
"""

import hashlib
import json
import os
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from dlid import recognize_dlid

STATE_DIR_NAME = ".doc-link"
"""管理状態を置く、プロジェクトルート直下のディレクトリ名。"""

DOCUMENTS_DIR_NAME = "documents"
KEYS_DIR_NAME = "keys"
BASELINES_FILE_NAME = "baselines.json"

TEMP_DIR_PARTS = (".temp", "doc-link")
"""一時ファイルの置き場（プロジェクトルート相対）。この下に `<skill>/` を作る。"""

SLUG_MAX_LEN = 40
"""ファイル名の slug 部分の最大文字数（DocAdvisor の `SLUG_MAX_LEN` と同じ）。"""

KEY_HASH_LEN = 12
"""ファイル名のハッシュ部分の 16 進桁数（DocAdvisor の `HASH_SUFFIX_LEN` と同じ）。"""


class StateError(Exception):
    """管理状態のファイルを読めない、または JSON として壊れている・形が合わない。"""


# ---------------------------------------------------------------------------
# データの型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentInfo:
    """文書情報。文書 ID ごとに 1 つで、キーに依存しない。"""

    doc_link_id: str
    path: str
    title: str
    purpose: str
    content_details: list[str]
    applicable_tasks: list[str]
    keywords: list[str]
    content_hash: str


@dataclass(frozen=True)
class DocumentEntry:
    """キーに所属する文書と、そのキーの ToC に反映済みの内容ハッシュ。"""

    doc_link_id: str
    reflected_hash: str


@dataclass(frozen=True)
class SectionEntry:
    """セクションエントリ。"""

    section_id: str
    doc_link_id: str
    heading: str
    line: int
    section_hash: str


@dataclass(frozen=True)
class ReferenceCheck:
    """参照検査結果。"""

    directory: str
    checked_at: str
    result: str
    found_paths: list[str]


@dataclass(frozen=True)
class ReferenceEntry:
    """参照記述と、その参照検査結果。"""

    source_doc_id: str
    source_section_id: str | None
    line: int
    target_id: str
    written_path: str
    fragment: str | None
    check: ReferenceCheck


@dataclass(frozen=True)
class CheckState:
    """ToCの検査状態。"""

    status: str
    checked_at: str


@dataclass(frozen=True)
class KeyIndex:
    """確定 ToC。文書情報を含まない。"""

    key: str
    version: str
    target_spec: dict
    check_state: CheckState
    documents: list[DocumentEntry] = field(default_factory=list)
    sections: list[SectionEntry] = field(default_factory=list)
    references: list[ReferenceEntry] = field(default_factory=list)


@dataclass(frozen=True)
class Baseline:
    """通知済みハッシュの 1 組。`source_id` が None のときは「参照元なし」。"""

    target_id: str
    source_id: str | None
    content_hash: str


# ---------------------------------------------------------------------------
# パス
# ---------------------------------------------------------------------------


def state_dir(project_root: Path) -> Path:
    """管理状態のディレクトリ `<project_root>/.doc-link` を返す。"""
    return Path(project_root) / STATE_DIR_NAME


def _key_slug(key: str) -> str:
    out = []
    prev_underscore = False
    for ch in unicodedata.normalize("NFC", key).lower():
        if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch == "-":
            out.append(ch)
            prev_underscore = False
        elif not prev_underscore:
            # `_` を含むそれ以外の文字はすべて `_` にし、連続は 1 つに縮める
            out.append("_")
            prev_underscore = True
    slug = "".join(out).strip("_")[:SLUG_MAX_LEN].strip("_")
    return slug or "k"


def key_to_filename(key: str) -> str:
    """ToC 識別キーをファイル名（`.json` 付き）へ対応させる。規則は module docstring を参照。"""
    normalized = unicodedata.normalize("NFC", key)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:KEY_HASH_LEN]
    return f"{_key_slug(key)}-{digest}.json"


def document_info_path(project_root: Path, doc_link_id: str) -> Path:
    """文書情報のファイルのパスを返す。"""
    return (
        state_dir(project_root)
        / DOCUMENTS_DIR_NAME
        / (_require_dlid(doc_link_id) + ".json")
    )


def key_index_path(project_root: Path, key: str) -> Path:
    """ToCのファイルのパスを返す。"""
    return state_dir(project_root) / KEYS_DIR_NAME / key_to_filename(key)


def baselines_path(project_root: Path) -> Path:
    """通知済みハッシュのファイルのパスを返す。"""
    return state_dir(project_root) / BASELINES_FILE_NAME


def temp_dir(project_root: Path, skill: str) -> Path:
    """書き込み用の一時ファイルの置き場 `<project_root>/.temp/doc-link/<skill>` を返す。"""
    if (
        not isinstance(skill, str)
        or skill in ("", ".", "..")
        or "/" in skill
        or "\\" in skill
        or "\0" in skill
    ):
        raise ValueError(f"SKILL 名として受け付けられない: {skill!r}")
    return Path(project_root).joinpath(*TEMP_DIR_PARTS, skill)


def _require_dlid(value: str) -> str:
    if recognize_dlid(value) is None:
        raise ValueError(f"DLID と認識できない: {value!r}")
    return value


# ---------------------------------------------------------------------------
# 決定的な書き込み
# ---------------------------------------------------------------------------


def serialize(data: object) -> bytes:
    """JSON の値を、同じ内容から常に同じになるバイト列にする。"""
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)
    return (text + "\n").encode("utf-8")


def write_json_if_changed(
    project_root: Path, skill: str, path: Path, data: object
) -> bool:
    """JSON を書く。既存のファイルと同じバイト列なら書き換えない。

    一時ファイルは `.temp/doc-link/<skill>/` に作り、`os.replace` で置き換える。

    Returns:
        書き換えたときは True、内容が同じで書き換えなかったときは False。
    """
    payload = serialize(data)
    path = Path(path)
    try:
        current = path.read_bytes()
    except FileNotFoundError:
        current = None
    if current == payload:
        return False

    work_dir = temp_dir(project_root, skill)
    work_dir.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=work_dir, prefix=path.stem + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return True


# ---------------------------------------------------------------------------
# 辞書との変換（書き込み側）
# ---------------------------------------------------------------------------


def _document_info_to_dict(info: DocumentInfo) -> dict:
    return {
        "doc_link_id": info.doc_link_id,
        "path": info.path,
        "title": info.title,
        "purpose": info.purpose,
        "content_details": list(info.content_details),
        "applicable_tasks": list(info.applicable_tasks),
        "keywords": list(info.keywords),
        "content_hash": info.content_hash,
    }


def _reference_sort_key(ref: ReferenceEntry) -> tuple:
    return (
        ref.source_doc_id,
        ref.line,
        ref.source_section_id or "",
        ref.target_id,
        ref.written_path,
        ref.fragment or "",
        serialize(_reference_check_to_dict(ref.check)),
    )


def _reference_check_to_dict(check: ReferenceCheck) -> dict:
    return {
        "directory": check.directory,
        "checked_at": check.checked_at,
        "result": check.result,
        "found_paths": sorted(check.found_paths),
    }


def _key_index_to_dict(index: KeyIndex) -> dict:
    documents = sorted(index.documents, key=lambda d: (d.doc_link_id, d.reflected_hash))
    sections = sorted(
        index.sections,
        key=lambda s: (s.doc_link_id, s.line, s.section_id, s.heading, s.section_hash),
    )
    references = sorted(index.references, key=_reference_sort_key)
    return {
        "key": index.key,
        "version": index.version,
        "target_spec": index.target_spec,
        "check_state": {
            "status": index.check_state.status,
            "checked_at": index.check_state.checked_at,
        },
        "documents": [
            {"doc_link_id": d.doc_link_id, "reflected_hash": d.reflected_hash}
            for d in documents
        ],
        "sections": [
            {
                "section_id": s.section_id,
                "doc_link_id": s.doc_link_id,
                "heading": s.heading,
                "line": s.line,
                "section_hash": s.section_hash,
            }
            for s in sections
        ],
        "references": [
            {
                "source_doc_id": r.source_doc_id,
                "source_section_id": r.source_section_id,
                "line": r.line,
                "target_id": r.target_id,
                "written_path": r.written_path,
                "fragment": r.fragment,
                "check": _reference_check_to_dict(r.check),
            }
            for r in references
        ],
    }


def _baselines_to_dict(entries: list[Baseline]) -> dict:
    pairs = set()
    for entry in entries:
        pair = (entry.target_id, entry.source_id)
        if pair in pairs:
            raise ValueError(f"通知済みハッシュの組が重複している: {pair!r}")
        pairs.add(pair)
    ordered = sorted(entries, key=lambda b: (b.target_id, b.source_id or ""))
    # 「参照元なし」（None）は同じ target_id の中で先頭に来る（"" が最小のため）
    return {
        "entries": [
            {
                "target_id": b.target_id,
                "source_id": b.source_id,
                "content_hash": b.content_hash,
            }
            for b in ordered
        ]
    }


# ---------------------------------------------------------------------------
# 辞書との変換（読み取り側）。形が合わなければ StateError
# ---------------------------------------------------------------------------


def _get(obj: object, name: str, expected: type | tuple, where: Path) -> object:
    if not isinstance(obj, dict):
        raise StateError(f"{where}: オブジェクトでない値がある")
    if name not in obj:
        raise StateError(f"{where}: フィールド {name!r} が無い")
    value = obj[name]
    # bool は int の派生型なので、int を期待するときは bool を除く
    if expected is int and isinstance(value, bool):
        raise StateError(f"{where}: フィールド {name!r} の型が合わない")
    if not isinstance(value, expected):
        raise StateError(f"{where}: フィールド {name!r} の型が合わない")
    return value


def _get_str_list(obj: object, name: str, where: Path) -> list[str]:
    value = _get(obj, name, list, where)
    if not all(isinstance(item, str) for item in value):
        raise StateError(f"{where}: フィールド {name!r} に文字列でない要素がある")
    return list(value)


def _get_optional_str(obj: object, name: str, where: Path) -> str | None:
    return _get(obj, name, (str, type(None)), where)


def _get_list_of_objects(obj: object, name: str, where: Path) -> list[dict]:
    value = _get(obj, name, list, where)
    if not all(isinstance(item, dict) for item in value):
        raise StateError(f"{where}: フィールド {name!r} にオブジェクトでない要素がある")
    return value


def _document_info_from_dict(data: object, where: Path) -> DocumentInfo:
    return DocumentInfo(
        doc_link_id=_get(data, "doc_link_id", str, where),
        path=_get(data, "path", str, where),
        title=_get(data, "title", str, where),
        purpose=_get(data, "purpose", str, where),
        content_details=_get_str_list(data, "content_details", where),
        applicable_tasks=_get_str_list(data, "applicable_tasks", where),
        keywords=_get_str_list(data, "keywords", where),
        content_hash=_get(data, "content_hash", str, where),
    )


def _key_index_from_dict(data: object, where: Path) -> KeyIndex:
    check_state = _get(data, "check_state", dict, where)
    documents = [
        DocumentEntry(
            doc_link_id=_get(d, "doc_link_id", str, where),
            reflected_hash=_get(d, "reflected_hash", str, where),
        )
        for d in _get_list_of_objects(data, "documents", where)
    ]
    sections = [
        SectionEntry(
            section_id=_get(s, "section_id", str, where),
            doc_link_id=_get(s, "doc_link_id", str, where),
            heading=_get(s, "heading", str, where),
            line=_get(s, "line", int, where),
            section_hash=_get(s, "section_hash", str, where),
        )
        for s in _get_list_of_objects(data, "sections", where)
    ]
    references = []
    for r in _get_list_of_objects(data, "references", where):
        check = _get(r, "check", dict, where)
        references.append(
            ReferenceEntry(
                source_doc_id=_get(r, "source_doc_id", str, where),
                source_section_id=_get_optional_str(r, "source_section_id", where),
                line=_get(r, "line", int, where),
                target_id=_get(r, "target_id", str, where),
                written_path=_get(r, "written_path", str, where),
                fragment=_get_optional_str(r, "fragment", where),
                check=ReferenceCheck(
                    directory=_get(check, "directory", str, where),
                    checked_at=_get(check, "checked_at", str, where),
                    result=_get(check, "result", str, where),
                    found_paths=_get_str_list(check, "found_paths", where),
                ),
            )
        )
    return KeyIndex(
        key=_get(data, "key", str, where),
        version=_get(data, "version", str, where),
        target_spec=_get(data, "target_spec", dict, where),
        check_state=CheckState(
            status=_get(check_state, "status", str, where),
            checked_at=_get(check_state, "checked_at", str, where),
        ),
        documents=documents,
        sections=sections,
        references=references,
    )


def _baselines_from_dict(data: object, where: Path) -> list[Baseline]:
    return [
        Baseline(
            target_id=_get(b, "target_id", str, where),
            source_id=_get_optional_str(b, "source_id", where),
            content_hash=_get(b, "content_hash", str, where),
        )
        for b in _get_list_of_objects(data, "entries", where)
    ]


def _read_json(path: Path) -> object | None:
    """JSON を読む。ファイルが無ければ None。読めない・壊れていれば StateError。"""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StateError(f"{path}: 読み取れない: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateError(f"{path}: JSON として読めない: {exc}") from exc


# ---------------------------------------------------------------------------
# 公開する読み書き
# ---------------------------------------------------------------------------


def read_document_info(project_root: Path, doc_link_id: str) -> DocumentInfo | None:
    """文書情報を読む。記録が無ければ None。"""
    path = document_info_path(project_root, doc_link_id)
    data = _read_json(path)
    if data is None:
        return None
    info = _document_info_from_dict(data, path)
    if info.doc_link_id != doc_link_id:
        raise StateError(f"{path}: 中身の doc_link_id がファイル名と一致しない")
    return info


def write_document_info(project_root: Path, skill: str, info: DocumentInfo) -> bool:
    """文書情報を書く。内容が同じなら書き換えず False を返す。"""
    path = document_info_path(project_root, info.doc_link_id)
    return write_json_if_changed(
        project_root, skill, path, _document_info_to_dict(info)
    )


def read_key_index(project_root: Path, key: str) -> KeyIndex | None:
    """ToCを読む。確定 ToCが無ければ None。"""
    path = key_index_path(project_root, key)
    data = _read_json(path)
    if data is None:
        return None
    index = _key_index_from_dict(data, path)
    if index.key != key:
        raise StateError(f"{path}: 中身の key がファイル名と一致しない")
    return index


def write_key_index(project_root: Path, skill: str, index: KeyIndex) -> bool:
    """ToCを書く（一括公開）。内容が同じなら書き換えず False を返す。"""
    path = key_index_path(project_root, index.key)
    return write_json_if_changed(project_root, skill, path, _key_index_to_dict(index))


def list_key_indexes(project_root: Path) -> list[KeyIndex]:
    """記録されている全キーの ToCを、キーの順に返す。"""
    keys_dir = state_dir(project_root) / KEYS_DIR_NAME
    try:
        paths = sorted(p for p in keys_dir.iterdir() if p.suffix == ".json")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise StateError(f"{keys_dir}: 読み取れない: {exc}") from exc
    indexes = []
    for path in paths:
        data = _read_json(path)
        if data is None:
            continue
        index = _key_index_from_dict(data, path)
        if path.name != key_to_filename(index.key):
            raise StateError(f"{path}: 中身の key がファイル名と一致しない")
        indexes.append(index)
    return sorted(indexes, key=lambda i: i.key)


def read_baselines(project_root: Path) -> list[Baseline]:
    """通知済みハッシュを読む。記録が無ければ空の配列。"""
    path = baselines_path(project_root)
    data = _read_json(path)
    if data is None:
        return []
    return _baselines_from_dict(data, path)


def write_baselines(project_root: Path, skill: str, entries: list[Baseline]) -> bool:
    """通知済みハッシュの全体を 1 回で書く。内容が同じなら書き換えず False を返す。"""
    return write_json_if_changed(
        project_root, skill, baselines_path(project_root), _baselines_to_dict(entries)
    )


# ---------------------------------------------------------------------------
# 読み取りの照会
# ---------------------------------------------------------------------------


def list_recorded_dlids(project_root: Path) -> list[str]:
    """全キーの ToCに記録された DLID（文書 ID とセクション ID）を列挙する。

    ID 付与操作の重複照合（D-030）に使う。重複を除き、並べ替えて返す。
    """
    dlids = set()
    for index in list_key_indexes(project_root):
        dlids.update(d.doc_link_id for d in index.documents)
        dlids.update(s.section_id for s in index.sections)
    return sorted(dlids)


def lookup_document_path(project_root: Path, doc_link_id: str) -> str | None:
    """文書 ID から、文書情報に記録された現在パスを引く。記録が無ければ None。"""
    info = read_document_info(project_root, doc_link_id)
    if info is None:
        return None
    return info.path


def lookup_section_documents(project_root: Path, section_id: str) -> list[str]:
    """セクション ID から、全キーの版に記録された所属する文書 ID をすべて引く。

    セクションを別の文書へ移した後に一部のキーだけを再構築すると、所属する文書の記録が
    キーごとに異なる（DES-006 §3）。そのため、重複を除いたすべてを並べ替えて返す。
    記録が無ければ空の配列。
    """
    documents = set()
    for index in list_key_indexes(project_root):
        documents.update(
            s.doc_link_id for s in index.sections if s.section_id == section_id
        )
    return sorted(documents)
