# Test Run full-real-recheck-after-shrink

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `973.4s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `acceptance_scope`: `settings_brainstorm_volume_export`
- `novel_id`: `codex-cf5a`
- `setting_session_id`: `sgs_2d701696ccc740a99c7d56c860b5056b`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `3`
- `review_batch_id`: `2a35a804311f4e28845a3a55be244b38`
- `pending_id`: `pe_89d4ea47`
- `volume_id`: `vol-1`
- `chapter_target_word_count`: `120`
- `chapter_auto_run_job_id`: `job_585d293b77b8`

## Issues

### SYSTEM_BUG-auto_run_chapters `SYSTEM_BUG`

- Severity: `high`
- Stage: `auto_run_chapters`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: auto_run_chapters did not archive any chapter
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage auto_run_chapters`
