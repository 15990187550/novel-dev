# Test Run phase6-smoke-final2-quality-summary

- Entrypoint: `novel-dev-testing quality-summary`
- Status: `passed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `0.0s`

## Artifacts

- `novel_id`: `novel-80ee`
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
- `source_material_approved_count`: `4`
- `source_material_char_count`: `1340`

## Details

### LONGFORM-SCALE-DETAIL-001

- Stage: `longform_scale`
- Title: 长篇目标规模与资料导入统计
- Evidence: generated_chapter_count=0, generated_word_count=0, source_material_count=4, source_material_approved_count=4, source_material_char_count=1340, target_volumes=18, target_chapters=1200, target_word_count=2000000, target_volume_number=1, target_volume_chapters=67, target_volume_word_count=111689, chapter_target_word_count=1667
- Recommendation: none

### SETTING-QUALITY-DETAIL-002

- Stage: `setting_generation`
- Title: 世界观与设定质量详情
- Evidence: passed=True, review_batch_status=approved, review_batch_summary=第一批待审核设定批次：基于已导入4份资料生成世界观/力量体系/剧情梗概/核心冲突/主角目标与第一章可执行目标5张设定卡，覆盖长篇首卷所需骨架；资料未支持的细节全部以 conflict_hints 标记为待确认。
- Recommendation: none

### SYNOPSIS-QUALITY-DETAIL-003

- Stage: `brainstorm`
- Title: 总纲质量详情
- Evidence: passed=True, structure_score=85, marketability_score=85, conflict_score=85, character_arc_score=85, writability_score=85, core_conflict=凡人陈渊(观天镜持有者) vs 以异族探子'青鳞'为首的情报网 vs 玄元大陆五大圣地清虚宗追捕队 vs 王朝暗通异族的内应'赵都尉'——三方围绕天道异变前夜对观天镜的争夺、对玉佩身世真相的封锁与对陈渊至亲的胁迫,展开凡人 vs 修行界的情报生死局。
- Recommendation: none

### VOLUME-QUALITY-DETAIL-004

- Stage: `volume_plan`
- Title: 卷纲与跨阶段承接质量详情
- Evidence: story_contract.protagonist_goal=在追杀中护住至亲并活着逃出边陲小城,同时初步摸清观天镜Lv1窥视的代价与边界。, story_contract.current_stage_goal=在追杀中护住至亲并活着逃出边陲小城,同时初步摸清观天镜Lv1窥视的代价与边界。, story_contract.first_chapter_goal=## 主角：陈渊
- 出身：边陲小城落魄世家子。
- 起点：凡人起步（具体境界待确认）。
- 金手指：祖传玉佩觉醒的"观天镜"，上古至宝残片，需逐层唤醒。
- 性格：谨慎不冲动，先观察再出手；有同理心但不滥情，关键抉择果断；喜欢用信息差与布局获胜；情感克制。
- 表层动机：为家族复仇、证明自己。
- 深层动机：寻求天道真相，理解"异变"本质。
- 周旋势力：玄元大陆五大圣地、王朝。
- 敌对势力：异族。

## 当前动机（第一章开篇时点）
1. 在"天道异变前夜、灵气潮汐暗涌"的边陲小城，确认祖传玉佩/观天镜已觉醒，并保守秘密。
2. 弄清家族败落的直接原因（族中长辈/旧仆/地方势力等可接触信息源），锁定"家族复仇"的最小可行目标。
3. 找到第一处安全、可控的方式进入修行界（边陲小城→玄元大陆腹地五大圣地之一或散修坊市），在不暴露观天镜的前提下完成从凡人向炼气期的过渡。
4. 用观天镜 Lv1"窥视"先识别身边潜在威胁与机会，建立信息差优势。

## 第一章可执行目标（须全部可回溯至导入资料）
- **场景前提**：太玄历末年，灵气潮汐暗涌的边陲小城；陈渊颈间祖传玉佩内嵌的观天镜首次显化。
- **本章目标 A（生存线）**：在不暴露观天镜的前提下，处理一次因灵气潮汐引发的现实危机（凡人层面的冲突或异象），让观天镜 Lv1"窥视"首次实战立功，建立"观察—识别—布局"的行为模式。
- **本章目标 B（动机线）**：推进"家族复仇"线索一步——获得一条可追溯的因果片段（对应观天镜 Lv2"追溯"或为后续升级埋下伏笔），但不直接复仇。
- **本章目标 C（世界线）**：引出"五大圣地/王朝/异族"三方势力的边陲投影（如过路修士、征召令、异象等），让读者明确周旋格局，不深入宗门内斗。
- **本章目标 D（代价线）**：本章内观天镜使用必须付出神识代价，呈现"金手指有代价"的硬约束，避免无敌化。

## 第一章禁忌（资料未支持，不写）
- 不写跨境界战胜强敌。
- 不写观天镜直接杀人或改写已发生之事。
- 不写具体家族仇人姓名、具体圣地名称、具体王朝国号、具体异族形态（资料未支持）。
- 不写主角一夜突破到高阶境界。
- 不让女性角色沦为工具人，需有其立场与命运（与调性一致）。, story_contract.core_conflict=凡人陈渊(观天镜持有者) vs 以异族探子'青鳞'为首的情报网 vs 玄元大陆五大圣地清虚宗追捕队 vs 王朝暗通异族的内应'赵都尉'——三方围绕天道异变前夜对观天镜的争夺、对玉佩身世真相的封锁与对陈渊至亲的胁迫,展开凡人 vs 修行界的情报生死局。
- Recommendation: none

## Issues

No issues recorded.
