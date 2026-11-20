import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_SCRIPTS_DIR = (
    PROJECT_ROOT / "plugins" / "doc-link" / "skills" / "index-docs" / "scripts"
)
sys.path.insert(0, str(SKILL_SCRIPTS_DIR))

import index_docs  # noqa: E402
from content_hash import RECORD_LENGTH  # noqa: E402
import state_store  # noqa: E402
import toc_candidate  # noqa: E402
from change_set import build_change_set  # noqa: E402

ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
ID_C = "DLID-pqrstvwxyz01"
S_A = "DLID-00000000s001"
S_B = "DLID-00000000s002"
S_C = "DLID-00000000s003"
RECORD = "c" * RECORD_LENGTH

A_TEXT = f"""---
doc_link_id: {ID_A}
---
# A {S_A}

[to b][b]

[b]: b.md "{RECORD} {ID_B}"
"""

B_TEXT = f"""---
doc_link_id: {ID_B}
---
# B {S_B}

body of b
"""

C_TEXT = f"""---
doc_link_id: {ID_C}
---
# C {S_C}

body of c
"""

FIXED = {
    "purpose": "目的\n\"引用符\" と 'apostrophe' と `backtick`",
    "summary": ["s1", "s2", "s3", "s4", "s5"],
    "applicable_tasks": ["t1"],
    "keywords": ["k1", "k2", "k3", "k4", "k5"],
}


def submit_args(doc_id, values=None):
    values = values or FIXED
    args = ["--doc-id", doc_id, f"--purpose={values['purpose']}"]
    for name in ("summary", "applicable_tasks", "keywords"):
        for item in values[name]:
            args.append(f"--{name.replace('_', '-')}={item}")
    return args


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.write("docs/a.md", A_TEXT)
        self.write("docs/b.md", B_TEXT)
        self.write("docs/c.md", C_TEXT)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def read(self, path):
        return (self.root / path).read_bytes().decode("utf-8")

    def without_random_values(self, text):
        """実行ごとに変わる値（構築 ID・一時ディレクトリのパス）を取り除く。

        数字の語（260・300 など）が現れないことを検査するとき、ランダムな値に偶然その並びが含まれて
        失敗しないようにするために使う。
        """
        text = text.replace(str(self.root), "<root>")
        return re.sub(r"BUILD-[0-9a-f]+", "<build>", text)

    def docs_snapshot(self):
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted((self.root / "docs").rglob("*"))
            if p.is_file()
        }

    def state_snapshot(self):
        base = self.root / ".doc-link"
        return {
            str(p.relative_to(self.root)): p.read_bytes()
            for p in sorted(base.rglob("*"))
            if p.is_file()
        }

    def toc_bytes(self, key):
        return state_store.confirmed_toc_path(self.root, key).read_bytes()

    def run_main(self, command, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = index_docs.main([command, "--project-root", str(self.root), *args])
        return code, json.loads(out.getvalue())

    def advance(self, key, paths, *extra):
        return self.run_main("advance", "--key", key, "--paths", *paths, *extra)

    def submit(self, key, paths, build_id, doc_id, values=None):
        return self.run_main(
            "submit",
            "--key",
            key,
            "--paths",
            *paths,
            "--build-id",
            build_id,
            *submit_args(doc_id, values),
        )

    def build(self, key, paths, values=None):
        """AI を介さず、生成結果を固定値で差し込んで構築を完了させる。最後の（終了コード、結果）を返す。"""
        build_id = None
        for _ in range(10):
            extra = [] if build_id is None else ["--build-id", build_id]
            code, result = self.advance(key, paths, *extra)
            if code != 0 or result["action"] == "done":
                return code, result
            build_id = result["build_id"]
            for batch in result["batches"]:
                for document in batch["documents"]:
                    scode, sresult = self.submit(
                        key, paths, build_id, document["doc_link_id"], values
                    )
                    self.assertEqual(scode, 0, sresult)
        self.fail("構築が終わらない")


ALL = ["docs/a.md", "docs/b.md", "docs/c.md"]


class RestartAfterInterruptionTest(Base):
    def work_files(self):
        directory = self.root / ".temp" / "doc-link" / "index-docs"
        return {p.name for p in directory.glob("BUILD-*.json")}

    def test_restart_removes_only_the_old_build_of_the_same_key(self):
        _, interrupted = self.advance("k", ALL)
        _, other = self.advance("other", ALL)
        self.assertEqual(
            self.work_files(),
            {f"{interrupted['build_id']}.json", f"{other['build_id']}.json"},
        )
        code, restarted = self.advance("k", ALL)
        self.assertEqual(code, 0)
        self.assertNotEqual(restarted["build_id"], interrupted["build_id"])
        self.assertEqual(
            self.work_files(),
            {f"{restarted['build_id']}.json", f"{other['build_id']}.json"},
        )

    def test_unreadable_work_file_is_kept(self):
        _, interrupted = self.advance("k", ALL)
        path = (
            self.root
            / ".temp"
            / "doc-link"
            / "index-docs"
            / f"{interrupted['build_id']}.json"
        )
        path.write_bytes(b"\xff not json")
        _, restarted = self.advance("k", ALL)
        self.assertEqual(
            self.work_files(),
            {f"{interrupted['build_id']}.json", f"{restarted['build_id']}.json"},
        )


class FirstBuildTest(Base):
    def test_first_advance_asks_for_generation_with_only_ids_and_limits(self):
        code, result = self.advance("k", ALL)
        self.assertEqual(code, 0)
        self.assertEqual(result["action"], "invoke_toc_updater")
        self.assertEqual(result["state"], "変更確定")
        self.assertTrue(result["await_completion"])
        self.assertRegex(result["build_id"], r"^BUILD-[0-9a-f]{8}$")
        # 同じディレクトリの 3 文書は 1 件にまとまる
        self.assertEqual(len(result["batches"]), 1)
        documents = result["batches"][0]["documents"]
        self.assertEqual([d["doc_link_id"] for d in documents], [ID_A, ID_B, ID_C])
        for document in documents:
            self.assertEqual(set(document), {"doc_link_id", "limits"})
            self.assertEqual(
                document["limits"],
                {
                    "purpose": 200,
                    "summary": 10,
                    "applicable_tasks": 10,
                    "keywords": 10,
                },
            )
        self.assertFalse((self.root / ".doc-link" / "tocs").exists())

    def test_request_does_not_contain_internal_limit_factor_or_margin(self):
        code, result = self.advance("k", ALL)

        def numbers(value):
            if isinstance(value, bool):
                return
            if isinstance(value, (int, float)):
                yield value
            elif isinstance(value, dict):
                for item in value.values():
                    yield from numbers(item)
            elif isinstance(value, list):
                for item in value:
                    yield from numbers(item)

        found = set(numbers(result["batches"])) | set(
            numbers([result["max_documents_per_agent"], result["remaining_documents"]])
        )
        # H（200 -> 260、10 -> 13）・係数 1.3 が現れない
        self.assertFalse(found & {260, 13, 1.3})
        text = self.without_random_values(json.dumps(result, ensure_ascii=False))
        self.assertNotIn("1.3", text)
        # 作業状態にも含まれない
        work = (self.root / ".temp" / "doc-link" / "index-docs").glob("*.json")
        for path in work:
            content = self.without_random_values(path.read_text(encoding="utf-8"))
            self.assertNotIn("1.3", content)
            self.assertNotIn("260", content)

    def test_values_starting_with_a_hyphen_are_accepted_when_joined_with_equals(self):
        values = {**FIXED, "keywords": ["--backend", "-x", "k3", "k4", "k5"]}
        code, result = self.build("k", ALL, values)
        self.assertEqual(code, 0, result)
        info = state_store.load_document_info(self.root, ID_A)
        self.assertEqual(info["keywords"], ["--backend", "-x", "k3", "k4", "k5"])

    def test_fixed_values_confirm_the_toc(self):
        before = self.docs_snapshot()
        code, result = self.build("k", ALL)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "done")
        self.assertEqual(result["state"], "完了")
        self.assertEqual(result["publication_state"], "確定 ToC あり")
        self.assertEqual(result["version"], 1)
        self.assertTrue(result["published"])
        self.assertEqual(result["excluded"], [])
        self.assertEqual(sorted(result["generated_documents"]), [ID_A, ID_B, ID_C])
        toc = state_store.load_confirmed_toc(self.root, "k")
        self.assertEqual(
            sorted(d["doc_link_id"] for d in toc["documents"]), [ID_A, ID_B, ID_C]
        )
        info = state_store.load_document_info(self.root, ID_B)
        self.assertEqual(info["title"], "B")
        self.assertEqual(info["purpose"], FIXED["purpose"])
        self.assertEqual(info["tasks"], FIXED["applicable_tasks"])
        # AC-030: [Index 対象文書]はバイト単位で変わらない
        self.assertEqual(self.docs_snapshot(), before)
        # 作業状態は削除される
        self.assertEqual(
            list((self.root / ".temp" / "doc-link" / "index-docs").glob("BUILD-*")),
            [],
        )

    def test_published_toc_matches_the_same_files_in_change_set(self):
        self.build("k", ALL)
        changes = build_change_set(self.root, "k", ALL)
        self.assertTrue(all(d.unchanged for d in changes.documents))
        self.assertEqual(changes.sections, ())

    def test_reference_results_are_recorded_and_do_not_stop_the_build(self):
        broken = f"""---
doc_link_id: {ID_A}
---
# A {S_A}

[gone][g] [nodir][n] [moved][m]

[g]: missing.md "DLID-zzzzzzzzzzzz"
[n]: nodir/x.md "{ID_B}"
[m]: sub/x.md "{ID_B}"
"""
        self.write("docs/a.md", broken)
        code, result = self.build("k", ALL)
        self.assertEqual(code, 0, result)
        report = result["reference_check"]
        self.assertEqual(report["summary"], {"absent": 3})
        self.assertEqual(
            sorted(f["absent_reason"] for f in report["findings"]),
            ["directory_missing", "directory_missing", "not_found"],
        )
        toc = state_store.load_confirmed_toc(self.root, "k")
        self.assertEqual(
            sorted(r["check"]["result"] for r in toc["references"]), ["absent"] * 3
        )

    def test_single_mode_uses_reserved_key(self):
        code, result = self.run_main("advance")
        self.assertEqual(code, 0)
        self.assertEqual(result["toc_key"], "all")


class IdempotenceTest(Base):
    def test_rerun_does_not_rewrite_toc_or_document_info(self):
        self.build("k", ALL)
        state_before = self.state_snapshot()
        code, result = self.advance("k", ALL)
        self.assertEqual(code, 0)
        self.assertEqual(result["action"], "done")
        self.assertFalse(result["published"])
        self.assertEqual(result["generated_documents"], [])
        self.assertEqual(self.state_snapshot(), state_before)

    def test_rerun_after_a_second_does_not_rewrite_toc(self):
        self.build("k", ALL)
        state_before = self.state_snapshot()
        with mock.patch.object(
            index_docs, "utc_now", return_value="2099-01-01T00:00:00+00:00"
        ):
            code, result = self.advance("k", ALL)
        self.assertEqual(code, 0)
        self.assertFalse(result["published"])
        self.assertEqual(self.state_snapshot(), state_before)

    def test_only_changed_document_is_a_generation_target(self):
        self.build("k", ALL)
        self.write("docs/b.md", B_TEXT + "\nmore body\n")
        code, result = self.advance("k", ALL)
        self.assertEqual(code, 0)
        self.assertEqual(result["action"], "invoke_toc_updater")
        ids = [d["doc_link_id"] for b in result["batches"] for d in b["documents"]]
        self.assertEqual(ids, [ID_B])

    def test_reference_only_change_does_not_generate(self):
        self.build("k", ALL)
        self.write("docs/a.md", A_TEXT.replace(RECORD, "d" * RECORD_LENGTH))
        # title の記録語だけの書き換えは[内容ハッシュ]に影響しない
        code, result = self.advance("k", ALL)
        self.assertEqual(code, 0)
        self.assertEqual(result["action"], "done")

    def test_moved_document_updates_path_only(self):
        self.build("k", ALL)
        info_before = state_store.load_document_info(self.root, ID_C)
        (self.root / "docs" / "sub").mkdir()
        (self.root / "docs" / "c.md").rename(self.root / "docs" / "sub" / "c.md")
        paths = ["docs/a.md", "docs/b.md", "docs/sub/c.md"]
        code, result = self.advance("k", paths)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "done")
        info = state_store.load_document_info(self.root, ID_C)
        self.assertEqual(info["path"], "docs/sub/c.md")
        self.assertEqual(info["purpose"], info_before["purpose"])


class OldVersionKeptTest(Base):
    def test_candidate_validation_failure_keeps_old_toc(self):
        self.build("k", ALL)
        toc_before = self.toc_bytes("k")
        self.write("docs/b.md", B_TEXT + "\nmore\n")
        failure = toc_candidate.CandidateFailure(
            toc_candidate.FailureReport(
                toc_candidate.STAGE_VALIDATION,
                (toc_candidate.CandidateProblem(ID_B, "docs/b.md", None, "検査失敗"),),
                True,
            )
        )
        build_id = self.advance("k", ALL)[1]["build_id"]
        self.submit("k", ALL, build_id, ID_B)
        with mock.patch.object(
            toc_candidate, "validate_candidate", side_effect=failure
        ):
            code, result = self.advance("k", ALL, "--build-id", build_id)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertEqual(result["stage"], "candidate_validation")
        self.assertEqual(result["state"], "失敗")
        self.assertEqual(result["failed_from"], "参照検査確定")
        self.assertTrue(result["confirmed_toc_present"])
        self.assertEqual(self.toc_bytes("k"), toc_before)
        # 確定済みの[文書情報]は戻らない
        self.assertEqual(
            state_store.load_document_info(self.root, ID_B)["purpose"],
            FIXED["purpose"],
        )
        # 再実行（B-09）で、生成せずに確定する
        code, result = self.advance("k", ALL)
        self.assertEqual(code, 0)
        self.assertEqual(result["action"], "done")
        self.assertEqual(result["version"], 2)

    def test_publish_failure_keeps_old_toc(self):
        self.build("k", ALL)
        toc_before = self.toc_bytes("k")
        self.write("docs/b.md", B_TEXT + "\nmore\n")
        build_id = self.advance("k", ALL)[1]["build_id"]
        self.submit("k", ALL, build_id, ID_B)
        error = state_store.StateStoreError(state_store.KIND_WRITE, "置き換え失敗")
        with mock.patch.object(state_store, "save_confirmed_toc", side_effect=error):
            code, result = self.advance("k", ALL, "--build-id", build_id)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertEqual(result["stage"], "publish")
        self.assertEqual(result["failed_from"], "候補検査済み")
        self.assertEqual(self.toc_bytes("k"), toc_before)

    def test_first_build_failure_creates_no_toc(self):
        build_id = self.advance("k", ALL)[1]["build_id"]
        for doc_id in (ID_A, ID_B, ID_C):
            self.submit("k", ALL, build_id, doc_id)
        failure = toc_candidate.CandidateFailure(
            toc_candidate.FailureReport(
                toc_candidate.STAGE_VALIDATION,
                (toc_candidate.CandidateProblem(None, None, None, "検査失敗"),),
                False,
            )
        )
        with mock.patch.object(
            toc_candidate, "validate_candidate", side_effect=failure
        ):
            code, result = self.advance("k", ALL, "--build-id", build_id)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertFalse(result["confirmed_toc_present"])
        self.assertFalse(state_store.confirmed_toc_path(self.root, "k").exists())

    def test_rejected_generation_fails_build_and_keeps_old_toc_and_saved_info(self):
        self.build("k", ALL)
        toc_before = self.toc_bytes("k")
        info_c_before = state_store.load_document_info(self.root, ID_C)
        self.write("docs/b.md", B_TEXT + "\nmore\n")
        self.write("docs/c.md", C_TEXT + "\nmore\n")
        new_values = {**FIXED, "purpose": "新しい目的"}
        _, invoked = self.advance("k", ALL)
        build_id = invoked["build_id"]
        code, _ = self.submit("k", ALL, build_id, ID_B, new_values)
        self.assertEqual(code, 0)
        too_long = {**FIXED, "purpose": "あ" * 300}
        code, rejected = self.submit("k", ALL, build_id, ID_C, too_long)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertEqual(rejected["stage"], "information")
        self.assertEqual(rejected["problems"][0]["field"], "purpose")
        # 拒否理由に H・係数・余白・実際の長さが現れない
        text = self.without_random_values(json.dumps(rejected, ensure_ascii=False))
        self.assertNotIn("260", text)
        self.assertNotIn("300", text)
        self.assertNotIn("1.3", text)

        code, result = self.advance("k", ALL, "--build-id", build_id)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertEqual(result["stage"], "information")
        self.assertEqual([p["doc_link_id"] for p in result["problems"]], [ID_C])
        self.assertTrue(result["confirmed_toc_present"])
        self.assertEqual(self.toc_bytes("k"), toc_before)
        # 検証に通った B の[文書情報]は保存されたまま、通らなかった C は旧版のまま
        self.assertEqual(
            state_store.load_document_info(self.root, ID_B)["purpose"], "新しい目的"
        )
        self.assertEqual(state_store.load_document_info(self.root, ID_C), info_c_before)
        # 作業状態は削除される
        self.assertEqual(
            list((self.root / ".temp" / "doc-link" / "index-docs").glob("BUILD-*")),
            [],
        )

    def test_missing_generation_result_fails_instead_of_publishing(self):
        build_id = self.advance("k", ALL)[1]["build_id"]
        self.submit("k", ALL, build_id, ID_A)
        code, result = self.advance("k", ALL, "--build-id", build_id)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertEqual(result["stage"], "information")
        self.assertEqual(
            sorted(p["doc_link_id"] for p in result["problems"]), [ID_B, ID_C]
        )
        self.assertFalse(result["confirmed_toc_present"])
        self.assertFalse(state_store.confirmed_toc_path(self.root, "k").exists())

    def test_unreadable_document_stops_the_build(self):
        (self.root / "docs" / "b.md").write_bytes(b"\xff\xfe\x00bad\n")
        code, result = self.advance("k", ALL)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertEqual(result["stage"], "id_confirmation")
        self.assertEqual(result["failed_from"], "対象確定")
        self.assertEqual(result["problems"][0]["path"], "docs/b.md")
        self.assertFalse((self.root / ".doc-link").exists())

    def test_unreadable_directory_stops_the_build_and_keeps_the_old_toc(self):
        if os.geteuid() == 0:
            self.skipTest("root は権限で読めなくならない")
        self.build("k", ALL)
        toc_before = self.toc_bytes("k")
        state_before = self.state_snapshot()
        self.write("docs/locked/d.md", C_TEXT.replace(ID_C, "DLID-mnpqrstvwxyz"))
        locked = self.root / "docs" / "locked"
        locked.chmod(0o000)
        self.addCleanup(locked.chmod, 0o755)
        code, result = self.run_main("advance", "--key", "k", "--dirs", "docs")
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertEqual(result["stage"], "target_scope")
        self.assertEqual(result["problems"][0]["path"], "docs/locked")
        self.assertEqual(self.toc_bytes("k"), toc_before)
        self.assertEqual(self.state_snapshot(), state_before)

    def test_corrupt_confirmed_toc_stops_the_build(self):
        self.build("k", ALL)
        path = state_store.confirmed_toc_path(self.root, "k")
        path.write_bytes(b"not json")
        code, result = self.advance("k", ALL)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertEqual(result["stage"], "change_set")
        self.assertEqual(path.read_bytes(), b"not json")


class MultipleKeysTest(Base):
    def test_update_and_departure_in_one_key_do_not_rewrite_the_other(self):
        keys = {"one": ["docs/a.md", "docs/b.md"], "two": ["docs/b.md", "docs/c.md"]}
        for key, paths in keys.items():
            code, _ = self.build(key, paths)
            self.assertEqual(code, 0)
        two_before = self.toc_bytes("two")

        # key one で共有の文書 b を更新する
        self.write("docs/b.md", B_TEXT + "\nmore\n")
        code, result = self.build("one", keys["one"])
        self.assertEqual(code, 0, result)
        self.assertEqual(result["version"], 2)
        self.assertEqual(self.toc_bytes("two"), two_before)

        # key one から b が離脱する
        code, result = self.build("one", ["docs/a.md"])
        self.assertEqual(code, 0, result)
        self.assertEqual(self.toc_bytes("two"), two_before)
        self.assertEqual(
            [
                d["doc_link_id"]
                for d in state_store.load_confirmed_toc(self.root, "two")["documents"]
            ],
            sorted([ID_B, ID_C]),
        )

    def test_document_with_verified_info_from_another_key_is_not_a_target(self):
        self.build("one", ["docs/a.md", "docs/b.md"])
        code, result = self.advance("two", ["docs/b.md", "docs/c.md"])
        self.assertEqual(code, 0)
        ids = [d["doc_link_id"] for b in result["batches"] for d in b["documents"]]
        self.assertEqual(ids, [ID_C])

    def test_stale_toc_of_other_key_is_not_a_basis_for_the_build(self):
        self.build("one", ["docs/a.md", "docs/b.md"])
        self.build("two", ["docs/b.md", "docs/c.md"])
        self.write("docs/b.md", B_TEXT + "\nmore\n")
        self.build("one", ["docs/a.md", "docs/b.md"])
        # two の確定 ToC は古いが、two の再構築は文書情報（最新）と現物から決まる
        code, result = self.advance("two", ["docs/b.md", "docs/c.md"])
        self.assertEqual(code, 0)
        self.assertEqual(result["action"], "done")
        self.assertEqual(result["version"], 2)


class ExcludedDocumentsTest(Base):
    def test_missing_and_duplicate_ids_are_reported_and_others_enter_the_toc(self):
        self.write("docs/noid.md", "# No id\n")
        self.write("docs/dup1.md", f"---\ndoc_link_id: {ID_C}\n---\n# dup\n")
        paths = [*ALL, "docs/noid.md", "docs/dup1.md"]
        code, result = self.build("k", paths)
        self.assertEqual(code, 0, result)
        excluded = {e["path"]: e for e in result["excluded"]}
        self.assertEqual(excluded["docs/noid.md"]["reason"], "missing")
        self.assertEqual(excluded["docs/c.md"]["reason"], "duplicate")
        self.assertEqual(excluded["docs/dup1.md"]["reason"], "duplicate")
        toc = state_store.load_confirmed_toc(self.root, "k")
        self.assertEqual(
            sorted(d["doc_link_id"] for d in toc["documents"]), [ID_A, ID_B]
        )


class PremiseTest(Base):
    def test_unknown_build_id_is_rejected(self):
        code, result = self.advance("k", ALL, "--build-id", "BUILD-00000000")
        self.assertEqual(code, 1)
        self.assertTrue(result["errors"])
        self.assertFalse((self.root / ".doc-link").exists())

    def test_malformed_build_id_is_rejected(self):
        code, result = self.advance("k", ALL, "--build-id", "../../x")
        self.assertEqual(code, 1)

    def test_build_id_for_another_key_or_spec_is_rejected(self):
        build_id = self.advance("k", ALL)[1]["build_id"]
        code, _ = self.advance("other", ALL, "--build-id", build_id)
        self.assertEqual(code, 1)
        code, _ = self.advance("k", ["docs/a.md", "docs/b.md"], "--build-id", build_id)
        self.assertEqual(code, 1)
        code, _ = self.submit("other", ALL, build_id, ID_A)
        self.assertEqual(code, 1)
        self.assertFalse((self.root / ".doc-link").exists())

    def test_submit_for_document_outside_the_request_is_rejected(self):
        build_id = self.advance("k", ALL)[1]["build_id"]
        code, result = self.submit("k", ALL, build_id, "DLID-zzzzzzzzzzzz")
        self.assertEqual(code, 1)
        self.assertTrue(result["errors"])
        self.assertFalse((self.root / ".doc-link").exists())

    def test_submit_twice_is_rejected_and_does_not_overwrite(self):
        build_id = self.advance("k", ALL)[1]["build_id"]
        self.assertEqual(self.submit("k", ALL, build_id, ID_A)[0], 0)
        info = state_store.load_document_info(self.root, ID_A)
        other = {**FIXED, "purpose": "別の目的"}
        code, _ = self.submit("k", ALL, build_id, ID_A, other)
        self.assertEqual(code, 1)
        self.assertEqual(state_store.load_document_info(self.root, ID_A), info)

    def test_submit_without_advance_is_rejected(self):
        code, _ = self.submit("k", ALL, "BUILD-12345678", ID_A)
        self.assertEqual(code, 1)

    def test_conflicting_target_arguments_are_rejected_with_exit_1(self):
        before = self.docs_snapshot()
        for args in (
            ("--paths", "docs/a.md"),
            ("--key", "all", "--paths", "docs/a.md"),
            ("--key", "k"),
            ("--key", "k", "--all", "--paths", "docs/a.md"),
        ):
            with self.subTest(args=args):
                code, result = self.run_main("advance", *args)
                self.assertEqual(code, 1)
                self.assertTrue(result["errors"])
        self.assertEqual(self.docs_snapshot(), before)
        self.assertFalse((self.root / ".doc-link").exists())

    def test_unknown_argument_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                index_docs.main(["advance", "--unknown"])
        self.assertEqual(caught.exception.code, 2)

    def test_state_machine_rejects_skipping_a_stage(self):
        session = index_docs.bsm.BuildSession()
        with self.assertRaises(index_docs.bsm.TransitionRejected):
            session.apply(
                index_docs.bsm.EVENT_COMMIT,
                index_docs.bsm.BuildFacts(commit_succeeded=True),
            )

    def test_rejected_title_is_required_without_h1(self):
        self.write("docs/noh1.md", f"---\ndoc_link_id: {ID_C}\n---\nbody only\n")
        paths = ["docs/noh1.md"]
        _, invoked = self.advance("k", paths)
        build_id = invoked["build_id"]
        code, rejected = self.submit("k", paths, build_id, ID_C)
        self.assertEqual(code, index_docs.EXIT_BUILD_FAILED)
        self.assertEqual(rejected["problems"][0]["field"], "title")


class WaveTest(Base):
    def test_batches_split_by_directory_and_limits(self):
        paths = []
        for directory in range(2):
            for index in range(4):
                doc_id = f"DLID-d{directory}00000000{index:02d}"[:17]
                path = f"docs/dir{directory}/f{index}.md"
                self.write(path, f"---\ndoc_link_id: {doc_id}\n---\n# F{index}\n")
                paths.append(path)
        code, result = self.advance("k", paths)
        self.assertEqual(code, 0)
        sizes = [len(b["documents"]) for b in result["batches"]]
        self.assertEqual(sizes, [3, 1, 3, 1])
        self.assertEqual(result["remaining_documents"], 0)

    def test_more_than_ten_batches_are_issued_in_waves(self):
        paths = []
        for directory in range(12):
            path = f"docs/d{directory:02d}/f.md"
            doc_id = f"DLID-w{directory:02d}000000000"[:17]
            self.write(path, f"---\ndoc_link_id: {doc_id}\n---\n# F\n")
            paths.append(path)
        code, first = self.advance("k", paths)
        self.assertEqual(len(first["batches"]), 10)
        self.assertEqual(first["remaining_documents"], 2)
        build_id = first["build_id"]
        for batch in first["batches"]:
            for document in batch["documents"]:
                self.assertEqual(
                    self.submit("k", paths, build_id, document["doc_link_id"])[0], 0
                )
        code, second = self.advance("k", paths, "--build-id", build_id)
        self.assertEqual(code, 0)
        self.assertEqual(second["build_id"], build_id)
        self.assertEqual(len(second["batches"]), 2)
        self.assertEqual(second["remaining_documents"], 0)
        for batch in second["batches"]:
            for document in batch["documents"]:
                self.assertEqual(
                    self.submit("k", paths, build_id, document["doc_link_id"])[0], 0
                )
        code, done = self.advance("k", paths, "--build-id", build_id)
        self.assertEqual(code, 0)
        self.assertEqual(done["action"], "done")
        self.assertEqual(len(done["generated_documents"]), 12)


@unittest.skipUnless(shutil.which("uv"), "uv が使えない環境では実行しない")
class EntryScriptWithUvTest(Base):
    SCRIPT = SKILL_SCRIPTS_DIR / "index_docs.py"

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

    def test_build_through_uv_keeps_values_unchanged(self):
        common = ["--project-root", str(self.root), "--key", "k", "--paths", *ALL]
        completed = self.uv_run("advance", *common)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        invoked = json.loads(completed.stdout)
        self.assertEqual(invoked["action"], "invoke_toc_updater")
        build_id = invoked["build_id"]
        values = {
            **FIXED,
            "purpose": '改行\nと "引用符" と `backtick` と 日本語 と -dash',
            "keywords": ["-先頭がハイフン", "k2", "k3", "k4", "k5"],
        }
        for batch in invoked["batches"]:
            for document in batch["documents"]:
                completed = self.uv_run(
                    "submit",
                    *common,
                    "--build-id",
                    build_id,
                    *submit_args(document["doc_link_id"], values),
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
        completed = self.uv_run("advance", *common, "--build-id", build_id)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["action"], "done")
        info = state_store.load_document_info(self.root, ID_A)
        self.assertEqual(info["purpose"], values["purpose"])
        self.assertEqual(info["keywords"], values["keywords"])

    def test_rejected_target_exits_1(self):
        completed = self.uv_run(
            "advance", "--project-root", str(self.root), "--paths", "docs/a.md"
        )
        self.assertEqual(completed.returncode, 1)
        self.assertTrue(json.loads(completed.stdout)["errors"])

    def test_failure_exits_3(self):
        (self.root / "docs" / "b.md").write_bytes(b"\xff\xfe\x00bad\n")
        completed = self.uv_run(
            "advance",
            "--project-root",
            str(self.root),
            "--key",
            "k",
            "--paths",
            *ALL,
        )
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["stage"], "id_confirmation")

    def test_invalid_argument_exits_2(self):
        completed = self.uv_run("advance", "--unknown")
        self.assertEqual(completed.returncode, 2)


if __name__ == "__main__":
    unittest.main()
