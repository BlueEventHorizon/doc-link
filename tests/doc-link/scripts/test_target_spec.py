"""プラグイン共通 script `target_spec.py`（Index 対象指定の検証と展開）の単体テスト。

期待値は DES-005 §2 の 1・2、§2.1、REQ-002 FR-017・AC-022・§6.1・§8、REQ-001 §17.1、
D-020・D-041、script_error_output_rules.md から導く。DES-005 §2 の 2 が DocAdvisor と
同じとする細部（展開・除外・パスの正規化・シンボリックリンク・警告）は、DocAdvisor の
`expand_dirs.py`・`prepare_toc.py`・`toc_utils.py`・`toc_store.py` の挙動から導き、
各テストのコメントに根拠の行を書く。プロジェクトルートはテスト内で作る一時的な
ディレクトリに向ける。
"""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _REPO_ROOT / "plugins" / "doc-link" / "scripts"
_SCRIPT = _SCRIPTS_DIR / "target_spec.py"
sys.path.insert(0, str(_SCRIPTS_DIR))

import target_spec as ts  # noqa: E402

Raw = ts.RawTargetArgs


def _touch(root: Path, rel: str, text: str = "# t\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run_cli(argv: list[str]) -> tuple[int, dict | None, str]:
    """CLI を同じプロセスで実行し、終了コード・標準出力の JSON・標準出力の原文を返す。"""
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = ts.main(argv)
        except SystemExit as e:  # argparse の引数エラー
            code = e.code
    text = out.getvalue()
    data = json.loads(text) if text.strip() else None
    return code, data, text


class _TempProject(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)

    def resolve(self, raw: ts.RawTargetArgs) -> dict:
        return ts.resolve_targets(raw, self.root, cwd=self.root)

    def assertRejected(self, raw: ts.RawTargetArgs, pattern: str) -> list[str]:
        with self.assertRaises(ts.TargetSpecError) as cm:
            self.resolve(raw)
        errors = cm.exception.errors
        self.assertIsInstance(errors, list)
        self.assertTrue(
            any(re.search(pattern, e) for e in errors),
            f"{pattern!r} を含む理由が無い: {errors}",
        )
        return errors


# ---------------------------------------------------------------------------
# DES-005 §2 の 1: 組み合わせの規則（受理する例と拒否する例）
# ---------------------------------------------------------------------------


class TestCombinationRules(_TempProject):
    def setUp(self):
        super().setUp()
        _touch(self.root, "docs/a.md")
        _touch(self.root, "docs/b.md")
        _touch(self.root, "specs/c.md")

    # 規則: --paths と --paths-json、--dirs と --dirs-json、--exclude と --exclude-json は併用でき、連結する
    def test_accept_paths_and_paths_json_are_concatenated(self):
        result = self.resolve(
            Raw(key="k", paths=["docs/a.md"], paths_json=['["docs/b.md"]'])
        )
        self.assertEqual(result["targets"], ["docs/a.md", "docs/b.md"])
        self.assertEqual(result["target_spec"]["paths"], ["docs/a.md", "docs/b.md"])

    def test_accept_dirs_and_dirs_json_are_concatenated(self):
        result = self.resolve(Raw(key="k", dirs=["docs"], dirs_json=['["specs"]']))
        self.assertEqual(result["targets"], ["docs/a.md", "docs/b.md", "specs/c.md"])

    def test_accept_exclude_and_exclude_json_are_concatenated(self):
        result = self.resolve(
            Raw(
                key="k",
                dirs=["."],
                exclude=["docs/a.md"],
                exclude_json=['["specs"]'],
            )
        )
        self.assertEqual(result["targets"], ["docs/b.md"])
        self.assertEqual(result["target_spec"]["exclude"], ["docs/a.md", "specs"])

    def test_reject_malformed_json_form(self):
        self.assertRejected(Raw(key="k", dirs_json=["[docs"]), "--dirs-json")
        self.assertRejected(Raw(key="k", paths_json=['{"a": 1}']), "JSON 配列")
        self.assertRejected(
            Raw(key="k", dirs=["docs"], exclude_json=["[1]"]), "--exclude"
        )

    # 規則: 対象指定には --key が必要。--key を省くと単体モードで、対象指定を併せて渡せない
    def test_accept_target_with_key(self):
        result = self.resolve(Raw(key="rules", dirs=["docs"]))
        self.assertEqual(result["key"], "rules")
        self.assertEqual(result["targets"], ["docs/a.md", "docs/b.md"])

    def test_reject_each_target_without_key(self):
        paths_file = self.root / "list.json"
        paths_file.write_text('["docs/a.md"]', encoding="utf-8")
        cases = {
            "--paths": Raw(paths=["docs/a.md"]),
            "--paths-json": Raw(paths_json=['["docs/a.md"]']),
            "--paths-file": Raw(paths_file=str(paths_file)),
            "--dirs": Raw(dirs=["docs"]),
            "--dirs-json": Raw(dirs_json=['["docs"]']),
            "--exclude": Raw(exclude=["docs"]),
            "--exclude-json": Raw(exclude_json=['["docs"]']),
        }
        for flag, raw in cases.items():
            with self.subTest(flag=flag):
                self.assertRejected(
                    raw, r"--key を省いた単体モード.*" + re.escape(flag)
                )

    # 規則: --key all は予約語なので指定できない。空の --key も拒否する
    def test_accept_non_reserved_key(self):
        self.assertEqual(self.resolve(Raw(key="All", dirs=["docs"]))["key"], "All")

    def test_reject_reserved_key_all(self):
        self.assertRejected(Raw(key="all", dirs=["docs"]), "--key all は予約語")

    def test_reject_empty_key(self):
        self.assertRejected(Raw(key="", dirs=["docs"]), "--key が空")

    # キーの検証は NFC 化してから行う（toc_store.py:253-293）
    def test_reject_blank_key(self):
        self.assertRejected(Raw(key=" \t", dirs=["docs"]), "--key が空")

    def test_accept_key_with_spaces_around_all(self):
        # strip するのは空の判定だけで、予約語との照合は NFC 化した値そのもので行う
        self.assertEqual(self.resolve(Raw(key=" all", dirs=["docs"]))["key"], " all")

    def test_key_is_returned_in_nfc(self):
        nfd = unicodedata.normalize("NFD", "ガイド")
        self.assertNotEqual(nfd, "ガイド")
        self.assertEqual(self.resolve(Raw(key=nfd, dirs=["docs"]))["key"], "ガイド")

    # 規則: --all は対象指定と併用できない
    def test_accept_all_alone(self):
        result = self.resolve(Raw(all=True))
        self.assertEqual(result["key"], "all")
        self.assertEqual(result["target_spec"], {"all": True})

    def test_reject_all_with_each_target(self):
        cases = {
            "--paths": Raw(all=True, paths=["docs/a.md"]),
            "--paths-json": Raw(all=True, paths_json=['["docs/a.md"]']),
            "--paths-file": Raw(all=True, paths_file="list.json"),
            "--dirs": Raw(all=True, dirs=["docs"]),
            "--dirs-json": Raw(all=True, dirs_json=['["docs"]']),
            "--exclude": Raw(all=True, exclude=["docs"]),
            "--exclude-json": Raw(all=True, exclude_json=['["docs"]']),
        }
        for flag, raw in cases.items():
            with self.subTest(flag=flag):
                self.assertRejected(raw, r"--all は対象指定.*" + re.escape(flag))

    def test_reject_all_with_key(self):
        self.assertRejected(Raw(all=True, key="k"), "--all と --key は併用できない")

    # 規則: --paths-file はほかの対象指定と併用できない
    def test_accept_paths_file_alone(self):
        (self.root / "list.json").write_text(
            '["docs/b.md", "docs/a.md"]', encoding="utf-8"
        )
        result = self.resolve(Raw(key="k", paths_file="list.json"))
        self.assertEqual(result["targets"], ["docs/a.md", "docs/b.md"])

    def test_reject_paths_file_with_other_targets(self):
        cases = {
            "--paths": Raw(key="k", paths_file="l.json", paths=["docs/a.md"]),
            "--paths-json": Raw(key="k", paths_file="l.json", paths_json=["[]"]),
            "--dirs": Raw(key="k", paths_file="l.json", dirs=["docs"]),
            "--dirs-json": Raw(key="k", paths_file="l.json", dirs_json=["[]"]),
        }
        for flag, raw in cases.items():
            with self.subTest(flag=flag):
                self.assertRejected(
                    raw, r"--paths-file はほかの対象指定.*" + re.escape(flag)
                )

    def test_reject_unreadable_paths_file(self):
        self.assertRejected(
            Raw(key="k", paths_file="missing.json"), "--paths-file を読めない"
        )

    # 規則: --exclude 系は --all・--paths-file と併用できない
    def test_accept_exclude_with_dirs_and_paths(self):
        result = self.resolve(
            Raw(key="k", dirs=["docs"], paths=["specs/c.md"], exclude=["docs/a.md"])
        )
        self.assertEqual(result["targets"], ["docs/b.md", "specs/c.md"])

    def test_reject_exclude_with_all(self):
        for raw in (
            Raw(all=True, exclude=["docs"]),
            Raw(all=True, exclude_json=['["docs"]']),
        ):
            with self.subTest(raw=raw):
                self.assertRejected(raw, r"--exclude.* は --all と併用できない")

    def test_reject_exclude_with_paths_file(self):
        for raw in (
            Raw(key="k", paths_file="l.json", exclude=["docs"]),
            Raw(key="k", paths_file="l.json", exclude_json=['["docs"]']),
        ):
            with self.subTest(raw=raw):
                self.assertRejected(raw, r"--exclude.* は --paths-file と併用できない")

    # 規則: --key を指定したのに対象指定が無い指定は拒否する（REQ-001 §17.1）
    def test_reject_key_without_target(self):
        self.assertRejected(Raw(key="k"), "--key を指定したが対象指定が無い")

    def test_accept_key_with_empty_json_target(self):
        # フラグが渡されていれば、配列が空でも対象指定がある（空の desired state）
        result = self.resolve(Raw(key="k", dirs_json=["[]"]))
        self.assertEqual(result["targets"], [])

    # 規則: 引数が無いときは --all として扱う
    def test_no_arguments_is_all(self):
        self.assertEqual(self.resolve(Raw()), self.resolve(Raw(all=True)))
        result = self.resolve(Raw())
        self.assertEqual(result["key"], "all")
        self.assertEqual(result["target_spec"], {"all": True})
        self.assertEqual(result["targets"], ["docs/a.md", "docs/b.md", "specs/c.md"])

    def test_cli_without_arguments_is_all(self):
        code_none, data_none, _ = _run_cli(["--project-root", str(self.root)])
        code_all, data_all, _ = _run_cli(["--project-root", str(self.root), "--all"])
        self.assertEqual((code_none, code_all), (0, 0))
        self.assertEqual(data_none, data_all)
        self.assertEqual(data_none["key"], "all")

    def test_reports_all_violated_rules(self):
        errors = self.assertRejected(
            Raw(all=True, key="all", exclude=["docs"]), "--all と --key"
        )
        self.assertTrue(any("予約語" in e for e in errors), errors)
        self.assertTrue(any("--exclude は --all" in e for e in errors), errors)


# ---------------------------------------------------------------------------
# DES-005 §2 の 2: 展開と除外
# ---------------------------------------------------------------------------


class TestExpansion(_TempProject):
    def setUp(self):
        super().setUp()
        for rel in (
            "README.md",
            "docs/a.md",
            "docs/notes.txt",
            "docs/sub/b.md",
            "docs/draft/c.md",
            "docs/sub/draft/d.md",
            "docs/drafts.md",
            "docs/x.md.bak",
            "specs/req/r.md",
            "specs/design/d.md",
            "specs/design/e.md",
            "other/o.md",
        ):
            _touch(self.root, rel)

    def test_literal_dir_collects_markdown_recursively_only(self):
        result = self.resolve(Raw(key="k", dirs=["docs"]))
        self.assertEqual(
            result["targets"],
            [
                "docs/a.md",
                "docs/draft/c.md",
                "docs/drafts.md",
                "docs/sub/b.md",
                "docs/sub/draft/d.md",
            ],
        )

    def test_targets_contain_nothing_outside_specification(self):
        result = self.resolve(Raw(key="k", dirs=["specs/design"], paths=["README.md"]))
        self.assertEqual(
            result["targets"], ["README.md", "specs/design/d.md", "specs/design/e.md"]
        )

    def test_pattern_matching_directories_collects_their_markdown(self):
        result = self.resolve(Raw(key="k", dirs=["specs/*"]))
        self.assertEqual(
            result["targets"],
            ["specs/design/d.md", "specs/design/e.md", "specs/req/r.md"],
        )

    def test_pattern_matching_markdown_files_adds_them(self):
        result = self.resolve(Raw(key="k", dirs=["specs/design/[d]*"]))
        self.assertEqual(result["targets"], ["specs/design/d.md"])

    def test_pattern_with_question_mark(self):
        result = self.resolve(Raw(key="k", dirs=["docs/?.md"]))
        self.assertEqual(result["targets"], ["docs/a.md"])

    def test_pattern_does_not_add_non_markdown_files(self):
        result = self.resolve(Raw(key="k", dirs=["docs/*.txt"]))
        self.assertEqual(result["targets"], [])
        self.assertEqual(result["rejected_dirs"], [])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("docs/*.txt", result["warnings"][0])

    # 存在しないディレクトリは rejected_dirs、一致の無いパターンは warnings（expand_dirs.py:188-209）
    def test_missing_dir_and_unmatched_pattern_are_reported_not_rejected(self):
        result = self.resolve(Raw(key="k", dirs=["docs/sub", "gone", "nothing/*"]))
        self.assertEqual(result["targets"], ["docs/sub/b.md", "docs/sub/draft/d.md"])
        self.assertEqual(
            result["rejected_dirs"], [{"dir": "gone", "reason": "存在しない"}]
        )
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("nothing/*", result["warnings"][0])

    def test_dir_that_is_a_file_is_rejected_dir(self):
        result = self.resolve(Raw(key="k", dirs=["docs/a.md", "specs/req"]))
        self.assertEqual(result["targets"], ["specs/req/r.md"])
        self.assertEqual(
            result["rejected_dirs"],
            [{"dir": "docs/a.md", "reason": "ディレクトリではない"}],
        )

    # 存在しない・Markdown でない明示パスは除いて続行する（prepare_toc.py:210-249）
    def test_missing_explicit_path_is_excluded_and_reported(self):
        result = self.resolve(Raw(key="k", paths=["docs/a.md", "docs/none.md"]))
        self.assertEqual(result["targets"], ["docs/a.md"])
        self.assertEqual(
            result["rejected_paths"], [{"path": "docs/none.md", "reason": "存在しない"}]
        )

    def test_non_markdown_explicit_path_is_excluded_and_reported(self):
        result = self.resolve(Raw(key="k", paths=["docs/a.md", "docs/notes.txt"]))
        self.assertEqual(result["targets"], ["docs/a.md"])
        self.assertEqual(
            [r["path"] for r in result["rejected_paths"]], ["docs/notes.txt"]
        )
        self.assertIn("Markdown", result["rejected_paths"][0]["reason"])

    def test_explicit_directory_is_not_a_markdown_file(self):
        result = self.resolve(Raw(key="k", paths=["docs"]))
        self.assertEqual(result["targets"], [])
        self.assertIn("Markdown", result["rejected_paths"][0]["reason"])

    def test_explicit_directory_with_markdown_suffix_is_not_a_file(self):
        (self.root / "dir.md").mkdir()
        result = self.resolve(Raw(key="k", paths=["dir.md"]))
        self.assertEqual(
            result["rejected_paths"], [{"path": "dir.md", "reason": "ファイルではない"}]
        )

    def test_missing_path_is_checked_before_markdown(self):
        # 検証の順は DocAdvisor の validate_path と同じ（存在 → Markdown）
        result = self.resolve(Raw(key="k", paths=["docs/none.txt"]))
        self.assertEqual(result["rejected_paths"][0]["reason"], "存在しない")

    def test_paths_file_entries_are_validated(self):
        (self.root / "l.json").write_text(
            '["docs/missing.md", "docs/a.md"]', encoding="utf-8"
        )
        result = self.resolve(Raw(key="k", paths_file="l.json"))
        self.assertEqual(result["targets"], ["docs/a.md"])
        self.assertEqual(
            result["rejected_paths"],
            [{"path": "docs/missing.md", "reason": "存在しない"}],
        )

    def test_paths_file_object_form_is_rejected_with_guidance(self):
        (self.root / "l.json").write_text('{"paths": ["docs/a.md"]}', encoding="utf-8")
        self.assertRejected(Raw(key="k", paths_file="l.json"), "配列そのもの")

    def test_empty_string_elements_are_rejected(self):
        for raw in (
            Raw(key="k", paths=[" "]),
            Raw(key="k", dirs_json=['[""]']),
            Raw(key="k", dirs=["docs"], exclude_json=['["  "]']),
        ):
            with self.subTest(raw=raw):
                self.assertRejected(raw, "空でない文字列")

    # Markdown の判定（toc_utils.py:215,289、expand_dirs.py:196、MARKDOWN_GLOB）
    def test_explicit_paths_accept_md_and_markdown_case_insensitively(self):
        _touch(self.root, "m/a.MD")
        _touch(self.root, "m/b.markdown")
        _touch(self.root, "m/c.Markdown")
        result = self.resolve(
            Raw(key="k", paths=["m/a.MD", "m/b.markdown", "m/c.Markdown"])
        )
        self.assertEqual(result["targets"], ["m/a.MD", "m/b.markdown", "m/c.Markdown"])
        self.assertEqual(result["rejected_paths"], [])

    def test_directory_walk_collects_only_lowercase_md(self):
        _touch(self.root, "m/a.MD")
        _touch(self.root, "m/b.markdown")
        _touch(self.root, "m/c.md")
        self.assertEqual(self.resolve(Raw(key="k", dirs=["m"]))["targets"], ["m/c.md"])
        self.assertEqual(self.resolve(Raw(all=True))["targets"].count("m/c.md"), 1)
        self.assertNotIn("m/a.MD", self.resolve(Raw(all=True))["targets"])

    def test_pattern_matched_file_accepts_md_case_insensitively_only(self):
        _touch(self.root, "m/a.MD")
        _touch(self.root, "m/b.markdown")
        result = self.resolve(Raw(key="k", dirs=["m/*"]))
        self.assertEqual(result["targets"], ["m/a.MD"])

    # 除外は存在・Markdown の検証より先に適用する（index_docs.py:528-535）
    def test_exclude_is_applied_before_validation(self):
        result = self.resolve(
            Raw(key="k", paths=["docs/a.md", "docs/draft/none.md"], exclude=["draft"])
        )
        self.assertEqual(result["targets"], ["docs/a.md"])
        self.assertEqual(result["excluded"], ["docs/draft/none.md"])
        self.assertEqual(result["rejected_paths"], [])

    # 除外: `/` を含まない名前はどの階層の同じ名前のディレクトリとも完全一致で照合し、ファイル名とは照合しない
    def test_exclude_name_matches_directories_at_any_depth(self):
        result = self.resolve(Raw(key="k", dirs=["docs"], exclude=["draft"]))
        self.assertEqual(
            result["targets"], ["docs/a.md", "docs/drafts.md", "docs/sub/b.md"]
        )
        self.assertEqual(result["excluded"], ["docs/draft/c.md", "docs/sub/draft/d.md"])
        # 除いた件数を warnings で報告する（index_docs.py:535,549）
        self.assertEqual(result["warnings"], ["--exclude 系で対象から除いた: 2 件"])

    def test_no_exclude_warning_when_nothing_excluded(self):
        result = self.resolve(Raw(key="k", dirs=["docs"], exclude=["nothing"]))
        self.assertEqual(result["excluded"], [])
        self.assertEqual(result["warnings"], [])

    def test_exclude_name_does_not_match_file_names(self):
        result = self.resolve(
            Raw(key="k", dirs=["docs"], exclude=["a.md", "drafts.md"])
        )
        self.assertIn("docs/a.md", result["targets"])
        self.assertIn("docs/drafts.md", result["targets"])
        self.assertEqual(result["excluded"], [])

    # 要件 REQ-002 §6.1: パターンで除外できる（DocAdvisor と異なる）
    def test_exclude_pattern_matches_names_and_paths(self):
        _touch(self.root, "docs/x.draft.md")
        cases = {
            "*.draft.md": ["docs/x.draft.md"],
            "dra?t": ["docs/draft/c.md", "docs/sub/draft/d.md"],
            "docs/*/draft": ["docs/sub/draft/d.md"],
            "docs/**/c.md": ["docs/draft/c.md"],
        }
        for pattern, expected in cases.items():
            with self.subTest(pattern=pattern):
                result = self.resolve(Raw(key="k", dirs=["docs"], exclude=[pattern]))
                self.assertEqual(result["excluded"], expected)
                self.assertFalse(set(expected) & set(result["targets"]))

    def test_exclude_name_is_exact_not_prefix(self):
        result = self.resolve(Raw(key="k", dirs=["docs"], exclude=["dra", "su"]))
        self.assertEqual(result["excluded"], [])

    # 除外: `/` を含めば、パスとの完全一致、またはその配下で照合する
    def test_exclude_path_matches_exact_file(self):
        result = self.resolve(Raw(key="k", dirs=["docs"], exclude=["docs/sub/b.md"]))
        self.assertNotIn("docs/sub/b.md", result["targets"])
        self.assertIn("docs/sub/draft/d.md", result["targets"])

    def test_exclude_path_matches_subtree_only_at_segment_boundary(self):
        result = self.resolve(Raw(key="k", dirs=["docs"], exclude=["docs/draft"]))
        self.assertNotIn("docs/draft/c.md", result["targets"])
        # docs/drafts.md はセグメント境界が違うので除かない。別階層の draft も除かない
        self.assertIn("docs/drafts.md", result["targets"])
        self.assertIn("docs/sub/draft/d.md", result["targets"])

    def test_exclude_applies_to_explicit_paths(self):
        result = self.resolve(
            Raw(key="k", paths=["docs/a.md", "docs/draft/c.md"], exclude=["draft"])
        )
        self.assertEqual(result["targets"], ["docs/a.md"])
        self.assertEqual(result["excluded"], ["docs/draft/c.md"])

    def test_exclude_trailing_slash_is_stripped(self):
        result = self.resolve(Raw(key="k", dirs=["docs"], exclude=["draft/"]))
        self.assertEqual(result["target_spec"]["exclude"], ["draft"])
        self.assertNotIn("docs/sub/draft/d.md", result["targets"])

    # 除外の正規化は NFC と前後の `/` の除去だけ（toc_utils.py:862-865）
    def test_exclude_is_normalized_like_docadvisor(self):
        nfd = unicodedata.normalize("NFD", "ドキュメント")
        _touch(self.root, "ドキュメント/z.md")
        result = self.resolve(
            Raw(key="k", dirs=["."], exclude=[f"/{nfd}/", "/", "./docs", "docs/../x"])
        )
        self.assertEqual(
            result["target_spec"]["exclude"], ["./docs", "docs/../x", "ドキュメント"]
        )
        self.assertEqual(result["excluded"], ["ドキュメント/z.md"])
        # `.`・`..` を含む要素は書き換えず、そのまま照合する（一致するパスは無い）
        self.assertIn("docs/a.md", result["targets"])


class TestFixedExcludes(_TempProject):
    FIXED = (
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
    )

    def setUp(self):
        super().setUp()
        _touch(self.root, "docs/a.md")
        for name in self.FIXED:
            _touch(self.root, f"{name}/x.md")
            _touch(self.root, f"docs/{name}/y.md")

    def test_fixed_names_match_design(self):
        self.assertEqual(ts.FIXED_EXCLUDED_DIR_NAMES, frozenset(self.FIXED))

    def test_all_skips_fixed_directories_at_any_depth(self):
        result = self.resolve(Raw(all=True))
        self.assertEqual(result["targets"], ["docs/a.md"])

    # 固定除外は --dirs 系の展開にも適用する（expand_dirs.py:131）
    def test_fixed_excludes_apply_to_dirs_at_any_depth(self):
        result = self.resolve(Raw(key="k", dirs=["docs"]))
        self.assertEqual(result["targets"], ["docs/a.md"])
        result = self.resolve(
            Raw(key="k", dirs=["node_modules", ".temp", "docs/build"])
        )
        self.assertEqual(result["targets"], [])
        self.assertEqual(result["rejected_dirs"], [])

    def test_fixed_excludes_apply_to_pattern_expansion(self):
        for pattern in ("*", "docs/*", "**/x.md", "build/*.md"):
            with self.subTest(pattern=pattern):
                result = self.resolve(Raw(key="k", dirs=[pattern]))
                self.assertTrue(
                    all(t == "docs/a.md" for t in result["targets"]), result["targets"]
                )

    def test_fixed_excludes_do_not_apply_to_paths(self):
        result = self.resolve(Raw(key="k", paths=["build/x.md", "docs/.git/y.md"]))
        self.assertEqual(result["targets"], ["build/x.md", "docs/.git/y.md"])


class TestProjectBoundary(_TempProject):
    def setUp(self):
        super().setUp()
        _touch(self.root, "docs/a.md")

    # `--dirs /` は末尾の `/` を除いてからルート全体として扱う（expand_dirs.py:76-78）
    def test_dirs_slash_is_project_root(self):
        _touch(self.root, "top.md")
        result = self.resolve(Raw(key="k", dirs=["/"]))
        self.assertEqual(result["target_spec"]["dirs"], ["."])
        self.assertEqual(result["targets"], ["docs/a.md", "top.md"])
        self.assertEqual(result["rejected_dirs"], [])

    # 絶対パス・ルートの外へ出るパスも除いて続行する（toc_utils.py:257-269、expand_dirs.py:76-87,110-117）
    def test_absolute_and_parent_paths_are_excluded_and_reported(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        _touch(Path(outside.name), "z.md")
        abs_file = str(Path(outside.name) / "z.md")
        result = self.resolve(
            Raw(
                key="k",
                dirs=["docs", outside.name, "../x", "docs/../../x", "../*"],
                paths=[abs_file, "../z.md", "docs/../../z.md"],
            )
        )
        self.assertEqual(result["targets"], ["docs/a.md"])
        rejected_dirs = {r["dir"]: r["reason"] for r in result["rejected_dirs"]}
        self.assertEqual(
            set(rejected_dirs), {outside.name, "../x", "docs/../../x", "../*"}
        )
        self.assertIn("絶対パス", rejected_dirs[outside.name])
        self.assertIn("外", rejected_dirs["../x"])
        self.assertIn("'..'", rejected_dirs["../*"])
        rejected_paths = {r["path"]: r["reason"] for r in result["rejected_paths"]}
        self.assertEqual(set(rejected_paths), {abs_file, "../z.md", "docs/../../z.md"})
        self.assertIn("絶対パス", rejected_paths[abs_file])
        self.assertIn("外", rejected_paths["../z.md"])

    def test_rejected_entries_are_kept_in_spec_and_reported_again(self):
        result = self.resolve(Raw(key="k", dirs=["../x"], paths=["../z.md"]))
        self.assertEqual(result["target_spec"]["dirs"], ["../x"])
        self.assertEqual(result["target_spec"]["paths"], ["../z.md"])
        expansion = ts.expand_target_spec(result["target_spec"], self.root)
        self.assertEqual(expansion.rejected_dirs, result["rejected_dirs"])
        self.assertEqual(expansion.rejected_paths, result["rejected_paths"])

    # パスの正規化（toc_utils.py:26-35,257-269、expand_dirs.py:76,110）
    def test_dot_and_inner_parent_segments_are_resolved(self):
        result = self.resolve(
            Raw(
                key="k",
                paths=["./docs/a.md", "docs/../docs/a.md"],
                dirs=["./docs/", "docs/sub/.."],
            )
        )
        self.assertEqual(result["target_spec"]["paths"], ["docs/a.md"])
        self.assertEqual(result["target_spec"]["dirs"], ["docs"])
        self.assertEqual(result["targets"], ["docs/a.md"])

    def test_paths_are_normalized_to_nfc(self):
        nfc = "プラン"
        nfd = unicodedata.normalize("NFD", nfc)
        self.assertNotEqual(nfc, nfd)
        _touch(self.root, f"{nfc}/a.md")
        result = self.resolve(Raw(key="k", paths=[f"{nfd}/a.md"], dirs=[nfd]))
        self.assertEqual(result["target_spec"]["paths"], [f"{nfc}/a.md"])
        self.assertEqual(result["target_spec"]["dirs"], [nfc])
        self.assertEqual(result["targets"], [f"{nfc}/a.md"])

    def test_pattern_backslashes_become_slashes(self):
        _touch(self.root, "specs/design/d.md")
        result = self.resolve(Raw(key="k", dirs=["specs\\*"]))
        self.assertEqual(result["target_spec"]["dirs"], ["specs/*"])
        self.assertEqual(result["targets"], ["specs/design/d.md"])

    # シンボリックリンク（toc_utils.py:879-946、prepare_toc.py:552-567）
    def _outside_with_markdown(self) -> Path:
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        path = Path(outside.name).resolve()
        _touch(path, "z.md")
        return path

    def test_symlink_inside_project_is_followed(self):
        _touch(self.root, "real/r.md")
        os.symlink(self.root / "real", self.root / "docs" / "link")
        result = self.resolve(Raw(key="k", dirs=["docs"]))
        self.assertEqual(result["targets"], ["docs/a.md", "docs/link/r.md"])
        self.assertEqual(result["warnings"], [])

    def test_same_file_reached_twice_is_counted_once(self):
        os.symlink(self.root / "docs", self.root / "docs" / "self")
        os.symlink(self.root / "docs" / "a.md", self.root / "docs" / "b.md")
        result = self.resolve(Raw(key="k", dirs=["docs"]))
        self.assertEqual(result["targets"], ["docs/a.md"])

    def test_symlink_loop_terminates(self):
        os.symlink(self.root, self.root / "docs" / "loop")
        result = self.resolve(Raw(all=True))
        self.assertEqual(result["targets"], ["docs/a.md"])

    # DES-005 §2 の 2: 実体がプロジェクトの外にあっても、たどったパスで扱う（DocAdvisor と異なる）
    def test_symlink_to_outside_is_treated_as_project_path(self):
        outside = self._outside_with_markdown()
        os.symlink(outside, self.root / "docs" / "ext")
        for raw in (
            Raw(all=True),
            Raw(key="k", dirs=["docs"]),
            Raw(key="k", dirs=["docs/ext"]),
            Raw(key="k", dirs=["docs/*"]),
            Raw(key="k", paths=["docs/a.md", "docs/ext/z.md"]),
        ):
            with self.subTest(raw=raw):
                result = self.resolve(raw)
                self.assertIn("docs/ext/z.md", result["targets"])
                self.assertEqual(result["warnings"], [])

    # D-020: 保存した指定から、確認なしに構築時と同じ一覧へ再展開できる
    def test_all_with_symlink_to_outside_reexpands_to_same_list(self):
        outside = self._outside_with_markdown()
        os.symlink(outside, self.root / "docs" / "ext")
        result = self.resolve(Raw(all=True))
        restored = json.loads(json.dumps(result["target_spec"]))
        expansion = ts.expand_target_spec(restored, self.root)
        self.assertEqual(expansion.targets, ["docs/a.md", "docs/ext/z.md"])
        self.assertEqual(expansion.targets, result["targets"])

    def test_broken_symlink_path_is_reported_missing(self):
        os.symlink(self.root / "nowhere.md", self.root / "docs" / "broken.md")
        result = self.resolve(Raw(key="k", paths=["docs/broken.md"]))
        self.assertEqual(
            result["rejected_paths"],
            [{"path": "docs/broken.md", "reason": "存在しない"}],
        )
        self.assertEqual(
            self.resolve(Raw(key="k", dirs=["docs"]))["targets"], ["docs/a.md"]
        )

    def test_unreadable_directory_is_reported_as_error(self):
        if os.geteuid() == 0:
            self.skipTest("root では権限で読み取りを止められない")
        locked = self.root / "docs" / "locked"
        _touch(self.root, "docs/locked/z.md")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        self.assertRejected(Raw(key="k", dirs=["docs"]), "読めない")

    # DES-006 §1・D-026: 存在しない以外の読み取りの失敗を「存在しない」と取り違えない
    def test_unreadable_parent_is_error_not_missing(self):
        if os.geteuid() == 0:
            self.skipTest("root では権限で読み取りを止められない")
        locked = self.root / "docs" / "locked"
        _touch(self.root, "docs/locked/sub/z.md")
        os.symlink(locked / "sub" / "z.md", self.root / "docs" / "x.md")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        for raw in (
            Raw(key="k", paths=["docs/locked/sub/z.md"]),
            Raw(key="k", dirs=["docs/locked/sub"]),
            Raw(key="k", dirs=["docs/locked/*"]),
            Raw(key="k", dirs=["docs/**"]),
            Raw(key="k", paths=["docs/x.md"]),
            Raw(all=True),
        ):
            with self.subTest(raw=raw):
                self.assertRejected(raw, "読めない")


# ---------------------------------------------------------------------------
# 警告（toc_utils.py:296-320、prepare_toc.py:72-73,581-586）
# ---------------------------------------------------------------------------


class TestWarnings(_TempProject):
    def test_case_only_difference_is_warned(self):
        _touch(self.root, "docs/a.md")
        if not (self.root / "docs" / "A.md").exists():
            _touch(self.root, "docs/A.md")  # 大文字小文字を区別するファイルシステム
        result = self.resolve(Raw(key="k", paths=["docs/a.md", "docs/A.md"]))
        self.assertEqual(result["targets"], ["docs/A.md", "docs/a.md"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("docs/A.md", result["warnings"][0])
        self.assertIn("docs/a.md", result["warnings"][0])

    def test_no_case_warning_without_collision(self):
        _touch(self.root, "docs/a.md")
        _touch(self.root, "docs/b.md")
        self.assertEqual(self.resolve(Raw(key="k", dirs=["docs"]))["warnings"], [])

    def test_all_over_threshold_is_warned(self):
        for i in range(ts.MAX_FILES_WARN_THRESHOLD):
            _touch(self.root, f"docs/{i:03d}.md")
        self.assertEqual(self.resolve(Raw(all=True))["warnings"], [])
        _touch(self.root, "docs/extra.md")
        result = self.resolve(Raw(all=True))
        self.assertEqual(len(result["targets"]), ts.MAX_FILES_WARN_THRESHOLD + 1)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn(str(ts.MAX_FILES_WARN_THRESHOLD + 1), result["warnings"][0])

    def test_threshold_applies_only_to_all(self):
        for i in range(ts.MAX_FILES_WARN_THRESHOLD + 1):
            _touch(self.root, f"docs/{i:03d}.md")
        self.assertEqual(self.resolve(Raw(key="k", dirs=["docs"]))["warnings"], [])


# ---------------------------------------------------------------------------
# プロジェクトルート（toc_utils.py:38-93）
# ---------------------------------------------------------------------------


class TestProjectRoot(_TempProject):
    def setUp(self):
        super().setUp()
        _touch(self.root, "docs/a.md")
        self._other = tempfile.TemporaryDirectory()
        self.addCleanup(self._other.cleanup)
        self.other = Path(self._other.name).resolve()
        _touch(self.other, "o.md")
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)

    def test_project_root_option_wins(self):
        os.chdir(self.other)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.other)}):
            code, data, _ = _run_cli(["--project-root", str(self.root)])
        self.assertEqual((code, data["targets"]), (0, ["docs/a.md"]))

    def test_claude_project_dir_is_used_without_option(self):
        os.chdir(self.other)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.root)}):
            code, data, _ = _run_cli([])
        self.assertEqual((code, data["targets"]), (0, ["docs/a.md"]))

    def test_cwd_is_used_without_option_and_env(self):
        os.chdir(self.root)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            code, data, _ = _run_cli([])
        self.assertEqual((code, data["targets"]), (0, ["docs/a.md"]))

    def test_invalid_claude_project_dir_falls_back_to_cwd(self):
        os.chdir(self.root)
        missing = str(self.other / "missing")
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": missing}):
            code, data, _ = _run_cli([])
        self.assertEqual((code, data["targets"]), (0, ["docs/a.md"]))


# ---------------------------------------------------------------------------
# D-020: 正規化した指定と再展開
# ---------------------------------------------------------------------------


class TestNormalizedSpec(_TempProject):
    def setUp(self):
        super().setUp()
        for rel in ("docs/a.md", "docs/b.md", "docs/draft/c.md", "specs/s.md"):
            _touch(self.root, rel)

    def test_json_and_plain_forms_normalize_to_one_form(self):
        _, spec_plain = ts.build_target_spec(
            Raw(
                key="k", dirs=["docs", "specs"], paths=["docs/a.md"], exclude=["draft"]
            ),
            self.root,
        )
        _, spec_json = ts.build_target_spec(
            Raw(
                key="k",
                dirs_json=['["specs"]'],
                dirs=["./docs/"],
                paths_json=['["docs/a.md", "docs/a.md"]'],
                exclude_json=['["draft"]'],
            ),
            self.root,
        )
        self.assertEqual(spec_plain, spec_json)
        self.assertEqual(
            spec_plain,
            {
                "all": False,
                "paths": ["docs/a.md"],
                "dirs": ["docs", "specs"],
                "exclude": ["draft"],
            },
        )

    def test_spec_is_json_serializable_and_reexpands_to_same_list(self):
        result = self.resolve(Raw(key="k", dirs=["docs"], exclude=["draft"]))
        restored = json.loads(json.dumps(result["target_spec"]))
        expansion = ts.expand_target_spec(restored, self.root)
        self.assertEqual(expansion.targets, result["targets"])
        self.assertEqual(expansion.excluded, result["excluded"])

    def test_paths_file_content_is_stored_as_paths(self):
        list_file = self.root / "l.json"
        list_file.write_text('["specs/s.md", "docs/a.md"]', encoding="utf-8")
        result = self.resolve(Raw(key="k", paths_file=str(list_file)))
        self.assertEqual(
            result["target_spec"],
            {
                "all": False,
                "paths": ["docs/a.md", "specs/s.md"],
                "dirs": [],
                "exclude": [],
            },
        )
        list_file.unlink()
        expansion = ts.expand_target_spec(result["target_spec"], self.root)
        self.assertEqual(expansion.targets, ["docs/a.md", "specs/s.md"])

    def test_reexpansion_follows_current_files(self):
        result = self.resolve(Raw(key="k", dirs=["docs"]))
        _touch(self.root, "docs/new.md")
        expansion = ts.expand_target_spec(result["target_spec"], self.root)
        self.assertEqual(expansion.targets, result["targets"] + ["docs/new.md"])

    def test_all_spec_reexpands(self):
        expansion = ts.expand_target_spec({"all": True}, self.root)
        self.assertEqual(
            expansion.targets,
            ["docs/a.md", "docs/b.md", "docs/draft/c.md", "specs/s.md"],
        )

    def test_malformed_saved_spec_is_rejected(self):
        for spec in (
            None,
            {},
            {"all": "yes"},
            {"all": True, "dirs": []},
            {"all": False, "paths": []},
            {"all": False, "paths": [1], "dirs": [], "exclude": []},
            {"all": False, "paths": [""], "dirs": [], "exclude": []},
        ):
            with self.subTest(spec=spec):
                with self.assertRaises(ts.TargetSpecError):
                    ts.expand_target_spec(spec, self.root)

    def test_output_is_deterministic(self):
        raw = Raw(key="k", dirs=["specs", "docs"], paths=["docs/b.md"])
        first = self.resolve(raw)
        self.assertEqual(first, self.resolve(raw))
        self.assertEqual(first["targets"], sorted(set(first["targets"])))


# ---------------------------------------------------------------------------
# D-041: embed-dlid と index-docs が同じ script で検証・展開する
# ---------------------------------------------------------------------------


_TARGET_FLAGS = (
    "--paths-json",
    "--paths-file",
    "--dirs-json",
    "--exclude-json",
)


class TestSharedByEmbedAndIndex(_TempProject):
    def setUp(self):
        super().setUp()
        _touch(self.root, "docs/a.md")

    def test_no_other_script_defines_target_flags(self):
        # 対象指定の引数を定義する実装は target_spec.py だけである（同じ役割を並べない）
        plugin_root = _REPO_ROOT / "plugins" / "doc-link"
        offenders = []
        for path in plugin_root.rglob("*.py"):
            if path.resolve() == _SCRIPT.resolve():
                continue
            text = path.read_text(encoding="utf-8")
            for flag in _TARGET_FLAGS:
                if re.search(r"add_argument\(\s*['\"]" + re.escape(flag), text):
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}: {flag}")
        self.assertEqual(offenders, [])

    def test_skills_call_this_script(self):
        skills_dir = _REPO_ROOT / "plugins" / "doc-link" / "skills"
        present = [
            s
            for s in ("embed-dlid", "index-docs")
            if (skills_dir / s / "SKILL.md").exists()
        ]
        if not present:
            self.skipTest("embed-dlid・index-docs の SKILL.md はまだ無い")
        for skill in present:
            with self.subTest(skill=skill):
                text = (skills_dir / skill / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("scripts/target_spec.py", text)

    def test_function_and_cli_reject_the_same_specs(self):
        # 両 SKILL が渡しうる同じ指定に対し、関数と CLI が同じ理由で拒否する
        cases = [
            (["--key", "all", "--dirs", "docs"], Raw(key="all", dirs=["docs"])),
            (["--key", "", "--dirs", "docs"], Raw(key="", dirs=["docs"])),
            (["--dirs", "docs"], Raw(dirs=["docs"])),
            (["--all", "--paths", "docs/a.md"], Raw(all=True, paths=["docs/a.md"])),
            (["--key", "k"], Raw(key="k")),
            (
                ["--key", "k", "--paths-file", "l.json", "--dirs", "docs"],
                Raw(key="k", paths_file="l.json", dirs=["docs"]),
            ),
            (
                ["--key", "k", "--paths-file", "l.json", "--exclude", "x"],
                Raw(key="k", paths_file="l.json", exclude=["x"]),
            ),
        ]
        for argv, raw in cases:
            with self.subTest(argv=argv):
                with self.assertRaises(ts.TargetSpecError) as cm:
                    ts.resolve_targets(raw, self.root, cwd=self.root)
                code, data, _ = _run_cli(["--project-root", str(self.root), *argv])
                self.assertEqual(code, 1)
                self.assertEqual(data, {"errors": cm.exception.errors})

    def test_function_and_cli_accept_the_same_spec(self):
        argv = [
            "--key",
            "rules",
            "--dirs-json",
            '["docs"]',
            "--exclude-json",
            '["draft"]',
        ]
        code, data, _ = _run_cli(["--project-root", str(self.root), *argv])
        self.assertEqual(code, 0)
        expected = ts.resolve_targets(
            Raw(key="rules", dirs_json=['["docs"]'], exclude_json=['["draft"]']),
            self.root,
            cwd=self.root,
        )
        self.assertEqual(data, expected)


# ---------------------------------------------------------------------------
# script_error_output_rules.md: 終了コードと標準出力
# ---------------------------------------------------------------------------


class TestCliOutputContract(_TempProject):
    def setUp(self):
        super().setUp()
        _touch(self.root, "docs/a.md")

    def test_success_exits_0_with_result_json(self):
        code, data, _ = _run_cli(
            [
                "--project-root",
                str(self.root),
                "--key",
                "rules",
                "--dirs",
                "docs",
                "gone",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            set(data),
            {
                "key",
                "target_spec",
                "targets",
                "excluded",
                "rejected_paths",
                "rejected_dirs",
                "warnings",
            },
        )
        self.assertEqual(data["targets"], ["docs/a.md"])
        self.assertEqual(data["rejected_dirs"][0]["dir"], "gone")

    def test_excluded_targets_still_exit_0(self):
        # 対象から除いたパスがあっても、検証と展開は完了している
        code, data, _ = _run_cli(
            ["--project-root", str(self.root), "--key", "k", "--paths", "docs/none.md"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(data["targets"], [])
        self.assertEqual(data["rejected_paths"][0]["path"], "docs/none.md")

    def test_rejection_exits_1_with_errors_array_of_strings(self):
        for argv in (
            ["--key", "all", "--dirs", "docs"],
            ["--all", "--exclude", "x"],
            ["--key", "k", "--paths-json", "[1]"],
        ):
            with self.subTest(argv=argv):
                code, data, _ = _run_cli(["--project-root", str(self.root), *argv])
                self.assertEqual(code, 1)
                self.assertEqual(set(data), {"errors"})
                self.assertIsInstance(data["errors"], list)
                self.assertGreaterEqual(len(data["errors"]), 1)
                for e in data["errors"]:
                    self.assertIsInstance(e, str)
                    self.assertNotEqual(e.strip(), "")

    def test_argparse_error_exits_2_without_stdout(self):
        code, data, text = _run_cli(["--project-root", str(self.root), "--unknown"])
        self.assertEqual(code, 2)
        self.assertIsNone(data)
        self.assertEqual(text, "")

    def test_subprocess_run_uses_same_contract(self):
        # 実際に script として起動したときも、終了コードと標準出力の JSON が契約に従う
        proc = subprocess.run(
            [
                sys.executable,
                str(_SCRIPT),
                "--project-root",
                str(self.root),
                "--key",
                "all",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("errors", json.loads(proc.stdout))
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--project-root", str(self.root)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["targets"], ["docs/a.md"])

    def test_docstring_declares_only_common_exit_codes(self):
        doc = ts.__doc__
        codes = re.findall(r"^\|\s*(\d+)\s*\|", doc, flags=re.MULTILINE)
        self.assertEqual(codes, ["0", "1", "2"])


if __name__ == "__main__":
    unittest.main()
