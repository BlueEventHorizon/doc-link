import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import change_set  # noqa: E402
import state_store  # noqa: E402
import update_plan  # noqa: E402
from content_hash import document_content_hash  # noqa: E402

ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
ID_C = "DLID-pqrstvwxyz01"
S1 = "DLID-00000000s001"


def doc(doc_id, *lines):
    head = "" if doc_id is None else f"---\ndoc_link_id: {doc_id}\n---\n"
    return head + "\n".join(lines) + "\n"


def generated(title="Generated title", purpose="purpose text"):
    return {
        "title": title,
        "purpose": purpose,
        "summary": [f"s{i}" for i in range(5)],
        "applicable_tasks": ["task"],
        "keywords": [f"k{i}" for i in range(5)],
    }


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def save_info(self, doc_id, path, content_hash, **overrides):
        info = {
            "doc_link_id": doc_id,
            "path": path,
            "title": "old title",
            "purpose": "old purpose",
            "summary": ["a", "b", "c", "d", "e"],
            "tasks": ["t"],
            "keywords": ["a", "b", "c", "d", "e"],
            "content_hash": content_hash,
        }
        info.update(overrides)
        state_store.save_document_info(self.root, "test", info)
        return info

    def save_toc(self, key, doc_ids_hashes):
        state_store.save_confirmed_toc(
            self.root,
            "test",
            {
                "toc_key": key,
                "version": 1,
                "target_spec": {},
                "documents": [
                    {"doc_link_id": i, "applied_hash": h} for i, h in doc_ids_hashes
                ],
                "sections": [],
                "references": [],
                "reverse_references": [],
                "last_checks": [],
            },
        )

    def plan(self, key, files):
        cs = change_set.build_change_set(self.root, key, files)
        return update_plan.build_update_plan(self.root, cs)

    def by_id(self, plan):
        return {d.doc_link_id: d for d in plan.documents}


class PlanTest(Base):
    def test_path_only_change_updates_path_without_generation(self):
        text = doc(ID_A, "# Title", "body")
        self.write("old.md", text)
        h = document_content_hash(text)
        self.save_info(ID_A, "old.md", h)
        self.save_toc("main", [(ID_A, h)])
        (self.root / "old.md").rename(self.root / "new.md")
        plan = self.plan("main", ["new.md"])
        item = self.by_id(plan)[ID_A]
        self.assertEqual(item.action, update_plan.ACTION_UPDATE_PATH)
        self.assertEqual(plan.generation_targets, ())
        outcomes = update_plan.apply_path_updates(self.root, "test", plan)
        self.assertEqual([o.status for o in outcomes], ["saved"])
        info = state_store.load_document_info(self.root, ID_A)
        self.assertEqual(info["path"], "new.md")
        self.assertEqual(info["purpose"], "old purpose")
        self.assertEqual(info["title"], "old title")

    def test_document_known_by_other_key_is_not_generated_for_new_key(self):
        text = doc(ID_A, "# Title", "body")
        self.write("a.md", text)
        self.save_info(ID_A, "a.md", document_content_hash(text))
        self.save_toc("other", [(ID_A, document_content_hash(text))])
        plan = self.plan("newkey", ["a.md"])  # newkey の[ToC]は無い（初回）
        item = self.by_id(plan)[ID_A]
        self.assertIn(change_set.CHANGE_NEW, item.kinds)
        self.assertEqual(item.action, update_plan.ACTION_REUSE)
        self.assertEqual(plan.generation_targets, ())

    def test_only_changed_and_new_documents_are_generated(self):
        a = doc(ID_A, "# A", "v1")
        b = doc(ID_B, "# B", "body", "", "[r]: ./c.md 'x " + ID_C + "'")
        c = doc(ID_C, "# C", "body")
        for path, text in (("a.md", a), ("b.md", b), ("c.md", c)):
            self.write(path, text)
        ha, hb, hc = (document_content_hash(t) for t in (a, b, c))
        self.save_info(ID_A, "a.md", ha)
        self.save_info(ID_B, "b.md", hb)
        self.save_toc("main", [(ID_A, ha), (ID_B, hb)])
        # A は本文変更、B は参照変更だけ（内容ハッシュは同じ記録語の変更）、C は新規
        self.write("a.md", doc(ID_A, "# A", "v2"))
        b2 = doc(
            ID_B, "# B", "body", "", "[r]: ./c.md 'x " + "0" * 64 + " " + ID_C + "'"
        )
        self.write("b.md", b2)
        plan = self.plan("main", ["a.md", "b.md", "c.md"])
        items = self.by_id(plan)
        self.assertEqual(items[ID_A].action, update_plan.ACTION_GENERATE)
        self.assertEqual(items[ID_A].reason, update_plan.REASON_CONTENT_CHANGED)
        self.assertEqual(items[ID_B].action, update_plan.ACTION_REUSE)
        self.assertEqual(items[ID_C].action, update_plan.ACTION_GENERATE)
        self.assertEqual(items[ID_C].reason, update_plan.REASON_NEW_DOCUMENT)
        self.assertEqual([d.doc_link_id for d in plan.generation_targets], [ID_A, ID_C])

    def test_document_without_h1_generates_title(self):
        self.write("a.md", doc(ID_A, "## only h2"))
        self.write("b.md", doc(ID_B, f"# Heading {S1}"))
        plan = self.plan("main", ["a.md", "b.md"])
        items = self.by_id(plan)
        self.assertIn("title", items[ID_A].generate_fields)
        self.assertIsNone(items[ID_A].title)
        self.assertNotIn("title", items[ID_B].generate_fields)
        self.assertEqual(items[ID_B].title, "Heading")

    def test_departed_documents_are_listed_and_info_kept(self):
        a = doc(ID_A, "# A")
        self.write("a.md", a)
        h = document_content_hash(a)
        self.save_info(ID_A, "a.md", h)
        self.save_toc("main", [(ID_A, h)])
        self.write("b.md", doc(ID_B, "# B"))
        plan = self.plan("main", ["b.md"])
        self.assertEqual(plan.departed, (ID_A,))
        self.assertEqual(
            state_store.load_document_info(self.root, ID_A)["path"], "a.md"
        )

    def test_corrupt_document_info_fails_with_kind(self):
        text = doc(ID_A, "# A")
        self.write("a.md", text)
        path = state_store.document_info_path(self.root, ID_A)
        path.parent.mkdir(parents=True)
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(change_set.ChangeFailure) as caught:
            self.plan("main", ["a.md"])
        self.assertEqual(caught.exception.kind, change_set.FAILURE_STATE_UNREADABLE)
        self.assertEqual(caught.exception.problems[0].state_kind, "corrupt")

    def test_unreadable_document_and_unreadable_info_are_reported_together(self):
        self.write("a.md", doc(ID_A, "# A"))
        self.write("b.md", doc(ID_B, "# B"))
        cs = change_set.build_change_set(self.root, "main", ["a.md", "b.md"])
        # 変更集合を作った後に、a.md を読めなくし、B の[文書情報]を壊す
        (self.root / "a.md").write_bytes(b"\xff\xfe\x00")
        info_path = state_store.document_info_path(self.root, ID_B)
        info_path.parent.mkdir(parents=True)
        info_path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(change_set.ChangeFailure) as caught:
            update_plan.build_update_plan(self.root, cs)
        self.assertEqual(caught.exception.kind, change_set.FAILURE_DOCUMENT_UNREADABLE)
        problems = caught.exception.problems
        self.assertEqual(len(problems), 2)
        self.assertIsNone(problems[0].state_kind)
        self.assertEqual(problems[1].state_kind, "corrupt")

    def test_unreadable_document_alone_is_reported(self):
        self.write("a.md", doc(ID_A, "# A"))
        cs = change_set.build_change_set(self.root, "main", ["a.md"])
        (self.root / "a.md").write_bytes(b"\xff\xfe\x00")
        with self.assertRaises(change_set.ChangeFailure) as caught:
            update_plan.build_update_plan(self.root, cs)
        self.assertEqual(caught.exception.kind, change_set.FAILURE_DOCUMENT_UNREADABLE)
        self.assertEqual([p.path for p in caught.exception.problems], ["a.md"])

    def test_plan_exposes_only_limits_not_internal_bound(self):
        self.write("a.md", doc(ID_A, "# A"))
        plan = self.plan("main", ["a.md"])
        item = self.by_id(plan)[ID_A]
        self.assertEqual(
            item.limits,
            {"purpose": 200, "summary": 10, "applicable_tasks": 10, "keywords": 10},
        )
        dumped = json.dumps(plan.to_dict())
        for forbidden in ("260", "1.3", "margin", "130"):
            self.assertNotIn(forbidden, dumped)


class StoreTest(Base):
    def setup_two(self):
        self.write("a.md", doc(ID_A, "# A"))
        self.write("b.md", doc(ID_B, "## no h1"))
        self.write("c.md", doc(ID_C, "# C"))
        return self.plan("main", ["a.md", "b.md", "c.md"])

    def test_results_are_saved_per_document_and_failure_keeps_earlier(self):
        plan = self.setup_two()
        bad = generated()
        bad["purpose"] = "x" * 1000
        outcomes = update_plan.store_generated(
            self.root,
            "test",
            plan,
            {ID_A: generated(), ID_B: bad, ID_C: generated(purpose="c purpose")},
        )
        self.assertEqual([o.status for o in outcomes], ["saved", "failed", "saved"])
        failed = outcomes[1]
        self.assertEqual(failed.kind, update_plan.KIND_REJECTED)
        self.assertEqual(failed.failures[0].field, "purpose")
        self.assertNotIn("260", failed.failures[0].reason)
        info_a = state_store.load_document_info(self.root, ID_A)
        self.assertEqual(info_a["title"], "A")  # H1 を優先
        self.assertEqual(info_a["tasks"], ["task"])
        self.assertEqual(info_a["content_hash"], plan.documents[0].content_hash)
        with self.assertRaises(state_store.StateStoreError) as caught:
            state_store.load_document_info(self.root, ID_B)
        self.assertEqual(caught.exception.kind, "missing")
        self.assertEqual(
            state_store.load_document_info(self.root, ID_C)["purpose"], "c purpose"
        )

    def test_generated_title_is_used_without_h1(self):
        plan = self.setup_two()
        update_plan.store_generated(
            self.root, "test", plan, {ID_B: generated(title="From AI")}
        )
        self.assertEqual(
            state_store.load_document_info(self.root, ID_B)["title"], "From AI"
        )

    def test_earlier_save_is_kept_when_later_save_raises(self):
        plan = self.setup_two()
        real = state_store.save_document_info
        calls = []

        def flaky(root, skill, info):
            calls.append(info["doc_link_id"])
            if info["doc_link_id"] == ID_B:
                raise state_store.StateStoreError("write", "disk full")
            return real(root, skill, info)

        with mock.patch.object(state_store, "save_document_info", flaky):
            outcomes = update_plan.store_generated(
                self.root,
                "test",
                plan,
                {ID_A: generated(), ID_B: generated(), ID_C: generated()},
            )
        self.assertEqual([o.status for o in outcomes], ["saved", "failed", "saved"])
        self.assertEqual(outcomes[1].kind, "write")
        self.assertEqual(state_store.load_document_info(self.root, ID_A)["title"], "A")

    def test_missing_and_unplanned_results_fail(self):
        plan = self.setup_two()
        outcomes = update_plan.store_generated(
            self.root,
            "test",
            plan,
            {ID_A: generated(), "DLID-zzzzzzzzzzzz": generated()},
        )
        statuses = {(o.doc_link_id, o.kind) for o in outcomes if o.status == "failed"}
        self.assertIn((ID_B, update_plan.KIND_NOT_GENERATED), statuses)
        self.assertIn((ID_C, update_plan.KIND_NOT_GENERATED), statuses)
        self.assertIn(("DLID-zzzzzzzzzzzz", update_plan.KIND_NOT_PLANNED), statuses)

    def test_unchanged_info_is_not_rewritten(self):
        plan = self.setup_two()
        results = {ID_A: generated(), ID_B: generated(), ID_C: generated()}
        update_plan.store_generated(self.root, "test", plan, results)
        again = update_plan.store_generated(self.root, "test", plan, results)
        self.assertEqual([o.status for o in again], ["unchanged"] * 3)

    def test_results_contain_no_internal_bound(self):
        plan = self.setup_two()
        bad = generated()
        bad["summary"] = ["x"] * 50
        outcomes = update_plan.store_generated(self.root, "test", plan, {ID_A: bad})
        dumped = json.dumps([o.to_dict() for o in outcomes])
        for forbidden in ("13", "1.3", "margin"):
            self.assertNotIn(forbidden, dumped)


class UnfilledTest(Base):
    """[doc-db]を使う構築: AI 生成フィールドを作らず、未生成の[文書情報]を整える（DES-011 §3・§6）。"""

    def test_a_new_document_gets_an_unfilled_info_and_is_not_marked_unfilled_before(
        self,
    ):
        self.write("a.md", doc(ID_A, "# Title", "body"))
        plan = self.plan("main", ["a.md"])
        self.assertEqual(
            plan.unfilled_targets, ()
        )  # [文書情報]がまだ無い新規の文書は、未生成ではない
        outcomes = update_plan.apply_unfilled(self.root, "test", plan)
        self.assertEqual([o.status for o in outcomes], [update_plan.STATUS_SAVED])
        info = state_store.load_document_info(self.root, ID_A)
        self.assertEqual(
            (
                info["title"],
                info["purpose"],
                info["summary"],
                info["tasks"],
                info["keywords"],
            ),
            ("Title", "", [], [], []),
        )
        self.assertEqual(info["content_hash"], update_plan.UNFILLED_CONTENT_HASH)
        self.assertEqual(info["path"], "a.md")

    def test_a_document_without_an_h1_gets_an_empty_title(self):
        self.write("a.md", doc(ID_A, "body only"))
        plan = self.plan("main", ["a.md"])
        update_plan.apply_unfilled(self.root, "test", plan)
        self.assertEqual(state_store.load_document_info(self.root, ID_A)["title"], "")

    def test_the_unfilled_info_is_a_generation_target_marked_unfilled(self):
        self.write("a.md", doc(ID_A, "# Title", "body"))
        update_plan.apply_unfilled(self.root, "test", self.plan("main", ["a.md"]))
        plan = self.plan("main", ["a.md"])
        item = self.by_id(plan)[ID_A]
        self.assertEqual(item.action, update_plan.ACTION_GENERATE)
        self.assertTrue(item.unfilled)
        self.assertEqual(plan.unfilled_targets, (item,))

    def test_a_changed_document_keeps_its_old_ai_fields_and_is_not_unfilled(self):
        text = doc(ID_A, "# Title", "body")
        self.write("old.md", text)
        h = document_content_hash(text)
        self.save_info(ID_A, "old.md", h)
        self.save_toc("main", [(ID_A, h)])
        (self.root / "old.md").rename(self.root / "new.md")
        self.write("new.md", doc(ID_A, "# Title", "changed"))
        plan = self.plan("main", ["new.md"])
        self.assertEqual(self.by_id(plan)[ID_A].action, update_plan.ACTION_GENERATE)
        self.assertEqual(plan.unfilled_targets, ())
        update_plan.apply_unfilled(self.root, "test", plan)
        info = state_store.load_document_info(self.root, ID_A)
        self.assertEqual(info["path"], "new.md")
        self.assertEqual(info["purpose"], "old purpose")
        self.assertEqual(info["content_hash"], h)

    def test_applying_twice_changes_nothing(self):
        self.write("a.md", doc(ID_A, "# Title", "body"))
        update_plan.apply_unfilled(self.root, "test", self.plan("main", ["a.md"]))
        before = (self.root / ".doc-link").rglob("*")
        before = {str(p): p.read_bytes() for p in before if p.is_file()}
        outcomes = update_plan.apply_unfilled(
            self.root, "test", self.plan("main", ["a.md"])
        )
        self.assertEqual([o.status for o in outcomes], [update_plan.STATUS_UNCHANGED])
        after = {
            str(p): p.read_bytes()
            for p in (self.root / ".doc-link").rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)

    def test_unreadable_info_is_a_failure_not_replaced(self):
        self.write("a.md", doc(ID_A, "# Title", "body"))
        path = state_store.document_info_path(self.root, ID_A)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(change_set.ChangeFailure):
            self.plan("main", ["a.md"])


if __name__ == "__main__":
    unittest.main()
