# Test Run full-real-contract-volumefix-20260508180735

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `622.5s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `novel_id`: `codex-19e6`
- `setting_session_id`: `sgs_2e89943ac37b4b4daff86cb008422614`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `1`
- `review_batch_id`: `e145775de0fc404092be034b66343a9a`
- `pending_id`: `pe_848f5121`
- `brainstorm_original_estimated_volumes`: `4`
- `brainstorm_original_estimated_total_chapters`: `120`
- `brainstorm_shrunk_estimated_total_chapters`: `1`
- `volume_id`: `volume_1`
- `chapter_id`: `acceptance-codex-19e6-ch1`
- `chapter_plan_source`: `current_volume_plan.chapters[0]`
- `chapter_target_word_count`: `120`
- `chapter_auto_run_job_id`: `job_c100552d54f3`
- `chapter_job_stopped_reason`: `volume_completed`
- `chapter_text_status`: `none`
- `chapter_text_length`: `0`

## Issues

### SYSTEM_BUG-auto_run_chapters_contract `SYSTEM_BUG`

- Severity: `high`
- Stage: `auto_run_chapters_contract`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: auto_run_chapters completed without generated chapter text
- Evidence: chapter_id=acceptance-codex-19e6-ch1, job_id=job_c100552d54f3
- Reproduce: `scripts/verify_generation_real.sh --stage auto_run_chapters`
