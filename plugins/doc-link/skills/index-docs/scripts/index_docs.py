# /// script
# requires-python = ">=3.15"
# dependencies = [
#     "markdown-it-py>=4.2.0",
# ]
#
# [tool.uv]
# exclude-newer = "3 days"
# ///
"""[ToC]を構築・再構築する（index-docs の入口 script）。

SKILL と `toc-updater` は、この script を 1 本だけ呼ぶ。script は構築の段階（DES-004 の B-01〜B-07）を進められる所まで進め、
次に SKILL が行うこと（`action`）を返す。SKILL はそれに従って動き、終えたら `advance` をもう一度呼ぶ。
初回と再開を区別しない。今どの段階かは、前の呼び出しの自己申告ではなく、毎回、現物と管理状態（`.doc-link/`）から
判定し直す。段階の前提は `build_state_machine`（`BuildSession`）のガードで検査し、許可されない遷移を拒否する。
対象の指定は `target_spec`、ID 確認と変更集合は `change_set`、更新計画と[文書情報]の保存は `update_plan`、
生成結果の検証は `update_plan` が使う `ai_output_validator`、参照の検査は `reference_check`、候補の組み立て・検査・
一括公開は `toc_candidate`、管理状態の書き込みは `state_store` を使う。このファイルは段階の処理を再実装せず、
順に呼んで結果をつなぐだけである。[Index 対象文書]は書き換えない。[DLID]を発行・保存しない。

## 検索基盤（DES-011、REQ-006）

`advance` は、構築の入口で[検索基盤]を決める（`backend_select`。設定ファイル `.doc-link/config.json` の `backend` と、
[doc-db]への接続の可否）。[強制スイッチ]の呼び出しごとの指定（引数）は無い。

[doc-db]に接続できないとき（実行ファイルはある）、script は[doc-db]を起動せずに止まり、`action` が `confirm_docdb_startup`
（利用者に、起動してよいかを聞く）の結果を返す（終了コード 0。何も書き込まない）。利用者の回答は、build-id を付けない
最初の呼び出しの `--docdb-startup` で渡す。`start` は起動してよい（期限付きの再接続）、`toc` は起動せず今回は[ToC]で続ける。
許可を得て起動したのに接続できなかったときは、切り替えずに `action` が `docdb_startup_failed`（起動できなかったこと・原因の
分類・起動の command・選択肢）の結果を返す。実行ファイルが無い・[doc-db]の設定から `port` を得られないときは、起動できない
ので、許可を求めずに[ToC]へ切り替える。

- `toc`（強制スイッチ、または[doc-db]を使えず[自動切り替え]・利用者の選択で切り替えた）: 現在の構築のとおり、`toc-updater` に[AI 生成
  フィールド]を作らせる。[doc-db]へ触れない。切り替えたときは、`backend_switch` に通知を持つ
- `doc-db`: 機械取得の構築（B-01〜B-07）だけを行い、[AI 生成フィールド]は作らない（`update_plan.apply_unfilled`。
  候補の検査は[文書情報]の[内容ハッシュ]を求めない）。[確定 ToC]を公開した後、[doc-db]の同期（`docdb_sync`）を行う。
  同期が成功したら、`done` を返す。同期が接続できない (a)・OpenAI の失敗 (b) で切り替わったときは、[ToC]として続ける:
  「[AI 生成フィールド]が要る文書」があれば、`invoke_toc_updater` を返し（`backend` は `toc`、`backend_switch` に通知）、
  以後の `advance --build-id` は、作業状態に記録した基盤で続ける（[doc-db]へ再接続しない）。同期が障害のときは、
  終了コード 4 を返す（[確定 ToC]は確定済み）

`advance` の結果は、`backend`（`doc-db` か `toc`）・`forced`・`startup`・`backend_switch`（切り替えが無ければ `null`）を持つ。
`doc-db` のときは、`docdb_sync`（同期の結果。一覧の件数・除いた文書の件数・[doc-db]の処理の件数）も持つ。

## 呼び出し方

4 つのサブコマンドを持つ。すべて `--project-root`（既定は現在のディレクトリ）を取る。`advance` と `submit` は、
`--key` と[Index 対象指定]（`--paths`・`--dirs`・`--exclude`・`--all` など。規則は `target_spec`）も取る。
単体モード（`--all`・引数なし）の[ToC 識別キー]は、予約キー `all` である。`request` と `deliver` は `toc-updater`
（カスタム Agent）が呼ぶので、識別値（構築 ID と[文書 ID]）だけを取り、対象指定を取らない（記録した作業状態から
読む）。

- `advance [--build-id ID]`: 段階を進め、次の行動を返す。`--build-id` は、直前の `advance` が返した値をそのまま渡す
  （AI は組み立てない）。初回は付けない
- `submit --build-id ID --doc-id DOC_ID [--title T] [--purpose P] [--summary S]... [--applicable-tasks A]...
  [--keywords K]...`: `toc-updater` の生成結果を、1 文書分ずつ差し込む。これが、生成結果を検証器
  （`ai_output_validator.validate_generated_fields`）と[文書情報]の保存（`update_plan.store_generated`）へ渡す
  唯一の入力である。AI を介さずに固定値を差し込むテストも、`toc-updater` の結果の受け取り（TASK-014）も、この入力を使う。
  値は引数のまま変形されず届く（改行・引用符・非 ASCII を含んでよい）。値が `-` で始まるときは、`--summary=-値` の
  形で渡す。H1 の見出しからタイトルを取れる文書は、`--title` を省いてよい（タイトルは見出しを優先する）
- `request --build-id ID --doc-id DOC_ID [--doc-id DOC_ID]...`: `toc-updater` が、受け取った識別値（構築 ID と
  [文書 ID]の並び）から、依頼のファイルの絶対パスを得る。標準出力は `{"path": …}` だけで、依頼の本文を載せない。
  依頼は `advance` が `invoke_toc_updater` を返す前に、script が組み立てて置いて公開してある。依頼として公開されて
  いない[文書 ID]の組には、パスを返さずに終了コード 1 で失敗する
- `deliver --build-id ID --doc-id DOC_ID --exit-value V [--title T] [--purpose P] [--summary S]...
  [--applicable-tasks A]... [--keywords K]...`: `toc-updater` が、1 文書分の生成結果と終了の値を渡す。終了の値は
  文字列で、正常は `"0"`、エラー値は `"source_unreadable"`（対象文書を読めなかった）だけである。`"0"` のときだけ、
  値を `submit` と同じ検証・保存（`_store_generated`）へ渡す。`"0"` 以外・定義に無い値・終了の値が無い（`--exit-value`
  を付けない）ときは、その文書の生成失敗として、終了コード 3 で失敗する。成否の判定は script が行う

## `advance` が返す `action`

- `invoke_toc_updater`: 生成が必要な文書がある。`batches` は `toc-updater` への依頼の単位で、1 件が同じディレクトリの
  最大 3 文書（`max_documents_per_agent`）、1 回に最大 10 件（`max_concurrent_agents`）である。各文書は `doc_link_id` と、
  生成するフィールドごとの記述上限 `limits`（`L`）だけを持つ。内部許容上限・係数・余白は含まない。
  `remaining_documents` は、この回に含めなかった生成対象の数で、全部の完了後の `advance` が続きを返す。
  `await_completion` が真のとき、SKILL は起動した Agent の完了を待ってから、`build_id` を付けて `advance` を呼ぶ
  （完了の待機は、この `action` に含まれる SKILL の動作である）。依頼の中身（対象文書の絶対パスと `limits`）は、
  この script が組み立てて置く（下の「`toc-updater` との受け渡し」）。依頼の元になる文書のパスと生成する
  フィールドは、`build_id` の作業状態に記録する
- `done`: [確定 ToC]を一括して公開した。判断に要る項目と件数だけを返し、全件の明細は明細ファイルへ書く（D-059）。
  確定結果（`version`・`published`）、変更の種別ごとの件数（`change_summary`）、生成した文書の件数（`generated_count`）、
  参照検査結果の分類ごとの件数（`reference_check.summary`）、除外した文書の件数（`excluded_counts`: `missing`・
  `duplicate`）、問題と警告（`problems`・`warnings`）、明細ファイルの絶対パス（`detail_path`）を返す。一致以外の
  参照の検出事項と、除外した文書の一覧は、件数に比例して大きくなるので、標準出力に載せず、明細ファイルへ書く。
  同じ入力の再実行は、[確定 ToC]・[文書情報]を書き換えず（`published` が偽）、
  生成対象を出さない。`change_summary` は、文書（`documents`: `new`・`content_changed`・`references_changed`・
  `path_changed`・`departed`・`unchanged`）とセクション（`sections`: `added`・`deleted`・`moved`・`heading_changed`・
  `body_changed`）の件数を持つ。複数の種別に該当する文書・セクションは、それぞれの種別に数え、該当が無い種別も 0 で
  持つ。`unchanged` は種別を持たない文書の数である。ほかに、初回構築か（`first_build`）と、[確定 Index 対象リスト]の
  件数（`confirmed_documents`）を持つ

## 失敗

失敗（B-08）は、候補を公開せず、旧[確定 ToC]を維持する。エラーの JSON に、段階（`stage`）、対象の[文書 ID]・パス・
フィールド・原因（`problems`）、失敗の時点で[確定 ToC]のファイルがあるか（`confirmed_toc_present`）、失敗した
段階の状態（`failed_from`）を持つ。自動では再試行せず、`advance` を呼び直すことが再実行（B-09）である。確定済みの
[文書情報]は戻さない。`submit` の生成結果が検証に通らないときは、その文書の生成失敗として、直ちに同じ形で終了コード 3 を返す。
その失敗は作業状態に残り、次の `advance` が構築を失敗として報告する（ほかの Agent の `submit` は止めない）。

## 作業状態（`.temp/doc-link/index-docs/`）

生成が必要なとき、`advance` が識別値 `BUILD-<8 桁の 16 進>` を生成し、`<識別値>.json` を置く。内容は
`toc_key`・`target_spec`・今回の依頼に含めた文書（`doc_link_id`・`path`・`generate_fields`）・これまでに依頼した
文書の[文書 ID]（`generated`）である。`submit` の失敗は、`<識別値>.failed-<符号化した文書 ID>.json` に文書ごとに
置く（`submit` は同時に走るので、共有のファイルを更新しない）。どの文書の結果を受け取ったかは、作業状態に持たず、
[文書情報]が現在の[内容ハッシュ]になっているかで判定する。構築が終わったとき（完了・失敗）に、識別値の作業状態を
すべて削除する。新しい構築を始めるとき、同じ[ToC 識別キー]の古い作業状態も削除する。作業状態が無くても、管理状態と
現物から再判定して再開できる（識別値を付けずに `advance` を呼べばよい）。識別値を付けたのに作業状態が無い・
[ToC 識別キー]か対象指定が合わないときは、前段の申告を信用せず、拒否する。

## 完了結果の明細ファイル

`done` の前に、script が全件の明細を `.temp/doc-link/index-docs/detail-<符号化した[ToC 識別キー]>.json` へ書く
（D-059）。内容は、`toc_key`・`version`・`generated_documents`（生成した文書の[文書 ID]の一覧）・`change_set`
（`first_build`・`confirmed_documents`・`excluded`・`documents`・`sections`。文書・セクションごとの変更前後の値を
含む）・`reference_findings`（一致以外の参照の検出事項。参照元のパス・行・[DLID]の順）である。書き込みは共通モジュール
`detail_file` を使う。[ToC 識別キー]ごとに 1 つで、同じキーの次の構築が置き換える。構築が終わっても削除しない（呼び出し元が
読むため）。一時ファイルへ書き終えてから 1 回の置き換えで公開する。呼び出し元は、明細が要るときだけ、`detail_path`
のファイルを読む。

## 移動の記録

移動（`path_changed`）だけは、比べる相手が構築の途中で書き換わる。[ToC]はパスを持たず、パスは[文書情報]が持ち、
構築の最初の `advance` で新しくなる。そのため、あとの比較には移動が現れない。そこで `advance` は、移動を検出する
たびに、パスを新しくする前に、`.temp/doc-link/index-docs/moves-<符号化した[ToC 識別キー]>.json` へ、
`{"doc_link_id", "old_path", "new_path"}` を足す（同じ組は足さない。足すものが無ければ書かない）。この記録は、構築の
作業状態（`BUILD-*`）とは別で、`build_id` なしのやり直しをまたいで残る。完了結果の変更集合は、最後の比較に、
記録した移動を合わせて作る（`ChangeSet.with_first_old_paths`）。文書ごとに、記録の最初の `old_path` と現在のパスを
比べ、違えば `path_changed`、同じなら（移動して元に戻した場合）移動なしとする。記録は、[確定 ToC]を公開した後に
削除し、構築が失敗したときは残す。複数のキーで同じ文書を使うとき、移動を報告するのは、[文書情報]のパスを新しくした
構築で、あとに構築するキーには現れない。

## `toc-updater` との受け渡し

`toc-updater` へ運ぶのは、識別値（構築 ID と[文書 ID]の並び。最大 3）だけである。依頼は、`advance` が `batches` の 1 件ごとに
`.temp/doc-link/index-docs/<構築 ID>.exchange/` の下へ組み立てて置く。置き方は、一時ファイルへ書き終えてから 1 回の
置き換えで公開する（組み立て途中のものを読ませない）。依頼の中身は `{"documents": [{"doc_link_id", "path"（絶対パス）,
"limits"}]}` だけで、内部許容上限・係数・余白を含まない。生成結果の保存を終えた文書は、同じ場所に結果（`doc_link_id`・
終了の値・保存の状態）を置く。この場所は、次の波の依頼を置くとき、および構築が終わったとき（完了・失敗）に、
構築の作業状態といっしょにすべて削除する。

## 標準出力

終了コード 0 のとき結果の JSON、それ以外（2 を除く）のときエラーの JSON（`errors` は自然文の配列）を返す。
次の行動（`action`）を返すことは操作の完了であり、終了コード 0 である。

## 終了コード

| code | 意味                                                                                                                                                  |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0    | 操作が完了した（`advance` は次の行動を返した。`submit`・`deliver` は生成結果を保存した。`request` は依頼のパスを返した）                              |
| 1    | 区別のないエラー（対象指定の拒否、設定ファイルを受理できない、識別値・状態が合わない、段階の前提が満たされない、生成対象でない文書への `submit`・`deliver`、公開されていない依頼） |
| 2    | 引数を受理できない（`argparse`）                                                                                                                      |
| 3    | 構築が失敗した（B-08）。文書を読めない、[確定 ToC]・[文書情報]を読めない、生成結果が検証に通らない・届かない、`deliver` の終了の値が `"0"` でない・無い、候補の検査・公開の失敗。旧[確定 ToC]は残る |
| 4    | [doc-db]を使う構築で、[確定 ToC]は確定したが、[doc-db]の同期が障害で失敗した（接続できない (a)・OpenAI の失敗 (b) 以外の失敗。切り替えない）。`docdb_sync.errors` に原因 |

## 仕様の解釈（設計書が値や形式を定めていない点）

- 段階の判定: 生成が必要な文書（`update_plan` の生成対象）が残っていれば、情報確定（B-04）に進まず、依頼を返す。
  残っていなければ、そのまま参照検査・候補の検査・公開まで進める
- 失敗の段階（`stage`）: `target_scope`（対象を展開できない。読めないディレクトリがある。B-01）、`id_confirmation`（文書を読めない。B-02）、`change_set`（[確定 ToC]・[文書情報]を読めない。B-03）、
  `update_plan`・`path_update`（B-04 の前。パスを更新できない、移動を記録できない・記録を読めない）、`information`（生成結果が検証に通らない・届かない。B-04）、
  `reference_check`（参照元を読めない。B-05）、`candidate_assembly`・`candidate_validation`・`publish`（`toc_candidate`
  の段階。B-06・B-07）、`result_detail`（明細ファイルを書けない。[確定 ToC]を公開する前に書くので、書けなければ公開しない）
- 構築を失敗にする生成の失敗: 依頼した文書のうち、`advance` の再呼び出しの時点で生成対象のままの文書（結果が届かない、
  または検証に通らなかった）。Agent の完了の後に呼ぶ前提なので、待たず失敗にする
- 対象文書の依頼の分け方: 生成対象を、ディレクトリごとにまとめて 3 文書ずつに分け、ディレクトリ名の昇順に並べ、
  先頭の 10 件を 1 回の依頼にする
- 検査の時点: [文書情報]・[確定 ToC]には記録しない。参照検査の結果と最終検査状態が前回と同じなら、保存内容も同じなので、
  再実行で不要な差分を作らない（NFR-003）。参照検査を実行した時点は、明細ファイルの検出事項の `scope` が持つ
- `reference_check` の `findings`: 一致（`match`）以外の参照の検査結果。件数は `summary` に分類ごとに持つ
- 依頼の置き場と名前: `<構築 ID>.exchange/request-<符号化した、昇順に並べて "+" でつないだ[文書 ID]>.json`。
  `toc-updater` が受け取る[文書 ID]の並びの順に依らず、同じ組は同じファイルに当たる。結果は
  `result-<符号化した[文書 ID]>.json`。作業状態の `*.json` と分けて、サブディレクトリに置く
- `deliver` の失敗（終了の値が `"0"` でない・無い、検証に通らない）は、`submit` の検証失敗と同じ、文書ごとの失敗の
  ファイルに残し、次の `advance` が構築を失敗として報告する（B-04・B-08）。再試行・`toc-updater` への差し戻しはしない。
  生成対象でなくなった文書（結果を受け取り済み）への `deliver` は、失敗を残さず拒否する
- 終了の値の報告・拒否理由には、フィールド名と記述上限 `L` 以外の検証の境界を含めない
"""

import argparse
import json
import os
import posixpath
import re
import secrets
import shutil
import sys
from pathlib import Path

# 共通モジュールは、プラグイン直下の scripts/（このファイルの 3 つ上の scripts/）にある。
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import backend_config  # noqa: E402
import backend_select  # noqa: E402
import build_state_machine as bsm  # noqa: E402
import change_set as cs  # noqa: E402
from clock import utc_now  # noqa: E402
import detail_file  # noqa: E402
import docdb_contract  # noqa: E402
import docdb_sync  # noqa: E402
import script_output  # noqa: E402
import state_store  # noqa: E402
import target_spec  # noqa: E402
import toc_candidate  # noqa: E402
import update_plan  # noqa: E402
from reference_check import (  # noqa: E402
    STATUS_ABSENT,
    STATUS_MATCH,
    DirectoryScanner,
    ReferenceCheckError,
    build_index,
    check_document,
    relocate,
)

SKILL = "index-docs"
WORK_DIR_PARTS = (*state_store.TEMP_ROOT, SKILL)

EXIT_BUILD_FAILED = 3
EXIT_SYNC_FAILED = 4

ACTION_INVOKE = "invoke_toc_updater"
ACTION_DONE = "done"

# `toc-updater` が渡す終了の値（文字列）。正常は "0"。エラー値は閉じた集合で、これだけである。
EXIT_VALUE_NORMAL = "0"
EXIT_VALUE_SOURCE_UNREADABLE = "source_unreadable"

MAX_DOCUMENTS_PER_AGENT = 3
MAX_CONCURRENT_AGENTS = 10

STAGE_SCOPE = "target_scope"
STAGE_IDS = "id_confirmation"
STAGE_CHANGES = "change_set"
STAGE_PLAN = "update_plan"
STAGE_PATHS = "path_update"
STAGE_INFORMATION = "information"
STAGE_REFERENCES = "reference_check"
STAGE_DETAIL = "result_detail"

MOVES_PREFIX = "moves-"

_BUILD_ID = re.compile(r"BUILD-[0-9a-f]{8}")


class Rejected(Exception):
    """入力・識別値・段階の前提を受理できない（終了コード 1）。`errors` に自然文の理由を持つ。"""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class BuildFailed(Exception):
    """構築の段階の処理が失敗した（B-08。終了コード 3）。`publication` は、候補の検査・公開の失敗（P-03）のとき真。"""

    def __init__(
        self,
        stage: str,
        problems: list[toc_candidate.CandidateProblem],
        publication: bool = False,
    ):
        super().__init__(stage)
        self.stage = stage
        self.problems = problems
        self.publication = publication


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subcommands = parser.add_subparsers(dest="command", required=True)

    advance = subcommands.add_parser(
        "advance", help="段階を進め、次に SKILL が行うことを返す"
    )
    advance.add_argument("--project-root", default=os.getcwd())
    advance.add_argument("--build-id", default=None)
    advance.add_argument(
        "--docdb-startup",
        choices=backend_select.STARTUP_CHOICES,
        default=None,
        help="doc-db に接続できないときの利用者の回答（start＝起動してよい、toc＝今回は ToC で続ける）。build-id なしの呼び出しだけで使う",
    )
    target_spec.add_target_arguments(advance)

    submit = subcommands.add_parser("submit", help="生成結果を 1 文書分ずつ差し込む")
    submit.add_argument("--project-root", default=os.getcwd())
    submit.add_argument("--build-id", required=True)
    submit.add_argument("--doc-id", required=True)
    submit.add_argument("--title", default=None)
    submit.add_argument("--purpose", default=None)
    submit.add_argument("--summary", action="append", default=None)
    submit.add_argument("--applicable-tasks", action="append", default=None)
    submit.add_argument("--keywords", action="append", default=None)
    target_spec.add_target_arguments(submit)

    request = subcommands.add_parser(
        "request", help="toc-updater が、依頼のファイルの絶対パスを得る"
    )
    request.add_argument("--project-root", default=os.getcwd())
    request.add_argument("--build-id", required=True)
    request.add_argument("--doc-id", action="append", required=True)

    deliver = subcommands.add_parser(
        "deliver", help="toc-updater が、1 文書分の生成結果と終了の値を渡す"
    )
    deliver.add_argument("--project-root", default=os.getcwd())
    deliver.add_argument("--build-id", required=True)
    deliver.add_argument("--doc-id", required=True)
    deliver.add_argument("--exit-value", default=None)
    deliver.add_argument("--title", default=None)
    deliver.add_argument("--purpose", default=None)
    deliver.add_argument("--summary", action="append", default=None)
    deliver.add_argument("--applicable-tasks", action="append", default=None)
    deliver.add_argument("--keywords", action="append", default=None)
    return parser


# --- 作業状態 ------------------------------------------------------------------


def _work_dir(root: Path) -> Path:
    return root.joinpath(*WORK_DIR_PARTS)


def _build_path(root: Path, build_id: str) -> Path:
    return _work_dir(root) / f"{build_id}.json"


def _failure_path(root: Path, build_id: str, doc_id: str) -> Path:
    return (
        _work_dir(root)
        / f"{build_id}.failed-{state_store.encode_name(doc_id)}{state_store.FILE_SUFFIX}"
    )


def _exchange_dir(root: Path, build_id: str) -> Path:
    """`toc-updater` との受け渡し（依頼と結果）の置き場。構築の作業状態の `*.json` とは分ける。"""
    return _work_dir(root) / f"{build_id}.exchange"


def _clear_exchange(root: Path, build_id: str) -> None:
    directory = _exchange_dir(root, build_id)
    if directory.is_dir():
        shutil.rmtree(directory)


def _exchange_name(prefix: str, doc_ids: list[str]) -> str:
    """識別値（[文書 ID]の並び）から、受け渡しのファイル名を決める。並びの順に依らない。"""
    try:
        encoded = state_store.encode_name("+".join(sorted(doc_ids)))
    except state_store.StateStoreError as exc:
        raise Rejected([f"[文書 ID]を受け渡しの名前にできない: {exc}"]) from exc
    return f"{prefix}-{encoded}{state_store.FILE_SUFFIX}"


def _request_path(root: Path, build_id: str, doc_ids: list[str]) -> Path:
    return _exchange_dir(root, build_id) / _exchange_name("request", doc_ids)


def _result_path(root: Path, build_id: str, doc_id: str) -> Path:
    return _exchange_dir(root, build_id) / _exchange_name("result", [doc_id])


def _build_files(root: Path, build_id: str) -> list[Path]:
    directory = _work_dir(root)
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.name == f"{build_id}.json"
        or path.name.startswith(f"{build_id}.failed-")
    )


def _remove_build(root: Path, build_id: str) -> None:
    for path in _build_files(root, build_id):
        path.unlink(missing_ok=True)
    _clear_exchange(root, build_id)


def _remove_old_builds(root: Path, toc_key: str) -> None:
    """同じ[ToC 識別キー]の、前の構築の作業状態を削除する。読めない作業状態は、判定できないので残す。"""
    directory = _work_dir(root)
    if not directory.is_dir():
        return
    for path in sorted(directory.iterdir()):
        if _BUILD_ID.fullmatch(path.stem) is None or path.suffix != ".json":
            continue
        try:
            recorded = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(recorded, dict) and recorded.get("toc_key") == toc_key:
            _remove_build(root, path.stem)


def _write_work_file(root: Path, path: Path, value: dict) -> None:
    try:
        state_store.write_if_changed(root, SKILL, path, state_store.serialize(value))
    except state_store.StateStoreError as exc:
        raise BuildFailed(
            STAGE_INFORMATION,
            [toc_candidate.CandidateProblem(None, str(path), None, str(exc))],
        ) from exc


def _write_detail(
    root: Path,
    toc_key: str,
    version: int,
    changes: cs.ChangeSet,
    generated: list[str],
    reference_findings: list[dict],
) -> str:
    """完了結果の全件（変更集合・生成した文書の一覧・一致以外の参照の検出事項）を明細ファイルへ書き、
    その絶対パスを返す。

    [確定 ToC]を公開する前に呼ぶ。書けないときは、公開せずに構築の失敗（`result_detail`）にする。
    """
    detail = {
        "toc_key": toc_key,
        "version": version,
        "generated_documents": list(generated),
        "change_set": changes.to_dict(),
        "reference_findings": reference_findings,
    }
    try:
        return detail_file.write_detail(root, SKILL, toc_key, detail)
    except state_store.StateStoreError as exc:
        raise BuildFailed(
            STAGE_DETAIL,
            [toc_candidate.CandidateProblem(None, toc_key, None, str(exc))],
        ) from exc


def _moves_path(root: Path, toc_key: str) -> Path:
    """移動の記録。[ToC 識別キー]ごとに 1 つで、構築の作業状態（`BUILD-*`）とは別に、やり直しをまたいで残る。"""
    return (
        _work_dir(root)
        / f"{MOVES_PREFIX}{state_store.encode_name(toc_key)}{state_store.FILE_SUFFIX}"
    )


def _moves_failure(toc_key: str, cause: str) -> BuildFailed:
    return BuildFailed(
        STAGE_PATHS,
        [toc_candidate.CandidateProblem(None, toc_key, None, cause)],
    )


def _read_moves(root: Path, toc_key: str) -> list[dict]:
    """記録した移動（[文書 ID]・前のパス・後のパス）を、記録した順に返す。記録が無ければ空。"""
    try:
        path = _moves_path(root, toc_key)
        try:
            recorded = json.loads(path.read_bytes().decode("utf-8"))
        except FileNotFoundError:
            return []
        return list(recorded["moves"])
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        state_store.StateStoreError,
    ) as exc:
        raise _moves_failure(toc_key, f"移動の記録を読めない: {exc}") from exc


def _record_moves(root: Path, toc_key: str, changes: cs.ChangeSet) -> None:
    """検出した移動を、パスを新しくする前に、記録へ足す。同じ組は足さない。足すものが無ければ書かない。"""
    detected = [
        {
            "doc_link_id": document.doc_link_id,
            "old_path": document.old_path,
            "new_path": document.new_path,
        }
        for document in changes.documents
        if cs.CHANGE_PATH in document.kinds
    ]
    if not detected:
        return
    moves = _read_moves(root, toc_key)
    added = [move for move in detected if move not in moves]
    if not added:
        return
    try:
        state_store.write_if_changed(
            root,
            SKILL,
            _moves_path(root, toc_key),
            state_store.serialize({"toc_key": toc_key, "moves": moves + added}),
        )
    except state_store.StateStoreError as exc:
        raise _moves_failure(toc_key, f"移動を記録できない: {exc}") from exc


def _first_old_paths(moves: list[dict]) -> dict[str, str]:
    """[文書 ID]ごとに、記録の最初の前のパスを返す。"""
    first: dict[str, str] = {}
    for move in moves:
        first.setdefault(move["doc_link_id"], move["old_path"])
    return first


def _clear_moves(root: Path, toc_key: str) -> None:
    """[確定 ToC]を公開した後に、記録を削除する。公開済みなので、構築の失敗にしない（`_remove_build` と同じ）。"""
    _moves_path(root, toc_key).unlink(missing_ok=True)


def _read_build(root: Path, build_id: str) -> dict:
    """識別値に対応する作業状態を読む。無い・読めない・識別値が合わないときは拒否する。"""
    if _BUILD_ID.fullmatch(build_id) is None:
        raise Rejected([f"識別値の形式が正しくない: {build_id}"])
    path = _build_path(root, build_id)
    try:
        build = json.loads(path.read_bytes().decode("utf-8"))
    except FileNotFoundError as exc:
        raise Rejected(
            [f"識別値に対応する構築が無い（前段の結果として受理できない）: {build_id}"]
        ) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Rejected([f"識別値の作業状態を読めない: {build_id}: {exc}"]) from exc
    if not isinstance(build, dict) or build.get("build_id") != build_id:
        raise Rejected([f"識別値の作業状態が合わない: {build_id}"])
    return build


def _load_build(
    root: Path, build_id: str, toc_key: str, spec: target_spec.TargetSpec
) -> dict:
    """識別値に対応する作業状態を読み、[ToC 識別キー]・対象指定が合うことを確かめる。合わなければ拒否する。"""
    build = _read_build(root, build_id)
    if build.get("toc_key") != toc_key or build.get("target_spec") != spec.to_dict():
        raise Rejected(
            [f"識別値の構築と[ToC 識別キー]・対象指定が合わない: {build_id}"]
        )
    return build


def _read_failures(root: Path, build_id: str) -> list[dict]:
    failures = []
    for path in _build_files(root, build_id):
        if ".failed-" not in path.name:
            continue
        try:
            failures.append(json.loads(path.read_bytes().decode("utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BuildFailed(
                STAGE_INFORMATION,
                [toc_candidate.CandidateProblem(None, str(path), None, str(exc))],
            ) from exc
    return failures


# --- 段階 ----------------------------------------------------------------------


def _change_problems(exc: cs.ChangeFailure) -> list[toc_candidate.CandidateProblem]:
    return [
        toc_candidate.CandidateProblem(
            None,
            problem.path,
            None,
            problem.reason
            + (f"（{problem.state_kind}）" if problem.state_kind else ""),
        )
        for problem in exc.problems
    ]


def _prepare(
    root,
    spec,
    toc_key,
    session: bsm.BuildSession,
    write_paths: bool,
    backend: str = backend_select.BACKEND_TOC,
):
    """対象確定（B-01）・ID 確認（B-02）・変更確定（B-03）と更新計画を行う。失敗は `BuildFailed`。

    `backend` が `doc-db` のとき、`write_paths` なら、生成対象の文書の[文書情報]を、AI に生成させずに整える
    （`update_plan.apply_unfilled`。[AI 生成フィールド]を作らない）。
    """
    expansion = target_spec.expand(spec, root)
    unreadable = [
        problem
        for problem in expansion.problems
        if problem.reason == target_spec.PROBLEM_UNREADABLE
    ]
    if unreadable:
        # 読めないディレクトリの配下の文書は一覧に入らない。[Index 対象リスト]を確定できないので、構築を失敗にする
        # （一覧に無い文書を、対象離脱として[確定 ToC]から除かない）
        raise BuildFailed(
            STAGE_SCOPE,
            [
                toc_candidate.CandidateProblem(
                    None, problem.path, None, "ディレクトリを読めない"
                )
                for problem in unreadable
            ],
        )
    session.apply(bsm.EVENT_EXPAND_SCOPE, bsm.BuildFacts(scope_validated=True))
    try:
        changes = cs.build_change_set(root, toc_key, expansion.files)
    except cs.ChangeFailure as exc:
        if exc.kind == cs.FAILURE_DOCUMENT_UNREADABLE:
            raise BuildFailed(STAGE_IDS, _change_problems(exc)) from exc
        session.apply(bsm.EVENT_CONFIRM_IDS, bsm.BuildFacts(frontmatter_read=True))
        raise BuildFailed(STAGE_CHANGES, _change_problems(exc)) from exc
    session.apply(bsm.EVENT_CONFIRM_IDS, bsm.BuildFacts(frontmatter_read=True))
    session.apply(bsm.EVENT_COMPARE, bsm.BuildFacts(comparison_succeeded=True))
    try:
        plan = update_plan.build_update_plan(root, changes)
    except cs.ChangeFailure as exc:
        raise BuildFailed(STAGE_PLAN, _change_problems(exc)) from exc
    if write_paths:
        # 移動は、パスを新しくする前に記録する。あとの比較には、移動が現れない
        _record_moves(root, toc_key, changes)
        outcomes = update_plan.apply_path_updates(root, SKILL, plan)
        if backend == backend_select.BACKEND_DOCDB:
            outcomes += update_plan.apply_unfilled(root, SKILL, plan)
        failed = [
            outcome
            for outcome in outcomes
            if outcome.status == update_plan.STATUS_FAILED
        ]
        if failed:
            raise BuildFailed(
                STAGE_PATHS,
                [
                    toc_candidate.CandidateProblem(
                        outcome.doc_link_id, outcome.path, failure.field, failure.reason
                    )
                    for outcome in failed
                    for failure in outcome.failures
                ],
            )
    return expansion, changes, plan


def _batches(targets) -> list[list]:
    """生成対象を、同じディレクトリの最大 3 文書ずつに分ける（ディレクトリ名の昇順）。"""
    groups: dict[str, list] = {}
    for target in targets:
        groups.setdefault(posixpath.dirname(target.path), []).append(target)
    batches = []
    for directory in sorted(groups):
        documents = groups[directory]
        for start in range(0, len(documents), MAX_DOCUMENTS_PER_AGENT):
            batches.append(documents[start : start + MAX_DOCUMENTS_PER_AGENT])
    return batches


def _check_generation_received(root, build: dict, targets) -> None:
    """依頼した文書の結果が届いていないとき、または検証に通らなかったときは、構築を失敗にする（B-04）。"""
    failures = _read_failures(root, build["build_id"])
    requested = {entry["doc_link_id"] for entry in build["documents"]}
    problems: list[toc_candidate.CandidateProblem] = []
    failed_ids = set()
    for failure in failures:
        failed_ids.add(failure["doc_link_id"])
        for item in failure["failures"]:
            problems.append(
                toc_candidate.CandidateProblem(
                    failure["doc_link_id"],
                    failure.get("path"),
                    item["field"],
                    item["reason"],
                )
            )
    for target in targets:
        if target.doc_link_id in requested and target.doc_link_id not in failed_ids:
            problems.append(
                toc_candidate.CandidateProblem(
                    target.doc_link_id,
                    target.path,
                    None,
                    "生成結果が届いていない",
                )
            )
    if problems:
        raise BuildFailed(STAGE_INFORMATION, problems)


def _write_requests(root: Path, build_id: str, wave: list[list]) -> None:
    """`toc-updater` への依頼を、`batches` の 1 件ごとに組み立てて置く。置き換えで公開し、途中のものを読ませない。

    中身は、対象文書の絶対パスと記述上限 `L`（`limits`）だけである。
    """
    for batch in wave:
        try:
            path = _request_path(
                root, build_id, [document.doc_link_id for document in batch]
            )
        except Rejected as exc:
            raise BuildFailed(
                STAGE_INFORMATION,
                [
                    toc_candidate.CandidateProblem(
                        None, None, None, "; ".join(exc.errors)
                    )
                ],
            ) from exc
        _write_work_file(
            root,
            path,
            {
                "documents": [
                    {
                        "doc_link_id": document.doc_link_id,
                        "path": str(root / document.path),
                        "limits": document.limits,
                    }
                    for document in batch
                ]
            },
        )


def _build_backend_record(info: dict) -> dict:
    """構築の作業状態に記録する[検索基盤]の情報。"""
    return {
        "backend": info["backend"],
        "forced": info.get("forced", False),
        "startup": info.get("startup"),
        "switch": info.get("backend_switch"),
    }


def _info_from_build(build: dict) -> dict:
    """作業状態に記録した[検索基盤]の情報から、結果に添える情報を作る。記録が無い作業状態は、[ToC]とする。"""
    return {
        "backend": build.get("backend", backend_select.BACKEND_TOC),
        "forced": build.get("forced", False),
        "startup": build.get("startup"),
        "backend_switch": build.get("switch"),
    }


def _issue_wave(
    root, toc_key, spec, session, build: dict | None, targets, info: dict
) -> dict:
    """生成対象の依頼（1 回に最大 10 件）を、作業状態に記録して、`invoke_toc_updater` の内容を返す。

    `info` は、その構築の[検索基盤]の情報（`backend`・`forced`・`startup`・`backend_switch`）で、作業状態に記録する。
    以後の `advance --build-id` は、再判定せず、この記録で続ける。
    """
    batches = _batches(targets)
    wave = batches[:MAX_CONCURRENT_AGENTS]
    wave_documents = [document for batch in wave for document in batch]
    if build is None:
        _remove_old_builds(root, toc_key)
        build_id = "BUILD-" + secrets.token_hex(4)
        while _build_path(root, build_id).exists():
            build_id = "BUILD-" + secrets.token_hex(4)
        generated: list[str] = []
    else:
        build_id = build["build_id"]
        generated = list(build["generated"])
    generated += [document.doc_link_id for document in wave_documents]
    if build is not None:
        # 前の波の依頼と結果は、[文書情報]を確定した後なので削除する。
        _clear_exchange(root, build_id)
    _write_requests(root, build_id, wave)
    _write_work_file(
        root,
        _build_path(root, build_id),
        {
            "build_id": build_id,
            "toc_key": toc_key,
            "target_spec": spec.to_dict(),
            "documents": [
                {
                    "doc_link_id": document.doc_link_id,
                    "path": document.path,
                    "generate_fields": list(document.generate_fields),
                }
                for document in wave_documents
            ],
            "generated": generated,
            **_build_backend_record(info),
        },
    )
    return {
        **info,
        "action": ACTION_INVOKE,
        "state": session.build.state,
        "build_id": build_id,
        "toc_key": toc_key,
        "batches": [
            {
                "documents": [
                    {"doc_link_id": document.doc_link_id, "limits": document.limits}
                    for document in batch
                ]
            }
            for batch in wave
        ],
        "max_documents_per_agent": MAX_DOCUMENTS_PER_AGENT,
        "max_concurrent_agents": MAX_CONCURRENT_AGENTS,
        "remaining_documents": len(targets) - len(wave_documents),
        "await_completion": True,
    }


def _reference_report(results) -> tuple[dict, list[dict]]:
    """参照検査結果の（分類ごとの件数、一致以外の検出事項の全件）を返す。

    件数は標準出力へ、検出事項は明細ファイルへ出す（検出事項は件数に比例して大きくなるため）。
    """
    summary: dict[str, int] = {}
    findings = []
    for found in results.values():
        for result in found:
            summary[result.status] = summary.get(result.status, 0) + 1
            if result.status != STATUS_MATCH:
                findings.append(result.to_dict())
    findings.sort(
        key=lambda item: (
            item["source_path"],
            item["reference"]["line"],
            item["reference"]["dlid"],
        )
    )
    return dict(sorted(summary.items())), findings


def _relocate_absent(root: Path, files, results: dict) -> dict:
    """指定ディレクトリ内に不在だった参照を、[Index 対象リスト]の文書の中から探し直す（要件 D-062）。

    ID 未付与・ID 重複で[ToC]に入れなかった文書も、[Index 対象リスト]の文書なので探す対象である。
    不在の参照が 1 件も無ければ、対象文書を読み直さない。
    """
    if not any(
        result.status == STATUS_ABSENT for found in results.values() for result in found
    ):
        return results
    index = build_index(root, files)
    return {
        doc_id: [relocate(result, index) for result in found]
        for doc_id, found in results.items()
    }


def _candidate_failed(exc: toc_candidate.CandidateFailure) -> BuildFailed:
    return BuildFailed(exc.report.stage, list(exc.report.problems), publication=True)


def _finish(
    root,
    toc_key,
    spec,
    session,
    build,
    expansion,
    changes,
    require_ai_fields: bool = True,
) -> dict:
    """参照検査（B-05）・候補の検査（B-06）・一括公開（B-07）まで進める。

    `require_ai_fields` が偽（[doc-db]を使う構築）のとき、候補の検査は、[文書情報]の[内容ハッシュ]を求めない。
    """
    session.apply(bsm.EVENT_ACQUIRE_INFO, bsm.BuildFacts(info_acquired=True))
    now = utc_now()
    scanner = DirectoryScanner(root)
    results = {}
    problems: list[toc_candidate.CandidateProblem] = []
    for item in changes.confirmed_documents:
        try:
            results[item.doc_link_id] = check_document(
                root, item.path, checked_at=now, scanner=scanner
            )
        except ReferenceCheckError as exc:
            problems.append(
                toc_candidate.CandidateProblem(
                    item.doc_link_id, item.path, "references", str(exc)
                )
            )
    if problems:
        raise BuildFailed(STAGE_REFERENCES, problems)
    results = _relocate_absent(root, expansion.files, results)
    session.apply(
        bsm.EVENT_CHECK_REFERENCES, bsm.BuildFacts(references_classified=True)
    )

    try:
        candidate = toc_candidate.assemble_candidate(
            root, toc_key, spec, changes, results
        )
        toc_candidate.validate_candidate(
            root, candidate, changes.confirmed_documents, require_ai_fields
        )
    except toc_candidate.CandidateFailure as exc:
        raise _candidate_failed(exc) from exc
    session.apply(
        bsm.EVENT_VALIDATE_CANDIDATE, bsm.BuildFacts(required_and_consistent=True)
    )

    generated = [] if build is None else list(build["generated"])
    # 完了結果の変更集合は、最後の比較に、記録した移動を合わせて作る
    reported = changes.with_first_old_paths(
        _first_old_paths(_read_moves(root, toc_key))
    )
    reference_summary, reference_findings = _reference_report(results)
    detail_path = _write_detail(
        root, toc_key, candidate["version"], reported, generated, reference_findings
    )
    try:
        written = toc_candidate.publish_candidate(root, SKILL, candidate)
    except toc_candidate.CandidateFailure as exc:
        raise _candidate_failed(exc) from exc
    session.apply(bsm.EVENT_COMMIT, bsm.BuildFacts(commit_succeeded=True))
    _clear_moves(root, toc_key)
    if build is not None:
        _remove_build(root, build["build_id"])
    return {
        "action": ACTION_DONE,
        "state": session.build.state,
        "publication_state": session.publication.state,
        "toc_key": toc_key,
        "version": candidate["version"],
        "published": written,
        "generated_count": len(generated),
        "change_summary": reported.summary(),
        "detail_path": detail_path,
        "reference_check": {"summary": reference_summary},
        "excluded_counts": {
            reason: sum(1 for item in changes.excluded if item.reason == reason)
            for reason in (cs.REASON_MISSING, cs.REASON_DUPLICATE)
        },
        "problems": [problem.to_dict() for problem in expansion.problems],
        "warnings": list(expansion.warnings),
    }


# --- 出力 ----------------------------------------------------------------------


def _emit(payload: dict, code: int) -> int:
    """結果・エラーの JSON を `script_output` の形式で出し、指定の終了コードを返す。

    `script_output.emit_error` は `errors` だけを出して 1 を返すので、終了コード 3 で追加の情報（`stage`・
    `problems` など）を返すために、同じ書式の `emit_result` を使い、返り値は使わない。
    """
    script_output.emit_result(payload)
    return code


def _rejected(session: bsm.BuildSession, errors: list[str]) -> int:
    state = session.build.state
    if state in bsm.FAILABLE_STATES:
        session.apply(bsm.EVENT_FAIL, bsm.BuildFacts(stage_failed=True))
    return _emit(
        {"errors": errors, "state": session.build.state, "failed_from": state},
        script_output.EXIT_ERROR,
    )


def _failed(root, toc_key, session: bsm.BuildSession, failure: BuildFailed) -> int:
    failed_from = session.build.state
    session.apply(bsm.EVENT_FAIL, bsm.BuildFacts(stage_failed=True))
    if failure.publication:
        session.fail_publication(bsm.PublicationFacts(candidate_stage_failed=True))
    report = toc_candidate.FailureReport(
        stage=failure.stage,
        problems=tuple(failure.problems),
        confirmed_toc_present=toc_candidate.confirmed_toc_present(root, toc_key),
    )
    errors = [
        f"{report.stage}: {problem.doc_link_id or problem.path or '-'}: "
        f"{problem.field + ': ' if problem.field else ''}{problem.cause}"
        for problem in report.problems
    ]
    return _emit(
        {
            "errors": errors,
            "state": session.build.state,
            "failed_from": failed_from,
            **report.to_dict(),
        },
        EXIT_BUILD_FAILED,
    )


# --- サブコマンド ----------------------------------------------------------------


def _session(root: Path, toc_key: str | None) -> bsm.BuildSession:
    present = toc_key is not None and toc_candidate.confirmed_toc_present(root, toc_key)
    return bsm.BuildSession(publication_state=bsm.PUBLISHED if present else bsm.UNBUILT)


def _parse_target(args, root: Path):
    try:
        spec = target_spec.parse_namespace(args, root)
    except target_spec.TargetSpecError as exc:
        raise Rejected(exc.errors) from exc
    return spec, spec.key or target_spec.RESERVED_KEY


def _docdb_done(root, toc_key, spec, session, expansion, changes, decision, info: dict):
    """[doc-db]を使う構築。機械取得の構築を公開した後、[doc-db]を同期する。`(payload, 終了コード)` を返す。

    同期が切り替え（(a)・(b)）になったときは、[ToC]として続ける。[確定 ToC]は既に確定している。
    「[AI 生成フィールド]が要る文書」があれば `invoke_toc_updater` を返し、無ければ完了を返す。
    """
    payload = _finish(
        root,
        toc_key,
        spec,
        session,
        None,
        expansion,
        changes,
        require_ai_fields=False,
    )
    outcome = docdb_sync.run_sync(decision.client, root, toc_key)
    payload = {**payload, **info, "docdb_sync": outcome.to_dict()}
    if outcome.status == docdb_sync.STATUS_SYNCED:
        if not outcome.contract_met:
            payload["warnings"] = [
                *payload["warnings"],
                docdb_contract.WARNING_CONTRACT_UNMET,
            ]
        return payload, script_output.EXIT_OK
    if outcome.status == docdb_sync.STATUS_FAILED:
        return (
            {
                **payload,
                "errors": outcome.errors,
                "toc_published": True,
            },
            EXIT_SYNC_FAILED,
        )
    # 切り替え: [ToC]として続ける（[確定 ToC]の機械取得の情報は、基盤によらず確定済み）
    switch = backend_select.Switch(outcome.reason_code, outcome.cause, outcome.presumed)
    toc_session = _session(root, toc_key)
    _, _, plan = _prepare(
        root, spec, toc_key, toc_session, False, backend_select.BACKEND_TOC
    )
    targets = plan.generation_targets
    switched = {
        "backend": backend_select.BACKEND_TOC,
        "forced": False,
        "startup": decision.startup,
        "backend_switch": switch.with_impact(len(targets)).to_dict(),
    }
    if targets:
        wave = _issue_wave(root, toc_key, spec, toc_session, None, targets, switched)
        return (
            {
                **wave,
                "machine_toc": {
                    "version": payload["version"],
                    "published": payload["published"],
                    "detail_path": payload["detail_path"],
                },
                "docdb_sync": outcome.to_dict(),
            },
            script_output.EXIT_OK,
        )
    return {**payload, **switched}, script_output.EXIT_OK


def advance(args: argparse.Namespace) -> int:
    root = Path(os.path.abspath(args.project_root))
    try:
        spec, toc_key = _parse_target(args, root)
    except Rejected as exc:
        return _rejected(bsm.BuildSession(), exc.errors)
    session = _session(root, toc_key)
    build = None
    try:
        decision = None
        if args.build_id is not None:
            if args.docdb_startup is not None:
                raise Rejected(
                    [
                        "--docdb-startup は、--build-id を付けない最初の呼び出しだけで指定できる"
                    ]
                )
            build = _load_build(root, args.build_id, toc_key, spec)
            info = _info_from_build(build)
        else:
            try:
                decision = backend_select.decide(root, startup=args.docdb_startup)
            except backend_config.BackendConfigError as exc:
                raise Rejected(exc.errors) from exc
            if decision.pending is not None:
                # 利用者の回答を待つ。構築しない（何も書き込まない）
                return _emit(decision.pending.to_dict(), script_output.EXIT_OK)
            info = decision.to_dict()
        backend = info["backend"]
        expansion, changes, plan = _prepare(root, spec, toc_key, session, True, backend)
        code = script_output.EXIT_OK
        if backend == backend_select.BACKEND_DOCDB:
            payload, code = _docdb_done(
                root, toc_key, spec, session, expansion, changes, decision, info
            )
        else:
            targets = plan.generation_targets
            if build is not None:
                _check_generation_received(root, build, targets)
            if targets:
                payload = _issue_wave(
                    root, toc_key, spec, session, build, targets, info
                )
            else:
                payload = {
                    **_finish(root, toc_key, spec, session, build, expansion, changes),
                    **info,
                }
    except Rejected as exc:
        return _rejected(session, exc.errors)
    except bsm.TransitionRejected as exc:
        return _rejected(
            session, [f"段階の前提が満たされず、次の段階へ進めない: {exc}"]
        )
    except BuildFailed as failure:
        if build is not None:
            _remove_build(root, build["build_id"])
        return _failed(root, toc_key, session, failure)
    return _emit(payload, code)


def _generated_result(args: argparse.Namespace) -> dict:
    values = (
        ("title", args.title),
        ("purpose", args.purpose),
        ("summary", args.summary),
        ("applicable_tasks", args.applicable_tasks),
        ("keywords", args.keywords),
    )
    return {name: value for name, value in values if value is not None}


def _generation_failed(
    root: Path,
    build_id: str,
    doc_id: str,
    path: str | None,
    kind: str | None,
    failures: list[dict],
) -> BuildFailed:
    """その文書の生成失敗を、文書ごとのファイルに残し、構築の失敗（B-08）として返す。再試行しない。"""
    _write_work_file(
        root,
        _failure_path(root, build_id, doc_id),
        {
            "doc_link_id": doc_id,
            "path": path,
            "kind": kind,
            "failures": failures,
        },
    )
    return BuildFailed(
        STAGE_INFORMATION,
        [
            toc_candidate.CandidateProblem(doc_id, path, item["field"], item["reason"])
            for item in failures
        ],
    )


def _requested_target(
    root, spec, toc_key, session, build: dict, doc_id: str, build_id: str
):
    """依頼に含めた生成対象の文書の計画を返す。

    依頼に無い・生成対象でない文書は拒否する。生成の失敗を残した文書への再送も拒否する（再試行しない。
    DES-004 B-08。失敗の記録を上書きせず、[文書情報]も保存しない）。
    """
    if doc_id not in {entry["doc_link_id"] for entry in build["documents"]}:
        raise Rejected([f"識別値の依頼に含まれない文書の結果: {doc_id}"])
    if _failure_path(root, build_id, doc_id).exists():
        raise Rejected(
            [
                f"生成の失敗を記録した文書への再送は受け付けない（再試行しない）: {doc_id}"
            ]
        )
    _, _, plan = _prepare(root, spec, toc_key, session, False)
    target = next((d for d in plan.generation_targets if d.doc_link_id == doc_id), None)
    if target is None:
        raise Rejected([f"生成対象でない文書の結果: {doc_id}"])
    return target


def _store_generated(root, build_id: str, target, generated: dict):
    """生成結果を検証器と[文書情報]の保存へ渡す。`submit` と `deliver` の共通の入力である。

    検証に通らないときは、その文書の失敗を残して `BuildFailed` を送出する。
    """
    single = update_plan.UpdatePlan(documents=(target,), departed=())
    (outcome,) = update_plan.store_generated(
        root, SKILL, single, {target.doc_link_id: generated}
    )
    if outcome.status == update_plan.STATUS_FAILED:
        raise _generation_failed(
            root,
            build_id,
            outcome.doc_link_id,
            outcome.path,
            outcome.kind,
            [item.to_dict() for item in outcome.failures],
        )
    return outcome


def _stored(outcome) -> dict:
    return {
        "stored": {
            "doc_link_id": outcome.doc_link_id,
            "path": outcome.path,
            "status": outcome.status,
        }
    }


def submit(args: argparse.Namespace) -> int:
    root = Path(os.path.abspath(args.project_root))
    try:
        spec, toc_key = _parse_target(args, root)
    except Rejected as exc:
        return _rejected(bsm.BuildSession(), exc.errors)
    session = _session(root, toc_key)
    try:
        build = _load_build(root, args.build_id, toc_key, spec)
        target = _requested_target(
            root, spec, toc_key, session, build, args.doc_id, args.build_id
        )
        outcome = _store_generated(root, args.build_id, target, _generated_result(args))
    except Rejected as exc:
        return _rejected(session, exc.errors)
    except BuildFailed as failure:
        return _failed(root, toc_key, session, failure)
    return _emit(_stored(outcome), script_output.EXIT_OK)


def _exit_value_failure(exit_value: str | None) -> str | None:
    """終了の値が正常でないときの理由を返す（正常なら `None`）。成否は script が判定する。"""
    if exit_value == EXIT_VALUE_NORMAL:
        return None
    if exit_value is None:
        return "exit value was not provided"
    if exit_value == EXIT_VALUE_SOURCE_UNREADABLE:
        return "source_unreadable: the source document could not be read"
    return "exit value is not defined"


def deliver(args: argparse.Namespace) -> int:
    """`toc-updater` が、1 文書分の生成結果と終了の値を渡す。対象指定は、作業状態に記録したものを使う。"""
    root = Path(os.path.abspath(args.project_root))
    try:
        build = _read_build(root, args.build_id)
        spec = target_spec.TargetSpec.from_dict(build["target_spec"])
        toc_key = build["toc_key"]
        if not isinstance(toc_key, str):
            raise Rejected([f"識別値の作業状態に[ToC 識別キー]が無い: {args.build_id}"])
    except target_spec.TargetSpecError as exc:
        return _rejected(bsm.BuildSession(), exc.errors)
    except (KeyError, TypeError) as exc:
        return _rejected(
            bsm.BuildSession(),
            [f"識別値の作業状態に対象指定が無い: {args.build_id}: {exc}"],
        )
    except Rejected as exc:
        return _rejected(bsm.BuildSession(), exc.errors)
    session = _session(root, toc_key)
    try:
        target = _requested_target(
            root, spec, toc_key, session, build, args.doc_id, args.build_id
        )
        reason = _exit_value_failure(args.exit_value)
        if reason is not None:
            raise _generation_failed(
                root,
                args.build_id,
                target.doc_link_id,
                target.path,
                None,
                [{"field": None, "reason": reason}],
            )
        outcome = _store_generated(root, args.build_id, target, _generated_result(args))
        _write_work_file(
            root,
            _result_path(root, args.build_id, args.doc_id),
            {
                "doc_link_id": args.doc_id,
                "exit": EXIT_VALUE_NORMAL,
                "status": outcome.status,
            },
        )
    except Rejected as exc:
        return _rejected(session, exc.errors)
    except BuildFailed as failure:
        return _failed(root, toc_key, session, failure)
    return _emit(_stored(outcome), script_output.EXIT_OK)


def request(args: argparse.Namespace) -> int:
    """`toc-updater` が、識別値（構築 ID と[文書 ID]の並び）から、依頼のファイルの絶対パスを得る。

    依頼は script が書き終えて公開したものだけである。公開されていなければ、パスを返さずに失敗する。
    """
    root = Path(os.path.abspath(args.project_root))
    try:
        build = _read_build(root, args.build_id)
        path = _request_path(root, build["build_id"], args.doc_id)
        if not path.is_file():
            raise Rejected([f"識別値に対応する依頼が公開されていない: {args.build_id}"])
    except Rejected as exc:
        return script_output.emit_error(exc.errors)
    return script_output.emit_result({"path": str(path)})


def execute(args: argparse.Namespace) -> int:
    commands = {
        "advance": advance,
        "submit": submit,
        "request": request,
        "deliver": deliver,
    }
    return commands[args.command](args)


def main(argv: list[str] | None = None) -> int:
    return execute(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
