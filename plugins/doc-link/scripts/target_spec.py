# /// script
# requires-python = ">=3.15"
# dependencies = []
# ///
"""Index 対象指定の引数を検証し、Markdown の一覧（Index 対象リスト）へ展開する共通の部品。

`embed-dlid`（ID 付与操作）と `index-docs`（ToC の構築）は、対象指定の検証と展開に
どちらもこの script を使う（DES-005 §2.1、要件 D-041）。同じ役割の実装を別に作らない。
後続の script は関数を import して使い、SKILL は CLI を呼ぶ。

展開・除外・パスの扱いは、DocAdvisor の `index-docs`（`expand_dirs.py`・`prepare_toc.py`・
`toc_utils.py`）を参考にし、要件・設計が決めていない点はそれと同じにする（DES-005 §2 の 2）。
異なる点は、下の各項に「DocAdvisor と異なる」として理由とともに書く。

## 引数の組み合わせ（DES-005 §2 の 1、REQ-002 FR-017・AC-022、REQ-001 §17.1）

次に反する指定は拒否し、拒否した指定と理由を返す。

- `--paths` と `--paths-json`、`--dirs` と `--dirs-json`、`--exclude` と `--exclude-json` は
  それぞれ併用でき、連結する
- 対象指定（`--paths` 系、`--paths-file`、`--dirs` 系、`--exclude` 系）には `--key` が要る。
  `--key` を省くと単体モードで、対象指定を併せて渡せない
- `--key` は NFC に揃える。前後の空白を除くと空になるキーは拒否する。NFC に揃えた結果が
  予約語 `all` のキーは指定できない
- `--key` を指定したのに対象指定が無い指定は拒否する（DocAdvisor と異なる。DES-005 §2 の 1）
- `--all` は対象指定と併用できない。`--all` と `--key` も併用できない。引数が無いときは
  `--all` として扱う
- `--paths-file` はほかの対象指定と併用できない
- `--exclude` 系は `--all`・`--paths-file` と併用できない

フラグが渡されていれば、JSON 配列が空でも対象指定があるものとして扱う。JSON 形を解析
できない、配列でない、要素が空でない文字列でない、`--paths-file` を読めない指定は拒否する。

## 展開と除外（DES-005 §2 の 2）

- `--dirs` 系の要素に `*`・`?`・`[` があればパターンとして展開する。一致したディレクトリは
  配下の Markdown（名前が `*.md` に一致するファイル）を再帰的に集め、一致したファイルは
  拡張子が大文字小文字を区別せず `.md` のものだけを加える。無ければ、そのディレクトリ配下の
  Markdown を再帰的に集める
- `--all` の走査と `--dirs` 系の展開では、`FIXED_EXCLUDED_DIR_NAMES` の名前のディレクトリの
  配下（プロジェクトルートからのパスのどの階層でも）を対象にしない。`--paths` 系・
  `--paths-file` で指定したファイルには適用しない。名前のうち `.temp` は DocAdvisor と異なり、
  doc-link が加える（一時ファイルの置き場を索引しない。DES-005 §2 の 2）
- `--exclude` 系の要素は、`/` を含まなければ、どの階層の同じ名前のディレクトリとも完全一致で
  照合し、ファイル名とは照合しない。`/` を含めば、パスとの完全一致、またはその配下で照合する。
  `*`・`?`・`[` を含む要素はパターンとし、`--dirs` 系のパターンと同じ規則（pathlib の glob）で
  照合する。`/` を含まなければどの階層の名前（ディレクトリ名・ファイル名）と、含めばパスまたは
  その祖先のパスと照合し、一致したものとその配下を除く（DocAdvisor と異なる。要件 REQ-002 §6.1）
  除外は確定した対象（`--dirs` 系の展開結果と個別に指定したファイル）に、存在と Markdown の
  検証より先に適用する。除いたパスは `excluded` に入れ、件数を `warnings` で報告する
- 対象（`--dirs` 系の展開結果と個別に指定したファイル）は、次の順で検証し、満たさないものは
  対象から除いて `rejected_paths` に理由とともに入れ、残りで続行する（理由は DocAdvisor と
  異なり自然文とする。script_error_output_rules.md）
  1. 絶対パスでない
  2. NFC に揃え、`./` とプロジェクトルートの中に収まる `..` を解決した結果がルートの外に出ない
  3. 実体が存在する（シンボリックリンクはたどる）
  4. 拡張子が大文字小文字を区別せず `.md`・`.markdown` である
  5. 実体がファイルである（ディレクトリでない）
- `--dirs` 系の要素は、絶対パス・ルートの外に出るもの・存在しないもの・ディレクトリでないもの・
  展開できないパターンを `rejected_dirs` に理由とともに入れ、残りで続行する。一致の無い
  パターンは `warnings` で報告する
- シンボリックリンクはたどる。1 回の走査の中では同じ実体（デバイス番号と inode 番号）を
  二度数えず、循環も止める。走査は名前の昇順に行い、同じ実体に複数のパスで届くときは先に
  届いたパスを採る（DocAdvisor と異なり順を定める。同じ入力から同じ一覧を得るため。NFR-002）
- シンボリックリンク経由の対象は、リンクの実体がどこにあっても、たどったプロジェクト内の
  パスで扱う。DocAdvisor と異なり、実体がプロジェクトの外にあることを理由に確認・警告・
  除外をしない。確認の結果で一覧が変わると、保存した指定から構築時と同じ一覧を得られない
  ためである（DES-005 §2 の 2、要件 D-020）
- 大文字小文字だけが異なるパスが対象にあるとき、`--all` で対象が `MAX_FILES_WARN_THRESHOLD`
  件を超えるときは `warnings` で報告する
- 存在しない以外の理由で読めないとき（走査中のディレクトリ、対象や `--dirs` 系の要素の親が
  読めない等）は、「存在しない」として除かず、一覧を黙って欠かさずに全体を失敗にする
  （DES-006 §1、要件 D-026。展開の失敗を対象離脱や「更新不要」と判定させない）。パターンの
  展開も同じで、読めないディレクトリを黙って飛ばさない（DocAdvisor と異なる）
- 結果はプロジェクトルート相対の `/` 区切りのパスで、重複を除き、昇順に並べる（NFR-002）

## パスの正規化

- `--paths` 系: NFC に揃え、`os.path.normpath` で `./` と `..` を解決する
- `--dirs` 系（パターンでない）: NFC に揃え、末尾の `/` を除き、`os.path.normpath` で解決する。
  絶対パスの判定は末尾の `/` を除いた後に行うので、`/` はプロジェクトルート（`.`）になる
- `--dirs` 系（パターン）: NFC に揃え、`\\` を `/` に置き換え、前後の空白と末尾の `/` を除く。
  空・絶対パス・`..` のセグメントを含むパターンは展開しない
- `--exclude` 系: NFC に揃え、前後の `/` を除く。何も残らない要素は使わない

## プロジェクトルート

`--project-root` が無ければ環境変数 `CLAUDE_PROJECT_DIR`（存在するディレクトリのとき）、
それも無ければカレントディレクトリとする。`--paths-file` の相対パスはカレントディレクトリを
基準にする。

## 正規化した指定（要件 D-020、REQ-003 §7）

正規化した指定（`target_spec`）は ToC に保存し、次回に外部から指定が渡されなくても
`expand_target_spec` で同じ一覧へ再展開できる形にする。

- 単体モード: `{"all": true}`
- 対象指定モード: `{"all": false, "paths": [...], "dirs": [...], "exclude": [...]}`。
  JSON 形と通常形を連結し、`--paths-file` の内容は読み込んで `paths` に入れる（ファイルが
  後で無くなっても再展開できる）。各要素は上の規則で正規化した文字列（正規化できない
  要素は NFC に揃えただけの文字列）で、重複を除いて昇順に並べる。正規化できない要素も
  保存し、再展開のたびに同じ理由で `rejected_paths`・`rejected_dirs` に入れる

ToC 識別キーは指定に含めず、結果の `key` に返す（単体モードは予約キー `all`）。

## 標準出力と終了コード（script_error_output_rules.md）

| code | 意味                                                         |
| ---- | ------------------------------------------------------------ |
| 0    | 検証と展開が完了した。結果の JSON を出す                     |
| 1    | 指定を拒否した、または展開できなかった。`errors` の JSON を出す |
| 2    | 引数を受理できない（`argparse`）                             |

対象から除いたパス・ディレクトリがあっても、検証と展開は完了しているので `0` を返す。

成功時の JSON: `key`（ToC 識別キー）、`target_spec`（正規化した指定）、`targets`
（Index 対象リスト）、`excluded`（`--exclude` 系で除いたパス）、`rejected_paths`
（対象から除いたパスと理由。`{"path", "reason"}`）、`rejected_dirs`（展開しなかった
`--dirs` 系の要素と理由。`{"dir", "reason"}`）、`warnings`（自然文の配列）。
"""

import argparse
import fnmatch
import json
import os
import stat
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

RESERVED_KEY = "all"
"""単体モードの予約 ToC 識別キー。"""

MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
"""個別に指定したファイルを Markdown とみなす拡張子（大文字小文字を区別しない）。"""

MARKDOWN_FILE_PATTERN = "*.md"
"""ディレクトリの走査で集めるファイル名のパターン。"""

GLOB_MATCH_SUFFIX = ".md"
"""パターンに直接一致したファイルを加える拡張子（大文字小文字を区別しない）。"""

GLOB_CHARS = ("*", "?", "[")
"""`--dirs` 系の要素をパターンとして扱う文字。"""

MAX_FILES_WARN_THRESHOLD = 100
"""`--all` で対象がこの件数を超えると警告する。"""

PROJECT_DIR_ENV = "CLAUDE_PROJECT_DIR"
"""`--project-root` が無いときにプロジェクトルートとする環境変数。"""

FIXED_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".claude",
        ".codex",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "__pycache__",
        ".venv",
        "target",
        "coverage",
        ".pytest_cache",
        ".mypy_cache",
        ".temp",
    }
)
"""`--all` の走査と `--dirs` 系の展開で配下を対象にしないディレクトリの名前（DES-005 §2 の 2）。"""


class TargetSpecError(Exception):
    """指定を拒否した、または展開できなかったことを表す。`errors` は自然文の配列。"""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


@dataclass(frozen=True)
class RawTargetArgs:
    """呼び出し元から受け取った対象指定の引数（解釈前）。

    `None` はそのフラグが渡されていないことを表す。JSON 形はフラグごとに複数回
    渡せるので、文字列の list で持つ。
    """

    key: str | None = None
    all: bool = False
    paths: list[str] | None = None
    paths_json: list[str] | None = None
    paths_file: str | None = None
    dirs: list[str] | None = None
    dirs_json: list[str] | None = None
    exclude: list[str] | None = None
    exclude_json: list[str] | None = None


@dataclass(frozen=True)
class Expansion:
    """正規化した指定を展開した結果。"""

    targets: list[str]
    excluded: list[str] = field(default_factory=list)
    rejected_paths: list[dict] = field(default_factory=list)
    rejected_dirs: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


# ---------------------------------------------------------------------------
# 組み合わせの検証
# ---------------------------------------------------------------------------


def _given_target_flags(raw: RawTargetArgs) -> list[str]:
    """渡された対象指定のフラグ名を、決まった順で返す。"""
    pairs = (
        ("--paths", raw.paths),
        ("--paths-json", raw.paths_json),
        ("--paths-file", raw.paths_file),
        ("--dirs", raw.dirs),
        ("--dirs-json", raw.dirs_json),
        ("--exclude", raw.exclude),
        ("--exclude-json", raw.exclude_json),
    )
    return [flag for flag, value in pairs if value is not None]


def validate_combination(raw: RawTargetArgs) -> list[str]:
    """引数の組み合わせを検証し、反する規則ごとの理由（自然文）を返す。空なら受理する。"""
    errors: list[str] = []
    targets = _given_target_flags(raw)
    exclude_flags = [f for f in targets if f in ("--exclude", "--exclude-json")]
    listed = " / ".join(targets)

    if raw.key is not None:
        key = _nfc(raw.key)
        if key.strip() == "":
            errors.append("--key が空である。ToC 識別キーを指定する")
        elif key == RESERVED_KEY:
            errors.append(
                "--key all は予約語なので指定できない。単体モードなら --all を使う"
            )

    if raw.all:
        if raw.key is not None:
            errors.append("--all と --key は併用できない")
        if targets:
            errors.append(f"--all は対象指定（{listed}）と併用できない")
        if exclude_flags:
            errors.append(f"{' / '.join(exclude_flags)} は --all と併用できない")
    elif raw.key is None:
        if targets:
            errors.append(
                f"--key を省いた単体モードでは対象指定（{listed}）を渡せない。"
                "対象を指定するなら --key <key> を渡す"
            )
    elif not targets:
        errors.append(
            "--key を指定したが対象指定が無い。--paths 系・--paths-file・"
            "--dirs 系・--exclude 系のいずれかを渡す"
        )

    if raw.paths_file is not None:
        others = [f for f in targets if f != "--paths-file"]
        if others:
            errors.append(
                f"--paths-file はほかの対象指定（{' / '.join(others)}）と併用できない"
            )
        if exclude_flags:
            errors.append(f"{' / '.join(exclude_flags)} は --paths-file と併用できない")
    return errors


# ---------------------------------------------------------------------------
# 正規化
# ---------------------------------------------------------------------------


def _escapes_root(rel: str) -> bool:
    """`./`・`..` を解決した相対パスが、プロジェクトルートの外に出るか。"""
    return rel == ".." or rel.startswith("../")


def _normalize_path_entry(value: str) -> tuple[str, str | None]:
    """`--paths` 系の要素を正規化する。

    Returns:
        (正規化した文字列, None) または (NFC に揃えただけの文字列, 対象から除く理由)。
    """
    text = _nfc(value)
    if os.path.isabs(text):
        return text, "絶対パスは指定できない"
    normalized = _nfc(os.path.normpath(text))
    if _escapes_root(normalized):
        return text, "プロジェクトルートの外を指す"
    return normalized, None


def _is_pattern(value: str) -> bool:
    return any(c in value for c in GLOB_CHARS)


def _normalize_dir_entry(value: str) -> tuple[str, str | None]:
    """`--dirs` 系の要素を正規化する。パターンはメタ文字を保ったまま整える。

    Returns:
        (正規化した文字列, None) または (NFC に揃えただけの文字列, 展開しない理由)。
    """
    text = _nfc(value)
    if _is_pattern(text):
        pattern = text.replace("\\", "/").strip().rstrip("/")
        if pattern == "":
            return text, "空のパターンは展開できない"
        if pattern.startswith("/"):
            return text, "絶対パスのパターンは展開できない"
        if ".." in pattern.split("/"):
            return text, "'..' を含むパターンは展開できない"
        return pattern, None
    # 末尾の `/` を除いてから絶対パスを判定する（DocAdvisor と同じ。`/` はルート全体になる）
    stripped = text.rstrip("/")
    if os.path.isabs(stripped):
        return text, "絶対パスは指定できない"
    normalized = _nfc(os.path.normpath(stripped))
    if _escapes_root(normalized):
        return text, "プロジェクトルートの外を指す"
    return normalized, None


def _normalize_exclude_entry(value: str) -> str:
    """`--exclude` 系の要素を正規化する。空文字列は使わない要素を表す。"""
    return _nfc(value).strip("/")


def _parse_json_array(text: str, label: str, errors: list[str]) -> list:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        errors.append(f"{label} を JSON として解析できない: {e}")
        return []
    if not isinstance(data, list):
        if isinstance(data, dict) and isinstance(data.get("paths"), list):
            errors.append(
                f"{label} は JSON 配列である必要がある。"
                '{"paths": [...]} ではなく配列そのものを渡す'
            )
        else:
            errors.append(f"{label} は JSON 配列である必要がある")
        return []
    return data


def _read_paths_file(path_text: str, cwd: Path, errors: list[str]) -> list:
    path = Path(path_text)
    if not path.is_absolute():
        path = cwd / path
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        errors.append(f"--paths-file を読めない: {path_text}: {e}")
        return []
    return _parse_json_array(text, f"--paths-file（{path_text}）", errors)


def _check_strings(values: list, label: str, errors: list[str]) -> list[str]:
    """要素が空でない文字列であることを検証し、満たすものだけを返す。"""
    result = []
    for value in values:
        if not isinstance(value, str) or value.strip() == "":
            errors.append(f"{label} の要素は空でない文字列である必要がある: {value!r}")
        else:
            result.append(value)
    return result


def build_target_spec(raw: RawTargetArgs, cwd: Path | None = None) -> tuple[str, dict]:
    """引数を検証し、ToC 識別キーと正規化した指定を返す。

    パスとして正規化できない要素（絶対パス・ルートの外を指すもの）は拒否せず、
    NFC に揃えたまま指定に残す。対象から除くのは展開（`expand_target_spec`）である。

    Args:
        raw: 呼び出し元から受け取った引数。
        cwd: `--paths-file` の相対パスの基準。省略時はカレントディレクトリ。

    Returns:
        (ToC 識別キー（NFC に揃えたもの）, 正規化した指定)。

    Raises:
        TargetSpecError: 組み合わせの規則に反する、JSON を解析できない、
            `--paths-file` を読めない、要素が空でない文字列でない。
    """
    errors = validate_combination(raw)
    if errors:
        raise TargetSpecError(errors)
    if raw.key is None:
        return RESERVED_KEY, {"all": True}

    base = Path.cwd() if cwd is None else Path(cwd)
    paths_raw: list = list(raw.paths or [])
    for text in raw.paths_json or []:
        paths_raw.extend(_parse_json_array(text, "--paths-json", errors))
    if raw.paths_file is not None:
        paths_raw.extend(_read_paths_file(raw.paths_file, base, errors))
    dirs_raw: list = list(raw.dirs or [])
    for text in raw.dirs_json or []:
        dirs_raw.extend(_parse_json_array(text, "--dirs-json", errors))
    exclude_raw: list = list(raw.exclude or [])
    for text in raw.exclude_json or []:
        exclude_raw.extend(_parse_json_array(text, "--exclude-json", errors))

    paths = [
        _normalize_path_entry(v)[0]
        for v in _check_strings(paths_raw, "--paths 系", errors)
    ]
    dirs = [
        _normalize_dir_entry(v)[0]
        for v in _check_strings(dirs_raw, "--dirs 系", errors)
    ]
    exclude = [
        _normalize_exclude_entry(v)
        for v in _check_strings(exclude_raw, "--exclude 系", errors)
    ]
    if errors:
        raise TargetSpecError(errors)
    return _nfc(raw.key), {
        "all": False,
        "paths": sorted(set(paths)),
        "dirs": sorted(set(dirs)),
        "exclude": sorted({e for e in exclude if e != ""}),
    }


# ---------------------------------------------------------------------------
# 走査
# ---------------------------------------------------------------------------


def _stat_or_missing(path: Path) -> os.stat_result | None:
    """シンボリックリンクをたどった実体の stat を返す。存在しなければ `None`。

    存在しない以外の読み取りの失敗（権限不足など）は「存在しない」と区別し、全体を
    失敗にする（DES-006 §1、要件 D-026。対象離脱と判定不能を取り違えない）。

    Raises:
        TargetSpecError: 存在しない以外の理由で読めない。
    """
    try:
        return path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as e:
        raise TargetSpecError([f"読めない: {path}: {e.strerror}"]) from e


def _has_fixed_excluded_dir(rel: str) -> bool:
    """プロジェクトルート相対のパスが、固定除外の名前のディレクトリの配下にあるか。"""
    return any(part in FIXED_EXCLUDED_DIR_NAMES for part in rel.split("/")[:-1])


def _walk_markdown(root: Path, start: Path) -> list[str]:
    """`start` 配下の Markdown を、シンボリックリンクをたどって再帰的に集める。

    同じ実体（ディレクトリ・ファイルのデバイス番号と inode 番号）は二度数えない。
    これで循環も止まる。名前の昇順にたどり、同じ実体に複数のパスで届くときは先に
    届いたパスを採る。固定除外の名前のディレクトリの配下は対象にしない。

    Returns:
        `root` 相対の `/` 区切りのパス（NFC）。リンク先ではなく、たどったパスで表す。

    Raises:
        TargetSpecError: 走査中のディレクトリを読めない（読めない部分を黙って
            一覧から落とさない）。
    """
    found: list[str] = []
    seen: set[tuple[int, int]] = set()
    walk_errors: list[str] = []

    def on_error(error: OSError) -> None:
        walk_errors.append(
            f"ディレクトリを読めない: {error.filename}: {error.strerror}"
        )

    for dirpath, dirnames, filenames in os.walk(
        start, onerror=on_error, followlinks=True
    ):
        current = Path(dirpath)
        st = _stat_or_missing(current)
        if st is None:
            dirnames.clear()
            continue
        if (st.st_dev, st.st_ino) in seen:
            dirnames.clear()
            continue
        seen.add((st.st_dev, st.st_ino))
        dirnames[:] = sorted(d for d in dirnames if d not in FIXED_EXCLUDED_DIR_NAMES)
        for name in sorted(filenames):
            if not fnmatch.fnmatch(name, MARKDOWN_FILE_PATTERN):
                continue
            full = current / name
            fst = _stat_or_missing(full)
            if fst is None:
                continue
            if (fst.st_dev, fst.st_ino) in seen:
                continue
            seen.add((fst.st_dev, fst.st_ino))
            rel = _nfc(full.relative_to(root).as_posix())
            if not _has_fixed_excluded_dir(rel):
                found.append(rel)
    if walk_errors:
        raise TargetSpecError(walk_errors)
    return found


def _case_collision_warnings(paths: list[str]) -> list[str]:
    warnings = []
    first: dict[str, str] = {}
    for path in paths:
        lower = path.lower()
        if lower in first and first[lower] != path:
            warnings.append(
                f"大文字小文字だけが異なるパスがある: {first[lower]} と {path}"
            )
        else:
            first.setdefault(lower, path)
    return warnings


# ---------------------------------------------------------------------------
# 展開
# ---------------------------------------------------------------------------


def _is_excluded(rel_path: str, exclude: list[str]) -> bool:
    parts = rel_path.split("/")
    dir_parts = parts[:-1]
    for item in exclude:
        if _is_pattern(item):
            if "/" in item:
                candidates = ["/".join(parts[: i + 1]) for i in range(len(parts))]
            else:
                candidates = parts
            if any(PurePosixPath(c).full_match(item) for c in candidates):
                return True
        elif "/" in item:
            if rel_path == item or rel_path.startswith(item + "/"):
                return True
        elif item in dir_parts:
            return True
    return False


def _glob(root: Path, pattern: str) -> list[Path]:
    """`pattern`（ルート相対、`**` 可）に一致するディレクトリとファイルを名前の昇順で返す。

    pathlib の glob は読めないディレクトリを黙って飛ばすため使わず、読めないときは
    全体を失敗にする（DES-006 §1、要件 D-026）。照合は `PurePosixPath.full_match` で、
    pathlib の glob と同じ規則である。シンボリックリンクはたどり、循環は止める。

    Raises:
        TargetSpecError: 走査中のディレクトリを読めない。
    """
    parts = pattern.split("/")
    fixed: list[str] = []
    for part in parts:
        if _is_pattern(part):
            break
        fixed.append(part)
    base = root.joinpath(*fixed)
    base_stat = _stat_or_missing(base)
    if base_stat is None or not stat.S_ISDIR(base_stat.st_mode):
        return []
    max_depth = None if "**" in parts else len(parts) - len(fixed)
    matches: list[Path] = []
    if "**" in parts and PurePosixPath(*fixed or ["."]).full_match(pattern):
        matches.append(base)
    seen: set[tuple[int, int]] = set()
    walk_errors: list[str] = []

    def on_error(error: OSError) -> None:
        walk_errors.append(
            f"ディレクトリを読めない: {error.filename}: {error.strerror}"
        )

    for dirpath, dirnames, filenames in os.walk(
        base, onerror=on_error, followlinks=True
    ):
        current = Path(dirpath)
        st = _stat_or_missing(current)
        if st is None or (st.st_dev, st.st_ino) in seen:
            dirnames.clear()
            continue
        seen.add((st.st_dev, st.st_ino))
        dirnames.sort()
        for name in [*dirnames, *sorted(filenames)]:
            full = current / name
            if PurePosixPath(_nfc(full.relative_to(root).as_posix())).full_match(
                pattern
            ):
                matches.append(full)
        depth = len(current.relative_to(base).parts) + 1
        dirnames[:] = [
            d
            for d in dirnames
            if d not in FIXED_EXCLUDED_DIR_NAMES
            and (max_depth is None or depth < max_depth)
        ]
    if walk_errors:
        raise TargetSpecError(walk_errors)
    return sorted(matches)


def _expand_dir_entry(
    root: Path,
    entry: str,
    collected: dict[str, None],
    rejected_dirs: list[dict],
    warnings: list[str],
) -> None:
    normalized, reason = _normalize_dir_entry(entry)
    if reason is not None:
        rejected_dirs.append({"dir": entry, "reason": reason})
        return
    if _is_pattern(normalized):
        matches = _glob(root, normalized)
        if not matches:
            warnings.append(f"パターンに一致するものが無い: {entry}")
            return
        matched_any = False
        for match in matches:
            match_stat = _stat_or_missing(match)
            if match_stat is None:
                continue
            if stat.S_ISDIR(match_stat.st_mode):
                collected.update(dict.fromkeys(_walk_markdown(root, match)))
                matched_any = True
            elif (
                stat.S_ISREG(match_stat.st_mode)
                and match.suffix.lower() == GLOB_MATCH_SUFFIX
            ):
                rel = _nfc(match.relative_to(root).as_posix())
                if not _has_fixed_excluded_dir(rel):
                    collected[rel] = None
                matched_any = True
        if not matched_any:
            warnings.append(f"パターンに一致するディレクトリ・Markdown が無い: {entry}")
        return
    target = root / normalized
    target_stat = _stat_or_missing(target)
    if target_stat is None:
        rejected_dirs.append({"dir": entry, "reason": "存在しない"})
        return
    if not stat.S_ISDIR(target_stat.st_mode):
        rejected_dirs.append({"dir": entry, "reason": "ディレクトリではない"})
        return
    collected.update(dict.fromkeys(_walk_markdown(root, target)))


def _validate_target(entry: str, root: Path) -> tuple[str | None, str | None]:
    """対象のパスを検証する（DocAdvisor の validate_path と同じ順）。

    シンボリックリンクの実体がプロジェクトの外にあっても除かない（DES-005 §2 の 2）。

    Returns:
        (正規化したパス, None) または (None, 対象から除く理由)。
    """
    normalized, reason = _normalize_path_entry(entry)
    if reason is not None:
        return None, reason
    target_stat = _stat_or_missing(root / normalized)
    if target_stat is None:
        return None, "存在しない"
    if Path(normalized).suffix.lower() not in MARKDOWN_SUFFIXES:
        return None, "Markdown（.md・.markdown）ではない"
    if not stat.S_ISREG(target_stat.st_mode):
        return None, "ファイルではない"
    return normalized, None


def _validate_spec_shape(target_spec: object) -> list[str]:
    if not isinstance(target_spec, dict) or not isinstance(
        target_spec.get("all"), bool
    ):
        return [
            "正規化した指定は真偽値の 'all' を持つ JSON オブジェクトである必要がある"
        ]
    if target_spec["all"]:
        if set(target_spec) != {"all"}:
            return ["単体モードの正規化した指定は 'all' だけを持つ"]
        return []
    errors = []
    if set(target_spec) != {"all", "paths", "dirs", "exclude"}:
        errors.append(
            "対象指定モードの正規化した指定は 'all'・'paths'・'dirs'・'exclude' を持つ"
        )
        return errors
    for name in ("paths", "dirs", "exclude"):
        value = target_spec[name]
        if not isinstance(value, list) or not all(
            isinstance(v, str) and v.strip() != "" for v in value
        ):
            errors.append(
                f"正規化した指定の '{name}' は空でない文字列の配列である必要がある"
            )
    return errors


def _expand_all(root: Path) -> Expansion:
    targets = sorted(_walk_markdown(root, root))
    warnings = _case_collision_warnings(targets)
    if len(targets) > MAX_FILES_WARN_THRESHOLD:
        warnings.append(
            f"対象が {len(targets)} 件で、{MAX_FILES_WARN_THRESHOLD} 件を超えている。"
            "処理は続ける"
        )
    return Expansion(targets=targets, warnings=warnings)


def expand_target_spec(target_spec: dict, project_root: Path) -> Expansion:
    """正規化した指定を、Index 対象リストへ展開する。

    ToC に保存した指定からの再展開にも使う（外部から指定が渡されない検索前検査など）。

    Args:
        target_spec: 正規化した指定。
        project_root: プロジェクトルート。

    Raises:
        TargetSpecError: 指定の形が正しくない、存在しない以外の理由で読めない。
    """
    errors = _validate_spec_shape(target_spec)
    if errors:
        raise TargetSpecError(errors)
    root = Path(project_root)
    if target_spec["all"]:
        return _expand_all(root)

    collected: dict[str, None] = {}
    rejected_dirs: list[dict] = []
    warnings: list[str] = []
    for entry in target_spec["dirs"]:
        _expand_dir_entry(root, entry, collected, rejected_dirs, warnings)
    for entry in target_spec["paths"]:
        normalized, reason = _normalize_path_entry(entry)
        collected[entry if reason is not None else normalized] = None

    exclude = [
        e for e in (_normalize_exclude_entry(v) for v in target_spec["exclude"]) if e
    ]
    excluded = sorted(
        p
        for p in collected
        if _normalize_path_entry(p)[1] is None and _is_excluded(p, exclude)
    )
    excluded_set = set(excluded)
    if excluded:
        warnings.append(f"--exclude 系で対象から除いた: {len(excluded)} 件")

    targets: set[str] = set()
    rejected_paths: list[dict] = []
    for entry in sorted(collected):
        if entry in excluded_set:
            continue
        normalized, reason = _validate_target(entry, root)
        if reason is not None:
            rejected_paths.append({"path": entry, "reason": reason})
            continue
        targets.add(normalized)

    sorted_targets = sorted(targets)
    warnings.extend(_case_collision_warnings(sorted_targets))
    return Expansion(
        targets=sorted_targets,
        excluded=excluded,
        rejected_paths=rejected_paths,
        rejected_dirs=rejected_dirs,
        warnings=warnings,
    )


def resolve_targets(
    raw: RawTargetArgs, project_root: Path, cwd: Path | None = None
) -> dict:
    """引数を検証・正規化・展開し、CLI と同じ形の結果を返す。

    Raises:
        TargetSpecError: 指定を拒否した、または展開できなかった。
    """
    key, spec = build_target_spec(raw, cwd)
    expansion = expand_target_spec(spec, project_root)
    return {
        "key": key,
        "target_spec": spec,
        "targets": expansion.targets,
        "excluded": expansion.excluded,
        "rejected_paths": expansion.rejected_paths,
        "rejected_dirs": expansion.rejected_dirs,
        "warnings": expansion.warnings,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def default_project_root() -> Path:
    """`CLAUDE_PROJECT_DIR`（存在するディレクトリのとき）、無ければカレントディレクトリ。"""
    project_dir = os.environ.get(PROJECT_DIR_ENV)
    if project_dir:
        path = Path(project_dir)
        if path.is_dir():
            return path.absolute()
        print(
            f"警告: {PROJECT_DIR_ENV}={project_dir!r} はディレクトリではない。"
            "カレントディレクトリをプロジェクトルートとする",
            file=sys.stderr,
        )
    return Path.cwd()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Index 対象指定を検証し、Markdown の一覧へ展開する"
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help=(
            f"プロジェクトルート（省略時は {PROJECT_DIR_ENV}、"
            "それも無ければカレントディレクトリ）"
        ),
    )
    parser.add_argument("--key", default=None, help="ToC 識別キー")
    parser.add_argument("--all", action="store_true", help="単体モード（予約キー all）")
    parser.add_argument("--paths", nargs="+", action="extend", default=None)
    parser.add_argument("--paths-json", action="append", default=None)
    parser.add_argument("--paths-file", default=None)
    parser.add_argument("--dirs", nargs="+", action="extend", default=None)
    parser.add_argument("--dirs-json", action="append", default=None)
    parser.add_argument("--exclude", nargs="+", action="extend", default=None)
    parser.add_argument("--exclude-json", action="append", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    raw = RawTargetArgs(
        key=args.key,
        all=args.all,
        paths=args.paths,
        paths_json=args.paths_json,
        paths_file=args.paths_file,
        dirs=args.dirs,
        dirs_json=args.dirs_json,
        exclude=args.exclude,
        exclude_json=args.exclude_json,
    )
    project_root = (
        Path(args.project_root).absolute()
        if args.project_root
        else default_project_root()
    )
    try:
        result = resolve_targets(raw, project_root)
    except TargetSpecError as e:
        print(json.dumps({"errors": e.errors}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
