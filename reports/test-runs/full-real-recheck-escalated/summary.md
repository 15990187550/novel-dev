# Test Run full-real-recheck-escalated

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `784.5s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `acceptance_scope`: `settings_brainstorm_volume_export`
- `novel_id`: `codex-f88e`
- `setting_session_id`: `sgs_3f3c478c81544e68b33aa0d08ad1d553`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `1`
- `review_batch_id`: `cebbe398c4d44a448e9fdc5f62e2d19e`
- `pending_id`: `pe_12f3ea9f`
- `volume_id`: `vol-1-qingyunjin`
- `exported_path`: `./novel_output/codex-f88e/novel.md`

## Issues

### SYSTEM_BUG-export `SYSTEM_BUG`

- Severity: `high`
- Stage: `export`
- External blocker: `False`
- Real LLM: `False`
- Fake rerun status: `None`
- Message: Exported novel file is empty: ./novel_output/codex-f88e/novel.md
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --stage export`
