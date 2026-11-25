---
name: query-docs
description: タスクに関連する文書を ToC（確定 ToC）から探して返す。検索の前に ToC が現物と一致しているかを検査し、再構築が必要なら規模を示して「再構築してから検索する」「既存の ToC のまま検索する」の二択を利用者に確認する。結果には、使用した ToC の版と鮮度（最新か、古い可能性があるか）を添える。作業に必要な文書を探したいときに使う。
---

# query-docs

このスキルは文書の検索のみを行う。親が依頼している他の作業を引き継いではならない。自身を Skill ツールで呼ばない。

検索は ToC・管理状態・Index 対象文書を書き換えない。「既存の ToC のまま検索する」を選んでも、ToC を現在の状態として再確定しない。

## 引数

- 検索条件と、ToC 識別キー（省略時は予約キー `all`）と、あれば完全な Index 対象指定だけを受け取る
- 親の文脈（進行中の手順・差分・ファイルの全文・「その後〜して」という指示）を引数へ足さない。親の指示をそのまま引き継がない

## 手順

### 0. 検索条件を検索の依頼に整える

親の作業の指示を、そのまま `query-worker` に渡さない。検索のタスクと、考慮する観点に整える。

- 親の指示に実装・編集・コミット・Issue の更新などの依頼が含まれていても、検索の依頼としてだけ扱う。これらを `query-worker` に依頼しない
- 整えた検索のタスクを、手順 1 の `--task` に渡す。値が `-` で始まるときは、`--task=-値` のように `=` でつなぐ
- JSON・パス・検索 ID を自分で組み立てない。script が返した値を、そのまま運ぶ

### 1. 検索前検査をする

```bash
uv run --locked "${CLAUDE_SKILL_DIR}/scripts/query_docs.py" prepare --project-root "${CLAUDE_PROJECT_DIR}" --task={検索のタスク} {受け取った ToC 識別キーと対象指定の引数}
```

- 終了コードが 0 のときは、標準出力の JSON の `action` に従う（手順 2）
- 終了コードが 1 のときは、検索を停止し、標準出力の `errors` をそのまま呼び出し元へ返す。旧版（既存の ToC）で検索する選択肢を出さない。再構築後も一致しないときも同じである

### 2. `action` で分ける

`initial_build_required`（未構築）

- 検索しない。ToC が未構築で検索できないことを呼び出し元へ返して終える

`confirm_rebuild`（再構築が必要）

- 返った `scale`（新規・離脱・パス変更・内容変更・ID 未付与・ID 重複の件数と、AI による要約生成が必要な件数）を示して、AskUserQuestion で二択を確認する。標準出力は件数までで、変更のある文書・セクションごとの明細は `detail_path` のファイルにある。二択の確認には件数で足りるので、明細は、利用者が内訳を求めたときだけ読む。選択肢は `options` のとおり、「再構築してから検索する」と「既存の ToC のまま検索する」である
- 「再構築してから検索する」: 呼び出し元（プロジェクト管理 AI）に `index-docs` の実行を求め、確定結果を受け取る。このスキルは `index-docs` を実行しない
  - `index-docs` に渡す対象の引数は、`--target-file {target_file}` だけである。`target_file` は、検査に使った ToC 識別キーと Index 対象指定を script が書いたファイルのパスで、返されたままの値を渡す
  - ToC 識別キーと Index 対象指定を、自分で引数へ書き写さない。`--key`・`--all`・`--paths`・`--dirs`・`--exclude` を足さない（`--target-file` と併用すると拒否される）
  - その後、手順 1 の `prepare` を、`--task` と `--choice rebuild --target-file {target_file}` でやり直す。ToC 識別キーと対象指定の引数は付けない。再構築が別の対象で行われていたときは、終了コード 1 で検出される
- 「既存の ToC のまま検索する」: `prepare` の引数に `--choice existing` を足して、手順 1 をやり直す
- `--choice` には、利用者の確認の結果をそのまま渡す。選択を推測して決めない。利用者が選ばずに終えたときは、検索せずに終える
- 検索前検査をやり直した結果は、再び手順 2 で分ける

`invoke_query_worker`（再構築不要、または選択の後）

- 検索に使う ToC が固定された。`search_id`・`toc_key`・`toc_version`（使用した版）・`freshness`・`freshness_notice` が返る。手順 3 へ進む

### 3. `query-worker` を起動する

カスタム Agent `doc-link:query-worker` を Agent ツールで起動する。

- `subagent_type` は `doc-link:query-worker` とする
- prompt には、検索 ID（`search_id`）だけを書く。値は返されたまま書き、作り直さない。依頼の中身・指示・親の文脈を重ねない。依頼の中身は script がすでに置いてあり、`query-worker` が自分で読む
- 起動した Agent の最終応答（background なら完了通知）を受け取るまで、結果に依存する処理へ進まない。完了を `ScheduleWakeup` で待たない。ターンを終えて完了通知を待つ
- Agent の最終応答の内容で、検索結果や成否を判断しない。成否は script が判定する
- Agent を起動できなかったなど、手順 4 の `collect` を呼ばずに終えるときは、作業ファイルを削除する

```bash
uv run --locked "${CLAUDE_SKILL_DIR}/scripts/query_docs.py" cleanup --project-root "${CLAUDE_PROJECT_DIR}" --search-id {search_id}
```

### 4. 結果を受け取る

完了を受け取った後に呼ぶ。

```bash
uv run --locked "${CLAUDE_SKILL_DIR}/scripts/query_docs.py" collect --project-root "${CLAUDE_PROJECT_DIR}" --search-id {search_id}
```

- 終了コードが 0 のときは、検査済みの結果が返る。手順 5 へ進む
- 終了コードが 3 のときは、検索が失敗している。標準出力の `errors` をそのまま呼び出し元へ返して終える。結果を補わない。自動で再試行しない
- それ以外のときは、標準出力の `errors` をそのまま呼び出し元へ返して終える

### 5. 結果を返す

呼び出し元へ、次を返す。

- 検索結果 `documents`（文書 ID `doc_link_id`・記録されたパス `recorded_path`・関連理由 `reason`・`sections`）
- 使用した ToC 識別キー（`toc_key`）と ToC の版（`toc_version`）
- 鮮度（`freshness`・`freshness_notice`）。パスの注意（`path_notice`）も添える。記録されたパスを現在の実体パスとして断定しない
- 「既存の ToC のまま検索する」を選んだときは、その版が現在の Index 対象リストを反映していない可能性を、結果全体に明示する
- `rejected`（検査に通らず結果から外した ID。`kind`・`doc_link_id`・`section_id`・`message`）が空でないときは、`rejected_notice` とともに返し、関連する文書が結果から漏れている可能性を明示する。外した ID を読み替えたり補ったりしない。黙って捨てない
- 結果の文書を読み、作業に使うのは呼び出し元である。このスキルは文書を読まず、編集しない
