# Test Run 2026-05-10T154504-generation-real-quality-summary

- Entrypoint: `novel-dev-testing quality-summary`
- Status: `passed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `0.0s`

## Artifacts

- `novel_id`: `codex-194a`
- `chapter_count`: `2`

## Details

### SETTING-QUALITY-DETAIL-001

- Stage: `setting_generation`
- Title: 世界观与设定质量详情
- Evidence: passed=True, review_batch_status=pending, review_batch_summary=东方玄幻短篇测试小说 - 最小可用设定批次（宗门、修炼规则、主角、对立势力、核心冲突、第一章目标）
- Recommendation: none

### SYNOPSIS-QUALITY-DETAIL-002

- Stage: `brainstorm`
- Title: 总纲质量详情
- Evidence: passed=True, structure_score=85, marketability_score=85, conflict_score=85, character_arc_score=85, writability_score=85, core_conflict=林照 vs 幕后敌对势力（与林家灭门相关）关于真相与复仇之争；林照 vs 青云宗内保守派长老关于资源分配与出身偏见之争。
- Recommendation: none

### VOLUME-QUALITY-DETAIL-003

- Stage: `volume_plan`
- Title: 卷纲与跨阶段承接质量详情
- Evidence: passed=True, chapters[0]={'chapter_id': 'vol_1_ch_1', 'chapter_number': 1, 'title': '残卷与残玉', 'report': {'passed': True, 'blocking_issues': [], 'warning_issues': [], 'repair_suggestions': [], 'weak_beats': []}}, story_contract.protagonist_goal=在排挤中生存并提升实力，寻找家族灭门案的蛛丝马迹。, story_contract.current_stage_goal=在排挤中生存并提升实力，寻找家族灭门案的蛛丝马迹。, story_contract.first_chapter_goal=第一章目标：林照在外门生存压力下，通过一次意外事件（外门试炼或杂役任务）接触到与家族覆灭相关的第一条线索。

具体执行路径：
1. 林照接到外门执事分配的杂役任务——前往青云宗后山废弃矿洞采集灵铁矿。
2. 在矿洞深处发现一块刻有林氏家族家徽的残破玉佩，以及一具枯骨（疑似林氏旧部）。
3. 从枯骨遗物中找到一封残信，提及「玄火盟」「血契」「灭口」等关键词。
4. 返回途中遭遇不明身份者偷袭（玄火盟暗哨），林照凭借对地形的熟悉和淬体三层修为勉强逃生。
5. 第一条线索到手：林氏覆灭与玄火盟有关，且有人在监视青云宗内可能知情的林氏旧人。, story_contract.core_conflict=林照 vs 幕后敌对势力（与林家灭门相关）关于真相与复仇之争；林照 vs 青云宗内保守派长老关于资源分配与出身偏见之争。
- Recommendation: none

## Issues

No issues recorded.
