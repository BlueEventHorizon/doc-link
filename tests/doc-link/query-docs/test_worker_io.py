"""`query-worker` の入口（ラッパー `worker_io.py`）のテスト。

引数は、サブコマンド（`next`・`answer`）と担当の識別値だけで、プロジェクトのルートは作業ディレクトリから探す。
文書は 1 件ずつ受け取り、答えは標準入力の JSON で渡す。形式が合わない・見出しを引き当てられない答えは、何も保存されず、
同じ文書に答え直せる（Issue #19）。
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_query_docs import (  # noqa: E402
    HEAD_A,
    HEAD_B,
    ID_A,
    ID_B,
    TITLE_A,
    TITLE_B,
    QueryTestBase,
    worker_io,
)


class WorkerIoTest(QueryTestBase):
    def start(self):
        """検索を固定し、担当の識別値を返す（文書が少ないので担当は 1 つ。文書は a.md、b.md の順）。"""
        self.build()
        prepared = self.prepare()[1]
        self.assertEqual(len(prepared["workers"]), 1)
        return prepared["workers"][0]

    def answer_files(self):
        directory = self.root / ".temp" / "doc-link" / "query-docs"
        return [p for p in directory.iterdir() if ".answer-" in p.name]

    def item(self, step):
        return json.loads(Path(step["item_path"]).read_text(encoding="utf-8"))

    def test_next_returns_the_first_item_and_does_not_advance_until_answered(self):
        wid = self.start()
        code, first = self.worker("next", wid)
        self.assertEqual(code, 0)
        self.assertEqual(
            (first["done"], first["answered"], first["total"]), (False, 0, 2)
        )
        self.assertTrue(Path(first["item_path"]).is_absolute())
        self.assertEqual(self.worker("next", wid), (0, first))  # 何度呼んでも同じ文書
        item = self.item(first)
        self.assertEqual(item["title"], TITLE_A)
        self.assertEqual((item["position"], item["total"]), (1, 2))
        self.assertEqual(item["sections"], [HEAD_A])
        # 依頼は ID・パス・番号を持たない（検索 AI が書き写さない）
        self.assertEqual(
            sorted(item),
            [
                "keywords",
                "position",
                "purpose",
                "sections",
                "summary",
                "task",
                "tasks",
                "title",
                "total",
            ],
        )
        text = Path(first["item_path"]).read_text(encoding="utf-8")
        self.assertNotIn("DLID-", text)

    def test_answering_every_document_ends_with_done_and_no_more_answers(self):
        wid = self.start()
        code, stored = self.answer(wid, {"relevance": "no"})
        self.assertEqual(code, 0)
        self.assertEqual(stored["stored"], {"position": 1, "total": 2})
        self.assertFalse(stored["done"])
        self.assertEqual(self.item(stored)["title"], TITLE_B)
        self.assertEqual(self.worker("next", wid)[1]["item_path"], stored["item_path"])
        code, last = self.answer(wid, {"relevance": "no"})
        self.assertEqual(code, 0)
        self.assertEqual(last["stored"], {"position": 2, "total": 2})
        self.assertEqual(
            (last["done"], last["item_path"], last["answered"]), (True, None, 2)
        )
        code, again = self.worker("next", wid)
        self.assertEqual((code, again["done"], again["item_path"]), (0, True, None))
        code, extra = self.answer(wid, {"relevance": "no"})
        self.assertEqual(code, 1)  # すべて答えたあとは受け取らない
        self.assertTrue(extra["errors"])
        self.assertEqual(len(self.answer_files()), 2)
        # 関連する文書が 0 件でも、全部に答えていれば正常な結果である
        sid = wid.rsplit("-", 1)[0]
        code, found = self.run_main("collect", "--search-id", sid)
        self.assertEqual((code, found["documents"]), (0, []))

    def test_answer_goes_to_the_document_the_script_holds(self):
        wid = self.start()
        self.assertEqual(
            self.answer(wid, {"relevance": "yes", "reason": "1", "headings": [HEAD_A]})[
                0
            ],
            0,
        )
        self.assertEqual(
            self.answer(
                wid, {"relevance": "maybe", "reason": "2", "headings": [HEAD_B]}
            )[0],
            0,
        )
        sid = wid.rsplit("-", 1)[0]
        code, found = self.run_main("collect", "--search-id", sid)
        self.assertEqual(code, 0)
        self.assertEqual(
            [
                (d["doc_link_id"], d["relevance"], d["reason"])
                for d in found["documents"]
            ],
            [(ID_A, "yes", "1"), (ID_B, "maybe", "2")],  # 担当内はパスの昇順
        )
        self.assertEqual(
            [s["heading"] for s in found["documents"][1]["sections"]], [HEAD_B]
        )

    def test_malformed_answers_exit_1_store_nothing_and_leave_the_search_failing(self):
        wid = self.start()
        cases = {
            "empty": "",
            "unreadable": '{"relevance": ',
            "not an object": "[]",
            "relevance missing": "{}",
            "relevance uppercase": '{"relevance": "YES", "reason": "r"}',
            "relevance a boolean": '{"relevance": true, "reason": "r"}',
            "relevance null": '{"relevance": null}',
            "relevance an unknown word": '{"relevance": "unknown"}',
            "old relevant key": '{"relevant": true, "reason": "r"}',
            "reason missing for yes": '{"relevance": "yes"}',
            "reason missing for maybe": '{"relevance": "maybe"}',
            "reason on no": '{"relevance": "no", "reason": "x"}',
            "unknown key": '{"relevance": "yes", "reason": "r", "title": "t"}',
            "headings not an array": '{"relevance": "yes", "reason": "r", "headings": "A"}',
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                code, result = self.worker("answer", wid, text)
                self.assertEqual(code, 1)
                self.assertTrue(result["errors"])
                self.assertEqual(self.answer_files(), [])
        self.assertEqual(self.worker("next", wid)[1]["answered"], 0)
        code, _ = self.run_main("collect", "--search-id", wid.rsplit("-", 1)[0])
        self.assertEqual(code, 3)  # 何も保存されていないので、黙った 0 件にならない

    def test_invalid_relevance_can_be_redone_on_the_same_document(self):
        wid = self.start()
        code, result = self.answer(wid, {"relevance": "YES", "reason": "r"})
        self.assertEqual(code, 1)
        self.assertTrue(result["errors"])
        self.assertEqual(self.answer_files(), [])
        code, step = self.worker("next", wid)
        self.assertEqual((step["answered"], self.item(step)["title"]), (0, TITLE_A))
        code, stored = self.answer(wid, {"relevance": "maybe", "reason": "r"})
        self.assertEqual(code, 0)
        self.assertEqual(stored["stored"]["position"], 1)
        self.assertEqual(len(self.answer_files()), 1)

    def test_unresolvable_heading_stores_nothing_lists_candidates_and_can_be_redone(
        self,
    ):
        wid = self.start()
        code, result = self.answer(
            wid, {"relevance": "yes", "reason": "r", "headings": [HEAD_A, "無い見出し"]}
        )
        self.assertEqual(code, 1)
        self.assertTrue(
            any("無い見出し" in e and f'["{HEAD_A}"]' in e for e in result["errors"])
        )
        self.assertEqual(self.answer_files(), [])
        self.assertEqual(self.worker("next", wid)[1]["answered"], 0)
        # 同じ文書に答え直せる（全角半角を正規化した完全一致で引き当てる）
        code, stored = self.answer(
            wid, {"relevance": "yes", "reason": "r", "headings": ["Ａ", HEAD_A]}
        )
        self.assertEqual(code, 0)
        self.assertEqual(stored["stored"]["position"], 1)
        self.assertEqual(len(self.answer_files()), 1)

    def test_accepted_answer_cannot_be_replaced(self):
        wid = self.start()
        self.assertEqual(self.answer(wid, {"relevance": "no"})[0], 0)
        # 次の文書への答えになるだけで、保存済みの答えは変わらない
        self.assertEqual(self.answer(wid, {"relevance": "yes", "reason": "b"})[0], 0)
        found = self.run_main("collect", "--search-id", wid.rsplit("-", 1)[0])[1]
        self.assertEqual([d["doc_link_id"] for d in found["documents"]], [ID_B])

    def test_answer_keeps_special_characters_unchanged(self):
        wid = self.start()
        reason = (
            "改行\nと \"引用符\" と 'apostrophe' と `backtick` と $(x) と \\ と -先頭"
        )
        self.assertEqual(self.answer(wid, {"relevance": "yes", "reason": reason})[0], 0)
        self.assertEqual(self.answer(wid, {"relevance": "no"})[0], 0)
        code, found = self.run_main("collect", "--search-id", wid.rsplit("-", 1)[0])
        self.assertEqual(found["documents"][0]["reason"], reason)

    def test_finds_the_project_root_from_a_subdirectory(self):
        wid = self.start()
        nested = self.root / "docs" / "deep"
        nested.mkdir(parents=True)
        code, step = self.worker("next", wid, start=nested)
        self.assertEqual(code, 0)
        self.assertTrue(Path(step["item_path"]).is_file())
        code, stored = self.worker(
            "answer", wid, json.dumps({"relevance": "no"}), start=nested
        )
        self.assertEqual(code, 0)

    def test_finds_the_project_root_from_the_project_dir_variable(self):
        wid = self.start()
        with tempfile.TemporaryDirectory() as elsewhere:
            code, _ = self.worker("next", wid, start=Path(elsewhere))
            self.assertEqual(code, 1)  # 作業ディレクトリの親には作業ファイルが無い
            code, step = self.worker(
                "next", wid, start=Path(elsewhere), project_dir=str(self.root)
            )
        self.assertEqual(code, 0)
        self.assertFalse(step["done"])

    def test_unknown_or_malformed_worker_id_exits_1(self):
        wid = self.start()
        sid = wid.rsplit("-", 1)[0]
        for bad in (
            "SEARCH-00000000-1",  # 検索が無い
            f"{sid}-9",  # 検索はあるが、その担当が無い
            f"{sid}-0",
            sid,  # 枝番が無い
            "../etc",
        ):
            for command, stdin_text in (
                ("next", ""),
                ("answer", '{"relevance": "no"}'),
            ):
                with self.subTest(worker_id=bad, command=command):
                    code, result = self.worker(command, bad, stdin_text)
                    self.assertEqual(code, 1)
                    self.assertTrue(result["errors"])
        self.assertEqual(self.answer_files(), [])

    def test_main_uses_the_working_directory_and_standard_input(self):
        wid = self.start()
        nested = self.root / "sub"
        nested.mkdir()
        previous = os.getcwd()
        os.chdir(nested)
        self.addCleanup(os.chdir, previous)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = worker_io.main(
                ["answer", wid],
                stdin=io.StringIO(json.dumps({"relevance": "yes", "reason": "r"})),
            )
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(
            json.loads(out.getvalue())["stored"], {"position": 1, "total": 2}
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = worker_io.main(["next", wid])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(json.loads(out.getvalue())["answered"], 1)

    def test_unknown_subcommand_and_missing_arguments_exit_2(self):
        for argv in (
            ["bogus", "SEARCH-00000000-1"],
            ["submit", "SEARCH-00000000-1"],  # 旧サブコマンドは無い
            ["request", "SEARCH-00000000-1"],
            ["next"],
            ["answer"],
            [],
        ):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        worker_io.main(argv)
                self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
