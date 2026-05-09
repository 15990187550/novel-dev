# Test Run stage-volume-fix-quality-summary

- Entrypoint: `novel-dev-testing quality-summary`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `0.0s`

## Artifacts

- `novel_id`: `codex-6523`
- `chapter_count`: `1`

## Issues

### SETTING-QUALITY-001 `GENERATION_QUALITY`

- Severity: `high`
- Stage: `setting_generation`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: AI 自动生成/整合设定质量未通过。
- Evidence: passed=False, missing_sections[0]=worldview
- Reproduce: `novel-dev-testing quality-summary --input-json <snapshot.json>`

### VOLUME-WRITABILITY-001 `GENERATION_QUALITY`

- Severity: `high`
- Stage: `volume_plan`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: 卷纲存在不可直接写正文的章节。
- Evidence: failed_chapter_numbers=[1], passed=False, failed_chapter_numbers[0]=1, chapters[0]={'chapter_id': 'vol_1_ch_1', 'chapter_number': 1, 'title': '残页启疑', 'report': {'passed': False, 'blocking_issues': ['节拍 1 缺少选择/代价，当前摘要不可直接写正文。', '节拍 2 缺少阻力、选择/代价，当前摘要不可直接写正文。', '节拍 3 缺少阻力、选择/代价，当前摘要不可直接写正文。'], 'warning_issues': [], 'repair_suggestions': ['将弱 beat 改写为：角色目标 + 具体阻力 + 当场选择 + 失败代价 + 停点。'], 'weak_beats': [0, 1, 2]}}
- Reproduce: `novel-dev-testing quality-summary --input-json <snapshot.json>`

### CHAPTER-QUALITY-001 `GENERATION_QUALITY`

- Severity: `high`
- Stage: `chapter_final_review`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: 章节质量门禁阻断或成稿评分过低。
- Evidence: chapter_id=vol_1_ch_1, quality_status=block, final_review_score=72, status=block, blocking_items[0]={'code': 'word_count_drift', 'message': '字数严重偏离目标', 'detail': {'target_word_count': 3000, 'polished_word_count': 5410}}, warning_items[0]={'code': 'final_review_score', 'message': '成稿评分偏低: 72'}, summary=存在阻断级质量问题，停止归档和世界状态入库。
- Reproduce: `novel-dev-testing quality-summary --input-json <snapshot.json>`
