# Test Run 2026-05-10T153500-generation-real

- Entrypoint: `scripts/verify_generation_real.sh`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `531.7s`

## Artifacts

- `fixture_title`: `Codex 最小生成验收`
- `contract_scope`: `real-contract`
- `acceptance_scope`: `real-contract`
- `novel_id`: `codex-90c0`
- `setting_session_id`: `sgs_03c3dfb2906f4838817c9b86d71b6d29`
- `setting_session_status`: `ready_to_generate`
- `setting_clarification_round`: `4`
- `review_batch_id`: `ca2769b7d3f54db7a3e3f73f364f03f1`
- `pending_id`: `pe_afb093b0`
- `brainstorm_original_estimated_volumes`: `4`
- `brainstorm_original_estimated_total_chapters`: `128`
- `brainstorm_shrunk_estimated_total_chapters`: `1`
- `volume_id`: `vol_001`
- `chapter_id`: `acceptance-codex-90c0-ch1`
- `chapter_plan_source`: `current_chapter_plan`
- `chapter_target_word_count`: `1000`
- `chapter_auto_run_job_id`: `job_af29b1f519d7`
- `chapter_job_stopped_reason`: `quality_blocked`
- `chapter_text_status`: `polished_text`
- `chapter_text_length`: `1330`
- `quality_status`: `block`
- `quality_reasons`: `blocking_items,status,summary,warning_items`
- `archived_chapter_count`: `0`
- `generation_snapshot_json`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/2026-05-10T153500-generation-real/artifacts/generation_snapshot.json`
- `quality_summary_json`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/2026-05-10T153500-generation-real/quality-summary/summary.json`
- `quality_summary_md`: `/Users/linlin/Desktop/novel-dev/reports/test-runs/2026-05-10T153500-generation-real/quality-summary/summary.md`
- `quality_summary_status`: `failed`
- `quality_summary_run_id`: `2026-05-10T153500-generation-real-quality-summary`

## Issues

### GENERATION_QUALITY-quality_gate `GENERATION_QUALITY`

- Severity: `high`
- Stage: `quality_gate`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: Chapter generated text but quality gate blocked archival
- Evidence: chapter_id=acceptance-codex-90c0-ch1, job_id=job_af29b1f519d7, chapter_job_stopped_reason=quality_blocked, archived_chapter_count=0, quality_status=block, quality_reasons=blocking_items,status,summary,warning_items
- Reproduce: `scripts/verify_generation_real.sh --stage auto_run_chapters`

### CHAPTER-QUALITY-001 `GENERATION_QUALITY`

- Severity: `high`
- Stage: `chapter_final_review`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: 章节质量门禁阻断或成稿评分过低。
- Evidence: chapter_id=acceptance-codex-90c0-ch1, quality_status=block, final_review_score=78, status=block, blocking_items[0]={'code': 'text_integrity', 'message': '正文包含孤立标点段落，疑似节拍拼接或生成清洗异常', 'detail': {'paragraph': '。'}}, warning_items[0]={'code': 'required_payoff', 'message': '章节计划要求的线索或章末钩子未充分兑现', 'detail': {'missing': ['林照必须在继续追查与保全自身之间做出选择，阻力当场升级，失败代价是失去关键线索并暴露处境，结尾留下新的危险信号']}}, summary=存在阻断级质量问题，停止归档和世界状态入库。
- Reproduce: `novel-dev-testing quality-summary --input-json <snapshot.json>`
