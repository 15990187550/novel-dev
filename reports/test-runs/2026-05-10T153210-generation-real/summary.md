# Test Run 2026-05-10T153210-generation-real

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `0.0s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`

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
