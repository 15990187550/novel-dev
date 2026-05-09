# Test Run full-real-recheck-after-synopsis-shrink

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `897.2s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `acceptance_scope`: `settings_brainstorm_volume_export`

## Issues

### SYSTEM_BUG-api_smoke_flow `SYSTEM_BUG`

- Severity: `high`
- Stage: `api_smoke_flow`
- External blocker: `False`
- Real LLM: `False`
- Fake rerun status: `None`
- Message: current_chapter_plan missing after volume_plan
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh`
