"""横断シナリオ（DES-009 §3）の統合テストが共有する補助。

各 SKILL の入口 script の `main()` を、実際の引数で呼ぶ。AI を介する部分（`toc-updater` の生成・
`query-worker` の検索）は、`index_docs` の `submit`・`worker_io` の `next`・`answer`（標準入力の JSON）で固定値を差し込む。
"""

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = PROJECT_ROOT / "plugins" / "doc-link"
for _directory in (
    PLUGIN_DIR / "scripts",
    *sorted((PLUGIN_DIR / "skills").glob("*/scripts")),
):
    sys.path.insert(0, str(_directory))

import backend_select  # noqa: E402
import check_impact  # noqa: E402
import check_links  # noqa: E402
import check_toc  # noqa: E402
import embed_dlid  # noqa: E402
import index_docs  # noqa: E402
import query_docs  # noqa: E402
import resolve_dlid  # noqa: E402
import state_store  # noqa: E402
import worker_io  # noqa: E402

ID_A = "DLID-0123456789ab"
ID_B = "DLID-abcdefghjkmn"
ID_C = "DLID-pqrstvwxyz01"
S_A = "DLID-00000000s001"
S_B = "DLID-00000000s002"
S_C = "DLID-00000000s003"

# AI の生成結果の固定値（検証器の下限・上限に収まる）。
FIXED = {
    "purpose": "目的\n\"引用符\" と 'apostrophe' と `backtick`",
    "summary": ["s1", "s2", "s3", "s4", "s5"],
    "applicable_tasks": ["t1"],
    "keywords": ["k1", "k2", "k3", "k4", "k5"],
}

_DLID_AT_LINE_END = re.compile(r" DLID-[0-9a-z]{12}$", re.MULTILINE)
_DLID_FRONTMATTER = re.compile(r"\A---\ndoc_link_id: DLID-[0-9a-z]{12}\n---\n\n?")


def doc_text(doc_id, title, body="", sec_id=None):
    """frontmatter の[文書 ID]と、H1 に[セクション ID]を持つ固定の文書。"""
    heading = f"# {title} {sec_id}" if sec_id else f"# {title}"
    return f"---\ndoc_link_id: {doc_id}\n---\n{heading}\n\n{body}\n"


def strip_dlids(text):
    """付与された[DLID]（frontmatter の `doc_link_id` と、見出しの行末）だけを取り除く。

    frontmatter を新設したときに、その後へ足す空行 1 行も、付与されたものとして取り除く。
    """
    return _DLID_AT_LINE_END.sub("", _DLID_FRONTMATTER.sub("", text, count=1))


def document_id_in(text):
    """文書の frontmatter の `doc_link_id`（付与された[文書 ID]）。`embed-dlid` は件数だけを返すので、文書から読む。"""
    found = re.search(r"\A---\ndoc_link_id: (DLID-[0-9a-z]{12})\n", text)
    return found.group(1) if found else None


def section_id_in(text, heading):
    """見出しのテキストが `heading` の行の末尾の[セクション ID]（付与された値）。無ければ `None`。"""
    found = re.search(
        r"^#+ " + re.escape(heading) + r" (DLID-[0-9a-z]{12})$", text, re.MULTILINE
    )
    return found.group(1) if found else None


def section_ids_in(text):
    """見出しの行の末尾の[セクション ID]の並び。"""
    return re.findall(r"^#+ .* (DLID-[0-9a-z]{12})$", text, re.MULTILINE)


def submit_args(doc_id, values=None):
    values = values or FIXED
    args = ["--doc-id", doc_id, f"--purpose={values['purpose']}"]
    for name in ("summary", "applicable_tasks", "keywords"):
        for item in values[name]:
            args.append(f"--{name.replace('_', '-')}={item}")
    return args


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


def _force_toc_backend(testcase):
    """既存の検査が、実機の doc-db へ接続・起動しないよう、基盤判定を[ToC]の強制スイッチに固定する。"""
    patcher = mock.patch.object(
        backend_select,
        "decide",
        return_value=backend_select.Decision(backend_select.BACKEND_TOC, forced=True),
    )
    patcher.start()
    testcase.addCleanup(patcher.stop)


class ScenarioBase(unittest.TestCase):
    """一時ディレクトリをプロジェクトルートとする、シナリオの共通の土台。"""

    def setUp(self):
        _force_toc_backend(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        # `toc-updater` への生成依頼の[文書 ID]を、`build` が呼ぶたびに積む。
        self.requested: list[str] = []

    # --- ファイル ---

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def read(self, path):
        return (self.root / path).read_bytes().decode("utf-8")

    def snapshot(self, *directories):
        """指定したディレクトリ（プロジェクトルート相対）の全ファイルのバイト列。"""
        result = {}
        for directory in directories:
            base = self.root / directory
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    result[str(path.relative_to(self.root))] = path.read_bytes()
        return result

    def state_snapshot(self):
        return self.snapshot(".doc-link")

    def toc_bytes(self, key):
        return state_store.confirmed_toc_path(self.root, key).read_bytes()

    def toc(self, key):
        return state_store.load_confirmed_toc(self.root, key)

    def info(self, doc_id):
        return state_store.load_document_info(self.root, doc_id)

    def summary(self, doc_id):
        """[文書情報]のうち、構築の確定で変わらない項目（現在パス・要約・要約を生成した時点の[内容ハッシュ]）。"""
        info = self.info(doc_id)
        return {
            name: value
            for name, value in info.items()
            if name not in state_store.UNCONFIRMED_FACTS
        }

    # --- 入口 script ---

    def run_script(self, module, *args, command=None):
        prefix = [] if command is None else [command]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = module.main([*prefix, "--project-root", str(self.root), *args])
        return code, with_detail(json.loads(out.getvalue()))

    def run_worker(self, command, worker_id, stdin_text=""):
        """`query-worker` の入口（`worker_io`）を、プロジェクトのルートを作業ディレクトリとして呼ぶ。"""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = worker_io.execute(
                worker_io.build_parser().parse_args([command, worker_id]),
                io.StringIO(stdin_text),
                self.root,
                None,
            )
        return code, with_detail(json.loads(out.getvalue()))

    def work_through(self, worker_id, decide):
        """`query-worker` を模す。`next` で依頼を受け、依頼を読み、`decide(依頼)` の答えを `answer` で渡すことを、
        `done` まで繰り返す。読んだ依頼を、受け取った順に返す。"""
        items = []
        code, step = self.run_worker("next", worker_id)
        self.assertEqual(code, 0, step)
        while not step["done"]:
            item = json.loads(Path(step["item_path"]).read_text(encoding="utf-8"))
            items.append(item)
            code, step = self.run_worker(
                "answer", worker_id, json.dumps(decide(item), ensure_ascii=False)
            )
            self.assertEqual(code, 0, step)
        return items

    def embed(self, key, paths, *extra):
        return self.run_script(
            embed_dlid, "--key", key, "--paths", *paths, *extra, command="apply"
        )

    def check_toc(self, key, paths):
        return self.run_script(check_toc, "--key", key, "--paths", *paths)

    def check_impact(self, key, paths):
        return self.run_script(check_impact, "--key", key, "--paths", *paths)

    def check_links(self, key, paths):
        return self.run_script(check_links, "--key", key, "--paths", *paths)

    def resolve(self, *dlids):
        return self.run_script(resolve_dlid, *dlids)

    def resolve_one(self, dlid):
        code, result = self.resolve(dlid)
        self.assertEqual(code, 0, result)
        return result["results"][0]

    def advance(self, key, paths, *extra):
        return self.run_script(
            index_docs, "--key", key, "--paths", *paths, *extra, command="advance"
        )

    def submit(self, key, paths, build_id, doc_id, values=None):
        return self.run_script(
            index_docs,
            "--key",
            key,
            "--paths",
            *paths,
            "--build-id",
            build_id,
            *submit_args(doc_id, values),
            command="submit",
        )

    def build(self, key, paths, values=None):
        """AI を介さず、生成結果を固定値で差し込んで構築を完了させる。最後の（終了コード、結果）を返す。

        生成を依頼された[文書 ID]は `self.requested` に積まれる。
        """
        self.requested = []
        build_id = None
        for _ in range(10):
            extra = [] if build_id is None else ["--build-id", build_id]
            code, result = self.advance(key, paths, *extra)
            if code != 0 or result["action"] == "done":
                return code, result
            build_id = result["build_id"]
            for batch in result["batches"]:
                for document in batch["documents"]:
                    self.requested.append(document["doc_link_id"])
                    scode, sresult = self.submit(
                        key, paths, build_id, document["doc_link_id"], values
                    )
                    self.assertEqual(scode, 0, sresult)
        self.fail("構築が終わらない")

    def build_ok(self, key, paths, values=None):
        code, result = self.build(key, paths, values)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["action"], "done", result)
        return result

    def impact_documents(self, key, paths):
        """`check-impact` が返した（参照先の[DLID]、title の記録、現在ハッシュ）の並び。"""
        code, result = self.check_impact(key, paths)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["status"], "up_to_date", result)
        return [
            (
                referrer["target_dlid"],
                referrer["recorded_hash"],
                referrer["current_hash"],
            )
            for changed in result["changed_documents"]
            for referrer in changed["referrers"]
        ]
