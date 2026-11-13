"""バージョン関連のファイルを、このブランチで編集していないことを git の差分で確かめる。

根拠は実装ガイドライン「バージョン関連ファイルは通常の作業で編集しない」である。更新は `/forge:update-version`
だけが行う。

- 基準: `main`（なければ `origin/main`）と HEAD の merge-base。取れない環境では skip し、理由を表示する
- CHANGELOG（ファイル名が `CHANGELOG` で始まるもの）: merge-base から HEAD までの差分、ステージ済み・未ステージの
  差分、未追跡のファイルのどれにも現れない
- `plugin.json` の `version`・`marketplace.json` の各プラグインの `version`:
  - merge-base に存在したファイルは、現在の値が merge-base の値と同じである
  - 新規に追加されたファイル（新規プラグインの追加）は、追加したコミットの初期値のままである。
    追加後のどのコミットでも、現在の作業ツリーでも、値が変わっていない
- 対象外: README のバージョン表・git タグ（タグはこのテストが git の差分で見られないため、ここでは確かめない）
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from distribution_support import PROJECT_ROOT, run_git  # noqa: E402

BASE_BRANCHES = ("main", "origin/main")
VERSION_FILE_NAMES = {"plugin.json", "marketplace.json"}
CHANGELOG_PREFIX = "CHANGELOG"


def merge_base():
    for branch in BASE_BRANCHES:
        output = run_git("merge-base", "HEAD", branch)
        if output and output.strip():
            return output.strip()
    return None


def versions_of(text):
    """plugin.json は `version`、marketplace.json は各プラグインの `version`（無ければ `None`）。"""
    data = json.loads(text)
    if "plugins" in data:
        return {plugin["name"]: plugin.get("version") for plugin in data["plugins"]}
    return {data["name"]: data.get("version")}


def files_in_state():
    output = run_git("ls-files", "--cached", "--others", "--exclude-standard")
    return [line for line in (output or "").splitlines() if line]


class VersionFilesUntouchedTest(unittest.TestCase):
    def setUp(self):
        self.base = merge_base()
        if self.base is None:
            self.skipTest(
                "main との merge-base を取れない環境では実行しない（"
                + "、".join(BASE_BRANCHES)
                + " のどれも解決できない）"
            )

    def changed_since_base(self):
        names = set()
        for arguments in (
            ("diff", "--name-only", f"{self.base}..HEAD"),
            ("diff", "--name-only", "HEAD"),
            ("ls-files", "--others", "--exclude-standard"),
        ):
            names.update((run_git(*arguments) or "").splitlines())
        return sorted(name for name in names if name)

    def test_changelog_is_not_edited(self):
        touched = [
            name
            for name in self.changed_since_base()
            if Path(name).name.upper().startswith(CHANGELOG_PREFIX)
        ]
        self.assertEqual(touched, [])

    def test_versions_are_unchanged_from_the_initial_values(self):
        version_files = [
            name for name in files_in_state() if Path(name).name in VERSION_FILE_NAMES
        ]
        self.assertTrue(version_files, "plugin.json・marketplace.json が見つからない")
        for name in version_files:
            with self.subTest(file=name):
                current = versions_of((PROJECT_ROOT / name).read_text(encoding="utf-8"))
                at_base = run_git("show", f"{self.base}:{name}")
                if at_base is not None:
                    self.assertEqual(versions_of(at_base), current)
                    continue
                self.assert_initial_value_kept(name, current)

    def assert_initial_value_kept(self, name, current):
        """merge-base に無いファイルは、追加したコミットの値を初期値とし、以後の値が同じであることを確かめる。"""
        commits = (
            run_git("log", "--reverse", "--format=%H", f"{self.base}..HEAD", "--", name)
            or ""
        ).split()
        if not commits:
            # コミットされていない新規ファイル。初期値と現在の値は同じ内容である
            return
        for commit in commits:
            content = run_git("show", f"{commit}:{name}")
            if content is None:
                continue  # 削除したコミット。値の比較対象が無い
            self.assertEqual(versions_of(content), current, f"{commit} の値と異なる")
        diff = run_git("diff", "HEAD", "--", name)
        self.assertEqual(diff, "", f"{name} に未コミットの変更がある")


if __name__ == "__main__":
    unittest.main()
