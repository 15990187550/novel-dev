# Test Run production-guards-stage-volume-plan-3

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `87.7s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `target_stage`: `volume_plan`
- `novel_id`: `codex-001f`
- `setting_session_id`: `sgs_f71eb10d05c74808aff344f8228cb582`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `1`

## Issues

### SYSTEM_BUG-generate_setting_review_batch `SYSTEM_BUG`

- Severity: `high`
- Stage: `generate_setting_review_batch`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Client error '409 Conflict' for url 'http://127.0.0.1:8000/api/novels/codex-001f/settings/sessions/sgs_f71eb10d05c74808aff344f8228cb582/generate'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/409
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage generate_setting_review_batch`
