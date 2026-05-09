# Test Run debug-full-escalated-quality-summary

- Entrypoint: `novel-dev-testing quality-summary`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `0.0s`

## Artifacts

- `novel_id`: `codex-5604`
- `chapter_count`: `2`

## Issues

### CHAPTER-QUALITY-001 `GENERATION_QUALITY`

- Severity: `high`
- Stage: `chapter_final_review`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: 章节质量门禁阻断或成稿评分过低。
- Evidence: chapter_id=vol_1_ch_1, quality_status=block, final_review_score=72, status=block, blocking_items[0]={'code': 'word_count_drift', 'message': '字数严重偏离目标', 'detail': {'target_word_count': 3000, 'polished_word_count': 5410}}, warning_items[0]={'code': 'final_review_score', 'message': '成稿评分偏低: 72'}, summary=存在阻断级质量问题，停止归档和世界状态入库。
- Reproduce: `novel-dev-testing quality-summary --input-json <snapshot.json>`
