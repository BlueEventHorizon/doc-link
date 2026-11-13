"""配布する全 `.py` が、テスト・Node.js 不使用・終了コードの宣言の規約に適合していることを検査する。

- 全 `.py` にテスト: `plugins/doc-link/` 配下の `.py`（`__init__.py` を除く）ごとに、プラグイン共通の
  `scripts/` なら `tests/doc-link/scripts/test_<module>.py`、スキル固有なら `tests/doc-link/<skill>/test_<module>.py`
  がある（実装ガイドライン「テスト」）
- Node.js 不使用: git が管理するファイル（追跡済みと、未追跡で ignore されていないもの）に、Node.js の
  ファイル・コマンドが無い。検索語と除外は下の定数である
- 終了コードの宣言: `3` 以上の終了コードを返しうる script は、module docstring に「終了コード」の表を持ち、
  表は `0` を含み、実装が返しうる `3` 以上の値と一致する。宣言の無い script は `3` 以上を返さない
  （`script_error_output_rules`）。返しうる値は AST で調べる（`EXIT_*` 定数の整数、`sys.exit`・
  `SystemExit` の整数リテラルと `EXIT_*` 定数、`main` の `return` の整数リテラルと `EXIT_*` 定数）。
  標準出力の契約（非 0 でエラー JSON の `errors` 配列）は、各入口 script のテストが確かめている
"""

import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from distribution_support import (  # noqa: E402
    COMMON_SCRIPTS_DIR,
    PLUGIN_ROOT,
    PROJECT_ROOT,
    SKILLS_DIR,
    TESTS_ROOT,
    entry_scripts,
    python_files,
    relative,
    run_git,
)

# Node.js のファイル。`.js` `.ts` とその派生、パッケージ管理のファイル、`node_modules`
NODE_FILE_NAMES = {
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    ".nvmrc",
    ".node-version",
}
NODE_SUFFIXES = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"}
# Node.js のコマンド（行の先頭、または `|`・`;`・`&&`・`$(`・`run:` の直後に現れるもの）
NODE_COMMAND = re.compile(
    r"(?:^|[|;&(`]|\brun:)\s*(?:npx|npm|pnpm|yarn|node|nodejs|bun|deno)\s", re.M
)
# コマンドの検索から除く種類のファイル。Markdown は説明の文章に語が現れるだけであり、dprint.jsonc の
# `npm:` は dprint のプラグインの指定（Node.js を実行しない）である
NODE_COMMAND_SCAN_SUFFIXES = {".sh", ".bash", ".zsh", ".yml", ".yaml", ".py"}

EXIT_CODE_TABLE_ROW = re.compile(r"^\|\s*(\d+)\s*\|", re.M)


def tracked_and_new_files():
    output = run_git("ls-files", "--cached", "--others", "--exclude-standard")
    if output is None:
        return None
    return [PROJECT_ROOT / line for line in output.splitlines() if line]


def expected_test_path(script):
    if script.parent == COMMON_SCRIPTS_DIR:
        return TESTS_ROOT / "scripts" / f"test_{script.stem}.py"
    skill = script.relative_to(SKILLS_DIR).parts[0]
    return TESTS_ROOT / skill / f"test_{script.stem}.py"


def module_constants(tree):
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
    return constants


def returned_exit_codes(tree):
    """script が返しうる終了コード（整数）の集合を、AST から求める。"""
    constants = module_constants(tree)

    def as_int(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name) and type(constants.get(node.id)) is int:
            if node.id.startswith("EXIT_"):
                return constants[node.id]
        return None

    codes = {
        value
        for name, value in constants.items()
        if name.startswith("EXIT_") and type(value) is int
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = node.func
            name = (
                callee.attr
                if isinstance(callee, ast.Attribute)
                else getattr(callee, "id", "")
            )
            if name in {"exit", "SystemExit"} and node.args:
                value = as_int(node.args[0])
                if value is not None:
                    codes.add(value)
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and child.value is not None:
                    value = as_int(child.value)
                    if value is not None:
                        codes.add(value)
    return codes


def declared_exit_codes(tree):
    """module docstring の「終了コード」の表が宣言する終了コードの集合。表が無ければ `None`。"""
    docstring = ast.get_docstring(tree) or ""
    if "終了コード" not in docstring:
        return None
    heading = re.search(r"^#+\s*終了コード\s*$", docstring, re.M)
    if heading is None:
        return None
    codes = {int(m) for m in EXIT_CODE_TABLE_ROW.findall(docstring[heading.end() :])}
    return codes or None


class EveryPythonFileHasTestTest(unittest.TestCase):
    def test_python_files_are_found(self):
        self.assertTrue(python_files())

    def test_every_python_file_has_its_test(self):
        for script in python_files():
            with self.subTest(script=relative(script)):
                test_path = expected_test_path(script)
                self.assertTrue(
                    test_path.is_file(), f"テストが無い: {relative(test_path)}"
                )

    def test_no_test_is_orphaned_in_scripts_directory(self):
        modules = {path.stem for path in COMMON_SCRIPTS_DIR.glob("*.py")}
        for test_path in sorted((TESTS_ROOT / "scripts").glob("test_*.py")):
            with self.subTest(test=relative(test_path)):
                self.assertIn(test_path.stem.removeprefix("test_"), modules)


class NoNodeJsTest(unittest.TestCase):
    def setUp(self):
        self.files = tracked_and_new_files()
        if self.files is None:
            self.skipTest("git でファイルの一覧を得られない環境では実行しない")

    def test_no_node_files(self):
        found = [
            relative(path)
            for path in self.files
            if path.name in NODE_FILE_NAMES
            or path.suffix.lower() in NODE_SUFFIXES
            or "node_modules" in path.parts
        ]
        self.assertEqual(found, [])

    def test_no_node_commands_in_scripts_and_workflows(self):
        found = []
        for path in self.files:
            if path.suffix.lower() not in NODE_COMMAND_SCAN_SUFFIXES:
                continue
            if not path.is_file():
                continue
            # この検査自身は、検索語の正規表現を持つので除く
            if path.resolve() == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in NODE_COMMAND.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                found.append(f"{relative(path)}:{line} {match.group(0).strip()!r}")
        self.assertEqual(found, [], "\n".join(found))

    def test_command_pattern_detects_node_commands(self):
        for text in ("npx foo", "run: npm ci", "x | node a.js", "a && yarn install"):
            with self.subTest(text=text):
                self.assertTrue(NODE_COMMAND.search(text))
        for text in ("uv run --locked foo.py", "python3 -m unittest"):
            with self.subTest(text=text):
                self.assertFalse(NODE_COMMAND.search(text))


class ExitCodeDeclarationTest(unittest.TestCase):
    def test_codes_of_three_or_more_are_declared_with_zero_included(self):
        for script in python_files():
            with self.subTest(script=relative(script)):
                tree = ast.parse(script.read_text(encoding="utf-8"))
                returned = returned_exit_codes(tree)
                declared = declared_exit_codes(tree)
                high = {code for code in returned if code >= 3}
                if not high:
                    continue
                self.assertIsNotNone(
                    declared,
                    "3 以上を返すのに、module docstring に終了コードの表が無い",
                )
                self.assertIn(0, declared, "表に 0 が無い")
                self.assertLessEqual(high, declared, "表に無い値を返しうる")

    def test_declared_codes_of_three_or_more_are_returned_by_the_script(self):
        for script in python_files():
            with self.subTest(script=relative(script)):
                tree = ast.parse(script.read_text(encoding="utf-8"))
                declared = declared_exit_codes(tree)
                if declared is None:
                    continue
                declared_high = {code for code in declared if code >= 3}
                returned_high = {c for c in returned_exit_codes(tree) if c >= 3}
                self.assertEqual(declared_high, returned_high)

    def test_declared_tables_reserve_zero_one_and_two_for_entry_scripts(self):
        for script in entry_scripts():
            with self.subTest(script=relative(script)):
                tree = ast.parse(script.read_text(encoding="utf-8"))
                declared = declared_exit_codes(tree)
                if declared is None:
                    # 宣言の無い入口 script は、本文書の共通の意味（0・1・2）だけで返す。
                    # 2 は argparse が返し、1 は script_output が返す。ここでは何も追加で確かめない
                    continue
                self.assertLessEqual({0, 1, 2}, declared)

    def test_entry_scripts_are_found(self):
        self.assertTrue(entry_scripts())
        self.assertTrue(
            all(path.is_relative_to(PLUGIN_ROOT) for path in entry_scripts())
        )


if __name__ == "__main__":
    unittest.main()
