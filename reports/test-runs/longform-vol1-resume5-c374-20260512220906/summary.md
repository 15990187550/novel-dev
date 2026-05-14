# Test Run longform-vol1-resume5-c374-20260512220906

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `1118.1s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-longform-volume1`
- `acceptance_scope`: `real-longform-volume1`
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
- `novel_id`: `codex-c374`
- `resume_current_phase`: `context_preparation`
- `volume_id`: `vol_1`
- `chapter_id`: `vol_1_ch_6`
- `resume_reset_chapter_id`: `vol_1_ch_6`
- `create_novel_status`: `skipped_for_resume`
- `create_setting_session_status`: `skipped_for_resume`
- `advance_setting_session_status`: `skipped_for_resume`
- `generate_setting_review_batch_status`: `skipped_for_resume`
- `apply_generated_settings_status`: `skipped_for_resume`
- `upload_source_materials_status`: `skipped_for_resume`
- `approve_source_materials_status`: `skipped_for_resume`
- `consolidate_settings_status`: `skipped_for_resume`
- `apply_consolidated_settings_status`: `skipped_for_resume`
- `brainstorm_status`: `skipped_for_resume`
- `volume_plan_status`: `skipped_for_resume`
- `chapter_auto_run_job_id`: `job_f6b5df43343f`
- `generation_snapshot_json`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/longform-vol1-resume5-c374-20260512220906/artifacts/generation_snapshot.json`
- `quality_summary_json`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/longform-vol1-resume5-c374-20260512220906/quality-summary/summary.json`
- `quality_summary_md`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/longform-vol1-resume5-c374-20260512220906/quality-summary/summary.md`
- `quality_summary_status`: `passed`
- `quality_summary_run_id`: `longform-vol1-resume5-c374-20260512220906-quality-summary`

## Issues

### SYSTEM_BUG-auto_run_chapters `SYSTEM_BUG`

- Severity: `high`
- Stage: `auto_run_chapters`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: All connection attempts failed
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --acceptance-scope real-longform-volume1 --stage auto_run_chapters`

### SYSTEM_BUG-export_contract `SYSTEM_BUG`

- Severity: `high`
- Stage: `export_contract`
- External blocker: `False`
- Real LLM: `False`
- Fake rerun status: `None`
- Message: Exported novel file missing: exported_path not returned
- Evidence: archived_chapter_count=0
- Reproduce: `scripts/verify_generation_real.sh --acceptance-scope real-longform-volume1 --stage export`
