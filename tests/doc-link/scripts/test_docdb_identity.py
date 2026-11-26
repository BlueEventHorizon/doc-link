"""`docdb_identity`（[doc-db]での KEY と series）のテスト。"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import docdb_identity as identity  # noqa: E402
import state_store  # noqa: E402


def git_runner(common_dir):
    def run(arguments, cwd):
        assert arguments == ["rev-parse", "--git-common-dir"]
        return 0, f"{common_dir}\n"

    return run


def no_git(arguments, cwd):
    return 128, ""


class IdentityTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.main = self.base / "my-project"
        self.worktree = self.base / "wt" / "feature"
        for directory in (self.main / ".git", self.worktree):
            directory.mkdir(parents=True)

    def test_all_worktrees_of_a_project_share_the_key(self):
        runner = git_runner(self.main / ".git")
        a = identity.key_for(self.main, "specs", runner)
        b = identity.key_for(self.worktree, "specs", runner)
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("doc-link.my-project."))
        self.assertTrue(a.endswith(".specs"))

    def test_a_relative_common_dir_is_resolved_against_the_root(self):
        absolute = identity.key_for(self.main, "k", git_runner(self.main / ".git"))
        relative = identity.key_for(self.main, "k", git_runner(".git"))
        self.assertEqual(absolute, relative)

    def test_series_differs_per_worktree_and_is_stable(self):
        self.assertEqual(identity.series_for(self.main), identity.series_for(self.main))
        self.assertNotEqual(
            identity.series_for(self.main), identity.series_for(self.worktree)
        )
        self.assertTrue(identity.series_for(self.worktree).startswith("feature."))

    def test_projects_with_the_same_name_get_different_keys(self):
        other = self.base / "elsewhere" / "my-project"
        (other / ".git").mkdir(parents=True)
        a = identity.key_for(self.main, "k", git_runner(self.main / ".git"))
        b = identity.key_for(other, "k", git_runner(other / ".git"))
        self.assertNotEqual(a, b)

    def test_without_git_the_project_root_is_used(self):
        key = identity.key_for(self.main, "k", no_git)
        self.assertTrue(key.startswith("doc-link.my-project."))

    def test_unsafe_characters_in_the_project_name_are_replaced(self):
        odd = self.base / "プロジェクト名 x"
        odd.mkdir()
        key = identity.key_for(odd, "k", no_git)
        name = key.split(".")[1]
        self.assertRegex(name, r"^[A-Za-z0-9_-]+$")

    def test_toc_key_uses_the_state_file_name_encoding(self):
        key = identity.key_for(self.main, "a/b c", no_git)
        self.assertTrue(key.endswith("." + state_store.encode_name("a/b c")))

    def test_an_unencodable_toc_key_is_rejected(self):
        with self.assertRaises(state_store.StateStoreError):
            identity.key_for(self.main, "", no_git)


class RunGitTest(unittest.TestCase):
    def test_it_returns_none_when_git_cannot_run(self):
        from unittest import mock
        import subprocess

        with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(identity.run_git(["status"], Path(".")), (None, ""))

    def test_it_returns_the_output(self):
        with tempfile.TemporaryDirectory() as directory:
            code, output = identity.run_git(["--version"], Path(directory))
        self.assertEqual(code, 0)
        self.assertIn("git", output)


if __name__ == "__main__":
    unittest.main()
