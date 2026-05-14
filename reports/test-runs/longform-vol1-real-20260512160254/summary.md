# Test Run longform-vol1-real-20260512160254

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `external_blocked`
- Dataset: `minimal_builtin`
- LLM mode: `real`
- Duration: `0.6s`

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
- `novel_id`: `codex-a3e8`
- `setting_session_id`: `sgs_cafd94e0b05342d6af1b43b344528182`
- `quality_summary_status`: `skipped_external_blocker`

## Issues

### EXTERNAL_BLOCKED-advance_setting_session `EXTERNAL_BLOCKED`

- Severity: `high`
- Stage: `advance_setting_session`
- External blocker: `True`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Server error '502 Bad Gateway' for url 'http://127.0.0.1:8000/api/novels/codex-a3e8/settings/sessions/sgs_cafd94e0b05342d6af1b43b344528182/reply'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/502
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --acceptance-scope real-longform-volume1 --stage advance_setting_session`
