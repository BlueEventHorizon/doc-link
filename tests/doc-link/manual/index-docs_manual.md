# index-docs の通しの手動確認（完了結果の明細ファイルと、移動の記録）

修正後の `doc-link` プラグインを SKILL の経路で動かし、実際の `toc-updater`・`query-worker`（AI）を含めて、`index-docs` の完了結果を確かめる手順。AI の判断は揺れ、実行に費用がかかるので、自動で実行するテスト（`test_*.py`）に入れない。AI を介さない振る舞い（完了結果の項目、明細ファイルの中身、移動の記録と集計）は、自動テストが確かめている。ここで確かめるのは、実際の SKILL・Agent を通しても、同じ結果になることである。

## 目的

- 完了結果（`done`）の標準出力が、判断に要る項目と件数だけで、小さい（文書数によらず 1 KB 程度）
- 全件の明細が、`detail_path` の明細ファイルにある
- 移動を、生成が挟まる構築、本文変更との同時、構築のやり直し、移動して元に戻した場合でも、正しく報告する
- 複数の[ToC 識別キー]で同じ文書を使うとき、移動を報告するのは、[文書情報]のパスを新しくした構築だけである
- 構築のあとの `check-toc`・`check-links`・`check-impact`・`resolve-dlid`・`query-docs` が、移動後の文書を正しく扱う

## 事前条件

- 修正後の `plugins/doc-link/` を `--plugin-dir` で読み込んだ Claude Code で行う。インストール済みの同名のプラグインが優先されていないことを、SKILL の基準ディレクトリで確かめる（`plugins/doc-link/skills/...` を指していること）
- `uv` と `dprint` が使える
- `.temp/` を `.gitignore` に含める
- テスト用の文書は `tests/doc-link/fixtures/index-docs-e2e/docs/` にある（`alpha`・`beta`・`gamma`・`delta` の 4 文書。`alpha` が `beta` を参照する。[文書 ID]・[セクション ID]・title の記録語は、あらかじめ書いてある）。各文書は、5 項目の内容概要を書ける量の話題を持つ。短すぎると、`toc-updater` が 5 項目に満たない内容概要を返し、検証で拒否される

## 手順

[ToC 識別キー]は `e2e`、対象は `--dirs-json '["tests/doc-link/fixtures/index-docs-e2e/docs/"]'` とする。各場面は、`index-docs` の手順（`advance` → `toc-updater` の起動 → `build_id` 付きの `advance`）で行い、`done` の件数と明細ファイルを確かめる。

1. **初回構築**
   - 期待: `new: 4`、`first_build` が真、`generated_count` が文書の数、標準出力が約 1 KB 以下、`detail_path` のファイルに 4 文書の変更集合と生成した文書の一覧がある、移動の記録が無い
2. **移動だけ**: `gamma.md` を `sub/` へ移動する
   - 期待: 生成の依頼が無く、その場で `done`。`path_changed: 1`、`generated_count: 0`、`published` が偽、明細ファイルの `gamma` に `old_path`・`new_path`
3. **移動した文書と本文を変えた文書の混在**: `beta.md` の本文を変え、`delta.md` を `sub/` へ移動する
   - 期待: `beta` だけが生成の依頼になる。`done` で `path_changed: 1`（`delta`）と `content_changed: 1`（`beta`）の両方が出る
4. **構築のやり直し**: `gamma.md` を `sub/` から戻し、`delta.md` の本文を変える。`advance` を 1 回呼んで生成の依頼が返ったところで中断し、`build_id` なしで `advance` をやり直す
   - 期待: 中断した時点で、移動の記録（`.temp/doc-link/index-docs/moves-e2e.json`）がある。やり直しの `done` で `path_changed: 1`（`gamma`）と `content_changed: 1`（`delta`）。記録は公開のあとに削除される
5. **移動して元に戻す**: `gamma.md` を `sub/` へ移動し、`beta.md` の本文を変えて、`advance` を 1 回呼んで中断する。`gamma.md` を元の場所へ戻して、`build_id` なしでやり直す
   - 期待: `path_changed: 0`、`content_changed: 1`。明細ファイルの `gamma` は種別が空
6. **複数のキー**: 別のキー `e2e2` で同じ対象を初回構築する（生成の依頼は無い）。`gamma.md` を移動し、`delta.md` の本文を変えて、`e2e` を先に構築し、続けて `e2e2` を構築する
   - 期待: `e2e` は `path_changed: 1`、`e2e2` は `path_changed: 0`。キーごとに別の明細ファイル（`detail-e2e.json`・`detail-e2e2.json`）がある
7. **構築のあとの検査と検索**
   - `check-toc` が `up_to_date`、`check-links` が 0 件
   - `check-impact` が、変更した `beta` を参照する `alpha` を、変更影響候補として挙げる
   - `resolve-dlid` が、移動した文書とセクションの現在のパスを返す
   - `query-docs` を、移動した文書に関わるタスクで実行し、実際の `query-worker` が移動後の文書を、使用版・鮮度つきで返す

## 後始末

- テスト用の文書を、最初の姿に戻す（移動と追記を元に戻す。`alpha` の title の記録語は、`beta` が最初の姿のときの値）
- 確認が作った状態を削除する。削除するのは、未追跡の次のファイルだけである
  - `.doc-link/documents/DLID-a1a1a1a1a1a1.json`・`DLID-b1b1b1b1b1b1.json`・`DLID-c1c1c1c1c1c1.json`・`DLID-d1d1d1d1d1d1.json`
  - `.doc-link/tocs/e2e.json`・`e2e2.json`
  - `.temp/doc-link/index-docs/detail-e2e.json`・`detail-e2e2.json`
- `git status` で、テスト用の文書と手順書以外に、未追跡のファイルが残っていないことを確かめる
