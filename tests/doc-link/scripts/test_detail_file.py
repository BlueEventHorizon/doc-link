import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import detail_file  # noqa: E402
import state_store  # noqa: E402

SKILL = "check-links"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def files(self):
        return sorted(
            str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file()
        )


class PathTest(Base):
    def test_path_is_under_the_skill_work_directory(self):
        self.assertEqual(
            detail_file.detail_path(self.root, SKILL, "specs"),
            self.root / ".temp" / "doc-link" / "check-links" / "detail-specs.json",
        )

    def test_key_is_encoded(self):
        path = detail_file.detail_path(self.root, SKILL, "a/b c")
        self.assertEqual(path.parent, self.root / ".temp" / "doc-link" / "check-links")
        self.assertEqual(path.name, f"detail-{state_store.encode_name('a/b c')}.json")
        self.assertNotIn("/", path.name)

    def test_skill_and_key_separate_the_files(self):
        paths = {
            detail_file.detail_path(self.root, skill, key)
            for skill in ("check-links", "check-toc")
            for key in ("a", "b")
        }
        self.assertEqual(len(paths), 4)


class WriteTest(Base):
    def test_returns_the_absolute_path_and_writes_the_detail(self):
        detail = {"findings": [{"line": 1, "見出し": "日本語"}]}
        path = detail_file.write_detail(self.root, SKILL, "k", detail)
        self.assertTrue(Path(path).is_absolute())
        self.assertEqual(Path(path), detail_file.detail_path(self.root, SKILL, "k"))
        self.assertEqual(json.loads(Path(path).read_bytes().decode("utf-8")), detail)
        self.assertEqual(Path(path).read_bytes(), state_store.serialize(detail))

    def test_empty_detail_is_written(self):
        path = detail_file.write_detail(self.root, SKILL, "k", {"findings": []})
        self.assertEqual(
            json.loads(Path(path).read_bytes().decode("utf-8")), {"findings": []}
        )

    def test_next_run_replaces_the_file_and_leaves_no_temporary_file(self):
        detail_file.write_detail(self.root, SKILL, "k", {"findings": [1, 2]})
        path = detail_file.write_detail(self.root, SKILL, "k", {"findings": []})
        self.assertEqual(
            json.loads(Path(path).read_bytes().decode("utf-8")), {"findings": []}
        )
        self.assertEqual(self.files(), [".temp/doc-link/check-links/detail-k.json"])

    def test_writes_only_under_the_work_directory(self):
        (self.root / "doc.md").write_text("# T\n", encoding="utf-8")
        detail_file.write_detail(self.root, SKILL, "k", {})
        self.assertEqual(
            self.files(), [".temp/doc-link/check-links/detail-k.json", "doc.md"]
        )

    def test_unwritable_place_raises(self):
        blocker = self.root / ".temp" / "doc-link"
        blocker.mkdir(parents=True)
        (blocker / SKILL).write_text("not a directory", encoding="utf-8")
        with self.assertRaises(state_store.StateStoreError):
            detail_file.write_detail(self.root, SKILL, "k", {})


class EmitTest(Base):
    def emit(self, summary, detail):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = detail_file.emit_with_detail(self.root, SKILL, "k", summary, detail)
        return code, json.loads(out.getvalue())

    def test_summary_gets_the_detail_path_and_not_the_detail(self):
        code, result = self.emit({"counts": {"findings": 2}}, {"findings": [1, 2]})
        self.assertEqual(code, 0)
        self.assertEqual(set(result), {"counts", "detail_path"})
        self.assertEqual(
            json.loads(Path(result["detail_path"]).read_bytes().decode("utf-8")),
            {"findings": [1, 2]},
        )

    def test_unwritable_detail_returns_errors_and_1_without_the_summary(self):
        blocker = self.root / ".temp" / "doc-link"
        blocker.mkdir(parents=True)
        (blocker / SKILL).write_text("not a directory", encoding="utf-8")
        code, result = self.emit({"counts": {"findings": 2}}, {"findings": [1, 2]})
        self.assertEqual(code, 1)
        self.assertEqual(set(result), {"errors"})
        self.assertTrue(any("明細ファイルを書けない" in e for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
