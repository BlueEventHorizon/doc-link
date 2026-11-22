---
doc_link_id: DLID-zvepba87h7zk
---

# doc-link 設計書の構成 DLID-2f3q114x45q6

要件定義書は「実現する振る舞いと制約」の正本、ここにある設計書は「どの主体・情報・状態・処理で実現するか」の正本とする。要件と設計が食い違う場合、設計だけで要件を上書きしない。未決事項を解決するまで、該当する遷移や結果を確定仕様として扱わない。

| 文書                                     | 担当する内容                                                                                          |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| [DES-001 全体設計][des-001]              | システム境界、主要操作の接続、全体シーケンス、共通不変条件                                            |
| [DES-002 実行主体][des-002]              | Skill・決定論的な script・各 AI の責務と書き込み権限                                                  |
| [DES-003 データモデル][des-003]          | 識別子、情報源、論理的な関係・版・鮮度                                                                |
| [DES-004 状態モデル][des-004]            | 独立した状態機械、許可遷移、禁止遷移、失敗・再実行                                                    |
| [DES-005 ToC 構築][des-005]              | 対象確定、ID 確認、DLID 付与操作、差分、情報取得、候補検査・確定                                      |
| [DES-006 文書検索][des-006]              | 検索前検査、利用者の選択、検索結果の鮮度、[DLID]の解決                                                |
| [DES-007 参照と変更通知][des-007]        | 参照検査、逆引き、[変更影響候補の通知]                                                                |
| [DES-008 内容規則][des-008]              | Markdown 解析、ID、ハッシュ、AI 生成結果の検証契約                                                    |
| [DES-009 検証設計][des-009]              | 状態遷移と変換規則のテスト、要件との対応                                                              |
| [DES-010 SKILL と Agent の構成][des-010] | SKILL・カスタム Agent の責務、検査の SKILL ごとの検出事項の扱い、ユースケース、SKILL ごとのシーケンス |

各図は理解用の表示であり、許可遷移の規範は DES-004 の遷移表とする。各処理の詳細は当該文書だけに置き、全体設計には重複して記載しない。

## 確定を妨げる判断待ち DLID-w7ddwdx6jqa9

- 無い

要件の未決事項はすべて決定済みであり、保存方式は JSON ファイルに決定済みである（[DES-002 §4][des-002-sec-4]）。要件定義書と設計書はレビューを経て承認済みである。

[des-001]: DES-001_system-overview.md "5f91d48e8b97 DLID-3da82gspdp44"
[des-002]: DES-002_execution-responsibilities.md "5eb022745267 DLID-anz9vack2xzt"
[des-003]: DES-003_data-model.md "c166e9748f2a DLID-yqqrwtycr379"
[des-004]: DES-004_state-machines.md "bad0bb8aa05a DLID-3f92k3tz4rew"
[des-005]: DES-005_indexing.md "226248ba364c DLID-dgphqw70rkpz"
[des-006]: DES-006_search.md "ce56d4ed6907 DLID-nnbgpzkkm5vq"
[des-007]: DES-007_references-impact.md "463a2d89954a DLID-pr3jp4hzb8js"
[des-008]: DES-008_content-rules.md "a535f218431f DLID-ywa6htx8vq09"
[des-009]: DES-009_verification.md "29b125164ccc DLID-xmg0jcmep2h2"
[des-010]: DES-010_skill-composition.md "6f5e412f608f DLID-7e90gq3sdncc"
[des-002-sec-4]: DES-002_execution-responsibilities.md#sec-4 "5eb022745267 DLID-anz9vack2xzt"
