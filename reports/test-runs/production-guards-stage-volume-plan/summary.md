# Test Run production-guards-stage-volume-plan

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `0.3s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `target_stage`: `volume_plan`
- `novel_id`: `codex-b312`
- `setting_session_id`: `sgs_b63bf57737374bcba738444ae2f1e3ba`

## Issues

### SYSTEM_BUG-advance_setting_session `SYSTEM_BUG`

- Severity: `high`
- Stage: `advance_setting_session`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Server error '500 Internal Server Error' for url 'http://127.0.0.1:8000/api/novels/codex-b312/settings/sessions/sgs_b63bf57737374bcba738444ae2f1e3ba/reply'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage advance_setting_session`
