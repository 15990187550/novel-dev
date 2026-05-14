# Test Run longform-vol1-real-20260512163157

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real`
- Duration: `870.3s`

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
- `source_materials_json`: `[{"filename": "《一世之尊》-+爱潜水的乌贼.txt", "path": "/Users/xuhuibin/Desktop/novel/《一世之尊》-+爱潜水的乌贼.txt", "pending_id": "pe_1ea2e655", "status": "approved", "char_count": 4739301, "byte_count": 14110044}, {"filename": "世界观.md", "path": "/Users/xuhuibin/Desktop/novel/世界观.md", "pending_id": "pe_f8e17135", "status": "approved", "char_count": 3523, "byte_count": 7678}, {"filename": "力量体系.md", "path": "/Users/xuhuibin/Desktop/novel/力量体系.md", "pending_id": "pe_d9a971c4", "status": "approved", "char_count": 6020, "byte_count": 14312}, {"filename": "诸天万界.md", "path": "/Users/xuhuibin/Desktop/novel/诸天万界.md", "pending_id": "pe_1a26b7f5", "status": "approved", "char_count": 8054, "byte_count": 18104}]`
- `novel_id`: `codex-6af4`
- `setting_session_id`: `sgs_2b308a7069c9454c9ef012e8b0228cf7`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `5`
- `review_batch_id`: `112f895c238745e99e8c794330a69cc6`
- `generated_setting_change_count`: `10`
- `generated_setting_approvable_change_count`: `10`
- `generated_setting_conflict_change_count`: `0`
- `generated_setting_approved_change_ids`: `f17abc90c03d4eba8e6dddc299b9d9fc,7be30b964aa248dea84ac222da059c4a,e4d1e2b3d6e248c2b24c0c2fc6a7f4bb,8d8576055c944694a372747e6a7e91a3,d3bbbdf09171402fb6cf2c110d807636,307a65ee909043a695735cacb9c62391,70fc8c8c52e34835b89ab103973d6d22,6cf74418fd1c4be09af89a1e544fad46,cb4f4961c0db443d94d71c8fb2a48d9e,1741ff81f67149308792988ac716b531`
- `generated_setting_batch_status`: `partially_approved`
- `source_material_uploaded_count`: `4`
- `source_material_pending_ids`: `pe_1ea2e655,pe_f8e17135,pe_d9a971c4,pe_1a26b7f5`
- `source_material_approved_count`: `4`
- `setting_consolidation_job_id`: `job_47970e6f8abb`
- `setting_consolidation_batch_id`: `6e32b335ef524ff1a2039603d070cfa6`
- `consolidated_setting_change_count`: `25`
- `consolidated_setting_approvable_change_count`: `16`
- `consolidated_setting_conflict_change_count`: `9`
- `consolidated_setting_approved_change_ids`: `e840e5b2c7d14c20ac3a522ff3271ee9,d1670f9ecc1b472ebe76daffe4ac18b0,32dda5b3f22b46d59e3db49c8efbad6b,457ff0c3e73349a085ed69abb9ad8181,1ea7cb27316643f7b3cfeeece3a2b702,06c534780e064ee2917e633de3f2ed6a,dd65aa4d9ca242c89839d64651e8a35d,5671d3d10c784fe69a14238afb5d9ada,7d0432d6c49548b3b431f317f3d924e6,bd5efc50062d4d6f8cc4639c64aa4e9c,d67f8480db484ffb8a5daa533845b29a,3efc190a6ba1441cbca3ff7fffc66bff,32737a4ff30e4550b08b461a3e6613f7,2d9b9e706d1f4cadabd78fffba93e6c7,73e18e45b9da47f98282ff5a0a41f0be,f9e87e12316a41f1b2f86ff4770d2d9c`
- `consolidated_setting_batch_status`: `pending`
- `generation_snapshot_json`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/longform-vol1-real-20260512163157/artifacts/generation_snapshot.json`
- `quality_summary_json`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/longform-vol1-real-20260512163157/quality-summary/summary.json`
- `quality_summary_md`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/longform-vol1-real-20260512163157/quality-summary/summary.md`
- `quality_summary_status`: `passed`
- `quality_summary_run_id`: `longform-vol1-real-20260512163157-quality-summary`

## Issues

### SYSTEM_BUG-volume_plan `SYSTEM_BUG`

- Severity: `high`
- Stage: `volume_plan`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Client error '400 Bad Request' for url 'http://127.0.0.1:8000/api/novels/codex-6af4/volume_plan'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- Evidence: http_status=400, response_text={"detail":"generate_volume_plan violates setting constraints after repair: 无垠混沌海最高等级修炼体系，核心路径为内天地→外天地→诸天万界→ 缺失必经节点: 超脱"}
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
