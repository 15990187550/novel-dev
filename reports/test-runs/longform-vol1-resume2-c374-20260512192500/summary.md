# Test Run longform-vol1-resume2-c374-20260512192500

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real`
- Duration: `1582.1s`

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
- `novel_id`: `codex-c374`
- `resume_current_phase`: `context_preparation`
- `volume_id`: `vol_1`
- `chapter_id`: `vol_1_ch_4`
- `resume_reset_chapter_id`: `vol_1_ch_4`
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
- `chapter_auto_run_job_id`: `job_374bec974e8d`
- `generation_snapshot_json`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/longform-vol1-resume2-c374-20260512192500/artifacts/generation_snapshot.json`
- `quality_summary_json`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/longform-vol1-resume2-c374-20260512192500/quality-summary/summary.json`
- `quality_summary_md`: `/Users/xuhuibin/Documents/popo/Modules/novel-dev/reports/test-runs/longform-vol1-resume2-c374-20260512192500/quality-summary/summary.md`
- `quality_summary_status`: `passed`
- `quality_summary_run_id`: `longform-vol1-resume2-c374-20260512192500-quality-summary`

## Issues

### SYSTEM_BUG-auto_run_chapters `SYSTEM_BUG`

- Severity: `high`
- Stage: `auto_run_chapters`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: generation job cancelled
- Evidence: job_id=job_374bec974e8d, status=cancelled, result_payload.stopped_reason=flow_cancelled, result_payload.current_phase=drafting, result_payload.current_chapter_id=vol_1_ch_5, chapter_structure_guard={"beat_index": 2, "changed_event_order": false, "completed_current_beat": false, "introduced_plan_external_fact": true, "issues": ["润色后新增了'淡金纹路一闪'和'界面边缘像被火燎过的纸角，蜷曲一瞬'这一情节——道经与系统界面发生直接交互/对抗，这在原稿中不存在。原稿仅描述界面卡顿后恢复正常，没有道经对界面造成物理/视觉损伤的描写。", "润色后新增了'窗外虫鸣骤歇'和'枝叶断裂声极轻，从厢房左侧移到了正前方'这一外部威胁升级情节，暗示有实体正在靠近监视，这在原稿中没有。原稿结尾仅有界面卡顿和陆照的内心警觉，没有外部环境的危险信号升级。", "润色后新增了'丹田里汞浆仍在盘结，速度比先前慢了一半，像在等什么'这一状态变化，暗示道经运转受系统影响而改变速度，这在原稿中不存在。", "润色后删减了祖父训话的关键内容'不牢，终成空中楼阁。风一吹，人连楼一起塌'，改为仅保留'根基'二字，削弱了祖训的完整性和因果逻辑。", "润色后改变了事件细节：原稿中陆照'后槽牙咬紧'，润色后改为'右手缓缓收回，重新压到枕下'，且新增'玉佩焦痕硌着指腹，比先前更深三分'——'更深三分'是新增的身体感受细节。"], "mode": "editor", "passed": false, "polished_chars": 877, "premature_future_beat": false, "source_chars": 729, "suggested_rewrite_focus": "删除道经与系统界面的直接交互描写（淡金纹路、界面边缘蜷曲），删除外部环境威胁升级（虫鸣骤歇、枝叶断裂声、人影移动），恢复祖父训话的完整内容，删除'汞浆速度比先前慢了一半'的新增状态。保持原稿中界面卡顿后恢复正常、陆照内心警觉即可。"}, writer_guard_failures_count=2, writer_guard_last_failure={"beat_index": 0, "changed_event_order": false, "completed_current_beat": false, "introduced_plan_external_fact": true, "issues": ["当前节拍是beat 0，核心事件应为陆照修炼道经第一层心法、眉心祖窍微光明灭。但正文在beat 0中提前引入了beat 1和beat 2的核心元素：签到系统界面弹出、系统与道经互斥、系统卡顿等，这些属于后续节拍内容。", "正文中陆照面临'继续追查与保全自身'的选择，这虽然是章节计划中每个beat都提到的元素，但正文将其表现为系统与道经的冲突，提前揭示了beat 2才应出现的'道经与系统互斥'主题。", "新增计划外事实：'玉佩焦痕与残页纹路的关联'、'赵执事的眼线'、'感应法器'、'暴露坐标'等，这些在章节计划中均未提及，属于新增线索和因果。", "新增计划外事实：'残茶表面油光凝成纹路'与道经墨迹相似，这是新增的伏笔/线索。", "新增计划外事实：纸窗上直立如人的影子、梆子声近了半条街，这构成了提前的追兵到达/危险信号，而beat 0的结尾应只保留'新的危险信号'，但这里已经让外部威胁实体化（影子出现、追兵逼近），超出了beat 0应有的范围。", "事件顺序问题：beat 0应专注道经修炼的专注与惊奇，但正文让陆照在修炼过程中提前做出'以保全为主'的选择并撤回真气，这压缩了后续beats中'双法并行'和'抉择'的空间。"], "mode": "writer", "passed": false, "premature_future_beat": true, "suggested_rewrite_focus": "将beat 0聚焦于陆照修炼道经第一层的过程：经文自行运转、真气沿陌生经脉推进、速度缓慢但凝实、眉心祖窍微光明灭。保持'专注、惊奇'的情绪基调。移除签到系统的任何出场（包括界面弹出、卡顿、互斥感）。移除'追查vs保全'的抉择场景和外部威胁（影子、梆子声逼近）。移除玉佩、赵执事、感应法器等计划外元素。结尾可保留轻微的不安信号（如灯焰偏移、窗外异响），但不应让威胁实体化。"}, editor_guard_warnings_count=2
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
