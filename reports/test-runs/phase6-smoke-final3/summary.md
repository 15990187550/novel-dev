# Test Run phase6-smoke-final3

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `1118.3s`

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
- `source_materials_json`: `[{"filename": "世界观.md", "path": "/private/tmp/phase6-smoke-source/世界观.md", "pending_id": "pe_e6ebfe38", "status": "approved", "char_count": 325, "byte_count": 831}, {"filename": "力量体系.md", "path": "/private/tmp/phase6-smoke-source/力量体系.md", "pending_id": "pe_f4f7869b", "status": "approved", "char_count": 308, "byte_count": 732}, {"filename": "道照诸天_brief.md", "path": "/private/tmp/phase6-smoke-source/道照诸天_brief.md", "pending_id": "pe_add8a1e5", "status": "approved", "char_count": 305, "byte_count": 692}, {"filename": "金手指设计.md", "path": "/private/tmp/phase6-smoke-source/金手指设计.md", "pending_id": "pe_1056c062", "status": "approved", "char_count": 402, "byte_count": 910}]`
- `novel_id`: `novel-8299`
- `genre_template_summary`: `{"genre": "玄幻 / 诸天文", "template_layers": 3, "template_warnings": [], "template_evidence_available": true}`
- `source_material_uploaded_count`: `4`
- `source_material_pending_ids`: `pe_e6ebfe38,pe_f4f7869b,pe_add8a1e5,pe_1056c062`
- `source_material_approved_count`: `4`
- `setting_session_id`: `sgs_a6b5a08920234e2b8869ee019f9beb09`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `5`
- `review_batch_id`: `ed7503f6b6ca41098f2de3b943241869`
- `generated_setting_change_count`: `3`
- `generated_setting_approvable_change_count`: `3`
- `generated_setting_conflict_change_count`: `0`
- `generated_setting_rejected_conflict_change_count`: `0`
- `generated_setting_approved_change_ids`: `5c8fadca0cc648229330d91d6da3a832,b8be2710f9874ad186d5b94d0fbf4aee,9a247da317f04c3ebc3433fd8f8aea46`
- `generated_setting_batch_status`: `approved`
- `setting_consolidation_job_id`: `job_9d3681431fb4`
- `setting_consolidation_batch_id`: `65646e2122ae47fb85f9c8d0d60e6d35`
- `consolidated_setting_change_count`: `0`
- `consolidated_setting_approvable_change_count`: `0`
- `consolidated_setting_conflict_change_count`: `0`
- `consolidated_setting_rejected_conflict_change_count`: `0`
- `consolidated_setting_batch_status`: `pending`
- `generation_snapshot_json`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/phase6-smoke-final3/artifacts/generation_snapshot.json`
- `quality_summary_json`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/phase6-smoke-final3/quality-summary/summary.json`
- `quality_summary_md`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/phase6-smoke-final3/quality-summary/summary.md`
- `quality_summary_status`: `passed`
- `quality_summary_run_id`: `phase6-smoke-final3-quality-summary`

## Issues

### SYSTEM_BUG-volume_plan `SYSTEM_BUG`

- Severity: `high`
- Stage: `volume_plan`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Client error '400 Bad Request' for url 'http://127.0.0.1:8000/api/novels/novel-8299/volume_plan'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- Evidence: http_status=400, response_text={"detail":"generate_volume_plan semantic conflicts remain after repair: 第12章陈渊'临阵反杀大弟子一击'与卷级总览/核心冲突中'陈渊顾忌玉佩一旦在圣地眼前显化将招来灭门之祸、选择隐镜逃亡'产生直接矛盾——设定明确陈渊并未当场反杀大弟子，而是放弃暴露观天镜以保全玉佩。卷纲既写'反杀一击'又写'不暴露观天镜'，且ch11-12将反杀作为既成事实描写，违反hard/fact卷级总览与第一幕高潮设定。</item>"}
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
