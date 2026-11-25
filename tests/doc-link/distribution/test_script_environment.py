"""配布する script の実行環境（PEP 723 とロック・uv での起動）と、一時ファイルの置き場を検査する。

- PEP 723 とロック: 入口 script（`__main__` で起動できる `.py`。`skills/<skill>/scripts/` と、
  プラグイン共通の `scripts/` の入口）すべてに、`# /// script` ブロック（`requires-python`・`dependencies`・
  `[tool.uv]` の `exclude-newer = "3 days"`）と、隣の `<script>.py.lock` がある。SKILL.md・Agent の実行コマンドは
  `--exclude-newer` を付けない（付け忘れで `--locked` が失敗するのを避けるため、メタデータだけに書く）。依存の版番号を手で書いていないことは、検査の対象外である
  （`uv add --bounds lower` の書き込みと手書きを、ファイルから区別できない）
- uv での起動: 全入口 script を `uv run --locked <script> --help` で起動し、
  終了コード 0 で動くことを確かめる。uv が無い環境では skip し、理由を表示する。`--help` だけに絞り、並列にしない。
  SKILL.md の実行コマンドの形は `test_skill_agent_conformance` が確かめる
- 一時ファイルの置き場: 配布物の `.py` が、システムの一時ディレクトリの既定（`tempfile` の `dir` の無い呼び出し、
  `gettempdir`、`/tmp`、`$TMPDIR`）を使わない。`tempfile` を使う呼び出しは `dir=` を明示し、そのモジュールが
  `.temp/doc-link/<skill>/` の置き場（`state_store.TEMP_ROOT`）を指す。置き場の実体が `.temp/doc-link/<skill>/`
  であることの実行による確認は `tests/doc-link/scripts/test_state_store.py`
  （`AtomicWriteTest.test_temp_file_is_inside_project_temp_dir`）が持つ。SKILL.md・Agent には、
  システムの一時ディレクトリを指す記述とシェルによる一時ファイルの書き出しが無い
"""

import ast
import re
import shutil
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from distribution_support import (  # noqa: E402
    COMMON_SCRIPTS_DIR,
    PLUGIN_ROOT,
    agent_md_files,
    entry_scripts,
    python_files,
    relative,
    skill_md_files,
)

PEP723_BLOCK = re.compile(r"^# /// script\n((?:#(?: .*)?\n)+?)# ///$", re.M)
TEMPFILE_FUNCTIONS = {
    "mkstemp",
    "mkdtemp",
    "NamedTemporaryFile",
    "TemporaryDirectory",
    "TemporaryFile",
    "SpooledTemporaryFile",
}
# システムの一時ディレクトリを指す語。Python の文字列定数と、SKILL.md・Agent の文章を調べる
SYSTEM_TEMP_PATTERN = re.compile(
    r"(?<![\w.])/tmp\b|/var/folders|\$\{?TMPDIR\b|\bmktemp\b|\bgettempdir\b"
)
# SKILL.md・Agent から、シェルで一時ファイルを書き出す記述（ヒアドキュメント・echo のリダイレクト）
SHELL_WRITE_PATTERN = re.compile(r"<<-?\s*['\"]?\w+|\becho\b[^\n]*>|\bcat\b[^\n]*>")
# スクリプトの標準入力へ内容を渡すヒアドキュメント。シェルがファイルを書かず、先頭が固定の `uv run --locked` の
# 呼び出しで、区切りを引用符で囲む形に限る。書き出しの検出から除く（実装ガイドラインの一時ファイルの節）
STDIN_HEREDOC_TO_SCRIPT = re.compile(
    r"^uv run --locked [^\n]*<<'\w+'[ \t]*$", re.MULTILINE
)


def pep723_metadata(source):
    match = PEP723_BLOCK.search(source)
    if match is None:
        return None
    lines = [
        line[2:] if line.startswith("# ") else ""
        for line in match.group(1).splitlines()
    ]
    return tomllib.loads("\n".join(lines))


class Pep723AndLockTest(unittest.TestCase):
    def test_entry_scripts_are_found(self):
        scripts = entry_scripts()
        self.assertGreaterEqual(len(scripts), 9)
        self.assertIn(COMMON_SCRIPTS_DIR / "env_check.py", scripts)

    def test_every_entry_script_has_pep723_metadata(self):
        for script in entry_scripts():
            with self.subTest(script=relative(script)):
                metadata = pep723_metadata(script.read_text(encoding="utf-8"))
                self.assertIsNotNone(metadata, "# /// script ブロックが無い")
                self.assertIsInstance(metadata.get("requires-python"), str)
                self.assertIsInstance(metadata.get("dependencies"), list)
                self.assertEqual(
                    metadata.get("tool", {}).get("uv", {}).get("exclude-newer"),
                    "3 days",
                )

    def test_skill_and_agent_commands_do_not_pass_exclude_newer(self):
        for path in [*skill_md_files(), *agent_md_files()]:
            with self.subTest(file=relative(path)):
                self.assertNotIn("--exclude-newer", path.read_text(encoding="utf-8"))

    def test_every_entry_script_has_its_lock_file(self):
        for script in entry_scripts():
            with self.subTest(script=relative(script)):
                lock = script.with_name(script.name + ".lock")
                self.assertTrue(lock.is_file(), f"ロックが無い: {relative(lock)}")
                self.assertGreater(lock.stat().st_size, 0)

    def test_no_orphaned_lock_file(self):
        scripts = set(entry_scripts())
        for lock in sorted(PLUGIN_ROOT.rglob("*.py.lock")):
            with self.subTest(lock=relative(lock)):
                self.assertIn(lock.with_suffix(""), scripts)


@unittest.skipUnless(shutil.which("uv"), "uv が使えない環境では実行しない")
class UvRunHelpTest(unittest.TestCase):
    def test_every_entry_script_runs_with_uv_run_locked(self):
        for script in entry_scripts():
            with self.subTest(script=relative(script)):
                completed = subprocess.run(
                    [
                        "uv",
                        "run",
                        "--locked",
                        str(script),
                        "--help",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("usage", completed.stdout.lower())


class TemporaryFileLocationTest(unittest.TestCase):
    def test_tempfile_calls_name_their_directory(self):
        calls = 0
        for script in python_files():
            tree = ast.parse(script.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                callee = node.func
                if not (
                    isinstance(callee, ast.Attribute)
                    and isinstance(callee.value, ast.Name)
                    and callee.value.id == "tempfile"
                ):
                    continue
                calls += 1
                with self.subTest(script=relative(script), line=node.lineno):
                    self.assertIn(callee.attr, TEMPFILE_FUNCTIONS)
                    self.assertIn("dir", {kw.arg for kw in node.keywords})
        self.assertGreater(calls, 0, "tempfile の呼び出しを 1 つも見つけられない")

    def test_modules_using_tempfile_point_at_the_project_temp_root(self):
        for script in python_files():
            source = script.read_text(encoding="utf-8")
            if "tempfile." not in source:
                continue
            with self.subTest(script=relative(script)):
                self.assertTrue(
                    "TEMP_ROOT" in source or ".temp" in source,
                    ".temp/doc-link/<skill>/ の置き場を指していない",
                )

    def test_temp_root_is_dot_temp_doc_link(self):
        tree = ast.parse(
            (COMMON_SCRIPTS_DIR / "state_store.py").read_text(encoding="utf-8")
        )
        values = [
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "TEMP_ROOT" for t in node.targets
            )
        ]
        self.assertEqual(values, [(".temp", "doc-link")])

    def test_python_scripts_do_not_use_the_system_temp_directory(self):
        for script in python_files():
            tree = ast.parse(script.read_text(encoding="utf-8"))
            docstrings = {
                id(node.body[0].value)
                for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
                and node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
            }
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                if id(node) in docstrings:
                    continue  # docstring と説明は、置き場を述べるだけである
                with self.subTest(script=relative(script), line=node.lineno):
                    self.assertIsNone(SYSTEM_TEMP_PATTERN.search(node.value))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in {
                    "gettempdir",
                    "tempdir",
                }:
                    self.fail(f"{relative(script)}:{node.lineno} {node.attr}")

    def test_skill_and_agent_documents_do_not_use_system_temp_or_shell_writes(self):
        for path in skill_md_files() + agent_md_files():
            text = path.read_text(encoding="utf-8")
            with self.subTest(document=relative(path)):
                self.assertIsNone(SYSTEM_TEMP_PATTERN.search(text))
                self.assertIsNone(
                    SHELL_WRITE_PATTERN.search(STDIN_HEREDOC_TO_SCRIPT.sub("", text))
                )

    def test_patterns_detect_what_they_are_meant_to_detect(self):
        for text in (
            "/tmp/x",
            "/var/folders/ab",
            "$TMPDIR/x",
            "mktemp -d",
            "gettempdir()",
        ):
            with self.subTest(text=text):
                self.assertTrue(SYSTEM_TEMP_PATTERN.search(text))
        for text in (".temp/doc-link/index-docs/", "a/tmp_dir", "x.tmp"):
            with self.subTest(text=text):
                self.assertFalse(SYSTEM_TEMP_PATTERN.search(text))
        for text in ("cat <<EOF", "echo hi > a.txt", "cat a > b"):
            with self.subTest(text=text):
                self.assertTrue(SHELL_WRITE_PATTERN.search(text))

    def test_stdin_heredoc_to_a_script_is_not_a_shell_write_but_the_rest_still_is(self):
        allowed = "uv run --locked \"x/worker_io.py\" submit SEARCH-1 <<'EOF'"
        self.assertIsNone(
            SHELL_WRITE_PATTERN.search(STDIN_HEREDOC_TO_SCRIPT.sub("", allowed))
        )
        for text in (
            'uv run --locked "x/worker_io.py" submit SEARCH-1 <<EOF',  # 区切りが引用符で囲まれていない
            "uv run --locked \"x\" submit SEARCH-1 <<'EOF' > out.json",  # 書き出し先がある
            "cat <<'EOF' > a.txt",
            "python3 x.py <<'EOF'",  # 先頭が固定の uv run の呼び出しではない
        ):
            with self.subTest(text=text):
                self.assertTrue(
                    SHELL_WRITE_PATTERN.search(STDIN_HEREDOC_TO_SCRIPT.sub("", text))
                )


if __name__ == "__main__":
    unittest.main()
