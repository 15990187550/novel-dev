# Test Run full-real-fixed-20260508105556

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `13.4s`

## Issues

### SYSTEM_BUG-advance_setting_session `SYSTEM_BUG`

- Severity: `high`
- Stage: `advance_setting_session`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: advance_setting_session did not reach ready_to_generate
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage advance_setting_session`
