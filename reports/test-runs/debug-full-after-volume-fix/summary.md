# Test Run debug-full-after-volume-fix

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `698.1s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `novel_id`: `codex-78e4`
- `setting_session_id`: `sgs_71b0739158d14fb19fc332672f0b1a6a`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `1`
- `review_batch_id`: `e2634d61105a40f3aea39877781d54f6`
- `pending_id`: `pe_9a34337a`
- `brainstorm_original_estimated_volumes`: `5`
- `brainstorm_original_estimated_total_chapters`: `180`
- `brainstorm_shrunk_estimated_total_chapters`: `1`
- `generation_snapshot_json`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/debug-full-after-volume-fix/artifacts/generation_snapshot.json`
- `quality_summary_json`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/debug-full-after-volume-fix/quality-summary/summary.json`
- `quality_summary_md`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/debug-full-after-volume-fix/quality-summary/summary.md`
- `quality_summary_status`: `passed`
- `quality_summary_run_id`: `debug-full-after-volume-fix-quality-summary`

## Issues

### SYSTEM_BUG-volume_plan `SYSTEM_BUG`

- Severity: `high`
- Stage: `volume_plan`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Client error '400 Bad Request' for url 'http://127.0.0.1:8000/api/novels/codex-78e4/volume_plan'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage volume_plan`
