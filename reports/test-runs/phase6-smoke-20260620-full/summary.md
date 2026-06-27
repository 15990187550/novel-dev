# Test Run phase6-smoke-20260620-full

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `1356.9s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-longform-volume1`
- `acceptance_scope`: `real-longform-volume1`
- `target_volumes`: `18`
- `target_chapters`: `1200`
- `target_word_count`: `2000000`
- `target_volume_number`: `1`
- `target_volume_chapters`: `67`
- `run_chapter_limit`: `67`
- `chapter_target_word_count`: `1667`
- `target_volume_word_count`: `111689`
- `source_dir`: `/private/tmp/phase6-smoke-source`
- `source_material_count`: `4`
- `source_material_char_count`: `1340`
- `source_material_byte_count`: `3165`
- `source_materials_json`: `[{"filename": "世界观.md", "path": "/private/tmp/phase6-smoke-source/世界观.md", "pending_id": "pe_e762c6c6", "status": "approved", "char_count": 325, "byte_count": 831}, {"filename": "力量体系.md", "path": "/private/tmp/phase6-smoke-source/力量体系.md", "pending_id": "pe_eab2d29e", "status": "approved", "char_count": 308, "byte_count": 732}, {"filename": "道照诸天_brief.md", "path": "/private/tmp/phase6-smoke-source/道照诸天_brief.md", "pending_id": "pe_467427a1", "status": "approved", "char_count": 305, "byte_count": 692}, {"filename": "金手指设计.md", "path": "/private/tmp/phase6-smoke-source/金手指设计.md", "pending_id": "pe_9310ae6a", "status": "approved", "char_count": 402, "byte_count": 910}]`
- `novel_id`: `novel-6f36`
- `genre_template_summary`: `{"genre": "玄幻 / 诸天文", "template_layers": 3, "template_warnings": [], "template_evidence_available": true}`
- `source_material_uploaded_count`: `4`
- `source_material_pending_ids`: `pe_e762c6c6,pe_eab2d29e,pe_467427a1,pe_9310ae6a`
- `source_material_approved_count`: `4`
- `setting_session_id`: `sgs_90fc79ea999248968d4d377339e1af33`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `5`
- `review_batch_id`: `7793be8cb514498b891d08241bbcd099`
- `generated_setting_change_count`: `11`
- `generated_setting_approvable_change_count`: `11`
- `generated_setting_conflict_change_count`: `0`
- `generated_setting_rejected_conflict_change_count`: `0`
- `generated_setting_approved_change_ids`: `5075837ae373435aafb06cba634c30eb,e10bd3476d44498f959cd441df69cf20,8b6b9092654d4662a7aa38643bc6fdc1,ffca9446105846e69f3109f5e77e0761,95c59e8c76894f89bada95bba157daeb,a089d2f6cf024bf0aa703b7b1c6ea1d5,3a771e7659dd46e9955660fa861de8af,cf53dc233fdd476285b45130ef541032,c28f7747e7874625ac26d70ca1ea995f,8f7b9e36503d4cf2bcb6030f51a42ce2,2741b8692de9407b92a465c5798cc26b`
- `generated_setting_batch_status`: `approved`
- `setting_consolidation_job_id`: `job_cfae788f70f4`
- `setting_consolidation_batch_id`: `190210ac5620406295e21dedefc9ada2`
- `consolidated_setting_change_count`: `12`
- `consolidated_setting_approvable_change_count`: `5`
- `consolidated_setting_conflict_change_count`: `7`
- `consolidated_setting_rejected_conflict_change_count`: `7`
- `consolidated_setting_approved_change_ids`: `9291aa29cf614567b1e44f8b723fe1b9,2a8b035c3d8f4227bacdd9e6375821d2,defc0b6cdb2040c281994e9c3270e3f8,431cda73a3ab44c5804d1c7884af14a6,c969060eeb2b4031badec6d1d70000d5`
- `consolidated_setting_batch_status`: `partially_approved`
- `generation_snapshot_json`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/phase6-smoke-20260620-full/artifacts/generation_snapshot.json`
- `quality_summary_json`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/phase6-smoke-20260620-full/quality-summary/summary.json`
- `quality_summary_md`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/phase6-smoke-20260620-full/quality-summary/summary.md`
- `quality_summary_status`: `failed`
- `quality_summary_run_id`: `phase6-smoke-20260620-full-quality-summary`

## Issues

### SYSTEM_BUG-volume_plan `SYSTEM_BUG`

- Severity: `high`
- Stage: `volume_plan`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Client error '400 Bad Request' for url 'http://127.0.0.1:8000/api/novels/novel-6f36/volume_plan'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- Evidence: http_status=400, response_text={"detail":"Setting review is not complete: setting_review_batch:190210ac5620406295e21dedefc9ada2:status=partially_approved:source_type=consolidation:change:2a8b035c3d8f4227bacdd9e6375821d2:target_type=document:change_status=failed; setting_review_batch:190210ac5620406295e21dedefc9ada2:status=partially_approved:source_type=consolidation:change:defc0b6cdb2040c281994e9c3270e3f8:target_type=document:change_status=failed; setting_review_batch:190210ac5620406295e21dedefc9ada2:status=partially_approved:source_type=consolidation:change:431cda73a3ab44c5804d1c7884af14a6:target_type=document:change_status=failed; setting_review_batch:190210ac5620406295e21dedefc9ada2:status=partially_approved:source_type=consolidation:change:c969060eeb2b4031badec6d1d70000d5:target_type=pending_review:change_status=fai...
- Reproduce: `scripts/verify_generation_real.sh --acceptance-scope real-longform-volume1 --stage volume_plan`

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
- Evidence: passed=False, structure_score=60, marketability_score=85, conflict_score=85, character_arc_score=85, writability_score=85, warning_issues[0]=总纲可识别结构转折不足 4 个，当前识别到 3 个。, repair_suggestions[0]=补充会改变主角处境、关系、目标、风险等级或关键信息掌握状态的转折。
- Reproduce: `novel-dev-testing quality-summary --input-json <snapshot.json>`
