import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "doc-link" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import state_store  # noqa: E402

SKILL = "test-skill"


def make_info(doc_id="ABCDEFGH1234", **overrides):
    info = {
        "doc_link_id": doc_id,
        "path": "docs/a.md",
        "title": "題",
        "purpose": "目的",
        "summary": ["概要1", "概要2"],
        "tasks": ["作業"],
        "keywords": ["キー"],
        "content_hash": "0" * 64,
    }
    info.update(overrides)
    return info


def make_toc(key="main", **overrides):
    toc = {
        "toc_key": key,
        "version": 1,
        "target_spec": {"dirs": ["docs"]},
        "documents": [
            {"doc_link_id": "B", "applied_hash": "b" * 64},
            {"doc_link_id": "A", "applied_hash": "a" * 64},
        ],
        "sections": [
            {
                "doc_link_id": "A",
                "section_id": "S1",
                "heading": "見出し",
                "position": 0,
                "content_hash": "c" * 64,
            }
        ],
        "references": [
            {
                "source_doc_id": "A",
                "source_section_id": None,
                "position": 3,
                "target_doc_id": "B",
                "target_section_id": None,
                "recorded_path": "b.md",
                "recorded_content_hash": None,
                "kind": "document",
                "check": {
                    "scope": "docs",
                    "checked_at": "2026-01-01T00:00:00Z",
                    "result": "match",
                    "found_path": None,
                },
            }
        ],
        "reverse_references": [
            {
                "target_doc_id": "B",
                "target_section_id": None,
                "source_doc_id": "A",
                "source_section_id": None,
            }
        ],
        "last_checks": [
            {"doc_link_id": "A", "checked_at": None, "result": "unprocessed"}
        ],
    }
    toc.update(overrides)
    return toc


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def temp_files(self):
        base = self.root / ".temp"
        return [p for p in base.rglob("*") if p.is_file()] if base.exists() else []

    def save_infos(self, toc, root=None):
        """[確定 ToC]に入れる文書の[文書情報]を保存する（[確定 ToC]の保存の前提）。"""
        for entry in toc["documents"]:
            state_store.save_document_info(
                root or self.root, SKILL, make_info(entry["doc_link_id"])
            )

    def save_toc(self, toc=None, root=None):
        toc = make_toc() if toc is None else toc
        self.save_infos(toc, root)
        return state_store.save_confirmed_toc(root or self.root, SKILL, toc)


class SaveLoadTest(StoreTestCase):
    def test_document_info_roundtrip_one_file_per_document(self):
        state_store.save_document_info(self.root, SKILL, make_info("ID1"))
        state_store.save_document_info(self.root, SKILL, make_info("ID2"))
        self.assertEqual(
            state_store.load_document_info(self.root, "ID1")["doc_link_id"], "ID1"
        )
        files = sorted(
            p.name for p in (self.root / ".doc-link" / "documents").iterdir()
        )
        self.assertEqual(files, ["ID1.json", "ID2.json"])
        self.assertEqual(state_store.list_document_ids(self.root), ["ID1", "ID2"])

    def test_confirmed_toc_roundtrip_one_file_per_key(self):
        self.save_toc(make_toc("k1"))
        self.save_toc(make_toc("k2"))
        loaded = state_store.load_confirmed_toc(self.root, "k1")
        self.assertEqual(loaded["toc_key"], "k1")
        files = sorted(p.name for p in (self.root / ".doc-link" / "tocs").iterdir())
        self.assertEqual(files, ["k1.json", "k2.json"])
        self.assertEqual(state_store.list_toc_keys(self.root), ["k1", "k2"])

    def test_confirmed_toc_with_empty_arrays_roundtrips(self):
        # 参照が 1 件も無い文書集合など、空の配列を持つ[確定 ToC]も保存・読取りできる
        empty = make_toc(
            "empty",
            documents=[],
            sections=[],
            references=[],
            reverse_references=[],
            last_checks=[],
        )
        state_store.save_confirmed_toc(self.root, SKILL, empty)
        self.assertEqual(state_store.load_confirmed_toc(self.root, "empty"), empty)

    def test_confirmed_toc_array_fields_must_be_lists(self):
        for name in (
            "documents",
            "sections",
            "references",
            "reverse_references",
            "last_checks",
        ):
            for bad in ("abc", None, {}, 0):
                with self.subTest(field=name, value=bad):
                    with self.assertRaises(state_store.StateStoreError) as ctx:
                        state_store.save_confirmed_toc(
                            self.root, SKILL, make_toc("bad", **{name: bad})
                        )
                    self.assertEqual(ctx.exception.kind, "invalid")

    def test_document_info_not_inside_toc_and_unknown_fields_rejected(self):
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.save_document_info(self.root, SKILL, make_info(extra="x"))
        self.assertEqual(ctx.exception.kind, "invalid")
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.save_confirmed_toc(
                self.root, SKILL, make_toc(document_infos=[])
            )
        self.assertEqual(ctx.exception.kind, "invalid")

    def test_missing_field_rejected(self):
        info = make_info()
        del info["title"]
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.save_document_info(self.root, SKILL, info)
        self.assertEqual(ctx.exception.kind, "invalid")


class DeterminismTest(StoreTestCase):
    def test_second_save_does_not_rewrite(self):
        self.assertTrue(state_store.save_document_info(self.root, SKILL, make_info()))
        path = state_store.document_info_path(self.root, "ABCDEFGH1234")
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
        before = path.stat().st_mtime_ns
        self.assertFalse(state_store.save_document_info(self.root, SKILL, make_info()))
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertTrue(
            state_store.save_document_info(self.root, SKILL, make_info(title="別"))
        )
        self.assertNotEqual(path.stat().st_mtime_ns, before)

    def test_same_toc_does_not_rewrite(self):
        self.assertTrue(self.save_toc())
        self.assertFalse(self.save_toc())

    def test_same_bytes_regardless_of_order(self):
        other = Path(tempfile.mkdtemp(dir=self.root))
        a = make_info("A")
        b = make_info("B")
        state_store.save_document_info(self.root, SKILL, a)
        state_store.save_document_info(self.root, SKILL, b)
        state_store.save_document_info(other, SKILL, dict(reversed(list(b.items()))))
        state_store.save_document_info(other, SKILL, dict(reversed(list(a.items()))))
        for name in ("A", "B"):
            self.assertEqual(
                state_store.document_info_path(self.root, name).read_bytes(),
                state_store.document_info_path(other, name).read_bytes(),
            )

    def test_toc_set_lists_are_order_independent(self):
        other = Path(tempfile.mkdtemp(dir=self.root))
        toc = make_toc()
        shuffled = make_toc(documents=list(reversed(toc["documents"])))
        self.save_toc(toc)
        self.save_toc(shuffled, other)
        self.assertEqual(
            state_store.confirmed_toc_path(self.root, "main").read_bytes(),
            state_store.confirmed_toc_path(other, "main").read_bytes(),
        )

    def test_last_checks_order_does_not_change_the_bytes(self):
        other = Path(tempfile.mkdtemp(dir=self.root))
        checks = [
            {"doc_link_id": "A", "checked_at": None, "result": "unprocessed"},
            {"doc_link_id": "B", "checked_at": None, "result": "success"},
        ]
        self.save_toc(make_toc(last_checks=checks))
        self.save_toc(make_toc(last_checks=list(reversed(checks))), other)
        self.assertEqual(
            state_store.confirmed_toc_path(self.root, "main").read_bytes(),
            state_store.confirmed_toc_path(other, "main").read_bytes(),
        )
        for name in ("A", "B"):
            self.assertEqual(
                state_store.document_info_path(self.root, name).read_bytes(),
                state_store.document_info_path(other, name).read_bytes(),
            )

    def test_output_format(self):
        state_store.save_document_info(self.root, SKILL, make_info(title="日本語"))
        raw = state_store.document_info_path(self.root, "ABCDEFGH1234").read_bytes()
        text = raw.decode("utf-8")
        self.assertIn("日本語", text)
        self.assertTrue(text.endswith("}\n"))
        self.assertIn('\n  "content_hash"', text)
        keys = [
            line.split('"')[1] for line in text.splitlines() if line.startswith('  "')
        ]
        self.assertEqual(keys, sorted(keys))


class AtomicWriteTest(StoreTestCase):
    def test_replace_failure_keeps_old_file_and_leaves_no_temp(self):
        state_store.save_document_info(self.root, SKILL, make_info())
        path = state_store.document_info_path(self.root, "ABCDEFGH1234")
        old = path.read_bytes()
        with mock.patch("state_store.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(state_store.StateStoreError) as ctx:
                state_store.save_document_info(self.root, SKILL, make_info(title="新"))
        self.assertEqual(ctx.exception.kind, "write")
        self.assertEqual(path.read_bytes(), old)
        self.assertEqual(self.temp_files(), [])

    def test_write_failure_midway_leaves_no_temp_and_no_target(self):
        self.save_infos(make_toc())
        with mock.patch("state_store.os.fsync", side_effect=OSError("disk")):
            with self.assertRaises(state_store.StateStoreError) as ctx:
                state_store.save_confirmed_toc(self.root, SKILL, make_toc())
        self.assertEqual(ctx.exception.kind, "write")
        self.assertFalse(state_store.confirmed_toc_path(self.root, "main").exists())
        self.assertEqual(self.temp_files(), [])

    def test_temp_file_is_inside_project_temp_dir(self):
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(Path(src))
            real_replace(src, dst)

        with mock.patch("state_store.os.replace", side_effect=spy):
            state_store.save_document_info(self.root, SKILL, make_info())
        self.assertEqual(seen[0].parent, self.root / ".temp" / "doc-link" / SKILL)
        self.assertEqual(self.temp_files(), [])

    def test_invalid_skill_name_rejected(self):
        for bad in ("", "../x", "a/b", ".hidden"):
            with self.assertRaises(state_store.StateStoreError) as ctx:
                state_store.save_document_info(self.root, bad, make_info())
            self.assertEqual(ctx.exception.kind, "invalid")


class ReadFailureTest(StoreTestCase):
    def test_missing(self):
        for load, key in (
            (state_store.load_document_info, "X"),
            (state_store.load_confirmed_toc, "X"),
        ):
            with self.assertRaises(state_store.StateStoreError) as ctx:
                load(self.root, key)
            self.assertEqual(ctx.exception.kind, "missing")

    def test_corrupt_json(self):
        state_store.save_document_info(self.root, SKILL, make_info())
        path = state_store.document_info_path(self.root, "ABCDEFGH1234")
        path.write_bytes(b"{not json")
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.load_document_info(self.root, "ABCDEFGH1234")
        self.assertEqual(ctx.exception.kind, "corrupt")

    def test_corrupt_utf8(self):
        state_store.save_document_info(self.root, SKILL, make_info())
        state_store.document_info_path(self.root, "ABCDEFGH1234").write_bytes(
            b"\xff\xfe"
        )
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.load_document_info(self.root, "ABCDEFGH1234")
        self.assertEqual(ctx.exception.kind, "corrupt")

    def test_corrupt_schema(self):
        self.save_toc()
        state_store.confirmed_toc_path(self.root, "main").write_text(
            '{"toc_key": "main"}'
        )
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.load_confirmed_toc(self.root, "main")
        self.assertEqual(ctx.exception.kind, "corrupt")

    def test_corrupt_last_check_result_of_unhashable_type_is_corrupt(self):
        # result が list・dict でも、TypeError ではなく corrupt（読取り）・invalid（保存）で失敗する
        for bad in ([], {}):
            with self.subTest(bad=bad):
                toc = make_toc(
                    last_checks=[
                        {"doc_link_id": "A", "checked_at": None, "result": bad}
                    ]
                )
                with self.assertRaises(state_store.StateStoreError) as ctx:
                    state_store.save_confirmed_toc(self.root, SKILL, toc)
                self.assertEqual(ctx.exception.kind, "invalid")
                self.save_toc()
                # 最終検査状態は、その文書の[文書情報]のファイルにある
                path = state_store.document_info_path(self.root, "A")
                text = path.read_text(encoding="utf-8").replace(
                    '"result": "unprocessed"', f'"result": {json.dumps(bad)}'
                )
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(state_store.StateStoreError) as ctx:
                    state_store.load_confirmed_toc(self.root, "main")
                self.assertEqual(ctx.exception.kind, "corrupt")

    def test_corrupt_id_mismatch(self):
        state_store.save_document_info(self.root, SKILL, make_info("A"))
        state_store.document_info_path(self.root, "B").parent.mkdir(exist_ok=True)
        state_store.document_info_path(self.root, "B").write_bytes(
            state_store.document_info_path(self.root, "A").read_bytes()
        )
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.load_document_info(self.root, "B")
        self.assertEqual(ctx.exception.kind, "corrupt")

    def test_unreadable_when_path_is_directory(self):
        path = state_store.document_info_path(self.root, "D")
        path.mkdir(parents=True)
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.load_document_info(self.root, "D")
        self.assertEqual(ctx.exception.kind, "unreadable")

    @unittest.skipIf(os.geteuid() == 0, "root は権限で拒否されない")
    def test_unreadable_when_permission_denied(self):
        state_store.save_document_info(self.root, SKILL, make_info())
        path = state_store.document_info_path(self.root, "ABCDEFGH1234")
        path.chmod(0)
        self.addCleanup(path.chmod, stat.S_IRUSR | stat.S_IWUSR)
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.load_document_info(self.root, "ABCDEFGH1234")
        self.assertEqual(ctx.exception.kind, "unreadable")

    def test_list_ignores_files_that_are_not_json(self):
        self.assertEqual(state_store.list_document_ids(self.root), [])
        state_store.save_document_info(self.root, SKILL, make_info("ID1"))
        for directory in (
            self.root / ".doc-link" / "documents",
            self.root / ".doc-link" / "tocs",
        ):
            directory.mkdir(parents=True, exist_ok=True)
            for name in (".DS_Store", "stray.txt", "x.json.orig"):
                (directory / name).write_text("x")
        self.assertEqual(state_store.list_document_ids(self.root), ["ID1"])
        self.assertEqual(state_store.list_toc_keys(self.root), [])


class FileNameMappingTest(StoreTestCase):
    def test_roundtrip_for_awkward_ids(self):
        for value in ("a/b", "..", ".", "日本語", "A b%c", "con:x?*", "a\\b", "\x00"):
            encoded = state_store.encode_name(value)
            self.assertRegex(encoded, r"^[A-Za-z0-9_%-]+$")
            self.assertEqual(state_store.decode_name(encoded), value)

    def test_injective_and_safe_for_save(self):
        ids = ["a/b", "a%2Fb", "..", "日本語"]
        for doc_id in ids:
            state_store.save_document_info(self.root, SKILL, make_info(doc_id))
        self.assertEqual(sorted(state_store.list_document_ids(self.root)), sorted(ids))
        for doc_id in ids:
            self.assertEqual(
                state_store.load_document_info(self.root, doc_id)["doc_link_id"], doc_id
            )
        self.assertEqual(
            [p.parent for p in (self.root / ".doc-link" / "documents").iterdir()],
            [self.root / ".doc-link" / "documents"] * len(ids),
        )

    def test_empty_and_too_long_rejected(self):
        for bad in ("", "x" * 201, "日" * 70):
            with self.assertRaises(state_store.StateStoreError) as ctx:
                state_store.encode_name(bad)
            self.assertEqual(ctx.exception.kind, "invalid")

    def test_case_collision_is_not_silently_overwritten(self):
        state_store.save_document_info(self.root, SKILL, make_info("abc"))
        path_lower = state_store.document_info_path(self.root, "abc")
        # 大文字小文字を区別しない環境を模す: 別 ID の要求が既存ファイルに当たる
        with mock.patch("state_store.document_info_path", return_value=path_lower):
            with self.assertRaises(state_store.StateStoreError) as ctx:
                state_store.save_document_info(self.root, SKILL, make_info("ABC"))
        self.assertEqual(ctx.exception.kind, "invalid")
        self.assertEqual(
            state_store.load_document_info(self.root, "abc")["doc_link_id"], "abc"
        )


class DocumentFactsTest(StoreTestCase):
    """文書ごとに決まる値は[文書情報]が持ち、[確定 ToC]のファイルはキーごとに決まる値だけを持つ。"""

    def test_toc_file_holds_only_key_level_values(self):
        self.save_toc()
        stored = json.loads(
            state_store.confirmed_toc_path(self.root, "main").read_text("utf-8")
        )
        self.assertEqual(
            sorted(stored),
            ["documents", "reverse_references", "target_spec", "toc_key", "version"],
        )
        self.assertEqual(stored["documents"], ["A", "B"])
        self.assertEqual(stored["reverse_references"], make_toc()["reverse_references"])

    def test_document_values_are_stored_in_the_document_info(self):
        toc = make_toc()
        self.save_toc(toc)
        info_a = state_store.load_document_info(self.root, "A")
        self.assertEqual(info_a["applied_hash"], "a" * 64)
        self.assertEqual(
            info_a["sections"],
            [
                {
                    "section_id": "S1",
                    "heading": "見出し",
                    "position": 0,
                    "content_hash": "c" * 64,
                }
            ],
        )
        self.assertEqual(len(info_a["references"]), 1)
        self.assertNotIn("source_doc_id", info_a["references"][0])
        self.assertEqual(info_a["references"][0]["target_doc_id"], "B")
        self.assertEqual(
            info_a["last_check"], {"checked_at": None, "result": "unprocessed"}
        )
        info_b = state_store.load_document_info(self.root, "B")
        self.assertEqual(info_b["applied_hash"], "b" * 64)
        self.assertEqual(info_b["sections"], [])
        self.assertEqual(info_b["references"], [])
        self.assertIsNone(info_b["last_check"])

    def test_loaded_toc_is_assembled_from_the_document_infos(self):
        toc = make_toc()
        self.save_toc(toc)
        loaded = state_store.load_confirmed_toc(self.root, "main")
        self.assertEqual(sorted(loaded), sorted(state_store.CONFIRMED_TOC_FIELDS))
        for name in ("documents", "sections", "references", "last_checks"):
            self.assertCountEqual(loaded[name], toc[name])
        self.assertEqual(loaded["reverse_references"], toc["reverse_references"])
        self.assertEqual(loaded["version"], 1)
        self.assertEqual(loaded["target_spec"], toc["target_spec"])

    def test_value_of_a_shared_document_is_the_same_from_every_key(self):
        self.save_toc(make_toc("one"))
        two = make_toc(
            "two",
            documents=[{"doc_link_id": "A", "applied_hash": "f" * 64}],
            sections=[],
            references=[],
            reverse_references=[],
            last_checks=[],
        )
        state_store.save_confirmed_toc(self.root, SKILL, two)
        for key in ("one", "two"):
            loaded = state_store.load_confirmed_toc(self.root, key)
            applied = {d["doc_link_id"]: d["applied_hash"] for d in loaded["documents"]}
            self.assertEqual(applied["A"], "f" * 64)
            self.assertEqual(
                [s for s in loaded["sections"] if s["doc_link_id"] == "A"], []
            )
        # キーごとに決まる値（所属）は、ほかのキーの保存で変わらない
        one = state_store.load_confirmed_toc(self.root, "one")
        self.assertEqual(sorted(d["doc_link_id"] for d in one["documents"]), ["A", "B"])

    def test_saving_summary_fields_keeps_the_confirmed_values(self):
        self.save_toc()
        state_store.save_document_info(self.root, SKILL, make_info("A", title="新"))
        info = state_store.load_document_info(self.root, "A")
        self.assertEqual(info["title"], "新")
        self.assertEqual(info["applied_hash"], "a" * 64)
        self.assertEqual(len(info["sections"]), 1)
        self.assertEqual(len(info["references"]), 1)

    def test_document_info_not_yet_in_any_toc_has_no_confirmed_values(self):
        state_store.save_document_info(self.root, SKILL, make_info("N"))
        info = state_store.load_document_info(self.root, "N")
        for name, value in state_store.UNCONFIRMED_FACTS.items():
            self.assertEqual(info[name], value)

    def test_partial_confirmed_values_are_rejected(self):
        info = make_info("P", applied_hash="a" * 64)
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.save_document_info(self.root, SKILL, info)
        self.assertEqual(ctx.exception.kind, "invalid")

    def test_saving_a_toc_without_the_document_info_fails_and_writes_nothing(self):
        state_store.save_document_info(self.root, SKILL, make_info("A"))
        before = state_store.document_info_path(self.root, "A").read_bytes()
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.save_confirmed_toc(self.root, SKILL, make_toc())
        self.assertEqual(ctx.exception.kind, "invalid")
        self.assertFalse(state_store.confirmed_toc_path(self.root, "main").exists())
        self.assertEqual(
            state_store.document_info_path(self.root, "A").read_bytes(), before
        )

    def test_values_of_a_document_outside_the_toc_are_rejected(self):
        self.save_infos(make_toc())
        for name, entry in (
            ("sections", {**make_toc()["sections"][0], "doc_link_id": "X"}),
            ("references", {**make_toc()["references"][0], "source_doc_id": "X"}),
            (
                "last_checks",
                {"doc_link_id": "X", "checked_at": None, "result": "success"},
            ),
        ):
            with self.subTest(field=name):
                with self.assertRaises(state_store.StateStoreError) as ctx:
                    state_store.save_confirmed_toc(
                        self.root, SKILL, make_toc(**{name: [entry]})
                    )
                self.assertEqual(ctx.exception.kind, "invalid")
        self.assertFalse(state_store.confirmed_toc_path(self.root, "main").exists())

    def test_failure_while_writing_document_infos_keeps_the_old_toc_file(self):
        self.save_toc()
        old = state_store.confirmed_toc_path(self.root, "main").read_bytes()
        changed = make_toc(
            version=2,
            documents=[
                {"doc_link_id": "B", "applied_hash": "d" * 64},
                {"doc_link_id": "A", "applied_hash": "e" * 64},
            ],
        )
        with mock.patch("state_store.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(state_store.StateStoreError) as ctx:
                state_store.save_confirmed_toc(self.root, SKILL, changed)
        self.assertEqual(ctx.exception.kind, "write")
        self.assertEqual(
            state_store.confirmed_toc_path(self.root, "main").read_bytes(), old
        )
        self.assertEqual(self.temp_files(), [])

    def test_missing_info_of_a_member_is_not_reported_as_an_unbuilt_toc(self):
        self.save_toc()
        state_store.document_info_path(self.root, "B").unlink()
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.load_confirmed_toc(self.root, "main")
        self.assertEqual(ctx.exception.kind, "corrupt")
        self.assertEqual(
            ctx.exception.path, state_store.document_info_path(self.root, "B")
        )

    def test_member_without_confirmed_values_is_corrupt(self):
        self.save_toc()
        path = state_store.document_info_path(self.root, "B")
        path.unlink()
        state_store.save_document_info(self.root, SKILL, make_info("B"))
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.load_confirmed_toc(self.root, "main")
        self.assertEqual(ctx.exception.kind, "corrupt")

    def test_load_all_document_infos(self):
        self.save_toc()
        state_store.save_document_info(self.root, SKILL, make_info("N"))
        infos = state_store.load_all_document_infos(self.root)
        self.assertEqual([info["doc_link_id"] for info in infos], ["A", "B", "N"])


class PreviousFormatTest(StoreTestCase):
    """ひとつ前の保存形式（文書ごとの値を[確定 ToC]のファイルが持つ）を読み、保存で現在の形式に書き直す。"""

    def write_previous(self, toc):
        for entry in toc["documents"]:
            path = state_store.document_info_path(self.root, entry["doc_link_id"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(state_store.serialize(make_info(entry["doc_link_id"])))
        path = state_store.confirmed_toc_path(self.root, toc["toc_key"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(state_store.serialize(toc))

    def test_previous_format_is_read_as_it_is(self):
        toc = make_toc()
        self.write_previous(toc)
        loaded = state_store.load_confirmed_toc(self.root, "main")
        self.assertEqual(loaded, toc)
        info = state_store.load_document_info(self.root, "A")
        self.assertEqual(info["title"], "題")
        for name, value in state_store.UNCONFIRMED_FACTS.items():
            self.assertEqual(info[name], value)

    def test_saving_rewrites_the_previous_format_into_the_current_one(self):
        toc = make_toc()
        self.write_previous(toc)
        loaded = state_store.load_confirmed_toc(self.root, "main")
        self.assertTrue(state_store.save_confirmed_toc(self.root, SKILL, loaded))
        stored = json.loads(
            state_store.confirmed_toc_path(self.root, "main").read_text("utf-8")
        )
        self.assertEqual(stored["documents"], ["A", "B"])
        self.assertNotIn("sections", stored)
        self.assertEqual(
            state_store.load_document_info(self.root, "A")["applied_hash"], "a" * 64
        )
        reloaded = state_store.load_confirmed_toc(self.root, "main")
        for name in ("documents", "sections", "references", "last_checks"):
            self.assertCountEqual(reloaded[name], toc[name])
        self.assertFalse(state_store.save_confirmed_toc(self.root, SKILL, reloaded))

    def test_previous_format_with_a_broken_entry_is_corrupt(self):
        toc = make_toc(sections=[{"doc_link_id": "A"}])
        self.write_previous(toc)
        with self.assertRaises(state_store.StateStoreError) as ctx:
            state_store.load_confirmed_toc(self.root, "main")
        self.assertEqual(ctx.exception.kind, "corrupt")


if __name__ == "__main__":
    unittest.main()
