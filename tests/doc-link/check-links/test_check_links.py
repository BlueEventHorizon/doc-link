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
from content_hash import (  # noqa: E402
    RECORD_LENGTH,
    document_content_hash,
    section_content_hashes,
    title_value,
)

DOC_A = "DLID-0123456789ab"
SEC_A1 = "DLID-abcdefghjkmn"
SEC_A2 = "DLID-pqrstvwxyz01"
DOC_B = "DLID-2222222222bb"
SEC_GONE = "DLID-4444444444dd"
DOC_GONE = "DLID-zzzzzzzzzzzz"
DOC_MAIN = "DLID-5555555555ee"
SEC_MAIN = "DLID-6666666666ff"
HASH = "a" * RECORD_LENGTH

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


def with_detail(stdout: dict) -> dict:
    """標準出力の JSON に、明細ファイル（`detail_path`）の全件を重ねて返す。同じ名前の項目は標準出力を優先する。

    標準出力は件数までで、明細は作業ファイルにある（要件 D-061）。内容の検査は、両方を合わせた形で行う。
    標準出力に明細が載っていないことは、標準出力だけを読むテストで確かめる。
    """
    path = stdout.get("detail_path")
    if path is None:
        return stdout
    detail = json.loads(Path(path).read_bytes().decode("utf-8"))
    return {**detail, **stdout}


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
        """対象文書と管理状態（`.temp/` の作業ファイルを除く、すべてのファイル）の内容。"""
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file() and ".temp" not in p.relative_to(self.root).parts
        }

    def work_files(self):
        """`.temp/` の下に書かれた作業ファイルの、ルートからの相対パス。"""
        return sorted(
            str(p.relative_to(self.root))
            for p in self.root.rglob("*")
            if p.is_file() and ".temp" in p.relative_to(self.root).parts
        )

    def run_stdout(self, *args):
        """（終了コード、標準出力の JSON）を返す。"""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_links.main(["--project-root", str(self.root), *args])
        return code, json.loads(out.getvalue())

    def run_main(self, *args):
        """（終了コード、標準出力の JSON に明細ファイルの全件を重ねたもの）を返す。"""
        code, stdout = self.run_stdout(*args)
        return code, with_detail(stdout)

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

    def test_every_finding_has_the_source_document_id(self):
        self.assertEqual(self.one("path_mismatch")["source_doc_id"], DOC_MAIN)
        for finding in self.result["findings"]:
            self.assertEqual(finding["source_doc_id"], DOC_MAIN, finding)

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

    def test_scope(self):
        scope = self.result["scope"]
        self.assertIn("ref", self.result["directories"])
        self.assertEqual(scope["directory_count"], len(self.result["directories"]))
        self.assertNotIn("directories", scope)
        self.assertTrue(scope["checked_at"])

    def test_writes_nothing(self):
        self.assertEqual(self.snapshot(), self.before)


class GuidanceConfirmationTest(unittest.TestCase):
    """D-057・AC-033: 書き直す対象の検出事項が 1 つでもあれば、書き直す前の確認を案内する。"""

    def confirm_lines(self, categories):
        findings = [{"category": category} for category in categories]
        return [
            line
            for line in check_links._guidance(findings)
            if "利用者" in line and "確認" in line and "承認" in line
        ]

    def test_link_without_dlid_alone_asks_for_confirmation(self):
        self.assertEqual(len(self.confirm_lines(["link_without_dlid"])), 1)

    def test_inline_link_with_dlid_alone_asks_for_confirmation(self):
        self.assertEqual(len(self.confirm_lines(["inline_link_with_dlid"])), 1)

    def test_path_mismatch_alone_asks_for_confirmation(self):
        self.assertEqual(len(self.confirm_lines(["path_mismatch"])), 1)

    def test_confirmation_is_given_once_for_mixed_findings(self):
        categories = ["link_without_dlid", "path_mismatch", "absent"]
        self.assertEqual(len(self.confirm_lines(categories)), 1)

    def test_no_findings_gives_no_guidance(self):
        self.assertEqual(check_links._guidance([]), [])


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
        expected = f"{title_value(document_content_hash(REF_A))} {DOC_A}"
        self.assertEqual(found["../ref/a.md"]["suggested_title"], expected)
        self.assertEqual(len(expected.split()[0]), RECORD_LENGTH)

    def test_heading_fragment_gets_section_hash_and_section_id(self):
        anchor = "beta-dlid-pqrstvwxyz01"
        found, _ = self.findings_of(f"# M\n\n[r]: ../ref/a.md#{anchor}\n")
        # 見出しの出現順は Alpha, Beta なので、Beta は 2 番目
        expected = f"{title_value(section_content_hashes(REF_A)[1])} {SEC_A2}"
        self.assertEqual(found[f"../ref/a.md#{anchor}"]["suggested_title"], expected)

    def test_explicit_anchor_fragment_gets_document_value(self):
        found, _ = self.findings_of("# M\n\n[r]: ../ref/c.md#manual\n")
        expected = f"{title_value(document_content_hash(REF_C))} {DOC_C}"
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
        expected = f"{title_value(document_content_hash(REF_A))} {DOC_A}"
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
    def test_only_a_lowercase_hex_word_of_the_record_length_is_read_as_a_record(self):
        words = {
            "ok": "a" * RECORD_LENGTH,
            "upper": "A" * RECORD_LENGTH,
            "short": "a" * (RECORD_LENGTH - 1),
            "long": "a" * (RECORD_LENGTH + 1),
            "nonhex": "g" * RECORD_LENGTH,
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
            f"ref/gone{index}.md": ("a" * RECORD_LENGTH if name == "ok" else None)
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
        self.assertEqual([f["source_doc_id"] for f in result["findings"]], [None, None])


class NonReferenceLinksTest(CheckLinksTestBase):
    def test_images_and_scheme_links_are_not_reported(self):
        self.write("ref/a.md", REF_A)
        self.write(
            "src/i.md",
            "# I\n\n"
            "![figure](../ref/a.md) and ![site](https://example.com/a.png)\n\n"
            "<https://example.com/a.md> and [web](https://example.com/a.md)\n\n"
            "[real](../ref/a.md)\n",
        )
        code, result = self.run_main("--key", "k", "--paths", "src/i.md")
        self.assertEqual(code, 0)
        (finding,) = result["findings"]
        self.assertEqual(finding["category"], "link_without_dlid")
        self.assertEqual(finding["line"], 7)
        self.assertEqual(finding["target"], "../ref/a.md")


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


class WithoutDocumentIdTest(CheckLinksTestBase):
    def test_document_without_id_is_warned_as_incomplete(self):
        self.write("ref/a.md", REF_A)
        self.write("src/m.md", "# M\n")
        code, result = self.run_main("--key", "k", "--paths", "src/m.md")
        self.assertEqual(code, 0)
        self.assertEqual(len(result["warnings"]), 1)
        # 警告は件数だけを持ち、パスは明細ファイルにある
        self.assertIn("1 件", result["warnings"][0])
        self.assertNotIn("src/m.md", result["warnings"][0])
        self.assertEqual(result["documents_without_id"], ["src/m.md"])
        self.assertEqual(result["summary"]["documents_without_id"], 1)

    def test_documents_with_id_give_no_warning(self):
        self.write("src/m.md", f"---\ndoc_link_id: {DOC_MAIN}\n---\n# M {SEC_MAIN}\n")
        code, result = self.run_main("--key", "k", "--paths", "src/m.md")
        self.assertEqual(code, 0)
        self.assertEqual(result["warnings"], [])


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
        result = json.loads(completed.stdout)
        self.assertNotIn("findings", result)
        self.assertGreater(result["summary"]["findings"], 0)
        self.assertTrue(Path(result["detail_path"]).is_file())
        self.assertEqual(self.snapshot(), before)

    def test_rejected_target_exits_1(self):
        completed = self.uv_run("--project-root", str(self.root), "--paths", "a.md")
        self.assertEqual(completed.returncode, 1)
        self.assertTrue(json.loads(completed.stdout)["errors"])

    def test_invalid_argument_exits_2(self):
        completed = self.uv_run("--unknown")
        self.assertEqual(completed.returncode, 2)


class DetailFileTest(CheckLinksTestBase):
    """D-061: 標準出力は件数までで、検出事項の全件は明細ファイルにある。"""

    def detail_file(self, key):
        return self.root / ".temp" / "doc-link" / "check-links" / f"detail-{key}.json"

    def test_stdout_holds_counts_and_the_detail_file_holds_every_item(self):
        self.make_fixture()
        code, stdout = self.run_stdout("--key", "k", "--paths", "src/main.md")
        self.assertEqual(code, 0)
        self.assertEqual(
            set(stdout),
            {"summary", "scope", "problems", "warnings", "guidance", "detail_path"},
        )
        self.assertEqual(
            set(stdout["scope"]), {"target", "directory_count", "checked_at"}
        )
        path = Path(stdout["detail_path"])
        self.assertTrue(path.is_absolute())
        self.assertEqual(path, self.detail_file("k"))
        detail = json.loads(path.read_bytes().decode("utf-8"))
        self.assertEqual(
            set(detail),
            {
                "findings",
                "unverified_links",
                "unreadable_documents",
                "directories",
                "documents_without_id",
            },
        )
        summary = stdout["summary"]
        self.assertEqual(summary["findings"], len(detail["findings"]))
        self.assertEqual(
            sum(summary["findings_by_category"].values()), len(detail["findings"])
        )
        self.assertEqual(summary["unverified_links"], len(detail["unverified_links"]))
        self.assertEqual(
            summary["unreadable_documents"], len(detail["unreadable_documents"])
        )
        self.assertEqual(stdout["scope"]["directory_count"], len(detail["directories"]))

    def test_stdout_size_does_not_grow_with_the_number_of_findings(self):
        def stdout_size(key, count):
            definitions = "".join(
                f'[r{i}]: ../gone/x{i}.md "{HASH} {DOC_GONE}"\n' for i in range(count)
            )
            path = f"src/{key}.md"
            self.write(
                path,
                f"---\ndoc_link_id: {DOC_MAIN}\n---\n# M {SEC_MAIN}\n\n" + definitions,
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                check_links.main(
                    ["--project-root", str(self.root), "--key", key, "--paths", path]
                )
            return len(out.getvalue())

        self.assertLess(abs(stdout_size("many", 300) - stdout_size("few", 1)), 20)

    def test_detail_file_is_written_even_when_nothing_is_found(self):
        self.write("src/m.md", f"---\ndoc_link_id: {DOC_MAIN}\n---\n# M {SEC_MAIN}\n")
        code, stdout = self.run_stdout("--key", "k", "--paths", "src/m.md")
        self.assertEqual(code, 0)
        self.assertEqual(stdout["summary"]["findings"], 0)
        self.assertEqual(stdout["guidance"], [])
        detail = json.loads(Path(stdout["detail_path"]).read_bytes().decode("utf-8"))
        self.assertEqual(detail["findings"], [])

    def test_only_the_detail_file_is_written(self):
        self.make_fixture()
        before = self.snapshot()
        self.run_main("--key", "k", "--paths", "src/main.md")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(
            self.work_files(), [".temp/doc-link/check-links/detail-k.json"]
        )

    def test_unwritable_detail_file_exits_1(self):
        self.make_fixture()
        self.write(".temp/doc-link/check-links", "not a directory")
        code, stdout = self.run_stdout("--key", "k", "--paths", "src/main.md")
        self.assertEqual(code, 1)
        self.assertTrue(any("明細ファイルを書けない" in e for e in stdout["errors"]))


class MovedTargetTest(CheckLinksTestBase):
    """D-062: リンク先のディレクトリに無い参照先を、今回の対象文書の中から探す。"""

    SOURCE = f"""---
doc_link_id: {DOC_MAIN}
---
# Main {SEC_MAIN}

[doc]: ../old/a.md "{HASH} {DOC_A}"
[sec]: ../old/a.md#beta-dlid-pqrstvwxyz01 "{HASH} {SEC_A2}"
"""

    def findings(self, *paths):
        code, result = self.run_main("--key", "k", "--paths", *paths)
        self.assertEqual(code, 0)
        return {f["dlid"]: f for f in result["findings"]}, result

    def test_target_moved_to_another_directory_in_the_targets_is_found(self):
        self.write("src/main.md", self.SOURCE)
        self.write("archive/a.md", REF_A)
        found, result = self.findings("src/main.md", "archive/a.md")
        for dlid, kind in ((DOC_A, "document"), (SEC_A2, "section")):
            finding = found[dlid]
            self.assertEqual(finding["category"], "path_mismatch")
            self.assertEqual(finding["current_path"], "archive/a.md")
            self.assertEqual(finding["target_kind"], kind)
            self.assertEqual(finding["source_doc_id"], DOC_MAIN)
            self.assertNotIn("absent_reason", finding)
        self.assertEqual(
            result["summary"]["findings_by_category"], {"path_mismatch": 2}
        )

    def test_order_of_the_targets_does_not_matter(self):
        self.write("src/main.md", self.SOURCE)
        self.write("archive/a.md", REF_A)
        found, _ = self.findings("archive/a.md", "src/main.md")
        self.assertEqual(found[DOC_A]["current_path"], "archive/a.md")

    def test_target_moved_outside_the_targets_stays_absent(self):
        self.write("src/main.md", self.SOURCE)
        self.write("archive/a.md", REF_A)
        found, _ = self.findings("src/main.md")
        self.assertEqual(found[DOC_A]["category"], "absent")
        self.assertEqual(found[DOC_A]["absent_reason"], "directory_missing")
        self.assertNotIn("archive", str(found[DOC_A]))

    def test_target_found_in_several_documents_is_a_duplicate(self):
        self.write("src/main.md", self.SOURCE)
        self.write("archive/a.md", REF_A)
        self.write("copy/a.md", REF_A)
        found, _ = self.findings("src/main.md", "archive/a.md", "copy/a.md")
        self.assertEqual(found[DOC_A]["category"], "duplicate")
        self.assertEqual(found[DOC_A]["duplicate_paths"], ["archive/a.md", "copy/a.md"])

    def test_section_moved_to_another_document_is_not_a_missing_section(self):
        # リンク先の文書は残っているが、セクションは別のディレクトリの文書へ移った
        self.write("src/main.md", self.SOURCE)
        self.write("old/a.md", f"---\ndoc_link_id: {DOC_A}\n---\n# Alpha {SEC_A1}\n")
        self.write(
            "new/b.md", f"---\ndoc_link_id: {DOC_B}\n---\n# Bee\n\n## Beta {SEC_A2}\n"
        )
        found, _ = self.findings("src/main.md", "old/a.md", "new/b.md")
        self.assertNotIn(DOC_A, found)
        self.assertEqual(found[SEC_A2]["category"], "path_mismatch")
        self.assertEqual(found[SEC_A2]["current_path"], "new/b.md")

    def test_dlid_in_no_target_document_stays_a_missing_section(self):
        self.write("src/main.md", self.SOURCE)
        self.write("old/a.md", f"---\ndoc_link_id: {DOC_A}\n---\n# Alpha {SEC_A1}\n")
        found, _ = self.findings("src/main.md", "old/a.md")
        self.assertEqual(found[SEC_A2]["category"], "missing_section")

    def test_managed_state_is_not_used(self):
        # 管理状態に移動先の記録があっても、対象文書の現物に無ければ、移動先を示さない
        self.write("src/main.md", self.SOURCE)
        self.write(".doc-link/documents/x.json", "{}")
        before = self.snapshot()
        found, _ = self.findings("src/main.md")
        self.assertEqual(found[DOC_A]["category"], "absent")
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
