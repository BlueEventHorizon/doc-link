"""プラグイン共通 script `state_store.py`（管理状態の読み書き）の単体テスト。

期待値は DES-002 §4（ファイルの分け方、決定的なバイト列、内容が同じなら書き換えない）、
DES-005 §5（一時ファイルから os.replace）、DES-006 §3（現在パスと所属文書の引き方）、
D-030（全キーの DLID の列挙）から導く。プロジェクトルートはテスト内で作る一時的な
ディレクトリに向け、本リポジトリの `.doc-link/` を作らない。
"""

import json
import os
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "doc-link" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import state_store as ss  # noqa: E402

DOC_A = "DLID-aaaaaaaaaaaa"
DOC_B = "DLID-bbbbbbbbbbbb"
DOC_C = "DLID-cccccccccccc"
SEC_1 = "DLID-111111111111"
SEC_2 = "DLID-222222222222"
SEC_3 = "DLID-333333333333"
SKILL = "index-docs"


def _doc_info(doc_id: str, path: str, title: str = "タイトル") -> ss.DocumentInfo:
    return ss.DocumentInfo(
        doc_link_id=doc_id,
        path=path,
        title=title,
        purpose="目的",
        content_details=["概要1", "概要2"],
        applicable_tasks=["作業"],
        keywords=["キーワード"],
        content_hash="h-" + doc_id,
    )


def _check() -> ss.ReferenceCheck:
    return ss.ReferenceCheck(
        directory="docs",
        checked_at="2026-10-31T00:00:00Z",
        result="match",
        found_paths=["docs/b.md"],
    )


def _key_index(
    key: str, sections: list[ss.SectionEntry], docs: list[str]
) -> ss.KeyIndex:
    return ss.KeyIndex(
        key=key,
        version="v1",
        target_spec={"dirs": ["docs"], "exclude": []},
        check_state=ss.CheckState(status="checked", checked_at="2026-10-31T00:00:00Z"),
        documents=[
            ss.DocumentEntry(doc_link_id=d, reflected_hash="r-" + d) for d in docs
        ],
        sections=sections,
        references=[
            ss.ReferenceEntry(
                source_doc_id=DOC_A,
                source_section_id=None,
                line=10,
                target_id=DOC_B,
                written_path="b.md",
                fragment=None,
                check=_check(),
            ),
            ss.ReferenceEntry(
                source_doc_id=DOC_A,
                source_section_id=SEC_1,
                line=3,
                target_id=SEC_2,
                written_path="b.md",
                fragment="DLID-222222222222",
                check=_check(),
            ),
        ],
    )


def _section(section_id: str, doc_id: str, line: int = 1) -> ss.SectionEntry:
    return ss.SectionEntry(
        section_id=section_id,
        doc_link_id=doc_id,
        heading="見出し",
        line=line,
        section_hash="s-" + section_id,
    )


class _ProjectTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()


class TestDeterministicBytes(_ProjectTestCase):
    def test_same_content_gives_same_bytes_regardless_of_order(self):
        index1 = _key_index(
            "specs", [_section(SEC_1, DOC_A), _section(SEC_2, DOC_B)], [DOC_A, DOC_B]
        )
        index2 = ss.KeyIndex(
            key=index1.key,
            version=index1.version,
            # 辞書の挿入順が違っても同じバイト列になる
            target_spec={"exclude": [], "dirs": ["docs"]},
            check_state=index1.check_state,
            documents=list(reversed(index1.documents)),
            sections=list(reversed(index1.sections)),
            references=list(reversed(index1.references)),
        )
        ss.write_key_index(self.root, SKILL, index1)
        first = ss.key_index_path(self.root, "specs").read_bytes()
        other_root = self.root / "other"
        ss.write_key_index(other_root, SKILL, index2)
        second = ss.key_index_path(other_root, "specs").read_bytes()
        self.assertEqual(first, second)

    def test_serialize_format(self):
        data = {"b": 1, "a": ["日本語", "x"]}
        expected = '{\n  "a": [\n    "日本語",\n    "x"\n  ],\n  "b": 1\n}\n'.encode(
            "utf-8"
        )
        self.assertEqual(ss.serialize(data), expected)
        self.assertEqual(ss.serialize({"a": ["日本語", "x"], "b": 1}), expected)

    def test_document_info_bytes_are_stable(self):
        info = _doc_info(DOC_A, "docs/a.md")
        ss.write_document_info(self.root, SKILL, info)
        first = ss.document_info_path(self.root, DOC_A).read_bytes()
        ss.document_info_path(self.root, DOC_A).unlink()
        ss.write_document_info(self.root, SKILL, info)
        self.assertEqual(ss.document_info_path(self.root, DOC_A).read_bytes(), first)
        # UTF-8 で、非 ASCII を \\u エスケープしない
        self.assertIn("タイトル".encode("utf-8"), first)

    def test_baselines_bytes_are_stable(self):
        entries = [
            ss.Baseline(target_id=DOC_B, source_id=DOC_A, content_hash="x"),
            ss.Baseline(target_id=DOC_A, source_id=None, content_hash="y"),
            ss.Baseline(target_id=DOC_B, source_id=None, content_hash="x"),
        ]
        self.assertEqual(
            ss.serialize(ss._baselines_to_dict(entries)),
            ss.serialize(ss._baselines_to_dict(list(reversed(entries)))),
        )


class TestUnchangedFileIsNotRewritten(_ProjectTestCase):
    def _assert_not_rewritten(self, path: Path, write):
        self.assertTrue(write())
        old = 1_000_000_000
        os.utime(path, ns=(old, old))
        before = path.stat()
        self.assertFalse(write())
        after = path.stat()
        self.assertEqual(after.st_mtime_ns, old)
        self.assertEqual(after.st_ino, before.st_ino)

    def test_document_info(self):
        info = _doc_info(DOC_A, "docs/a.md")
        self._assert_not_rewritten(
            ss.document_info_path(self.root, DOC_A),
            lambda: ss.write_document_info(self.root, SKILL, info),
        )

    def test_key_index(self):
        index = _key_index("specs", [_section(SEC_1, DOC_A)], [DOC_A])
        self._assert_not_rewritten(
            ss.key_index_path(self.root, "specs"),
            lambda: ss.write_key_index(self.root, SKILL, index),
        )

    def test_baselines(self):
        entries = [ss.Baseline(target_id=DOC_A, source_id=None, content_hash="y")]
        self._assert_not_rewritten(
            ss.baselines_path(self.root),
            lambda: ss.write_baselines(self.root, SKILL, entries),
        )

    def test_changed_content_is_rewritten(self):
        ss.write_document_info(self.root, SKILL, _doc_info(DOC_A, "docs/a.md"))
        self.assertTrue(
            ss.write_document_info(self.root, SKILL, _doc_info(DOC_A, "docs/moved.md"))
        )
        self.assertEqual(ss.lookup_document_path(self.root, DOC_A), "docs/moved.md")


class TestTemporaryFilePlacement(_ProjectTestCase):
    def test_temp_files_are_only_created_under_temp_skill_dir(self):
        created = []
        replaced = []
        real_mkstemp = tempfile.mkstemp
        real_replace = os.replace

        def spy_mkstemp(*args, **kwargs):
            fd, name = real_mkstemp(*args, **kwargs)
            created.append(Path(name))
            return fd, name

        def spy_replace(src, dst):
            replaced.append(Path(src))
            return real_replace(src, dst)

        with (
            mock.patch.object(ss.tempfile, "mkstemp", side_effect=spy_mkstemp),
            mock.patch.object(ss.os, "replace", side_effect=spy_replace),
        ):
            ss.write_document_info(self.root, SKILL, _doc_info(DOC_A, "docs/a.md"))
            ss.write_key_index(
                self.root, SKILL, _key_index("specs", [_section(SEC_1, DOC_A)], [DOC_A])
            )
            ss.write_baselines(
                self.root,
                SKILL,
                [ss.Baseline(target_id=DOC_A, source_id=None, content_hash="y")],
            )

        expected_dir = self.root / ".temp" / "doc-link" / SKILL
        self.assertEqual(len(created), 3)
        self.assertEqual(created, replaced)
        for path in created:
            self.assertEqual(path.resolve().parent, expected_dir)
            self.assertTrue(path.resolve().is_relative_to(self.root))
        # 一時ファイルは置き換えで消え、置き場に残らない
        self.assertEqual(list(expected_dir.iterdir()), [])

    def test_mkstemp_is_given_the_project_temp_dir(self):
        # dir を渡さないと OS の一時ディレクトリに作られる。dir が置き場であることを確かめる
        with mock.patch.object(ss.tempfile, "mkstemp", wraps=tempfile.mkstemp) as spy:
            ss.write_document_info(self.root, SKILL, _doc_info(DOC_A, "docs/a.md"))
        self.assertEqual(
            Path(spy.call_args.kwargs["dir"]), self.root / ".temp" / "doc-link" / SKILL
        )

    def test_temp_file_is_removed_when_replace_fails(self):
        with mock.patch.object(ss.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                ss.write_document_info(self.root, SKILL, _doc_info(DOC_A, "docs/a.md"))
        self.assertEqual(list((self.root / ".temp" / "doc-link" / SKILL).iterdir()), [])
        self.assertFalse(ss.document_info_path(self.root, DOC_A).exists())

    def test_invalid_skill_names_are_rejected(self):
        for skill in ["", ".", "..", "a/b", "a\\b", "../x"]:
            with self.subTest(skill=skill):
                with self.assertRaises(ValueError):
                    ss.temp_dir(self.root, skill)


class TestFileLayout(_ProjectTestCase):
    def test_paths(self):
        state = self.root / ".doc-link"
        self.assertEqual(
            ss.document_info_path(self.root, DOC_A),
            state / "documents" / (DOC_A + ".json"),
        )
        self.assertEqual(
            ss.key_index_path(self.root, "specs"),
            state / "keys" / "specs-7846086ae9fc.json",
        )
        self.assertEqual(ss.baselines_path(self.root), state / "baselines.json")

    def test_key_filename_matches_docadvisor(self):
        # 期待値は DocAdvisor 0.4.10 の toc_store.resolve_store_dir(key) のディレクトリ名を
        # 実際に計算した値に `.json` を付けたもの
        nfd = unicodedata.normalize("NFD", "プ")
        cases = {
            "specs": "specs-7846086ae9fc.json",
            "Specs": "specs-e1f44367527c.json",
            "rules/all": "rules_all-418beb5e4633.json",
            "仕様": "k-7881d4875013.json",
            "a_b": "a_b-648fa9b31bc7.json",
            "__A--B__": "a--b-9ed872410d6a.json",
            "x" * 50: "x" * 40 + "-77cf12060d47.json",
            "プ": "k-40d0b0b23fd7.json",
            nfd: "k-40d0b0b23fd7.json",
            "all": "all-5ef5ef0364b6.json",
        }
        for key, expected in cases.items():
            with self.subTest(key=key):
                self.assertEqual(ss.key_to_filename(key), expected)

    def test_key_filename_distinguishes_keys_and_is_case_safe(self):
        keys = [
            "specs",
            "Specs",
            "SPECS",
            "a/b",
            "a_b",
            "a.b",
            "a b",
            "仕様",
            "規則",
            "..",
            "%",
            "-_",
        ]
        names = [ss.key_to_filename(k) for k in keys]
        self.assertEqual(len({n.lower() for n in names}), len(keys))
        for name in names:
            self.assertEqual(name, name.lower())
            self.assertNotIn("/", name)
            self.assertNotIn("\\", name)
            self.assertTrue(name.endswith(".json"))

    def test_key_is_restored_from_file_content(self):
        for key in ["a/b", "Specs", "仕様 の キー"]:
            with self.subTest(key=key):
                ss.write_key_index(self.root, SKILL, _key_index(key, [], [DOC_A]))
                path = ss.key_index_path(self.root, key)
                self.assertEqual(path.parent, self.root / ".doc-link" / "keys")
                self.assertEqual(json.loads(path.read_text("utf-8"))["key"], key)
                self.assertEqual(ss.read_key_index(self.root, key).key, key)

    def test_key_is_neither_validated_nor_normalized_here(self):
        # 検証と NFC 化は引数を受け取る側が行う。変換は DocAdvisor の resolve_store_dir と
        # 同じく空キーも変換し、予約キー `all` も受け付ける
        self.assertEqual(ss.key_to_filename(""), "k-e3b0c44298fc.json")
        ss.write_key_index(self.root, SKILL, _key_index("all", [], [DOC_A]))
        self.assertEqual(ss.read_key_index(self.root, "all").key, "all")

    def test_nfc_equivalent_keys_map_to_one_file(self):
        nfc = "プ"
        nfd = unicodedata.normalize("NFD", nfc)
        self.assertEqual(
            ss.key_index_path(self.root, nfd), ss.key_index_path(self.root, nfc)
        )
        # 照合は渡されたキーそのままで行う（NFC 化は呼び出し側の責務）
        ss.write_key_index(self.root, SKILL, _key_index(nfc, [], [DOC_A]))
        with self.assertRaises(ss.StateError):
            ss.read_key_index(self.root, nfd)

    def test_non_dlid_document_id_is_rejected(self):
        for value in ["../x", "DLID-AAAAAAAAAAAA", "foo"]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ss.document_info_path(self.root, value)


class TestRoundTrip(_ProjectTestCase):
    def test_document_info(self):
        info = _doc_info(DOC_A, "docs/a.md")
        ss.write_document_info(self.root, SKILL, info)
        self.assertEqual(ss.read_document_info(self.root, DOC_A), info)

    def test_document_info_field_names_match_docadvisor(self):
        # AI が作るフィールドは DocAdvisor の ToC（formats/toc_format.md の docs）と同じ名前
        ss.write_document_info(self.root, SKILL, _doc_info(DOC_A, "docs/a.md"))
        data = json.loads(ss.document_info_path(self.root, DOC_A).read_text("utf-8"))
        self.assertEqual(
            set(data),
            {
                "doc_link_id",
                "path",
                "title",
                "purpose",
                "content_details",
                "applicable_tasks",
                "keywords",
                "content_hash",
            },
        )

    def test_key_index(self):
        index = _key_index("specs", [_section(SEC_1, DOC_A, 5)], [DOC_A])
        ss.write_key_index(self.root, SKILL, index)
        restored = ss.read_key_index(self.root, "specs")
        self.assertEqual(ss._key_index_to_dict(restored), ss._key_index_to_dict(index))
        # 文書情報を含まない
        data = json.loads(ss.key_index_path(self.root, "specs").read_text("utf-8"))
        self.assertNotIn("title", json.dumps(data))
        self.assertEqual(
            sorted(data),
            [
                "check_state",
                "documents",
                "key",
                "references",
                "sections",
                "target_spec",
                "version",
            ],
        )

    def test_baselines(self):
        entries = [
            ss.Baseline(target_id=DOC_A, source_id=None, content_hash="y"),
            ss.Baseline(target_id=SEC_1, source_id=DOC_B, content_hash="z"),
        ]
        ss.write_baselines(self.root, SKILL, entries)
        # 書き込みは (target_id, source_id) の順に並べる
        self.assertEqual(ss.read_baselines(self.root), list(reversed(entries)))

    def test_duplicate_baseline_pair_is_rejected(self):
        entries = [
            ss.Baseline(target_id=DOC_A, source_id=None, content_hash="y"),
            ss.Baseline(target_id=DOC_A, source_id=None, content_hash="z"),
        ]
        with self.assertRaises(ValueError):
            ss.write_baselines(self.root, SKILL, entries)


class TestMissingAndBrokenState(_ProjectTestCase):
    def test_missing_files_mean_no_record(self):
        self.assertIsNone(ss.read_document_info(self.root, DOC_A))
        self.assertIsNone(ss.read_key_index(self.root, "specs"))
        self.assertEqual(ss.read_baselines(self.root), [])
        self.assertEqual(ss.list_key_indexes(self.root), [])
        self.assertEqual(ss.list_recorded_dlids(self.root), [])
        self.assertIsNone(ss.lookup_document_path(self.root, DOC_A))
        self.assertEqual(ss.lookup_section_documents(self.root, SEC_1), [])
        self.assertFalse((self.root / ".doc-link").exists())

    def _write_raw(self, path: Path, raw: bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def test_broken_json_is_an_error(self):
        self._write_raw(ss.document_info_path(self.root, DOC_A), b"{not json")
        with self.assertRaises(ss.StateError):
            ss.read_document_info(self.root, DOC_A)
        with self.assertRaises(ss.StateError):
            ss.lookup_document_path(self.root, DOC_A)

    def test_non_utf8_is_an_error(self):
        self._write_raw(ss.baselines_path(self.root), b"\xff\xfe")
        with self.assertRaises(ss.StateError):
            ss.read_baselines(self.root)

    def test_wrong_shape_is_an_error(self):
        self._write_raw(ss.key_index_path(self.root, "specs"), b'{"key": "specs"}')
        with self.assertRaises(ss.StateError):
            ss.read_key_index(self.root, "specs")
        with self.assertRaises(ss.StateError):
            ss.list_recorded_dlids(self.root)
        with self.assertRaises(ss.StateError):
            ss.lookup_section_documents(self.root, SEC_1)

    def test_bool_is_not_accepted_as_line(self):
        ss.write_key_index(
            self.root, SKILL, _key_index("specs", [_section(SEC_1, DOC_A)], [DOC_A])
        )
        path = ss.key_index_path(self.root, "specs")
        data = json.loads(path.read_text("utf-8"))
        data["sections"][0]["line"] = True
        path.write_text(json.dumps(data), "utf-8")
        with self.assertRaises(ss.StateError):
            ss.read_key_index(self.root, "specs")

    def test_key_mismatch_with_file_name_is_an_error(self):
        ss.write_key_index(self.root, SKILL, _key_index("specs", [], [DOC_A]))
        path = ss.key_index_path(self.root, "specs")
        data = json.loads(path.read_text("utf-8"))
        data["key"] = "rules"
        path.write_text(json.dumps(data), "utf-8")
        with self.assertRaises(ss.StateError):
            ss.read_key_index(self.root, "specs")
        with self.assertRaises(ss.StateError):
            ss.list_key_indexes(self.root)

    def test_document_id_mismatch_with_file_name_is_an_error(self):
        ss.write_document_info(self.root, SKILL, _doc_info(DOC_A, "docs/a.md"))
        path = ss.document_info_path(self.root, DOC_A)
        data = json.loads(path.read_text("utf-8"))
        data["doc_link_id"] = DOC_B
        path.write_text(json.dumps(data), "utf-8")
        with self.assertRaises(ss.StateError):
            ss.read_document_info(self.root, DOC_A)

    def test_unreadable_file_is_an_error(self):
        path = ss.document_info_path(self.root, DOC_A)
        # ディレクトリはファイルとして読めない（OSError）
        path.mkdir(parents=True)
        with self.assertRaises(ss.StateError):
            ss.read_document_info(self.root, DOC_A)


class TestReadQueries(_ProjectTestCase):
    def setUp(self):
        super().setUp()
        # SEC_2 は specs では DOC_B、rules では DOC_C に所属する（一部のキーだけを再構築した状態）
        ss.write_key_index(
            self.root,
            SKILL,
            _key_index(
                "specs",
                [_section(SEC_1, DOC_A), _section(SEC_2, DOC_B)],
                [DOC_A, DOC_B],
            ),
        )
        ss.write_key_index(
            self.root,
            SKILL,
            _key_index(
                "rules/all", [_section(SEC_2, DOC_C), _section(SEC_3, DOC_C)], [DOC_C]
            ),
        )
        ss.write_document_info(self.root, SKILL, _doc_info(DOC_A, "docs/a.md"))
        ss.write_document_info(self.root, SKILL, _doc_info(DOC_B, "docs/b.md"))
        ss.write_document_info(self.root, SKILL, _doc_info(DOC_C, "rules/c.md"))

    def test_list_recorded_dlids_covers_all_keys(self):
        self.assertEqual(
            ss.list_recorded_dlids(self.root),
            sorted([DOC_A, DOC_B, DOC_C, SEC_1, SEC_2, SEC_3]),
        )

    def test_list_key_indexes(self):
        self.assertEqual(
            [i.key for i in ss.list_key_indexes(self.root)], ["rules/all", "specs"]
        )

    def test_lookup_document_path(self):
        self.assertEqual(ss.lookup_document_path(self.root, DOC_A), "docs/a.md")
        self.assertEqual(ss.lookup_document_path(self.root, DOC_C), "rules/c.md")
        self.assertIsNone(ss.lookup_document_path(self.root, "DLID-dddddddddddd"))

    def test_lookup_section_documents_returns_all_keys(self):
        self.assertEqual(ss.lookup_section_documents(self.root, SEC_1), [DOC_A])
        self.assertEqual(ss.lookup_section_documents(self.root, SEC_2), [DOC_B, DOC_C])
        self.assertEqual(ss.lookup_section_documents(self.root, SEC_3), [DOC_C])
        self.assertEqual(
            ss.lookup_section_documents(self.root, "DLID-dddddddddddd"), []
        )

    def test_reads_do_not_write(self):
        before = {p: p.read_bytes() for p in (self.root / ".doc-link").rglob("*.json")}
        mtimes = {p: p.stat().st_mtime_ns for p in before}
        ss.list_recorded_dlids(self.root)
        ss.lookup_document_path(self.root, DOC_A)
        ss.lookup_section_documents(self.root, SEC_2)
        after = {p: p.read_bytes() for p in (self.root / ".doc-link").rglob("*.json")}
        self.assertEqual(before, after)
        self.assertEqual(mtimes, {p: p.stat().st_mtime_ns for p in after})


if __name__ == "__main__":
    unittest.main()
