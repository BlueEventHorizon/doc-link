import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "_index_docs_base", HERE / "test_index_docs.py"
)
_base = importlib.util.module_from_spec(_spec)
sys.modules["_index_docs_base"] = _base
_spec.loader.exec_module(_base)

Base = _base.Base
ALL = _base.ALL
FIXED = _base.FIXED
ID_A, ID_B, ID_C = _base.ID_A, _base.ID_B, _base.ID_C
index_docs = _base.index_docs
state_store = _base.state_store

FORBIDDEN = ("1.3", "260", "余白", "許容")


def deliver_args(build_id, doc_id, values=None, exit_value="0"):
    values = values or FIXED
    args = ["--build-id", build_id, "--doc-id", doc_id]
    if exit_value is not None:
        args += ["--exit-value", exit_value]
    args.append(f"--purpose={values['purpose']}")
    for name in ("summary", "applicable_tasks", "keywords"):
        for item in values[name]:
            args.append(f"--{name.replace('_', '-')}={item}")
    return args


class ExchangeBase(Base):
    def invoke(self):
        code, result = self.advance("k", ALL)
        self.assertEqual(code, 0, result)
        return result["build_id"], result["batches"]

    def ids(self, batches):
        return [d["doc_link_id"] for d in batches[0]["documents"]]

    def request_path(self, build_id, ids):
        code, result = self.run_main(
            "request",
            "--build-id",
            build_id,
            *[a for i in ids for a in ("--doc-id", i)],
        )
        self.assertEqual(code, 0, result)
        return Path(result["path"])

    def work_files(self):
        base = self.root / ".temp" / "doc-link" / "index-docs"
        return [p for p in base.rglob("*")] if base.is_dir() else []


class RequestTest(ExchangeBase):
    def test_request_is_placed_by_script_and_holds_only_paths_and_limits(self):
        build_id, batches = self.invoke()
        path = self.request_path(build_id, self.ids(batches))
        self.assertTrue(path.is_absolute())
        self.assertTrue(path.is_file())
        request = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(request), {"documents"})
        documents = request["documents"]
        self.assertEqual([d["doc_link_id"] for d in documents], [ID_A, ID_B, ID_C])
        for document in documents:
            self.assertEqual(set(document), {"doc_link_id", "path", "limits"})
            self.assertTrue(Path(document["path"]).is_absolute())
            self.assertTrue(Path(document["path"]).is_file())
            self.assertEqual(
                document["limits"],
                {
                    "purpose": 200,
                    "summary": 10,
                    "applicable_tasks": 10,
                    "keywords": 10,
                },
            )
        text = path.read_text(encoding="utf-8")
        for word in FORBIDDEN:
            self.assertNotIn(word, text)

    def test_request_output_has_only_the_path(self):
        build_id, batches = self.invoke()
        code, result = self.run_main(
            "request",
            "--build-id",
            build_id,
            *[a for i in self.ids(batches) for a in ("--doc-id", i)],
        )
        self.assertEqual(code, 0)
        self.assertEqual(set(result), {"path"})

    def test_same_ids_in_any_order_find_the_same_request(self):
        build_id, batches = self.invoke()
        ids = self.ids(batches)
        self.assertEqual(
            self.request_path(build_id, ids),
            self.request_path(build_id, list(reversed(ids))),
        )

    def test_request_is_not_visible_until_published(self):
        build_id, batches = self.invoke()
        path = self.request_path(build_id, self.ids(batches))
        path.unlink()
        code, result = self.run_main(
            "request",
            "--build-id",
            build_id,
            *[a for i in self.ids(batches) for a in ("--doc-id", i)],
        )
        self.assertEqual(code, 1)
        self.assertTrue(result["errors"])

    def test_unknown_build_or_unrequested_ids_fail_without_a_path(self):
        build_id, _ = self.invoke()
        code, result = self.run_main(
            "request", "--build-id", "BUILD-00000000", "--doc-id", ID_A
        )
        self.assertEqual(code, 1)
        self.assertNotIn("path", result)
        code, result = self.run_main(
            "request", "--build-id", build_id, "--doc-id", ID_A
        )
        self.assertEqual(code, 1)
        self.assertNotIn("path", result)

    def test_no_temporary_file_is_left_beside_the_request(self):
        build_id, batches = self.invoke()
        path = self.request_path(build_id, self.ids(batches))
        self.assertEqual([p.name for p in path.parent.iterdir()], [path.name])


class DeliverTest(ExchangeBase):
    def deliver(self, build_id, doc_id, **kwargs):
        return self.run_main("deliver", *deliver_args(build_id, doc_id, **kwargs))

    def test_deliver_stores_values_unchanged_and_confirms_the_toc(self):
        build_id, batches = self.invoke()
        values = {
            **FIXED,
            "purpose": '改行\nと "引用符" と `backtick` と 日本語',
            "keywords": ["-dash", "k2", "k3", "k4", "k5"],
        }
        for doc_id in self.ids(batches):
            code, result = self.deliver(build_id, doc_id, values=values)
            self.assertEqual(code, 0, result)
            self.assertEqual(result["stored"]["doc_link_id"], doc_id)
        code, result = self.advance("k", ALL, "--build-id", build_id)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "done")
        info = state_store.load_document_info(self.root, ID_A)
        self.assertEqual(info["purpose"], values["purpose"])
        self.assertEqual(info["keywords"], values["keywords"])

    def test_exchange_and_work_state_are_deleted_after_the_build(self):
        build_id, batches = self.invoke()
        self.assertTrue(self.work_files())
        for doc_id in self.ids(batches):
            self.assertEqual(self.deliver(build_id, doc_id)[0], 0)
        self.assertTrue(
            any(p.name.startswith("result-") for p in self.work_files()),
            "結果が置かれていない",
        )
        self.assertEqual(self.advance("k", ALL, "--build-id", build_id)[0], 0)
        self.assertEqual(
            [p for p in self.work_files() if p.is_file()],
            [],
        )

    def assert_generation_failure(self, build_id, doc_id, code, result):
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED, result)
        self.assertEqual(result["stage"], "information")
        self.assertEqual(result["problems"][0]["doc_link_id"], doc_id)
        text = json.dumps(result, ensure_ascii=False)
        for word in FORBIDDEN:
            self.assertNotIn(word, text)

    def _fails_and_the_build_fails(self, exit_value):
        build_id, batches = self.invoke()
        ids = self.ids(batches)
        self.assertEqual(self.deliver(build_id, ids[0])[0], 0)
        code, result = self.deliver(build_id, ids[1], exit_value=exit_value)
        self.assert_generation_failure(build_id, ids[1], code, result)
        # 再試行しない: 失敗を残した文書へ正しい値を渡し直しても、script が拒否し、構築は失敗のまま
        code, result = self.deliver(build_id, ids[1])
        self.assertEqual(code, index_docs.script_output.EXIT_ERROR, result)
        self.assertEqual(
            self.deliver(build_id, ids[2])[0], 0
        )  # ほかの文書の差し込みは止めない
        code, result = self.advance("k", ALL, "--build-id", build_id)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertIn(ids[1], [p["doc_link_id"] for p in result["problems"]])
        self.assertFalse(state_store.confirmed_toc_path(self.root, "k").exists())
        self.assertFalse(
            (self.root / ".doc-link" / "documents").is_dir()
            and any(
                ids[1] in p.name
                for p in (self.root / ".doc-link" / "documents").rglob("*")
            )
        )

    def test_submit_to_a_document_with_a_recorded_failure_is_rejected(self):
        build_id, batches = self.invoke()
        ids = self.ids(batches)
        code, result = self.deliver(build_id, ids[0], exit_value="source_unreadable")
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED, result)
        code, result = self.submit("k", ALL, build_id, ids[0])
        self.assertEqual(code, index_docs.script_output.EXIT_ERROR, result)
        infos = self.root / ".doc-link" / "documents"
        self.assertFalse(
            infos.is_dir() and any(ids[0] in p.name for p in infos.rglob("*"))
        )

    def test_source_unreadable_fails_that_document(self):
        self._fails_and_the_build_fails("source_unreadable")

    def test_undefined_exit_value_fails_that_document(self):
        self._fails_and_the_build_fails("something_else")

    def test_non_zero_looking_exit_value_fails_that_document(self):
        self._fails_and_the_build_fails("1")

    def test_missing_exit_value_fails_that_document(self):
        self._fails_and_the_build_fails(None)

    def test_validation_failure_is_not_retried_and_info_is_not_stored(self):
        build_id, batches = self.invoke()
        ids = self.ids(batches)
        too_long = {**FIXED, "purpose": "あ" * 300}
        code, result = self.deliver(build_id, ids[0], values=too_long)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED, result)
        self.assertEqual(result["problems"][0]["field"], "purpose")
        text = json.dumps(result, ensure_ascii=False)
        for word in FORBIDDEN + ("300",):
            self.assertNotIn(word, text)
        code, result = self.advance("k", ALL, "--build-id", build_id)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertIn(ids[0], [p["doc_link_id"] for p in result["problems"]])
        self.assertFalse(state_store.confirmed_toc_path(self.root, "k").exists())
        self.assertEqual(
            [p for p in self.work_files() if p.is_file()],
            [],
        )

    def test_document_outside_the_request_is_rejected(self):
        build_id, _ = self.invoke()
        code, result = self.deliver(build_id, "DLID-zzzzzzzzzzzz")
        self.assertEqual(code, 1)
        self.assertTrue(result["errors"])

    def test_unknown_build_id_is_rejected(self):
        code, result = self.deliver("BUILD-00000000", ID_A)
        self.assertEqual(code, 1)

    def test_deliver_twice_is_rejected_without_overwriting(self):
        build_id, batches = self.invoke()
        doc_id = self.ids(batches)[0]
        self.assertEqual(self.deliver(build_id, doc_id)[0], 0)
        code, _ = self.deliver(
            build_id, doc_id, values={**FIXED, "purpose": "書き換え"}
        )
        self.assertEqual(code, 1)
        for other in self.ids(batches)[1:]:
            self.deliver(build_id, other)
        self.advance("k", ALL, "--build-id", build_id)
        self.assertEqual(
            state_store.load_document_info(self.root, doc_id)["purpose"],
            FIXED["purpose"],
        )


class NextWaveTest(ExchangeBase):
    def test_previous_wave_exchange_is_deleted_when_the_next_wave_is_issued(self):
        paths = []
        for i in range(12):
            path = f"docs/d{i:02d}/f.md"
            doc_id = f"DLID-w{i:02d}000000000"[:17]
            self.write(path, f"---\ndoc_link_id: {doc_id}\n---\n# F\n")
            paths.append(path)
        code, first = self.advance("k", paths)
        self.assertEqual(code, 0, first)
        build_id = first["build_id"]
        first_requests = sorted(
            p.name for p in self.work_files() if p.name.startswith("request-")
        )
        self.assertTrue(first_requests)
        for batch in first["batches"]:
            for document in batch["documents"]:
                self.assertEqual(
                    self.run_main(
                        "deliver", *deliver_args(build_id, document["doc_link_id"])
                    )[0],
                    0,
                )
        code, second = self.advance("k", paths, "--build-id", build_id)
        self.assertEqual(code, 0, second)
        self.assertEqual(second["action"], "invoke_toc_updater")
        second_requests = sorted(
            p.name for p in self.work_files() if p.name.startswith("request-")
        )
        self.assertTrue(second_requests)
        self.assertFalse(set(first_requests) & set(second_requests))
        self.assertFalse([p for p in self.work_files() if p.name.startswith("result-")])


class DefinitionsTest(unittest.TestCase):
    def test_script_docstring_and_messages_do_not_leak_internals_in_requests(self):
        # 依頼の中身を組み立てる関数は、記述上限 L だけを持つ
        source = Path(index_docs.__file__).read_text(encoding="utf-8")
        match = re.search(r"def _write_requests.*?\n\n\ndef ", source, re.DOTALL)
        self.assertIsNotNone(match)
        for word in ("1.3", "260", "余白", "許容"):
            self.assertNotIn(word, match.group(0))


if __name__ == "__main__":
    unittest.main()
