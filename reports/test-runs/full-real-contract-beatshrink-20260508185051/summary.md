# Test Run full-real-contract-beatshrink-20260508185051

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `1102.8s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `novel_id`: `codex-4f6c`
- `setting_session_id`: `sgs_d79dd9eba9ea44f98145ad14aa6a5488`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `3`
- `review_batch_id`: `99b02935d3b94475955cd925e5fe3851`
- `pending_id`: `pe_7ce8e8db`
- `brainstorm_original_estimated_volumes`: `3`
- `brainstorm_original_estimated_total_chapters`: `90`
- `brainstorm_shrunk_estimated_total_chapters`: `1`
- `volume_id`: `volume_1`
- `chapter_id`: `acceptance-codex-4f6c-ch1`
- `chapter_plan_source`: `current_volume_plan.chapters[0]`
- `chapter_target_word_count`: `120`
- `chapter_auto_run_job_id`: `job_fdd06caa93cb`
- `chapter_job_stopped_reason`: `quality_blocked`
- `chapter_text_status`: `polished_text`
- `chapter_text_length`: `950`
- `quality_status`: `block`
- `quality_reasons`: `blocking_items,status,summary,warning_items`
- `archived_chapter_count`: `0`

## Issues

### SYSTEM_BUG-quality_gate `SYSTEM_BUG`

- Severity: `high`
- Stage: `quality_gate`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Chapter generated text but quality gate blocked archival
- Evidence: chapter_id=acceptance-codex-4f6c-ch1, job_id=job_fdd06caa93cb, chapter_job_stopped_reason=quality_blocked, archived_chapter_count=0, quality_status=block, quality_reasons=blocking_items,status,summary,warning_items
- Reproduce: `scripts/verify_generation_real.sh --stage auto_run_chapters`
