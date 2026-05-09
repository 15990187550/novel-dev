# Test Run debug-full-after-context-fix

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `0.2s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `novel_id`: `codex-684f`
- `setting_session_id`: `sgs_f640cdd7fa0c44b29a5dd92b9d98dd7a`
- `generation_snapshot_json`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/debug-full-after-context-fix/artifacts/generation_snapshot.json`
- `quality_summary_json`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/debug-full-after-context-fix/quality-summary/summary.json`
- `quality_summary_md`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/debug-full-after-context-fix/quality-summary/summary.md`
- `quality_summary_status`: `passed`
- `quality_summary_run_id`: `debug-full-after-context-fix-quality-summary`

## Issues

### SYSTEM_BUG-advance_setting_session `SYSTEM_BUG`

- Severity: `high`
- Stage: `advance_setting_session`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Server error '500 Internal Server Error' for url 'http://127.0.0.1:8000/api/novels/codex-684f/settings/sessions/sgs_f640cdd7fa0c44b29a5dd92b9d98dd7a/reply'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage advance_setting_session`
