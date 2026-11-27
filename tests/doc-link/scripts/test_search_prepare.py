import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import change_set  # noqa: E402
import search_prepare as sp  # noqa: E402
import state_store  # noqa: E402
import target_spec  # noqa: E402
import toc_candidate  # noqa: E402
from content_hash import document_content_hash  # noqa: E402
from reference_check import check_document  # noqa: E402
from target_spec import MODE_TARGETS, TargetSpec  # noqa: E402

KEY = "k"
ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
SEC_A = "DLID-00000000s001"
SEC_B = "DLID-00000000s002"
SEC_A1 = "DLID-00000000s011"
SEC_A2 = "DLID-00000000s012"
SEC_A3 = "DLID-00000000s013"
WHEN = "2026-11-13T00:00:00+00:00"
A_TEXT = f"---\ndoc_link_id: {ID_A}\n---\n# A {SEC_A}\n\nbody\n"
B_TEXT = f"---\ndoc_link_id: {ID_B}\n---\n# B {SEC_B}\n"
# 前方一致の検査に使う、複数のセクションを持つ文書 A
MULTI_A_TEXT = (
    f"---\ndoc_link_id: {ID_A}\n---\n# A {SEC_A}\n\n"
    f"## 概要 {SEC_A1}\n\n## 設計方針 {SEC_A2}\n\n## 設計判断 {SEC_A3}\n"
)
TASK = '検索のタスク\n"引用" `code`'


TITLE_A = "タイトル A"
TITLE_B = "B"
HEAD_A = "A"
HEAD_B = "B"

RELEVANT = {"relevance": "yes", "reason": "r"}
RELEVANCE_FORM = 'relevance が "yes"・"maybe"・"no" のどれかでない'
MAYBE = {"relevance": "maybe", "reason": "m"}
NOT_RELEVANT = {"relevance": "no"}


def as_text(value):
    """答え（`query-worker` が標準入力で渡す JSON）の文字列にする。文字列はそのまま返す。"""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


class SearchTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def build(
        self,
        key=KEY,
        a_text=A_TEXT,
        paths=("a.md", "b.md"),
        titles=(TITLE_A, TITLE_B),
    ):
        """[文書情報]と[確定 ToC]を、index-docs が確定した状態として保存する。"""
        self.write("a.md", a_text)
        self.write("b.md", B_TEXT)
        for path, doc_id, title in (
            ("a.md", ID_A, titles[0]),
            ("b.md", ID_B, titles[1]),
        ):
            state_store.save_document_info(
                self.root,
                "test",
                {
                    "doc_link_id": doc_id,
                    "path": path,
                    "title": title,
                    "purpose": f"目的 {title}",
                    "summary": [f"概要 {title}"],
                    "tasks": [f"作業 {title}"],
                    "keywords": [f"kw-{title}"],
                    "content_hash": document_content_hash(
                        (self.root / path).read_text(encoding="utf-8")
                    ),
                },
            )
        spec = TargetSpec(mode=MODE_TARGETS, key=key, paths=tuple(paths))
        cs = change_set.build_change_set(self.root, key, list(paths))
        results = {
            item.doc_link_id: check_document(self.root, item.path, checked_at=WHEN)
            for item in cs.confirmed_documents
        }
        toc_candidate.build_and_publish(self.root, "test", key, spec, cs, results)

    def snapshot(self, include_temp=False):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
            and (include_temp or p.relative_to(self.root).parts[0] != ".temp")
        }

    def work_dir(self):
        return self.root / ".temp" / "doc-link" / "query-docs"

    def work_files(self):
        directory = self.work_dir()
        return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []

    def fix(self, **build_options):
        self.build(**build_options)
        return sp.prepare(self.root, KEY, None, TASK)

    def fix_multi(self, **build_options):
        """文書 1 件ずつの担当（担当は 2 本）に分けて固定する。"""
        self.build(**build_options)
        with mock.patch.object(sp, "MIN_DOCUMENTS_PER_WORKER", 1):
            return sp.prepare(self.root, KEY, None, TASK)

    def fixed_state(self, search_id):
        path = self.work_dir() / f"{search_id}.fixed.json"
        return json.loads(path.read_text("utf-8"))

    def start(self, **build_options):
        """固定して、担当 1 本の識別値を返す（文書は 2 件とも、その担当が持つ）。"""
        payload = self.fix(**build_options)
        self.assertEqual(len(payload["workers"]), 1)
        return payload["search_id"], payload["workers"][0]

    def answer(self, worker_id, value):
        return sp.submit_answer(self.root, worker_id, as_text(value))

    def answer_files(self):
        return [name for name in self.work_files() if ".answer-" in name]

    def read_item(self, worker_id):
        return json.loads(
            Path(sp.next_item(self.root, worker_id)["item_path"]).read_text("utf-8")
        )


class PlanWorkersTest(unittest.TestCase):
    def ids(self, count):
        return [f"DLID-{n:012d}" for n in range(count)]

    def test_no_documents_means_no_workers(self):
        self.assertEqual(sp._plan_workers([]), [])

    def test_few_documents_are_assigned_to_one_worker(self):
        for count in (
            1,
            5,
            sp.MIN_DOCUMENTS_PER_WORKER,
            sp.MIN_DOCUMENTS_PER_WORKER + 1,
        ):
            with self.subTest(count=count):
                ids = self.ids(count)
                self.assertEqual(sp._plan_workers(ids), [ids])

    def test_a_worker_never_gets_fewer_than_the_minimum(self):
        with mock.patch.object(sp, "MIN_DOCUMENTS_PER_WORKER", 3):
            for count in range(3, 30):
                with self.subTest(count=count):
                    plans = sp._plan_workers(self.ids(count))
                    self.assertEqual(
                        len(plans), min(sp.MAX_CONCURRENT_WORKERS, count // 3)
                    )
                    self.assertTrue(all(len(plan) >= 3 for plan in plans))
            self.assertEqual(
                [len(plan) for plan in sp._plan_workers(self.ids(7))], [4, 3]
            )
            # 最小の件数に足りないときも、担当は 1 本ある
            self.assertEqual([len(plan) for plan in sp._plan_workers(self.ids(2))], [2])

    def test_workers_never_exceed_the_maximum(self):
        with mock.patch.object(sp, "MIN_DOCUMENTS_PER_WORKER", 1):
            plans = sp._plan_workers(self.ids(25))
            self.assertEqual(len(plans), sp.MAX_CONCURRENT_WORKERS)
            with mock.patch.object(sp, "MAX_CONCURRENT_WORKERS", 3):
                self.assertEqual(len(sp._plan_workers(self.ids(100))), 3)

    def test_the_remainder_goes_one_by_one_from_the_first_worker(self):
        with mock.patch.object(sp, "MIN_DOCUMENTS_PER_WORKER", 1):
            with mock.patch.object(sp, "MAX_CONCURRENT_WORKERS", 3):
                self.assertEqual(
                    [len(plan) for plan in sp._plan_workers(self.ids(10))], [4, 3, 3]
                )
                self.assertEqual(
                    [len(plan) for plan in sp._plan_workers(self.ids(11))], [4, 4, 3]
                )
                self.assertEqual(
                    [len(plan) for plan in sp._plan_workers(self.ids(12))], [4, 4, 4]
                )

    def test_order_is_kept_and_every_document_is_assigned_exactly_once(self):
        with mock.patch.object(sp, "MIN_DOCUMENTS_PER_WORKER", 2):
            for count in (1, 2, 7, 23, 64):
                with self.subTest(count=count):
                    ids = self.ids(count)
                    plans = sp._plan_workers(ids)
                    self.assertEqual([i for plan in plans for i in plan], ids)


class FixTest(SearchTestBase):
    def test_fixed_search_has_id_version_workers_and_current_freshness(self):
        payload = self.fix()
        self.assertEqual(payload["action"], sp.ACTION_INVOKE_WORKER)
        self.assertRegex(payload["search_id"], r"SEARCH-[0-9a-f]{8}")
        self.assertEqual(payload["toc_key"], KEY)
        self.assertEqual(
            payload["toc_version"],
            state_store.load_confirmed_toc(self.root, KEY)["version"],
        )
        self.assertEqual(payload["freshness"], sp.FRESHNESS_CURRENT)
        self.assertIsNone(payload["freshness_notice"])
        self.assertEqual(payload["workers"], [payload["search_id"] + "-1"])
        self.assertEqual(
            sp.split_worker_id(payload["workers"][0]), (payload["search_id"], 1)
        )

    def test_documents_are_split_into_workers_by_the_plan(self):
        payload = self.fix_multi()
        sid = payload["search_id"]
        self.assertEqual(payload["workers"], [f"{sid}-1", f"{sid}-2"])
        self.assertEqual(
            self.fixed_state(sid)["workers"], {f"{sid}-1": [ID_A], f"{sid}-2": [ID_B]}
        )

    def test_fixed_state_holds_the_shown_content_and_the_section_names(self):
        sid, wid = self.start()
        fixed = self.fixed_state(sid)
        self.assertEqual(fixed["task"], TASK)
        self.assertEqual(fixed["toc_key"], KEY)
        self.assertEqual(fixed["freshness"], sp.FRESHNESS_CURRENT)
        self.assertEqual(fixed["workers"], {wid: [ID_A, ID_B]})
        first = fixed["documents"][ID_A]
        self.assertEqual(first["path"], "a.md")
        self.assertEqual(first["title"], "タイトル A")
        self.assertEqual(first["purpose"], "目的 タイトル A")
        self.assertEqual(first["summary"], ["概要 タイトル A"])
        self.assertEqual(first["tasks"], ["作業 タイトル A"])
        self.assertEqual(first["keywords"], ["kw-タイトル A"])
        self.assertEqual(
            first["sections"],
            [{"section_id": SEC_A, "heading": HEAD_A, "name": HEAD_A}],
        )

    def test_documents_of_a_worker_are_in_ascending_path_order(self):
        # 並びは[文書 ID]ではなく、記録されたパスの昇順
        self.build()
        info = state_store.load_document_info(self.root, ID_A)
        info["path"] = "z.md"
        state_store.save_document_info(self.root, "test", info)
        payload = sp._fix(self.root, KEY, TASK, sp.FRESHNESS_CURRENT, "up_to_date")
        fixed = self.fixed_state(payload["search_id"])
        self.assertEqual(list(fixed["workers"].values()), [[ID_B, ID_A]])

    def test_same_headings_get_a_marker_and_names_are_unique(self):
        text = (
            f"---\ndoc_link_id: {ID_A}\n---\n# A {SEC_A}\n\n"
            f"## X {SEC_A1}\n\n## X {SEC_A2}\n"
        )
        sid, _ = self.start(a_text=text)
        sections = self.fixed_state(sid)["documents"][ID_A]["sections"]
        self.assertEqual(
            [s["name"] for s in sections], ["A", "X（同名 1/2）", "X（同名 2/2）"]
        )
        self.assertEqual([s["heading"] for s in sections], ["A", "X", "X"])

    def test_section_names_that_differ_only_in_width_are_made_unique(self):
        text = (
            f"---\ndoc_link_id: {ID_A}\n---\n# A {SEC_A}\n\n"
            f"## ＡＢＣ {SEC_A1}\n\n## ABC {SEC_A2}\n"
        )
        sid, _ = self.start(a_text=text)
        names = [
            s["name"] for s in self.fixed_state(sid)["documents"][ID_A]["sections"]
        ]
        self.assertEqual(names, ["A", "ＡＢＣ（同名 1/2）", "ABC（同名 2/2）"])

    def test_names_that_cannot_be_made_unique_are_a_search_error(self):
        text = (
            f"---\ndoc_link_id: {ID_A}\n---\n# A {SEC_A}\n\n"
            f"## X {SEC_A1}\n\n## X {SEC_A2}\n\n## X（同名 1/2） {SEC_A3}\n"
        )
        self.build(a_text=text)
        with self.assertRaises(sp.SearchError):
            sp.prepare(self.root, KEY, None, TASK)

    def test_unique_names_adds_a_marker_only_to_names_that_collide(self):
        self.assertEqual(sp._unique_names(["a", "b"]), ["a", "b"])
        self.assertEqual(
            sp._unique_names(["概要", "別", "概要"]),
            ["概要（同名 1/2）", "別", "概要（同名 2/2）"],
        )
        # 全角半角・空白の違いだけの名前は、同じ名前として扱う
        self.assertEqual(
            sp._unique_names(["ＡＢＣ  d", "ABC d"]),
            ["ＡＢＣ  d（同名 1/2）", "ABC d（同名 2/2）"],
        )

    def test_unique_names_refuses_when_a_marker_would_collide_with_another_name(self):
        with self.assertRaises(sp.SearchError):
            sp._unique_names(["x", "x", "x（同名 1/2）"])

    def test_normalize_unifies_width_and_whitespace(self):
        self.assertEqual(sp._normalize("ＡＢＣ　 d\te"), "ABC d e")
        self.assertEqual(sp._normalize("  a  "), "a")

    def test_the_fixed_state_is_published_last_and_alone(self):
        payload = self.fix()
        sid = payload["search_id"]
        # 依頼・答え・写し・一時ファイルは、固定の時点では無い。固定した状態だけがある
        self.assertEqual(self.work_files(), [f"{sid}.fixed.json"])
        self.assertEqual(sp.find_project_root(sid, self.root), self.root)

    def test_no_item_file_or_copy_exists_after_prepare(self):
        self.fix()
        for name in self.work_files():
            self.assertNotIn(".item-", name)
            self.assertNotIn(".toc.", name)
            self.assertNotIn(".request.", name)

    def test_version_is_fixed_even_if_toc_is_updated_afterwards(self):
        sid, wid = self.start()
        fixed_version = self.fixed_state(sid)["toc_version"]
        self.build(a_text=A_TEXT + "changed\n")
        self.assertNotEqual(
            state_store.load_confirmed_toc(self.root, KEY)["version"], fixed_version
        )
        self.answer(wid, NOT_RELEVANT)
        self.answer(wid, NOT_RELEVANT)
        self.assertEqual(sp.collect(self.root, sid)["toc_version"], fixed_version)

    def test_unreadable_document_info_is_an_error(self):
        self.build()
        state_store.document_info_path(self.root, ID_B).write_bytes(b"{broken")
        with self.assertRaises(sp.SearchError):
            sp._fix(self.root, KEY, TASK, sp.FRESHNESS_CURRENT, "up_to_date")

    def test_prepare_with_no_documents_has_no_workers(self):
        self.build(paths=())
        payload = sp.prepare(self.root, KEY, None, TASK)
        self.assertEqual(payload["action"], sp.ACTION_INVOKE_WORKER)
        self.assertEqual(payload["workers"], [])
        self.assertEqual(self.fixed_state(payload["search_id"])["workers"], {})


class NextItemTest(SearchTestBase):
    def test_returns_the_path_of_the_item_with_only_the_specified_content(self):
        sid, wid = self.start()
        result = sp.next_item(self.root, wid)
        self.assertFalse(result["done"])
        path = Path(result["item_path"])
        self.assertTrue(path.is_absolute())
        self.assertEqual(path.parent, self.work_dir().resolve())
        self.assertTrue(path.is_file())
        text = path.read_text("utf-8")
        item = json.loads(text)
        self.assertEqual(
            sorted(item),
            sorted(
                [
                    "task",
                    "position",
                    "total",
                    "title",
                    "purpose",
                    "summary",
                    "tasks",
                    "keywords",
                    "sections",
                ]
            ),
        )
        self.assertEqual(item["task"], TASK)
        self.assertEqual(item["position"], 1)
        self.assertEqual(item["total"], 2)
        self.assertEqual(item["title"], "タイトル A")
        self.assertEqual(item["purpose"], "目的 タイトル A")
        self.assertEqual(item["summary"], ["概要 タイトル A"])
        self.assertEqual(item["tasks"], ["作業 タイトル A"])
        self.assertEqual(item["keywords"], ["kw-タイトル A"])
        self.assertEqual(item["sections"], [HEAD_A])
        # ID・パス・内容ハッシュ・参照関係・検査結果を含まない
        toc = state_store.load_confirmed_toc(self.root, KEY)
        forbidden = [
            "a.md",
            "b.md",
            "content_hash",
            "applied_hash",
            "references",
            "doc_link_id",
            "section_id",
            "DLID-",
            ID_A,
            ID_B,
            SEC_A,
            SEC_B,
        ] + [entry["applied_hash"] for entry in toc["documents"]]
        for needle in forbidden:
            self.assertNotIn(needle, text)

    def test_item_is_written_in_the_state_style_not_compact(self):
        _, wid = self.start()
        text = Path(sp.next_item(self.root, wid)["item_path"]).read_text("utf-8")
        self.assertTrue(text.startswith('{\n  "task"'))
        self.assertTrue(text.endswith("}\n"))

    def test_item_that_cannot_be_encoded_is_a_search_error(self):
        # 単独のサロゲートは UTF-8 にできない。契約外の例外にせず、SearchError にする
        with self.assertRaises(sp.SearchError):
            sp._serialize_item({"title": "\ud800"})

    def test_same_document_and_same_path_until_the_answer_is_stored(self):
        _, wid = self.start()
        first = sp.next_item(self.root, wid)
        again = sp.next_item(self.root, wid)
        self.assertEqual(first, again)
        self.assertEqual(self.read_item(wid)["title"], "タイトル A")
        # 答えの検査に通らなくても、進まない
        with self.assertRaises(sp.SearchError):
            self.answer(wid, "{")
        self.assertEqual(sp.next_item(self.root, wid), first)
        self.answer(wid, NOT_RELEVANT)
        second = sp.next_item(self.root, wid)
        self.assertNotEqual(second["item_path"], first["item_path"])
        self.assertEqual(second["answered"], 1)
        self.assertEqual(self.read_item(wid)["title"], TITLE_B)
        self.assertEqual(self.read_item(wid)["position"], 2)
        self.assertEqual(sp.next_item(self.root, wid), second)

    def test_done_when_every_document_is_answered(self):
        _, wid = self.start()
        self.answer(wid, NOT_RELEVANT)
        self.answer(wid, NOT_RELEVANT)
        result = sp.next_item(self.root, wid)
        self.assertTrue(result["done"])
        self.assertIsNone(result["item_path"])

    def test_each_worker_gets_its_own_documents(self):
        payload = self.fix_multi()
        first, second = payload["workers"]
        self.assertEqual(self.read_item(first)["title"], "タイトル A")
        self.assertEqual(self.read_item(first)["total"], 1)
        self.assertEqual(self.read_item(second)["title"], TITLE_B)
        self.assertEqual(self.read_item(second)["position"], 1)

    def test_unknown_or_malformed_worker_is_a_search_error(self):
        sid, _ = self.start()
        for worker_id in (
            f"{sid}-2",
            f"{sid}-0",
            f"{sid}-01",
            sid,
            "not-a-worker",
            "../etc",
            "SEARCH-00000000-1",
        ):
            with self.subTest(worker_id=worker_id):
                with self.assertRaises(sp.SearchError):
                    sp.next_item(self.root, worker_id)

    def test_split_worker_id(self):
        self.assertEqual(
            sp.split_worker_id("SEARCH-0123abcd-12"), ("SEARCH-0123abcd", 12)
        )
        for bad in ("SEARCH-0123abcd", "SEARCH-0123abcd-0", "SEARCH-xyz-1", "-1", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(sp.SearchError):
                    sp.split_worker_id(bad)


class SubmitAnswerTest(SearchTestBase):
    """標準入力で渡された答えの検査。通らなければ何も書かず、同じ文書に答え直せる（Issue #17・#19）。"""

    def assertRejected(self, wid, value, *expected):
        before = sp.next_item(self.root, wid)
        with self.assertRaises(sp.SearchError) as caught:
            self.answer(wid, value)
        for fragment in expected:
            self.assertTrue(
                any(fragment in e for e in caught.exception.errors),
                (fragment, caught.exception.errors),
            )
        self.assertEqual(self.answer_files(), [])
        self.assertEqual(sp.next_item(self.root, wid), before)
        return caught.exception.errors

    def test_unreadable_json_is_rejected_and_the_same_document_can_be_answered_again(
        self,
    ):
        _, wid = self.start()
        self.assertRejected(wid, '{"relevance": ', "JSON として読めない")
        self.assertRejected(wid, "", "標準入力が空")
        self.assertRejected(wid, "  \n", "標準入力が空")
        self.answer(wid, NOT_RELEVANT)
        self.assertEqual(len(self.answer_files()), 1)

    def test_wrong_shape_is_rejected(self):
        _, wid = self.start()
        for text in ("[]", '"x"', "1", "null"):
            with self.subTest(text=text):
                self.assertRejected(wid, text, "relevance")

    def test_wrong_keys_and_types_are_rejected(self):
        _, wid = self.start()
        cases = [
            ("{}", RELEVANCE_FORM),
            ('{"relevance": 1}', RELEVANCE_FORM),
            ('{"relevance": "true"}', RELEVANCE_FORM),
            ('{"relevance": null}', RELEVANCE_FORM),
            ('{"relevance": "no", "x": 1}', "定義に無いキーがある: x"),
            ('{"relevance": "no", "doc_link_id": "DLID-1"}', "doc_link_id"),
            ('{"relevance": "no", "title": "t"}', "title"),
            ('{"relevance": "no", "reason": "r"}', "reason・headings を付けない"),
            ('{"relevance": "no", "headings": []}', "reason・headings を付けない"),
            ('{"relevance": "yes"}', "reason が文字列でない"),
            ('{"relevance": "maybe"}', "reason が文字列でない"),
            ('{"relevance": "maybe", "reason": 1}', "reason が文字列でない"),
            ('{"relevance": "yes", "reason": null}', "reason が文字列でない"),
            ('{"relevance": "yes", "reason": 1}', "reason が文字列でない"),
            (
                '{"relevance": "yes", "reason": "r", "headings": "s"}',
                "headings が文字列の配列でない",
            ),
            (
                '{"relevance": "yes", "reason": "r", "headings": [1]}',
                "headings が文字列の配列でない",
            ),
            (
                '{"relevance": "yes", "reason": "r", "headings": null}',
                "headings が文字列の配列でない",
            ),
        ]
        for text, fragment in cases:
            with self.subTest(text=text):
                self.assertRejected(wid, text, fragment)

    def test_every_wrong_point_is_reported_at_once(self):
        _, wid = self.start()
        errors = self.assertRejected(
            wid,
            '{"relevance": "yes", "reason": 1, "headings": "s", "extra": 1}',
            "定義に無いキーがある: extra",
            "reason が文字列でない",
            "headings が文字列の配列でない",
        )
        self.assertEqual(len(errors), 3)

    def test_headings_may_be_omitted_and_an_empty_reason_is_accepted(self):
        _, wid = self.start()
        self.answer(wid, {"relevance": "yes", "reason": ""})
        self.answer(wid, RELEVANT)
        found = sp.collect(self.root, self.fixed_state_id(wid))["documents"]
        self.assertEqual([d["sections"] for d in found], [[], []])
        self.assertEqual(found[0]["reason"], "")

    def fixed_state_id(self, wid):
        return sp.split_worker_id(wid)[0]

    def test_heading_is_matched_after_normalizing_width_and_whitespace(self):
        sid, wid = self.start()
        self.answer(wid, {"relevance": "yes", "reason": "r", "headings": [" Ａ "]})
        self.answer(wid, NOT_RELEVANT)
        result = sp.collect(self.root, sid)
        self.assertEqual(
            result["documents"][0]["sections"],
            [{"section_id": SEC_A, "heading": "A"}],
        )

    def test_the_heading_with_the_same_text_as_the_title_is_a_selectable_section(self):
        # b.md は、タイトルと先頭の見出しが同じ（B）。見出しは、その文書のセクションの中だけから引く
        sid, wid = self.start()
        self.answer(wid, NOT_RELEVANT)
        self.answer(wid, {"relevance": "yes", "reason": "r", "headings": [HEAD_B]})
        result = sp.collect(self.root, sid)
        self.assertEqual(
            result["documents"][0]["sections"],
            [{"section_id": SEC_B, "heading": "B"}],
        )

    def test_a_unique_prefix_resolves_and_an_exact_match_resolves(self):
        sid, wid = self.start(a_text=MULTI_A_TEXT)
        self.answer(
            wid, {"relevance": "yes", "reason": "r", "headings": ["概", "設計方針"]}
        )
        self.answer(wid, NOT_RELEVANT)
        sections = sp.collect(self.root, sid)["documents"][0]["sections"]
        self.assertEqual(
            sections,
            [
                {"section_id": SEC_A1, "heading": "概要"},
                {"section_id": SEC_A2, "heading": "設計方針"},
            ],
        )

    def test_a_prefix_matching_several_headings_is_rejected_with_candidates(self):
        _, wid = self.start(a_text=MULTI_A_TEXT)
        errors = self.assertRejected(
            wid,
            {"relevance": "yes", "reason": "r", "headings": ["設計"]},
            "複数の見出しに当たる",
        )
        for candidate in ("A", "概要", "設計方針", "設計判断"):
            self.assertTrue(any(candidate in e for e in errors), candidate)
        # 候補で答え直せる
        self.answer(wid, {"relevance": "yes", "reason": "r", "headings": ["設計判"]})

    def test_a_missing_heading_is_rejected_with_candidates_and_nothing_is_stored(self):
        _, wid = self.start(a_text=MULTI_A_TEXT)
        errors = self.assertRejected(
            wid,
            {
                "relevance": "yes",
                "reason": "r",
                "headings": ["概要", "存在しない見出し"],
            },
            "存在しない見出し",
            "見出しに無い",
        )
        for candidate in ("A", "概要", "設計方針", "設計判断"):
            self.assertTrue(any(candidate in e for e in errors), candidate)

    def test_a_heading_of_another_document_cannot_be_resolved(self):
        # 見出しは、答える文書のセクションの中だけから引く。文書を取り違えない
        _, wid = self.start()
        self.assertRejected(
            wid,
            {"relevance": "yes", "reason": "r", "headings": [HEAD_B]},
            "見出しに無い",
        )

    def test_the_same_section_selected_twice_is_selected_once(self):
        sid, wid = self.start()
        self.answer(
            wid, {"relevance": "yes", "reason": "r", "headings": [HEAD_A, HEAD_A, " A"]}
        )
        self.answer(wid, NOT_RELEVANT)
        self.assertEqual(
            sp.collect(self.root, sid)["documents"][0]["sections"],
            [{"section_id": SEC_A, "heading": "A"}],
        )

    def test_a_relevance_other_than_the_three_words_is_rejected_and_can_be_answered_again(
        self,
    ):
        _, wid = self.start()
        for text in (
            '{"relevance": "YES"}',
            '{"relevance": "true"}',
            '{"relevance": true}',
            '{"relevance": false}',
            '{"relevance": 1}',
            '{"relevance": null}',
            '{"reason": "r"}',
            '{"relevant": true, "reason": "r"}',
        ):
            with self.subTest(text=text):
                self.assertRejected(wid, text, RELEVANCE_FORM)
        self.answer(wid, RELEVANT)
        self.assertEqual(len(self.answer_files()), 1)

    def test_maybe_is_accepted_and_stores_the_relevance_as_a_string(self):
        sid, wid = self.start()
        self.answer(wid, MAYBE)
        self.answer(wid, NOT_RELEVANT)
        stored = json.loads(
            (self.work_dir() / f"{sid}.w1.answer-0001.json").read_text("utf-8")
        )
        self.assertEqual(stored["relevance"], "maybe")
        self.assertNotIn("relevant", stored)
        stored_no = json.loads(
            (self.work_dir() / f"{sid}.w1.answer-0002.json").read_text("utf-8")
        )
        self.assertEqual(stored_no["relevance"], "no")
        self.assertNotIn("relevant", stored_no)

    def test_maybe_needs_a_reason_and_may_omit_headings(self):
        _, wid = self.start()
        self.assertRejected(wid, '{"relevance": "maybe"}', "reason が文字列でない")
        self.assertRejected(
            wid, '{"relevance": "maybe", "reason": null}', "reason が文字列でない"
        )
        self.assertRejected(
            wid,
            '{"relevance": "maybe", "reason": "r", "headings": "s"}',
            "headings が文字列の配列でない",
        )
        self.answer(wid, {"relevance": "maybe", "reason": ""})
        self.assertEqual(len(self.answer_files()), 1)

    def test_maybe_resolves_headings_like_yes(self):
        sid, wid = self.start(a_text=MULTI_A_TEXT)
        self.answer(
            wid, {"relevance": "maybe", "reason": "r", "headings": ["概", "設計方針"]}
        )
        self.answer(wid, NOT_RELEVANT)
        document = sp.collect(self.root, sid)["documents"][0]
        self.assertEqual(document["relevance"], "maybe")
        self.assertEqual(
            document["sections"],
            [
                {"section_id": SEC_A1, "heading": "概要"},
                {"section_id": SEC_A2, "heading": "設計方針"},
            ],
        )

    def test_maybe_with_a_missing_or_ambiguous_heading_is_rejected(self):
        _, wid = self.start(a_text=MULTI_A_TEXT)
        self.assertRejected(
            wid,
            {"relevance": "maybe", "reason": "r", "headings": ["存在しない見出し"]},
            "見出しに無い",
        )
        self.assertRejected(
            wid,
            {"relevance": "maybe", "reason": "r", "headings": ["設計"]},
            "複数の見出しに当たる",
        )

    def test_no_with_a_reason_or_headings_is_rejected(self):
        _, wid = self.start()
        for text in (
            '{"relevance": "no", "reason": "r"}',
            '{"relevance": "no", "headings": []}',
            '{"relevance": "no", "reason": "r", "headings": ["A"]}',
        ):
            with self.subTest(text=text):
                self.assertRejected(wid, text, "reason・headings を付けない")
        self.answer(wid, NOT_RELEVANT)
        self.assertEqual(len(self.answer_files()), 1)

    def test_same_named_headings_are_answered_by_their_marked_names(self):
        text = (
            f"---\ndoc_link_id: {ID_A}\n---\n# A {SEC_A}\n\n"
            f"## X {SEC_A1}\n\n## X {SEC_A2}\n"
        )
        sid, wid = self.start(a_text=text)
        self.answer(
            wid, {"relevance": "yes", "reason": "r", "headings": ["X（同名 2/2）"]}
        )
        self.answer(wid, NOT_RELEVANT)
        self.assertEqual(
            sp.collect(self.root, sid)["documents"][0]["sections"],
            [{"section_id": SEC_A2, "heading": "X"}],
        )

    def test_the_return_value_has_the_next_item_and_the_last_is_done(self):
        _, wid = self.start()
        first = self.answer(wid, NOT_RELEVANT)
        self.assertEqual(first["stored"], {"position": 1, "total": 2})
        self.assertFalse(first["done"])
        self.assertEqual(first["item_path"], sp.next_item(self.root, wid)["item_path"])
        self.assertEqual(
            json.loads(Path(first["item_path"]).read_text("utf-8"))["title"], TITLE_B
        )
        last = self.answer(wid, NOT_RELEVANT)
        self.assertEqual(last["stored"], {"position": 2, "total": 2})
        self.assertTrue(last["done"])
        self.assertIsNone(last["item_path"])

    def test_an_answer_after_all_documents_are_answered_is_rejected(self):
        sid, wid = self.start()
        self.answer(wid, NOT_RELEVANT)
        self.answer(wid, NOT_RELEVANT)
        with self.assertRaises(sp.SearchError):
            self.answer(wid, RELEVANT)
        self.assertEqual(len(self.answer_files()), 2)
        self.assertEqual(sp.collect(self.root, sid)["documents"], [])

    def test_an_answer_is_tied_to_the_document_by_position(self):
        sid, wid = self.start()
        self.answer(wid, {"relevance": "yes", "reason": "ra"})
        self.answer(wid, {"relevance": "yes", "reason": "rb"})
        self.assertEqual(
            [
                (d["doc_link_id"], d["reason"])
                for d in sp.collect(self.root, sid)["documents"]
            ],
            [(ID_A, "ra"), (ID_B, "rb")],
        )
        stored = json.loads(
            (self.work_dir() / f"{sid}.w1.answer-0001.json").read_text("utf-8")
        )
        self.assertEqual(stored["doc_link_id"], ID_A)
        self.assertEqual(stored["section_ids"], [])

    def test_answers_of_different_workers_are_independent(self):
        payload = self.fix_multi()
        first, second = payload["workers"]
        self.answer(second, {"relevance": "yes", "reason": "rb"})
        self.assertEqual(sp.next_item(self.root, first)["answered"], 0)
        self.assertTrue(sp.next_item(self.root, second)["done"])

    def test_submitting_to_an_unknown_worker_fails(self):
        self.start()
        with self.assertRaises(sp.SearchError):
            self.answer("SEARCH-00000000-1", NOT_RELEVANT)
        with self.assertRaises(sp.SearchError):
            self.answer("bad", NOT_RELEVANT)
        self.assertEqual(self.answer_files(), [])


class CollectTest(SearchTestBase):
    def test_returns_relevant_documents_with_recorded_path_reason_and_sections(self):
        sid, wid = self.start()
        self.answer(wid, {"relevance": "yes", "reason": "ra", "headings": [HEAD_A]})
        self.answer(wid, {"relevance": "yes", "reason": "rb"})
        result = sp.collect(self.root, sid)
        self.assertEqual(
            result["documents"],
            [
                {
                    "doc_link_id": ID_A,
                    "recorded_path": "a.md",
                    "relevance": "yes",
                    "reason": "ra",
                    "sections": [{"section_id": SEC_A, "heading": "A"}],
                },
                {
                    "doc_link_id": ID_B,
                    "recorded_path": "b.md",
                    "relevance": "yes",
                    "reason": "rb",
                    "sections": [],
                },
            ],
        )
        self.assertEqual(result["search_id"], sid)
        self.assertEqual(result["toc_key"], KEY)
        self.assertEqual(result["freshness"], sp.FRESHNESS_CURRENT)
        self.assertIsNone(result["freshness_notice"])
        self.assertIn("実体パス", result["path_notice"])

    def test_only_relevant_documents_are_returned(self):
        sid, wid = self.start()
        self.answer(wid, NOT_RELEVANT)
        self.answer(wid, RELEVANT)
        self.assertEqual(
            [d["doc_link_id"] for d in sp.collect(self.root, sid)["documents"]], [ID_B]
        )

    def test_maybe_is_included_in_the_result_with_its_relevance(self):
        sid, wid = self.start()
        self.answer(wid, {"relevance": "maybe", "reason": "ra", "headings": [HEAD_A]})
        self.answer(wid, RELEVANT)
        self.assertEqual(
            sp.collect(self.root, sid)["documents"],
            [
                {
                    "doc_link_id": ID_A,
                    "recorded_path": "a.md",
                    "relevance": "maybe",
                    "reason": "ra",
                    "sections": [{"section_id": SEC_A, "heading": "A"}],
                },
                {
                    "doc_link_id": ID_B,
                    "recorded_path": "b.md",
                    "relevance": "yes",
                    "reason": "r",
                    "sections": [],
                },
            ],
        )

    def test_maybe_and_yes_are_in_worker_order_then_path_order(self):
        payload = self.fix_multi()
        sid = payload["search_id"]
        first, second = payload["workers"]
        self.answer(second, RELEVANT)
        self.answer(first, MAYBE)
        documents = sp.collect(self.root, sid)["documents"]
        self.assertEqual([d["doc_link_id"] for d in documents], [ID_A, ID_B])
        self.assertEqual([d["relevance"] for d in documents], ["maybe", "yes"])
        sid, wid = self.start()
        self.answer(wid, MAYBE)
        self.answer(wid, MAYBE)
        self.assertEqual(
            [d["recorded_path"] for d in sp.collect(self.root, sid)["documents"]],
            ["a.md", "b.md"],
        )

    def test_a_search_with_only_maybe_answers_succeeds(self):
        sid, wid = self.start()
        self.answer(wid, MAYBE)
        self.answer(wid, MAYBE)
        result = sp.collect(self.root, sid)
        self.assertEqual([d["relevance"] for d in result["documents"]], ["maybe"] * 2)

    def test_only_no_answers_are_excluded_from_the_result(self):
        sid, wid = self.start()
        self.answer(wid, NOT_RELEVANT)
        self.answer(wid, MAYBE)
        self.assertEqual(
            [d["doc_link_id"] for d in sp.collect(self.root, sid)["documents"]], [ID_B]
        )

    def test_every_document_in_the_result_has_a_relevance_of_yes_or_maybe(self):
        sid, wid = self.start()
        self.answer(wid, RELEVANT)
        self.answer(wid, MAYBE)
        for document in sp.collect(self.root, sid)["documents"]:
            self.assertIn(document["relevance"], (sp.RELEVANCE_YES, sp.RELEVANCE_MAYBE))
            self.assertNotEqual(document["relevance"], sp.RELEVANCE_NO)

    def test_the_relevance_constants(self):
        self.assertEqual(sp.RELEVANCE_YES, "yes")
        self.assertEqual(sp.RELEVANCE_MAYBE, "maybe")
        self.assertEqual(sp.RELEVANCE_NO, "no")
        self.assertEqual(sp.RELEVANCES, ("yes", "maybe", "no"))

    def test_order_is_worker_order_then_order_in_the_worker_not_the_answering_order(
        self,
    ):
        payload = self.fix_multi()
        sid = payload["search_id"]
        first, second = payload["workers"]
        # 担当 2 を先に答えても、結果は担当の順
        self.answer(second, {"relevance": "yes", "reason": "rb"})
        self.answer(first, {"relevance": "yes", "reason": "ra"})
        result = sp.collect(self.root, sid)
        self.assertEqual([d["doc_link_id"] for d in result["documents"]], [ID_A, ID_B])
        self.assertEqual(result["order_notice"], sp.NOTICE_ORDER)

    def test_the_order_in_a_worker_is_the_path_order(self):
        sid, wid = self.start()
        self.answer(wid, RELEVANT)
        self.answer(wid, RELEVANT)
        result = sp.collect(self.root, sid)
        self.assertEqual(
            [d["recorded_path"] for d in result["documents"]], ["a.md", "b.md"]
        )

    def test_no_rejected_and_an_order_notice_in_the_output(self):
        sid, wid = self.start()
        self.answer(wid, NOT_RELEVANT)
        self.answer(wid, NOT_RELEVANT)
        result = sp.collect(self.root, sid)
        self.assertNotIn("rejected", result)
        self.assertNotIn("rejected_notice", result)
        self.assertIn("関連度の順ではない", result["order_notice"])

    def test_all_no_answers_are_a_normal_zero_result(self):
        sid, wid = self.start()
        self.answer(wid, NOT_RELEVANT)
        self.answer(wid, NOT_RELEVANT)
        self.assertEqual(sp.collect(self.root, sid)["documents"], [])

    def test_a_search_with_no_documents_is_a_normal_zero_result(self):
        self.build(paths=())
        payload = sp.prepare(self.root, KEY, None, TASK)
        self.assertEqual(payload["workers"], [])
        self.assertEqual(sp.collect(self.root, payload["search_id"])["documents"], [])

    def test_a_worker_with_unanswered_documents_fails_the_search(self):
        sid, wid = self.start()
        self.answer(wid, RELEVANT)
        with self.assertRaises(sp.SearchFailed) as caught:
            sp.collect(self.root, sid)
        self.assertTrue(any(wid in e and "1 件" in e for e in caught.exception.errors))

    def test_a_worker_with_no_answers_fails_the_search_even_if_others_finished(self):
        payload = self.fix_multi()
        sid = payload["search_id"]
        first, second = payload["workers"]
        self.answer(first, RELEVANT)
        with self.assertRaises(sp.SearchFailed) as caught:
            sp.collect(self.root, sid)
        self.assertTrue(any(second in e for e in caught.exception.errors))
        self.assertFalse(any(first in e for e in caught.exception.errors))

    def test_no_answers_at_all_fails_the_search(self):
        sid, _ = self.start()
        with self.assertRaises(sp.SearchFailed):
            sp.collect(self.root, sid)

    def test_collect_of_an_unknown_search_fails(self):
        self.start()
        with self.assertRaises(sp.SearchError):
            sp.collect(self.root, "SEARCH-00000000")
        with self.assertRaises(sp.SearchError):
            sp.collect(self.root, "../etc")

    def test_values_reach_the_result_unchanged(self):
        sid, wid = self.start()
        reason = '改行\nと "引用符" と `バッククォート` と $(x) と 日本語'
        self.answer(wid, {"relevance": "yes", "reason": reason, "headings": [HEAD_A]})
        self.answer(wid, NOT_RELEVANT)
        self.assertEqual(sp.collect(self.root, sid)["documents"][0]["reason"], reason)

    def test_a_broken_answer_file_is_a_search_error(self):
        sid, wid = self.start()
        self.answer(wid, NOT_RELEVANT)
        self.answer(wid, NOT_RELEVANT)
        (self.work_dir() / f"{sid}.w1.answer-0002.json").write_bytes(b"{broken")
        with self.assertRaises(sp.SearchError):
            sp.collect(self.root, sid)


class CleanupTest(SearchTestBase):
    def test_cleanup_removes_item_answer_and_fixed_files(self):
        sid, wid = self.start()
        self.answer(wid, RELEVANT)
        self.answer(wid, NOT_RELEVANT)
        sp.collect(self.root, sid)
        names = self.work_files()
        self.assertTrue(any(".item-" in n for n in names))
        self.assertTrue(any(".answer-" in n for n in names))
        self.assertTrue(any(n.endswith(".fixed.json") for n in names))
        self.assertEqual(sp.cleanup(self.root, sid), len(names))
        self.assertEqual(self.work_files(), [])
        with self.assertRaises(sp.SearchError):
            sp.next_item(self.root, wid)
        self.assertEqual(sp.cleanup(self.root, sid), 0)

    def test_cleanup_does_not_touch_other_searches(self):
        first, first_worker = self.start()
        second_payload = sp.prepare(self.root, KEY, None, TASK)
        second, second_worker = (
            second_payload["search_id"],
            second_payload["workers"][0],
        )
        self.answer(first_worker, NOT_RELEVANT)
        self.answer(second_worker, NOT_RELEVANT)
        sp.cleanup(self.root, first)
        self.assertTrue(self.work_files())
        self.assertTrue(all(n.startswith(second + ".") for n in self.work_files()))
        self.assertEqual(sp.next_item(self.root, second_worker)["answered"], 1)

    def test_cleanup_of_a_malformed_search_id_is_an_error(self):
        with self.assertRaises(sp.SearchError):
            sp.cleanup(self.root, "../etc")


class FindProjectRootTest(SearchTestBase):
    def test_finds_the_root_from_a_subdirectory_and_by_the_environment_variable(self):
        sid = self.fix()["search_id"]
        nested = self.root / "docs" / "deep"
        nested.mkdir(parents=True)
        self.assertEqual(sp.find_project_root(sid, nested), self.root)
        elsewhere = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: elsewhere.rmdir())
        self.assertEqual(
            sp.find_project_root(sid, elsewhere, str(self.root)), self.root
        )

    def test_fails_when_no_work_file_exists_above_the_start(self):
        sid = self.fix()["search_id"]
        elsewhere = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: elsewhere.rmdir())
        with self.assertRaises(sp.SearchError):
            sp.find_project_root(sid, elsewhere)
        with self.assertRaises(sp.SearchError):
            sp.find_project_root("not-a-search-id", self.root)


class PrepareTest(SearchTestBase):
    def test_unknown_choice_and_empty_task_are_rejected(self):
        self.build()
        with self.assertRaises(sp.SearchError):
            sp.prepare(self.root, KEY, None, TASK, "other")
        with self.assertRaises(sp.SearchError):
            sp.prepare(self.root, KEY, None, "")

    def test_stale_search_is_marked_possibly_stale_and_does_not_update_state(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        before = self.snapshot()
        payload = sp.prepare(self.root, KEY, None, TASK, sp.CHOICE_EXISTING)
        self.assertEqual(payload["freshness"], sp.FRESHNESS_POSSIBLY_STALE)
        self.assertIn("反映していない可能性", payload["freshness_notice"])
        self.assertEqual(len(payload["workers"]), 1)
        sid, wid = payload["search_id"], payload["workers"][0]
        self.assertEqual(
            self.fixed_state(sid)["freshness"], sp.FRESHNESS_POSSIBLY_STALE
        )
        self.answer(wid, NOT_RELEVANT)
        self.answer(wid, NOT_RELEVANT)
        result = sp.collect(self.root, sid)
        self.assertEqual(result["freshness"], sp.FRESHNESS_POSSIBLY_STALE)
        self.assertIn("反映していない可能性", result["freshness_notice"])
        self.assertEqual(self.snapshot(), before)


class ConfirmRebuildDetailTest(SearchTestBase):
    """D-061: 再構築の確認は、検索前検査の要約と明細ファイルのパスを返す。"""

    def test_confirm_rebuild_returns_the_summary_and_writes_the_detail(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        payload = sp.prepare(self.root, KEY, None, TASK)
        self.assertEqual(payload["action"], sp.ACTION_CONFIRM_REBUILD)
        for name in ("documents", "sections", "excluded", "excluded_in_toc"):
            self.assertNotIn(name, payload)
        self.assertEqual(payload["scale"]["content_changed"], 1)
        path = Path(payload["detail_path"])
        self.assertTrue(path.is_absolute())
        self.assertEqual(
            path,
            self.root / ".temp" / "doc-link" / "query-docs" / f"detail-{KEY}.json",
        )
        detail = json.loads(path.read_bytes().decode("utf-8"))
        self.assertEqual([d["doc_link_id"] for d in detail["documents"]], [ID_A])

    def test_confirm_rebuild_writes_the_checked_target_to_a_file(self):
        # D-063: 検査に使った[ToC 識別キー]と[Index 対象指定]を、対象指定ファイルへ書いてパスを返す
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        payload = sp.prepare(self.root, KEY, None, TASK)
        path = Path(payload["target_file"])
        self.assertTrue(path.is_absolute())
        self.assertEqual(
            path,
            self.root / ".temp" / "doc-link" / "query-docs" / f"target-{KEY}.json",
        )
        saved = state_store.load_confirmed_toc(self.root, KEY)["target_spec"]
        self.assertEqual(json.loads(path.read_bytes().decode("utf-8")), saved)
        self.assertEqual(
            target_spec.load_target_file(path, self.root),
            TargetSpec.from_dict(saved),
        )

    def test_target_file_holds_the_given_spec_when_one_is_given(self):
        self.build()
        given = TargetSpec(mode=MODE_TARGETS, key=KEY, paths=("a.md",))
        payload = sp.prepare(self.root, KEY, given, TASK)
        self.assertEqual(payload["action"], sp.ACTION_CONFIRM_REBUILD)
        self.assertEqual(
            target_spec.load_target_file(payload["target_file"], self.root), given
        )

    def test_target_file_survives_the_cleanup_of_a_search(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        confirm = sp.prepare(self.root, KEY, None, TASK)
        fixed = sp.prepare(self.root, KEY, None, TASK, sp.CHOICE_EXISTING)
        sp.cleanup(self.root, fixed["search_id"])
        self.assertTrue(Path(confirm["target_file"]).is_file())

    def test_rebuild_with_another_target_is_detected_by_the_file(self):
        # 再構築が別の対象で行われたとき、対象指定ファイルを渡した検索前検査が、黙って検索しない
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        confirm = sp.prepare(self.root, KEY, None, TASK)
        checked = target_spec.load_target_file(confirm["target_file"], self.root)
        self.build(a_text=A_TEXT + "more\n", paths=("a.md",))
        with self.assertRaises(sp.SearchError):
            sp.prepare(self.root, KEY, checked, TASK, sp.CHOICE_REBUILD)
        # 保存済みの指定で検査すると、別の対象の再構築を検出できない（最新と判定する）
        unchecked = sp.prepare(self.root, KEY, None, TASK, sp.CHOICE_REBUILD)
        self.assertEqual(unchecked["action"], sp.ACTION_INVOKE_WORKER)

    def test_unwritable_detail_is_a_failure(self):
        self.build()
        self.write("a.md", A_TEXT + "more\n")
        self.write(".temp/doc-link/query-docs", "not a directory")
        with self.assertRaises(sp.SearchError) as caught:
            sp.prepare(self.root, KEY, None, TASK)
        self.assertTrue(
            any("明細ファイルを書けない" in e for e in caught.exception.errors)
        )


if __name__ == "__main__":
    unittest.main()
