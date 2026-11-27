---
name: index-docs
description: ToC（確定 ToC）を構築・再構築する。対象の文書の DLID を確かめ、確定済みの ToC と現物の差分を検出し、生成が必要な文書だけ toc-updater に文書情報の生成を依頼して検証し、参照を検査して、ToC の新しい版を一括して確定する。ID 未付与・ID 重複の文書は ToC に入れずに報告する。ToC を初めて作るとき、check-toc が不一致を検出したとき、文書や参照を変更した後に使う。
---

# index-docs

このスキルは ToC の構築・再構築のみを行う。親が依頼している他の作業を引き継いではならない。自身を Skill ツールで呼ばない。

対象の文書（Index 対象文書）は書き換えない。DLID を発行・書き込みしない（それは `embed-dlid` の責務である）。管理状態（文書情報・確定 ToC）は、入口の script だけが書く。

## 引数

- ToC 識別キーと Index 対象指定だけを受け取る。`embed-dlid` と同じ形式である（`--key <キー>` と、`--paths`・`--paths-json`・`--paths-file`・`--dirs`・`--dirs-json`・`--exclude`・`--exclude-json` のいずれか。単体モードは `--all`、または引数なし）。`--target-file <パス>` は、doc-link の script が書いた対象指定ファイルを渡す形式で、ほかの対象の引数と併せて渡されない
- 受け取った引数を、解釈せずにそのまま script へ渡す。引数の検証は script が行い、反する指定は拒否される
- 親の文脈（作業の指示・差分・文書の本文など）を引数へ足さない

## 検索基盤

構築の入口の script が、検索基盤（doc-db か ToC）を決める。決めるのは、設定ファイル（`.doc-link/config.json` の `backend`。`"auto"` か `"toc"`。無ければ `"auto"`）と、doc-db への接続の可否である。強制スイッチの呼び出しごとの指定（引数）は無い。`"auto"` のとき、doc-db に接続できなければ、script は doc-db を起動せずに止まる（手順 1 の `confirm_docdb_startup`）。利用者が許可したときだけ、doc-db を起動して再接続を試みる（停止・常駐化はしない）。

- doc-db を使うとき: script は、機械取得の構築（手順 1〜3 の流れ）だけを行い、AI 生成フィールドを作らない（`toc-updater` を起動しない）。確定した後、doc-db を同期する
- ToC を使うとき（設定で強制、doc-db を使えず切り替えた、または利用者が今回は ToC で続けることを選んだ）: 現在のとおり、`toc-updater` が AI 生成フィールドを作る
- 結果の `backend`（`doc-db` か `toc`）・`forced`・`startup`・`backend_switch` を、報告に含める。`backend_switch` が `null` でないときは、切り替えが起きている。その `notice` を、そのまま利用者へ伝える（理由・原因・影響・次の実行の扱いを、自分で書き足さない・言い換えて補わない）

## 手順

構築の前に、前工程を済ませる（手順 0）。そのあと、入口の script を 1 本だけ呼ぶ。script は構築を進められる所まで進め、次に行うこと（`action`）を返す。返された `action` に従い、終えたら同じ script を `build_id` 付きでもう一度呼ぶ。この繰り返しで構築が終わる。

### 0. 前工程を済ませる（プロジェクト管理 AI）

初回の構築と、変更後の再構築では、手順 1 の前に次を順に行う。このスキルは実行しない。済んでいなければ、手順 1 に進まない。

1. `check-dlid` で、DLID の無い文書・見出しと重複を検出する。検出があれば、`embed-dlid` を実行する（起動が書き込みの承認である。利用者には確認しない）。書き込んだ件数は、手順 3 の報告に含める
2. `check-links` で、参照を検査する。書き直す対象があれば、一覧（文書・行・書く値）を利用者に示して確認し、承認された分だけを書き直す。利用者に確認できない文脈（`AskUserQuestion` を使えないなど）では、書き直さずに、書き直す対象の一覧を手順 3 の報告に含める

検出への対処が済んだら（検出が無い場合を含む）、手順 1 へ進む。

### 1. 構築を進める

最初は `build_id` を付けずに呼ぶ。

```bash
uv run --locked "${CLAUDE_SKILL_DIR}/scripts/index_docs.py" advance --project-root "${CLAUDE_PROJECT_DIR}" {受け取った対象指定の引数}
```

- 終了コードが 0 のときは、標準出力の JSON の `action` に従う（手順 2・3）。`backend_switch` があれば、その `notice` を利用者へ伝える
- `action` が `confirm_docdb_startup` のとき（doc-db に接続できず、起動していない。構築はまだ始まっていない）は、返った `question` と `options` を、AskUserQuestion で利用者に確認する。選択肢は「doc-db を起動する」と「今回は ToC で続ける」である。理由・原因を自分で書き足さない。利用者の選択を、そのまま `--docdb-startup` に渡し（`options` の `argument`）、同じ呼び出し（`build_id` なし）をやり直す。選択を推測して決めない。利用者が選ばずに終えたときは、構築せずに終える。利用者に確認できない文脈（`AskUserQuestion` を使えないなど）では、起動も ToC への切り替えも自分で決めず、質問と選択肢を呼び出し元へ返して終える
- `action` が `docdb_startup_failed` のとき（許可を得て起動したが、接続できなかった。構築はまだ始まっていない）は、返った `message`（起動できなかったこと・原因の分類・起動の command）を、そのまま利用者へ伝え、AskUserQuestion で「起動してやり直す」か「今回は ToC で続ける」かを確認する。原因を断定しない・自分で書き足さない。「起動してやり直す」は、利用者が `command` で doc-db を起動した後に、`--docdb-startup` なしで同じ呼び出しをやり直す。「今回は ToC で続ける」は、`options` の `argument` を付けて、やり直す
- 終了コードが 3 のときは、構築が失敗している。手順 4 へ進む
- 終了コードが 4 のときは、doc-db を使う構築で、確定 ToC は確定したが、doc-db の同期が障害で失敗している。手順 4 の後半へ進む
- それ以外（1）のときは、標準出力の `errors` をそのまま利用者へ報告して終える。対象指定を直して再実行できる。設定ファイルを受理できないときも、ここである（`errors` に、ファイルと箇所）
- `problems`（存在しない・Markdown でない指定）と `warnings` があれば、あわせて報告する

### 2. `action` が `invoke_toc_updater` のとき

ToC を使うとき（設定で強制、または doc-db を使えず切り替えた）に返る。doc-db の同期が接続できない・OpenAI の失敗で切り替わったときも、この `action` が返る（確定 ToC は確定済みで、`machine_toc` に版と明細ファイルを持つ。続けて AI 生成フィールドを作る）。`backend_switch` の `notice` を、最初に利用者へ伝える。

`batches` の 1 件ごとに、カスタム Agent `doc-link:toc-updater` を Agent ツールで起動する。

- `subagent_type` は `doc-link:toc-updater` とする。1 件が最大 3 文書で、同時に起動するのは最大 10 本（`batches` の件数がすでにその範囲に収まっている）。`batches` の分け方・件数・順序を変えない
- prompt には、識別値だけを書く。構築 ID（`build_id`）と、その `batches` の 1 件の文書 ID（`doc_link_id`）の並びである。値は返されたまま書き、作り直さない。依頼の中身（文書のパス・記述上限など）・生成の指示・親の文脈を重ねない。依頼の中身は script がすでに置いてあり、`toc-updater` が自分で読む
- 起動した Agent の最終応答（background なら完了通知）を、すべて受け取るまで待つ。結果に依存する次の処理へ、その前に進まない。完了を `ScheduleWakeup` で待たない。ターンを終えて完了通知を待つ
- Agent の最終応答の内容で、成否を判断しない。成否は script が判定する
- すべての Agent の完了を受け取ったら、`build_id` を付けて、同じ script をもう一度呼ぶ

```bash
uv run --locked "${CLAUDE_SKILL_DIR}/scripts/index_docs.py" advance --project-root "${CLAUDE_PROJECT_DIR}" --build-id {build_id} {受け取った対象指定の引数}
```

- 返された `action` が再び `invoke_toc_updater` のときは、残りの生成対象の依頼である（`remaining_documents` が、前の回に含めなかった数）。この手順 2 を繰り返す
- 終了コードの扱いは手順 1 と同じである

### 3. `action` が `done` のとき

[確定 ToC]が公開された。標準出力の JSON から、次を報告する。

- 使った検索基盤（`backend`）。doc-db のときは、同期の結果（`docdb_sync`。一覧の件数 `listed`・一覧から除いた文書の件数 `missing_count`・doc-db の処理の件数 `counts`）。`warnings` に doc-db の契約を満たすと確認できない旨があれば、あわせて伝える
- 確定結果（`version`・`published`。`published` が偽なら、前回と同じ内容で、書き換えていない。doc-db から ToC へ切り替えた構築では、機械取得の確定は最初の呼び出しの `machine_toc`（`published` が真）で済んでおり、AI 生成フィールドを作った後の完了の `published` が偽でも異常ではない）と、生成した文書の件数（`generated_count`。doc-db のときは 0）
- 変更の種別ごとの件数（`change_summary`）
- 参照検査結果（`reference_check`）。`summary` の、分類ごとの件数。一致（`match`）以外の件数があれば、参照に検出事項がある
- 除外した文書の件数（`excluded_counts`。ID 未付与は `missing`、ID 重複は `duplicate`）
- `problems`・`warnings` があれば、あわせて報告する

標準出力は件数までで、全件の明細は `detail_path` のファイルにある。変更集合（`change_set`。除外した文書の一覧 `excluded` を含む）、生成した文書の一覧（`generated_documents`）、一致以外の参照の検出事項（`reference_findings`）である。報告に文書ごとの明細が要るときだけ、そのファイルを読む。明細が要らないときは読まない。件数が多いときは、一度に全部を読まない。

### 4. 構築が失敗したとき（終了コード 4 を含む）

終了コードが 4 のときは、`errors`・`toc_published`・`docdb_sync` をそのまま利用者へ報告する。確定 ToC は確定している（機械取得の情報は最新）が、doc-db の同期は完了していない。切り替えていない（接続できない・OpenAI の失敗以外の失敗のため）。自動で再試行しない。原因を直した後、利用者の指示で、手順 1 から再実行する。設定ファイルで `"backend": "toc"` にすると、doc-db を使わずに ToC で構築できることを添える。

終了コードが 3 のときは次のとおり。

終了コードが 3 のときは、標準出力の `errors`・`stage`・`problems`（失敗した文書・フィールド・原因）・`confirmed_toc_present` をそのまま利用者へ報告する。

- 候補は公開されておらず、旧い確定 ToC は変わっていない。確定済みの文書情報は戻らない
- 自動で再試行しない。`toc-updater` へ生成のやり直しを頼まない。原因を直した後、利用者の指示で、`build_id` を付けずに手順 1 から再実行する

### 5. 変更の影響を検査する（プロジェクト管理 AI）

手順 3 で ToC が確定したら、`check-impact` で変更の影響を検査する。このスキルは実行しない。変更影響候補があるときは、`check-impact` の手順 3 に従い、参照元ごとに読んで確かめた参照だけの title を書き換える。読まずに一括で書き換えない。参照元の本文を直したときは、ToC が古くなるので、手順 0 からやり直す。title の内容ハッシュだけを書いたときは、やり直さない。
