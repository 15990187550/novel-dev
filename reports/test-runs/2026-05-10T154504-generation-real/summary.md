# Test Run 2026-05-10T154504-generation-real

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `319.4s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `novel_id`: `codex-194a`
- `setting_session_id`: `sgs_0c8f0f58276544b89cfac54a3714a24d`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `2`
- `review_batch_id`: `8913addf4ed745388792d3b26d3899a9`
- `pending_id`: `pe_b999a8e0`
- `brainstorm_original_estimated_volumes`: `4`
- `brainstorm_original_estimated_total_chapters`: `120`
- `brainstorm_shrunk_estimated_total_chapters`: `1`
- `volume_id`: `vol_001`
- `chapter_id`: `acceptance-codex-194a-ch1`
- `chapter_plan_source`: `current_chapter_plan`
- `chapter_target_word_count`: `1000`
- `chapter_auto_run_job_id`: `job_13f8f97c6c0b`
- `generation_snapshot_json`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/2026-05-10T154504-generation-real/artifacts/generation_snapshot.json`
- `quality_summary_json`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/2026-05-10T154504-generation-real/quality-summary/summary.json`
- `quality_summary_md`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/2026-05-10T154504-generation-real/quality-summary/summary.md`
- `quality_summary_status`: `passed`
- `quality_summary_run_id`: `2026-05-10T154504-generation-real-quality-summary`

## Issues

### SYSTEM_BUG-auto_run_chapters `SYSTEM_BUG`

- Severity: `high`
- Stage: `auto_run_chapters`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Writer beat structure guard failed
- Evidence: job_id=job_13f8f97c6c0b, status=failed, error_message=Writer beat structure guard failed, result_payload.stopped_reason=failed, result_payload.failed_phase=drafting, result_payload.failed_chapter_id=acceptance-codex-194a-ch1, result_payload.current_phase=drafting, result_payload.current_chapter_id=acceptance-codex-194a-ch1, result_payload.error=Writer beat structure guard failed, chapter_structure_guard={"beat_index": 1, "changed_event_order": true, "completed_current_beat": true, "introduced_plan_external_fact": true, "issues": ["当前节拍正文引入了计划外人物'张横'并赋予其具体姓名和互动戏份，章节计划仅提及'外门同门'和'外门弟子'作为群体存在，未指定具体人物姓名。", "当前节拍正文新增了计划外情节：林照对张横说'我赌你，一招都撑不过'的挑衅台词，以及与张横的个性化冲突。章节计划中仅提及'外门同门依旧对他冷嘲热讽，甚至克扣他的口粮，他咬牙隐忍'，未包含具体挑衅回怼或个体冲突升级。", "当前节拍正文引入了计划外人物'执法长老'并新增了与林家'叛宗'案的关联背景（'三年前林家叛宗案，正是他签的缉拿令'），这是新增的计划外事实和背景设定。章节计划中未提及此人物或此背景。", "当前节拍正文新增计划外悬念：'柴房另一侧，脚步声停了一瞬...那脚步声轻得不似寻常外门弟子'，这是新增的跟踪/监视线索，超出章节计划设定的结尾危险信号范围。", "当前节拍正文改变了事件顺序：在章节计划中，'外门大比抽签结果公布'后应直接结束，但正文在抽签后加入了挑衅张横、柴房看残卷、被神秘人跟踪等多个额外事件，扩展了节拍范围。"], "mode": "writer_retry", "passed": false, "premature_future_beat": false, "suggested_rewrite_focus": "删除具体命名的外门弟子'张横'，将同门互动改为群体性的冷嘲热讽和口粮克扣；删除林照回怼挑衅的台词；删除'执法长老'这一新增人物及其与林家叛宗案的背景设定；删除柴房被神秘跟踪者的情节；将结尾危险信号简化为抽签后的群体嘲讽和残卷运转异常，聚焦于'隐忍中积蓄暗力'的核心情绪。"}, writer_guard_failures_count=2, writer_guard_last_failure={"beat_index": 1, "changed_event_order": true, "completed_current_beat": true, "introduced_plan_external_fact": true, "issues": ["当前节拍正文引入了计划外人物'张横'并赋予其具体姓名和互动戏份，章节计划仅提及'外门同门'和'外门弟子'作为群体存在，未指定具体人物姓名。", "当前节拍正文新增了计划外情节：林照对张横说'我赌你，一招都撑不过'的挑衅台词，以及与张横的个性化冲突。章节计划中仅提及'外门同门依旧对他冷嘲热讽，甚至克扣他的口粮，他咬牙隐忍'，未包含具体挑衅回怼或个体冲突升级。", "当前节拍正文引入了计划外人物'执法长老'并新增了与林家'叛宗'案的关联背景（'三年前林家叛宗案，正是他签的缉拿令'），这是新增的计划外事实和背景设定。章节计划中未提及此人物或此背景。", "当前节拍正文新增计划外悬念：'柴房另一侧，脚步声停了一瞬...那脚步声轻得不似寻常外门弟子'，这是新增的跟踪/监视线索，超出章节计划设定的结尾危险信号范围。", "当前节拍正文改变了事件顺序：在章节计划中，'外门大比抽签结果公布'后应直接结束，但正文在抽签后加入了挑衅张横、柴房看残卷、被神秘人跟踪等多个额外事件，扩展了节拍范围。"], "mode": "writer_retry", "passed": false, "premature_future_beat": false, "suggested_rewrite_focus": "删除具体命名的外门弟子'张横'，将同门互动改为群体性的冷嘲热讽和口粮克扣；删除林照回怼挑衅的台词；删除'执法长老'这一新增人物及其与林家叛宗案的背景设定；删除柴房被神秘跟踪者的情节；将结尾危险信号简化为抽签后的群体嘲讽和残卷运转异常，聚焦于'隐忍中积蓄暗力'的核心情绪。"}
- Reproduce: `scripts/verify_generation_real.sh --stage auto_run_chapters`
