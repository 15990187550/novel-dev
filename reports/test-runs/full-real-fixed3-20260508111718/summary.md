# Test Run full-real-fixed3-20260508111718

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `366.0s`

## Issues

### TIMEOUT_INTERNAL-brainstorm `TIMEOUT_INTERNAL`

- Severity: `high`
- Stage: `brainstorm`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `passed`
- Message: ReadTimeout
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage brainstorm`
