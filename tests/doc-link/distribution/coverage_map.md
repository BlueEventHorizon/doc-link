# 要件と検証の対応の記録

この文書は開発用であり、配布物には含めない。要件定義書の受け入れ条件（AC）と検証観点を、実装したテストまたは手動確認と突き合わせた記録である。

- 参照の書式は `<tests/doc-link/ からの相対パス>::<クラス>::<テスト名>` である。`test_coverage_map.py` が、参照したテストの実在を確かめる
- AI の判断を試す手動確認は `manual/` の文書に置く（自動実行しない）
- 見つからなかった対応は、推測で埋めず「対応なし」と書く。「対応なし（間接のみ）」は、直接の検証が無く、他の検証から間接にうかがえる状態である
- 対象の行は設計書の「要件から設計・受け入れ検証への対応」の表の各行である。見出しはその行の要件の欄と一致させる。表の AC をすべてこの文書に載せる

## FR-017 [Index 対象指定]

### AC-021

- 異なる Markdown 集合 A、B を順に与えると B が完全な desired state になる（対象から外れた文書の離脱）→ `scripts/test_toc_check.py::ChangeListTest::test_departed_document_by_spec_and_by_removal`、`scripts/test_toc_check.py::ChangeListTest::test_given_spec_takes_priority_over_the_saved_one`、`scripts/test_change_set.py::DocumentChangeTest::test_new_departed_path_content_and_reference_are_independent`
- 指定外の Markdown を推測で追加しない → `scripts/test_target_spec.py::ExpansionTest::test_dirs_collects_markdown_recursively`、`scripts/test_target_spec.py::ExpansionTest::test_missing_and_non_markdown_paths_are_reported_and_rest_continues`
- 離脱した文書の実体の有無を調べるために対象範囲外を探索しない → `scripts/test_toc_check.py::DirectoryDisappearedTest::test_vanished_target_directory_is_departure_not_undeterminable`
- 異なるキーの更新が、他方のキーの[ToC]を変更しない → `scripts/test_toc_candidate.py::PublishTest::test_unspecified_key_is_untouched_by_success_and_failure`、`index-docs/test_index_docs.py::MultipleKeysTest::test_update_and_departure_in_one_key_do_not_rewrite_the_other`、`scenarios/test_scenario_5_multiple_keys.py::MultipleKeysScenarioTest::test_scenario_5_update_and_departure_do_not_rewrite_the_other_key`

### AC-022

- `--key` と対象指定の形式を受け取り、`--all` と引数なしが予約キー `all` の単体モードになる → `scripts/test_target_spec.py::CombinationTest::test_no_arguments_is_all_mode`、`scripts/test_target_spec.py::CombinationTest::test_all_flag_alone_is_all_mode`、`scripts/test_target_spec.py::ArgparseIntegrationTest::test_dirs_exclude_and_json_options_are_combined`、`index-docs/test_index_docs.py::FirstBuildTest::test_single_mode_uses_reserved_key`
- `--key all`、`--key` なしの対象指定、`--all` と対象指定の併用を拒否する → `scripts/test_target_spec.py::CombinationTest::test_key_all_is_rejected`、`scripts/test_target_spec.py::CombinationTest::test_target_spec_without_key_is_rejected`、`scripts/test_target_spec.py::CombinationTest::test_all_with_target_spec_is_rejected`
- 構築と DLID 付与操作が同じ指定を拒否する → `index-docs/test_index_docs.py::PremiseTest::test_conflicting_target_arguments_are_rejected_with_exit_1`、`embed-dlid/test_embed_dlid.py::RejectedArgumentsTest::test_conflicting_target_arguments_are_rejected_with_exit_1`

### AC-024

- Forge が解決したキーと対象指定を直接渡すだけで構築できる → 対応なし（間接のみ）。構築・検査のテストは、`.doc_structure.yaml` を置かない一時のツリーへキーと対象指定を直接与えて通っている。外部設定を直接読まないことを確かめるテストは無い

## FR-001／002 [文書 ID]

### AC-005

- 重複を検出して、管理状態に記録されたパスと一致するものを原本の候補として示す → `scripts/test_embed_plan.py::DuplicateTest::test_recorded_path_makes_a_single_candidate_but_does_not_decide`、`embed-dlid/test_embed_dlid.py::PlanCommandTest::test_plan_with_duplicates_awaits_origin_and_shows_origin_args`
- 利用者が確定した原本以外へ新しい[文書 ID]を発行する → `scripts/test_embed_plan.py::DuplicateTest::test_origin_confirmed_reissues_non_origin_document_and_its_sections`、`scripts/test_dlid_writer.py::ReissueTest::test_copy_is_reissued_and_original_is_unchanged`、`embed-dlid/test_embed_dlid.py::ApplyCommandTest::test_apply_with_duplicates_and_no_origin_exits_3_and_writes_nothing`
- 構築で検出した重複の文書を[ToC]に入れずに報告し、構築を続ける → `index-docs/test_index_docs.py::ExcludedDocumentsTest::test_missing_and_duplicate_ids_are_reported_and_others_enter_the_toc`、`scripts/test_change_set.py::ExclusionTest::test_missing_and_duplicate_ids_are_excluded_and_others_continue`

### AC-012

- 欠落・null・空・空白・単一文字列でない値・認識できない値が、すべて「存在しない」に分類される → `scripts/test_markdown_reader.py::FrontmatterTest::test_unrecognized_values_are_all_missing`、`scripts/test_markdown_reader.py::FrontmatterTest::test_frontmatter_without_doc_link_id`、`scripts/test_dlid.py::RecognitionTest::test_unrecognized_doc_link_id_is_none`、`check-dlid/test_check_dlid.py::DetectionTest::test_unrecognized_doc_link_id_is_missing_document_id`
- 形式不正という別の分類を返さない → `check-dlid/test_check_dlid.py::DetectionTest::test_missing_document_and_section_ids`、`scripts/test_embed_plan.py::MissingIdsTest::test_document_and_headings_without_ids`

### AC-013

- DLID 付与操作が、[文書 ID]の無い文書へ `DLID-` 付きの[文書 ID]を frontmatter へ保存する → `scripts/test_embed_plan.py::MissingIdsTest::test_frontmatter_positions`、`scripts/test_dlid_writer.py::ExactBytesTest::test_without_frontmatter_creates_one_at_the_top`、`scripts/test_dlid.py::IssueTest::test_issued_passes_format_check`
- 構築・再構築が[文書 ID]を発行・保存せず、[文書 ID]の無い文書を[ToC]に入れずに報告する → `scripts/test_change_set.py::NoWriteTest::test_build_does_not_change_documents_or_state`、`index-docs/test_index_docs.py::ExcludedDocumentsTest::test_missing_and_duplicate_ids_are_reported_and_others_enter_the_toc`

### AC-014

- 本文・ファイル名・パス・タイトル・要約を変更しても、発行済みの[文書 ID]が変わらない → `scripts/test_embed_plan.py::MissingIdsTest::test_existing_ids_are_not_issued_again`、`scripts/test_dlid_writer.py::ExactBytesTest::test_existing_ids_are_kept`、`scenarios/test_scenario_2_3_move_and_change.py::MoveScenarioTest::test_scenario_2_move_updates_current_path_without_regenerating`

### AC-016

- [文書 ID]の値部分が、本文・ファイル名・パス・タイトル・要約から導出されず、再計算もされない → 対応なし（間接のみ）。`scripts/test_dlid.py::IssueTest::test_ten_thousand_are_unique` が、発行の値が重複しないことを確かめる。値が文書の属性から導出されないことを直接確かめるテストは無い

### AC-023

- 文書をあるキーの対象から外して別のキーの対象に含めても、`doc_link_id` が変更されない → 対応なし（間接のみ）。`scripts/test_dlid_writer.py::ExactBytesTest::test_existing_ids_are_kept` が、付与済みの[文書 ID]が書き換わらないことを確かめ、`scenarios/test_scenario_5_multiple_keys.py::MultipleKeysScenarioTest::test_scenario_5_adding_to_another_key_does_not_request_generation` が、同じ[文書 ID]のまま別のキーへ加えられることを確かめる。キーの所属の変更を理由に[文書 ID]が変わらないことを直接確かめるテストは無い

### AC-025

- [Index 対象文書]の読み取りに失敗したとき、変更検出・[文書情報]の取得・[ToC 候補]の生成へ進まない → `scripts/test_change_set.py::FirstBuildAndFailureTest::test_unreadable_documents_stop_and_are_all_reported`、`index-docs/test_index_docs.py::OldVersionKeptTest::test_unreadable_document_stops_the_build`、`index-docs/test_index_docs.py::OldVersionKeptTest::test_unreadable_directory_stops_the_build_and_keeps_the_old_toc`
- [文書 ID]の無い文書と重複する文書を[確定 Index 対象リスト]から除いて報告し、残りで変更検出へ進む → `scripts/test_change_set.py::ExclusionTest::test_missing_and_duplicate_ids_are_excluded_and_others_continue`、`scripts/test_change_set.py::ExclusionTest::test_excluded_document_is_not_departed_and_its_sections_not_deleted`

### AC-029

- 同じ文書を二つのキーの対象に含めたとき、同一の `doc_link_id` で識別される → `scenarios/test_scenario_5_multiple_keys.py::MultipleKeysScenarioTest::test_scenario_5_both_keys_show_the_same_document_info`、`index-docs/test_index_docs.py::MultipleKeysTest::test_document_with_verified_info_from_another_key_is_not_a_target`
- 一方のキーから外しても、他方への所属と[文書 ID]を変更しない → `scenarios/test_scenario_5_multiple_keys.py::MultipleKeysScenarioTest::test_scenario_5_update_and_departure_do_not_rewrite_the_other_key`

### AC-030

- [ToC]の構築・再構築が[Index 対象文書]を変更しない → `scripts/test_change_set.py::NoWriteTest::test_build_does_not_change_documents_or_state`、`scripts/test_toc_candidate.py::AssembleTest::test_assembly_does_not_write`、`scenarios/test_scenario_7_later_reference.py::LaterReferenceScenarioTest::test_scenario_7_embedding_after_index_keeps_every_document_unchanged`
- 文書検索が[Index 対象文書]を変更しない → `query-docs/test_query_docs.py::ExchangeTest::test_state_and_documents_are_unchanged`
- [Index 対象文書]への書き込みを DLID 付与操作だけが行う → `check-dlid/test_check_dlid.py::ReadOnlyTest::test_documents_and_state_are_unchanged`、`check-toc/test_check_toc.py::ReadOnlyTest::test_documents_and_state_are_unchanged`、`check-impact/test_check_impact.py::ReadOnlyTest::test_documents_and_state_are_unchanged`、`resolve-dlid/test_resolve_dlid.py::ReadOnlyTest::test_documents_and_state_are_unchanged`、`check-links/test_check_links.py::CategoriesTest::test_writes_nothing`

## FR-003／011／012 変更検出

### AC-001

- 別ディレクトリへ移動しても、同じ[文書 ID]を持つ限り同一文書として認識される → `scripts/test_change_set.py::DocumentChangeTest::test_new_departed_path_content_and_reference_are_independent`、`scenarios/test_scenario_2_3_move_and_change.py::MoveScenarioTest::test_scenario_2_move_updates_current_path_without_regenerating`、`scripts/test_toc_check.py::ChangeListTest::test_moved_document`

### AC-002

- パスだけが変更され[内容ハッシュ]が変わらないとき、要約を再生成しない → `scripts/test_update_plan.py::PlanTest::test_path_only_change_updates_path_without_generation`、`index-docs/test_index_docs.py::IdempotenceTest::test_moved_document_updates_path_only`、`scenarios/test_scenario_2_3_move_and_change.py::MoveScenarioTest::test_scenario_2_rerun_after_move_changes_nothing`

### AC-020

- [ToC]の構築・再構築が[変更影響候補の通知]の対象を変えない（記録は書き換えるまで変わらず、再構築しても同じ参照が報告される） → `scenarios/test_scenario_2_3_move_and_change.py::ContentChangeScenarioTest::test_scenario_3_same_reference_until_the_record_is_rewritten`、`scripts/test_impact_candidates.py::ComparisonTest::test_same_references_are_returned_every_time_until_rewritten`
- [現在ハッシュ]が反映された後に再実行しても、要約を再生成しない → `index-docs/test_index_docs.py::IdempotenceTest::test_rerun_does_not_rewrite_toc_or_document_info`、`index-docs/test_index_docs.py::IdempotenceTest::test_rerun_after_a_second_does_not_rewrite_toc`

### AC-026

- 新規・本文変更・参照変更・移動／改名・離脱・変更なしを識別し、同じ文書の複数の種別をすべて保持する → `scripts/test_change_set.py::DocumentChangeTest::test_unchanged`、`scripts/test_change_set.py::DocumentChangeTest::test_new_departed_path_content_and_reference_are_independent`、`scripts/test_change_set.py::DocumentChangeTest::test_move_and_content_change_on_one_document`、`scripts/test_change_set.py::DocumentChangeTest::test_reference_only_change`
- セクション単位の変更を識別する → `scripts/test_change_set.py::SectionChangeTest::test_added_and_deleted`、`scripts/test_change_set.py::SectionChangeTest::test_body_change_only`、`scripts/test_change_set.py::SectionChangeTest::test_move_between_documents_with_body_change`
- 既存[ToC]が無いとき、現在の[Index 対象文書]をすべて新規として扱う → `scripts/test_change_set.py::FirstBuildAndFailureTest::test_first_build_all_new`
- 変更集合を確定する前に、AI による要約生成や[ToC]の更新を開始しない → `scripts/test_build_state_machine.py::BuildTableTest::test_no_state_skipping`、`index-docs/test_index_docs.py::PremiseTest::test_state_machine_rejects_skipping_a_stage`

## FR-004／005 [ToC]・要約

### AC-010

- 記述上限 `L` と内部許容上限 `H` の境界を、検証器が受理・拒否する → `scripts/test_ai_output_validator.py::BoundaryTest::test_internal_limits`、`scripts/test_ai_output_validator.py::BoundaryTest::test_purpose_boundaries`、`scripts/test_ai_output_validator.py::BoundaryTest::test_array_boundaries`、`scripts/test_ai_output_validator.py::CodePointCountTest::test_emoji_counts_as_code_points`

### AC-011

- 内部許容上限・許容係数・許容余白が、[情報生成 AI]に渡すルール・プロンプト・テンプレート・再試行メッセージに含まれない → `scripts/test_ai_output_validator.py::NonDisclosureTest::test_reasons_do_not_contain_internal_limit_factor_or_margin`、`scripts/test_ai_output_validator.py::NonDisclosureTest::test_reason_for_over_limit_cites_only_l`、`index-docs/test_index_docs.py::FirstBuildTest::test_request_does_not_contain_internal_limit_factor_or_margin`、`index-docs/test_toc_updater_exchange.py::DefinitionsTest::test_script_docstring_and_messages_do_not_leak_internals_in_requests`、`index-docs/test_skill_md.py::SkillMdTest::test_does_not_contain_internal_limit_factor_or_margin`、`toc-updater/test_agent_md.py::AgentMdTest::test_does_not_contain_internal_limit_factor_or_margin`、`scripts/test_update_plan.py::PlanTest::test_plan_exposes_only_limits_not_internal_bound`

### AC-017

- 追加・移動・改名・除外・変更の後の再構築が[ToC]へ反映される → `index-docs/test_index_docs.py::FirstBuildTest::test_fixed_values_confirm_the_toc`、`scenarios/test_scenario_2_3_move_and_change.py::MoveScenarioTest::test_scenario_2_move_updates_current_path_without_regenerating`、`index-docs/test_index_docs.py::IdempotenceTest::test_only_changed_document_is_a_generation_target`
- 離脱した[文書 ID]への対象内の残存参照を、離脱だけを理由に無効とせず、指定ディレクトリの検索結果を記録する → `scenarios/test_scenario_6_out_of_scope_reference.py::OutOfScopeReferenceScenarioTest::test_scenario_6_scan_result_has_scope_and_time_for_out_of_target_documents`、`scripts/test_toc_candidate.py::AssembleTest::test_references_record_results_without_stopping`
- 参照先の不在や参照パス不一致があっても[ToC]を確定し、検査結果を保持する → `index-docs/test_index_docs.py::FirstBuildTest::test_reference_results_are_recorded_and_do_not_stop_the_build`、`scripts/test_toc_candidate.py::AssembleTest::test_absent_and_mismatch_alone_are_success`
- 再構築後の検索と通知が、変更前のパス・ハッシュ・参照関係を現在状態として返さない → `scripts/test_toc_candidate.py::PublishTest::test_published_toc_gives_no_change_against_same_files`、`resolve-dlid/test_resolve_dlid.py::MovedDocumentTest::test_moved_document_is_not_resolved_until_rebuilt`

### AC-018

- 再構築が途中で失敗したとき、途中状態を新しい現在状態として確定しない（旧[ToC]が変わらず、初回構築の失敗では[ToC]が作られない） → `index-docs/test_index_docs.py::OldVersionKeptTest::test_candidate_validation_failure_keeps_old_toc`、`index-docs/test_index_docs.py::OldVersionKeptTest::test_publish_failure_keeps_old_toc`、`index-docs/test_index_docs.py::OldVersionKeptTest::test_first_build_failure_creates_no_toc`、`scripts/test_build_state_machine.py::ConfirmedTocUnchangedByRejectionTest::test_rejections_leave_bytes_unchanged`、`scenarios/test_scenario_4_failure.py::GenerationFailureScenarioTest::test_scenario_4_rejected_generation_keeps_old_toc_and_saved_info`
- 古い[ToC]を現在状態として通知を正常終了しない → `check-impact/test_check_impact.py::StaleTocTest::test_changed_document_returns_the_check_toc_result_without_candidates`、`check-impact/test_check_impact.py::FailureTest::test_undeterminable_is_an_error_without_candidates`
- 検索は、利用者が既存の[ToC]のまま検索すると明示的に選んだ場合に限り実行でき、現在状態として扱わない。初回構築に失敗して[ToC]が無いときは検索できない → `query-docs/test_query_docs.py::ChoiceTest::test_existing_choice_uses_old_version_and_marks_stale`、`query-docs/test_query_docs.py::PrepareOutcomeTest::test_not_built_returns_initial_build_and_exits_0`

### AC-027

- 変更なしの文書を AI に再解析せず、既存の情報を再利用する → `scripts/test_update_plan.py::PlanTest::test_only_changed_and_new_documents_are_generated`、`index-docs/test_index_docs.py::IdempotenceTest::test_only_changed_document_is_a_generation_target`
- パスだけが変更された文書で現在パスだけを更新し、要約を再生成しない → `scripts/test_update_plan.py::PlanTest::test_path_only_change_updates_path_without_generation`、`index-docs/test_index_docs.py::IdempotenceTest::test_moved_document_updates_path_only`
- 新規または本文変更の文書に限って[AI 生成フィールド]を生成する → `scripts/test_update_plan.py::PlanTest::test_only_changed_and_new_documents_are_generated`、`scripts/test_update_plan.py::PlanTest::test_document_without_h1_generates_title`
- 参照情報だけが変更された文書で、参照関係を更新して[AI 生成フィールド]を再利用する → `index-docs/test_index_docs.py::IdempotenceTest::test_reference_only_change_does_not_generate`

### 長さの境界・失敗時旧版・AI 判断の手動確認

- 情報生成 Agent の判断（文書情報の生成・script への渡し方）は自動実行しない → `toc-updater_manual.md`（`manual/`）、自動側の枠は `toc-updater/test_agent_md.py::ManualTest::test_manual_is_separate_from_automatic_tests`

## FR-008／007／009／010 参照

### AC-003

- 文書移動後、[文書 ID]は正しいがリンク定義のパスが古い場合に、不一致を検出する → `scripts/test_reference_check.py::StatusTest::test_path_mismatch_in_subdirectory_of_designated_dir`、`scripts/test_reference_check.py::StatusTest::test_path_mismatch_renamed_in_same_directory`、`check-links/test_check_links.py::CategoriesTest::test_path_mismatch_has_current_path`

### AC-004

- 実走査で現在パスを確認できたとき、問題箇所と古いパスと確認済みの現在パスを返す → `check-links/test_check_links.py::CategoriesTest::test_path_mismatch_has_current_path`、`scripts/test_reference_check.py::StatusTest::test_path_mismatch_renamed_in_same_directory`
- 現在パスを確認できないとき、指定ディレクトリ内の不在を示し、保存済みデータによる推測パスを確定値として返さない → `scripts/test_reference_check.py::StatusTest::test_moved_outside_designated_directory_is_not_guessed`、`scripts/test_reference_check.py::StatusTest::test_duplicate_does_not_guess_current_path`、`scenarios/test_scenario_6_out_of_scope_reference.py::OutOfScopeReferenceScenarioTest::test_scenario_6_target_moved_outside_the_scope_is_absent_and_not_guessed`
- 通知時点で[Index 対象文書]を変更していない → `scripts/test_reference_check.py::ScopeAndReadOnlyTest::test_does_not_write_anything`、`check-links/test_check_links.py::CategoriesTest::test_writes_nothing`

### AC-028

- 指定ディレクトリを検索して、リンク先パスに[文書 ID]のファイルがあれば正しいと判定し、別パスなら不一致を検出する → `scripts/test_reference_check.py::StatusTest::test_match_document`、`scripts/test_reference_check.py::StatusTest::test_match_section_compares_owner_document_path`、`scripts/test_reference_check.py::StatusTest::test_path_mismatch_in_subdirectory_of_designated_dir`
- [DLID]とパスが一致していても、フラグメントがセクションへ解決しなければフラグメント不一致を検出する（見出しの改名後を含む） → `scripts/test_reference_check.py::FragmentTest::test_document_fragment_mismatch_has_no_current_anchor`、`scripts/test_reference_check.py::FragmentTest::test_section_fragment_after_rename_returns_current_anchor`、`check-links/test_check_links.py::CategoriesTest::test_fragment_mismatch_has_current_anchor`
- 検索を完了しても見つからないとき「指定ディレクトリ内に不在」と記録し、世界全体での不存在としない → `scripts/test_reference_check.py::StatusTest::test_absent_when_id_is_not_in_directory`、`scenarios/test_scenario_6_out_of_scope_reference.py::OutOfScopeReferenceScenarioTest::test_scenario_6_target_moved_outside_the_scope_is_absent_and_not_guessed`
- 参照先ディレクトリを検索できないとき不在とし、保存済みの情報だけで正しいと判定しない → `scripts/test_reference_check.py::StatusTest::test_directory_missing`、`scripts/test_reference_check.py::StatusTest::test_directory_is_a_file`、`scripts/test_reference_check.py::StatusTest::test_directory_unreadable`、`scenarios/test_scenario_6_out_of_scope_reference.py::OutOfScopeReferenceScenarioTest::test_scenario_6_missing_directory_is_recorded_as_absent`
- 参照先キーへの所属有無によって判定を変えず、検査結果を検索後に保存する → `scenarios/test_scenario_6_out_of_scope_reference.py::OutOfScopeReferenceScenarioTest::test_scenario_6_scan_result_has_scope_and_time_for_out_of_target_documents`、`scripts/test_toc_candidate.py::AssembleTest::test_last_checks`

### ID 付き記法・実走査・一致・不一致・不在

- ID 付き記法（リファレンスリンクの定義の title の末尾の語が[DLID]）の抽出 → `scripts/test_references.py::ExtractTest::test_extracts_fields`、`scripts/test_markdown_reader.py::ReferenceDefinitionTest::test_title_last_word_and_preceding_word`、`scripts/test_markdown_reader.py::LinkRulesTest::test_inline_link_has_title_but_is_not_a_definition`、`scenarios/test_scenario_7_later_reference.py::LaterReferenceScenarioTest::test_scenario_7_new_reference_is_extracted_without_writing_the_target`

## FR-006 文書検索

### AC-019

- 指定キーの[ToC]が未構築のとき検索できず、初回構築が必要であることを返す → `query-docs/test_query_docs.py::PrepareOutcomeTest::test_not_built_returns_initial_build_and_exits_0`
- 既存[ToC]があれば、検索要求に対象指定が無くても、保存された指定を再解釈して再構築要否を検査する → `query-docs/test_query_docs.py::ChoiceTest::test_default_key_uses_the_saved_spec`
- 再構築が不要ならそのまま検索する → `query-docs/test_query_docs.py::PrepareOutcomeTest::test_up_to_date_fixes_current_version`
- 再構築が必要なとき、規模（変更種別ごとの件数と AI 要約が必要な件数）を示し、「再構築してから検索する」「既存の[ToC]のまま検索する」を選べる → `query-docs/test_query_docs.py::PrepareOutcomeTest::test_rebuild_needed_returns_scale_and_two_options`、`query-docs/test_skill_md.py::SkillMdTest::test_asks_two_choices_with_scale_and_passes_choice`、`query-docs/test_skill_md.py::SkillMdTest::test_rebuild_passes_the_same_key_and_target_spec_to_index_docs`
- 後者を選んだとき[ToC]を更新せず、結果に[ToC]の状態と反映していない可能性を含める → `query-docs/test_query_docs.py::ChoiceTest::test_existing_choice_uses_old_version_and_marks_stale`、`scripts/test_search_prepare.py::PrepareTest::test_stale_search_is_marked_possibly_stale_and_does_not_update_state`
- 再構築要否を判定できないとき検索を停止し、原因を返す → `query-docs/test_query_docs.py::PrepareOutcomeTest::test_undeterminable_is_a_failure_without_old_version_option`、`scripts/test_toc_check.py::UndeterminableTest::test_unreadable_subdirectory_is_undeterminable_not_departure`
- 検索結果の件数・[ToC]の版・鮮度の返却、検索の受け渡し → `scripts/test_search_prepare.py::FixTest::test_fixed_search_has_id_version_and_current_freshness`、`scripts/test_search_prepare.py::ExchangeTest::test_collect_returns_ordered_documents_with_recorded_path_and_sections`、`scripts/test_search_prepare.py::InspectionTest::test_unknown_document_id_is_abnormal`

### 検索 Agent の判断の手動確認

- `query-worker` の関連文書の選択（全エントリを読む・存在しない ID を補わない）は自動実行しない → `query-worker_manual.md`（`manual/`）、自動側の枠は `query-worker/test_agent_md.py::AgentMdTest::test_reads_all_entries_without_keyword_filtering`、`query-worker/test_agent_md.py::ManualTest::test_manual_is_separate_from_automatic_tests`

## FR-018 [DLID]の解決

### AC-031

- 文書とセクションの現在のパスが返り、セクションには見出しとアンカーが添えられる → `resolve-dlid/test_resolve_dlid.py::ResolvedTest::test_document_is_resolved_with_path_and_content_hash`、`resolve-dlid/test_resolve_dlid.py::ResolvedTest::test_section_is_resolved_with_heading_anchor_and_hash`
- 解決済みに記録した[内容ハッシュ]が添えられる（文書、セクション、セクションの値が記録によって異なるとき、得られないとき） → `resolve-dlid/test_resolve_dlid.py::ContentHashTest::test_section_hash_differing_between_records`、`resolve-dlid/test_resolve_dlid.py::ContentHashTest::test_same_section_hash_in_several_records`、`resolve-dlid/test_resolve_dlid.py::ContentHashTest::test_unavailable_hash`
- 移動後の再構築の前は「記録されたパスに無い」を返し、移動前のパスを返さない。再構築の後は移動後のパスが返る → `resolve-dlid/test_resolve_dlid.py::MovedDocumentTest::test_moved_document_is_not_resolved_until_rebuilt`、`scenarios/test_scenario_2_3_move_and_change.py::MoveScenarioTest::test_scenario_2_move_updates_current_path_without_regenerating`
- 記録の無い[DLID]に「記録が無い」を返す → `resolve-dlid/test_resolve_dlid.py::NoRecordTest::test_unrecorded_dlid`、`resolve-dlid/test_resolve_dlid.py::NoRecordTest::test_no_state_directory_means_no_record`
- 管理状態を読めないとき失敗し、「記録が無い」と取り違えない → `resolve-dlid/test_resolve_dlid.py::FailureTest::test_broken_state_is_a_failure_not_no_record`、`resolve-dlid/test_resolve_dlid.py::FailureTest::test_unreadable_state_is_a_failure`
- 解決の前後で、[Index 対象文書]・[ToC]・管理状態が変わらない → `resolve-dlid/test_resolve_dlid.py::ReadOnlyTest::test_documents_and_state_are_unchanged`

## FR-013／014／015 [変更影響候補の通知]

### AC-006

- 参照先の内容が、参照元の title に記録した[内容ハッシュ]と異なるとき、正式な記法で参照している文書を列挙する → `scripts/test_impact_candidates.py::ComparisonTest::test_different_record_is_returned_and_matching_record_is_not`、`scripts/test_impact_candidates.py::ComparisonTest::test_references_without_a_record_are_returned_with_current_hashes`、`check-impact/test_check_impact.py::ImpactResultTest::test_returns_changed_documents_with_referrers_and_scope`

### AC-007

- 参照対象外のセクションだけが変更されたとき、その参照元を影響対象に含めない → `scripts/test_impact_candidates.py::ScopeOfChangeTest::test_document_reference_follows_any_change_section_reference_only_its_range`、`scripts/test_impact_candidates.py::ScopeOfChangeTest::test_section_reference_is_returned_when_its_range_changes`、`scripts/test_content_hash.py::SectionHashTest::test_outside_change_keeps_hash`

### AC-008

- キーの Index 対象から外れた文書を参照している対象内のすべての文書を検出し、参照先のディレクトリの検索で検査状態を決める → `scenarios/test_scenario_6_out_of_scope_reference.py::OutOfScopeReferenceScenarioTest::test_scenario_6_scan_result_has_scope_and_time_for_out_of_target_documents`、`scripts/test_toc_candidate.py::AssembleTest::test_reverse_references_are_derived_from_references`
- 対象範囲外の文書を、そのキーの[Index 対象文書]として追跡しない → `scripts/test_toc_candidate.py::AssembleTest::test_departed_and_excluded_documents_are_not_in_candidate`

### AC-009

- 参照元と参照記述を機械的に列挙し、判断・修正案の作成・[Index 対象文書]の修正をしない → `check-impact/test_check_impact.py::ImpactResultTest::test_returns_changed_documents_with_referrers_and_scope`、`check-impact/test_check_impact.py::ReadOnlyTest::test_documents_and_state_are_unchanged`、`check-impact/test_skill_md.py::SkillMdTest::test_hands_the_follow_up_to_the_project_manager_ai`
- 記録が参照先の[現在ハッシュ]へ書き換えられるまで同じ参照を毎回報告し、書き換えた後は報告しない → `scripts/test_impact_candidates.py::ComparisonTest::test_same_references_are_returned_every_time_until_rewritten`、`check-impact/test_check_impact.py::ImpactResultTest::test_same_references_are_returned_every_time`、`check-impact/test_check_impact.py::ImpactResultTest::test_empty_result_after_the_records_are_rewritten`、`scenarios/test_scenario_2_3_move_and_change.py::ContentChangeScenarioTest::test_scenario_3_same_reference_until_the_record_is_rewritten`
- 記録だけを書き換えても、参照元の[内容ハッシュ]が変わらず、通知が連鎖せず、互いを参照する 2 つの文書で通知が終わらなくならない → `scenarios/test_scenario_2_3_move_and_change.py::ContentChangeScenarioTest::test_rewriting_a_record_does_not_change_the_referrer_hash`、`scripts/test_content_hash.py::DocumentHashTest::test_two_documents_referencing_each_other_do_not_chain`、`check-impact/test_check_impact.py::ImpactResultTest::test_mutual_references_settle_after_one_rewrite`
- 記録だけを書き換えても `check-toc` が[ToC]を古いと判定しない → `check-impact/test_check_impact.py::StaleTocTest::test_record_only_rewrite_is_not_stale`、`scripts/test_toc_check.py::ChangeListTest::test_rewriting_only_the_recorded_word_is_not_stale`

## FR-016 不整合検査

- [DLID]の欠落・重複の検査 → `check-dlid/test_check_dlid.py::DetectionTest::test_missing_document_and_section_ids`、`check-dlid/test_check_dlid.py::DetectionTest::test_document_and_section_duplicates_carry_all_paths`
- 参照の検査（壊れた参照・パス不一致・フラグメント不一致・[DLID]の無いリンク） → `check-links/test_check_links.py::CategoriesTest::test_path_mismatch_has_current_path`、`check-links/test_check_links.py::CategoriesTest::test_missing_section_is_distinguished_from_absent`、`check-links/test_check_links.py::CategoriesTest::test_links_without_dlid_in_definition_and_inline_forms`
- [ToC]の不整合（古いハッシュを含む）の検査 → `check-toc/test_check_toc.py::StatusTest::test_rebuild_needed_exits_0_with_list_scale_and_guidance`、`scripts/test_toc_check.py::ChangeListTest::test_content_change_lists_the_section_change`
- 記録と現在ハッシュが異なる参照の列挙 → `check-impact/test_check_impact.py::ImpactResultTest::test_returns_changed_documents_with_referrers_and_scope`
- 検査の SKILL が管理状態を書き換えない → `check-dlid/test_check_dlid.py::ReadOnlyTest::test_documents_and_state_are_unchanged`、`check-toc/test_check_toc.py::ReadOnlyTest::test_documents_and_state_are_unchanged`、`check-impact/test_check_impact.py::ReadOnlyTest::test_documents_and_state_are_unchanged`、`check-links/test_check_links.py::CategoriesTest::test_writes_nothing`
- 参照先が[確定 ToC]に無い参照を返さず、`check-links` が検出する（設計書の `check-impact` の検証観点） → `scripts/test_impact_candidates.py::StructureTest::test_reference_whose_target_is_not_in_the_toc_is_not_returned`、`check-links/test_check_links.py::CategoriesTest::test_unresolved_outside_root`
- 失敗したとき、エラーの JSON を返し、通知しない → `check-impact/test_check_impact.py::FailureTest::test_undeterminable_is_an_error_without_candidates`、`check-impact/test_check_impact.py::FailureTest::test_broken_confirmed_toc_is_an_error`
- 文書の[DLID]の参照は文書内のどこが変わっても返し、[セクション ID]の参照はそのセクションの範囲が変わったときだけ返す → `scripts/test_impact_candidates.py::ScopeOfChangeTest::test_document_reference_follows_any_change_section_reference_only_its_range`

## NFR-001〜003 一貫性・決定性・冪等性

- 同一入力の論理同値 → `scripts/test_state_store.py::DeterminismTest::test_same_bytes_regardless_of_order`、`scripts/test_toc_candidate.py::AssembleTest::test_deterministic`、`scripts/test_state_store.py::DeterminismTest::test_toc_set_lists_are_order_independent`
- 途中版非公開 → `scripts/test_toc_candidate.py::PublishTest::test_failed_publish_keeps_old_toc_and_leaves_no_temp_file`、`scripts/test_state_store.py::AtomicWriteTest::test_replace_failure_keeps_old_file_and_leaves_no_temp`、`index-docs/test_toc_updater_exchange.py::RequestTest::test_request_is_not_visible_until_published`
- 再実行の不要差分なし → `index-docs/test_index_docs.py::IdempotenceTest::test_rerun_does_not_rewrite_toc_or_document_info`、`scripts/test_state_store.py::DeterminismTest::test_second_save_does_not_rewrite`、`scripts/test_dlid_writer.py::IdempotenceAndFilesTest::test_second_run_makes_no_difference`

## NFR-004〜005 書き込み境界・診断

- [DLID]以外の本文が不変 → `scripts/test_dlid_writer.py::ExactBytesTest::test_links_html_and_text_are_untouched`、`scripts/test_dlid_writer.py::VerifyWrittenTest::test_accepts_only_the_planned_difference`、`scripts/test_dlid_writer.py::VerifyWrittenTest::test_rejects_text_change_in_heading`、`scenarios/test_scenario_7_later_reference.py::LaterReferenceScenarioTest::test_scenario_7_embedding_again_does_not_write_to_a_link_without_a_dlid`
- 書き込み後の差分検証と取消し → `scripts/test_dlid_writer.py::RevertTest::test_non_dlid_difference_reverts_the_document`、`scripts/test_dlid_writer.py::RevertTest::test_link_title_change_reverts`、`scripts/test_dlid_writer.py::RevertTest::test_failed_revert_is_reported_as_not_reverted`
- 対象・箇所・機械的に確認した原因の提示 → `embed-dlid/test_embed_dlid.py::ApplyCommandTest::test_partial_failure_exits_4_and_keeps_issued_dlids`、`scripts/test_dlid_writer.py::PartialFailureTest::test_unreadable_target_is_reported`、`scripts/test_dlid_writer.py::RefusalTest::test_unclosed_frontmatter_is_not_written`

## NFR-006〜008 再実行・スケール・生成境界

- 未変更の AI 再解析なし → `scripts/test_update_plan.py::PlanTest::test_only_changed_and_new_documents_are_generated`、`index-docs/test_index_docs.py::IdempotenceTest::test_only_changed_document_is_a_generation_target`
- 未処理の再開 → `scenarios/test_scenario_4_failure.py::GenerationFailureScenarioTest::test_scenario_4_rerun_after_failure_resumes_without_regenerating_stored_info`、`index-docs/test_index_docs.py::WaveTest::test_more_than_ten_batches_are_issued_in_waves`
- [情報生成 AI]の入力に `H` が無い → `index-docs/test_index_docs.py::FirstBuildTest::test_request_does_not_contain_internal_limit_factor_or_margin`、`scripts/test_ai_output_validator.py::NonDisclosureTest::test_reasons_do_not_contain_internal_limit_factor_or_margin`、`scripts/test_update_plan.py::PlanTest::test_plan_exposes_only_limits_not_internal_bound`、`toc-updater/test_agent_md.py::AgentMdTest::test_does_not_contain_internal_limit_factor_or_margin`

## 状態テストの規範（設計書の「テストの規範」）

- 構築・公開の遷移表（P-01〜P-03、B-01〜B-09）の各行・ガード不成立・表にないイベントの拒否と、拒否で[確定 ToC]が変わらないこと → `scripts/test_build_state_machine.py::PublicationTableTest::test_table_has_exactly_p01_to_p03`、`scripts/test_build_state_machine.py::BuildTableTest::test_b01_to_b07_move_to_the_next_state`、`scripts/test_build_state_machine.py::BuildTableTest::test_b01_to_b07_guard_unmet_is_rejected`、`scripts/test_build_state_machine.py::BuildTableTest::test_events_from_another_state_are_rejected`、`scripts/test_build_state_machine.py::BuildTableTest::test_b09_only_explicit_rerun_returns_from_failed`、`scripts/test_build_state_machine.py::ConfirmedTocUnchangedByRejectionTest::test_rejections_leave_bytes_unchanged`
- DLID 付与操作の遷移表（E-01〜E-07）の各行・拒否 → `scripts/test_embed_state_machine.py::AllowedTransitionsTest::test_e01`、`scripts/test_embed_state_machine.py::AllowedTransitionsTest::test_e07`、`scripts/test_embed_state_machine.py::RejectedTransitionsTest::test_guard_unmet`、`scripts/test_embed_state_machine.py::RejectedTransitionsTest::test_events_not_in_the_table_for_the_state_are_rejected`
- 参照先の不在が候補確定ガードを不成立にしない（指定ディレクトリ内の不在・指定ディレクトリ自体の不在・ディレクトリを読めない場合） → `scripts/test_toc_candidate.py::ValidateTest::test_absent_and_path_mismatch_do_not_fail_validation`、`scenarios/test_scenario_6_out_of_scope_reference.py::OutOfScopeReferenceScenarioTest::test_scenario_6_missing_directory_is_recorded_as_absent`、`scenarios/test_scenario_6_out_of_scope_reference.py::OutOfScopeReferenceScenarioTest::test_scenario_6_unreadable_directory_does_not_stop_the_build`
- `check-links` の検証観点（[DLID]入りの title のインラインリンクの報告、直前の語が 64 桁の小文字 16 進のときだけ記録として読む） → `check-links/test_check_links.py::CategoriesTest::test_inline_link_with_dlid_title`、`check-links/test_check_links.py::RecordWordTest::test_only_64_lowercase_hex_is_read_as_a_record`
- 決定論的処理の単体テスト（対象指定の展開、Markdown 解析、ID の認識・発行・重複、[DLID]の解決、パス解決、ディレクトリ走査結果の分類、比較値、AI 出力検証、[ToC 候補]の整合性） → `scripts/test_target_spec.py::ExpansionTest::test_dirs_collects_markdown_recursively`、`scripts/test_markdown_reader.py::HeadingTest::test_section_ranges`、`scripts/test_dlid.py::DuplicateTest::test_same_document_id_in_two_files`、`scripts/test_reference_check.py::StatusTest::test_directory_unreadable`、`scripts/test_content_hash.py::DocumentHashTest::test_known_vector`、`scripts/test_ai_output_validator.py::BoundaryTest::test_valid_result_is_accepted`、`scripts/test_toc_candidate.py::ValidateTest::test_assembled_candidate_passes`

## 横断シナリオ（設計書の「横断シナリオ」）

- 1 初回 → `scenarios/test_scenario_1_first_time.py::FirstTimeScenarioTest::test_scenario_1_from_embedding_to_searchable`
- 2 移動 → `scenarios/test_scenario_2_3_move_and_change.py::MoveScenarioTest::test_scenario_2_move_updates_current_path_without_regenerating`
- 3 内容変更 → `scenarios/test_scenario_2_3_move_and_change.py::ContentChangeScenarioTest::test_scenario_3_same_reference_until_the_record_is_rewritten`
- 4 失敗 → `scenarios/test_scenario_4_failure.py::GenerationFailureScenarioTest::test_scenario_4_rejected_generation_keeps_old_toc_and_saved_info`、`scenarios/test_scenario_4_failure.py::ReferenceScanFailureScenarioTest::test_scenario_4_scan_failure_keeps_old_toc`、`scenarios/test_scenario_4_failure.py::CandidateFailureScenarioTest::test_scenario_4_publish_failure_keeps_old_toc`
- 5 複数キー → `scenarios/test_scenario_5_multiple_keys.py::MultipleKeysScenarioTest::test_scenario_5_both_keys_show_the_same_document_info`
- 6 範囲外参照 → `scenarios/test_scenario_6_out_of_scope_reference.py::OutOfScopeReferenceScenarioTest::test_scenario_6_scan_result_has_scope_and_time_for_out_of_target_documents`
- 7 後からの参照 → `scenarios/test_scenario_7_later_reference.py::LaterReferenceScenarioTest::test_scenario_7_new_reference_is_extracted_without_writing_the_target`

## 配布物の適合（このディレクトリの検査）

- 配布物が開発文書を参照しない → `distribution/test_distribution_references.py::DistributionReferenceTest::test_distributed_documents_do_not_refer_to_development_documents`
- SKILL.md・Agent の作成規約への適合 → `distribution/test_skill_agent_conformance.py::SkillMdConformanceTest::test_code_blocks_only_call_entry_scripts_and_hold_no_logic`、`distribution/test_skill_agent_conformance.py::AgentMdConformanceTest::test_role_constraints_and_prohibitions_are_written_negatively`
- 全 `.py` にテストがあり、Node.js を使わず、終了コードを宣言している → `distribution/test_script_conformance.py::EveryPythonFileHasTestTest::test_every_python_file_has_its_test`、`distribution/test_script_conformance.py::NoNodeJsTest::test_no_node_files`、`distribution/test_script_conformance.py::ExitCodeDeclarationTest::test_codes_of_three_or_more_are_declared_with_zero_included`
- PEP 723・ロック・uv での起動・一時ファイルの置き場 → `distribution/test_script_environment.py::Pep723AndLockTest::test_every_entry_script_has_its_lock_file`、`distribution/test_script_environment.py::UvRunHelpTest::test_every_entry_script_runs_with_uv_run_locked`、`distribution/test_script_environment.py::TemporaryFileLocationTest::test_tempfile_calls_name_their_directory`
- バージョン関連ファイルを編集していない → `distribution/test_version_files_untouched.py::VersionFilesUntouchedTest::test_versions_are_unchanged_from_the_initial_values`
