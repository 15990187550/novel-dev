# Test Run 2026-06-20T123655-generation-real

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `external_blocked`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `0.1s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `novel_id`: `codex-0118`
- `genre_template_summary`: `{"genre": "通用 / 未分类", "template_layers": 1, "template_warnings": [], "template_evidence_available": true}`
- `setting_session_id`: `sgs_8a7ba9b74d5b4024beb32c4e3fbdc2b4`
- `quality_summary_status`: `skipped_external_blocker`

## Issues

### EXTERNAL_BLOCKED-advance_setting_session `EXTERNAL_BLOCKED`

- Severity: `high`
- Stage: `advance_setting_session`
- External blocker: `True`
- Real LLM: `True`
- Fake rerun status: `passed`
- Message: Server error '502 Bad Gateway' for url 'http://127.0.0.1:8000/api/novels/codex-0118/settings/sessions/sgs_8a7ba9b74d5b4024beb32c4e3fbdc2b4/reply'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/502
- Evidence: http_status=502, response_text={"detail":"AI 模型配置或认证失败：Missing API key environment variable: DEEPSEEK_API_KEY"}
- Reproduce: `scripts/verify_generation_real.sh --stage advance_setting_session`
