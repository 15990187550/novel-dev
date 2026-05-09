# Test Run full-real-recheck-after-fix

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `1405.3s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `acceptance_scope`: `settings_brainstorm_volume_export`
- `novel_id`: `codex-91f5`
- `setting_session_id`: `sgs_f566afdeb29a47cfa1601ab931161177`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `2`
- `review_batch_id`: `7e9ed354455943e2abcc3b23350a8669`
- `pending_id`: `pe_55f54be8`
- `volume_id`: `V1-QYXH`
- `chapter_auto_run_job_id`: `job_f39d01410877`

## Issues

### SYSTEM_BUG-auto_run_chapters `SYSTEM_BUG`

- Severity: `high`
- Stage: `auto_run_chapters`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: generation job polling timed out: job_f39d01410877 last_status=running
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage auto_run_chapters`
