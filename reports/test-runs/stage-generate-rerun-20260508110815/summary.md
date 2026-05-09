# Test Run stage-generate-rerun-20260508110815

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `76.1s`

## Issues

### SYSTEM_BUG-generate_setting_review_batch `SYSTEM_BUG`

- Severity: `high`
- Stage: `generate_setting_review_batch`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: 
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage generate_setting_review_batch`
