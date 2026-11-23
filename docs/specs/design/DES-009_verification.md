---
doc_link_id: DLID-xmg0jcmep2h2
---

# DES-009 要件対応と設計検証 DLID-7e6sqa5ehfep

<a id="sec-1"></a>

## 1. テストの規範 DLID-13qfqbvamwny

状態を持つ処理は[DES-004 の遷移表][des-004]を唯一の許可遷移一覧とする。P-01〜P-03、B-01〜B-09、E-01〜E-07 の各行について、元状態・イベント・ガード成立で指定した次状態と効果になることを試す。同じ元状態でガード不成立、表にないイベント、別状態からのイベントを与えたときは拒否し、[確定 ToC]が変わらないことを試す。Mermaid 図は表と同じ遷移を可視化するだけであり、図にない暗黙の遷移を認めない。

参照先の不在は候補確定ガードを不成立にしない（要件 [D-025][req-005-fr-009]）。指定ディレクトリ内不在・指定ディレクトリ自体の不在・ディレクトリを読めない場合がいずれも「不在」として記録され、確定することを試す。途中中断、再実行、旧[確定 ToC]保持、部分的に保存済みの ID、複数キーの隔離も状態テストに含める。`check-impact` は、次を試す。

- 何も書き換えない。管理状態と[Index 対象文書]が変わらない。
- title に記録した[内容ハッシュ]が参照先の[現在ハッシュ]と異なる参照を返す。
- title に記録した[内容ハッシュ]が無い参照（title が[DLID]だけの参照を含む）を返す。
- 記録が参照先の[現在ハッシュ]と一致する参照を返さない。
- 記録を書き換えるまで、同じ参照を毎回返す。
- 記録だけを書き換えても、参照元の[内容ハッシュ]が変わらず、参照元を参照する文書へ通知が連鎖しない。
- 互いを参照する 2 つの文書で、記録を書き換えても、通知が終わらなくならない。
- 記録だけを書き換えても、`check-toc` は[ToC]を古いと判定しない。`index-docs` を実行せずに、同じ参照が返らなくなる。
- 文書の[DLID]の参照は、文書内のどこが変わっても返す。[セクション ID]の参照は、そのセクションの範囲が変わったときだけ返す。
- 参照先が[確定 ToC]に無い参照を返さず、`check-links` が検出する。
- 失敗したときは、エラーの JSON を返し、通知しない。

`check-links` は、次を試す。

- [DLID]入りの title を持つインラインリンクを報告する。
- title の[DLID]の直前の語が title の記録語の形（要件 [D-058][req-003-sec-10-1-2]）のときだけ、記録として読む。それ以外は「記録なし」にする。
- 参照先を、リンク先のパスが示すディレクトリから、対象文書に含まれる別のディレクトリへ移動したとき、移動先を現在パスとして、パス不一致を返す。対象の外へ移動したときは不在のまま、対象文書に同じ[DLID]が複数あるときは重複を返す。管理状態の記録は使わない（[AC-035][req-005-ac-035]）。

検査と検索前検査は、次を試す（[AC-034][req-005-ac-034]）。

- 標準出力が件数までで、検出事項・変更のある文書とセクション・変更影響候補の全件が明細ファイルにある。
- 検出の件数を増やしても、標準出力の大きさが変わらない。
- 検出が 0 件でも明細ファイルを書き、同じ[ToC 識別キー]の次の実行が置き換える。
- 明細ファイルを書けないとき、件数だけを返さず、エラーとして終了する。
- 検査の前後で、対象文書と管理状態が変わらず、書くのが明細ファイルだけである。

状態遷移でない決定論的処理は別に単体テストを持つ。対象指定の展開、Markdown 解析、ID 認識・発行・重複、[DLID]の解決、パス解決、ディレクトリ走査結果の分類、比較値、AI 出力検証、[ToC 候補]整合性、構築の完了結果の組み立て（種別ごとの件数、明細ファイルの内容と置き換え、移動の記録と集計）、明細ファイルの書き込み、[DLID]と現在のパスの対応による不在の参照の引き直しを対象にする。

<a id="sec-2"></a>

## 2. 要件から設計・受け入れ検証への対応 DLID-m4ccp38zt37g

| 要件                                                       | 主設計                                                     | 主な検証観点                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ---------------------------------------------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [FR-017][req-002-fr-017] [Index 対象指定]                  | [DES-005][des-005]                                         | 完全な desired state、対象離脱、他キー非変更、[AC-021][req-002-ac-021]／022／024                                                                                                                                                                                                                                                                                                                                                          |
| [FR-001][req-002-fr-001]／002 [文書 ID]                    | [DES-005][des-005]、[DES-008][des-008]                     | 欠落統一、発行形式、不変、重複の原本候補の提示と利用者による確定、構築での ID 未付与・重複文書の除外と報告、構築・検索が[Index 対象文書]を書き換えないこと、[AC-005][req-002-ac-005]／012〜014／016／023／025／029／030                                                                                                                                                                                                                   |
| [FR-003][req-003-fr-003]／011／012 変更検出                | [DES-005][des-005]、[DES-008][des-008]                     | パスのみ・本文・参照・離脱の差分、セクション単位の限定、[AC-001][req-003-ac-001]／002／020／026                                                                                                                                                                                                                                                                                                                                           |
| [FR-004][req-003-fr-004]／005 [ToC]・要約                  | [DES-005][des-005]、[DES-004][des-004]、[DES-008][des-008] | 初回確定、更新計画、変更時のみ AI、長さ境界、失敗時旧版、[AC-010][req-003-ac-010]／011／017／018／027                                                                                                                                                                                                                                                                                                                                     |
| [FR-008][req-003-fr-008]／007／009／010 参照               | [DES-007][des-007]、[DES-008][des-008]                     | ID 付き記法、実走査、一致・不一致・不在、見出しの改名後のフラグメント不一致、修正先の証拠、[AC-003][req-005-ac-003]／004／028／035                                                                                                                                                                                                                                                                                                        |
| [FR-006][req-004-fr-006] 文書検索                          | [DES-006][des-006]                                         | 未構築、再構築要否、規模の件数、ユーザー二択、判定不能時の停止、古い版の表示、[AC-019][req-004-ac-019]                                                                                                                                                                                                                                                                                                                                    |
| [FR-018][req-002-fr-018] [DLID]の解決                      | [DES-006][des-006]                                         | 文書・セクションの解決、移動後の再構築前後、記録の無い[DLID]、管理状態を読めないときの失敗、管理状態と[Index 対象文書]を変えないこと、解決済みに[内容ハッシュ]を添えること（文書、セクション、セクションの値が記録によって異なるとき、得られないとき）、[AC-031][req-002-ac-031]                                                                                                                                                          |
| [FR-013][req-005-fr-013]／014／015 [変更影響候補の通知]    | [DES-007][des-007]                                         | 逆引き範囲、記録と現在ハッシュの比較、参照元の通知、記録を書き換えるまでの毎回の通知、[AC-006][req-005-ac-006]〜009                                                                                                                                                                                                                                                                                                                       |
| [FR-016][req-005-fr-016] 不整合検査                        | [DES-007][des-007]、[DES-010][des-010]                     | ID、参照、[ToC]不整合（古いハッシュを含む）、記録と現在ハッシュが異なる参照の列挙。検査の SKILL が管理状態を書き換えないこと。[DLID]の無いリンクへ title に書く値を添えること（文書・セクションの値、解決しないフラグメントの理由、書いた参照が一致になること）、[AC-032][req-005-ac-032]。書き直す前に、利用者へ一覧を示して確認する案内、[AC-033][req-005-ac-033]。検査の結果を件数と明細ファイルに分けること、[AC-034][req-005-ac-034] |
| [NFR-001][req-001-nfr-001]〜003 一貫性・決定性・冪等性     | [DES-003][des-003]、[DES-005][des-005]                     | 同一入力の論理同値、途中版非公開、再実行の不要差分なし                                                                                                                                                                                                                                                                                                                                                                                    |
| [NFR-004][req-001-nfr-004]〜005 書き込み境界・診断         | [DES-002][des-002]、[DES-007][des-007]                     | [DLID]以外の本文不変、書き込み後の差分検証と取消し、対象・箇所・機械的に確認した原因の提示                                                                                                                                                                                                                                                                                                                                                |
| [NFR-006][req-001-nfr-006]〜008 再実行・スケール・生成境界 | [DES-002][des-002]、[DES-005][des-005]、[DES-008][des-008] | 未変更の AI 再解析なし、未処理の再開、[情報生成 AI]の入力に `H` がないこと                                                                                                                                                                                                                                                                                                                                                                |

<a id="sec-3"></a>

## 3. 横断シナリオ DLID-7ppw4fp92v08

1. 初回：DLID 付与操作 → 対象指定 → ID 確認 → 変更集合 → 必要情報 → 参照実走査 → [ToC]確定 → 検索可能。
2. 移動：同じ ID・同じ内容でパスだけ変更し、要約を再生成せず[ToC]の現在パスを更新する。参照元の古いパスは自動修正しない。
3. 内容変更：参照先を変えると、[ToC]確定後も、参照元の記録は旧値のまま。`check-impact` が、記録を書き換えるまで毎回その参照を返す。要約は再生成しない。
4. 失敗：AI 生成・参照走査・候補確定の各失敗位置で、旧[確定 ToC]の扱いを区別する。それまでに確定した[文書情報]は戻さず、[ToC]が旧版のキーからも最新の[文書情報]が見える（要件 [D-024][req-003-fr-004]）。
5. 複数キー：同一 ID が A と B に所属し、A の更新・離脱が B の[ToC]を書き換えない。同じ ID・[内容ハッシュ]の検証済み情報を再利用できる場合、B への追加だけで AI 要約を再生成しない。B は A と同じ[文書情報]を参照するため表示は一致する（要件 [D-024][req-003-fr-004]）。
6. 範囲外参照：Index 対象外でも指定ディレクトリを実走査し、結果に範囲・時点を付ける。対象範囲外への移動先は推測しない。
7. 後からの参照：DLID 付与操作が全見出しに[セクション ID]を付けた文書の見出しへ、別の文書から、title にその[セクション ID]を書いたリンクを新しく書く。参照先の文書へ書き込むことなく、そのリンクが[正式な参照]として抽出されることを確かめる（要件 [D-033][req-005-sec-13-1]）。DLID 付与操作が、title に[DLID]の無いリンクにも書き込まないことを確かめる（要件 [D-042][req-005-fr-016]）。

[des-004]: DES-004_state-machines.md "d3b39867775c DLID-3f92k3tz4rew"
[des-005]: DES-005_indexing.md "52ed2959d4d0 DLID-dgphqw70rkpz"
[des-008]: DES-008_content-rules.md "f28039845959 DLID-ywa6htx8vq09"
[des-007]: DES-007_references-impact.md "fdeb71fae505 DLID-pr3jp4hzb8js"
[des-006]: DES-006_search.md "96dc8a0cdfe8 DLID-nnbgpzkkm5vq"
[des-010]: DES-010_skill-composition.md "c24ddb837a66 DLID-7e90gq3sdncc"
[des-003]: DES-003_data-model.md "370b9cb0bf83 DLID-yqqrwtycr379"
[des-002]: DES-002_execution-responsibilities.md "9c2bea9cc41e DLID-anz9vack2xzt"
[req-001-nfr-001]: ../requirement/REQ-001_overview.md#nfr-001-toc再構築の一貫性-dlid-j4xry3ca5rsb "1bfb73100c73 DLID-j4xry3ca5rsb"
[req-001-nfr-004]: ../requirement/REQ-001_overview.md#nfr-004-index-対象文書への書き込み境界-dlid-kp2w32mbpdb8 "4ca9ecf3d971 DLID-kp2w32mbpdb8"
[req-001-nfr-006]: ../requirement/REQ-001_overview.md#nfr-006-中断後の再実行-dlid-wwhfthxzv8pv "57d65dcd4e6a DLID-wwhfthxzv8pv"
[req-002-ac-005]: ../requirement/REQ-002_document-id.md#ac-005-id-重複-dlid-zwwxj8ctqkn6 "9613468bd782 DLID-zwwxj8ctqkn6"
[req-002-ac-021]: ../requirement/REQ-002_document-id.md#ac-021-toc-識別キーごとの-desired-state-dlid-rrhdkcqvbmgt "1bff7a3fbf43 DLID-rrhdkcqvbmgt"
[req-002-ac-031]: ../requirement/REQ-002_document-id.md#ac-031-dlidの解決-dlid-3yrk3sey2krp "bb60d45e1215 DLID-3yrk3sey2krp"
[req-002-fr-001]: ../requirement/REQ-002_document-id.md#fr-001-文書-idの発行と読み取り-dlid-z0g4zx0wr0cn "594d2964b515 DLID-z0g4zx0wr0cn"
[req-002-fr-017]: ../requirement/REQ-002_document-id.md#fr-017-toc-識別キーとindex-対象指定の受領-dlid-3wc02prwb6x7 "ab2973434c9d DLID-3wc02prwb6x7"
[req-002-fr-018]: ../requirement/REQ-002_document-id.md#fr-018-dlidの解決-dlid-8vajyevfatkv "cf5307ccef85 DLID-8vajyevfatkv"
[req-003-ac-001]: ../requirement/REQ-003_toc.md#ac-001-文書移動-dlid-7z3rvbfsdwtq "7b75758d45bc DLID-7z3rvbfsdwtq"
[req-003-ac-010]: ../requirement/REQ-003_toc.md#ac-010-ai-生成フィールドの許容余白-dlid-5btzbc2qvhqz "3fc42417518e DLID-5btzbc2qvhqz"
[req-003-fr-003]: ../requirement/REQ-003_toc.md#fr-003-文書の移動改名の認識-dlid-grzqdx81bakh "5e0072a4ce7a DLID-grzqdx81bakh"
[req-003-fr-004]: ../requirement/REQ-003_toc.md#fr-004-tocの構築と再構築-dlid-7hjmngynv8sb "950ff227e36b DLID-7hjmngynv8sb"
[req-003-fr-008]: ../requirement/REQ-003_toc.md#fr-008-参照関係の抽出-dlid-vdkqzhjf68hj "4714440a4fce DLID-vdkqzhjf68hj"
[req-004-ac-019]: ../requirement/REQ-004_search.md#ac-019-検索前のtoc再構築確認-dlid-36g5pqvaxrh9 "b0b99bc75414 DLID-36g5pqvaxrh9"
[req-004-fr-006]: ../requirement/REQ-004_search.md#fr-006-文書検索-dlid-481cwc8365a3 "002418132007 DLID-481cwc8365a3"
[req-005-ac-003]: ../requirement/REQ-005_references.md#ac-003-参照パス不一致の検出-dlid-4wyyhbdg1we0 "67d4937046c6 DLID-4wyyhbdg1we0"
[req-005-ac-006]: ../requirement/REQ-005_references.md#ac-006-変更影響候補の列挙-dlid-n874z4gfzc0v "744dbd0f14bc DLID-n874z4gfzc0v"
[req-005-ac-032]: ../requirement/REQ-005_references.md#ac-032-title-に書く値の提示-dlid-nc6z2c2w5wx3 "d2b830d42495 DLID-nc6z2c2w5wx3"
[req-005-ac-033]: ../requirement/REQ-005_references.md#ac-033-書き直しの確認-dlid-p2nyvmexdjg3 "18e6e981cdbb DLID-p2nyvmexdjg3"
[req-005-fr-013]: ../requirement/REQ-005_references.md#fr-013-変更影響候補の特定-dlid-cnw6h5pzv3wz "6af5f019bff6 DLID-cnw6h5pzv3wz"
[req-005-fr-016]: ../requirement/REQ-005_references.md#fr-016-不整合検査-dlid-jhkngqtfdnhn "00a4a4df7313 DLID-jhkngqtfdnhn"
[req-003-sec-10-1-2]: ../requirement/REQ-003_toc.md#1012-内容ハッシュ-dlid-c3prh9y4nbzw "dfb119ed393a DLID-c3prh9y4nbzw"
[req-005-fr-009]: ../requirement/REQ-005_references.md#fr-009-id-付きリンクの検査-dlid-zacf5tmy6x4x "1a232498a7af DLID-zacf5tmy6x4x"
[req-005-sec-13-1]: ../requirement/REQ-005_references.md#131-セクション参照-dlid-5p5ms6a74w73 "275305521655 DLID-5p5ms6a74w73"
[req-005-ac-034]: ../requirement/REQ-005_references.md#ac-034-検査の結果の件数と明細ファイル-dlid-gm124n5abz9h "b8819e66d8b7 DLID-gm124n5abz9h"
[req-005-ac-035]: ../requirement/REQ-005_references.md#ac-035-対象文書の中の移動先の提示-dlid-gk7ss8dm7q0w "fc3411739362 DLID-gk7ss8dm7q0w"
