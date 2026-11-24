---
name: check-toc
description: ToC（確定 ToC）が現物の文書に対して最新かを検査する。ToC が未構築か、再構築が要らないか、再構築が必要か（新規・離脱・移動・内容変更・参照の違い・反映済みハッシュと現在ハッシュの違いの件数と、再構築の規模）、判定できないかを返す。変更のある文書の一覧は作業ファイルに書く。対象の文書と管理状態には何も書き込まない。ToC を使う前や、文書を変更した後に ToC が古くなっていないかを確かめたいときに使う。
---

# check-toc

このスキルは ToC の鮮度の検査のみを行う。親が依頼している他の作業を引き継いではならない。自身を Skill ツールで呼ばない。

対象文書と管理状態には何も書き込まない。ToC・文書情報・対象文書を読むだけである。書くのは、結果の明細の作業ファイル（`.temp/doc-link/check-toc/`）だけである。ToC の構築・再構築は `index-docs` の責務であり、このスキルでは行わない。

## 引数

- ToC 識別キーと Index 対象指定だけを受け取る。`index-docs` と同じ形式である（`--key <キー>` と、`--paths`・`--paths-json`・`--paths-file`・`--dirs`・`--dirs-json`・`--exclude`・`--exclude-json` のいずれか。単体モードは `--all`、または引数なし）。`--target-file <パス>` は、doc-link の script が書いた対象指定ファイルを渡す形式で、ほかの対象の引数と併せて渡されない
- 受け取った引数を、解釈せずにそのまま script へ渡す。引数の検証は script が行い、反する指定は拒否される
- 渡された完全な対象指定は、ToC に保存された指定より優先して比較される
- 親の文脈（作業の指示・差分・文書の本文など）を引数へ足さない

## 手順

### 1. 検査する

```bash
uv run --locked "${CLAUDE_SKILL_DIR}/scripts/check_toc.py" --project-root "${CLAUDE_PROJECT_DIR}" {受け取った対象指定の引数}
```

- 終了コードが 0 のときは、標準出力の JSON を読み、手順 2 へ進む。未構築・再構築不要・再構築必要は、どれも検査が完了しており、終了コードは 0 である
- 終了コードが 0 以外のときは、標準出力の `errors` をそのまま利用者へ報告して終える。対象指定の拒否と、鮮度を判定できなかった場合（判定できなかった対象と原因が `errors` にある）の両方がここに当たる。判定できなかった場合に、最新である、または古いと読み替えて報告しない

### 2. 結果を報告する

標準出力の JSON は件数までを持つ。変更のある文書・セクションごとの明細は、`detail_path` のファイル（明細ファイル）にある。変更が多いと明細は大きくなるので、標準出力には載らない。

標準出力の JSON の `status` に応じて、次を報告する。

- `not_built`: ToC が未構築であること
- `up_to_date`: 再構築が要らない（最新である）こと
- `rebuild_needed`: 再構築が必要であること。あわせて次を示す
  - `counts`: 変更の種別ごとの文書の件数（`new`・`departed`・`path_changed`・`content_changed`・`references_changed`）、変更のあるセクションの件数（`sections`）、ID 未付与・ID 重複で ToC に入れなかった文書の件数（`missing_id`・`duplicate_id`）、ToC に入っているが今回 ID の重複で除外された文書の件数（`excluded_in_toc`。再構築すると ToC から除かれる）
  - `scale`: 再構築の規模（新規・離脱・パス変更・内容変更・ID 未付与・ID 重複の件数と、AI による生成が必要な文書の件数）
  - `target_spec_changed` が真のときは、渡された対象指定が、ToC に保存された指定（`saved_target_spec`）と違うこと
- `problems`・`warnings`: 存在しない・Markdown でない指定など。あれば、あわせて報告する

明細ファイルは、報告に文書ごとの明細が要るときだけ読む。件数が多いときは、一度に全部を読まない。

- `documents`: 変更のある文書ごとに、`kinds`（`new`・`departed`・`path_changed`・`content_changed`・`references_changed`）、変更前後のパス、反映済みハッシュ（`old_hash`）と現在ハッシュ（`new_hash`）
- `sections`: 変更のあるセクション
- `excluded`・`excluded_in_toc`: ID 未付与・ID 重複で ToC に入れなかった文書と、そのうち ToC に入っている文書
