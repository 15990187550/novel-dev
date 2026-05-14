# Test Run longform-vol1-resume-c374-20260512182100

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real`
- Duration: `0.2s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-longform-volume1`
- `acceptance_scope`: `real-longform-volume1`
- `target_stage`: `auto_run_chapters`
- `resume_novel_id`: `codex-c374`
- `resume_from_stage`: `auto_run_chapters`
- `resume_reset_current_chapter`: `true`
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

## Issues

### SYSTEM_BUG-api_smoke_flow `SYSTEM_BUG`

- Severity: `high`
- Stage: `api_smoke_flow`
- External blocker: `False`
- Real LLM: `False`
- Fake rerun status: `None`
- Message: 'setting_session_id'
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --acceptance-scope real-longform-volume1`
