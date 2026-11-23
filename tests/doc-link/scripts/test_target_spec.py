import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "plugins" / "doc-link" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import target_spec  # noqa: E402
from target_spec import TargetSpecError  # noqa: E402

TEMP_BASE = PROJECT_ROOT / ".temp" / "doc-link"


class TreeTestCase(unittest.TestCase):
    """プロジェクト内の .temp/doc-link/ 以下に fixture のディレクトリ構成を作る。"""

    def setUp(self):
        TEMP_BASE.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(dir=TEMP_BASE, prefix="target_spec_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def make(self, *relative_paths):
        for relative in relative_paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# t\n", encoding="utf-8")

    def parse(self, **kwargs):
        return target_spec.parse_target_arguments(root=self.root, **kwargs)

    def files(self, **kwargs):
        return target_spec.expand(self.parse(**kwargs), self.root)


class CombinationTest(TreeTestCase):
    def assertRejected(self, **kwargs):
        with self.assertRaises(TargetSpecError) as context:
            self.parse(**kwargs)
        self.assertTrue(context.exception.errors)

    def test_no_arguments_is_all_mode(self):
        self.assertEqual(self.parse().mode, target_spec.MODE_ALL)

    def test_all_flag_alone_is_all_mode(self):
        self.assertEqual(self.parse(all_targets=True).mode, target_spec.MODE_ALL)

    def test_paths_and_paths_json_are_concatenated(self):
        spec = self.parse(key="k", paths=["a.md"], paths_json='["b.md"]')
        self.assertEqual(spec.paths, ("a.md", "b.md"))

    def test_dirs_and_dirs_json_are_concatenated(self):
        spec = self.parse(key="k", dirs=["a"], dirs_json='["b"]')
        self.assertEqual(spec.dirs, ("a", "b"))

    def test_exclude_and_exclude_json_are_concatenated(self):
        spec = self.parse(key="k", paths=["a.md"], exclude=["x"], exclude_json='["y"]')
        self.assertEqual(spec.exclude, ("x", "y"))

    def test_paths_dirs_exclude_can_be_combined(self):
        spec = self.parse(key="k", paths=["a.md"], dirs=["d"], exclude=["e"])
        self.assertEqual(spec.mode, target_spec.MODE_TARGETS)
        self.assertEqual(spec.key, "k")

    def test_target_spec_without_key_is_rejected(self):
        for name, value in [
            ("paths", ["a.md"]),
            ("paths_json", "[]"),
            ("paths_file", "x.json"),
            ("dirs", ["d"]),
            ("dirs_json", "[]"),
            ("exclude", ["e"]),
            ("exclude_json", "[]"),
        ]:
            with self.subTest(name=name):
                self.assertRejected(**{name: value})

    def test_key_all_is_rejected(self):
        self.assertRejected(key="all", paths=["a.md"])

    def test_empty_key_is_rejected(self):
        self.assertRejected(key="", paths=["a.md"])

    def test_all_with_target_spec_is_rejected(self):
        self.assertRejected(all_targets=True, paths=["a.md"])
        self.assertRejected(all_targets=True, dirs=["d"])
        self.assertRejected(all_targets=True, exclude=["e"])

    def test_all_with_key_is_rejected(self):
        self.assertRejected(all_targets=True, key="k", paths=["a.md"])

    def test_key_without_target_spec_is_rejected(self):
        self.assertRejected(key="k")

    def test_key_with_only_exclude_is_rejected(self):
        self.assertRejected(key="k", exclude=["e"])

    def test_key_with_empty_target_lists_is_rejected(self):
        self.assertRejected(key="k", paths_json="[]")

    def test_paths_file_alone_is_accepted(self):
        listing = self.root / "list.json"
        listing.write_text(json.dumps(["a.md", "./b/../c.md"]), encoding="utf-8")
        spec = self.parse(key="k", paths_file=str(listing))
        self.assertEqual(spec.paths, ("a.md", "c.md"))

    def test_paths_file_with_other_spec_is_rejected(self):
        listing = self.root / "list.json"
        listing.write_text("[]", encoding="utf-8")
        for other in ({"paths": ["a.md"]}, {"dirs": ["d"]}, {"exclude": ["e"]}):
            with self.subTest(other=other):
                self.assertRejected(key="k", paths_file=str(listing), **other)

    def test_invalid_json_is_rejected(self):
        self.assertRejected(key="k", paths_json="not json")
        self.assertRejected(key="k", paths_json='{"a": 1}')
        self.assertRejected(key="k", paths_json="[1]")

    def test_missing_paths_file_is_rejected(self):
        self.assertRejected(key="k", paths_file=str(self.root / "nothing.json"))

    def test_all_violations_are_reported_together(self):
        with self.assertRaises(TargetSpecError) as context:
            self.parse(key="all", all_targets=True)
        self.assertGreaterEqual(len(context.exception.errors), 2)


class NormalizationTest(TreeTestCase):
    def test_dot_slash_and_inner_dotdot_are_resolved(self):
        spec = self.parse(key="k", paths=["./a/../b/./c.md"])
        self.assertEqual(spec.paths, ("b/c.md",))

    def test_path_is_normalized_to_nfc(self):
        decomposed = unicodedata.normalize("NFD", "がぎ.md")
        spec = self.parse(key="k", paths=[decomposed])
        self.assertEqual(spec.paths, (unicodedata.normalize("NFC", "がぎ.md"),))

    def test_path_outside_root_is_rejected(self):
        for path in ("../x.md", "a/../../x.md", "/etc/hosts.md"):
            with self.subTest(path=path):
                with self.assertRaises(TargetSpecError):
                    self.parse(key="k", paths=[path])

    def test_dirs_and_exclude_outside_root_are_rejected(self):
        with self.assertRaises(TargetSpecError):
            self.parse(key="k", dirs=["../x"])
        with self.assertRaises(TargetSpecError):
            self.parse(key="k", paths=["a.md"], exclude=["../x"])

    def test_absolute_path_inside_root_is_made_relative(self):
        spec = self.parse(key="k", paths=[str(self.root / "a" / "b.md")])
        self.assertEqual(spec.paths, ("a/b.md",))

    def test_empty_path_is_rejected(self):
        with self.assertRaises(TargetSpecError):
            self.parse(key="k", paths=[""])

    def test_is_markdown_is_case_insensitive_and_excludes_markdown_extension(self):
        self.assertTrue(target_spec.is_markdown("a.md"))
        self.assertTrue(target_spec.is_markdown("a.MD"))
        self.assertTrue(target_spec.is_markdown("a.Md"))
        self.assertFalse(target_spec.is_markdown("a.markdown"))
        self.assertFalse(target_spec.is_markdown("a.txt"))
        self.assertFalse(target_spec.is_markdown("md"))


class FixedExclusionTest(TreeTestCase):
    def setUp(self):
        super().setUp()
        self.make(
            "a.md",
            "docs/b.md",
            "docs/node_modules/x.md",
            "docs/sub/.temp/y.md",
            ".git/g.md",
            ".claude/c.md",
            ".codex/c.md",
            ".temp/t.md",
            "vendor/v.md",
            "dist/d.md",
            "build/b.md",
            "target/t.md",
            "coverage/c.md",
            "__pycache__/p.md",
            ".venv/v.md",
            ".pytest_cache/p.md",
            ".mypy_cache/m.md",
            "docs/build.md",
        )

    def test_all_skips_fixed_excluded_directories(self):
        self.assertEqual(
            self.files().files,
            ["a.md", "docs/b.md", "docs/build.md"],
        )

    def test_dirs_skips_fixed_excluded_directories(self):
        result = self.files(key="k", dirs=["docs"])
        self.assertEqual(result.files, ["docs/b.md", "docs/build.md"])

    def test_dirs_pattern_skips_fixed_excluded_directories(self):
        result = self.files(key="k", dirs=["*"])
        self.assertEqual(result.files, ["a.md", "docs/b.md", "docs/build.md"])

    def test_dirs_on_fixed_excluded_directory_yields_nothing(self):
        self.assertEqual(self.files(key="k", dirs=["vendor"]).files, [])
        self.assertEqual(self.files(key="k", dirs=["docs/node_modules"]).files, [])

    def test_dirs_on_fixed_excluded_directory_is_reported(self):
        for entry in ("vendor", "docs/node_modules"):
            with self.subTest(entry=entry):
                result = self.files(key="k", dirs=[entry])
                self.assertEqual(
                    [p.to_dict() for p in result.problems],
                    [{"path": entry, "reason": "fixed_excluded"}],
                )

    def test_scan_excluded_start_scans_the_designated_fixed_excluded_directory(self):
        self.make("vendor/sub/s.md", "vendor/node_modules/n.md")
        spec = self.parse(key="k", dirs=["vendor"])
        result = target_spec.expand(spec, self.root, scan_excluded_start=True)
        self.assertEqual(result.files, ["vendor/sub/s.md", "vendor/v.md"])
        self.assertEqual(result.problems, [])

    def test_scan_excluded_start_works_below_a_fixed_excluded_ancestor(self):
        spec = self.parse(key="k", dirs=["docs/node_modules"])
        result = target_spec.expand(spec, self.root, scan_excluded_start=True)
        self.assertEqual(result.files, ["docs/node_modules/x.md"])

    def test_dirs_on_the_root_is_not_reported_as_fixed_excluded(self):
        self.assertEqual(self.files(key="k", dirs=["."]).problems, [])

    def test_directly_specified_files_are_not_excluded(self):
        paths = [".git/g.md", "docs/node_modules/x.md", ".temp/t.md", "vendor/v.md"]
        result = self.files(key="k", paths=paths)
        self.assertEqual(result.files, sorted(paths))
        self.assertEqual(result.problems, [])

    def test_paths_file_files_are_not_excluded(self):
        listing = self.root / "list.json"
        listing.write_text(json.dumps([".git/g.md"]), encoding="utf-8")
        result = self.files(key="k", paths_file=str(listing))
        self.assertEqual(result.files, [".git/g.md"])


class ExpansionTest(TreeTestCase):
    def setUp(self):
        super().setUp()
        self.make(
            "top.md",
            "docs/a.md",
            "docs/deep/b.md",
            "docs/deep/c.txt",
            "docs/Up.MD",
            "docs/old.markdown",
            "other/d.md",
            "other/draft/e.md",
            "skip/f.md",
            "skip/draft.md",
        )

    def test_dirs_collects_markdown_recursively(self):
        result = self.files(key="k", dirs=["docs"])
        self.assertEqual(result.files, ["docs/Up.MD", "docs/a.md", "docs/deep/b.md"])

    def test_dirs_root(self):
        result = self.files(key="k", dirs=["."])
        self.assertIn("top.md", result.files)
        self.assertIn("other/d.md", result.files)

    def test_dirs_pattern_matches_directories_and_files(self):
        result = self.files(key="k", dirs=["do*", "top.m?"])
        self.assertEqual(
            result.files,
            ["docs/Up.MD", "docs/a.md", "docs/deep/b.md", "top.md"],
        )

    def test_dirs_pattern_with_slash_matches_from_root(self):
        result = self.files(key="k", dirs=["docs/de*"])
        self.assertEqual(result.files, ["docs/deep/b.md"])

    def test_double_star_matches_zero_or_more_directories(self):
        self.make(
            "specs/design/a.md",
            "specs/x/design/b.md",
            "specs/x/y/design/c.md",
            "specs/x/other/d.md",
            "specs/e.md",
        )
        expected = [
            "specs/design/a.md",
            "specs/x/design/b.md",
            "specs/x/y/design/c.md",
        ]
        for pattern in ("specs/**/design/", "**/design", "specs/**/design/**"):
            with self.subTest(pattern=pattern):
                result = self.files(key="k", dirs=[pattern])
                self.assertEqual(result.files, expected)

    def test_double_star_in_exclude_matches_zero_or_more_directories(self):
        self.make(
            "specs/design/a.md",
            "specs/x/design/b.md",
            "specs/x/y/design/c.md",
            "specs/x/other/d.md",
            "specs/e.md",
        )
        result = self.files(key="k", dirs=["specs"], exclude=["specs/**/design"])
        self.assertEqual(result.files, ["specs/e.md", "specs/x/other/d.md"])
        result = self.files(key="k", dirs=["specs"], exclude=["specs/**/y"])
        self.assertEqual(
            result.files,
            [
                "specs/design/a.md",
                "specs/e.md",
                "specs/x/design/b.md",
                "specs/x/other/d.md",
            ],
        )

    def test_dirs_pattern_without_slash_matches_any_level(self):
        result = self.files(key="k", dirs=["draft*"])
        self.assertEqual(result.files, ["other/draft/e.md", "skip/draft.md"])

    def test_dirs_pattern_matching_non_markdown_file_adds_nothing(self):
        result = self.files(key="k", paths=["top.md"], dirs=["c.t*"])
        self.assertEqual(result.files, ["top.md"])

    def test_exclude_plain_name_matches_directory_at_any_level_not_filename(self):
        result = self.files(key="k", dirs=["other", "skip"], exclude=["draft"])
        self.assertEqual(result.files, ["other/d.md", "skip/draft.md", "skip/f.md"])

    def test_exclude_plain_name_does_not_match_filename(self):
        result = self.files(key="k", dirs=["skip"], exclude=["f.md"])
        self.assertEqual(result.files, ["skip/draft.md", "skip/f.md"])

    def test_exclude_with_slash_matches_path_exactly_or_descendants(self):
        result = self.files(key="k", dirs=["docs"], exclude=["docs/deep"])
        self.assertEqual(result.files, ["docs/Up.MD", "docs/a.md"])
        result = self.files(key="k", dirs=["docs"], exclude=["docs/a.md"])
        self.assertEqual(result.files, ["docs/Up.MD", "docs/deep/b.md"])

    def test_exclude_with_slash_does_not_match_partial_name(self):
        result = self.files(key="k", dirs=["docs"], exclude=["docs/de"])
        self.assertEqual(len(result.files), 3)

    def test_exclude_with_slash_is_not_a_name_match_at_other_levels(self):
        self.make("x/docs/deep/z.md")
        result = self.files(key="k", dirs=["docs", "x"], exclude=["docs/deep"])
        self.assertIn("x/docs/deep/z.md", result.files)
        self.assertNotIn("docs/deep/b.md", result.files)

    def test_exclude_pattern_without_slash_matches_directory_and_file_names(self):
        result = self.files(key="k", dirs=["docs", "other"], exclude=["dra*", "U?.MD"])
        self.assertEqual(result.files, ["docs/a.md", "docs/deep/b.md", "other/d.md"])

    def test_exclude_pattern_with_slash_matches_path_or_ancestor(self):
        result = self.files(key="k", dirs=["docs"], exclude=["docs/d*"])
        self.assertEqual(result.files, ["docs/Up.MD", "docs/a.md"])

    def test_exclude_applies_to_directly_specified_paths_and_reports_them(self):
        result = self.files(key="k", paths=["top.md", "docs/a.md"], exclude=["docs"])
        self.assertEqual(result.files, ["top.md"])
        self.assertEqual(
            [problem.to_dict() for problem in result.problems],
            [{"path": "docs/a.md", "reason": target_spec.PROBLEM_EXCLUDED}],
        )

    def test_missing_and_non_markdown_paths_are_reported_and_rest_continues(self):
        result = self.files(
            key="k",
            paths=[
                "top.md",
                "nothing.md",
                "docs/old.markdown",
                "docs/deep/c.txt",
                "docs",
            ],
        )
        self.assertEqual(result.files, ["top.md"])
        reported = {problem.path: problem.reason for problem in result.problems}
        self.assertEqual(
            reported,
            {
                "nothing.md": target_spec.PROBLEM_MISSING,
                "docs/old.markdown": target_spec.PROBLEM_NOT_MARKDOWN,
                "docs/deep/c.txt": target_spec.PROBLEM_NOT_MARKDOWN,
                "docs": target_spec.PROBLEM_NOT_MARKDOWN,
            },
        )

    def test_missing_directory_pattern_without_match_and_non_directory_are_reported(
        self,
    ):
        result = self.files(key="k", dirs=["absent", "zzz*", "top.md", "docs"])
        reported = {problem.path: problem.reason for problem in result.problems}
        self.assertEqual(
            reported,
            {
                "absent": target_spec.PROBLEM_MISSING,
                "zzz*": target_spec.PROBLEM_NO_MATCH,
                "top.md": target_spec.PROBLEM_NOT_DIRECTORY,
            },
        )
        self.assertEqual(len(result.files), 3)

    def test_uppercase_extension_is_markdown_in_every_specification_method(self):
        direct = self.files(key="k", paths=["docs/Up.MD"])
        walked = self.files(key="k", dirs=["docs"])
        pattern = self.files(key="k", dirs=["docs/U*"])
        for result in (direct, walked, pattern):
            self.assertIn("docs/Up.MD", result.files)

    def test_all_mode_lists_every_markdown(self):
        self.assertEqual(
            self.files().files,
            [
                "docs/Up.MD",
                "docs/a.md",
                "docs/deep/b.md",
                "other/d.md",
                "other/draft/e.md",
                "skip/draft.md",
                "skip/f.md",
                "top.md",
            ],
        )


class UnreadableDirectoryTest(TreeTestCase):
    """権限不足で読めないディレクトリは、黙って空として扱わず `unreadable` として報告する。"""

    def setUp(self):
        super().setUp()
        if os.geteuid() == 0:
            self.skipTest("root は権限で読めなくならない")
        self.make("docs/ok/a.md", "docs/locked/b.md", "docs/locked/deep/c.md")
        self.locked = self.root / "docs" / "locked"
        self.locked.chmod(0o000)
        self.addCleanup(self.locked.chmod, 0o755)

    def reasons(self, result):
        return [(p.path, p.reason) for p in result.problems]

    def test_all_mode_reports_the_unreadable_subdirectory(self):
        result = self.files()
        self.assertEqual(result.files, ["docs/ok/a.md"])
        self.assertEqual(
            self.reasons(result), [("docs/locked", target_spec.PROBLEM_UNREADABLE)]
        )

    def test_directory_entry_reports_the_unreadable_subdirectory(self):
        result = self.files(key="k", dirs=["docs"])
        self.assertEqual(result.files, ["docs/ok/a.md"])
        self.assertEqual(
            self.reasons(result), [("docs/locked", target_spec.PROBLEM_UNREADABLE)]
        )

    def test_directory_entry_that_is_itself_unreadable(self):
        result = self.files(key="k", dirs=["docs/locked"])
        self.assertEqual(result.files, [])
        self.assertEqual(
            self.reasons(result), [("docs/locked", target_spec.PROBLEM_UNREADABLE)]
        )

    def test_pattern_entry_reports_it_once(self):
        result = self.files(key="k", dirs=["docs/*"])
        self.assertEqual(
            [r for r in self.reasons(result) if r[1] == target_spec.PROBLEM_UNREADABLE],
            [("docs/locked", target_spec.PROBLEM_UNREADABLE)],
        )

    def test_readable_tree_has_no_unreadable_problem(self):
        self.locked.chmod(0o755)
        result = self.files()
        self.assertEqual(result.problems, [])
        self.assertEqual(
            result.files, ["docs/locked/b.md", "docs/locked/deep/c.md", "docs/ok/a.md"]
        )


class SymlinkTest(TreeTestCase):
    def setUp(self):
        super().setUp()
        self.make("real/a.md", "real/sub/b.md")
        outside = Path(tempfile.mkdtemp(dir=TEMP_BASE, prefix="target_spec_outside_"))
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        (outside / "ext.md").write_text("# e\n", encoding="utf-8")
        self.outside = outside

    def test_symlinked_directory_is_followed_and_same_entity_counted_once(self):
        (self.root / "link").symlink_to(self.root / "real", target_is_directory=True)
        result = self.files()
        self.assertEqual(result.files, ["link/a.md", "link/sub/b.md"])

    def test_symlink_pointing_outside_root_is_kept_with_in_project_path(self):
        (self.root / "ext_link").symlink_to(self.outside, target_is_directory=True)
        (self.root / "file_link.md").symlink_to(self.outside / "ext.md")
        self.assertEqual(
            self.files(key="k", dirs=["ext_link"]).files, ["ext_link/ext.md"]
        )
        self.assertEqual(
            self.files(key="k", paths=["file_link.md"]).files, ["file_link.md"]
        )
        both = self.files(key="k", paths=["file_link.md"], dirs=["ext_link"])
        self.assertEqual(both.files, ["ext_link/ext.md"])

    def test_symlink_cycle_terminates(self):
        (self.root / "real" / "loop").symlink_to(
            self.root / "real", target_is_directory=True
        )
        result = self.files()
        self.assertEqual(result.files, ["real/a.md", "real/sub/b.md"])

    def test_broken_symlink_is_reported_missing(self):
        (self.root / "broken.md").symlink_to(self.root / "nowhere.md")
        result = self.files(key="k", paths=["broken.md"])
        self.assertEqual(result.files, [])
        self.assertEqual(result.problems[0].reason, target_spec.PROBLEM_MISSING)


class WarningTest(TreeTestCase):
    def test_over_100_files_in_all_mode_warns(self):
        self.make(*[f"d/{index:03}.md" for index in range(101)])
        result = self.files()
        self.assertEqual(len(result.files), 101)
        self.assertTrue(any("100" in warning for warning in result.warnings))

    def test_100_files_in_all_mode_does_not_warn(self):
        self.make(*[f"d/{index:03}.md" for index in range(100)])
        self.assertEqual(self.files().warnings, [])

    def test_over_100_files_with_key_does_not_warn(self):
        self.make(*[f"d/{index:03}.md" for index in range(101)])
        self.assertEqual(self.files(key="k", dirs=["d"]).warnings, [])

    def test_case_only_differing_paths_warn(self):
        self.make("lower/a.md")
        spec = target_spec.TargetSpec(
            mode=target_spec.MODE_TARGETS,
            key="k",
            paths=("lower/a.md", "Lower/A.md"),
        )
        result = target_spec.expand(spec, self.root)
        self.assertTrue(any("大文字小文字" in warning for warning in result.warnings))


class PersistenceTest(TreeTestCase):
    def setUp(self):
        super().setUp()
        self.make("docs/a.md", "docs/b/c.md", "docs/b/skip/d.md", "e.md")

    def test_saved_spec_re_expands_to_same_list(self):
        spec = self.parse(
            key="k",
            paths=["./e.md", "docs/../e.md"],
            dirs=["docs", "do*"],
            exclude=["skip"],
        )
        before = target_spec.expand(spec, self.root).to_dict()
        saved = json.dumps(spec.to_dict(), ensure_ascii=False)
        restored = target_spec.TargetSpec.from_dict(json.loads(saved))
        self.assertEqual(restored, spec)
        self.assertEqual(target_spec.expand(restored, self.root).to_dict(), before)

    def test_same_spec_in_different_order_gives_same_saved_form(self):
        first = self.parse(key="k", paths=["e.md", "docs/a.md"], dirs=["x", "y"])
        second = self.parse(key="k", paths=["docs/a.md", "./e.md"], dirs=["y", "x"])
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_paths_file_content_is_stored_in_paths(self):
        listing = self.root / "list.json"
        listing.write_text(json.dumps(["e.md", "docs/a.md"]), encoding="utf-8")
        spec = self.parse(key="k", paths_file=str(listing))
        listing.unlink()
        self.assertEqual(
            target_spec.expand(spec, self.root).files, ["docs/a.md", "e.md"]
        )

    def test_all_mode_round_trip(self):
        spec = self.parse()
        restored = target_spec.TargetSpec.from_dict(spec.to_dict())
        self.assertEqual(restored, spec)

    def test_from_dict_rejects_unknown_mode(self):
        with self.assertRaises(TargetSpecError):
            target_spec.TargetSpec.from_dict({"mode": "weird"})


class ArgparseIntegrationTest(TreeTestCase):
    """`add_target_arguments` で登録した引数を `parse_namespace` で `TargetSpec` にする。"""

    def parse_command_line(self, *arguments):
        parser = argparse.ArgumentParser()
        target_spec.add_target_arguments(parser)
        return target_spec.parse_namespace(
            parser.parse_args(list(arguments)), self.root
        )

    def test_no_arguments_is_all_mode(self):
        self.assertEqual(self.parse_command_line().mode, target_spec.MODE_ALL)

    def test_all_flag_alone_is_all_mode(self):
        self.assertEqual(self.parse_command_line("--all").mode, target_spec.MODE_ALL)

    def test_repeated_options_are_extended_in_order(self):
        spec = self.parse_command_line(
            "--key", "k", "--paths", "a.md", "b.md", "--paths", "c.md"
        )
        self.assertEqual(spec.mode, target_spec.MODE_TARGETS)
        self.assertEqual(spec.key, "k")
        self.assertEqual(spec.paths, ("a.md", "b.md", "c.md"))

    def test_dirs_exclude_and_json_options_are_combined(self):
        spec = self.parse_command_line(
            "--key",
            "k",
            "--dirs",
            "docs",
            "--dirs-json",
            '["rules"]',
            "--exclude",
            "draft",
        )
        self.assertEqual(spec.dirs, ("docs", "rules"))
        self.assertEqual(spec.exclude, ("draft",))

    def test_key_without_target_spec_is_rejected(self):
        # 指定なし（None）と空は区別される。--key だけでは対象指定が無いので拒否する
        with self.assertRaises(TargetSpecError):
            self.parse_command_line("--key", "k")

    def test_target_spec_without_key_is_rejected(self):
        with self.assertRaises(TargetSpecError):
            self.parse_command_line("--paths", "a.md")

    def test_all_with_target_spec_is_rejected(self):
        with self.assertRaises(TargetSpecError):
            self.parse_command_line("--all", "--key", "k", "--paths", "a.md")

    def test_option_without_values_is_rejected_by_argparse(self):
        parser = argparse.ArgumentParser()
        target_spec.add_target_arguments(parser)
        with self.assertRaises(SystemExit) as context:
            with contextlib.redirect_stderr(io.StringIO()):
                parser.parse_args(["--paths"])
        self.assertEqual(context.exception.code, 2)


class TocKeyTest(unittest.TestCase):
    def test_targets_mode_uses_its_key(self):
        spec = target_spec.TargetSpec(
            mode=target_spec.MODE_TARGETS, key="specs", paths=("a.md",)
        )
        self.assertEqual(target_spec.toc_key_of(spec), "specs")

    def test_all_mode_uses_the_reserved_key(self):
        spec = target_spec.TargetSpec(mode=target_spec.MODE_ALL)
        self.assertEqual(target_spec.toc_key_of(spec), target_spec.RESERVED_KEY)


if __name__ == "__main__":
    unittest.main()
