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

    def test_unknown_document_id_is_abnormal(self):
        sid = self.finish([("DLID-zzzzzzzzzzzz", [])])
        with self.assertRaises(sp.SearchFailed) as caught:
            sp.collect(self.root, sid)
        self.assertTrue(any("DLID-zzzzzzzzzzzz" in e for e in caught.exception.errors))

    def test_unknown_section_id_is_abnormal(self):
        sid = self.finish([(ID_A, ["DLID-00000000s999"])])
        with self.assertRaises(sp.SearchFailed):
            sp.collect(self.root, sid)

    def test_section_of_another_document_is_abnormal(self):
        sid = self.finish([(ID_A, [SEC_B])])
        with self.assertRaises(sp.SearchFailed):
            sp.collect(self.root, sid)

    def test_duplicate_document_is_abnormal(self):
        sid = self.finish([(ID_A, []), (ID_A, [])])
        with self.assertRaises(sp.SearchFailed):
            sp.collect(self.root, sid)

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
