# Test Run full-real-contract-wordcountwarn-20260509101112

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `1235.2s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `novel_id`: `codex-ec26`
- `setting_session_id`: `sgs_132ec9dd9bd7470384369aeaa9a6c6ba`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `1`
- `review_batch_id`: `f2a656c512754dd98a6dc05088300014`
- `pending_id`: `pe_fb31a660`
- `brainstorm_original_estimated_volumes`: `5`
- `brainstorm_original_estimated_total_chapters`: `150`
- `brainstorm_shrunk_estimated_total_chapters`: `1`
- `volume_id`: `vol_001`
- `chapter_id`: `acceptance-codex-ec26-ch1`
- `chapter_plan_source`: `current_volume_plan.chapters[0]`
- `chapter_target_word_count`: `1000`
- `chapter_auto_run_job_id`: `job_56ec46973479`

## Issues

### SYSTEM_BUG-auto_run_chapters `SYSTEM_BUG`

- Severity: `high`
- Stage: `auto_run_chapters`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: generation job polling timed out: job_56ec46973479 last_status=running
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage auto_run_chapters`
