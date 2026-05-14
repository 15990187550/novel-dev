# Test Run longform-vol1-real-20260512154156

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real`
- Duration: `1.2s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-longform-volume1`
- `acceptance_scope`: `real-longform-volume1`
- `target_volumes`: `18`
- `target_chapters`: `1200`
- `target_word_count`: `2000000`
- `target_volume_number`: `1`
- `target_volume_chapters`: `67`
- `chapter_target_word_count`: `1667`
- `target_volume_word_count`: `111689`
- `source_dir`: `/Users/xuhuibin/Desktop/novel`
- `source_material_count`: `4`
- `source_material_char_count`: `4756898`
- `source_material_byte_count`: `14150138`
- `source_materials_json`: `[{"filename": "《一世之尊》-+爱潜水的乌贼.txt", "path": "/Users/xuhuibin/Desktop/novel/《一世之尊》-+爱潜水的乌贼.txt", "status": "discovered", "char_count": 4739301, "byte_count": 14110044}, {"filename": "世界观.md", "path": "/Users/xuhuibin/Desktop/novel/世界观.md", "status": "discovered", "char_count": 3523, "byte_count": 7678}, {"filename": "力量体系.md", "path": "/Users/xuhuibin/Desktop/novel/力量体系.md", "status": "discovered", "char_count": 6020, "byte_count": 14312}, {"filename": "诸天万界.md", "path": "/Users/xuhuibin/Desktop/novel/诸天万界.md", "status": "discovered", "char_count": 8054, "byte_count": 18104}]`
- `novel_id`: `codex-ca46`
- `setting_session_id`: `sgs_7cafacd38a06439e9f4e2ec29da74c9d`
- `generation_snapshot_json`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/longform-vol1-real-20260512154156/artifacts/generation_snapshot.json`
- `quality_summary_json`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/longform-vol1-real-20260512154156/quality-summary/summary.json`
- `quality_summary_md`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/longform-vol1-real-20260512154156/quality-summary/summary.md`
- `quality_summary_status`: `failed`
- `quality_summary_run_id`: `longform-vol1-real-20260512154156-quality-summary`

## Issues

### SYSTEM_BUG-advance_setting_session `SYSTEM_BUG`

- Severity: `high`
- Stage: `advance_setting_session`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Server error '500 Internal Server Error' for url 'http://127.0.0.1:8000/api/novels/codex-ca46/settings/sessions/sgs_7cafacd38a06439e9f4e2ec29da74c9d/reply'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --acceptance-scope real-longform-volume1 --stage advance_setting_session`

### SYSTEM_BUG-export_contract `SYSTEM_BUG`

- Severity: `high`
- Stage: `export_contract`
- External blocker: `False`
- Real LLM: `False`
- Fake rerun status: `None`
- Message: Exported novel file missing: exported_path not returned
- Evidence: archived_chapter_count=0
- Reproduce: `scripts/verify_generation_real.sh --acceptance-scope real-longform-volume1 --stage export`

### SYNOPSIS-QUALITY-001 `GENERATION_QUALITY`

- Severity: `high`
- Stage: `brainstorm`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: 总纲质量门禁未通过。
- Evidence: passed=False, structure_score=60, marketability_score=60, conflict_score=45, character_arc_score=60, writability_score=45, blocking_issues[0]=总纲缺少具体对抗关系，需要写清谁与谁为了什么发生冲突。, warning_issues[0]=主要人物弧光转折不足，正文容易缺少人物选择。, warning_issues[1]=总纲可识别结构转折不足 4 个，当前识别到 0 个。, warning_issues[2]=缺少卷级承诺，卷纲生成时容易偏题。, repair_suggestions[0]=将 core_conflict 改成『主角 vs 具体阻力，为争夺具体目标』。, repair_suggestions[1]=为主角和关键对手补齐至少 3 个会改变关系或信念的转折点。
- Reproduce: `novel-dev-testing quality-summary --input-json <snapshot.json>`
