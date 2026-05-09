# Test Run full-real-contract-recheck

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `687.3s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `novel_id`: `codex-e690`
- `setting_session_id`: `sgs_4580d2bd8cba4d0fb9e5d5abf4e1d975`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `2`
- `review_batch_id`: `f3100c3290904c46b01fb7af5fc79100`
- `pending_id`: `pe_f9e41f49`
- `brainstorm_original_estimated_volumes`: `6`
- `brainstorm_original_estimated_total_chapters`: `240`
- `brainstorm_shrunk_estimated_total_chapters`: `1`
- `volume_id`: `vol_1`
- `chapter_id`: `acceptance-codex-e690-ch1`
- `chapter_plan_source`: `current_chapter_plan`
- `chapter_target_word_count`: `120`
- `chapter_auto_run_job_id`: `job_5e0470facfa7`

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
