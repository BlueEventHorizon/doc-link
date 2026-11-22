import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import change_set  # noqa: E402
import state_store  # noqa: E402
from content_hash import RECORD_LENGTH, document_content_hash, section_content_hashes  # noqa: E402
from markdown_reader import read_document  # noqa: E402

KEY = "main"
ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
ID_C = "DLID-pqrstvwxyz01"
S1 = "DLID-00000000s001"
S2 = "DLID-00000000s002"
S3 = "DLID-00000000s003"
HASH_X = "a" * RECORD_LENGTH
HASH_Y = "b" * RECORD_LENGTH


def doc(doc_id, *lines):
    head = "" if doc_id is None else f"---\ndoc_link_id: {doc_id}\n---\n"
    return head + "\n".join(lines) + "\n"


class ChangeSetTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def commit(self, files, key=KEY):
        """現在の文書から[確定 ToC]と[文書情報]を、docstring の対応どおりに保存する。"""
        documents, sections, references = [], [], []
        for path in files:
            text = (self.root / path).read_text(encoding="utf-8")
            document = read_document(text)
            doc_id = document.frontmatter.doc_link_id
            documents.append(
                {"doc_link_id": doc_id, "applied_hash": document_content_hash(text)}
            )
            state_store.save_document_info(
                self.root,
                "test",
                {
                    "doc_link_id": doc_id,
                    "path": path,
                    "title": "t",
                    "purpose": "p",
                    "summary": [],
                    "tasks": [],
                    "keywords": [],
                    "content_hash": "h",
                },
            )
            position = 0
            hashes = section_content_hashes(text)
            for heading, value in zip(document.headings, hashes):
                if heading.section_id is None:
                    continue
                words = heading.text.split()
                title = heading.text.rstrip()
                title = title[: len(title) - len(words[-1])].strip()
                sections.append(
                    {
                        "doc_link_id": doc_id,
                        "section_id": heading.section_id,
                        "heading": title,
                        "position": position,
                        "content_hash": value,
                    }
                )
                position += 1
            for number, definition in enumerate(
                d for d in document.references if d.dlid is not None
            ):
                recorded = definition.path
                if definition.fragment is not None:
                    recorded += "#" + definition.fragment
                references.append(
                    {
                        "source_doc_id": doc_id,
                        "source_section_id": None,
                        "position": number,
                        "target_doc_id": definition.dlid,
                        "target_section_id": None,
                        "recorded_path": recorded,
                        "recorded_content_hash": None,
                        "kind": "doc",
                        "check": {
                            "scope": "s",
                            "checked_at": "t",
                            "result": "match",
                            "found_path": None,
                        },
                    }
                )
        state_store.save_confirmed_toc(
            self.root,
            "test",
            {
                "toc_key": key,
                "version": 1,
                "target_spec": {},
                "documents": documents,
                "sections": sections,
                "references": references,
                "reverse_references": [],
                "last_checks": [],
            },
        )

    def build(self, files, key=KEY):
        return change_set.build_change_set(self.root, key, files)

    def doc_change(self, result, doc_id):
        return next(d for d in result.documents if d.doc_link_id == doc_id)

    def section_kinds(self, result):
        return {s.section_id: s.kinds for s in result.sections}

    def snapshot(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }


class DocumentChangeTest(ChangeSetTestBase):
    def test_unchanged(self):
        self.write("a.md", doc(ID_A, f"# T {S1}", "", "text"))
        self.commit(["a.md"])
        result = self.build(["a.md"])
        self.assertFalse(result.first_build)
        change = self.doc_change(result, ID_A)
        self.assertTrue(change.unchanged)
        self.assertEqual(change.kinds, ())
        self.assertEqual(result.sections, ())
        self.assertEqual(
            [(d.doc_link_id, d.path) for d in result.confirmed_documents],
            [(ID_A, "a.md")],
        )

    def test_new_departed_path_content_and_reference_are_independent(self):
        ref = '[r]: ./{}.md "t DLID-00000000d001"'
        self.write("a.md", doc(ID_A, "# A", "", "text", "", ref.format("x")))
        self.write("b.md", doc(ID_B, "# B"))
        self.write("c.md", doc(ID_C, "# C"))
        self.commit(["a.md", "b.md", "c.md"])
        # a: 本文変更（参照も変える）、b: 移動、c: 対象離脱、d: 新規
        self.write("a.md", doc(ID_A, "# A", "", "changed", "", ref.format("y")))
        (self.root / "b.md").rename(self.root / "moved.md")
        self.write("d.md", doc("DLID-00000000d002", "# D"))
        result = self.build(["a.md", "moved.md", "d.md"])
        self.assertEqual(
            self.doc_change(result, ID_A).kinds,
            (change_set.CHANGE_CONTENT, change_set.CHANGE_REFERENCES),
        )
        self.assertEqual(self.doc_change(result, ID_B).kinds, (change_set.CHANGE_PATH,))
        self.assertEqual(self.doc_change(result, ID_B).old_path, "b.md")
        self.assertEqual(self.doc_change(result, ID_B).new_path, "moved.md")
        self.assertEqual(
            self.doc_change(result, ID_C).kinds, (change_set.CHANGE_DEPARTED,)
        )
        self.assertEqual(
            self.doc_change(result, "DLID-00000000d002").kinds, (change_set.CHANGE_NEW,)
        )

    def test_move_and_content_change_on_one_document(self):
        self.write("a.md", doc(ID_A, "# A", "", "text"))
        self.commit(["a.md"])
        (self.root / "a.md").unlink()
        self.write("sub/a.md", doc(ID_A, "# A", "", "changed"))
        result = self.build(["sub/a.md"])
        self.assertEqual(
            self.doc_change(result, ID_A).kinds,
            (change_set.CHANGE_PATH, change_set.CHANGE_CONTENT),
        )

    def test_reference_only_change(self):
        self.write("a.md", doc(ID_A, "# A", "", '[r]: ./x.md "t DLID-00000000d001"'))
        self.commit(["a.md"])
        self.write("a.md", doc(ID_A, "# A", "", '[r]: ./x.md#h "t DLID-00000000d001"'))
        result = self.build(["a.md"])
        # 定義の行は内容ハッシュに入らない。リンク先の変更は、参照の変更としてだけ現れる（D-039）
        self.assertEqual(
            self.doc_change(result, ID_A).kinds, (change_set.CHANGE_REFERENCES,)
        )
        self.assertEqual(result.sections, ())

    def test_added_definition_is_not_a_content_change(self):
        self.write("a.md", doc(ID_A, f"# A {S1}", "", "text", ""))
        self.commit(["a.md"])
        # [正式な参照]の定義を足す: 参照の変更だけ。セクションも変わらない（前の空行は元からある）
        self.write(
            "a.md",
            doc(ID_A, f"# A {S1}", "", "text", "", '[r]: ./x.md "DLID-00000000d001"'),
        )
        result = self.build(["a.md"])
        self.assertEqual(
            self.doc_change(result, ID_A).kinds, (change_set.CHANGE_REFERENCES,)
        )
        self.assertEqual(result.sections, ())
        self.commit(["a.md"])
        # [正式な参照]でない定義（外部 URL）を足す: 変更なし
        self.write(
            "a.md",
            doc(
                ID_A,
                f"# A {S1}",
                "",
                "text",
                "",
                '[r]: ./x.md "DLID-00000000d001"',
                "[u]: https://example.com/",
            ),
        )
        result = self.build(["a.md"])
        self.assertTrue(self.doc_change(result, ID_A).unchanged)
        self.assertEqual(result.sections, ())

    def test_record_word_only_change_is_not_a_change(self):
        ref = '[r]: ./x.md "t {} DLID-00000000d001"'
        self.write("a.md", doc(ID_A, f"# A {S1}", "", ref.format(HASH_X)))
        self.commit(["a.md"])
        # 記録語の書き換え
        self.write("a.md", doc(ID_A, f"# A {S1}", "", ref.format(HASH_Y)))
        result = self.build(["a.md"])
        self.assertTrue(self.doc_change(result, ID_A).unchanged)
        self.assertEqual(result.sections, ())
        # 記録を除いた書き方へ、記録を初めて書き加える場合
        self.write(
            "a.md",
            doc(ID_A, f"# A {S1}", "", '[r]: ./x.md "t DLID-00000000d001"'),
        )
        self.commit(["a.md"])
        self.write("a.md", doc(ID_A, f"# A {S1}", "", ref.format(HASH_X)))
        result = self.build(["a.md"])
        self.assertTrue(self.doc_change(result, ID_A).unchanged)
        self.assertEqual(result.sections, ())

    def test_retargeting_is_a_reference_change_without_content_change(self):
        # title の DLID は内容ハッシュに含まれない。参照先の付け替えは、参照記述の違いとして検出される。
        self.write(
            "a.md", doc(ID_A, f"# A {S1}", "", '[r]: ./x.md "t DLID-00000000d001"')
        )
        self.commit(["a.md"])
        self.write(
            "a.md", doc(ID_A, f"# A {S1}", "", '[r]: ./x.md "t DLID-00000000d002"')
        )
        result = self.build(["a.md"])
        self.assertEqual(
            self.doc_change(result, ID_A).kinds, (change_set.CHANGE_REFERENCES,)
        )
        self.assertEqual(result.sections, ())

    def test_first_title_is_a_reference_change_without_content_change(self):
        # title の無い定義は[正式な参照]ではない。title を書くと参照が現れるが、内容ハッシュは変わらない。
        self.write("a.md", doc(ID_A, f"# A {S1}", "", "[r]: ./x.md"))
        self.commit(["a.md"])
        self.write(
            "a.md", doc(ID_A, f"# A {S1}", "", '[r]: ./x.md "t DLID-00000000d001"')
        )
        result = self.build(["a.md"])
        self.assertEqual(
            self.doc_change(result, ID_A).kinds, (change_set.CHANGE_REFERENCES,)
        )
        self.assertEqual(result.sections, ())

    def test_reference_line_shift_is_not_reference_change(self):
        self.write("a.md", doc(ID_A, "# A", "", '[r]: ./x.md "t DLID-00000000d001"'))
        self.commit(["a.md"])
        self.write(
            "a.md",
            doc(ID_A, "# A", "", "text", "", '[r]: ./x.md "t DLID-00000000d001"'),
        )
        kinds = self.doc_change(self.build(["a.md"]), ID_A).kinds
        self.assertEqual(kinds, (change_set.CHANGE_CONTENT,))


class FirstBuildAndFailureTest(ChangeSetTestBase):
    def test_first_build_all_new(self):
        self.write("a.md", doc(ID_A, f"# A {S1}"))
        self.write("b.md", doc(ID_B, "# B"))
        result = self.build(["a.md", "b.md"])
        self.assertTrue(result.first_build)
        self.assertEqual(
            [d.kinds for d in result.documents],
            [(change_set.CHANGE_NEW,)] * 2,
        )
        self.assertEqual(self.section_kinds(result), {S1: (change_set.SECTION_ADDED,)})

    def test_corrupt_toc_is_not_first_build(self):
        self.write("a.md", doc(ID_A, "# A"))
        path = state_store.confirmed_toc_path(self.root, KEY)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"{broken")
        with self.assertRaises(change_set.ChangeFailure) as caught:
            self.build(["a.md"])
        self.assertEqual(caught.exception.kind, change_set.FAILURE_STATE_UNREADABLE)
        self.assertEqual(
            caught.exception.problems[0].state_kind, state_store.KIND_CORRUPT
        )

    def test_missing_document_info_fails(self):
        self.write("a.md", doc(ID_A, "# A"))
        self.commit(["a.md"])
        state_store.document_info_path(self.root, ID_A).unlink()
        with self.assertRaises(change_set.ChangeFailure) as caught:
            self.build(["a.md"])
        self.assertEqual(caught.exception.kind, change_set.FAILURE_STATE_UNREADABLE)
        self.assertEqual(
            caught.exception.problems[0].state_kind, state_store.KIND_MISSING
        )

    def test_unreadable_documents_stop_and_are_all_reported(self):
        self.write("a.md", doc(ID_A, "# A"))
        (self.root / "bad.md").write_bytes(b"\xff\xfe\x00bad")
        with self.assertRaises(change_set.ChangeFailure) as caught:
            self.build(["a.md", "gone.md", "bad.md"])
        self.assertEqual(caught.exception.kind, change_set.FAILURE_DOCUMENT_UNREADABLE)
        self.assertEqual(
            [p.path for p in caught.exception.problems], ["gone.md", "bad.md"]
        )

    def test_unreadable_document_is_not_unchanged(self):
        self.write("a.md", doc(ID_A, "# A"))
        self.commit(["a.md"])
        (self.root / "a.md").unlink()
        with self.assertRaises(change_set.ChangeFailure):
            self.build(["a.md"])


class ExclusionTest(ChangeSetTestBase):
    def test_missing_and_duplicate_ids_are_excluded_and_others_continue(self):
        self.write("a.md", doc(ID_A, f"# A {S1}"))
        self.write("noid.md", doc(None, "# N"))
        self.write("dup1.md", doc(ID_B, "# D1"))
        self.write("dup2.md", doc(ID_B, "# D2"))
        self.write("c.md", doc(ID_C, "# C"))
        result = self.build(["a.md", "noid.md", "dup1.md", "dup2.md", "c.md"])
        self.assertEqual(
            [(d.path, d.reason, d.doc_link_id) for d in result.excluded],
            [
                ("noid.md", change_set.REASON_MISSING, None),
                ("dup1.md", change_set.REASON_DUPLICATE, ID_B),
                ("dup2.md", change_set.REASON_DUPLICATE, ID_B),
            ],
        )
        self.assertEqual([d.path for d in result.confirmed_documents], ["a.md", "c.md"])
        self.assertEqual({d.doc_link_id for d in result.documents}, {ID_A, ID_C})

    def test_excluded_document_is_not_departed_and_its_sections_not_deleted(self):
        self.write("a.md", doc(ID_A, f"# A {S1}"))
        self.write("b.md", doc(ID_B, f"# B {S2}"))
        self.commit(["a.md", "b.md"])
        self.write("b2.md", doc(ID_B, "# B2"))
        result = self.build(["a.md", "b.md", "b2.md"])
        self.assertEqual({d.doc_link_id for d in result.documents}, {ID_A})
        self.assertEqual(result.sections, ())
        self.assertEqual({d.doc_link_id for d in result.excluded}, {ID_B})

    def test_section_id_duplicate_is_not_a_document_exclusion(self):
        self.write("a.md", doc(ID_A, f"# A {S1}", "", f"## B {S1}"))
        result = self.build(["a.md"])
        self.assertEqual(result.excluded, ())
        self.assertEqual([d.doc_link_id for d in result.confirmed_documents], [ID_A])


class SectionChangeTest(ChangeSetTestBase):
    def base(self):
        self.write(
            "a.md",
            doc(ID_A, f"# A {S1}", "", "one", "", f"## B {S2}", "", "two"),
        )
        self.write("b.md", doc(ID_B, f"# Other {S3}", "", "three"))
        self.commit(["a.md", "b.md"])

    def test_unchanged_sections_do_not_appear(self):
        self.base()
        self.assertEqual(self.build(["a.md", "b.md"]).sections, ())

    def test_added_and_deleted(self):
        self.base()
        self.write(
            "a.md",
            doc(ID_A, f"# A {S1}", "", "one", "", "## New DLID-00000000s004"),
        )
        result = self.build(["a.md", "b.md"])
        kinds = self.section_kinds(result)
        self.assertEqual(kinds["DLID-00000000s004"], (change_set.SECTION_ADDED,))
        self.assertEqual(kinds[S2], (change_set.SECTION_DELETED,))
        self.assertNotIn(S3, kinds)

    def test_body_change_only(self):
        self.base()
        self.write(
            "a.md",
            doc(ID_A, f"# A {S1}", "", "one", "", f"## B {S2}", "", "TWO"),
        )
        kinds = self.section_kinds(self.build(["a.md", "b.md"]))
        self.assertEqual(kinds[S2], (change_set.SECTION_BODY,))
        # S1 の範囲は文書の末尾まで（子の見出しを含む）なので、S1 も本文が変わる
        self.assertEqual(kinds[S1], (change_set.SECTION_BODY,))

    def test_heading_change_does_not_report_body_change(self):
        self.base()
        self.write(
            "a.md",
            doc(ID_A, f"# A {S1}", "", "one", "", f"## B renamed {S2}", "", "two"),
        )
        kinds = self.section_kinds(self.build(["a.md", "b.md"]))
        self.assertEqual(kinds[S2], (change_set.SECTION_HEADING,))

    def test_move_between_documents_with_body_change(self):
        self.base()
        self.write("a.md", doc(ID_A, f"# A {S1}", "", "one"))
        self.write(
            "b.md",
            doc(ID_B, f"# Other {S3}", "", "three", "", f"## B {S2}", "", "two!"),
        )
        result = self.build(["a.md", "b.md"])
        kinds = self.section_kinds(result)
        self.assertEqual(kinds[S2], (change_set.SECTION_MOVED, change_set.SECTION_BODY))
        change = next(s for s in result.sections if s.section_id == S2)
        self.assertEqual(change.old.doc_link_id, ID_A)
        self.assertEqual(change.new.doc_link_id, ID_B)

    def test_move_within_document_and_heading_change(self):
        self.base()
        self.write(
            "a.md",
            doc(ID_A, f"# A2 {S2}", "", "two", "", f"# A {S1}", "", "one"),
        )
        kinds = self.section_kinds(self.build(["a.md", "b.md"]))
        self.assertEqual(
            kinds[S2], (change_set.SECTION_MOVED, change_set.SECTION_HEADING)
        )
        self.assertEqual(kinds[S1], (change_set.SECTION_MOVED, change_set.SECTION_BODY))

    def test_sections_of_departed_document_are_deleted(self):
        self.base()
        result = self.build(["a.md"])
        self.assertEqual(
            self.section_kinds(result), {S3: (change_set.SECTION_DELETED,)}
        )

    def test_headings_without_section_id_are_not_sections(self):
        self.write("a.md", doc(ID_A, f"# A {S1}", "", "## no id", "", "x"))
        self.commit(["a.md"])
        self.write("a.md", doc(ID_A, f"# A {S1}", "", "## no id 2", "", "x"))
        result = self.build(["a.md"])
        self.assertEqual(self.section_kinds(result), {S1: (change_set.SECTION_BODY,)})

    def test_excluded_document_sections_are_not_added(self):
        self.write("noid.md", doc(None, f"# N {S1}"))
        result = self.build(["noid.md"])
        self.assertEqual(result.sections, ())


class NoWriteTest(ChangeSetTestBase):
    def test_build_does_not_change_documents_or_state(self):
        self.write("a.md", doc(ID_A, f"# A {S1}", "", "text"))
        self.write("noid.md", doc(None, "# N"))
        self.commit(["a.md"])
        self.write("a.md", doc(ID_A, f"# A {S1}", "", "changed"))
        before = self.snapshot()
        result = self.build(["a.md", "noid.md"])
        self.assertEqual(self.snapshot(), before)
        data = result.to_dict()
        self.assertEqual(data["documents"][0]["kinds"], ["content_changed"])
        self.assertEqual(data["sections"][0]["kinds"], ["body_changed"])
        self.assertEqual(data["excluded"][0]["reason"], "missing")


def _document(doc_id, kinds):
    return change_set.DocumentChange(
        doc_link_id=doc_id,
        kinds=tuple(kinds),
        old_path=None,
        new_path=None,
        old_hash=None,
        new_hash=None,
        old_references=None,
        new_references=None,
    )


def _section(section_id, kinds):
    return change_set.SectionChange(
        section_id=section_id, kinds=tuple(kinds), old=None, new=None
    )


class SummaryTest(unittest.TestCase):
    def summary(self, documents=(), sections=(), confirmed=(), first_build=False):
        return change_set.ChangeSet(
            confirmed_documents=tuple(
                change_set.ConfirmedDocument(doc_id, f"{doc_id}.md")
                for doc_id in confirmed
            ),
            excluded=(),
            documents=tuple(documents),
            sections=tuple(sections),
            first_build=first_build,
        ).summary()

    def test_empty_change_set_has_every_kind_with_zero(self):
        summary = self.summary()
        self.assertEqual(
            summary,
            {
                "first_build": False,
                "confirmed_documents": 0,
                "documents": {
                    "new": 0,
                    "content_changed": 0,
                    "references_changed": 0,
                    "path_changed": 0,
                    "departed": 0,
                    "unchanged": 0,
                },
                "sections": {
                    "added": 0,
                    "deleted": 0,
                    "moved": 0,
                    "heading_changed": 0,
                    "body_changed": 0,
                },
            },
        )

    def test_a_document_with_several_kinds_is_counted_in_each_kind(self):
        summary = self.summary(
            documents=[
                _document(ID_A, ["content_changed", "path_changed"]),
                _document(ID_B, []),
                _document(ID_C, ["departed"]),
            ],
            confirmed=[ID_A, ID_B],
        )
        self.assertEqual(summary["confirmed_documents"], 2)
        self.assertEqual(
            summary["documents"],
            {
                "new": 0,
                "content_changed": 1,
                "references_changed": 0,
                "path_changed": 1,
                "departed": 1,
                "unchanged": 1,
            },
        )

    def test_a_section_with_several_kinds_is_counted_in_each_kind(self):
        summary = self.summary(
            sections=[
                _section(S1, ["moved", "body_changed"]),
                _section(S2, ["added"]),
            ],
            first_build=True,
        )
        self.assertTrue(summary["first_build"])
        self.assertEqual(
            summary["sections"],
            {
                "added": 1,
                "deleted": 0,
                "moved": 1,
                "heading_changed": 0,
                "body_changed": 1,
            },
        )


def _change(doc_id, kinds, old_path, new_path):
    return change_set.DocumentChange(
        doc_link_id=doc_id,
        kinds=tuple(kinds),
        old_path=old_path,
        new_path=new_path,
        old_hash=None,
        new_hash=None,
        old_references=None,
        new_references=None,
    )


class WithFirstOldPathsTest(unittest.TestCase):
    """構築の途中で[文書情報]のパスが新しくなった移動を、変更集合へ合わせる。"""

    def apply(self, documents, first_old_paths):
        original = change_set.ChangeSet(
            confirmed_documents=(),
            excluded=(),
            documents=tuple(documents),
            sections=(),
            first_build=False,
        )
        return original.with_first_old_paths(first_old_paths).documents

    def test_a_recorded_move_is_added_before_the_other_kinds(self):
        (document,) = self.apply(
            [_change(ID_A, ["content_changed"], "b.md", "b.md")],
            {ID_A: "a.md"},
        )
        self.assertEqual(document.kinds, ("path_changed", "content_changed"))
        self.assertEqual(document.old_path, "a.md")
        self.assertEqual(document.new_path, "b.md")
        self.assertFalse(document.unchanged)

    def test_a_move_that_was_undone_is_removed(self):
        (document,) = self.apply(
            [_change(ID_A, ["path_changed", "content_changed"], "b.md", "a.md")],
            {ID_A: "a.md"},
        )
        self.assertEqual(document.kinds, ("content_changed",))
        self.assertEqual(document.old_path, "a.md")

    def test_a_document_that_is_only_moved_and_undone_is_unchanged(self):
        (document,) = self.apply(
            [_change(ID_A, ["path_changed"], "b.md", "a.md")], {ID_A: "a.md"}
        )
        self.assertEqual(document.kinds, ())
        self.assertTrue(document.unchanged)

    def test_documents_without_a_record_keep_their_own_comparison(self):
        moved = _change(ID_A, ["path_changed"], "a.md", "b.md")
        same = _change(ID_B, [], "c.md", "c.md")
        documents = self.apply([moved, same], {})
        self.assertEqual(documents, (moved, same))

    def test_new_and_departed_documents_are_not_changed(self):
        new = _change(ID_A, ["new"], None, "a.md")
        departed = _change(ID_B, ["departed"], "b.md", None)
        documents = self.apply([new, departed], {ID_A: "x.md", ID_B: "y.md"})
        self.assertEqual(documents, (new, departed))


if __name__ == "__main__":
    unittest.main()
