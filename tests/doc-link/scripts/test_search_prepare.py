import json
import sys
import tempfile
import unittest
from pathlib import Path

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
WHEN = "2026-11-13T00:00:00+00:00"
A_TEXT = f"---\ndoc_link_id: {ID_A}\n---\n# A {SEC_A}\n\nbody\n"
B_TEXT = f"---\ndoc_link_id: {ID_B}\n---\n# B {SEC_B}\n"
TASK = '検索のタスク\n"引用" `code`'


class SearchTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def build(self, key=KEY, a_text=A_TEXT, paths=("a.md", "b.md")):
        """[文書情報]と[確定 ToC]を、index-docs が確定した状態として保存する。"""
        self.write("a.md", a_text)
        self.write("b.md", B_TEXT)
        for path, doc_id, title in (("a.md", ID_A, "タイトル A"), ("b.md", ID_B, "B")):
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
        toc_candidate.build_and_publish(self.root, "test", key, spec, cs, results, WHEN)

    def snapshot(self, include_temp=False):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
            and (include_temp or p.relative_to(self.root).parts[0] != ".temp")
        }

    def work_files(self):
        directory = self.root / ".temp" / "doc-link" / "query-docs"
        return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []

    def fix(self):
        self.build()
        return sp.prepare(self.root, KEY, None, TASK)


class FixTest(SearchTestBase):
    def test_fixed_search_has_id_version_and_current_freshness(self):
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

    def test_copy_has_only_the_specified_content(self):
        payload = self.fix()
        request = json.loads(
            Path(sp.request_path(self.root, payload["search_id"])).read_text("utf-8")
        )
        copy_text = Path(request["toc_copy_path"]).read_text("utf-8")
        copy = json.loads(copy_text)
        self.assertEqual(list(copy), ["documents"])
        self.assertEqual([d["doc_link_id"] for d in copy["documents"]], [ID_A, ID_B])
        first = copy["documents"][0]
        self.assertEqual(
            sorted(first),
            [
                "doc_link_id",
                "keywords",
                "purpose",
                "sections",
                "summary",
                "tasks",
                "title",
            ],
        )
        self.assertEqual(first["title"], "タイトル A")
        self.assertEqual(first["purpose"], "目的 タイトル A")
        self.assertEqual(first["summary"], ["概要 タイトル A"])
        self.assertEqual(first["tasks"], ["作業 タイトル A"])
        self.assertEqual(first["keywords"], ["kw-タイトル A"])
        self.assertEqual(first["sections"], [{"section_id": SEC_A, "heading": "A"}])
        # パス・内容ハッシュ・参照関係・検査結果を含まない。
        toc = state_store.load_confirmed_toc(self.root, KEY)
        for forbidden in ("a.md", "b.md", "content_hash", "applied_hash", "references"):
            self.assertNotIn(forbidden, copy_text)
        for entry in toc["documents"]:
            self.assertNotIn(entry["applied_hash"], copy_text)

    def copy_of(self, payload):
        request = json.loads(
            Path(sp.request_path(self.root, payload["search_id"])).read_text("utf-8")
        )
        return Path(request["toc_copy_path"]).read_text("utf-8")

    def test_copy_omits_the_heading_that_has_the_same_text_as_the_title(self):
        # 先頭の見出しのセクション ID は、文書の名前に見え、文書 ID と取り違えられる（Issue #17）。
        # b.md は、タイトルと先頭の見出しが同じ（B）。a.md は違う（タイトル A / A）
        copy_text = self.copy_of(self.fix())
        docs = {d["doc_link_id"]: d for d in json.loads(copy_text)["documents"]}
        self.assertEqual(docs[ID_B]["sections"], [])
        self.assertNotIn(SEC_B, copy_text)
        self.assertEqual(
            docs[ID_A]["sections"], [{"section_id": SEC_A, "heading": "A"}]
        )

    def test_the_omitted_section_is_still_valid_in_the_inspection(self):
        # 写しから外しただけで、固定した状態には残る。提出されたら受理される
        sid = self.fix()["search_id"]
        sp.submit_item(self.root, sid, ID_B, "r", [SEC_B])
        sp.submit_end(self.root, sid, "0")
        result = sp.collect(self.root, sid)
        self.assertEqual(result["rejected"], [])
        self.assertEqual(
            result["documents"][0]["sections"],
            [{"section_id": SEC_B, "heading": "B"}],
        )

    def test_only_the_first_heading_with_the_title_text_is_a_title_heading(self):
        info = {"title": "タイトル"}
        self.assertTrue(
            sp._is_title_heading({"position": 0, "heading": "タイトル"}, info)
        )
        # 先頭でない見出しは、文字列がタイトルと同じでも外さない
        self.assertFalse(
            sp._is_title_heading({"position": 1, "heading": "タイトル"}, info)
        )
        # 先頭の見出しでも、文字列がタイトルと違えば外さない
        self.assertFalse(
            sp._is_title_heading({"position": 0, "heading": "別の見出し"}, info)
        )

    def test_copy_is_written_without_indentation_and_with_short_lines(self):
        payload = self.fix()
        request_text = Path(sp.request_path(self.root, payload["search_id"])).read_text(
            "utf-8"
        )
        copy_text = Path(json.loads(request_text)["toc_copy_path"]).read_text("utf-8")
        copy = json.loads(copy_text)
        lines = copy_text.splitlines()
        # 字下げと、キーの後の空白が無い。
        self.assertFalse([line for line in lines if line[:1].isspace()])
        self.assertNotIn('": ', copy_text)
        # 1 行にせず、1 要素ごとに改行する（worker が Read で読むため、行を長くしない）。
        self.assertGreater(len(lines), len(copy["documents"]))
        # 内容は、字下げのある書き方と同じで、字下げの分だけ小さい。
        indented = json.dumps(copy, ensure_ascii=False, sort_keys=True, indent=2)
        self.assertLess(len(copy_text), len(indented))
        self.assertEqual(json.loads(indented), copy)
        # 写し以外の作業ファイルは、管理状態と同じ書き方のままである。
        self.assertTrue(request_text.startswith('{\n  "'))

    def test_copy_that_cannot_be_encoded_is_a_search_error(self):
        # 単独のサロゲートは UTF-8 にできない。契約外の例外にせず、SearchError にする。
        path = self.root / ".temp" / "doc-link" / "query-docs" / "x.toc.json"
        with self.assertRaises(sp.SearchError):
            sp._write(self.root, path, {"documents": ["\ud800"]}, compact=True)
        self.assertFalse(path.exists())

    def test_version_is_fixed_even_if_toc_is_updated_afterwards(self):
        payload = self.fix()
        fixed_version = payload["toc_version"]
        self.build(a_text=A_TEXT + "changed\n")
        self.assertNotEqual(
            state_store.load_confirmed_toc(self.root, KEY)["version"], fixed_version
        )
        sp.submit_item(self.root, payload["search_id"], ID_A, "r", [])
        sp.submit_end(self.root, payload["search_id"], "0")
        result = sp.collect(self.root, payload["search_id"])
        self.assertEqual(result["toc_version"], fixed_version)

    def test_unreadable_document_info_is_an_error(self):
        self.build()
        state_store.document_info_path(self.root, ID_B).write_bytes(b"{broken")
        with self.assertRaises(sp.SearchError):
            sp._fix(self.root, KEY, TASK, sp.FRESHNESS_CURRENT, "up_to_date")


class ExchangeTest(SearchTestBase):
    def test_request_is_published_last_and_carries_only_identifiers_and_values(self):
        payload = self.fix()
        sid = payload["search_id"]
        path = Path(sp.request_path(self.root, sid))
        self.assertTrue(path.is_absolute())
        self.assertEqual(
            path.parent, (self.root / ".temp/doc-link/query-docs").resolve()
        )
        request = json.loads(path.read_text("utf-8"))
        self.assertEqual(
            sorted(request), ["search_id", "task", "toc_copy_path", "toc_key"]
        )
        self.assertEqual(request["task"], TASK)
        self.assertEqual(request["toc_key"], KEY)
        self.assertTrue(Path(request["toc_copy_path"]).is_absolute())
        self.assertTrue(Path(request["toc_copy_path"]).is_file())
        self.assertFalse(any(name.endswith(".tmp") for name in self.work_files()))

    def test_request_path_fails_when_not_published_or_unknown(self):
        self.build()
        with self.assertRaises(sp.SearchError):
            sp.request_path(self.root, "SEARCH-00000000")
        with self.assertRaises(sp.SearchError):
            sp.request_path(self.root, "../etc")
        payload = sp.prepare(self.root, KEY, None, TASK)
        sid = payload["search_id"]
        (self.root / ".temp/doc-link/query-docs" / f"{sid}.request.json").unlink()
        with self.assertRaises(sp.SearchError):
            sp.request_path(self.root, sid)

    def test_values_reach_the_result_unchanged(self):
        sid = self.fix()["search_id"]
        reason = '改行\nと "引用符" と `バッククォート` と $(x) と 日本語'
        sp.submit_item(self.root, sid, ID_A, reason, [SEC_A])
        sp.submit_end(self.root, sid, "0")
        result = sp.collect(self.root, sid)
        self.assertEqual(result["documents"][0]["reason"], reason)

    def test_collect_returns_ordered_documents_with_recorded_path_and_sections(self):
        sid = self.fix()["search_id"]
        sp.submit_item(self.root, sid, ID_B, "rb", [])
        sp.submit_item(self.root, sid, ID_A, "ra", [SEC_A])
        sp.submit_end(self.root, sid, "0")
        result = sp.collect(self.root, sid)
        self.assertEqual(
            result["documents"],
            [
                {
                    "doc_link_id": ID_B,
                    "recorded_path": "b.md",
                    "reason": "rb",
                    "sections": [],
                },
                {
                    "doc_link_id": ID_A,
                    "recorded_path": "a.md",
                    "reason": "ra",
                    "sections": [{"section_id": SEC_A, "heading": "A"}],
                },
            ],
        )
        self.assertEqual(result["toc_key"], KEY)
        self.assertEqual(result["freshness"], sp.FRESHNESS_CURRENT)
        self.assertIn("実体パス", result["path_notice"])

    def test_zero_documents_with_exit_value_0_is_a_normal_result(self):
        sid = self.fix()["search_id"]
        sp.submit_end(self.root, sid, "0")
        self.assertEqual(sp.collect(self.root, sid)["documents"], [])

    def test_cleanup_removes_request_result_and_copy(self):
        sid = self.fix()["search_id"]
        sp.submit_item(self.root, sid, ID_A, "r", [])
        sp.submit_end(self.root, sid, "0")
        self.assertTrue(self.work_files())
        sp.collect(self.root, sid)
        self.assertEqual(sp.cleanup(self.root, sid), len(self.work_files()) + 5)
        self.assertEqual(self.work_files(), [])
        with self.assertRaises(sp.SearchError):
            sp.request_path(self.root, sid)

    def test_cleanup_does_not_touch_other_searches(self):
        first = self.fix()["search_id"]
        second = sp.prepare(self.root, KEY, None, TASK)["search_id"]
        sp.cleanup(self.root, first)
        self.assertTrue(sp.request_path(self.root, second))

    def test_result_cannot_be_overwritten_or_extended_after_end(self):
        sid = self.fix()["search_id"]
        sp.submit_end(self.root, sid, "0")
        with self.assertRaises(sp.SearchError):
            sp.submit_end(self.root, sid, "0")
        with self.assertRaises(sp.SearchError):
            sp.submit_item(self.root, sid, ID_A, "r", [])


class InspectionTest(SearchTestBase):
    def finish(self, items, exit_value="0"):
        sid = self.fix()["search_id"]
        for doc_id, sections in items:
            sp.submit_item(self.root, sid, doc_id, "r", sections)
        if exit_value is not None:
            sp.submit_end(self.root, sid, exit_value)
        return sid

    def rejected_of(self, result):
        return [
            (r["kind"], r["doc_link_id"], r["section_id"]) for r in result["rejected"]
        ]

    def test_clean_result_has_no_rejected_ids(self):
        result = sp.collect(self.root, self.finish([(ID_A, [SEC_A])]))
        self.assertEqual(result["rejected"], [])
        self.assertIsNone(result["rejected_notice"])

    def test_unknown_document_id_is_rejected_and_the_others_are_kept(self):
        # 1 件の誤りで、ほかの正しい結果を失わない。誤りは結果に見える形で返る（Issue #15）
        sid = self.finish([(ID_B, []), (SEC_A, []), (ID_A, [])])
        result = sp.collect(self.root, sid)
        self.assertEqual([d["doc_link_id"] for d in result["documents"]], [ID_B, ID_A])
        self.assertEqual(
            self.rejected_of(result), [("unknown_document_id", SEC_A, None)]
        )
        self.assertIn(SEC_A, result["rejected"][0]["message"])
        self.assertTrue(result["rejected_notice"])

    def test_unknown_section_id_is_rejected_and_its_document_is_kept(self):
        sid = self.finish([(ID_A, ["DLID-00000000s999", SEC_A])])
        result = sp.collect(self.root, sid)
        self.assertEqual(
            result["documents"][0]["sections"],
            [{"section_id": SEC_A, "heading": "A"}],
        )
        self.assertEqual(
            self.rejected_of(result),
            [("unknown_section_id", ID_A, "DLID-00000000s999")],
        )

    def test_section_of_another_document_is_rejected(self):
        result = sp.collect(self.root, self.finish([(ID_A, [SEC_B]), (ID_B, [])]))
        self.assertEqual(
            self.rejected_of(result), [("unknown_section_id", ID_A, SEC_B)]
        )
        self.assertEqual(result["documents"][0]["sections"], [])

    def test_duplicate_document_keeps_the_first_and_rejects_the_rest(self):
        sid = self.finish([(ID_A, [SEC_A]), (ID_A, [])])
        result = sp.collect(self.root, sid)
        self.assertEqual(len(result["documents"]), 1)
        self.assertEqual(
            result["documents"][0]["sections"],
            [{"section_id": SEC_A, "heading": "A"}],
        )
        self.assertEqual(
            self.rejected_of(result), [("duplicate_document_id", ID_A, None)]
        )

    def test_notice_says_a_document_may_be_missing_only_for_an_unknown_document_id(
        self,
    ):
        # 文書が結果に入っている重複・版に無いセクション ID で、文書が漏れたとは言わない
        unknown = sp.collect(self.root, self.finish([(ID_B, []), (SEC_A, [])]))
        self.assertEqual(unknown["rejected_notice"], sp.NOTICE_REJECTED)
        self.assertIn("漏れている可能性", unknown["rejected_notice"])
        for items in (
            [(ID_A, [SEC_A]), (ID_A, [])],
            [(ID_A, ["DLID-00000000s999"])],
        ):
            with self.subTest(items=items):
                result = sp.collect(self.root, self.finish(items))
                self.assertEqual(
                    result["rejected_notice"], sp.NOTICE_REJECTED_DOCUMENTS_KEPT
                )
                self.assertNotIn("漏れている可能性", result["rejected_notice"])
        # 版に無い文書 ID が 1 件でもあれば、ほかの種別と混ざっても文書が漏れた可能性を言う
        mixed = sp.collect(
            self.root,
            self.finish([(ID_A, []), (ID_A, []), (SEC_A, [])]),
        )
        self.assertEqual(mixed["rejected_notice"], sp.NOTICE_REJECTED)

    def test_duplicate_message_says_the_document_is_in_the_result(self):
        result = sp.collect(self.root, self.finish([(ID_A, []), (ID_A, [])]))
        message = result["rejected"][0]["message"]
        self.assertIn(ID_A, message)
        self.assertIn("1 回目", message)

    def test_search_fails_when_no_document_passes_the_inspection(self):
        # 全件が誤りの検索を、関連する文書が無いという正常な 0 件と見分けられるようにする
        sid = self.finish([("DLID-zzzzzzzzzzzz", []), (SEC_A, [])])
        with self.assertRaises(sp.SearchFailed) as caught:
            sp.collect(self.root, sid)
        self.assertTrue(any("DLID-zzzzzzzzzzzz" in e for e in caught.exception.errors))
        self.assertTrue(any(SEC_A in e for e in caught.exception.errors))

    def test_rejected_ids_are_not_completed_or_corrected(self):
        # 文書の先頭の見出しのセクション ID を、所属する文書の ID に読み替えて補わない
        result = sp.collect(self.root, self.finish([(SEC_A, []), (ID_B, [])]))
        self.assertEqual([d["doc_link_id"] for d in result["documents"]], [ID_B])

    def test_missing_exit_value_fails_the_search(self):
        sid = self.finish([(ID_A, [])], exit_value=None)
        with self.assertRaises(sp.SearchFailed) as caught:
            sp.collect(self.root, sid)
        self.assertTrue(any("終了の値" in e for e in caught.exception.errors))

    def test_undefined_exit_value_fails_the_search(self):
        for value in ("1", "", "source_unreadable", "0 "):
            with self.subTest(value=value):
                sid = self.finish([(ID_A, [])], exit_value=value)
                with self.assertRaises(sp.SearchFailed):
                    sp.collect(self.root, sid)


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
        sid = payload["search_id"]
        sp.submit_item(self.root, sid, ID_A, "r", [])
        sp.submit_end(self.root, sid, "0")
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
