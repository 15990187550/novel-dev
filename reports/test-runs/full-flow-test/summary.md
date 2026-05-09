# Test Run full-flow-test

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `736.6s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `novel_id`: `codex-0b71`
- `setting_session_id`: `sgs_b2b790ce802040fab51663e4ba52d9be`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `1`
- `review_batch_id`: `09a3cf8039f0417a8c1842eab316b5c4`
- `pending_id`: `pe_8f71574f`
- `brainstorm_original_estimated_volumes`: `5`
- `brainstorm_original_estimated_total_chapters`: `100`
- `brainstorm_shrunk_estimated_total_chapters`: `1`
- `volume_id`: `V1`
- `chapter_id`: `acceptance-codex-0b71-ch1`
- `chapter_plan_source`: `current_chapter_plan`
- `chapter_target_word_count`: `1000`
- `chapter_auto_run_job_id`: `job_0c0aa6407157`

## Issues

### SYSTEM_BUG-auto_run_chapters `SYSTEM_BUG`

- Severity: `high`
- Stage: `auto_run_chapters`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: LLM orchestrated parse failed after 3 retries for ContextAgent/build_scene_context: build_scene_context failed validator subtask after repair: {'valid': False, 'reason': 'missing_required_context', 'missing_terms': ['青云宗']}
- Evidence: job_id=job_0c0aa6407157, status=failed, error_message=LLM orchestrated parse failed after 3 retries for ContextAgent/build_scene_context: build_scene_context failed validator subtask after repair: {'valid': False, 'reason': 'missing_required_context', 'missing_terms': ['青云宗']}, result_payload.stopped_reason=failed, result_payload.failed_phase=context_preparation, result_payload.failed_chapter_id=acceptance-codex-0b71-ch1, result_payload.current_phase=context_preparation, result_payload.current_chapter_id=acceptance-codex-0b71-ch1, result_payload.error=LLM orchestrated parse failed after 3 retries for ContextAgent/build_scene_context: build_scene_context failed validator subtask after repair: {'valid': False, 'reason': 'missing_required_context', 'missing_terms': ['青云宗']}
- Reproduce: `scripts/verify_generation_real.sh --stage auto_run_chapters`
