# DES-010 SKILL と Agent の構成

**状態**: 承認済み\
**更新日**: 2026-11-02\
**根拠**: [要件総論][req-001]、[実行主体][des-002]

<a id="sec-1"></a>

## 1. 構成

doc-link は次の 8 つの SKILL と 2 つのカスタム Agent で構成する。SKILL はいずれも呼び出し元（[プロジェクト管理 AI]）のコンテキストで実行する継承型とする（[DES-002 §3][des-002-sec-3]）。各 SKILL は処理を script に委ね、SKILL.md にロジックを書かない。

| SKILL          | 種類 | [Index 対象文書]への書き込み   | 管理状態の書き換え            | 対応する要件                                                                                   |
| -------------- | ---- | ------------------------------ | ----------------------------- | ---------------------------------------------------------------------------------------------- |
| `embed-dlid`   | 操作 | あり（[DLID]だけ、要件 D-031） | なし                          | [REQ-002 §9.2][req-002-sec-9-2]、FR-001、FR-002、D-029、D-033〜D-035                           |
| `index-docs`   | 操作 | なし（要件 D-035）             | あり（[文書情報]、[ToC]の版） | FR-017、[REQ-002 §9.1][req-002-sec-9-1]、FR-003〜FR-005、FR-009、FR-010、FR-011、FR-012、D-036 |
| `query-docs`   | 照会 | なし                           | なし                          | [REQ-004 §12][req-004-sec-12] FR-006                                                           |
| `resolve-dlid` | 照会 | なし                           | なし                          | [REQ-002 §9][req-002-sec-9] FR-018、D-047                                                      |
| `check-dlid`   | 検査 | なし                           | なし                          | [REQ-005 §15][req-005-sec-15] FR-016、[REQ-002 §9][req-002-sec-9] FR-002                       |
| `check-links`  | 検査 | なし                           | なし                          | [REQ-005 §15][req-005-sec-15] FR-016、[REQ-005 §13][req-005-sec-13] FR-009                     |
| `check-toc`    | 検査 | なし                           | なし                          | [REQ-005 §15][req-005-sec-15] FR-016、[REQ-003 §10][req-003-sec-10] FR-011                     |
| `check-impact` | 検査 | なし                           | なし                          | [REQ-005 §14][req-005-sec-14] FR-013〜FR-015、[REQ-005 §15][req-005-sec-15] FR-016、D-038      |

検査の SKILL は検出して返し、管理状態を書き換える SKILL はない。`check-impact` も書き換えない（要件 D-038、[DES-007 §3][des-007-sec-3]）。

| カスタム Agent            | 責務                                                                                                                                                                                                                                                                                                                 | 起動元       |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| `toc-updater`（情報生成） | 1 回の起動で同じディレクトリの最大 3 文書を受け持ち、文書ごとに独立して、目的・内容概要・適用作業・検索用キーワードを生成する。記述上限 `L` 以外の検証情報を持たない（要件: [REQ-003 §7.4][req-003-sec-7-4]、[REQ-003 §11.2.2][req-003-sec-11-2-2]／設計: [DES-002 §3][des-002-sec-3]、[DES-008 §4][des-008-sec-4]） | `index-docs` |
| `query-worker`（検索）    | [確定 ToC]の[ToC]全体を読んで、タスクに関連する文書を選び、関連理由とともに返す。読み取り専用で、存在しない ID を補わず、[ToC]と管理状態を変更しない（要件: [REQ-004 §12][req-004-sec-12] FR-006／設計: [DES-006 §2][des-006-sec-2]）                                                                                | `query-docs` |

<a id="sec-1-1"></a>

### 1.1 操作と照会の SKILL の責務

`embed-dlid`

- [文書 ID]の無い文書へ[DLID]を発行し、frontmatter に書き込む（要件: [REQ-002 §9.2][req-002-sec-9-2]／設計: [DES-005 §2.1][des-005-sec-2-1]、[DES-008 §1][des-008-sec-1]）
- [セクション ID]を持たないすべての見出しへ[セクション ID]を発行し、見出しの行の末尾に書き込む（要件: [REQ-005 §13.1][req-005-sec-13-1]／設計: [DES-005 §2.1][des-005-sec-2-1]、[DES-008 §1][des-008-sec-1]）
- 同じ ID を持つ文書が複数あるとき、原本の候補を利用者に示し、利用者が原本を確定した後、複製側に新しい ID を発行して書き込む（要件: [REQ-002 §9][req-002-sec-9] FR-002／設計: [DES-005 §2.1][des-005-sec-2-1]）
- リンクとその title は書き換えない。既存文書の移行も、全対象への[文書 ID]の付与と[セクション ID]の発行だけで行う（要件: [REQ-002 §9.2][req-002-sec-9-2]、[REQ-001 §19][req-001-sec-19] D-034・D-042／設計: [DES-005 §2.1][des-005-sec-2-1]）

`index-docs`

- 対象を確定し、[文書 ID]を確認する。ID の無い文書と ID が重複する文書は[ToC]に入れずに報告する（要件: [REQ-002 §8][req-002-sec-8]、[REQ-002 §9.1][req-002-sec-9-1]／設計: [DES-005 §2][des-005-sec-2]）
- [確定 ToC]と現物の差分を検出する（要件: [REQ-003 §10][req-003-sec-10]／設計: [DES-005 §3][des-005-sec-3]）
- 生成が必要な文書だけ `toc-updater` に依頼し、結果を検証する（要件: [REQ-003 §11.2.2][req-003-sec-11-2-2]、[REQ-003 §7.4][req-003-sec-7-4]／設計: [DES-005 §4・§5][des-005-sec-4]、[DES-008 §4][des-008-sec-4]）
- 参照先ディレクトリを実走査して参照を検査する（要件: [REQ-005 §13][req-005-sec-13]／設計: [DES-007 §1][des-007-sec-1]）
- [ToC]の候補を検査し、一括して確定する（要件: [REQ-003 §11.2.4][req-003-sec-11-2-4]／設計: [DES-005 §4][des-005-sec-4]、[DES-004 §3][des-004-sec-3]）

`query-docs`

- 検索前に再構築の要否を検査し、必要なら再構築の規模を示して利用者に二択を確認する（要件: [REQ-004 §12][req-004-sec-12]／設計: [DES-006 §1][des-006-sec-1]）
- [確定 ToC]から文書を検索し、使用した版と鮮度を添えて返す（要件: [REQ-004 §12][req-004-sec-12]／設計: [DES-006 §2][des-006-sec-2]）

`resolve-dlid`

- 渡された[DLID]ごとに、管理状態に記録されたパスを、その文書が今もその[DLID]を持つことを確かめてから返す。[セクション ID]には見出しとアンカーを添える。確かめられない[DLID]には記録されたパスに無いことを、記録の無い[DLID]にはそのことを返す。解決済みには、記録した[内容ハッシュ]を添える（要件: [REQ-002 §9][req-002-sec-9] FR-018／設計: [DES-006 §3][des-006-sec-3]）

<a id="sec-1-2"></a>

### 1.2 検査の SKILL の責務

| SKILL          | 検出する状態                                                                                                                                                                                                                                                                                  | 検出後にすべきこと（誰が、何で）                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `check-dlid`   | [文書 ID]が無い。[セクション ID]の無い見出しがある。[文書 ID]または[セクション ID]が重複している（[セクション ID]は同じ文書の中を含む）                                                                                                                                                       | ユーザーまたは[プロジェクト管理 AI]が `embed-dlid` を実行する。重複は、示された候補から利用者が原本を確定する                                                                                                                                                                                                                                                                                                                                                                                   |
| `check-links`  | 壊れた参照。ID とパスの不一致。存在しないセクションへの参照。フラグメントが参照先のセクションへ解決しないリンク。参照先ディレクトリに見つからない。`doc_link_id` を持つ Markdown を指しているが title に[DLID]の無いリンク。[DLID]入りの title を持つが、リファレンスリンクの定義でないリンク | title に[DLID]の無いリンクには、[プロジェクト管理 AI]が参照先の[DLID]と、`resolve-dlid` で得た参照先の[内容ハッシュ]を title に書く。インラインリンクは、リファレンスリンクの定義に書き換える。[プロジェクト管理 AI]がリンクを直す。パスの不一致には確認できた現在のパスが添えられる（FR-010）。フラグメント不一致には、そのセクションへ届く現在のアンカーが添えられる（FR-009）。参照先が見つからない場合は、移動か削除かを[プロジェクト管理 AI]が判断する。直した後は `index-docs` を実行する |
| `check-toc`    | [ToC]が無い（未構築）。[ToC]と実体ファイルの不一致（新規、離脱、移動、参照の違い、[ToC]に反映したハッシュと[現在ハッシュ]の違い。参照の違いは title に記録した[内容ハッシュ]を除いて比べる）                                                                                                  | `index-docs` を実行する                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `check-impact` | 参照元の title に記録した[内容ハッシュ]が、参照先の[現在ハッシュ]と異なる参照（記録が無い参照を含む）と、[ToC]から把握できるその参照元。[ToC]が最新であることが前提で、古ければ変更影響候補を返さずに `check-toc` と同じ結果を返す                                                            | [プロジェクト管理 AI]が、参照元の修正が必要かを判断し、必要なら直す。確かめたあと、参照元の title の[内容ハッシュ]を書き換える。参照元を直したときは `index-docs` を実行する。書き換えるまで、同じ参照が次の `check-impact` でも返る。修正した参照元を参照する文書は、次の `check-impact` で新しい変更として現れる                                                                                                                                                                              |

検査ごとの根拠は次のとおり。

- `check-dlid`: 要件[REQ-005 §15][req-005-sec-15] FR-016、[REQ-002 §9][req-002-sec-9] FR-002／設計[DES-005 §2][des-005-sec-2]、[DES-008 §1][des-008-sec-1]
- `check-links`: 要件[REQ-005 §13][req-005-sec-13] FR-009・FR-010、[REQ-001 §19][req-001-sec-19] D-042、[REQ-005 §15][req-005-sec-15] FR-016／設計[DES-007 §1][des-007-sec-1]
- `check-toc`: 要件[REQ-003 §10][req-003-sec-10] FR-011、[REQ-005 §15][req-005-sec-15] FR-016／設計[DES-005 §3][des-005-sec-3]、[DES-006 §1][des-006-sec-1]。`query-docs` の検索前検査と同じ script を使い、渡された完全な対象指定を保存済みの指定より優先する（要件 FR-006、FR-016）
- `check-impact`: 要件[REQ-005 §14][req-005-sec-14] FR-013〜FR-015、D-038／設計[DES-007 §2・§3][des-007-sec-2]

`check-impact` は、title の記録と参照先の[現在ハッシュ]が異なる参照を、変更された文書ごとにまとめて返す。

- 変更された文書の配列を返し、その要素ごとに直接の参照元の配列を持つ。
- 各参照元に、title に記録した[内容ハッシュ]（記録なしを含む）と、参照先の[現在ハッシュ]を添える。
- [セクション ID]を指す参照元は、そのセクションの範囲の[現在ハッシュ]と比べる（要件 D-033）。
- 異なる参照が無いときは、空の配列と検査範囲を返す（FR-014）。
- 間接の参照元は含めない。参照元を直すと、その参照元が次の `check-impact` で変更として現れるので、間接的な影響は 1 段ずつ検出される（要件 D-043）。
- 通知の状態は持たない。比べる基準は、参照元の title の記録だけである（[DES-007 §3][des-007-sec-3]）。

<a id="sec-2"></a>

## 2. ユースケース

```mermaid
flowchart LR
    User(["ユーザー"])
    PM(["プロジェクト管理 AI"])
    Caller(["呼び出し元スキル（forge など）"])

    subgraph DL["doc-link"]
        UC1["文書に DLID を付与する<br>embed-dlid"]
        UC2["ToC を構築・再構築する<br>index-docs"]
        UC3["文書を検索する<br>query-docs"]
        UC4["DLID から現在のパスを得る<br>resolve-dlid"]
        subgraph CHK["検査"]
            UC5["文書 ID を検査する<br>check-dlid"]
            UC6["参照を検査する<br>check-links"]
            UC7["ToC の鮮度を検査する<br>check-toc"]
            UC8["変更の影響を検査する<br>check-impact"]
        end
    end

    User --> UC1
    User --> UC2
    User --> UC3
    User --> UC4
    PM --> UC1
    PM --> UC2
    PM --> UC3
    PM --> UC4
    PM --> CHK
    Caller --> UC1
    Caller --> UC2
    Caller --> UC3
    Caller --> UC4
    Caller --> CHK
    UC3 -. "利用者が再構築を選んだとき" .-> UC2
    UC4 -. "記録されたパスに無いとき" .-> UC2
    UC5 -. "検出したとき" .-> UC1
    UC7 -. "不一致があるとき" .-> UC2
```

ユーザーは `embed-dlid` で重複する ID の原本を確定し、`query-docs` で再構築の二択を選ぶ。検査の SKILL は、[プロジェクト管理 AI]と呼び出し元スキルのどちらからも呼び出せる。呼び出し元スキルは呼び出し元のコンテキストで実行されるので、検査の結果は同じ[プロジェクト管理 AI]に届く。たとえば呼び出し元スキルは、検索の前に再構築が必要かを `check-toc` で判断できる。呼び出し元スキルは文書を[DLID]で記録しておき、読む時点で `resolve-dlid` から現在のパスを得る。

<a id="sec-3"></a>

## 3. SKILL ごとのシーケンス

各図の「後工程」は、SKILL の結果を受けて[プロジェクト管理 AI]が続けて行う作業を示す。

<a id="sec-3-1"></a>

### 3.1 embed-dlid

起動を書き込みの承認とし、重複する ID の原本の確定以外では利用者に確認しない（要件 D-040）。対象は `index-docs` と同じ[ToC 識別キー]と[Index 対象指定]で決める（要件 D-041）。

```mermaid
sequenceDiagram
    actor User as ユーザー
    participant PM as プロジェクト管理 AI
    participant Skill as embed-dlid
    participant Scripts as script 群
    participant State as 管理状態
    participant Docs as Index 対象文書
    participant Index as index-docs

    PM->>Skill: ToC 識別キーと Index 対象指定を渡して起動
    Skill->>Scripts: 付与計画の作成
    Scripts->>Docs: doc_link_id・見出し・リンクを読み取る
    Scripts->>State: 既存の ID と照合する
    Scripts-->>Skill: ID 未付与の文書、重複と原本候補、発行するセクション DLID
    opt ID の重複がある
        Skill->>User: 原本候補を示す
        User-->>Skill: 原本を確定する
    end
    Skill->>Scripts: 付与計画と確定した原本を渡して書き込む
    loop 文書ごと
        Scripts->>Docs: DLID を書き込む
        Scripts->>Docs: 再解析して差分が DLID だけかを検証する
    end
    Scripts-->>Skill: 書き込み結果
    Skill-->>PM: 書き込んだ文書・位置・DLID と、書き込めなかった文書ごとのパス・問題箇所・原因
    Note over PM,Index: 後工程
    PM->>Index: ToC を構築・再構築する
```

<a id="sec-3-2"></a>

### 3.2 index-docs

SKILL は入口の script を 1 本だけ呼ぶ。入口の script は段階を進め、次に SKILL が行うこと（`toc-updater` の起動、起動した Agent の完了の待機、完了、エラー）を返す。SKILL はそれに従って動き、終えたら入口の script を再び呼ぶ。図の「script 群」は入口の script とその下の script を指す。`toc-updater` は、1 回の起動で最大 3 文書を受け持たせ、同時に最大 10 本を走らせる。

```mermaid
sequenceDiagram
    participant PM as プロジェクト管理 AI
    participant Skill as index-docs
    participant Scripts as script 群
    participant Agent as toc-updater
    participant State as 管理状態
    participant Docs as Index 対象文書
    participant RefDirs as 参照先ディレクトリ
    participant Embed as embed-dlid
    participant Impact as check-impact

    PM->>Skill: ToC 識別キーと完全な対象指定
    Skill->>Scripts: 対象確定と ID 確認
    Scripts->>Docs: frontmatter を読み取る
    Scripts-->>Skill: 確定 Index 対象リストと除外した文書
    Skill->>Scripts: 差分検出と更新計画
    Scripts->>State: 確定 ToCを読み取る
    Scripts-->>Skill: 変更集合と生成対象
    loop 生成が必要な文書を最大 3 件ずつ、同時に最大 10 本
        Skill->>Agent: 文書情報の生成を依頼する
        Agent->>Scripts: 文書ごとの生成結果を渡す
        Scripts->>State: 検証して文書情報を書き込む
        Agent-->>Skill: 完了
    end
    Skill->>Scripts: 参照検査と候補の検査・確定
    Scripts->>RefDirs: 指定ディレクトリを実走査する
    Scripts->>State: ToC の版を一括して確定する
    Scripts-->>Skill: 確定結果と参照検査結果
    Skill-->>PM: 確定結果、参照検査結果、ID 未付与・重複で除外した文書
    Note over PM,Impact: 後工程
    opt 除外した文書がある
        PM->>Embed: ID を付与・解消し、index-docs を再実行する
    end
    PM->>Impact: 変更の影響を検査する
```

<a id="sec-3-3"></a>

### 3.3 query-docs

SKILL は、親の作業の指示をそのまま `query-worker` に渡さず、検索のタスクと考慮する観点に整えて渡す。親の指示に実装や編集の依頼が含まれていても、検索の依頼としてだけ渡す。

```mermaid
sequenceDiagram
    actor User as ユーザー
    participant PM as プロジェクト管理 AI
    participant Skill as query-docs
    participant Index as index-docs
    participant Scripts as script 群
    participant Worker as query-worker

    PM->>Skill: キーと検索条件
    Note over Skill: 検索条件を検索の依頼に整える
    Skill->>Scripts: 検索前検査
    Scripts-->>Skill: 未構築、再構築不要、再構築必要、判定不能のいずれか
    alt 未構築
        Skill-->>PM: 初回構築が必要と返す
    else 判定不能
        Skill-->>PM: 障害として停止し、原因を返す
    else 再構築必要
        Skill->>User: 再構築の規模を示して二択を確認する
        alt 再構築後に検索
            User-->>Skill: 再構築を選ぶ
            Skill->>Index: 起動する
            Index-->>Skill: 確定結果
        else 既存版のまま検索
            User-->>Skill: 既存版を選ぶ
        end
    end
    Skill->>Scripts: 検索に使う ToC と版・鮮度を固定する
    Scripts-->>Skill: ToC、使用版、鮮度
    Skill->>Worker: 検索依頼と ToC
    Worker-->>Skill: 関連する文書と関連理由
    Skill-->>PM: 検索結果（使用版と鮮度を添える）
    Note over PM: 後工程: 検索結果の文書を読み、作業に使う
```

<a id="sec-3-4"></a>

### 3.4 check-dlid

```mermaid
sequenceDiagram
    participant PM as プロジェクト管理 AI
    participant Skill as check-dlid
    participant Scripts as script 群
    participant Docs as Index 対象文書
    participant Embed as embed-dlid

    PM->>Skill: ToC 識別キーと完全な対象指定
    Skill->>Scripts: 文書 ID を検査する
    Scripts->>Docs: frontmatter と見出しの行の末尾の DLID を読み取る
    Scripts-->>Skill: ID 未付与の文書と見出し、重複する DLID と該当パス
    Skill-->>PM: 検出結果
    Note over PM,Embed: 後工程
    opt 検出した文書がある
        PM->>Embed: ID を付与・解消する
    end
```

<a id="sec-3-5"></a>

### 3.5 check-links

```mermaid
sequenceDiagram
    participant PM as プロジェクト管理 AI
    participant Skill as check-links
    participant Scripts as script 群
    participant Docs as Index 対象文書
    participant RefDirs as 参照先ディレクトリ
    participant Index as index-docs

    PM->>Skill: ToC 識別キーと完全な対象指定
    Skill->>Scripts: 参照を検査する
    Scripts->>Docs: 参照元のリンクを読み取る
    Scripts->>RefDirs: 指定ディレクトリを実走査する
    Scripts-->>Skill: 壊れた参照、パス不一致と現在パス、セクション不在、フラグメント不一致と現在のアンカー、参照先不在、title に DLID の無いリンク
    Skill-->>PM: 検出結果
    Note over PM,Index: 後工程
    opt 修正が必要な参照がある
        PM->>Docs: リンクを修正する
        PM->>Index: ToC を再構築する
    end
```

<a id="sec-3-6"></a>

### 3.6 check-toc

```mermaid
sequenceDiagram
    participant PM as プロジェクト管理 AI
    participant Skill as check-toc
    participant Scripts as script 群
    participant State as 管理状態
    participant Docs as Index 対象文書
    participant Index as index-docs

    PM->>Skill: ToC 識別キーと完全な対象指定
    Skill->>Scripts: ToC と現物を照合する
    Scripts->>State: 確定 ToCを読み取る
    Scripts->>Docs: 対象文書のハッシュを計算する
    Scripts-->>Skill: 未構築、新規・離脱・移動・内容変更の一覧、または判定不能
    Skill-->>PM: 検出結果
    Note over PM,Index: 後工程
    opt 不一致がある
        PM->>Index: ToC を再構築する
    end
```

<a id="sec-3-7"></a>

### 3.7 check-impact

```mermaid
sequenceDiagram
    participant PM as プロジェクト管理 AI
    participant Skill as check-impact
    participant Scripts as script 群
    participant State as 管理状態
    participant Docs as Index 対象文書
    participant Index as index-docs

    PM->>Skill: ToC 識別キーと完全な対象指定
    Skill->>Scripts: ToC が最新かを確かめる
    alt ToC が古い
        Scripts-->>Skill: check-toc と同じ検出結果
        Skill-->>PM: index-docs の実行を案内する
    else ToC が最新
        Skill->>Scripts: 記録と違う参照を列挙する
        Scripts->>State: 参照関係と、参照先の反映済みハッシュを読み取る
        Scripts->>Docs: 参照元の title の記録を読み取る
        Scripts-->>Skill: 変更された文書ごとの参照元の一覧
        Skill-->>PM: 変更影響候補
        Note over PM,Index: 後工程
        opt 参照元の修正が必要
            PM->>Docs: 参照元を修正する
            PM->>Index: ToC を再構築する
        end
        PM->>Docs: title の内容ハッシュを書き換える
    end
```

`check-impact` は、変更影響候補を返したあとの動きを、[プロジェクト管理 AI]に次のとおり指示する。判断・修正・title の[内容ハッシュ]の書き換えは[プロジェクト管理 AI]が行い、script は行わない（要件 FR-014、D-031）。

- 変更箇所と参照元の文書を読み、参照元の修正が必要かを判断する。
- 必要なら、参照元を直す。
- 確かめた参照の title に、参照先の[現在ハッシュ]を書く。値は `check-impact` が返したものを使う。
- 確かめていない参照の title は、書き換えない。
- 参照元を直したときは、`index-docs` を実行する。title の[内容ハッシュ]だけを書いたときは、実行しなくてよい。
- 書いたあとは、`check-impact` をもう一度実行する。
- 報告が空になるまで、これを繰り返す。

<a id="sec-3-8"></a>

### 3.8 resolve-dlid

```mermaid
sequenceDiagram
    participant Caller as 呼び出し元スキル・プロジェクト管理 AI
    participant Skill as resolve-dlid
    participant Scripts as script 群
    participant State as 管理状態
    participant Docs as Index 対象文書
    participant Index as index-docs

    Caller->>Skill: DLID の並び
    Skill->>Scripts: 解決を依頼する
    Scripts->>State: 記録されたパス、所属する文書、内容ハッシュを読み取る
    alt 管理状態を読み取れない
        Scripts-->>Skill: 失敗と原因
        Skill-->>Caller: 失敗と原因を返す
    else 読み取れた
        loop DLID ごと
            Scripts->>Docs: 記録されたパスの文書を読み、DLID を照合する
        end
        Scripts-->>Skill: DLID ごとの解決結果
        Skill-->>Caller: 解決済み（パス、内容ハッシュ、セクションは見出しとアンカー）、記録されたパスに無い、記録が無いのいずれか
        Note over Caller,Index: 後工程
        opt 記録されたパスに無い DLID がある
            Caller->>Index: ToC を再構築する
        end
    end
```

[プロジェクト管理 AI]が参照を書くときは、次の順で行う。

- 参照先を含む[ToC 識別キー]で `check-toc` を実行する。古ければ、`index-docs` を実行する。
- `resolve-dlid` で、参照先の[DLID]のパスと[内容ハッシュ]を得る。
- リファレンスリンクの定義の title に、`"<内容ハッシュ> DLID-…"` を書く。
- 参照の行を足したときは、参照元の本文が変わるので、`index-docs` を実行する。
- title の[内容ハッシュ]だけを書き換えたときは、参照元の[内容ハッシュ]が変わらないので、`index-docs` は要らない。

<a id="sec-4"></a>

## 4. カスタム Agent との受け渡し

SKILL とカスタム Agent の間の依頼と結果は、[Agent とのデータ受け渡し規約][exchange-rules]に従う。運ぶのは script が生成した識別値だけで、置き場は `.temp/doc-link/<skill>/` の下で、識別値から script が決める（[DES-002 §4][des-002-sec-4]）。依頼と結果は script が書き、書き終えてから公開する。結果は Agent が値を script へ渡し、script が書く。読む側は script から絶対パスを受け取って直接読む。終了の値は文字列で、正常は `"0"` とする。成否は script が判定する。処理が終わったら、依頼と結果を削除する。

| 項目                               | `toc-updater`（情報生成）                                                                                   | `query-worker`（検索）                                                                                         |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| 識別値                             | 構築 ID と[文書 ID]の並び（最大 3）                                                                         | 検索 ID                                                                                                        |
| 依頼                               | 対象文書の絶対パス、フィールドごとの記述上限 `L`（要件 D-044）。内部許容上限 `H` は含めない（要件 NFR-008） | 検索のタスク、[ToC 識別キー]、検索に使う版で固定した[ToC]の写しの絶対パス（中身は[DES-006 §2][des-006-sec-2]） |
| 結果                               | 目的、内容概要、適用される作業、検索用キーワード。見出しから取得できない場合はタイトル                      | 関連する文書の[文書 ID]、関連理由、必要なら[セクション ID]の並び                                               |
| エラー値                           | `"source_unreadable"`（対象文書を読めなかった）                                                             | なし（空集合）                                                                                                 |
| script の検査                      | `L`・`H` による長さの検証（[DES-008 §4][des-008-sec-4]）                                                    | 返った[文書 ID]と[セクション ID]が、固定した[ToC]の版にあること。無い ID を含む結果は異常とする                |
| 終了の値が無い、または定義外のとき | その文書の生成を失敗とし、B-04 の失敗として扱う（[DES-004 §3][des-004-sec-3]）                              | 検索を失敗として返す                                                                                           |
| 削除する時点                       | [文書情報]を確定した後、または構築の終了時                                                                  | `query-docs` が結果を返した後                                                                                  |

[req-001]: ../requirement/REQ-001_overview.md
[des-002]: DES-002_execution-responsibilities.md
[req-002-sec-9-2]: ../requirement/REQ-002_document-id.md#sec-9-2
[req-002-sec-9-1]: ../requirement/REQ-002_document-id.md#sec-9-1
[req-004-sec-12]: ../requirement/REQ-004_search.md#sec-12
[req-005-sec-13]: ../requirement/REQ-005_references.md#sec-13
[req-005-sec-15]: ../requirement/REQ-005_references.md#sec-15
[req-002-sec-9]: ../requirement/REQ-002_document-id.md#sec-9
[req-003-sec-10]: ../requirement/REQ-003_toc.md#sec-10
[req-005-sec-14]: ../requirement/REQ-005_references.md#sec-14
[req-003-sec-7-4]: ../requirement/REQ-003_toc.md#sec-7-4
[req-003-sec-11-2-2]: ../requirement/REQ-003_toc.md#sec-11-2-2
[req-005-sec-13-1]: ../requirement/REQ-005_references.md#sec-13-1
[req-001-sec-19]: ../requirement/REQ-001_overview.md#sec-19
[req-002-sec-8]: ../requirement/REQ-002_document-id.md#sec-8
[req-003-sec-11-2-4]: ../requirement/REQ-003_toc.md#sec-11-2-4
[des-002-sec-3]: DES-002_execution-responsibilities.md#sec-3
[des-008-sec-4]: DES-008_content-rules.md#sec-4
[des-006-sec-2]: DES-006_search.md#sec-2
[des-006-sec-3]: DES-006_search.md#sec-3
[des-005-sec-2-1]: DES-005_indexing.md#sec-2-1
[des-008-sec-1]: DES-008_content-rules.md#sec-1
[des-005-sec-2]: DES-005_indexing.md#sec-2
[des-005-sec-3]: DES-005_indexing.md#sec-3
[des-005-sec-4]: DES-005_indexing.md#sec-4
[des-007-sec-1]: DES-007_references-impact.md#sec-1
[des-004-sec-3]: DES-004_state-machines.md#sec-3
[des-006-sec-1]: DES-006_search.md#sec-1
[des-007-sec-2]: DES-007_references-impact.md#sec-2
[des-007-sec-3]: DES-007_references-impact.md#sec-3
[exchange-rules]: ../../rules/agent_data_exchange_rules.md
[des-002-sec-4]: DES-002_execution-responsibilities.md#sec-4
