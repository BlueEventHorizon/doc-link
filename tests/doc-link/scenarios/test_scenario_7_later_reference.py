"""横断シナリオ 7（後からの参照）（DES-009 §3、受け入れ基準 4。要件 D-033・D-042）。

DLID 付与操作が全見出しに[セクション ID]を付けた文書の見出しへ、別の文書から、title にその[セクション ID]を
書いたリンクを新しく書く（テストが参照元の文書を書き換える）。参照先の文書へ書き込むことなく、そのリンクが
[正式な参照]として抽出される。DLID 付与操作は、title に[DLID]の無いリンクへも書き込まない。
AI の生成は固定値の差し込みで代替する。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scenario_support import (  # noqa: E402
    ScenarioBase,
    strip_dlids,
)

from content_hash import RECORD_LENGTH  # noqa: E402

KEY = "k"
PATHS = ["docs/target.md", "docs/source.md"]
TARGET_ORIGINAL = "# Target\n\nintro\n\n## Section One\n\nbody one\n"
SOURCE_ORIGINAL = "# Source\n\ntext\n"


class LaterReferenceScenarioTest(ScenarioBase):
    def setUp(self):
        super().setUp()
        self.write("docs/target.md", TARGET_ORIGINAL)
        self.write("docs/source.md", SOURCE_ORIGINAL)
        code, embedded = self.embed(KEY, PATHS)
        self.assertEqual(code, 0, embedded)
        self.target_after_embed = self.read("docs/target.md")
        self.target_doc_id = next(
            w["dlid"]
            for w in embedded["written"]
            if w["path"] == "docs/target.md" and w["kind"] == "document"
        )
        # 全見出しに[セクション ID]が付いている
        self.section_id = next(
            w["dlid"]
            for w in embedded["written"]
            if w["path"] == "docs/target.md"
            and w["kind"] == "section"
            and w["heading"].startswith("Section One")
        )
        self.assertEqual(
            len([w for w in embedded["written"] if w["kind"] == "section"]), 3
        )
        self.assertEqual(strip_dlids(self.target_after_embed), TARGET_ORIGINAL)

    def anchor(self):
        """見出しへ届くアンカーは、[セクション ID]を付けた見出しの文字列から決まる（resolve-dlid が返す）。"""
        section = self.resolve_after_build()
        return section["anchor"]

    def resolve_after_build(self):
        self.build_ok(KEY, PATHS)
        section = self.resolve_one(self.section_id)
        self.assertEqual(section["status"], "resolved", section)
        return section

    def write_reference(self, record=None):
        title = f"{record} {self.section_id}" if record else self.section_id
        text = (
            self.read("docs/source.md").rstrip("\n")
            + f'\n\nsee [the section][r]\n\n[r]: target.md#{self.anchor()} "{title}"\n'
        )
        self.write("docs/source.md", text)

    def test_scenario_7_new_reference_is_extracted_without_writing_the_target(self):
        target_before = self.target_after_embed
        self.write_reference()
        # 参照先の文書は、リンクを書いても、構築しても、書き換わらない
        self.assertEqual(self.read("docs/target.md"), target_before)
        result = self.build_ok(KEY, PATHS)
        self.assertEqual(self.read("docs/target.md"), target_before)
        # index-docs の参照検査: [正式な参照]として抽出され、フラグメントが解決して一致する
        self.assertEqual(result["reference_check"]["summary"], {"match": 1})
        self.assertEqual(result["reference_check"]["findings"], [])
        references = self.toc(KEY)["references"]
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["target_doc_id"], self.target_doc_id)
        self.assertEqual(references[0]["target_section_id"], self.section_id)
        self.assertEqual(references[0]["kind"], "section")
        self.assertEqual(references[0]["check"]["result"], "match")
        # check-links の結果: 一致として数えられ、検出事項に現れない
        code, links = self.check_links(KEY, PATHS)
        self.assertEqual(code, 0, links)
        self.assertEqual(links["findings"], [])
        self.assertEqual(links["summary"]["matched_references"], 1)
        self.assertEqual(self.read("docs/target.md"), target_before)

    def test_scenario_7_reference_with_a_record_is_a_formal_reference_too(self):
        self.write_reference(record="e" * RECORD_LENGTH)
        self.build_ok(KEY, PATHS)
        references = self.toc(KEY)["references"]
        self.assertEqual(
            [(r["target_section_id"], r["recorded_content_hash"]) for r in references],
            [(self.section_id, "e" * RECORD_LENGTH)],
        )

    def test_scenario_7_embedding_again_does_not_write_to_a_link_without_a_dlid(self):
        self.write_reference()
        bare_links = (
            "\n[plain](target.md) and [plain section](target.md#section-one)\n"
            '\n[d]: target.md "title without dlid"\n'
        )
        self.write(
            "docs/source.md",
            self.read("docs/source.md").rstrip("\n") + "\n" + bare_links,
        )
        documents_before = self.snapshot("docs")
        code, embedded = self.embed(KEY, PATHS)
        self.assertEqual(code, 0, embedded)
        # 付与するものは無く、リンク（title の無いもの・[DLID]の無いもの）には何も書き込まない
        self.assertEqual(embedded["written"], [])
        self.assertEqual(self.snapshot("docs"), documents_before)
        # title に[DLID]の無いリンクは、check-links が報告するだけである
        code, links = self.check_links(KEY, PATHS)
        self.assertEqual(code, 0, links)
        categories = sorted(
            (f["category"], f["kind"])
            for f in links["findings"]
            if f["category"] == "link_without_dlid"
        )
        self.assertEqual(
            categories,
            [
                ("link_without_dlid", "definition"),
                ("link_without_dlid", "inline"),
                ("link_without_dlid", "inline"),
            ],
        )
        self.assertEqual(self.snapshot("docs"), documents_before)

    def test_scenario_7_embedding_after_index_keeps_every_document_unchanged(self):
        self.write_reference()
        self.build_ok(KEY, PATHS)
        documents_before = self.snapshot("docs")
        state_before = self.state_snapshot()
        code, embedded = self.embed(KEY, PATHS)
        self.assertEqual(code, 0, embedded)
        self.assertEqual(embedded["written"], [])
        self.assertEqual(self.snapshot("docs"), documents_before)
        # DLID 付与操作は管理状態を書き換えない
        self.assertEqual(self.state_snapshot(), state_before)


if __name__ == "__main__":
    unittest.main()
