"""配布物の適合検査が共有する、走査範囲と読み取りの補助。

配布物とは、利用者の環境へ入る `plugins/doc-link/` 配下のファイルである。この検査は、全配布物を走査する
横断の検査だけを置く。個々の SKILL・Agent に固有の検査は、各 `tests/doc-link/<skill>/` が持つ。
"""

import re
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = PROJECT_ROOT / "plugins" / "doc-link"
TESTS_ROOT = PROJECT_ROOT / "tests" / "doc-link"

SKILLS_DIR = PLUGIN_ROOT / "skills"
AGENTS_DIR = PLUGIN_ROOT / "agents"
COMMON_SCRIPTS_DIR = PLUGIN_ROOT / "scripts"

# 配布物のうち、利用者の環境で AI が読む文書の置き場（script は含めない。誰が読むかで範囲を決める）。
# プラグイン共通と、スキル固有の docs / templates を数える。存在しない置き場は走査の対象が 0 件になるだけである
DOCUMENT_DIRECTORY_NAMES = ("docs", "templates")
# 走査する文書の拡張子（lock・.DS_Store・script は除く）
DOCUMENT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".html"}


def skill_md_files():
    return sorted(SKILLS_DIR.glob("*/SKILL.md"))


def agent_md_files():
    return sorted(AGENTS_DIR.glob("*.md"))


def distributed_documents():
    """利用者の環境で読まれる配布文書の一覧（SKILL.md・agents/*.md・docs・templates）。"""
    found = set(skill_md_files()) | set(agent_md_files())
    roots = [PLUGIN_ROOT]
    roots.extend(path for path in sorted(SKILLS_DIR.iterdir()) if path.is_dir())
    for root in roots:
        for name in DOCUMENT_DIRECTORY_NAMES:
            directory = root / name
            if not directory.is_dir():
                continue
            for path in directory.rglob("*"):
                if path.is_file() and path.suffix.lower() in DOCUMENT_SUFFIXES:
                    found.add(path)
    return sorted(found)


def python_files():
    """`plugins/doc-link/` 配下の全 `.py`（`__init__.py` を除く）。"""
    return sorted(
        path
        for path in PLUGIN_ROOT.rglob("*.py")
        if path.name != "__init__.py" and "__pycache__" not in path.parts
    )


def has_main_guard(source):
    return re.search(r"^if __name__ == [\"']__main__[\"']:", source, re.M) is not None


def entry_scripts():
    """入口 script（`__main__` で起動できる `.py`）。共通モジュールは含まない。"""
    return [
        path
        for path in python_files()
        if has_main_guard(path.read_text(encoding="utf-8"))
    ]


def split_frontmatter(text):
    """先頭の frontmatter の行の配列と、本文を返す。frontmatter が無ければ `AssertionError`。"""
    lines = text.split("\n")
    assert lines[0] == "---", "frontmatter で始まらない"
    end = lines.index("---", 1)
    return lines[1:end], "\n".join(lines[end + 1 :])


def frontmatter_fields(lines):
    fields = {}
    for line in lines:
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    return fields


def code_blocks(body):
    """フェンス付きコードブロックの（言語, 本文）の配列。"""
    return re.findall(r"```([^\n]*)\n(.*?)```", body, flags=re.DOTALL)


def relative(path):
    return str(Path(path).relative_to(PROJECT_ROOT))


def run_git(*arguments):
    """git を読み取りで実行する。失敗したときは `None`。"""
    try:
        completed = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout
