# DES-001 システム全体設計

**状態**: Draft 0.1・未承認\
**更新日**: 2026-10-10\
**根拠**: [要件総論](../requirement/REQ-001-overview.md)、[設計書の構成](README.md)

## 1. システム境界

doc-link は DocAdvisor を置き換え、管理対象 Markdown の文書 ID、ToC、検索、参照検査、変更影響候補の通知を担う。対象集合は呼び出し元が完全な desired state として渡す。Forge の設定ファイルは呼び出し元が解釈し、doc-link は直接読まない。管理キーは対象集合を指定するが、参照の有効範囲は限定しない。

doc-link が管理対象 Markdown に書き込めるのは `doc_link_id` の追加または置換だけである。本文・見出し・リンクの修正は、通知を受けたプロジェクト管理 AI が行う。Skill、script、AI の内部責務は [DES-002](DES-002-execution-responsibilities.md) に定める。

## 2. 全体の操作と接続

| 操作             | 主な入力                                         | 後続へ渡す結果                                   | 書き込み境界                                                     |
| ---------------- | ------------------------------------------------ | ------------------------------------------------ | ---------------------------------------------------------------- |
| ToC 構築・再構築 | 管理キー、完全な管理対象指定、現物、既存の確定版 | 確定済み ToC の版、変更集合、参照検査結果        | ID のない文書への ID 保存と、doc-link 管理状態の確定             |
| 文書検索         | キー、検索条件、確定済み ToC                     | 文書 ID、パス、関連理由、使用版・鮮度            | 古い版での検索を選んでも ToC は変更しない                        |
| 参照検査         | 参照記述と、記載パスが示すディレクトリ           | 検査範囲・時点を伴う一致／不一致／不在／検査不能 | 管理対象 Markdown のリンクは変更しない                           |
| 変更候補の通知   | 未報告の変更と把握済みの逆参照                   | 変更文書、参照元、検査範囲                       | 報告まで成功した対象の比較基準だけ進める                         |
| 不整合検査       | 管理対象指定と現物                               | 不整合一覧と調査不能箇所                         | 検査と ID 自動付与を混同しない。検査時の修正可否は別途定義が必要 |

ToC 構築・再構築は、対象確定、ID 保証、変更検出、必要情報の取得、参照検査、候補検査、確定の順に行う。初回 ToC がないキーでは検索できない。検索と変更影響候補の通知は、ToC 確定後の別操作である。報告の成功は、ToC 更新の成功と同義ではない。

## 3. 全体シーケンスの概要

次の図は ToC 構築と、その後に別操作として行う変更影響候補の通知の正常系を示す。修正要否は doc-link では判定しない。失敗分岐、検索時の確認、状態遷移の許可条件は処理別文書と [DES-004](DES-004-state-machines.md) に置く。

```mermaid
sequenceDiagram
    participant ProjectAI
    participant DocLinkSkill
    participant DeterministicScripts
    participant ContentAI
    participant ProjectDocs

    ProjectAI->>DocLinkSkill: 管理キーと完全な対象指定
    DocLinkSkill->>DeterministicScripts: 対象の走査とID保証
    DeterministicScripts->>ProjectDocs: IDの読取りと必要な保存
    ProjectDocs-->>DeterministicScripts: ID確定済み文書
    DocLinkSkill->>DeterministicScripts: 差分検出と更新計画
    DeterministicScripts-->>DocLinkSkill: 変更集合と生成対象
    DocLinkSkill->>ContentAI: 必要な文書情報だけ生成依頼
    ContentAI-->>DocLinkSkill: 要約などの生成結果
    DocLinkSkill->>DeterministicScripts: 検証と参照走査と候補確定
    DeterministicScripts-->>DocLinkSkill: 確定版と未処理変更
    DocLinkSkill-->>ProjectAI: ToC確定結果と参照検査結果
    opt 未報告の変更がある
        DocLinkSkill->>DeterministicScripts: 未報告の変更と把握済み参照元を取得
        DeterministicScripts-->>DocLinkSkill: 変更文書・参照元・検査範囲
        DocLinkSkill-->>ProjectAI: 修正が必要かもしれない参照元を通知
    end
```

処理済み比較基準は図中の ToC 確定時には進めない。変更と参照元の報告後に比較基準を更新する条件は [DES-007](DES-007-references-impact.md) で扱う。

構築中に対象文書が再変更された場合に、どの観測版を候補に含められるかは [DES-005](DES-005-indexing.md) の一貫性条件で扱う。参照先ディレクトリの走査不能を含めて確定できるかは未決定である。

## 4. 共通不変条件

1. 文書 ID はパス、本文、管理キーと独立し、発行済みの値を変更理由だけで再発行しない。
2. 現在の参照の存在・パス一致は、記載パスが示すディレクトリの実走査なしに断定しない。
3. 新しい ToC 候補の一部を、確定済みの現在状態として公開しない。
4. 確定した ToC の内容ハッシュと、変更影響候補の報告まで処理済みの比較基準は別の状態として保つ。
5. 逆参照と変更影響候補の報告範囲は、走査して登録した参照元の範囲を超えない。
6. あるキーの更新は、指定されていないキーの ToC を更新・削除しない。

## 5. 本書で確定しないこと

参照先の走査不能時の確定可否は未決定である。保存方式（SQLite と文書単位のロック）、同一 ID の複数キー間での見え方、変更報告の比較基準の単位、検索時の参照検査結果の鮮度は個別設計で決定済みである（[DES-002](DES-002-execution-responsibilities.md)、[DES-003](DES-003-data-model.md)、[DES-005](DES-005-indexing.md)、[DES-006](DES-006-search.md)、[DES-007](DES-007-references-impact.md)）。これらの選択は対応する個別設計に理由と帰結を記録し、要件変更が必要なら要件書にも反映する。
