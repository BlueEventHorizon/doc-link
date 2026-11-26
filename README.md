# doc-link

<img src="docs/images/logo.png" alt="doc-link のロゴ。青い髪の女性が、青い糸で 2 枚の文書を結んでいる。右に、鎖の記号と doc-link の文字" width="640">

Claude Code 用プラグイン `doc-link` の配布リポジトリ。

doc-link は、プロジェクトの Markdown 文書の中から、タスクに関連する文書を意味で探して返す。キーワードの一致ではなく、AI が各文書の目的・概要・適用作業・キーワードを読み、タスクとの関連を判断する（セマンティック検索）。

この検索を支えるために、文書をパスではなく恒久的な文書 ID（DLID）で管理する。文書の移動・改名に影響されずに索引（ToC）を保ち、文書間の参照関係を機械的に把握して、変更された文書を参照している文書をプロジェクト管理 AI へ通知する。[DocAdvisor](https://github.com/BlueEventHorizon/DocAdvisor) を置き換えることを目的とする。

## 特長

- タスクの記述から、関連する文書を意味で探せる。キーワードが一致しなくても見つかる
- 文書を移動・改名しても、DLID で同じ文書として追跡できる
- 文書やセクションを変えたとき、それを参照している文書を機械的に特定できる
- リンク切れ・ID の重複・索引の不整合を検出できる

![タスクに関連する文書を探す流れ。ToC が最新かを検査し、AI が ToC を読んで意味で関連を判断し、関連理由と該当セクションを添えて返す](docs/images/semantic-search.svg)

これらは、文書と見出しに付ける DLID を土台にしている。

![DLID とは。文書の frontmatter に文書 ID、見出し行の末尾にセクション ID として付ける、恒久的な識別子](docs/images/what-is-dlid.svg)

![文書を移動・改名したときの違い。パスで管理するとリンク切れになり、DLID で管理すると同じ文書として追跡できる](docs/images/move-rename.svg)

![文書を変更したときの流れ。参照している文書を機械的に特定し、プロジェクト管理 AI へ通知し、修正が必要かを判断する](docs/images/change-impact.svg)

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

## 動作に必要なもの

- [uv](https://docs.astral.sh/uv/)。SKILL が呼ぶ script は `uv run` で実行され、Python（3.15 以上）と依存（markdown-it-py）は uv が用意する

- 任意: doc-db（doc-db-mcp-server）と OpenAI の鍵。あると、文書の検索を doc-db で行い、AI による文書情報の生成を省く（下の「検索基盤」）

## 使い方

SKILL は `/doc-link:<名前>` で呼ぶ。対象の文書は、ToC を分ける単位の名前（`--key`）と、対象の指定（`--dirs` か `--paths`）で渡す。

```text
/doc-link:index-docs --key specs --dirs docs/specs/
```

ToC を作ったときの `--key` と対象の指定は、その ToC を使う SKILL（`query-docs`、`check-toc`、`check-impact` など）にも同じものを渡す。`--key` を省くと、別の ToC（予約キー `all`）を指す。

### 文書を管理する

| SKILL          | 役割                                                                      |
| -------------- | ------------------------------------------------------------------------- |
| `check-dlid`   | 文書 ID・セクション ID が無い箇所と、重複を検査する（文書を書き換えない） |
| `embed-dlid`   | 文書の frontmatter と見出し行の末尾へ DLID を付与する                     |
| `index-docs`   | ToC を構築・再構築する                                                    |
| `check-toc`    | ToC が現物の文書に対して最新かを検査する（文書を書き換えない）            |
| `query-docs`   | タスクに関連する文書を、意味で探す。検索の前に、ToC が最新かを検査する    |
| `resolve-dlid` | DLID から、文書の現在のパスと内容ハッシュを得る（何も書き込まない）       |

### 参照を管理する

| SKILL          | 役割                                                                                                                         |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `check-links`  | title に DLID を持つ参照を検査し、移動した文書には移動先を、DLID の無いリンクには title に書く値を示す（文書を書き換えない） |
| `check-impact` | 変更された文書を参照している文書を返す。参照元の title に記録した内容ハッシュと、現在のハッシュを比べる                      |

### 基本の流れ

1. `index-docs` で、ToC を作る・更新する。その前に、`check-dlid` で DLID の無い文書を検出して `embed-dlid` で付与し（確認は要らない）、`check-links` でリンクを検査する。リンクの書き直しは、利用者に一覧を示して確認し、承認された分だけ行う（確認できない文脈では、書き直さず、一覧を報告する）
2. `query-docs` で、作業に必要な文書を探す。ToC が古いときは、再構築するかを利用者に確認する
3. 文書を変えたあとは、1 を行ってから、`check-impact` で、影響を受ける参照元を確かめる。参照元ごとに、変更箇所と参照元の記述を読み、確かめた参照の title の記録だけを書き換える（ToC が古いと、`check-impact` は影響の一覧を返さず、`check-toc` と同じ検査結果を返す）

### 検索基盤（doc-db と ToC）

ToC の構築と文書の検索の裏側（検索基盤）は、doc-db と ToC で切り替わる。

- 既定は、doc-db が動作するなら doc-db である。doc-db を使うとき、AI による文書情報の生成は行わず、文書の一覧を doc-db へ同期して検索する。検索結果は上位の結果に限られ、関連の強弱はすべて `maybe` になる。doc-db が起動していなければ、doc-link が起動して接続する（停止・常駐の設定はしない）
- doc-db に接続できない、または OpenAI の呼び出しが失敗したときは、その実行だけ ToC へ自動で切り替わり、AI が切り替えたことを知らせる。ToC が無ければ、その場で作る。次の実行は、再び doc-db を先に試す
- ToC を使い続けるには、プロジェクトルートの `.doc-link/config.json` に `{"backend": "toc"}` を書く。値は `"auto"`（既定）か `"toc"` である。ファイルが無ければ `"auto"` で、不正な値は、構築・検索を行わず、原因を返す。呼び出しごとの指定はない
- **doc-db は、サンドボックスの外で起動し、常駐させておく。** サンドボックスの下の Claude Code から使うと、doc-db の OpenAI への通信が失敗し（通信の代理による TLS の書き換えなど）、ToC へ切り替わる。doc-link は、サンドボックスを調べず、サンドボックスの設定を変えない

### 書き込む範囲

doc-link が利用者の文書へ書き込むのは DLID だけである（frontmatter の `doc_link_id` と、見出し行の末尾）。利用者の文書へ書き込む SKILL は `embed-dlid` だけである（`index-docs` は、ToC と管理状態を doc-link の保存先へ書く）。リンクや title は、利用者かプロジェクト管理 AI が書く。

## ライセンス

[MIT](LICENSE)
