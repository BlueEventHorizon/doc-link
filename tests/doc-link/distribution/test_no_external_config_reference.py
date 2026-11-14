"""配布物が外部設定ファイル `.doc_structure.yaml` を直接読まないことの検査（受け入れ基準 24）。

走査範囲は `plugins/doc-link/` 配下の全テキストファイル（script・SKILL.md・agents・docs を含む）である。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from distribution_support import PLUGIN_ROOT, relative  # noqa: E402

NEEDLES = ("doc_structure", ".doc_structure.yaml")
SUFFIXES = {".py", ".sh", ".md", ".json", ".yaml", ".yml", ".toml", ".txt"}


class NoExternalConfigReferenceTest(unittest.TestCase):
    def test_distributed_files_do_not_refer_to_doc_structure(self):
        files = [
            path
            for path in sorted(PLUGIN_ROOT.rglob("*"))
            if path.is_file()
            and path.suffix.lower() in SUFFIXES
            and "__pycache__" not in path.parts
        ]
        self.assertTrue(files, "走査の対象が 0 件")
        found = [
            (relative(path), needle)
            for path in files
            for needle in NEEDLES
            if needle in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
