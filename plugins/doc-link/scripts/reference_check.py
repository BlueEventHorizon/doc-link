"""[正式な参照]を、指定ディレクトリの実走査で検査する共通モジュール（何も書き込まない）。

DES-007 §1、DES-009 §1 と REQ-005 FR-009・FR-010、REQ-001 D-025・D-048 を実装する。check-links・index-docs
など複数の SKILL の script が import して使う。入口 script ではないので、PEP 723 とロックは持たない。
参照の抽出は `references`、文書の解析・アンカーは `markdown_reader`、ディレクトリの走査は
`target_spec.expand` を使う（固定の除外・シンボリックリンク・NFC・Markdown 判定を再実装しない）。

保存済みの[ToC]・管理状態・[ToC 識別キー]への所属は、判定に使わない（入力にも取らない）。
検査は何も書き込まない。参照先の不在・パス不一致は、確定を妨げない検査結果として返す（例外にしない）。
例外（`ReferenceCheckError`）にするのは、参照元の文書を読めないなど、検査を行えない入力の誤りだけである。

結果の分類（`status`）

- `match`: リンク先パスの文書がその[DLID]を持つ（フラグメントがあれば到達先も確かめた）
- `path_mismatch`: 同じ指定ディレクトリ内の別パスに、その[DLID]を持つ文書が一意に見つかった（`current_path`）
- `fragment_mismatch`: 一致したが、フラグメントが到達先に解決しない（`current_anchor` に、その[DLID]の
  セクションへ届く現在のアンカー。title が文書の[DLID]のときは `None`）
- `absent`: 指定ディレクトリ内に見つからない。指定ディレクトリ自体が無い・ディレクトリを読めない・ディレクトリでない
  ことも、いずれも不在として返す（`absent_reason` に区別を残す）
- `duplicate`: 同じ[DLID]が複数見つかった。一意の現在パスを推定せず、`duplicate_paths` に見つけたものを並べる
- `unresolved`: リンク先パスを参照元から解決できない（設計書が分類を定めていない入力。下の解釈を参照）

不在の参照先を[Index 対象リスト]の中から探す（要件 D-062）

- `check_reference` は、リンク先のパスが示すディレクトリだけを走査する。別のディレクトリへ移動した文書は、そこでは
  `absent` になる
- `relocate` は、`absent` の結果を、`DlidIndex`（[Index 対象リスト]の文書を読んで作った、[DLID]と現在のパスの対応）で
  引き直す。一意に見つかれば `path_mismatch`（`current_path` に現在のパス）、複数見つかれば `duplicate`、見つからな
  ければ `absent` のままにする。指定ディレクトリが無い・読めない場合の `absent` も引き直す（ディレクトリごと
  移動した場合に当たる）
- `DlidIndex` は現物を読んだ結果だけを持つ。保存済みの[ToC]・管理状態は使わない。[Index 対象リスト]の外へ移動した
  文書は探さない

仕様の解釈（設計書が値や形式を定めていない点）

- 走査は、指定ディレクトリ（リンク先パスの親ディレクトリ）の配下を再帰的に行う。DES-005 §2 でディレクトリの指定が
  配下を再帰的に集めるのと同じである。FR-010 が「指定ディレクトリの外へ移動した文書は発見できない」と述べるので、
  配下の移動は発見できる前提とする。指定ディレクトリの外にある文書は、見つけても移動先を推測しない（不在）
- 参照元のパス・リンク先は、プロジェクトルート相対（`/` 区切り、NFC）で扱う。リンク先パスが空なら参照元の文書自身
- リンク先がプロジェクトルートの外に出るとき（絶対パスを含む）と、リンク先のパスが Markdown でないときは、
  `unresolved`（`unresolved_reason` は `outside_root`・`not_markdown`）とする。走査せず、別の結果に推測しない。
  FR-009 の「相対パスが参照元文書から正しく解決できる」に当たる
- 明示アンカーは、`<a id="…">` と `<a name="…">` のどちらも認識する（HTML ブロックと行内 HTML の `a` 要素の
  属性。コードブロック内は除く）。フラグメントはデコード後の値を、大文字小文字を区別して照合する
- フラグメントが空（`b.md#`）のときは、フラグメントなしとして扱う
- [DLID]の探索は、文書の `doc_link_id` と見出しの行の末尾の[DLID]（`Heading.section_id`）の両方で行う。
  文書として見つけたか、セクションとして見つけたかが、`target_kind`（`document`・`section`）になる
- 見つかった数は、（文書）＋（見出し）の合計で数える。同じ文書の中に同じ[セクション ID]が 2 つあるときも重複とする
- 読めない・UTF-8 として復号できない文書は、走査から除き、`unreadable_files` に残す（結果の証拠）。
  その文書に[DLID]があっても、見つかったとは扱わない
- `target_spec.expand` は、読めない下位ディレクトリを黙って飛ばす。指定ディレクトリ自体の読めなさだけを `absent` の
  `directory_unreadable` として返し、下位ディレクトリの読めなさは検出しない。固定の除外の名前の指定ディレクトリ
  （`build` など）は、参照が明示しているので走査する。その配下の固定の除外の名前は走査しない（要件 D-055）。
  `*`・`?`・`[` を含む名前のディレクトリは、
  `expand` がパターンとして扱うので、正しく扱えない
- 走査の結果は、同じ `DirectoryScanner` の間は再利用する（同じ検査の中で同じディレクトリを何度も読まない）。
  検査の時点は、検査 1 回につき 1 つで、`checked_at`（呼び出し側から渡せる。省かれたら現在の UTC）
"""

import os
import posixpath
import unicodedata
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from pathlib import Path

from clock import utc_now
from markdown_reader import (
    Heading,
    parse_markdown,
    read_document,
    read_frontmatter,
    split_lines,
)
from references import FormalReference, extract_from_document
from target_spec import (
    MODE_TARGETS,
    TargetSpec,
    expand,
    is_markdown,
)

STATUS_MATCH = "match"
STATUS_PATH_MISMATCH = "path_mismatch"
STATUS_FRAGMENT_MISMATCH = "fragment_mismatch"
STATUS_ABSENT = "absent"
STATUS_DUPLICATE = "duplicate"
STATUS_UNRESOLVED = "unresolved"

ABSENT_NOT_FOUND = "not_found"
ABSENT_DIRECTORY_MISSING = "directory_missing"
ABSENT_DIRECTORY_UNREADABLE = "directory_unreadable"
ABSENT_NOT_DIRECTORY = "not_directory"

UNRESOLVED_OUTSIDE_ROOT = "outside_root"
UNRESOLVED_NOT_MARKDOWN = "not_markdown"

KIND_DOCUMENT = "document"
KIND_SECTION = "section"


class ReferenceCheckError(Exception):
    """検査を行えない入力の誤り（参照元の文書を読めないなど）。"""


@dataclass(frozen=True)
class ScannedDocument:
    path: str
    doc_id: str | None
    headings: tuple[Heading, ...]
    explicit_anchors: frozenset[str]


@dataclass(frozen=True)
class ScannedDirectory:
    """実走査の結果。`absent_reason` が値を持つときは、走査できなかった（`documents` は空）。"""

    directory: str
    documents: dict[str, ScannedDocument] = field(default_factory=dict)
    unreadable_files: tuple[str, ...] = ()
    absent_reason: str | None = None


@dataclass(frozen=True)
class ReferenceCheckResult:
    status: str
    reference: FormalReference
    source_path: str
    resolved_path: str | None
    directory: str | None
    checked_at: str
    target_kind: str | None = None
    current_path: str | None = None
    current_anchor: str | None = None
    absent_reason: str | None = None
    unresolved_reason: str | None = None
    duplicate_paths: tuple[str, ...] = ()
    scanned_file_count: int = 0
    unreadable_files: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reference": self.reference.to_dict(),
            "source_path": self.source_path,
            "resolved_path": self.resolved_path,
            "scope": {"directory": self.directory, "checked_at": self.checked_at},
            "target_kind": self.target_kind,
            "current_path": self.current_path,
            "current_anchor": self.current_anchor,
            "absent_reason": self.absent_reason,
            "unresolved_reason": self.unresolved_reason,
            "duplicate_paths": list(self.duplicate_paths),
            "evidence": {
                "scanned_file_count": self.scanned_file_count,
                "unreadable_files": list(self.unreadable_files),
            },
        }


class _AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: set[str] = set()

    def handle_starttag(self, tag, attrs) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name in ("id", "name") and value:
                self.anchors.add(value)


def explicit_anchors(text: str) -> frozenset[str]:
    lines = split_lines(text)
    frontmatter = read_frontmatter(lines)
    offset = frontmatter.body_start_line if frontmatter.present else 0
    tokens, _env = parse_markdown("".join(lines[offset:]))
    collector = _AnchorCollector()
    for token in tokens:
        if token.type == "html_block":
            collector.feed(token.content)
        elif token.type == "inline":
            for child in token.children or []:
                if child.type == "html_inline":
                    collector.feed(child.content)
    collector.close()
    return frozenset(collector.anchors)


def _normalize(path: str) -> str:
    return unicodedata.normalize("NFC", path)


def _read_text(path: str) -> str:
    return Path(path).read_bytes().decode("utf-8")


class DirectoryScanner:
    """指定ディレクトリ（プロジェクトルート相対）の配下を実走査して、文書の一覧を得る。結果は再利用する。"""

    def __init__(self, root: str | Path) -> None:
        self.root = os.path.abspath(root)
        self._cache: dict[str, ScannedDirectory] = {}

    def scan(self, directory: str) -> ScannedDirectory:
        if directory not in self._cache:
            self._cache[directory] = self._scan(directory)
        return self._cache[directory]

    def _scan(self, directory: str) -> ScannedDirectory:
        absolute = self.root if directory == "." else os.path.join(self.root, directory)
        try:
            os.stat(absolute)
        except (FileNotFoundError, NotADirectoryError):
            return ScannedDirectory(directory, absent_reason=ABSENT_DIRECTORY_MISSING)
        except OSError:
            return ScannedDirectory(
                directory, absent_reason=ABSENT_DIRECTORY_UNREADABLE
            )
        if not os.path.isdir(absolute):
            return ScannedDirectory(directory, absent_reason=ABSENT_NOT_DIRECTORY)
        try:
            os.listdir(absolute)
        except OSError:
            return ScannedDirectory(
                directory, absent_reason=ABSENT_DIRECTORY_UNREADABLE
            )
        # 参照の明示するディレクトリそのものは、固定の除外の名前でも走査する（要件 D-055）
        expansion = expand(
            TargetSpec(mode=MODE_TARGETS, dirs=(directory,)),
            self.root,
            scan_excluded_start=True,
        )
        documents: dict[str, ScannedDocument] = {}
        unreadable: list[str] = []
        for path in expansion.files:
            try:
                text = _read_text(os.path.join(self.root, path))
            except (OSError, UnicodeDecodeError):
                unreadable.append(path)
                continue
            document = read_document(text)
            documents[path] = ScannedDocument(
                path=path,
                doc_id=document.frontmatter.doc_link_id,
                headings=document.headings,
                explicit_anchors=explicit_anchors(text),
            )
        return ScannedDirectory(
            directory,
            documents=documents,
            unreadable_files=tuple(unreadable),
        )


def _relative_to_root(root: str, path: str) -> str:
    text = _normalize(path)
    if os.path.isabs(text):
        text = os.path.relpath(text, root)
    return posixpath.normpath(text.replace(os.sep, "/"))


def _resolve_target(source_path: str, reference: FormalReference) -> str | None:
    """参照元を基準にリンク先を解決する。ルートの外に出るときは `None`。"""
    if reference.path == "":
        return source_path
    link = _normalize(reference.path)
    if link.startswith("/"):
        return None
    target = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), link))
    if target == ".." or target.startswith("../"):
        return None
    return target


@dataclass(frozen=True)
class _Hit:
    path: str
    kind: str
    heading: Heading | None


def _find_hits(scanned: ScannedDirectory, dlid: str) -> list[_Hit]:
    hits = []
    for path in sorted(scanned.documents):
        document = scanned.documents[path]
        if document.doc_id == dlid:
            hits.append(_Hit(path, KIND_DOCUMENT, None))
        for heading in document.headings:
            if heading.section_id == dlid:
                hits.append(_Hit(path, KIND_SECTION, heading))
    return hits


def check_reference(
    root: str | Path,
    source_path: str,
    reference: FormalReference,
    *,
    checked_at: str | None = None,
    scanner: DirectoryScanner | None = None,
) -> ReferenceCheckResult:
    """[正式な参照] 1 件を、リンク先の親ディレクトリの実走査で検査する。

    `source_path` は参照元の文書のプロジェクトルート相対パス。何も書き込まない。
    """
    scanner = scanner or DirectoryScanner(root)
    when = checked_at or utc_now()
    source = _relative_to_root(scanner.root, source_path)

    def result(**values) -> ReferenceCheckResult:
        return ReferenceCheckResult(
            reference=reference,
            source_path=source,
            checked_at=when,
            **values,
        )

    target = _resolve_target(source, reference)
    if target is None:
        return result(
            status=STATUS_UNRESOLVED,
            resolved_path=None,
            directory=None,
            unresolved_reason=UNRESOLVED_OUTSIDE_ROOT,
        )
    if not is_markdown(target):
        return result(
            status=STATUS_UNRESOLVED,
            resolved_path=target,
            directory=None,
            unresolved_reason=UNRESOLVED_NOT_MARKDOWN,
        )

    directory = posixpath.dirname(target) or "."
    scanned = scanner.scan(directory)
    common = dict(
        resolved_path=target,
        directory=directory,
        scanned_file_count=len(scanned.documents),
        unreadable_files=scanned.unreadable_files,
    )
    if scanned.absent_reason is not None:
        return result(
            status=STATUS_ABSENT, absent_reason=scanned.absent_reason, **common
        )

    hits = _find_hits(scanned, reference.dlid)
    if not hits:
        return result(status=STATUS_ABSENT, absent_reason=ABSENT_NOT_FOUND, **common)
    if len(hits) > 1:
        return result(
            status=STATUS_DUPLICATE,
            duplicate_paths=tuple(sorted({hit.path for hit in hits})),
            **common,
        )

    hit = hits[0]
    if hit.path != target:
        return result(
            status=STATUS_PATH_MISMATCH,
            target_kind=hit.kind,
            current_path=hit.path,
            **common,
        )

    fragment = reference.fragment
    if not fragment:
        return result(
            status=STATUS_MATCH, target_kind=hit.kind, current_path=hit.path, **common
        )
    document = scanned.documents[hit.path]
    if hit.kind == KIND_SECTION:
        current_anchor = hit.heading.anchor
        resolved = fragment == current_anchor
    else:
        current_anchor = None
        resolved = fragment in document.explicit_anchors or any(
            fragment == heading.anchor for heading in document.headings
        )
    return result(
        status=STATUS_MATCH if resolved else STATUS_FRAGMENT_MISMATCH,
        target_kind=hit.kind,
        current_path=hit.path,
        current_anchor=None if resolved else current_anchor,
        **common,
    )


class DlidIndex:
    """[Index 対象リスト]の文書から読んだ、[DLID]と現在のパスの対応（要件 D-062）。

    現物を読んだ結果だけを持つ。保存済みの[ToC]・管理状態は入力に取らない。
    """

    def __init__(self) -> None:
        self._hits: dict[str, list[tuple[str, str]]] = {}

    def add_document(
        self, path: str, doc_id: str | None, headings: tuple[Heading, ...]
    ) -> None:
        """文書 1 件の[文書 ID]と、見出しの[セクション ID]を足す。"""
        if doc_id is not None:
            self._hits.setdefault(doc_id, []).append((path, KIND_DOCUMENT))
        for heading in headings:
            if heading.section_id is not None:
                self._hits.setdefault(heading.section_id, []).append(
                    (path, KIND_SECTION)
                )

    def find(self, dlid: str) -> tuple[tuple[str, str], ...]:
        """その[DLID]を持つ箇所の（パス、種別）。同じ文書の中の重複も、別の箇所として数える。"""
        return tuple(self._hits.get(dlid, ()))


def build_index(root: str | Path, paths) -> DlidIndex:
    """[Index 対象リスト]の文書を読んで、対応を作る。読めない文書は、見つかったとは扱わない。"""
    index = DlidIndex()
    base = os.path.abspath(root)
    for path in paths:
        try:
            text = _read_text(os.path.join(base, path))
        except (OSError, UnicodeDecodeError):
            continue
        document = read_document(text)
        index.add_document(path, document.frontmatter.doc_link_id, document.headings)
    return index


def relocate(result: ReferenceCheckResult, index: DlidIndex) -> ReferenceCheckResult:
    """不在の参照先を、[Index 対象リスト]の文書の中から探す（要件 D-062）。

    リンク先のパスが示すディレクトリに参照先が無い（`absent`）ときだけ働く。一意に見つかればパスの不一致
    （`current_path` に現在のパス）、複数見つかれば重複にする。見つからなければ、不在のまま返す。
    [Index 対象リスト]の外へ移動した文書は探さない。
    """
    if result.status != STATUS_ABSENT:
        return result
    hits = index.find(result.reference.dlid)
    if not hits:
        return result
    if len(hits) > 1:
        return replace(
            result,
            status=STATUS_DUPLICATE,
            absent_reason=None,
            duplicate_paths=tuple(sorted({path for path, _kind in hits})),
        )
    path, kind = hits[0]
    if path == result.resolved_path:
        # リンク先のパスそのものにある。ディレクトリを走査できなかった不在であり、パスは違っていない
        return result
    return replace(
        result,
        status=STATUS_PATH_MISMATCH,
        absent_reason=None,
        target_kind=kind,
        current_path=path,
    )


def check_document(
    root: str | Path,
    source_path: str,
    *,
    checked_at: str | None = None,
    scanner: DirectoryScanner | None = None,
) -> list[ReferenceCheckResult]:
    """参照元の文書の[正式な参照]をすべて検査する（定義の行の順）。

    参照元の文書を読めない（存在しない・UTF-8 として復号できない）ときは `ReferenceCheckError`。
    """
    scanner = scanner or DirectoryScanner(root)
    source = _relative_to_root(scanner.root, source_path)
    try:
        text = _read_text(os.path.join(scanner.root, source))
    except (OSError, UnicodeDecodeError) as error:
        raise ReferenceCheckError(
            f"参照元の文書を読めない: {source}: {error}"
        ) from error
    when = checked_at or utc_now()
    return [
        check_reference(root, source, reference, checked_at=when, scanner=scanner)
        for reference in extract_from_document(read_document(text))
    ]
