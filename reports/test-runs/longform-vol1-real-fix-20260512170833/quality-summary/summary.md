# Test Run longform-vol1-real-fix-20260512170833-quality-summary

- Entrypoint: `novel-dev-testing quality-summary`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real`
- Duration: `0.0s`

## Artifacts

- `novel_id`: `codex-1375`
- `chapter_count`: `0`
- `target_volumes`: `18`
- `target_chapters`: `1200`
- `target_word_count`: `2000000`
- `target_volume_number`: `1`
- `target_volume_chapters`: `67`
- `target_volume_word_count`: `111689`
- `chapter_target_word_count`: `1667`
- `generated_chapter_count`: `0`
- `generated_word_count`: `0`
- `source_material_count`: `4`
- `source_material_approved_count`: `0`
- `source_material_char_count`: `4756898`

## Details

### LONGFORM-SCALE-DETAIL-001

- Stage: `longform_scale`
- Title: 长篇目标规模与资料导入统计
- Evidence: generated_chapter_count=0, generated_word_count=0, source_material_count=4, source_material_approved_count=0, source_material_char_count=4756898, target_volumes=18, target_chapters=1200, target_word_count=2000000, target_volume_number=1, target_volume_chapters=67, target_volume_word_count=111689, chapter_target_word_count=1667
- Recommendation: none

### SYNOPSIS-QUALITY-DETAIL-002

- Stage: `brainstorm`
- Title: 总纲质量详情
- Evidence: passed=False, structure_score=60, marketability_score=60, conflict_score=45, character_arc_score=60, writability_score=45, blocking_issues[0]=总纲缺少具体对抗关系，需要写清谁与谁为了什么发生冲突。, warning_issues[0]=主要人物弧光转折不足，正文容易缺少人物选择。, warning_issues[1]=总纲可识别结构转折不足 4 个，当前识别到 0 个。, warning_issues[2]=缺少卷级承诺，卷纲生成时容易偏题。, repair_suggestions[0]=将 core_conflict 改成『主角 vs 具体阻力，为争夺具体目标』。, repair_suggestions[1]=为主角和关键对手补齐至少 3 个会改变关系或信念的转折点。, repair_suggestions[2]=补充会改变主角处境、关系、目标、风险等级或关键信息掌握状态的转折。, repair_suggestions[3]=补充每卷目标、主冲突、卷级高潮和卷末钩子。
- Recommendation: 总纲缺少具体对抗关系，需要写清谁与谁为了什么发生冲突。

## Issues

### SYNOPSIS-QUALITY-001 `GENERATION_QUALITY`

- Severity: `high`
- Stage: `brainstorm`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: 总纲质量门禁未通过。
- Evidence: passed=False, structure_score=60, marketability_score=60, conflict_score=45, character_arc_score=60, writability_score=45, blocking_issues[0]=总纲缺少具体对抗关系，需要写清谁与谁为了什么发生冲突。, warning_issues[0]=主要人物弧光转折不足，正文容易缺少人物选择。, warning_issues[1]=总纲可识别结构转折不足 4 个，当前识别到 0 个。, warning_issues[2]=缺少卷级承诺，卷纲生成时容易偏题。, repair_suggestions[0]=将 core_conflict 改成『主角 vs 具体阻力，为争夺具体目标』。, repair_suggestions[1]=为主角和关键对手补齐至少 3 个会改变关系或信念的转折点。
- Reproduce: `novel-dev-testing quality-summary --input-json <snapshot.json>`
