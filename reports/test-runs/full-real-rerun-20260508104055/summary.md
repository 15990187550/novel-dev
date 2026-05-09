# Test Run full-real-rerun-20260508104055

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `0.4s`

## Issues

### SYSTEM_BUG-preflight_health `SYSTEM_BUG`

- Severity: `high`
- Stage: `preflight_health`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Server error '502 Bad Gateway' for url 'http://127.0.0.1:8000/healthz'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/502
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage preflight_health`
