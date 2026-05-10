# Test Run 2026-05-10T145708-generation-real

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `0.1s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `novel_id`: `codex-8aea`
- `setting_session_id`: `sgs_9b7cd29937fd4c01b79e329e71a14527`
- `generation_snapshot_json`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/2026-05-10T145708-generation-real/artifacts/generation_snapshot.json`
- `quality_summary_json`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/2026-05-10T145708-generation-real/quality-summary/summary.json`
- `quality_summary_md`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/2026-05-10T145708-generation-real/quality-summary/summary.md`
- `quality_summary_status`: `passed`
- `quality_summary_run_id`: `2026-05-10T145708-generation-real-quality-summary`

## Issues

### SYSTEM_BUG-advance_setting_session `SYSTEM_BUG`

- Severity: `high`
- Stage: `advance_setting_session`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Server error '500 Internal Server Error' for url 'http://127.0.0.1:8000/api/novels/codex-8aea/settings/sessions/sgs_9b7cd29937fd4c01b79e329e71a14527/reply'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage advance_setting_session`
