---
name: check-links
description: 対象の Markdown 文書の参照（title に DLID を持つリファレンスリンクの定義）を、参照先のディレクトリを実走査して検査する。壊れた参照・DLID とパスの不一致・存在しないセクションへの参照・フラグメントが参照先のセクションへ解決しないリンク・参照先ディレクトリに見つからない参照・title に DLID の無いリンク・インラインリンクを報告する。何も書き込まない。DLID を付与した後（index-docs の前）、参照を書いた後や直した後、文書を移動・改名した後、リンクの健全性を確かめたいときに使う。
---

# check-links

このスキルは参照の検査のみを行う。親が依頼している他の作業を引き継いではならない。自身を Skill ツールで呼ばない。

検出して返すだけで、何も書き込まない。対象文書・管理状態を書き換えず、リンクを直さない。リンクを直すのはプロジェクト管理 AI（呼び出し元）である。

## 引数

- ToC 識別キーと Index 対象指定だけを受け取る。`index-docs` と同じ形式である（`--key <キー>` と、`--paths`・`--paths-json`・`--paths-file`・`--dirs`・`--dirs-json`・`--exclude`・`--exclude-json` のいずれか。単体モードは `--all`、または引数なし）
- 受け取った引数を、解釈せずにそのまま script へ渡す。引数の検証は script が行い、反する指定は拒否される
- 親の文脈（作業の指示・差分・文書の本文など）を引数へ足さない

## 手順

### 1. 参照を検査する

```bash
uv run --locked "${CLAUDE_SKILL_DIR}/scripts/check_links.py" --project-root "${CLAUDE_PROJECT_DIR}" {受け取った対象指定の引数}
```

- 終了コードが 0 のときは、検査を完了した。検出事項があっても 0 である。手順 2 へ進む
- 終了コードが 1 のときは、標準出力の `errors` をそのまま報告して終える。対象指定を直して再実行できる
- `problems`（存在しない・Markdown でない指定）と `warnings` があれば、あわせて報告する

### 2. 結果を報告する

標準出力の JSON の `findings` を、`category` ごとにまとめて報告する。各検出事項には、参照元のパス（`source_path`）・行（`line`）・リンク先（`target`）・DLID（`dlid`）を示す。

| category                | 意味                                                                        | 添える情報                                                                                                                                         |
| ----------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `path_mismatch`         | DLID とリンク先のパスが一致しない（同じ DLID の文書が別のパスで見つかった） | `current_path`（確認できた現在のパス）                                                                                                             |
| `fragment_mismatch`     | リンク先は一致するが、フラグメントが参照先のセクションへ解決しない          | `current_anchor`（そのセクションへ届く現在のアンカー）                                                                                             |
| `missing_section`       | リンク先の文書はあるが、title の DLID が指定ディレクトリのどこにも無い      | `target_doc_link_id`（その文書の現在の文書 ID。無ければ null）                                                                                     |
| `absent`                | 指定ディレクトリ内に参照先が見つからない                                    | `absent_reason`                                                                                                                                    |
| `duplicate`             | 同じ DLID が複数見つかり、現在のパスを一意に決められない                    | `duplicate_paths`                                                                                                                                  |
| `unresolved`            | リンク先のパスを参照元から解決できない                                      | `unresolved_reason`                                                                                                                                |
| `link_without_dlid`     | `doc_link_id` を持つ Markdown を指すが、title に DLID が無い                | `kind`（`definition` か `inline`）、`target_doc_link_id`、`suggested_title`（title に書く値。書けないときは `suggested_title_unavailable_reason`） |
| `inline_link_with_dlid` | title に DLID を持つが、リファレンスリンクの定義でない                      | `recorded_hash`                                                                                                                                    |

- `absent` は、世界全体に参照先が無いことを意味しない。指定ディレクトリ内に見つからないことだけを示す。保存済みのデータから現在のパスを推測して補わない
- `recorded_hash` が null のものは、title に内容ハッシュの記録が無い参照である。記録と参照先の現在ハッシュの比較は、このスキルでは行わない
- `unverified_links`（リンク先の文書を読めず判定できなかったリンク）と `unreadable_documents`（読めなかった参照元の文書）が空でなければ、検査できなかったものとして報告する
- `summary` の `checked_documents`（参照元として読んだ文書の数）・`matched_references`（一致した参照の件数）と、`scope`（対象指定 `target`、参照先を探して走査したディレクトリ `directories`、時点 `checked_at`）を添える。`directories` は参照を検査するたびに足されるので、参照が 1 件も無いときは空になる。この場合の検査範囲は、`target` と `checked_documents` が示す。検出事項が無いことは、この範囲で見つからなかったという事実だけを示す

### 3. 検出事項の扱い

検出事項があるときは、`guidance` の内容をそのまま案内する。修正は呼び出し元（プロジェクト管理 AI）が行う。書き直す対象（title に DLID の無いリンク、インラインリンク、パスの不一致、フラグメントの不一致）があるときは、書き直す前に、検出したリンクと書く値の一覧（文書・行・書く値）を利用者に示して、書き直すかを確認し、承認された分だけを書き直す。

- title に DLID の無いリンクには、検出事項の `suggested_title`（参照先の内容ハッシュと DLID）を title に書く。`suggested_title` が無いものは、`suggested_title_unavailable_reason` が示す理由に応じて、どのセクションを指す参照にするかを決めてから、再度検査する。`fragment_unresolved` は、フラグメントが参照先のどの見出し・アンカーにも一致しないことを示す（リンクは壊れておらず、参照先の文書を開く。見出しのアンカーは、見出しに DLID を埋め込むと変わる）。セクションを指す参照にするなら、フラグメントを現在の見出しのアンカーへ直す。文書を指す参照にするなら、フラグメントを外す。`heading_without_dlid` は、解決した見出しに DLID が無いことを示す。`embed-dlid` で付与する。インラインリンクは、リファレンスリンクの定義に書き換える
- パスの不一致には `current_path`、フラグメント不一致には `current_anchor` を使ってリンクを直す
- 参照先が見つからない場合は、移動か削除かを判断する
