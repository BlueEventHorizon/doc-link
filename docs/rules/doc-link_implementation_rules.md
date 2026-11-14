# doc-link 実装ルール

doc-link の実装に固有のルール。`plugin_` で始まる汎用の規範文書（実装ガイドライン・uv 利用ルール・Claude Code 作成ガイド・Claude Code リファレンス・script のエラー出力）と食い違う点は、本文書が優先する。汎用の規範文書は、プロジェクト固有の採否をプロジェクトの文書に委ねている。

## 優先する範囲 [MANDATORY]

本文書が汎用の規範文書より優先するのは、次の項目だけである。ここに無い項目は、汎用の規範文書に従う。

| 汎用の規範文書の記述                                                 | doc-link の扱い                   |
| -------------------------------------------------------------------- | --------------------------------- |
| Python script は標準ライブラリのみを基本とし、利用者に依存を求めない | 下記「実行と依存」のとおり        |
| 設定は JSON にするか自前で読む                                       | PyYAML を使う                     |
| SKILL.md の呼び出し例が `python3`                                    | `uv run` で呼ぶ                   |
| fork 型 SKILL は既定で避ける                                         | 書かない                          |
| テストの配置とコマンドを定めない                                     | 下記「テスト」のとおり            |
| `exclude-newer` を script のメタデータへ書く                         | 下記「uv のコマンドの形」のとおり |

## 実行と依存 [MANDATORY]

- Python script は `uv run` で実行し、依存は script ごとに PEP 723 のインラインメタデータで宣言する。利用者の環境に必要なのは uv だけである
- 外部依存は次の 2 つだけである。ほかの依存を足すときは、利用者の許諾を得る
  - PyYAML（標準ライブラリに YAML パーサーが無いため）
  - markdown-it-py（CommonMark 準拠の Markdown パーサーが標準ライブラリに無いため）
- 外部コマンドの呼び出しは Bash で行う

## Node.js [MANDATORY]

- Node.js を使わない。Node.js で動くツール・パッケージに依存しない
- GitHub Actions のアクションは対象外とする

## SKILL の実行モデル [MANDATORY]

- SKILL はすべて継承型で書く。`context: fork` / `agent` を書かない
- 隔離 context が要る処理は、カスタム Agent にする

## テスト [MANDATORY]

- `plugins/` 配下の `.py` には、テストを付ける
- テストは `tests/{plugin}/{skill}/` に置き、`test_{module}.py` と命名する
- プラグイン直下の `scripts/` に置く共通 script のテストは、`tests/{plugin}/scripts/` に置く
- `scripts` という名前のスキルは作らない
- テストは次のコマンドで実行する

```bash
uv run --python 3.15 --exclude-newer "3 days" --with markdown-it-py python -m unittest discover -s tests -p 'test_*.py'
```

## uv のコマンドの形

- SKILL.md・Agent 定義・テストが呼ぶ script は、`uv run --locked --exclude-newer "3 days"` で実行する
- この形は、汎用の uv 利用ルール（`exclude-newer` を script のメタデータへ書く）に未適合である。メタデータへの移行が済むまでの現行の形を、ここに置く
