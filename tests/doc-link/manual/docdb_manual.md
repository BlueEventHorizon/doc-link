# doc-db との実機の確認（手動）

[doc-db]の起動・同期・検索と、[ToC]への切り替えを、実際の[doc-db]で確かめる手順である。自動実行しない（OpenAI の鍵と、[doc-db]の実行ファイルが要るため）。要件 REQ-006 の AC-036・AC-038・AC-039・AC-043・AC-047・AC-049 の実機の確認である。単体テストと統合テストは、[doc-db]を `FakeDocDb` で模す。

## 隔離の方法 [MANDATORY]

利用者の[doc-db]（`~/.doc-db`）と、その DB に触れない。次を、シナリオごとの一時ディレクトリに作る。

- `HOME` を一時ディレクトリへ向け、`<HOME>/.doc-db/doc-db.yaml` に、別のポート（`server.port`）と全項目を持つ設定を置く（`db_path` は `~/.doc-db/docdb.sqlite` のまま、一時の HOME へ展開される）
- 検証するプロジェクトも一時ディレクトリに置く。文書は、`doc_link_id` と、見出しの行の末尾の[セクション ID]を持つ 3 件（ログイン・決済・通知の設計）
- `uv` のキャッシュは、実際のキャッシュを `UV_CACHE_DIR` で指す
- 検証の後、起動した[doc-db]のプロセスを（待受のポートから）終了し、一時ディレクトリを削除する。doc-link は[doc-db]を停止しない
- OpenAI の鍵は、読まない・出力しない。有効な鍵は、環境を引き継ぐだけである。無効な鍵は、固定のダミーの文字列を環境変数に置く。鍵が無い場合は、環境変数を付けない

## 手順と期待

入口 script（`index_docs.py advance`・`query_docs.py prepare`）を、`uv run --locked` で実行する。契約を実装した[doc-db]（`document_errors` を返す版）は、PATH の先頭へ置く。[doc-db]が起動していないとき、最初の呼び出しは、起動せずに止まる（`confirm_docdb_startup`）。起動してよいときは、同じ呼び出しに `--docdb-startup start` を付けてやり直す。以下の「起動していない」場面の `advance`・`prepare` は、この 2 回の呼び出しを指す。

| #  | シナリオ                                                              | 期待                                                                                                                                                                                                                                                                                                                               |
| -- | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1  | [doc-db]が起動していない。有効な鍵。設定なし。`advance`               | 1 回目は `action` が `confirm_docdb_startup`（起動せず、何も書き込まない）。`--docdb-startup start` を付けた 2 回目は、`action` が `done`、`backend` が `doc-db`、`startup` が `succeeded`、`generated_count` が 0、`docdb_sync` が `synced`（`processed` が 3、`contract_met` が真）、`backend_switch` が `null`、`warnings` が空 |
| 2  | `prepare`（「決済の手順を知りたい」）                                 | `action` が `docdb_result`、`startup` が `not_attempted`、`documents` の先頭が決済の設計（`relevance` は `maybe`、`sections` に見出しと[セクション ID]）、`unmapped` が 0、`sync` の `skipped` が 3                                                                                                                                |
| 3  | 文書を 1 件移動し、1 件削除して、`prepare`                            | `action` が `rebuild_required`、`reason` が `toc_stale`、`options` が無い、`scale.ai_generation` が 0                                                                                                                                                                                                                              |
| 4  | 移動・削除した後の対象で `advance`、続けて `prepare`                  | `docdb_sync.listed` が 2、`documents` に変更前のパス（移動元・削除した文書）が無く、移動先のパスがある                                                                                                                                                                                                                             |
| 5  | `.doc-link/config.json` に `{"backend": "toc"}`。`prepare`、`advance` | `backend` が `toc`、`forced` が真、`backend_switch` が `null`、[doc-db]へ接続しない。`prepare` は `rebuild_required`（`ai_fields_needed`）、`advance` は `invoke_toc_updater`                                                                                                                                                      |
| 6  | `.doc-link/config.json` に `{"backend": "doc-db"}`                    | 終了コード 1。`errors` に、ファイルと箇所                                                                                                                                                                                                                                                                                          |
| 7  | 無効な鍵（HTTP 401）で `advance`                                      | `docdb_sync.status` が `switch`、`backend` が `toc`、`backend_switch.reason_code` が `docdb_openai_failed`（`cause_presumed` が偽。原因は `EMBEDDING_FAILED`）、`action` が `invoke_toc_updater`、`machine_toc.published` が真                                                                                                     |
| 8  | 7 の後、[doc-db]を終了し、有効な鍵で[doc-db]を再起動して、`advance`   | `action` が `done`、`backend` が `doc-db`、`docdb_sync` の `processed` が 3（Embedding が補われる）。続けて `prepare` の `sync` は `skipped` が 3                                                                                                                                                                                  |
| 9  | 鍵が無い。`advance`、`prepare`                                        | `--docdb-startup start` を付ける。起動した[doc-db]が接続の前に終了する。`action` が `docdb_startup_failed`、`cause` が `exited_early`（終了コード 1）、`command` が `doc-db`、`options` が `retry` と `toc`。切り替えず、構築・検索をしない。出力に特定の原因（サンドボックスなど）の断定が無い                                    |
| 10 | PATH に[doc-db]が無く、起動していない。`advance`、`prepare`           | `backend_switch.cause` が `executable_missing`、`backend` が `toc`                                                                                                                                                                                                                                                                 |
| 11 | 契約を満たさない旧版（0.3.4）。有効な鍵。`advance`、`prepare`         | 動作する。`docdb_sync.contract_met` が偽、`warnings` に、契約を満たすと確認できない旨                                                                                                                                                                                                                                              |
| 12 | 契約を満たさない旧版（0.3.4）。無効な鍵。`advance`                    | `backend_switch.reason_code` が `docdb_openai_failed`、`cause_presumed` が真（原因は `embed:` の文言による判別）                                                                                                                                                                                                                   |

## 結果の記録

2026-11-26 に、`develop` から分けたブランチで、7〜8 は契約を実装した[doc-db]のブランチのビルド（未 merge）、11〜12 は導入済みの旧版 0.3.4 で、上の期待どおりであることを確かめた。確かめていないこと:

- SKILL を通した、AI（`toc-updater`・`query-worker`）を含む一連の動作
- 契約を実装した[doc-db]のリリース版での動作
- 設定ファイルが無い環境での[doc-db]の起動（実装の読解のみ）
