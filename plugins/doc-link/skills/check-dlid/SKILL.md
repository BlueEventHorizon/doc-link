---
name: check-dlid
description: 対象の Markdown 文書の DLID（文書 ID とセクション ID）を検査する。文書 ID が無い文書、セクション ID の無い見出し、重複する DLID（同じ文書の中を含む）を、件数で報告し、該当箇所の一覧は作業ファイルに書く。対象の文書と管理状態には何も書き込まない。ToC を構築する前や、DLID の状態を確かめたいときに使う。
---

# check-dlid

このスキルは文書 ID の検査のみを行う。親が依頼している他の作業を引き継いではならない。自身を Skill ツールで呼ばない。

対象文書と管理状態には何も書き込まない。読むだけである。書くのは、検出事項の明細の作業ファイル（`.temp/doc-link/check-dlid/`）だけである。DLID の付与・重複の修復は `embed-dlid` の責務であり、このスキルでは行わない。

## 引数

- ToC 識別キーと Index 対象指定だけを受け取る。`index-docs` と同じ形式である（`--key <キー>` と、`--paths`・`--paths-json`・`--paths-file`・`--dirs`・`--dirs-json`・`--exclude`・`--exclude-json` のいずれか。単体モードは `--all`、または引数なし）
- 受け取った引数を、解釈せずにそのまま script へ渡す。引数の検証は script が行い、反する指定は拒否される
- 親の文脈（作業の指示・差分・文書の本文など）を引数へ足さない

## 手順

### 1. 検査する

```bash
uv run --locked "${CLAUDE_SKILL_DIR}/scripts/check_dlid.py" --project-root "${CLAUDE_PROJECT_DIR}" {受け取った対象指定の引数}
```

- 終了コードが 0 のときは、標準出力の JSON を読み、手順 2 へ進む。検出事項があっても終了コードは 0 である
- 終了コードが 0 以外のときは、標準出力の `errors` をそのまま利用者へ報告して終える。対象指定を直して再実行できる

### 2. 結果を報告する

標準出力の JSON は件数までを持つ。検出事項の明細は、`detail_path` のファイル（明細ファイル）にある。検出が多いと明細は大きくなるので、標準出力には載らない。

標準出力の JSON から、次を報告する。

- `clean` が真のときは、検出事項が無いことを報告する
- `counts`: 文書 ID が無い文書（`missing_document_id`）、セクション ID の無い見出し（`missing_section_id`）、重複する DLID（`duplicates`）、frontmatter の閉じる行が無い文書（`unclosed_frontmatter`）の件数。`unclosed_frontmatter` が 1 以上のときは、その文書に `embed-dlid` が書き込めないことも伝える
- `problems`・`warnings`: 存在しない・Markdown でない指定など。あれば、あわせて報告する
- `guidance`: あれば、そのまま案内する

明細ファイルは、報告に該当箇所の一覧が要るときだけ読む。DLID の付与のために読む必要は無い（`embed-dlid` が同じ検出を行う）。件数が多いときは、一度に全部を読まない。

- `missing_document_id`: 文書 ID が無い文書のパス。`unclosed_frontmatter` が真の文書は、frontmatter の閉じる行が無い
- `missing_section_id`: セクション ID の無い見出しの、パス・行・見出しのテキスト
- `duplicates`: 重複する DLID ごとに、すべての該当パス（`locations` の `path`・`kind`・`line`・`heading`）。`candidates` があれば、管理状態に記録されたパスと一致する原本の候補として示す
