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
- 異なるキーの更新が、他方のキーの所属と版を変更しない → `scripts/test_toc_candidate.py::PublishTest::test_unspecified_key_is_untouched_by_success_and_failure`、`index-docs/test_index_docs.py::MultipleKeysTest::test_update_and_departure_in_one_key_do_not_rewrite_the_other`、`scenarios/test_scenario_5_multiple_keys.py::MultipleKeysScenarioTest::test_scenario_5_update_and_departure_do_not_rewrite_the_other_key`

### AC-022

- `--key` と対象指定の形式を受け取り、`--all` と引数なしが予約キー `all` の単体モードになる → `scripts/test_target_spec.py::CombinationTest::test_no_arguments_is_all_mode`、`scripts/test_target_spec.py::CombinationTest::test_all_flag_alone_is_all_mode`、`scripts/test_target_spec.py::ArgparseIntegrationTest::test_dirs_exclude_and_json_options_are_combined`、`index-docs/test_index_docs.py::FirstBuildTest::test_single_mode_uses_reserved_key`
- `--key all`、`--key` なしの対象指定、`--all` と対象指定の併用を拒否する → `scripts/test_target_spec.py::CombinationTest::test_key_all_is_rejected`、`scripts/test_target_spec.py::CombinationTest::test_target_spec_without_key_is_rejected`、`scripts/test_target_spec.py::CombinationTest::test_all_with_target_spec_is_rejected`
- 構築と DLID 付与操作が同じ指定を拒否する → `index-docs/test_index_docs.py::PremiseTest::test_conflicting_target_arguments_are_rejected_with_exit_1`、`embed-dlid/test_embed_dlid.py::RejectedArgumentsTest::test_conflicting_target_arguments_are_rejected_with_exit_1`
- `--target-file` で対象指定ファイルの[ToC 識別キー]と[Index 対象指定]を受け取り、ほかの対象指定の引数との併用、読めないファイル、受理できない内容を拒否する（D-063）→ `scripts/test_target_spec.py::TargetFileTest::test_file_gives_the_same_spec_as_the_arguments`、`scripts/test_target_spec.py::TargetFileTest::test_all_mode_file`、`scripts/test_target_spec.py::TargetFileTest::test_other_target_arguments_are_rejected_with_the_file`、`scripts/test_target_spec.py::TargetFileTest::test_unreadable_or_malformed_file_is_rejected`、`scripts/test_target_spec.py::TargetFileTest::test_file_content_is_validated_by_the_same_rules_as_the_arguments`、`index-docs/test_index_docs.py::FirstBuildTest::test_target_file_with_other_target_arguments_is_rejected`

### AC-024

- Forge が解決したキーと対象指定を直接渡すだけで、外部設定ファイルが無くても構築・検査できる → `scenarios/test_external_config_absent.py::ExternalConfigAbsentTest::test_builds_and_checks_without_doc_structure_file`
- `.doc_structure.yaml` を直接読み取らない → `distribution/test_no_external_config_reference.py::NoExternalConfigReferenceTest::test_distributed_files_do_not_refer_to_doc_structure`

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

- [文書 ID]の値部分が、本文・ファイル名・パス・タイトル・要約から導出されず、再計算もされない → `scripts/test_dlid.py::IssueTest::test_value_is_not_derived_from_document_attributes`、`scripts/test_dlid.py::IssueTest::test_ten_thousand_are_unique`

### AC-023

- 文書をあるキーの対象から外して別のキーの対象に含めても、`doc_link_id` が変更されない → `scenarios/test_scenario_5_multiple_keys.py::MultipleKeysScenarioTest::test_scenario_5_moving_a_document_between_keys_keeps_its_document_id`、`scenarios/test_scenario_5_multiple_keys.py::MultipleKeysScenarioTest::test_scenario_5_adding_to_another_key_does_not_request_generation`

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
- 構築・再構築の完了結果は、判断に要る項目と種別ごとの件数だけを返し、変更集合の全件は明細ファイルへ書いてそのパスを返す（D-059）→ `index-docs/test_index_docs.py::DetailFileTest::test_done_returns_only_decision_items_counts_and_the_detail_path`、`index-docs/test_index_docs.py::DetailFileTest::test_first_build_counts_every_document_as_new_and_every_section_as_added`、`index-docs/test_index_docs.py::DetailFileTest::test_detail_path_is_absolute_and_the_file_holds_every_item`、`index-docs/test_index_docs.py::DetailFileTest::test_document_with_several_kinds_is_counted_in_each_kind`、`scripts/test_change_set.py::SummaryTest::test_a_document_with_several_kinds_is_counted_in_each_kind`、`scripts/test_change_set.py::SummaryTest::test_a_section_with_several_kinds_is_counted_in_each_kind`
- 移動は、[文書情報]のパスを新しくする前に script が記録し、完了結果の変更集合は、最後の比較に記録した移動を合わせて作る。生成が挟まる構築、本文変更との同時、構築のやり直し、移動して元に戻した場合でも、移動を正しく報告する → `index-docs/test_index_docs.py::PathMoveRecordTest::test_a_move_survives_a_build_that_generates_other_documents`、`index-docs/test_index_docs.py::PathMoveRecordTest::test_a_document_that_moved_and_changed_has_both_kinds`、`index-docs/test_index_docs.py::PathMoveRecordTest::test_a_move_is_kept_when_the_build_is_restarted_without_a_build_id`、`index-docs/test_index_docs.py::PathMoveRecordTest::test_a_move_that_was_undone_is_not_a_move`、`scripts/test_change_set.py::WithFirstOldPathsTest::test_a_recorded_move_is_added_before_the_other_kinds`、`scripts/test_change_set.py::WithFirstOldPathsTest::test_a_move_that_was_undone_is_removed`
- 移動の記録は、移動が無ければ書かず、構築が失敗したときは残し、公開の後に削除する。読めない記録は、公開せずに構築の失敗にする。複数のキーでは、パスを新しくした構築だけが記録する → `index-docs/test_index_docs.py::PathMoveRecordTest::test_no_record_is_written_without_a_move`、`index-docs/test_index_docs.py::PathMoveRecordTest::test_the_record_is_kept_when_the_build_fails_and_used_by_the_next_one`、`index-docs/test_index_docs.py::PathMoveRecordTest::test_unreadable_record_stops_the_build_before_publishing`、`index-docs/test_index_docs.py::PathMoveRecordTest::test_only_the_key_that_updates_the_path_records_the_move`
- 明細ファイルは[ToC 識別キー]ごとに 1 つで、次の構築が置き換え、構築が終わっても残る。書けないときは[確定 ToC]を公開しない（D-059）→ `index-docs/test_index_docs.py::DetailFileTest::test_detail_files_are_kept_per_toc_key`、`index-docs/test_index_docs.py::DetailFileTest::test_detail_file_is_kept_after_the_build_ends`、`index-docs/test_index_docs.py::DetailFileTest::test_rerun_replaces_the_detail_file_with_the_unchanged_result`、`index-docs/test_index_docs.py::DetailFileTest::test_failure_to_write_the_detail_file_does_not_publish_the_toc`

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

### AC-035

- 参照先を、対象文書に含まれる別のディレクトリへ移動したとき、移動先を現在パスとして、パス不一致を返す（D-062）→ `check-links/test_check_links.py::MovedTargetTest::test_target_moved_to_another_directory_in_the_targets_is_found`、`check-links/test_check_links.py::MovedTargetTest::test_order_of_the_targets_does_not_matter`、`check-links/test_check_links.py::MovedTargetTest::test_section_moved_to_another_document_is_not_a_missing_section`、`scripts/test_reference_check.py::RelocateTest::test_document_found_in_the_index_becomes_a_path_mismatch`、`scripts/test_reference_check.py::RelocateTest::test_section_found_in_the_index_reports_the_owner_document`、`scripts/test_reference_check.py::RelocateTest::test_missing_directory_is_relocated_too`、`index-docs/test_index_docs.py::FirstBuildTest::test_reference_results_are_recorded_and_do_not_stop_the_build`
- 対象の外へ移動した参照先は、移動先を示さず、不在を返す → `check-links/test_check_links.py::MovedTargetTest::test_target_moved_outside_the_targets_stays_absent`、`check-links/test_check_links.py::MovedTargetTest::test_dlid_in_no_target_document_stays_a_missing_section`、`scripts/test_reference_check.py::RelocateTest::test_document_outside_the_index_stays_absent`、`scenarios/test_scenario_6_out_of_scope_reference.py::OutOfScopeReferenceScenarioTest::test_scenario_6_target_moved_outside_the_scope_is_absent_and_not_guessed`
- 同じ[DLID]を持つ文書が対象文書に複数あるときは、重複を返し、現在パスを決めない → `check-links/test_check_links.py::MovedTargetTest::test_target_found_in_several_documents_is_a_duplicate`、`scripts/test_reference_check.py::RelocateTest::test_several_hits_become_a_duplicate`、`scripts/test_reference_check.py::RelocateTest::test_same_section_id_twice_in_one_document_is_a_duplicate`
- 保存済みの[ToC]と管理状態の記録を、移動先の根拠にしない。不在でない結果は変えない → `check-links/test_check_links.py::MovedTargetTest::test_managed_state_is_not_used`、`scripts/test_reference_check.py::RelocateTest::test_building_the_index_writes_nothing`、`scripts/test_reference_check.py::RelocateTest::test_unreadable_document_is_not_in_the_index`、`scripts/test_reference_check.py::RelocateTest::test_results_other_than_absent_are_returned_as_they_are`、`scripts/test_reference_check.py::RelocateTest::test_hit_at_the_link_path_itself_stays_absent`

### ID 付き記法・実走査・一致・不一致・不在

- ID 付き記法（リファレンスリンクの定義の title の末尾の語が[DLID]）の抽出 → `scripts/test_references.py::ExtractTest::test_extracts_fields`、`scripts/test_markdown_reader.py::ReferenceDefinitionTest::test_title_last_word_and_preceding_word`、`scripts/test_markdown_reader.py::LinkRulesTest::test_inline_link_has_title_but_is_not_a_definition`、`scenarios/test_scenario_7_later_reference.py::LaterReferenceScenarioTest::test_scenario_7_new_reference_is_extracted_without_writing_the_target`

## FR-006 文書検索

### AC-019

- 指定キーの[ToC]が未構築のとき検索できず、初回構築が必要であることを返す → `query-docs/test_query_docs.py::PrepareOutcomeTest::test_not_built_returns_initial_build_and_exits_0`
- 既存[ToC]があれば、検索要求に対象指定が無くても、保存された指定を再解釈して再構築要否を検査する → `query-docs/test_query_docs.py::ChoiceTest::test_default_key_uses_the_saved_spec`
- 再構築が不要ならそのまま検索する → `query-docs/test_query_docs.py::PrepareOutcomeTest::test_up_to_date_fixes_current_version`
- 再構築が必要なとき、規模（変更種別ごとの件数と AI 要約が必要な件数）を示し、「再構築してから検索する」「既存の[ToC]のまま検索する」を選べる → `query-docs/test_query_docs.py::PrepareOutcomeTest::test_rebuild_needed_returns_scale_and_two_options`、`query-docs/test_skill_md.py::SkillMdTest::test_asks_two_choices_with_scale_and_passes_choice`、`query-docs/test_skill_md.py::SkillMdTest::test_rebuild_passes_only_the_target_file_to_index_docs`
- 再構築の確認が、検査に使った[ToC 識別キー]と[Index 対象指定]を持つ対象指定ファイルのパスを返し、そのファイルを渡した構築が検査と同じ対象を再構築する。別の対象で再構築されたときは検出する（D-063）→ `scripts/test_search_prepare.py::ConfirmRebuildDetailTest::test_confirm_rebuild_writes_the_checked_target_to_a_file`、`scripts/test_search_prepare.py::ConfirmRebuildDetailTest::test_target_file_holds_the_given_spec_when_one_is_given`、`scripts/test_search_prepare.py::ConfirmRebuildDetailTest::test_target_file_survives_the_cleanup_of_a_search`、`scripts/test_search_prepare.py::ConfirmRebuildDetailTest::test_rebuild_with_another_target_is_detected_by_the_file`、`index-docs/test_index_docs.py::FirstBuildTest::test_target_file_builds_the_same_target_as_the_arguments`、`query-docs/test_query_docs.py::ChoiceTest::test_target_file_from_the_confirmation_is_taken_after_the_rebuild`、`query-docs/test_query_docs.py::ChoiceTest::test_rebuild_of_another_target_is_an_error_with_the_target_file`、`query-docs/test_query_docs.py::ChoiceTest::test_target_file_with_a_key_is_rejected`
- 後者を選んだとき[ToC]を更新せず、結果に[ToC]の状態と反映していない可能性を含める → `query-docs/test_query_docs.py::ChoiceTest::test_existing_choice_uses_old_version_and_marks_stale`、`scripts/test_search_prepare.py::PrepareTest::test_stale_search_is_marked_possibly_stale_and_does_not_update_state`
- 再構築要否を判定できないとき検索を停止し、原因を返す → `query-docs/test_query_docs.py::PrepareOutcomeTest::test_undeterminable_is_a_failure_without_old_version_option`、`scripts/test_toc_check.py::UndeterminableTest::test_unreadable_subdirectory_is_undeterminable_not_departure`
- 検索結果の件数・[ToC]の版・鮮度の返却、検索の受け渡し → `scripts/test_search_prepare.py::FixTest::test_fixed_search_has_id_version_workers_and_current_freshness`、`scripts/test_search_prepare.py::PlanWorkersTest::test_order_is_kept_and_every_document_is_assigned_exactly_once`、`scripts/test_search_prepare.py::CollectTest::test_returns_relevant_documents_with_recorded_path_reason_and_sections`、`scripts/test_search_prepare.py::CollectTest::test_a_worker_with_unanswered_documents_fails_the_search`
- 検索 AI が文書を 1 件ずつ受け取り、ID・番号を見ず、書かず、見出しだけで答え、script が見出しを ID に引き当てる（正規化した完全一致、または一意な前方一致。引き当てられなければ保存せず、候補を返す）。どの文書への答えかは script が持つ位置で決める。同名の見出しには目印を足して一意にする。答えを渡せなかった検索は、関連する文書が無い正常な 0 件にならず、失敗する（Issue #17・#19・#21）→ `scripts/test_search_prepare.py::NextItemTest::test_returns_the_path_of_the_item_with_only_the_specified_content`、`scripts/test_search_prepare.py::SubmitAnswerTest::test_an_answer_is_tied_to_the_document_by_position`、`scripts/test_search_prepare.py::SubmitAnswerTest::test_a_unique_prefix_resolves_and_an_exact_match_resolves`、`scripts/test_search_prepare.py::SubmitAnswerTest::test_a_missing_heading_is_rejected_with_candidates_and_nothing_is_stored`、`scripts/test_search_prepare.py::FixTest::test_same_headings_get_a_marker_and_names_are_unique`、`scripts/test_search_prepare.py::CollectTest::test_a_worker_with_unanswered_documents_fails_the_search`、`query-docs/test_worker_io.py::WorkerIoTest::test_answering_every_document_ends_with_done_and_no_more_answers`、`query-worker/test_agent_md.py::AgentMdTest::test_never_names_or_numbers_the_documents_and_answers_headings_only`

### 検索 Agent の判断の手動確認

- `query-worker` の関連文書の選択（担当の文書を飛ばさず 1 件ずつ答える・存在しない見出しを補わない・取りこぼしを出さないことを優先し迷う文書は関連するとする）は自動実行しない → `query-worker_manual.md`（`manual/`）、自動側の枠は `query-worker/test_agent_md.py::AgentMdTest::test_answers_every_document_without_skipping_or_keyword_filtering`、`query-worker/test_agent_md.py::AgentMdTest::test_selects_with_priority_on_not_missing_documents`、`query-worker/test_agent_md.py::ManualTest::test_manual_is_separate_from_automatic_tests`

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

- 参照元と参照記述を機械的に列挙し、判断・修正案の作成・[Index 対象文書]の修正をしない → `check-impact/test_check_impact.py::ImpactResultTest::test_returns_changed_documents_with_referrers_and_scope`、`check-impact/test_check_impact.py::ReadOnlyTest::test_documents_and_state_are_unchanged`
- 記録が参照先の[現在ハッシュ]へ書き換えられるまで同じ参照を毎回報告し、書き換えた後は報告しない → `scripts/test_impact_candidates.py::ComparisonTest::test_same_references_are_returned_every_time_until_rewritten`、`check-impact/test_check_impact.py::ImpactResultTest::test_same_references_are_returned_every_time`、`check-impact/test_check_impact.py::ImpactResultTest::test_empty_result_after_the_records_are_rewritten`、`scenarios/test_scenario_2_3_move_and_change.py::ContentChangeScenarioTest::test_scenario_3_same_reference_until_the_record_is_rewritten`
- 記録だけを書き換えても、参照元の[内容ハッシュ]が変わらず、通知が連鎖せず、互いを参照する 2 つの文書で通知が終わらなくならない → `scenarios/test_scenario_2_3_move_and_change.py::ContentChangeScenarioTest::test_rewriting_a_record_does_not_change_the_referrer_hash`、`scripts/test_content_hash.py::DocumentHashTest::test_two_documents_referencing_each_other_do_not_chain`、`check-impact/test_check_impact.py::ImpactResultTest::test_mutual_references_settle_after_one_rewrite`
- リファレンスリンクの定義の行を足しても、消しても、リンク先を直しても、文書と、その行を範囲に含むセクション（文書の最後のセクション）の[内容ハッシュ]が変わらない → `scripts/test_content_hash.py::DocumentHashTest::test_adding_or_removing_a_definition_does_not_change_hash`、`scripts/test_content_hash.py::DocumentHashTest::test_link_destination_change_does_not_change_hash`、`scripts/test_content_hash.py::SectionHashTest::test_definitions_at_the_end_do_not_alter_the_last_section`、`scripts/test_change_set.py::DocumentChangeTest::test_added_definition_is_not_a_content_change`
- 記録だけを書き換えても `check-toc` が[ToC]を古いと判定しない → `check-impact/test_check_impact.py::StaleTocTest::test_record_only_rewrite_is_not_stale`、`scripts/test_toc_check.py::ChangeListTest::test_rewriting_only_the_recorded_word_is_not_stale`

## FR-016 不整合検査

- [DLID]の欠落・重複の検査 → `check-dlid/test_check_dlid.py::DetectionTest::test_missing_document_and_section_ids`、`check-dlid/test_check_dlid.py::DetectionTest::test_document_and_section_duplicates_carry_all_paths`
- 参照の検査（壊れた参照・パス不一致・フラグメント不一致・[DLID]の無いリンク） → `check-links/test_check_links.py::CategoriesTest::test_path_mismatch_has_current_path`、`check-links/test_check_links.py::CategoriesTest::test_missing_section_is_distinguished_from_absent`、`check-links/test_check_links.py::CategoriesTest::test_links_without_dlid_in_definition_and_inline_forms`
- [ToC]の不整合（古いハッシュを含む）の検査 → `check-toc/test_check_toc.py::StatusTest::test_rebuild_needed_exits_0_with_list_and_scale`、`scripts/test_toc_check.py::ChangeListTest::test_content_change_lists_the_section_change`
- 記録と現在ハッシュが異なる参照の列挙 → `check-impact/test_check_impact.py::ImpactResultTest::test_returns_changed_documents_with_referrers_and_scope`
- 検査の SKILL が管理状態を書き換えない → `check-dlid/test_check_dlid.py::ReadOnlyTest::test_documents_and_state_are_unchanged`、`check-toc/test_check_toc.py::ReadOnlyTest::test_documents_and_state_are_unchanged`、`check-impact/test_check_impact.py::ReadOnlyTest::test_documents_and_state_are_unchanged`、`check-links/test_check_links.py::CategoriesTest::test_writes_nothing`
- 参照先が、検査するキーに所属せず別のキーにだけ所属する参照も比べ、参照先を含むキーだけを再構築した変更を返す（設計書の `check-impact` の検証観点） → `scripts/test_impact_candidates.py::OtherKeyTargetTest::test_reference_to_a_document_of_another_key_is_compared`、`scripts/test_impact_candidates.py::OtherKeyTargetTest::test_change_confirmed_by_the_other_key_is_returned`、`scenarios/test_scenario_5_multiple_keys.py::MultipleKeysScenarioTest::test_scenario_5_change_in_another_key_reaches_the_referrer`
- 参照先の構築が確定した値がどの[文書情報]にも無い参照を返さず、`check-links` が検出する（設計書の `check-impact` の検証観点） → `scripts/test_impact_candidates.py::StructureTest::test_reference_whose_target_is_not_in_the_toc_is_not_returned`、`check-links/test_check_links.py::CategoriesTest::test_unresolved_outside_root`
- 失敗したとき、エラーの JSON を返し、通知しない → `check-impact/test_check_impact.py::FailureTest::test_undeterminable_is_an_error_without_candidates`、`check-impact/test_check_impact.py::FailureTest::test_broken_confirmed_toc_is_an_error`
- 文書の[DLID]の参照は文書内のどこが変わっても返し、[セクション ID]の参照はそのセクションの範囲が変わったときだけ返す → `scripts/test_impact_candidates.py::ScopeOfChangeTest::test_document_reference_follows_any_change_section_reference_only_its_range`

### AC-032

- [DLID]の無いリンクへ、検査時点の現物から決めた title に書く値（文書の値・セクションの値）を添える → `check-links/test_check_links.py::SuggestedTitleTest::test_document_link_gets_document_hash_and_document_id`、`check-links/test_check_links.py::SuggestedTitleTest::test_heading_fragment_gets_section_hash_and_section_id`、`check-links/test_check_links.py::SuggestedTitleTest::test_explicit_anchor_fragment_gets_document_value`、`check-links/test_check_links.py::SuggestedTitleTest::test_inline_link_gets_the_same_value`
- 保存済みの管理状態の記録を根拠にしない → `check-links/test_check_links.py::SuggestedTitleTest::test_value_comes_from_the_current_file_not_from_managed_state`
- 値を添えられないとき、値を添えず理由を添える → `check-links/test_check_links.py::SuggestedTitleTest::test_unresolved_fragment_has_reason_and_no_value`、`check-links/test_check_links.py::SuggestedTitleTest::test_heading_without_dlid_has_reason_and_no_value`
- 添えた値を書いた参照が正しい参照として判定される → `check-links/test_check_links.py::SuggestedTitleTest::test_writing_the_value_makes_the_reference_formal_and_matched`、`check-links/test_check_links.py::SuggestedTitleTest::test_writing_the_section_value_makes_the_reference_matched`
- doc-link が文書へ書かない → `check-links/test_check_links.py::CategoriesTest::test_writes_nothing`

### AC-033

- 書き直す対象の検出事項があるとき、案内が、一覧を利用者に示して書き直しを確認し、承認された分だけを書き直すよう指示する → `check-links/test_check_links.py::GuidanceConfirmationTest::test_link_without_dlid_alone_asks_for_confirmation`、`check-links/test_check_links.py::GuidanceConfirmationTest::test_inline_link_with_dlid_alone_asks_for_confirmation`、`check-links/test_check_links.py::GuidanceConfirmationTest::test_path_mismatch_alone_asks_for_confirmation`、`check-links/test_check_links.py::GuidanceConfirmationTest::test_confirmation_is_given_once_for_mixed_findings`
- 検出事項が無いとき、案内を返さない → `check-links/test_check_links.py::GuidanceConfirmationTest::test_no_findings_gives_no_guidance`
- `check-links` が文書を書き換えない → `check-links/test_check_links.py::CategoriesTest::test_writes_nothing`

### AC-034

- 検査と検索前検査は、標準出力に件数までを返し、全件を明細ファイルへ書いて、そのパスを返す（D-061）→ `check-dlid/test_check_dlid.py::DetailFileTest::test_stdout_holds_counts_and_the_detail_file_holds_every_item`、`check-links/test_check_links.py::DetailFileTest::test_stdout_holds_counts_and_the_detail_file_holds_every_item`、`check-toc/test_check_toc.py::StatusTest::test_stdout_holds_counts_and_the_detail_file_holds_every_item`、`check-impact/test_check_impact.py::ImpactResultTest::test_stdout_holds_counts_and_the_detail_file_holds_every_item`、`check-impact/test_check_impact.py::StaleTocTest::test_changed_document_returns_the_check_toc_result_without_candidates`、`scripts/test_toc_check.py::TargetSpecChangeTest::test_summary_holds_counts_and_detail_holds_every_item`、`query-docs/test_query_docs.py::PrepareOutcomeTest::test_rebuild_needed_returns_scale_and_two_options`、`scripts/test_search_prepare.py::ConfirmRebuildDetailTest::test_confirm_rebuild_returns_the_summary_and_writes_the_detail`、`scripts/test_detail_file.py::EmitTest::test_summary_gets_the_detail_path_and_not_the_detail`、`scripts/test_detail_file.py::WriteTest::test_returns_the_absolute_path_and_writes_the_detail`
- 検出の件数が増えても、標準出力の大きさが変わらない → `check-dlid/test_check_dlid.py::DetailFileTest::test_stdout_size_does_not_grow_with_the_number_of_findings`、`check-links/test_check_links.py::DetailFileTest::test_stdout_size_does_not_grow_with_the_number_of_findings`
- 検出が 0 件でも明細ファイルを書き、同じ[ToC 識別キー]の次の実行が置き換える。SKILL と[ToC 識別キー]の組ごとに 1 つである → `check-dlid/test_check_dlid.py::DetailFileTest::test_detail_file_is_written_even_when_nothing_is_found`、`check-links/test_check_links.py::DetailFileTest::test_detail_file_is_written_even_when_nothing_is_found`、`check-toc/test_check_toc.py::StatusTest::test_detail_file_is_written_even_when_nothing_is_found`、`check-impact/test_check_impact.py::ImpactResultTest::test_detail_file_is_written_even_when_nothing_is_found`、`check-toc/test_check_toc.py::StatusTest::test_rerun_replaces_the_detail_file`、`check-dlid/test_check_dlid.py::DetailFileTest::test_all_mode_uses_the_reserved_key`、`scripts/test_detail_file.py::WriteTest::test_next_run_replaces_the_file_and_leaves_no_temporary_file`、`scripts/test_detail_file.py::WriteTest::test_empty_detail_is_written`、`scripts/test_detail_file.py::PathTest::test_skill_and_key_separate_the_files`、`scripts/test_detail_file.py::PathTest::test_key_is_encoded`、`scripts/test_detail_file.py::PathTest::test_path_is_under_the_skill_work_directory`、`scripts/test_target_spec.py::TocKeyTest::test_targets_mode_uses_its_key`、`scripts/test_target_spec.py::TocKeyTest::test_all_mode_uses_the_reserved_key`
- 明細ファイルを書けないときは、件数だけを返さず、失敗として報告する → `check-dlid/test_check_dlid.py::DetailFileTest::test_unwritable_detail_file_exits_1`、`check-links/test_check_links.py::DetailFileTest::test_unwritable_detail_file_exits_1`、`scripts/test_search_prepare.py::ConfirmRebuildDetailTest::test_unwritable_detail_is_a_failure`、`scripts/test_detail_file.py::EmitTest::test_unwritable_detail_returns_errors_and_1_without_the_summary`、`scripts/test_detail_file.py::WriteTest::test_unwritable_place_raises`
- 検査の前後で、[Index 対象文書]と管理状態が変わらず、書くのが明細ファイルだけである → `check-dlid/test_check_dlid.py::DetailFileTest::test_only_the_detail_file_is_written`、`check-links/test_check_links.py::DetailFileTest::test_only_the_detail_file_is_written`、`check-toc/test_check_toc.py::ReadOnlyTest::test_documents_and_state_are_unchanged`、`check-impact/test_check_impact.py::ReadOnlyTest::test_documents_and_state_are_unchanged`、`scripts/test_detail_file.py::WriteTest::test_writes_only_under_the_work_directory`

## FR-019〜028 検索基盤の切り替え、NFR-009

### AC-036

- [doc-db]が動作するとき、構築が[AI 生成フィールド]を作らず、[doc-db]を同期する → `index-docs/test_index_docs_backend.py::DocdbBuildTest::test_the_default_builds_the_machine_toc_syncs_doc_db_and_generates_nothing`、`index-docs/test_index_docs_backend.py::DocdbBuildTest::test_documents_have_no_ai_fields_and_are_marked_unfilled`、`scripts/test_update_plan.py::UnfilledTest::test_a_new_document_gets_an_unfilled_info_and_is_not_marked_unfilled_before`、`scripts/test_backend_select.py::DecideTest::test_the_default_is_doc_db_when_it_works`
- 検索が[doc-db]で行われ、結果が[検索基盤]として `doc-db` を示す → `query-docs/test_query_docs_backend.py::DocdbSearchTest::test_up_to_date_syncs_then_searches_and_returns_mapped_documents`、`query-docs/test_query_docs_backend.py::DocdbSearchTest::test_a_search_changes_neither_the_state_nor_the_documents`、`query-docs/test_query_docs_backend.py::DocdbSearchTest::test_no_working_files_are_left_for_a_doc_db_search`
- 実機の[doc-db]で、起動・同期・検索ができる → `docdb_manual.md`

### AC-037

- 設定ファイルの強制スイッチで、[doc-db]へ接続も起動もせず、[ToC]で構築と検索が行われ、切り替えの通知が無い → `scripts/test_backend_select.py::DecideTest::test_the_forced_switch_neither_connects_nor_starts_nor_notifies`、`index-docs/test_index_docs_backend.py::SettingTest::test_the_forced_switch_in_the_setting_never_touches_doc_db`、`query-docs/test_query_docs_backend.py::SettingTest::test_the_forced_switch_in_the_setting_is_used_without_connecting`、`query-docs/test_query_docs_backend.py::TocRuleTest::test_a_filled_up_to_date_toc_is_searched_by_workers`
- 呼び出しごとの上書きの引数が無い → `index-docs/test_index_docs_backend.py::SettingTest::test_there_is_no_per_call_override`
- 実機で、強制スイッチが[doc-db]へ接続しない → `docdb_manual.md`

### AC-038

- [doc-db]へ接続できず、起動を試みても接続できないとき、[ToC]へ切り替えて構築・検索を完了する → `scripts/test_backend_select.py::DecideTest::test_an_unreachable_doc_db_switches_to_toc_with_a_notice`、`scripts/test_backend_select.py::DecideTest::test_the_decision_is_not_remembered`、`index-docs/test_index_docs_backend.py::SwitchDuringBuildTest::test_an_unreachable_doc_db_at_the_start_builds_as_toc_with_a_notice`、`query-docs/test_query_docs_backend.py::DocdbFailureTest::test_an_unreachable_doc_db_at_the_start_is_reported_in_the_toc_result`
- 実機で、実行ファイルが無いときに切り替わる → `docdb_manual.md`

### AC-039

- 同期での Embedding の失敗（識別子 `EMBEDDING_FAILED`、または契約を満たさない[doc-db]の文言）で、[ToC]へ切り替えて続ける → `scripts/test_docdb_sync.py::RunSyncTest::test_an_embedding_failure_in_a_done_job_switches_for_openai`、`scripts/test_docdb_sync.py::RunSyncTest::test_identifiers_make_the_switch_certain`、`scripts/test_docdb_sync.py::RunSyncTest::test_a_failed_job_with_the_embedding_identifier_switches`、`index-docs/test_index_docs_backend.py::SwitchDuringBuildTest::test_an_openai_failure_in_the_sync_continues_as_toc_and_generates`、`index-docs/test_index_docs_backend.py::SwitchDuringBuildTest::test_no_generation_is_needed_when_every_document_is_already_filled`、`query-docs/test_query_docs_backend.py::DocdbFailureTest::test_an_openai_failure_in_the_sync_continues_as_toc`、`query-docs/test_query_docs_backend.py::DocdbFailureTest::test_the_switch_is_carried_into_the_toc_result`
- 検索の Embedding の失敗で、[ToC]へ切り替えて続ける → `scripts/test_docdb_search.py::SearchTest::test_embedding_failures_switch`、`scripts/test_docdb_search.py::SearchTest::test_an_internal_error_without_an_identifier_switches_only_for_old_versions`、`query-docs/test_query_docs_backend.py::DocdbFailureTest::test_an_embedding_failure_in_the_search_continues_as_toc`、`query-docs/test_query_docs_backend.py::DocdbFailureTest::test_an_internal_error_without_an_identifier_is_presumed_for_old_versions_only`
- 接続の断で切り替わる → `scripts/test_docdb_sync.py::RunSyncTest::test_a_dropped_connection_switches_for_unreachable`、`scripts/test_docdb_search.py::SearchTest::test_a_dropped_connection_switches_for_unreachable`、`index-docs/test_index_docs_backend.py::SwitchDuringBuildTest::test_a_dropped_connection_in_the_sync_switches_for_unreachable`、`query-docs/test_query_docs_backend.py::DocdbFailureTest::test_a_dropped_connection_continues_as_toc`
- 実機で、無効な鍵（HTTP 401）で切り替わる → `docdb_manual.md`

### AC-040

- (a)・(b) 以外の[doc-db]の失敗では、切り替えず、失敗として原因と次の判断に要る情報を返す → `scripts/test_docdb_sync.py::RunSyncTest::test_another_failure_in_a_done_job_is_a_fault`、`scripts/test_docdb_sync.py::RunSyncTest::test_tool_errors_follow_the_identifier`、`scripts/test_docdb_sync.py::RunSyncTest::test_http_and_protocol_errors_are_faults`、`scripts/test_docdb_sync.py::RunSyncTest::test_exceeding_the_wait_limit_is_a_fault_not_a_switch`、`scripts/test_docdb_search.py::SearchTest::test_other_failures_do_not_switch`、`index-docs/test_index_docs_backend.py::SwitchDuringBuildTest::test_a_fault_in_the_sync_exits_4_after_publishing_the_machine_toc`、`query-docs/test_query_docs_backend.py::DocdbFailureTest::test_other_failures_stop_without_switching`

### AC-041

- 切り替え後、AI 生成フィールドが未生成の文書と、内容が変わった文書だけを生成する → `index-docs/test_index_docs_backend.py::DocdbBuildTest::test_a_content_change_keeps_the_old_ai_fields_and_leaves_them_stale`、`index-docs/test_index_docs_backend.py::DocdbBuildTest::test_switching_to_toc_by_the_setting_generates_every_unfilled_document`、`scripts/test_update_plan.py::UnfilledTest::test_a_changed_document_keeps_its_old_ai_fields_and_is_not_unfilled`、`scripts/test_toc_check.py::AiFieldsTest::test_unfilled_documents_are_counted_even_when_the_toc_is_up_to_date`
- 未生成の文書があるとき、または機械取得の情報は最新なのに AI 生成フィールドが古いとき、二択を示さずに構築する。それ以外は、既存の二択を示す → `query-docs/test_query_docs_backend.py::TocRuleTest::test_unfilled_members_force_a_build_and_refuse_the_existing_choice`、`query-docs/test_query_docs_backend.py::TocRuleTest::test_stale_ai_fields_with_an_up_to_date_toc_force_a_build`、`query-docs/test_query_docs_backend.py::TocRuleTest::test_an_ordinary_stale_toc_keeps_the_two_options`、`query-docs/test_query_docs_backend.py::DocdbFailureTest::test_a_switch_with_unfilled_documents_asks_for_a_build_without_the_two_options`

### AC-042

- 切り替えの通知が、切り替え・理由・原因・影響・次の実行の扱いを持ち、認証情報と[doc-db]の応答の生の文字列を含まない → `scripts/test_backend_select.py::SwitchTest::test_the_notice_names_the_switch_reason_cause_impact_and_next_run`、`scripts/test_backend_select.py::SwitchTest::test_a_presumed_cause_is_marked`、`scripts/test_backend_select.py::SwitchTest::test_to_dict_carries_the_notice_and_no_secrets`、`scripts/test_docdb_client.py::ClientTest::test_a_tool_error_carries_only_the_identifier_and_numeric_code`、`scripts/test_docdb_client.py::ClientTest::test_the_openai_http_status_is_carried_when_doc_db_confirmed_it`、`scripts/test_docdb_runtime.py::EnsureAvailableTest::test_the_failure_detail_has_no_exception_message`、`scripts/test_docdb_sync.py::RunSyncTest::test_http_and_protocol_errors_are_faults`
- 通知を、AI が利用者へ伝える（SKILL.md の手順）→ `index-docs/test_skill_md.py`、`query-docs/test_skill_md.py` が、SKILL.md の構造を検査する。AI の振る舞いは `docdb_manual.md`（結果の `backend_switch.notice`）で確かめる

### AC-043

- [確定 ToC]の所属と現在のパスから一覧を作り、移動・削除・追加を[doc-db]へ反映する → `scripts/test_docdb_sync.py::DocumentListTest::test_the_list_comes_from_the_confirmed_toc_with_relative_and_absolute_paths`、`scripts/test_docdb_sync.py::DocumentListTest::test_a_deleted_file_is_left_out_and_reported`、`scripts/test_docdb_sync.py::DocumentListTest::test_a_moved_file_is_listed_under_its_recorded_path_only`、`scripts/test_docdb_sync.py::RunSyncTest::test_the_empty_list_is_still_sent`、`index-docs/test_index_docs_backend.py::DocdbBuildTest::test_a_moved_and_a_deleted_document_are_reflected_in_the_next_list`
- [doc-db]を使うとき、古ければ二択を示さずに更新してから検索する。未構築は初回構築を求める → `query-docs/test_query_docs_backend.py::DocdbAutomaticUpdateTest::test_a_stale_toc_asks_for_a_rebuild_without_the_two_options`、`query-docs/test_query_docs_backend.py::DocdbAutomaticUpdateTest::test_the_existing_choice_is_not_offered`、`query-docs/test_query_docs_backend.py::DocdbAutomaticUpdateTest::test_after_the_rebuild_the_search_runs`、`query-docs/test_query_docs_backend.py::DocdbAutomaticUpdateTest::test_a_rebuild_that_did_not_bring_the_toc_up_to_date_is_an_error`、`query-docs/test_query_docs_backend.py::DocdbSearchTest::test_not_built_still_asks_for_the_first_build`
- 実機で、移動・削除の後の検索が変更前のパスを返さない → `docdb_manual.md`

### AC-044

- 結果が、[文書 ID]・パス・理由・[ToC 識別キー]・版・鮮度・[検索基盤]を持ち、対応づけられない結果の件数を報告し、上位の結果に限られることを明示する → `query-docs/test_query_docs_backend.py::DocdbSearchTest::test_up_to_date_syncs_then_searches_and_returns_mapped_documents`、`scripts/test_docdb_search.py::MapResultsTest::test_documents_follow_the_rank_of_their_best_chunk`、`scripts/test_docdb_search.py::MapResultsTest::test_relevance_is_always_maybe_and_the_reason_is_a_fixed_sentence`、`scripts/test_docdb_search.py::MapResultsTest::test_the_section_is_read_from_the_dlid_at_the_end_of_the_heading_path`、`scripts/test_docdb_search.py::MapResultsTest::test_a_dlid_the_document_does_not_have_falls_back_to_the_document`、`scripts/test_docdb_search.py::MapResultsTest::test_a_result_without_a_matching_path_is_counted_not_listed`、`scripts/test_docdb_search.py::SearchTest::test_the_task_is_passed_as_is_in_all_mode_without_rerank`

### AC-045

- [検索基盤]によらず、検査・解決の SKILL が同じ結果を返す → `scenarios/test_scenario_8_docdb_backend.py::DocdbBackendScenarioTest::test_the_inspection_skills_return_the_same_results_for_both_backends`、`scripts/test_backend_config.py::LoadTest::test_config_file_does_not_disturb_the_state_listing`
- [doc-db]を使っている間に変更された文書の AI 生成フィールドが、[ToC]へ切り替えた後に再生成される → `scenarios/test_scenario_8_docdb_backend.py::DocdbBackendScenarioTest::test_a_change_made_while_using_doc_db_is_regenerated_after_switching_to_toc`、`index-docs/test_index_docs_backend.py::DocdbBuildTest::test_a_content_change_keeps_the_old_ai_fields_and_leaves_them_stale`

### AC-046

- 出力・作業ファイル・管理状態に、OpenAI の認証情報が含まれない（認証情報を読まない・渡さない）→ `scripts/test_docdb_client.py::ReadPortTest::test_the_failure_does_not_carry_the_file_body`、`scripts/test_docdb_client.py::ClientTest::test_a_tool_error_carries_only_the_identifier_and_numeric_code`、`scripts/test_docdb_runtime.py::SpawnServerTest::test_it_starts_a_new_session_without_arguments_or_inherited_streams`、`scripts/test_docdb_contract.py::JobTest::test_labels_never_contain_the_error_text`、`query-docs/test_query_docs_backend.py::DocdbFailureTest::test_an_unreachable_doc_db_at_the_start_is_reported_in_the_toc_result`

### AC-047

- [doc-db]へ接続できないとき、起動して期限内に再接続し、使える → `scripts/test_docdb_runtime.py::EnsureAvailableTest::test_it_starts_doc_db_and_reconnects_within_the_deadline`、`scripts/test_docdb_runtime.py::EnsureAvailableTest::test_a_running_doc_db_is_used_without_starting`、`scripts/test_docdb_runtime.py::EnsureAvailableTest::test_an_early_exit_is_forgiven_when_another_instance_answers`
- 起動しても接続できないとき、原因（実行ファイルが無い・起動できない・接続の前に終了した・期限内に接続できない・設定ファイルから port を得られない）を区別して返す → `scripts/test_docdb_runtime.py::EnsureAvailableTest::test_a_missing_executable_is_reported_without_starting`、`scripts/test_docdb_runtime.py::EnsureAvailableTest::test_a_spawn_failure_is_reported`、`scripts/test_docdb_runtime.py::EnsureAvailableTest::test_an_early_exit_gets_exactly_one_more_try`、`scripts/test_docdb_runtime.py::EnsureAvailableTest::test_the_deadline_stops_the_retries`、`scripts/test_docdb_runtime.py::EnsureAvailableTest::test_a_missing_config_means_neither_connecting_nor_starting`
- 停止せず、常駐の設定をせず、ログのファイルを作らない。強制スイッチのときは起動しない → `scripts/test_docdb_runtime.py::SpawnServerTest::test_it_starts_a_new_session_without_arguments_or_inherited_streams`、`scripts/test_backend_select.py::DecideTest::test_the_forced_switch_neither_connects_nor_starts_nor_notifies`
- 実機で、起動・鍵が無いときの終了・実行ファイルが無いときの切り替え → `docdb_manual.md`

### AC-048

- 設定が未指定のとき[doc-db]を先に試し、設定が読めない・値が不正なときは、構築・検索を行わず原因を返す → `scripts/test_backend_config.py::LoadTest::test_missing_file_means_auto`、`scripts/test_backend_config.py::LoadTest::test_missing_key_means_auto`、`scripts/test_backend_config.py::LoadTest::test_toc_and_auto_are_accepted`、`scripts/test_backend_config.py::LoadTest::test_invalid_files_are_rejected_without_falling_back_to_auto`、`scripts/test_backend_config.py::LoadTest::test_a_directory_in_place_of_the_file_is_rejected`、`scripts/test_backend_select.py::DecideTest::test_an_invalid_config_is_an_error_and_does_not_probe`、`index-docs/test_index_docs_backend.py::SettingTest::test_an_invalid_setting_stops_the_build_without_writing_anything`、`query-docs/test_query_docs_backend.py::SettingTest::test_an_invalid_setting_stops_the_search_with_the_reason`

### AC-049

- 識別子（`EMBEDDING_FAILED`・`INTERNAL_ERROR`・`KEY_NOT_FOUND`・`KEY_TRASHED`）だけで失敗を分類し、`EMBEDDING_FAILED` のときだけ[ToC]へ切り替える。契約を満たすかを、同期の応答の目印（`document_errors`）で判断する → `scripts/test_docdb_contract.py::MarkerTest::test_the_marker_is_document_errors_in_the_job`、`scripts/test_docdb_contract.py::ToolErrorTest::test_identifiers_classify_regardless_of_the_contract`、`scripts/test_docdb_contract.py::ToolErrorTest::test_an_internal_error_without_an_identifier_depends_on_the_contract`、`scripts/test_docdb_contract.py::ToolErrorTest::test_other_errors_without_an_identifier_are_faults`、`scripts/test_docdb_contract.py::JobTest::test_document_errors_are_read_by_their_codes`、`scripts/test_docdb_contract.py::JobTest::test_an_embedding_failure_wins_over_other_codes`、`scripts/test_docdb_contract.py::JobTest::test_text_errors_of_a_job_that_meets_the_contract_are_faults`、`scripts/test_docdb_sync.py::RunSyncTest::test_a_clean_job_with_the_marker_reports_the_contract_as_met`
- 契約を満たさない[doc-db]では、当面の扱いに従い、結果の警告に、その旨を含める → `scripts/test_docdb_contract.py::JobTest::test_text_errors_are_read_only_when_the_marker_is_absent`、`index-docs/test_index_docs_backend.py::DocdbBuildTest::test_the_contract_warning_is_added_unless_the_contract_is_met`、`query-docs/test_query_docs_backend.py::DocdbSearchTest::test_a_met_contract_has_no_warning`
- 同期で Embedding に失敗した文書が、次の同期で補われる → `docdb_manual.md`（契約を実装した[doc-db]の実機。手順 7・8）

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
- `check-links` の検証観点（[DLID]入りの title のインラインリンクの報告、直前の語が 12 桁の小文字 16 進のときだけ記録として読む） → `check-links/test_check_links.py::CategoriesTest::test_inline_link_with_dlid_title`、`check-links/test_check_links.py::RecordWordTest::test_only_a_lowercase_hex_word_of_the_record_length_is_read_as_a_record`
- 決定論的処理の単体テスト（対象指定の展開、Markdown 解析、ID の認識・発行・重複、[DLID]の解決、パス解決、ディレクトリ走査結果の分類、比較値、AI 出力検証、[ToC 候補]の整合性） → `scripts/test_target_spec.py::ExpansionTest::test_dirs_collects_markdown_recursively`、`scripts/test_markdown_reader.py::HeadingTest::test_section_ranges`、`scripts/test_dlid.py::DuplicateTest::test_same_document_id_in_two_files`、`scripts/test_reference_check.py::StatusTest::test_directory_unreadable`、`scripts/test_content_hash.py::DocumentHashTest::test_known_vector`、`scripts/test_ai_output_validator.py::BoundaryTest::test_valid_result_is_accepted`、`scripts/test_toc_candidate.py::ValidateTest::test_assembled_candidate_passes`

## 横断シナリオ（設計書の「横断シナリオ」）

- 1 初回 → `scenarios/test_scenario_1_first_time.py::FirstTimeScenarioTest::test_scenario_1_from_embedding_to_searchable`
- 2 移動 → `scenarios/test_scenario_2_3_move_and_change.py::MoveScenarioTest::test_scenario_2_move_updates_current_path_without_regenerating`
- 3 内容変更 → `scenarios/test_scenario_2_3_move_and_change.py::ContentChangeScenarioTest::test_scenario_3_same_reference_until_the_record_is_rewritten`
- 4 失敗 → `scenarios/test_scenario_4_failure.py::GenerationFailureScenarioTest::test_scenario_4_rejected_generation_keeps_old_toc_and_saved_info`、`scenarios/test_scenario_4_failure.py::ReferenceScanFailureScenarioTest::test_scenario_4_scan_failure_keeps_old_toc`、`scenarios/test_scenario_4_failure.py::CandidateFailureScenarioTest::test_scenario_4_publish_failure_keeps_old_toc`
- 5 複数キー → `scenarios/test_scenario_5_multiple_keys.py::MultipleKeysScenarioTest::test_scenario_5_both_keys_show_the_same_document_info`、`scenarios/test_scenario_5_multiple_keys.py::MultipleKeysScenarioTest::test_scenario_5_value_of_a_shared_document_is_one_for_both_keys`、`scenarios/test_scenario_5_multiple_keys.py::MultipleKeysScenarioTest::test_scenario_5_change_in_another_key_reaches_the_referrer`
- 6 範囲外参照 → `scenarios/test_scenario_6_out_of_scope_reference.py::OutOfScopeReferenceScenarioTest::test_scenario_6_scan_result_has_scope_and_time_for_out_of_target_documents`
- 7 後からの参照 → `scenarios/test_scenario_7_later_reference.py::LaterReferenceScenarioTest::test_scenario_7_new_reference_is_extracted_without_writing_the_target`

## 配布物の適合（このディレクトリの検査）

- 配布物が開発文書を参照しない → `distribution/test_distribution_references.py::DistributionReferenceTest::test_distributed_documents_do_not_refer_to_development_documents`
- SKILL.md・Agent の作成規約への適合 → `distribution/test_skill_agent_conformance.py::SkillMdConformanceTest::test_code_blocks_only_call_entry_scripts_and_hold_no_logic`、`distribution/test_skill_agent_conformance.py::AgentMdConformanceTest::test_role_constraints_and_prohibitions_are_written_negatively`
- 全 `.py` にテストがあり、Node.js を使わず、終了コードを宣言している → `distribution/test_script_conformance.py::EveryPythonFileHasTestTest::test_every_python_file_has_its_test`、`distribution/test_script_conformance.py::NoNodeJsTest::test_no_node_files`、`distribution/test_script_conformance.py::ExitCodeDeclarationTest::test_codes_of_three_or_more_are_declared_with_zero_included`
- PEP 723・ロック・uv での起動・一時ファイルの置き場 → `distribution/test_script_environment.py::Pep723AndLockTest::test_every_entry_script_has_its_lock_file`、`distribution/test_script_environment.py::UvRunHelpTest::test_every_entry_script_runs_with_uv_run_locked`、`distribution/test_script_environment.py::TemporaryFileLocationTest::test_tempfile_calls_name_their_directory`
