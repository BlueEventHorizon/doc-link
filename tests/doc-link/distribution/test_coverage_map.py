"""`coverage_map.md`（要件と検証の対応の記録）が、設計書・要件定義書・実装したテストと食い違っていないことを検査する。

`coverage_map.md` は開発用の文書であり、配布物には含めない。この検査は開発リポジトリの文書を読む。

- 設計書の「要件から設計・受け入れ検証への対応」の表の全行が、`coverage_map.md` に同じ要件の欄の見出し（`## `）で
  載っている。行ごとに、表が挙げる受け入れ条件（AC）がその見出しの下に `### AC-NNN` で載っている
- 要件定義書の AC がすべて、表のどこかの行に載っている（表の抜けを検出する）
- 対応の各項目（`- ` で始まる行）は、対応するテスト・手動確認の参照を持つか、「対応なし」と書かれている
- `<ファイル>::<クラス>::<テスト名>` の参照は、実在するテストを指す。手動確認の文書の参照は、`manual/` の
  実在するファイルを指す
- 「対応なし」の AC は `KNOWN_GAPS` と一致する。抜けが埋まったとき、または増えたときに、記録と
  この一覧を同時に直す（抜けは利用者へ報告する）
"""

import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from distribution_support import PROJECT_ROOT, TESTS_ROOT  # noqa: E402

COVERAGE_MAP = Path(__file__).resolve().parent / "coverage_map.md"
DESIGN = PROJECT_ROOT / "docs" / "specs" / "design" / "DES-009_verification.md"
REQUIREMENTS_DIR = PROJECT_ROOT / "docs" / "specs" / "requirement"
MANUAL_DIR = TESTS_ROOT / "manual"

NO_COUNTERPART = "対応なし"
# 対応なしと記録した AC。記録を直したときは、この一覧も同じ変更で直す
KNOWN_GAPS: set[str] = set()

TEST_REFERENCE = re.compile(r"`([\w./-]+\.py)::(\w+)::(\w+)`")
MANUAL_REFERENCE = re.compile(r"`([\w-]+_manual\.md)`")
AC_RUN = re.compile(r"AC-([\d／〜]+)")


def design_rows():
    """設計書の対応表の各行の（要件の欄, 受け入れ条件の ID の集合）。"""
    text = DESIGN.read_text(encoding="utf-8")
    start = text.index("## 2. 要件から設計・受け入れ検証への対応")
    end = text.index('<a id="sec-3">')
    rows = []
    for line in text[start:end].splitlines():
        if not re.match(r"^\| N?FR-", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append((cells[0], expand_acceptance_criteria(cells[2])))
    return rows


def expand_acceptance_criteria(cell):
    found = set()
    for run in AC_RUN.findall(cell):
        for part in run.split("／"):
            if not part:
                continue
            if "〜" in part:
                first, last = part.split("〜")
                found.update(f"AC-{n:03d}" for n in range(int(first), int(last) + 1))
            else:
                found.add(f"AC-{int(part):03d}")
    return found


def requirement_acceptance_criteria():
    found = set()
    for path in sorted(REQUIREMENTS_DIR.glob("REQ-*.md")):
        found.update(
            re.findall(r"^### (AC-\d+)\b", path.read_text(encoding="utf-8"), re.M)
        )
    return found


def parse_map():
    """`## ` ごとの `### ` の見出しと、`- ` の項目を返す。"""
    sections = {}
    current = None
    subsection = None
    for line in COVERAGE_MAP.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = {"acs": {}, "items": []}
            subsection = None
        elif line.startswith("### ") and current is not None:
            subsection = line[4:].strip()
            sections[current]["acs"][subsection] = []
        elif line.startswith("- ") and current is not None:
            sections[current]["items"].append(line)
            if subsection is not None:
                sections[current]["acs"][subsection].append(line)
    return sections


def test_methods():
    """テストのファイルごとの {クラス名: {メソッド名}}。"""
    found = {}
    for path in TESTS_ROOT.rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = {
            node.name: {
                child.name for child in node.body if isinstance(child, ast.FunctionDef)
            }
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        found[str(path.relative_to(TESTS_ROOT))] = classes
    return found


class CoverageMapTest(unittest.TestCase):
    def setUp(self):
        self.rows = design_rows()
        self.sections = parse_map()

    def test_design_table_is_read(self):
        self.assertGreaterEqual(len(self.rows), 12)

    def test_every_design_row_is_in_the_map_with_its_acceptance_criteria(self):
        for requirement, criteria in self.rows:
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.sections)
                self.assertLessEqual(
                    criteria,
                    set(self.sections[requirement]["acs"]),
                    "AC の見出しが無い",
                )

    def test_every_requirement_acceptance_criterion_is_in_the_design_table(self):
        in_table = set().union(*(criteria for _, criteria in self.rows))
        self.assertEqual(requirement_acceptance_criteria() - in_table, set())

    def test_every_requirement_acceptance_criterion_is_in_the_map(self):
        in_map = {ac for section in self.sections.values() for ac in section["acs"]}
        self.assertEqual(
            {ac for ac in requirement_acceptance_criteria() if ac not in in_map}, set()
        )

    def test_every_item_has_a_counterpart_or_says_there_is_none(self):
        for requirement, section in self.sections.items():
            for item in section["items"]:
                with self.subTest(requirement=requirement, item=item[:60]):
                    self.assertTrue(
                        TEST_REFERENCE.search(item)
                        or MANUAL_REFERENCE.search(item)
                        or NO_COUNTERPART in item
                    )

    def test_every_test_reference_points_at_an_existing_test(self):
        methods = test_methods()
        references = TEST_REFERENCE.findall(COVERAGE_MAP.read_text(encoding="utf-8"))
        self.assertGreater(len(references), 100)
        for path, class_name, test_name in references:
            with self.subTest(reference=f"{path}::{class_name}::{test_name}"):
                self.assertIn(path, methods)
                self.assertIn(class_name, methods[path])
                self.assertIn(test_name, methods[path][class_name])

    def test_every_manual_reference_points_at_an_existing_document(self):
        references = MANUAL_REFERENCE.findall(COVERAGE_MAP.read_text(encoding="utf-8"))
        self.assertTrue(references)
        for name in references:
            with self.subTest(manual=name):
                self.assertTrue((MANUAL_DIR / name).is_file())

    def test_acceptance_criteria_without_a_counterpart_match_the_known_gaps(self):
        gaps = {
            ac
            for section in self.sections.values()
            for ac, items in section["acs"].items()
            if any(NO_COUNTERPART in item for item in items)
        }
        self.assertEqual(gaps, KNOWN_GAPS)

    def test_map_is_not_a_distributed_document(self):
        self.assertNotIn(
            PROJECT_ROOT / "plugins", COVERAGE_MAP.parents, "配布物に含めない"
        )


if __name__ == "__main__":
    unittest.main()
