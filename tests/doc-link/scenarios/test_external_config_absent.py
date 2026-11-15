"""外部設定ファイルが無くても、キーと対象指定を直接与えれば構築・検査できること（受け入れ基準 24）。

`.doc_structure.yaml` を置かない一時のツリーへ、キーと対象指定を直接与える。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scenario_support import ID_A, S_A, ScenarioBase, doc_text  # noqa: E402

KEY = "k"
PATHS = ["docs/a.md"]


class ExternalConfigAbsentTest(ScenarioBase):
    def test_builds_and_checks_without_doc_structure_file(self):
        self.write("docs/a.md", doc_text(ID_A, "A", "body of a", S_A))
        self.assertFalse((self.root / ".doc_structure.yaml").exists())
        self.build_ok(KEY, PATHS)
        code, fresh = self.check_toc(KEY, PATHS)
        self.assertEqual((code, fresh["status"]), (0, "up_to_date"))
        self.assertFalse((self.root / ".doc_structure.yaml").exists())


if __name__ == "__main__":
    unittest.main()
