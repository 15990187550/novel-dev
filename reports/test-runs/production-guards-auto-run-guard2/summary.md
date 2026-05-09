# Test Run production-guards-auto-run-guard2

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `1341.9s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `target_stage`: `auto_run_chapters`
- `novel_id`: `codex-1674`
- `setting_session_id`: `sgs_574646973c29430f9221b4d0576d2202`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `5`
- `review_batch_id`: `9ec6f611a023426f8a36af4233957818`
- `pending_id`: `pe_92defc2f`
- `brainstorm_original_estimated_volumes`: `5`
- `brainstorm_original_estimated_total_chapters`: `160`
- `brainstorm_shrunk_estimated_total_chapters`: `1`
- `volume_id`: `vol-1`
- `chapter_id`: `acceptance-codex-1674-ch1`
- `chapter_plan_source`: `current_chapter_plan`
- `chapter_target_word_count`: `1000`
- `chapter_auto_run_job_id`: `job_b9c6255d9a8a`

## Issues

### SYSTEM_BUG-auto_run_chapters `SYSTEM_BUG`

- Severity: `high`
- Stage: `auto_run_chapters`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Writer beat structure guard failed
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage auto_run_chapters`
