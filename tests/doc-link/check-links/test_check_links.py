import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_SCRIPTS_DIR = (
    PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "check-links" / "scripts"
)
sys.path.insert(0, str(SKILL_SCRIPTS_DIR))

import check_links  # noqa: E402
from content_hash import document_content_hash, section_content_hashes  # noqa: E402

DOC_A = "DLID-0123456789ab"
SEC_A1 = "DLID-abcdefghjkmn"
SEC_A2 = "DLID-pqrstvwxyz01"
DOC_B = "DLID-2222222222bb"
SEC_GONE = "DLID-4444444444dd"
DOC_GONE = "DLID-zzzzzzzzzzzz"
DOC_MAIN = "DLID-5555555555ee"
SEC_MAIN = "DLID-6666666666ff"
HASH = "a" * 64

REF_A = f"---\ndoc_link_id: {DOC_A}\n---\n# Alpha {SEC_A1}\n\n## Beta {SEC_A2}\n"
REF_B = f"---\ndoc_link_id: {DOC_B}\n---\n# Bee\n"
REF_PLAIN = "# Plain\n"

MAIN = f"""---
doc_link_id: {DOC_MAIN}
---
# Main {SEC_MAIN}

inline plain [i](../ref/a.md) and inline dlid [j](../ref/a.md "{HASH} {DOC_A}").
external [e](https://example.com/a.md) same doc [s](#main-dlid-6666666666ff)
no id target [n](../ref/plain.md) and missing target [m](../ref/none.md).

[ok]: ../ref/a.md "{DOC_A}"
[ok2]: ../ref/a.md#alpha-dlid-abcdefghjkmn "{HASH} {SEC_A1}"
[moved]: ../ref/b.md "{HASH} {DOC_B}"
[frag]: ../ref/a.md#wrong "{HASH} {SEC_A2}"
[nosec]: ../ref/a.md "{HASH} {SEC_GONE}"
[gone]: ../ref/gone.md "{HASH} {DOC_GONE}"
[nodir]: ../nodir/x.md "{HASH} {DOC_GONE}"
[outside]: ../../x.md "{HASH} {DOC_GONE}"
[plain]: ../ref/a.md "just a title"
[noid]: ../ref/plain.md "title"
[web]: https://example.com/a.md "title"
"""


class CheckLinksTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def snapshot(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }

    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_links.main(["--project-root", str(self.root), *args])
        return code, json.loads(out.getvalue())

    def make_fixture(self):
        self.write("ref/a.md", REF_A)
        self.write("ref/sub/b.md", REF_B)
        self.write("ref/plain.md", REF_PLAIN)
        self.write("src/main.md", MAIN)


class CategoriesTest(CheckLinksTestBase):
    def setUp(self):
        super().setUp()
        self.make_fixture()
        self.before = self.snapshot()
        self.code, self.result = self.run_main("--key", "k", "--paths", "src/main.md")
        self.by_category = {}
        for finding in self.result["findings"]:
            self.by_category.setdefault(finding["category"], []).append(finding)

    def one(self, category):
        self.assertEqual(len(self.by_category.get(category, [])), 1, category)
        return self.by_category[category][0]

    def test_exit_0_even_with_findings(self):
        self.assertEqual(self.code, 0)
        self.assertTrue(self.result["findings"])

    def test_matching_references_are_not_reported(self):
        self.assertEqual(self.result["summary"]["matched_references"], 2)
        reported = {f["dlid"] for f in self.result["findings"] if "dlid" in f}
        self.assertNotIn(SEC_A1, reported)

    def test_path_mismatch_has_current_path(self):
        finding = self.one("path_mismatch")
        self.assertEqual(finding["dlid"], DOC_B)
        self.assertEqual(finding["current_path"], "ref/sub/b.md")
        self.assertEqual(finding["source_path"], "src/main.md")
        self.assertEqual(finding["recorded_hash"], HASH)
        self.assertEqual(finding["line"], 12)

    def test_fragment_mismatch_has_current_anchor(self):
        finding = self.one("fragment_mismatch")
        self.assertEqual(finding["dlid"], SEC_A2)
        self.assertEqual(finding["fragment"], "wrong")
        self.assertEqual(finding["current_anchor"], "beta-dlid-pqrstvwxyz01")

    def test_missing_section_is_distinguished_from_absent(self):
        finding = self.one("missing_section")
        self.assertEqual(finding["dlid"], SEC_GONE)
        self.assertEqual(finding["target_doc_link_id"], DOC_A)
        reasons = sorted(f["absent_reason"] for f in self.by_category["absent"])
        self.assertEqual(reasons, ["directory_missing", "not_found"])
        not_found = next(
            f for f in self.by_category["absent"] if f["absent_reason"] == "not_found"
        )
        self.assertEqual(not_found["resolved_path"], "ref/gone.md")

    def test_unresolved_outside_root(self):
        finding = self.one("unresolved")
        self.assertEqual(finding["unresolved_reason"], "outside_root")

    def test_links_without_dlid_in_definition_and_inline_forms(self):
        found = self.by_category["link_without_dlid"]
        self.assertEqual(sorted(f["kind"] for f in found), ["definition", "inline"])
        for finding in found:
            self.assertEqual(finding["resolved_path"], "ref/a.md")
            self.assertEqual(finding["target_doc_link_id"], DOC_A)

    def test_inline_link_with_dlid_title(self):
        finding = self.one("inline_link_with_dlid")
        self.assertEqual(finding["dlid"], DOC_A)
        self.assertEqual(finding["recorded_hash"], HASH)
        self.assertEqual(finding["line"], 6)

    def test_excluded_links_are_not_reported(self):
        targets = {f["target"] for f in self.by_category["link_without_dlid"]}
        self.assertEqual(targets, {"../ref/a.md"})
        for finding in self.result["findings"]:
            self.assertNotIn("example.com", finding["target"])
            self.assertNotIn("plain.md", finding["target"])

    def test_scope_and_guidance(self):
        scope = self.result["scope"]
        self.assertIn("ref", scope["directories"])
        self.assertTrue(scope["checked_at"])
        guidance = "\n".join(self.result["guidance"])
        self.assertIn("suggested_title", guidance)
        self.assertIn("index-docs", guidance)
        self.assertIn("current_path", guidance)

    def test_writes_nothing(self):
        self.assertEqual(self.snapshot(), self.before)


DOC_C = "DLID-3333333333cc"
REF_C = f'---\ndoc_link_id: {DOC_C}\n---\n# Nodlid\n\n<a id="manual"></a>\n\ntext\n'


class SuggestedTitleTest(CheckLinksTestBase):
    """title に DLID の無いリンクへ添える、title に書く値（DES-007 §1、AC-032）。"""

    def setUp(self):
        super().setUp()
        self.write("ref/a.md", REF_A)
        self.write("ref/c.md", REF_C)

    def findings_of(self, text):
        self.write("src/m.md", text)
        code, result = self.run_main("--key", "k", "--paths", "src/m.md")
        self.assertEqual(code, 0)
        return {
            f["target"]: f
            for f in result["findings"]
            if f["category"] == "link_without_dlid"
        }, result

    def test_document_link_gets_document_hash_and_document_id(self):
        found, _ = self.findings_of("# M\n\n[r]: ../ref/a.md\n")
        expected = f"{document_content_hash(REF_A)} {DOC_A}"
        self.assertEqual(found["../ref/a.md"]["suggested_title"], expected)

    def test_heading_fragment_gets_section_hash_and_section_id(self):
        anchor = "beta-dlid-pqrstvwxyz01"
        found, _ = self.findings_of(f"# M\n\n[r]: ../ref/a.md#{anchor}\n")
        # 見出しの出現順は Alpha, Beta なので、Beta は 2 番目
        expected = f"{section_content_hashes(REF_A)[1]} {SEC_A2}"
        self.assertEqual(found[f"../ref/a.md#{anchor}"]["suggested_title"], expected)

    def test_explicit_anchor_fragment_gets_document_value(self):
        found, _ = self.findings_of("# M\n\n[r]: ../ref/c.md#manual\n")
        expected = f"{document_content_hash(REF_C)} {DOC_C}"
        self.assertEqual(found["../ref/c.md#manual"]["suggested_title"], expected)

    def test_unresolved_fragment_has_reason_and_no_value(self):
        found, _ = self.findings_of("# M\n\n[r]: ../ref/a.md#nowhere\n")
        finding = found["../ref/a.md#nowhere"]
        self.assertNotIn("suggested_title", finding)
        self.assertEqual(
            finding["suggested_title_unavailable_reason"], "fragment_unresolved"
        )

    def test_heading_without_dlid_has_reason_and_no_value(self):
        found, _ = self.findings_of("# M\n\n[r]: ../ref/c.md#nodlid\n")
        finding = found["../ref/c.md#nodlid"]
        self.assertNotIn("suggested_title", finding)
        self.assertEqual(
            finding["suggested_title_unavailable_reason"], "heading_without_dlid"
        )

    def test_inline_link_gets_the_same_value(self):
        found, _ = self.findings_of("# M\n\nsee [x](../ref/a.md).\n")
        expected = f"{document_content_hash(REF_A)} {DOC_A}"
        self.assertEqual(found["../ref/a.md"]["suggested_title"], expected)
        self.assertEqual(found["../ref/a.md"]["kind"], "inline")

    def test_value_comes_from_the_current_file_not_from_managed_state(self):
        found, _ = self.findings_of("# M\n\n[r]: ../ref/a.md\n")
        before = found["../ref/a.md"]["suggested_title"]
        self.write("ref/a.md", REF_A + "\nchanged\n")
        found, _ = self.findings_of("# M\n\n[r]: ../ref/a.md\n")
        self.assertNotEqual(found["../ref/a.md"]["suggested_title"], before)
        self.assertFalse((self.root / ".doc-link").exists())

    def test_writing_the_value_makes_the_reference_formal_and_matched(self):
        found, _ = self.findings_of("# M\n\n[r]: ../ref/a.md\n")
        title = found["../ref/a.md"]["suggested_title"]
        self.write("src/m.md", f'# M\n\n[r]: ../ref/a.md "{title}"\n')
        code, result = self.run_main("--key", "k", "--paths", "src/m.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["summary"]["matched_references"], 1)

    def test_writing_the_section_value_makes_the_reference_matched(self):
        anchor = "beta-dlid-pqrstvwxyz01"
        found, _ = self.findings_of(f"# M\n\n[r]: ../ref/a.md#{anchor}\n")
        title = found[f"../ref/a.md#{anchor}"]["suggested_title"]
        self.write("src/m.md", f'# M\n\n[r]: ../ref/a.md#{anchor} "{title}"\n')
        code, result = self.run_main("--key", "k", "--paths", "src/m.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["summary"]["matched_references"], 1)


class RecordWordTest(CheckLinksTestBase):
    def test_only_64_lowercase_hex_is_read_as_a_record(self):
        words = {
            "ok": "a" * 64,
            "upper": "A" * 64,
            "short": "a" * 63,
            "long": "a" * 65,
            "nonhex": "g" * 64,
            "none": None,
        }
        self.write("ref/a.md", REF_A)
        lines = []
        for index, (name, word) in enumerate(words.items()):
            title = DOC_GONE if word is None else f"{word} {DOC_GONE}"
            lines.append(f'[{name}]: ../ref/gone{index}.md "{title}"')
        self.write("src/m.md", "# M\n\n" + "\n".join(lines) + "\n")
        code, result = self.run_main("--key", "k", "--paths", "src/m.md")
        self.assertEqual(code, 0)
        recorded = {f["resolved_path"]: f["recorded_hash"] for f in result["findings"]}
        expected = {
            f"ref/gone{index}.md": ("a" * 64 if name == "ok" else None)
            for index, name in enumerate(words)
        }
        self.assertEqual(recorded, expected)


class SourceWithoutDocumentIdTest(CheckLinksTestBase):
    def test_links_are_checked_without_a_document_id(self):
        self.write("ref/a.md", REF_A)
        self.write(
            "src/m.md",
            f'# M\n\n[x]: ../ref/gone.md "{DOC_GONE}"\n[y]: ../ref/a.md "plain"\n',
        )
        code, result = self.run_main("--key", "k", "--paths", "src/m.md")
        self.assertEqual(code, 0)
        self.assertEqual(
            sorted(f["category"] for f in result["findings"]),
            ["absent", "link_without_dlid"],
        )


class CleanTest(CheckLinksTestBase):
    def test_no_findings_returns_empty_guidance(self):
        self.write("ref/a.md", REF_A)
        self.write("src/m.md", f'# M\n\n[x]: ../ref/a.md "{HASH} {DOC_A}"\n')
        before = self.snapshot()
        code, result = self.run_main("--key", "k", "--paths", "src/m.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["guidance"], [])
        self.assertEqual(result["summary"]["matched_references"], 1)
        self.assertEqual(self.snapshot(), before)

    def test_directory_target_and_all_mode(self):
        self.make_fixture()
        for args in (("--key", "k", "--dirs", "src"), ()):
            with self.subTest(args=args):
                code, result = self.run_main(*args)
                self.assertEqual(code, 0)
                self.assertTrue(result["findings"])

    def test_missing_target_is_reported_and_processing_continues(self):
        self.write("ref/a.md", REF_A)
        self.write("src/m.md", "# M\n")
        code, result = self.run_main("--key", "k", "--paths", "src/m.md", "nope.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["problems"], [{"path": "nope.md", "reason": "missing"}])


class UnreadableTest(CheckLinksTestBase):
    def test_unreadable_source_and_link_target_are_reported(self):
        self.write("src/m.md", "# M\n\n[i](bad.md)\n")
        (self.root / "src" / "bad.md").write_bytes(b"\xff\xfe\x00bad\n")
        code, result = self.run_main("--key", "k", "--paths", "src/m.md", "src/bad.md")
        self.assertEqual(code, 0)
        self.assertEqual(
            [d["path"] for d in result["unreadable_documents"]], ["src/bad.md"]
        )
        self.assertEqual(
            [
                (u["source_path"], u["resolved_path"])
                for u in result["unverified_links"]
            ],
            [("src/m.md", "src/bad.md")],
        )
        self.assertEqual(result["findings"], [])


class RejectedArgumentsTest(CheckLinksTestBase):
    def test_conflicting_target_arguments_are_rejected_with_exit_1(self):
        self.write("a.md", "# T\n")
        before = self.snapshot()
        for args in (
            ("--paths", "a.md"),
            ("--key", "all", "--paths", "a.md"),
            ("--key", "k"),
            ("--key", "k", "--all", "--paths", "a.md"),
        ):
            with self.subTest(args=args):
                code, result = self.run_main(*args)
                self.assertEqual(code, 1)
                self.assertIsInstance(result["errors"], list)
                self.assertTrue(result["errors"])
        self.assertEqual(self.snapshot(), before)

    def test_unknown_argument_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                check_links.main(["--unknown"])
        self.assertEqual(caught.exception.code, 2)


@unittest.skipUnless(shutil.which("uv"), "uv が使えない環境では実行しない")
class EntryScriptWithUvTest(CheckLinksTestBase):
    SCRIPT = SKILL_SCRIPTS_DIR / "check_links.py"

    def uv_run(self, *args):
        return subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                str(self.SCRIPT),
                *args,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_exits_0_with_json_and_writes_nothing(self):
        self.make_fixture()
        before = self.snapshot()
        completed = self.uv_run(
            "--project-root", str(self.root), "--key", "k", "--paths", "src/main.md"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["findings"])
        self.assertEqual(self.snapshot(), before)

    def test_rejected_target_exits_1(self):
        completed = self.uv_run("--project-root", str(self.root), "--paths", "a.md")
        self.assertEqual(completed.returncode, 1)
        self.assertTrue(json.loads(completed.stdout)["errors"])

    def test_invalid_argument_exits_2(self):
        completed = self.uv_run("--unknown")
        self.assertEqual(completed.returncode, 2)


if __name__ == "__main__":
    unittest.main()
