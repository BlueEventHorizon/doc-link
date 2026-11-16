# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクトの状態

本リポジトリは Claude Code 用プラグイン `doc-link`（仮称、既存の DocAdvisor を置き換える文書検索・索引管理プラグイン）の**実装段階**にある。要件定義書と設計書は承認済みである。プラグインの実装は `plugins/doc-link/`、テストは `tests/doc-link/` に置く。テストと整形の確認はローカルで行う。

doc-link が実現しようとしている内容（パスでなく文書 ID による恒久的な文書管理、参照関係の機械的把握、変更影響の通知）は `docs/specs/requirement/REQ-001_overview.md` の「1. 文書の目的」「3. 目的」に要約がある。

## 正しいことの定義と、上位の階層を変えてはならないこと [MANDATORY]

- 正しいこととは、要件定義に従って正しいことをなすことである
- 設計とは、要件定義に従って正しいことをなすことである
- 実装とは、要件と設計を満たしたうえで正しいことをなすことである
- 実装中に設計を変えることは、正しいことではなく犯罪行為である。設計を作っているときに要件を変えることも、正しい行いではなく犯罪行為である
- 下の階層の作業中に上の階層（要件・設計）を変えたいときは、必ず理由を添えて利用者に承認を取る。承認を得るまで変えない

## doc-link が利用者の文書へ書き込めるもの [MANDATORY]

- doc-link が利用者の文書へ書き込めるのは DLID だけである。DLID 以外のもの（HTML のアンカー、Markdown のリンク・リンクの title・見出し・本文）を書き込まず、書き換えない
- doc-link の参照は DLID で動く。Markdown のリンク先パスや `#…`、HTML のアンカーは人間のためのものであり、doc-link の動作の前提にしない。人間が必要なら、人間（または AI）が自分で書く
- 要件定義書・設計書・実装に、この範囲を超える書き込みを書かない。超える必要があると考えたら、書く前に利用者に確認する

## 仕様は自分の文書だけで完結させる [MANDATORY]

- 要件定義書・設計書で、他のプロジェクト・他のプラグイン（DocAdvisor 等）を参照して仕様を決めない。「〜と同じとする」「〜に合わせる」と書かない
- 参考にした内容は、自分の仕様として取り出し、本文に書く。参照先が消えても仕様が分かる状態を保つ
- 置き換え対象であることなどの経緯を述べるのはよい

## コマンド

```bash
# Markdown/JSON/YAML/TOML の整形チェック
dprint check
# 整形を適用
dprint fmt

# 単体テスト
uv run --python 3.15 --exclude-newer "3 days" --with markdown-it-py python -m unittest discover -s tests -p 'test_*.py'
```

## ドキュメント構成

| ディレクトリ                         | 内容                                                                                                         |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| `docs/specs/requirement/REQ-*`       | 要件定義書（正本: 実現する振る舞いと制約）。`REQ-001` が総論で全体の文書構成・決定事項・未決事項を持つ       |
| `docs/specs/design/DES-*`            | 設計書（正本: どの主体・情報・状態・処理で実現するか）。構成は `docs/specs/design/README.md` の対応表を参照  |
| `docs/rules/`                        | 本リポジトリの開発ルール（実装ガイドライン、SKILL・Agent の作成規約、script の出力規約、Agent との受け渡し） |
| `docs/specs/adr/`, `docs/reference/` | 現時点では空                                                                                                 |

要件と設計が食い違う場合、**設計だけで要件を上書きしない**。未決事項を解決するまで、該当する遷移・結果を確定仕様として扱わない（`docs/specs/design/README.md`「確定を妨げる判断待ち」参照）。

## 文書を書く・直すときのルール

- 文書の記述スタイル（タグ・見出し・参照記法・履歴を置かない等）は、末尾の forge 規範ブロックと forge 同梱の文書スタイル指針に従う。
- 仕様書では、用語集（`docs/specs/requirement/REQ-001_overview.md` の §4）の用語を `[用語]` の形で書く。新しい用語は用語集に定義してから使う。
- 実装（`plugins/` 配下の script・SKILL.md）を書く段階になったら、[docs/rules/doc-link_implementation_rules.md][doc_link_implementation_rules]（doc-link 固有。汎用の規範文書に優先する）と、汎用の規範文書に従う。特に以下は MANDATORY:
  - Python script は `uv run` で実行し、依存は PEP 723 で宣言する。外部依存は PyYAML と markdown-it-py のみ許容。版番号を手で書かない
  - Node.js を使わない（ツール・パッケージ。GitHub Actions のアクションは対象外）
  - `plugins/` 配下の `.py` にはテスト必須（配置とコマンドは doc-link 実装ルール）
  - SKILL.md にロジックをインライン記述しない。独立スクリプトを呼び出す形にする
  - 配布物（SKILL.md / agents / commands / 配布物内蔵 docs）から本リポジトリの `docs/specs/` `docs/rules/` を参照しない
  - バージョン関連ファイル（`plugin.json` の version、CHANGELOG 等）は作業 PR で編集しない。更新は `/forge:update-version` のみ
- 汎用の規範文書は次のとおり。
  - 実装: [plugin_implementation_guidelines.md][plugin_implementation_guidelines]
  - uv による実行・依存の追加・ロック・更新: [plugin_uv_usage_rules.md][plugin_uv_usage_rules]
  - SKILL とカスタム Agent の組み方: [plugin_claude_code_authoring_guide.md][plugin_claude_code_authoring_guide]、依拠する Claude Code の事実: [plugin_claude_code_reference.md][plugin_claude_code_reference]
  - script の終了コード・標準出力の契約: [plugin_script_error_output_rules.md][plugin_script_error_output_rules]（`0`/`1`/`2` は全 script 共通、`3` 以上は script 自身の docstring で宣言）
- SKILL とカスタム Agent の間の一過性データの受け渡しは [docs/rules/agent_data_exchange_rules.md][agent_data_exchange_rules] に従う。

[doc_link_implementation_rules]: docs/rules/doc-link_implementation_rules.md
[plugin_implementation_guidelines]: docs/rules/plugin_implementation_guidelines.md
[plugin_uv_usage_rules]: docs/rules/plugin_uv_usage_rules.md
[plugin_claude_code_authoring_guide]: docs/rules/plugin_claude_code_authoring_guide.md
[plugin_claude_code_reference]: docs/rules/plugin_claude_code_reference.md
[plugin_script_error_output_rules]: docs/rules/plugin_script_error_output_rules.md
[agent_data_exchange_rules]: docs/rules/agent_data_exchange_rules.md

<!-- FORGE_ONBOARDING_START hash=6a3a278b2d31 -->

> このブロックは forge の onboarding スキルが生成する。手で編集しない（次回実行で上書きされる）。
> `${CLAUDE_PLUGIN_ROOT}` は forge プラグインの配置先を指すプレースホルダであり、この文脈では実パスに解決されない。実体を読むには onboarding スキルを起動する。
> forge はこのブロックの範囲だけ CLAUDE.md を利用している。ブロックの外側はプロジェクトの所有物。

## forge SSOT の定義

- SSOT とは「真理が単一」であることではなく、ある関心事について「変更と不整合を収束させる先が一意」であること。正本は絶対的な真理ではなく、反証されれば更新される循環の現在値である。

## forge 文書規範

- 文書内に「改定履歴」「変更履歴」等の履歴セクションを置かない。履歴は CHANGELOG と git 履歴が持ち、設計判断の変更は ADR に記録する
- 「関連文書」等のリンク集セクションを置かない。必要でない参照は書かない。書かなければ本文が理解・検証できない参照だけを `[表示名](相対パス)` 形式で書く
- 要件（What）と設計（How）の境界は「ユーザーマニュアルに書く内容か」で判定する。ただし決定済みの「設計」「実装」は要件として記載されることもある。
- 設計中に要件定義書に無い必要が判明したら設計を止める。要件へ戻す場合も、戻せず設計書に書く場合も、ユーザーの承認を得る。後者は承認を ADR に記録し、設計書の当該節からリンクする
- 未確定の定量値を推測して書かない（TBD とする）。責務分割・境界・依存方向などの構造品質を数値目標に翻訳しない
- 実装・設計・命名を変えて文書と乖離が生じたら、同じ変更の中で文書も直す
- ADR に仕様・ルールの本文を写さない（真実源が 2 つになる）。ADR を根拠に提案を見送るときは、棄却理由の前提が今も成立するかを確かめ、根拠にした ADR ID を添える。ADR の節番号は変えない
- 新規の文書 ID（REQ- / DES- / ADR- 等）を手動で採番しない（採番スキルを使う。並行ブランチでの ID 衝突を防ぐ）
- 差分開発型と判定した文書には、一時マーカー（frontmatter の `feature_type: temporary-feature`）を付ける。判定は要件定義書・設計書それぞれで行い、両方に付くとは限らない（要件定義書が差分開発型なら設計書にも付く。要件定義書が差分でなくても、設計が既存の設計書を変えるなら設計書だけに付く）

## forge 実装規範 [MANDATORY]

- 読まずに書き始めない。必読文書・検索でヒットした文書は、見出しや部分読みで済ませず本文を読む。調査は「該当なし」も記録し、未調査と区別できるようにする
- 推測で埋めない。仕様・設計に無い値を空想（類似からのコピー・「よくある値」）で実装しない。重要な仕様が未定義なら実装を止めて報告する
- 依って立つ文書（要件定義書・設計書・計画書・ルール）どうしの矛盾や誤りに気づいたら、実装・設計・計画・レビューのどの作業でも、他の何より先に止めて報告する。どちらを正とするかは利用者が決める。気づいたまま先へ進めない
- 実装で同じ役割のものを並べない。作る前に既存資産を探し、使えるものは使う。合わないものは直すか置き換える（整合のための削除は必要な労力である）。兄弟機能で確立されたパターンを壊さない。スコープ境界や影響範囲の狭さを口実に、同種の実装を並列に新設しない
- 設計は既存の実装に合わせず、要件から組み立てる。既存の実装をどう修正・削除・統合・分割するかは、設計ではなく実装戦略書が決める
- 複数箇所から参照される共用部品を、1 箇所の都合のために書き換えない
- 差分 feature を使うかは、要件定義書・設計書が定める意味が変わるかで判定する。意味を変えるなら差分 feature を使い、実装期間中は旧仕様ファイルを書き換えず、新規ファイルへ切り出す。意味の変更を「バグ修正」と呼んで、この手続きを飛ばさない
- 不具合（意味の正しい仕様に、実装や文書の記述が食い違っている状態）は差分開発にせず、原本を直接直す。文書の記述を書き換えても、意味が変わらなければ不具合の修正である
- 修正の検証は変更を反映した実体で行う。変更前の状態で得た結果を根拠に「直った」と判断しない。改名・語彙改訂・大規模な書き換えの後は、改名した識別子だけでなくその別名・形式の呼び名も検索し、検索語と範囲を残してから完了とする
- 「理論上あり得る」だけを根拠にした防御実装・投機的対策を積み増さない。この抑止を適用してよいのは投機的な防御の類型だけであり、判定に迷う指摘は通常どおり修正対象として扱う

## forge 機密情報 [MANDATORY]

- 認証情報・秘密鍵・資格情報を含む接続文字列・実在する個人の情報・内部ネットワーク情報をリポジトリに含めない
- commit された秘密は削除しても漏洩として扱う。修正は該当する秘密の失効・再発行を伴う
- 例示に実在の値を一部改変したものを使わない（公式の例示値・明白なプレースホルダを使う）。混入かどうか判断に迷う値は混入として扱う

## forge プロジェクト文書

- プロジェクトルール文書の参照には `query-db-rules` SKILL を使う
- プロジェクトルール文書の更新後には `update-db-rules` SKILL を使う
- プロジェクト仕様の参照には `query-db-specs` SKILL を使う
- プロジェクト仕様の更新後には `update-db-specs` SKILL を使う

## forge 重要規約

- **実装・文書改編に着手する前に `/forge:query-forge-rules`・`/forge:query-db-rules` で関連する原則・ルールを特定して読む**（スキル経由の作業は各スキルの調査 Phase がこれを担う。会話直の作業でも省略しない）
- **ルールはルール文書管理**: コンテキスト肥大化防止のため、CLAUDE.md にルールを詰め込まないことを推奨する
- **一般の作業で CHANGELOG.md・version 関連ファイルを編集しない**。リリースコミットでまとめて更新（`/forge:update-version` を使う）
- **`.toc_work/` 等の消えるべき一時物は `.gitignore` に入れない**。残存が `git status` に untracked として出ることで異常を検知できる
- セマンティック検索とは、字句の一致ではなく意味に基づいて文書を選ぶ検索であり、実現手段（ベクトル類似度か LLM による読解か）は問わない
- query-db-xxx SKILL はセマンティック検索であり、ワード一致検索（grep）ではない。**取りこぼしを出さないこと（false negative 厳禁）を規約として検索する**ため、意味的に近い文書を広く拾って返す。最終的に何を読むかは、何を求めて検索したかを知っている検索の実行主体が判断する
- doc-advisor のフロントマターを持つ文書を編集したら、`/doc-advisor:write-frontmatter --paths <編集した文書>` で再生成する。`Edit` / `Write` で直接書き換えてはならない（`body_hash` の打刻・値域検証・マージ規則は script の責務であり、手書きでは信頼されないフロントマターになる）。**編集した本人がその場で書いておく**。信頼できるフロントマターが原本にあれば、後日 `update-db-rules` / `update-db-specs` が走るときに AI 抽出が省かれ、索引が高速に作られる（信頼できなければ AI 抽出へフォールバックする）
- **forge plugin の script は、対応する SKILL.md が明示的に「直接呼び出す」と指示しているもの以外は直接実行しない**

<!-- FORGE_ONBOARDING_END -->
