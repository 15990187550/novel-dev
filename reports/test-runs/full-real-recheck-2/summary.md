# Test Run full-real-recheck-2

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `0.1s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `acceptance_scope`: `settings_brainstorm_volume_export`

## Issues

### SYSTEM_BUG-preflight_health `SYSTEM_BUG`

- Severity: `high`
- Stage: `preflight_health`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: All connection attempts failed
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage preflight_health`
