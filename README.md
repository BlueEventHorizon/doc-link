# doc-link

Claude Code 用プラグイン `doc-link` の配布リポジトリ。

doc-link は、プロジェクトの Markdown 文書をパスではなく恒久的な文書 ID（DLID）で管理する。文書の移動・改名に影響されずに索引（ToC）を保ち、タスクに関連する文書を検索し、文書間の参照関係を機械的に把握して、変更された文書を参照している文書をプロジェクト管理 AI へ通知する。DocAdvisor を置き換えることを目的とする。

> [!NOTE]
> 現在は実装中であり、利用できる SKILL はまだ無い。

## インストール

Claude Code のセッションで、このリポジトリを marketplace として登録してから、プラグインを入れる。

```text
/plugin marketplace add BlueEventHorizon/doc-link
/plugin install doc-link@doc-link
/reload-plugins
```

Claude Code v2.1.275 以降では、次の 1 行でもよい（新しい marketplace の追加は確認を経てから行われる）。

```text
/plugin install doc-link --marketplace BlueEventHorizon/doc-link
```

### インストールの範囲

| 範囲    | 有効になる場所                 | 保存先                        | git で共有されるか |
| ------- | ------------------------------ | ----------------------------- | ------------------ |
| user    | 自分の、すべてのプロジェクト   | `~/.claude/settings.json`     | されない           |
| project | このリポジトリの共同作業者全員 | `.claude/settings.json`       | 有効化の設定だけ   |
| local   | 自分の、このリポジトリだけ     | `.claude/settings.local.json` | されない           |

- セッションで `/plugin install` を実行すると、`/plugin` の画面でプラグインの詳細が開き、範囲（User / Project / Local）を選べる
- シェルの `claude plugin install` は、`--scope` を付けなければ user の範囲に入れる（すべてのプロジェクトで使える）

```bash
claude plugin install doc-link@doc-link --scope project   # user | project | local
```

- project の範囲は、git で追跡する `.claude/settings.json` に有効化の設定を書く。共有されるのは有効化の設定だけなので、共同作業者はそれぞれ一度 `claude plugin install doc-link@doc-link --scope project` を実行する

### Codex CLI など、marketplace を使わない導入

Codex CLI 向けや、marketplace を使わずにプロジェクトへ複製して導入する仕組みは、`/meta:generate-plugin-installer` で生成する。

## ライセンス

[MIT](LICENSE)
