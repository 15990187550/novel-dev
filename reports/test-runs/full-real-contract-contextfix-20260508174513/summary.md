# Test Run full-real-contract-contextfix-20260508174513

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `703.7s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `novel_id`: `codex-4325`
- `setting_session_id`: `sgs_f5634aaf04cf47e39aeb039c1be3d4f1`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `1`
- `review_batch_id`: `4779e96c13d847fb87a3027abe968f6b`
- `pending_id`: `pe_a3cc630c`
- `brainstorm_original_estimated_volumes`: `4`
- `brainstorm_original_estimated_total_chapters`: `48`
- `brainstorm_shrunk_estimated_total_chapters`: `1`

## Issues

### SYSTEM_BUG-volume_plan `SYSTEM_BUG`

- Severity: `high`
- Stage: `volume_plan`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Client error '400 Bad Request' for url 'http://127.0.0.1:8000/api/novels/codex-4325/volume_plan'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage volume_plan`
