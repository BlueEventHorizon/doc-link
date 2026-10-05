# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクトの状態

本リポジトリは Claude Code 用プラグイン `doc-link`（仮称、既存の DocAdvisor を置き換える文書検索・索引管理プラグイン）の**要件定義・設計段階**にある。`plugins/` や `tests/` 配下の実装コードはまだ存在せず、`doc/` 配下の仕様書・ルール文書のみが追跡対象。CI (`.github/workflows/ci.yml`) は将来の実装を見越して `tests/` の unittest 実行と `dprint check` を既に走らせている。

doc-link が実現しようとしている内容（パスでなく文書 ID による恒久的な文書管理、参照関係の機械的把握、変更影響の通知）は `doc/spec/requirement/REQ-001-overview.md` の「1. 文書の目的」「3. 目的」に要約がある。

## コマンド

```bash
# Markdown/JSON/YAML/TOML の整形チェック（CI と同じ）
dprint check
# 整形を適用
dprint fmt

# 単体テスト（tests/ が作成されたら）
python3 -m unittest discover -s tests -p 'test_*.py'
```

## ドキュメント構成

| ディレクトリ                 | 内容                                                                                                      |
| ---------------------------- | --------------------------------------------------------------------------------------------------------- |
| `doc/spec/requirement/REQ-*` | 要件定義書（正本: 実現する振る舞いと制約）。`REQ-001` が総論で全体の文書構成・決定事項・未決事項を持つ    |
| `doc/spec/design/DES-*`      | 設計書（正本: どの主体・情報・状態・処理で実現するか）。構成は `doc/spec/design/README.md` の対応表を参照 |
| `doc/rule/`                  | 本リポジトリの開発ルール（執筆手順・実装ガイドライン・出力規約）                                          |
| `doc/adr/`, `doc/reference/` | 現時点では空                                                                                              |

要件と設計が食い違う場合、**設計だけで要件を上書きしない**。未決事項を解決するまで、該当する遷移・結果を確定仕様として扱わない（`doc/spec/design/README.md`「確定を妨げる判断待ち」参照）。

## 文書を書く・直すときのルール

- 要件定義書から設計書を起こす手順は `doc/rule/requirements_to_design.md` に従う。設計は要件の言い換えではなく、複数要件が組み合わさったときの振る舞いを定義する。確定事項・導出できる設計・判断待ちの選択肢を分けて書く。
- 文書の見出し・タグ・用語統一・frontmatter 等の表記規約は `doc/rule/document_writing_rules.md` に従う。
- 実装（`plugins/` 配下の script・SKILL.md）を書く段階になったら `doc/rule/implementation_guidelines.md` に従う。特に以下は MANDATORY:
  - Python は標準ライブラリのみ（例外: PyYAML のみ許容）。外部コマンド呼び出しは Bash
  - `plugins/` 配下の `.py` にはテスト必須（`tests/{plugin}/{skill}/` に配置、`test_*.py` 命名）
  - SKILL.md にロジックをインライン記述しない。独立スクリプトを呼び出す形にする
  - 配布物（SKILL.md / agents / commands / 配布物内蔵 docs）から本リポジトリの `docs/specs/` `docs/rules/` を参照しない
  - バージョン関連ファイル（`plugin.json` の version、CHANGELOG 等）は作業 PR で編集しない。更新は `/forge:update-version` のみ
- script の終了コード・標準出力の契約は `doc/rule/script_error_output_rules.md` に従う（`0`/`1`/`2` は全 script 共通、`3` 以上は script 自身の docstring で宣言）。
- シェルスクリプトの色分け・表示形式は `doc/rule/cli_output_formatting.md` に従う。
