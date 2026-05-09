# Test Run full-real-recheck-after-isolation

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `1187.3s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `acceptance_scope`: `settings_brainstorm_volume_export`
- `novel_id`: `codex-d72e`
- `setting_session_id`: `sgs_797806368c104b16b441c96bc7f933c1`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `1`
- `review_batch_id`: `47eae1c50dba4e10aab32281d33fa28a`
- `pending_id`: `pe_c7a380ab`
- `volume_id`: `vol_01_canye_yishu`
- `chapter_target_word_count`: `120`
- `chapter_auto_run_job_id`: `job_d348607622f0`

## Issues

### LLM_PARSE_ERROR-auto_run_chapters `LLM_PARSE_ERROR`

- Severity: `high`
- Stage: `auto_run_chapters`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: LLM orchestrated parse failed after 3 retries for ContextAgent/build_scene_context: build_scene_context failed validator subtask after repair: {'valid': False, 'reason': 'narrative_too_short', 'min_chars': 30, 'actual_chars': 0}
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage auto_run_chapters`
