"""[Index 対象指定]の検証・展開・パスの正規化を行う共通モジュール（標準ライブラリのみ）。

DES-005 §2 の 1・2 を実装する。embed-dlid・index-docs・check-dlid など複数の SKILL の script が
import して使う。このモジュールは入口 script ではないので、PEP 723 とロックは持たない（使う script が宣言する）。

- `add_target_arguments` で対象指定の引数を `argparse` に登録する
- `parse_target_arguments` で引数の組み合わせを検証し、正規化した `TargetSpec` を得る（反する指定は
  `TargetSpecError`）
- `TargetSpec.to_dict` / `TargetSpec.from_dict` で、次回に再展開できる形に保つ
- `expand` で Markdown の一覧へ展開する（存在しない・Markdown でない指定は `problems` に報告して続ける）

仕様の解釈（設計書が数値や形式を定めていない点）

- `--paths-file` のファイルは、Markdown ファイルパスの JSON 配列とする
- パス・パターンは `/` 区切りのプロジェクトルート相対で扱う。プロジェクトルートの外に出るパスは拒否する
- `--dirs` 系・`--exclude` 系のパターンは、`*`・`?`・`[` を `fnmatch` の規則で解釈する。`/` を含まなければ
  どの階層の名前とも、含めばルートからのパス（またはその祖先のパス）と、1 階層ずつ照合する
"""

import argparse
import fnmatch
import json
import os
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

RESERVED_KEY = "all"
MODE_ALL = "all"
MODE_TARGETS = "targets"

# REQ-002 §6.1 の固定の除外（この名前のディレクトリの配下を --all の走査と --dirs の展開で対象にしない）
FIXED_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".claude",
        ".codex",
        ".temp",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "target",
        "coverage",
        "__pycache__",
        ".venv",
        ".pytest_cache",
        ".mypy_cache",
    }
)

ALL_MODE_WARN_THRESHOLD = 100

PROBLEM_MISSING = "missing"
PROBLEM_NOT_MARKDOWN = "not_markdown"
PROBLEM_NOT_DIRECTORY = "not_directory"
PROBLEM_NO_MATCH = "no_match"
PROBLEM_EXCLUDED = "excluded"
PROBLEM_UNREADABLE = "unreadable"

_WILDCARD_CHARS = "*?["


class TargetSpecError(Exception):
    """対象指定を受理できない。`errors` に自然文の理由を持つ。"""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class TargetSpec:
    """正規化した[Index 対象指定]。`paths-file` の内容は `paths` へ取り込んである。"""

    mode: str
    key: str | None = None
    paths: tuple[str, ...] = ()
    dirs: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "key": self.key,
            "paths": list(self.paths),
            "dirs": list(self.dirs),
            "exclude": list(self.exclude),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TargetSpec":
        mode = data["mode"]
        if mode not in (MODE_ALL, MODE_TARGETS):
            raise TargetSpecError([f"保存された指定の mode が不正である: {mode!r}"])
        return cls(
            mode=mode,
            key=data.get("key"),
            paths=tuple(data.get("paths", [])),
            dirs=tuple(data.get("dirs", [])),
            exclude=tuple(data.get("exclude", [])),
        )


@dataclass
class Problem:
    path: str
    reason: str

    def to_dict(self) -> dict:
        return {"path": self.path, "reason": self.reason}


@dataclass
class Expansion:
    files: list[str] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "files": list(self.files),
            "problems": [problem.to_dict() for problem in self.problems],
            "warnings": list(self.warnings),
        }


def add_target_arguments(parser: argparse.ArgumentParser) -> None:
    """`--key` と対象指定の引数を登録する。組み合わせの検証は `parse_target_arguments` が行う。"""
    parser.add_argument("--key", default=None, help="[ToC 識別キー]")
    parser.add_argument("--all", dest="all_targets", action="store_true")
    parser.add_argument("--paths", nargs="+", action="extend", default=None)
    parser.add_argument("--paths-json", default=None)
    parser.add_argument("--paths-file", default=None)
    parser.add_argument("--dirs", nargs="+", action="extend", default=None)
    parser.add_argument("--dirs-json", default=None)
    parser.add_argument("--exclude", nargs="+", action="extend", default=None)
    parser.add_argument("--exclude-json", default=None)


def parse_namespace(namespace: argparse.Namespace, root: str | Path) -> TargetSpec:
    """`add_target_arguments` で得た Namespace から `TargetSpec` を作る。"""
    return parse_target_arguments(
        root=root,
        key=namespace.key,
        all_targets=namespace.all_targets,
        paths=namespace.paths,
        paths_json=namespace.paths_json,
        paths_file=namespace.paths_file,
        dirs=namespace.dirs,
        dirs_json=namespace.dirs_json,
        exclude=namespace.exclude,
        exclude_json=namespace.exclude_json,
    )


def parse_target_arguments(
    *,
    root: str | Path,
    key: str | None = None,
    all_targets: bool = False,
    paths: list[str] | None = None,
    paths_json: str | None = None,
    paths_file: str | None = None,
    dirs: list[str] | None = None,
    dirs_json: str | None = None,
    exclude: list[str] | None = None,
    exclude_json: str | None = None,
) -> TargetSpec:
    """引数の組み合わせを DES-005 §2 の 1 に従って検証し、正規化した `TargetSpec` を返す。

    反する指定は `TargetSpecError` で拒否する。指定されなかった引数は `None` で渡す。
    """
    root = os.path.abspath(root)
    has_target_spec = any(
        value is not None
        for value in (
            paths,
            paths_json,
            paths_file,
            dirs,
            dirs_json,
            exclude,
            exclude_json,
        )
    )

    errors = _check_combination(
        key=key,
        all_targets=all_targets,
        has_target_spec=has_target_spec,
        has_paths_file=paths_file is not None,
        has_paths_or_dirs=any(
            value is not None for value in (paths, paths_json, dirs, dirs_json)
        ),
        has_exclude=exclude is not None or exclude_json is not None,
        has_non_file_spec=any(
            value is not None
            for value in (paths, paths_json, dirs, dirs_json, exclude, exclude_json)
        ),
    )
    if errors:
        raise TargetSpecError(errors)

    if key is None:
        return TargetSpec(mode=MODE_ALL)

    path_items = list(paths or []) + _load_json_list(paths_json, "--paths-json")
    if paths_file is not None:
        path_items += _load_paths_file(paths_file)
    dir_items = list(dirs or []) + _load_json_list(dirs_json, "--dirs-json")
    exclude_items = list(exclude or []) + _load_json_list(
        exclude_json, "--exclude-json"
    )

    if not path_items and not dir_items:
        raise TargetSpecError(
            [
                "--key に対する対象（--paths 系・--paths-file・--dirs 系）の要素が空である"
            ]
        )

    return TargetSpec(
        mode=MODE_TARGETS,
        key=key,
        paths=_canonical(normalize_path(root, item) for item in path_items),
        dirs=_canonical(normalize_pattern(root, item) for item in dir_items),
        exclude=_canonical(normalize_pattern(root, item) for item in exclude_items),
    )


def _check_combination(
    *,
    key: str | None,
    all_targets: bool,
    has_target_spec: bool,
    has_paths_file: bool,
    has_paths_or_dirs: bool,
    has_exclude: bool,
    has_non_file_spec: bool,
) -> list[str]:
    errors = []
    if key is not None:
        if key == "":
            errors.append("--key が空である")
        if key == RESERVED_KEY:
            errors.append(
                "--key all は予約語なので指定できない（全文書は --all で指定する）"
            )
        if all_targets:
            errors.append("--all は --key と併用できない")
        if not has_target_spec:
            errors.append(
                "--key を指定したが対象指定（--paths 系・--paths-file・--dirs 系）がない"
            )
    else:
        if has_target_spec:
            errors.append(
                "対象指定（--paths 系・--paths-file・--dirs 系・--exclude 系）には --key が必要である"
                "（--key を省くと単体モードになり、対象指定を併せて渡せない）"
            )
    if has_paths_file and has_non_file_spec:
        errors.append("--paths-file はほかの対象指定と併用できない")
    if has_exclude and all_targets:
        errors.append("--exclude 系は --all と併用できない")
    if (
        key is not None
        and has_target_spec
        and not has_paths_file
        and not has_paths_or_dirs
    ):
        errors.append(
            "--key を指定したが対象（--paths 系・--paths-file・--dirs 系）がなく、--exclude 系だけである"
        )
    return errors


def _load_json_list(text: str | None, option: str) -> list[str]:
    if text is None:
        return []
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise TargetSpecError([f"{option} が JSON として読めない: {error}"]) from error
    return _require_string_list(value, option)


def _load_paths_file(path: str) -> list[str]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise TargetSpecError([f"--paths-file を読めない: {path}: {error}"]) from error
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise TargetSpecError(
            [f"--paths-file が JSON として読めない: {path}: {error}"]
        ) from error
    return _require_string_list(value, f"--paths-file の内容 ({path})")


def _require_string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TargetSpecError([f"{label} は文字列の配列でなければならない"])
    return value


def _canonical(items) -> tuple[str, ...]:
    """重複を除き、並べ替える。同じ指定は引数の順序によらず同じ形になる。"""
    return tuple(sorted(set(items)))


def normalize_path(root: str, raw: str) -> str:
    """NFC に揃え、`./` と、ルートの中に収まる `..` を解決したルート相対パス（`/` 区切り）を返す。

    ルートの外に出るパス・空のパスは `TargetSpecError` で拒否する。ルート自身は `.` で表す。
    """
    text = unicodedata.normalize("NFC", raw)
    if text == "":
        raise TargetSpecError(["空のパスは指定できない"])
    if os.path.isabs(text):
        text = os.path.relpath(text, root)
    normalized = os.path.normpath(text).replace(os.sep, "/")
    if normalized == ".." or normalized.startswith("../"):
        raise TargetSpecError(
            [f"プロジェクトルートの外に出るパスは指定できない: {raw}"]
        )
    return normalized


def normalize_pattern(root: str, raw: str) -> str:
    """パターンまたはパスを正規化する。`normalize_path` と同じ規則を使う。"""
    return normalize_path(root, raw)


def is_markdown(path: str) -> bool:
    """拡張子 `.md` を大文字小文字を区別せずに Markdown とする。`.markdown` は含めない。"""
    return os.path.splitext(path)[1].lower() == ".md"


def _is_pattern(text: str) -> bool:
    return any(char in text for char in _WILDCARD_CHARS)


def _matches(pattern: str, parts: list[str]) -> bool:
    """パターン（またはパス）が、`parts` が表すパスまたはその祖先のパスに一致するか。

    - `/` を含まない要素は、どの階層の名前とも照合する。ワイルドカードを含まない要素は
      ディレクトリ名とだけ照合し、ファイル名とは照合しない
    - `/` を含む要素は、ルートからのパスと 1 階層ずつ照合し、一致したものの配下も一致とする
    """
    if "/" not in pattern:
        names = parts if _is_pattern(pattern) else parts[:-1]
        return any(fnmatch.fnmatchcase(name, pattern) for name in names)
    pattern_parts = pattern.split("/")
    if len(parts) < len(pattern_parts):
        return False
    return all(
        fnmatch.fnmatchcase(name, expected)
        for name, expected in zip(parts, pattern_parts)
    )


def _has_fixed_excluded_dir(parts: list[str]) -> bool:
    return any(name in FIXED_EXCLUDED_DIR_NAMES for name in parts)


def _walk(
    root: str, start: str, unreadable: list[str] | None = None
) -> tuple[list[str], list[str]]:
    """`start`（ルート相対）の配下を、シンボリックリンクをたどって走査する。

    固定の除外に挙げた名前のディレクトリへは入らない。戻り値は（ディレクトリの一覧、
    Markdown ファイルの一覧）で、どちらもルート相対パス。循環するリンクは祖先に戻る分だけ打ち切る。
    読めなかったディレクトリ（権限不足など）は、`unreadable` が渡されたときにそのパスを追加する
    （黙って空として扱わない。配下の文書は一覧に入らないので、呼び出し側が判定できるようにする）。
    """
    dirs: list[str] = []
    files: list[str] = []
    start_abs = root if start == "." else os.path.join(root, start)

    def visit(directory_abs: str, relative: str, ancestors: frozenset[str]) -> None:
        try:
            entries = sorted(os.listdir(directory_abs))
        except OSError:
            if unreadable is not None:
                unreadable.append(relative)
            return
        for name in entries:
            entry_abs = os.path.join(directory_abs, name)
            nfc_name = unicodedata.normalize("NFC", name)
            entry_rel = nfc_name if relative == "." else f"{relative}/{nfc_name}"
            if os.path.isdir(entry_abs):
                if name in FIXED_EXCLUDED_DIR_NAMES:
                    continue
                real = os.path.realpath(entry_abs)
                if real in ancestors:
                    continue
                dirs.append(entry_rel)
                visit(entry_abs, entry_rel, ancestors | {real})
            elif os.path.isfile(entry_abs) and is_markdown(name):
                files.append(entry_rel)

    visit(start_abs, start, frozenset({os.path.realpath(start_abs)}))
    return dirs, files


def expand(spec: TargetSpec, root: str | Path) -> Expansion:
    """正規化した指定を Markdown ファイルの一覧（ルート相対パス、ソート済み）へ展開する。

    存在しないパス・Markdown でないパスなどは `problems` に報告し、残りの処理を続ける。
    走査中に読めなかったディレクトリ（権限不足など）も、`problems`（`unreadable`）に報告する。配下の文書は
    一覧に入らないので、呼び出し側は、一覧が完全でないものとして扱う（対象離脱や空として扱わない）。
    同じ実体（シンボリックリンクの先を含む）は、辞書順で先のパス 1 つだけ数える。
    """
    root = os.path.abspath(root)
    result = Expansion()
    candidates: set[str] = set()
    unreadable: list[str] = []

    if spec.mode == MODE_ALL:
        _dirs, files = _walk(root, ".", unreadable)
        candidates.update(files)
    else:
        for path in spec.paths:
            _add_direct_path(root, path, candidates, result)
        for entry in spec.dirs:
            _add_dir_entry(root, entry, candidates, result, unreadable)
    for path in sorted(set(unreadable)):
        result.problems.append(Problem(path, PROBLEM_UNREADABLE))

    candidates = _apply_exclude(spec.exclude, candidates, spec.paths, result)
    result.files = _dedupe_by_entity(root, sorted(candidates))
    _add_warnings(spec, candidates, result)
    return result


def _add_direct_path(
    root: str, path: str, candidates: set[str], result: Expansion
) -> None:
    absolute = os.path.join(root, path)
    if not os.path.exists(absolute):
        result.problems.append(Problem(path, PROBLEM_MISSING))
    elif not os.path.isfile(absolute) or not is_markdown(path):
        result.problems.append(Problem(path, PROBLEM_NOT_MARKDOWN))
    else:
        candidates.add(path)


def _add_dir_entry(
    root: str,
    entry: str,
    candidates: set[str],
    result: Expansion,
    unreadable: list[str] | None = None,
) -> None:
    if _is_pattern(entry):
        dirs, files = _walk(root, ".", unreadable)
        matched = False
        for directory in dirs:
            if _matches(entry, directory.split("/")):
                matched = True
        for file in files:
            if _matches(entry, file.split("/")):
                matched = True
                candidates.add(file)
        if not matched:
            result.problems.append(Problem(entry, PROBLEM_NO_MATCH))
        return
    absolute = root if entry == "." else os.path.join(root, entry)
    if not os.path.exists(absolute):
        result.problems.append(Problem(entry, PROBLEM_MISSING))
    elif not os.path.isdir(absolute):
        result.problems.append(Problem(entry, PROBLEM_NOT_DIRECTORY))
    elif entry != "." and _has_fixed_excluded_dir(entry.split("/")):
        return
    else:
        candidates.update(_walk(root, entry, unreadable)[1])


def _apply_exclude(
    exclude: tuple[str, ...],
    candidates: set[str],
    direct_paths: tuple[str, ...],
    result: Expansion,
) -> set[str]:
    kept = set()
    for file in candidates:
        parts = file.split("/")
        if any(_matches(pattern, parts) for pattern in exclude):
            if file in direct_paths:
                # 直接指定したファイルを理由なく除かない
                result.problems.append(Problem(file, PROBLEM_EXCLUDED))
            continue
        kept.add(file)
    return kept


def _dedupe_by_entity(root: str, files: list[str]) -> list[str]:
    seen: set[str] = set()
    unique = []
    for file in files:
        real = os.path.realpath(os.path.join(root, file))
        if real in seen:
            continue
        seen.add(real)
        unique.append(file)
    return unique


def _add_warnings(spec: TargetSpec, candidates: set[str], result: Expansion) -> None:
    folded: dict[str, list[str]] = {}
    for file in sorted(candidates):
        folded.setdefault(file.casefold(), []).append(file)
    for variants in folded.values():
        if len(variants) > 1:
            result.warnings.append(
                "大文字小文字だけが異なるパスがある: " + ", ".join(variants)
            )
    if spec.mode == MODE_ALL and len(result.files) > ALL_MODE_WARN_THRESHOLD:
        result.warnings.append(
            f"--all の対象が {ALL_MODE_WARN_THRESHOLD} 件を超えている: {len(result.files)} 件"
        )
