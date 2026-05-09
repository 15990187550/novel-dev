# Test Run debug-full-after-env-fix

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `823.3s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`

## Issues

### SYSTEM_BUG-volume_plan_contract `SYSTEM_BUG`

- Severity: `high`
- Stage: `volume_plan_contract`
- External blocker: `False`
- Real LLM: `False`
- Fake rerun status: `None`
- Message: volume_plan review failed before a usable acceptance chapter plan was prepared
- Evidence: response_keys=chapters,estimated_total_words,review_status,summary,title,total_chapters,volume_id,volume_number, checkpoint_keys=acceptance_scope,current_volume_plan,novel_title,synopsis_data,synopsis_doc_id,volume_plan_attempt_count, current_chapter_plan_present=false, current_volume_plan_keys=chapters,entity_highlights,estimated_total_words,relationship_highlights,review_status,summary,title,total_chapters,volume_id,volume_number, current_volume_plan_chapter_count=1, review_status_status=revise_failed, review_status_reason=已达最大自动修订次数，请在大纲工作台人工调整。
- Reproduce: `scripts/verify_generation_real.sh --stage volume_plan`
