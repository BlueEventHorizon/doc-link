"""配布物が、開発用の文書（仕様書・設計書・開発ルール）を参照していないことを機械的に検査する。

根拠は実装ガイドライン「配布物は開発用の文書を参照しない」である。

- 走査範囲: `distribution_support.distributed_documents()`。`plugins/doc-link/` 配下の SKILL.md・`agents/*.md`・
  プラグイン共通とスキル固有の `docs/`・`templates/`（存在するもの）。利用者の環境で AI が読むものである
- 対象外: script（`.py` / `.sh`）のコメントと docstring。ソースを開くのは実装を追う開発者だけであり、
  実在する仕様 ID を書いてよい（同ガイドライン）。lock ファイルも対象外である
- 検索語: 開発文書のパス（`docs/specs`・`docs/rules`）、仕様 ID（`REQ-`・`DES-`・`ADR-` の後に数字）、
  決定 ID（`D-数字`・`U-数字`）、要件 ID（`FR-`・`NFR-`・`AC-` の後に数字）、状態遷移表の行 ID
  （`P-`・`B-`・`E-` の後に 2 桁の数字）
- 許容するプレースホルダ: ID の体系を示す抽象例は許容する。許容はファイルと該当文字列の組で
  `PLACEHOLDER_ALLOWLIST` に明示する。現時点で許容する組は無い（該当はすべて違反として失敗する）
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from distribution_support import (  # noqa: E402
    agent_md_files,
    distributed_documents,
    relative,
    skill_md_files,
)

FORBIDDEN_PATTERNS = {
    "開発文書のパス": re.compile(r"docs/(?:specs|rules)"),
    "仕様 ID": re.compile(r"\b(?:REQ|DES|ADR)-\d+"),
    "決定 ID": re.compile(r"(?<![A-Za-z0-9])[DU]-\d+"),
    "要件 ID": re.compile(r"\b(?:FR|NFR|AC)-\d+"),
    "状態遷移の行 ID": re.compile(r"(?<![A-Za-z0-9])[PBE]-\d{2}\b"),
}

# (相対パス, 該当した文字列) の組。ID の体系を示すプレースホルダを許容するときだけ、ここへ足す
PLACEHOLDER_ALLOWLIST = frozenset()


class DistributionReferenceTest(unittest.TestCase):
    def test_scan_covers_every_skill_and_agent(self):
        documents = set(distributed_documents())
        self.assertTrue(skill_md_files(), "SKILL.md が見つからない")
        self.assertTrue(agent_md_files(), "agents/*.md が見つからない")
        for path in skill_md_files() + agent_md_files():
            with self.subTest(path=relative(path)):
                self.assertIn(path, documents)

    def test_scan_does_not_include_scripts(self):
        for path in distributed_documents():
            with self.subTest(path=relative(path)):
                self.assertNotIn(path.suffix, {".py", ".sh"})

    def test_distributed_documents_do_not_refer_to_development_documents(self):
        violations = []
        for path in distributed_documents():
            text = path.read_text(encoding="utf-8")
            for label, pattern in FORBIDDEN_PATTERNS.items():
                for match in pattern.finditer(text):
                    if (relative(path), match.group(0)) in PLACEHOLDER_ALLOWLIST:
                        continue
                    line = text.count("\n", 0, match.start()) + 1
                    violations.append(
                        f"{relative(path)}:{line} {label} {match.group(0)!r}"
                    )
        self.assertEqual(violations, [], "\n".join(violations))

    def test_patterns_detect_what_they_are_meant_to_detect(self):
        samples = {
            "開発文書のパス": ["docs/specs/foo", "docs/rules/bar.md"],
            "仕様 ID": ["REQ-001", "DES-028 §3.4.1", "ADR-0001"],
            "決定 ID": ["D-024", "（決定: U-020）"],
            "要件 ID": ["FR-006", "NFR-004", "AC-031"],
            "状態遷移の行 ID": ["P-01", "B-09", "E-07"],
        }
        for label, texts in samples.items():
            for text in texts:
                with self.subTest(label=label, text=text):
                    self.assertTrue(FORBIDDEN_PATTERNS[label].search(text))
        for label, text in (
            ("決定 ID", "ID-123 と UID-5"),
            ("仕様 ID", "DESIGN-1"),
            ("状態遷移の行 ID", "EXP-01"),
        ):
            with self.subTest(label=label, text=text):
                self.assertFalse(FORBIDDEN_PATTERNS[label].search(text))


if __name__ == "__main__":
    unittest.main()
