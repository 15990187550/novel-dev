# Test Run phase6-smoke-20260620-rerun2

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `71.3s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-longform-volume1`
- `acceptance_scope`: `real-longform-volume1`
- `target_stage`: `upload_source_materials`
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
- `source_materials_json`: `[{"filename": "世界观.md", "path": "/private/tmp/phase6-smoke-source/世界观.md", "status": "discovered", "char_count": 325, "byte_count": 831}, {"filename": "力量体系.md", "path": "/private/tmp/phase6-smoke-source/力量体系.md", "status": "discovered", "char_count": 308, "byte_count": 732}, {"filename": "道照诸天_brief.md", "path": "/private/tmp/phase6-smoke-source/道照诸天_brief.md", "status": "discovered", "char_count": 305, "byte_count": 692}, {"filename": "金手指设计.md", "path": "/private/tmp/phase6-smoke-source/金手指设计.md", "status": "discovered", "char_count": 402, "byte_count": 910}]`
- `novel_id`: `novel-c16e`
- `genre_template_summary`: `{"genre": "玄幻 / 诸天文", "template_layers": 3, "template_warnings": [], "template_evidence_available": true}`
- `source_material_uploaded_count`: `4`
- `source_material_pending_ids`: `pe_b18563fc,pe_97f15dba,pe_245e6bb2,pe_8543331f`
- `stopped_at_stage`: `upload_source_materials`
- `generation_snapshot_json`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/phase6-smoke-20260620-rerun2/artifacts/generation_snapshot.json`

## Issues

### SYSTEM_BUG-export_contract `SYSTEM_BUG`

- Severity: `high`
- Stage: `export_contract`
- External blocker: `False`
- Real LLM: `False`
- Fake rerun status: `None`
- Message: Exported novel file missing: exported_path not returned
- Evidence: archived_chapter_count=0
- Reproduce: `scripts/verify_generation_real.sh --acceptance-scope real-longform-volume1 --stage export`

### SYSTEM_BUG-quality_summary `SYSTEM_BUG`

- Severity: `high`
- Stage: `quality_summary`
- External blocker: `False`
- Real LLM: `False`
- Fake rerun status: `None`
- Message: Missing required key quality_thresholds.publishable_final_review_score in llm_config.yaml
- Evidence: none
- Reproduce: `scripts/verify_generation_real.sh --acceptance-scope real-longform-volume1`
