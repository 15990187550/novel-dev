# Test Run phase6-smoke-20260620-full-quality-summary

- Entrypoint: `novel-dev-testing quality-summary`
- Status: `failed`
- Dataset: `minimal_builtin`
- LLM mode: `real_then_fake_on_external_block`
- Duration: `0.0s`

## Artifacts

- `novel_id`: `novel-6f36`
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
- Evidence: passed=True, review_batch_status=approved, review_batch_summary=第5轮按'待确认 + 保守推进'原则进入设定批次草案生成。本批次覆盖全量设定核心类别：世界观补强、力量/规则边界、剧情梗概与第一章可执行目标、人物（陈渊）、物品（观天镜/玉佩）、势力（五大圣地/王朝/诸宗门/异族）、关键关系。资料未支撑的关键参数（开局境界、首卷境界上限、观天镜升级门槛、第一章主要登场势力具体名号、王朝/异族具名、第一章女性角色安排）一律以 conflict_hints 标记待确认，不以模型记忆或题材惯例代写。所有内容均可回溯至已导入资料：世界观.md / 力量体系.md / 道照诸天_brief.md / 金手指设计.md。
- Recommendation: none

### SYNOPSIS-QUALITY-DETAIL-003

- Stage: `brainstorm`
- Title: 总纲质量详情
- Evidence: passed=False, structure_score=60, marketability_score=85, conflict_score=85, character_arc_score=85, writability_score=85, warning_issues[0]=总纲可识别结构转折不足 4 个，当前识别到 3 个。, repair_suggestions[0]=补充会改变主角处境、关系、目标、风险等级或关键信息掌握状态的转折。, core_conflict=陈渊（携观天镜Lv1窥视的边陲少年）与暗中勾结异族渗透者的圣地外门执事·周砚——后者以合谋三大势力献祭边陲同道换取异族庇护与晋升资粮——围绕矿脉暗局、玉佩观天镜之秘与天道异变前的棋局展开具名对抗；陈渊须在周砚收网前以信息差布局破局，否则同道尽灭、玉佩真相永封。
- Recommendation: none

### VOLUME-QUALITY-DETAIL-004

- Stage: `volume_plan`
- Title: 卷纲与跨阶段承接质量详情
- Evidence: story_contract.protagonist_goal=觉醒观天镜Lv1窥视，在家族变故中自保并救下关键之人，初步踏入修行界，并隐约触及追杀者背后周砚的影子。, story_contract.current_stage_goal=觉醒观天镜Lv1窥视，在家族变故中自保并救下关键之人，初步踏入修行界，并隐约触及追杀者背后周砚的影子。, story_contract.first_chapter_goal=# 世界观（草案·待审核）

## 一、大背景
凡人界之上有三千大世界，大世界之间以"天道"相连。天道运转不息，每隔一段岁月便有"天道异变"——届时大世界互通，修士可穿梭诸天。
来源：世界观.md

## 二、时代背景
故事开端为"太玄历末年"，天道异变前夜，灵气潮汐暗涌，各宗明哲保身又暗中备战。
来源：世界观.md

## 三、地理格局
- 玄元大陆：凡人界主大陆，宗门林立，以五大圣地为首
- 虚天界：天道交汇之处，异变期间对外开启
- 三千小世界：天道异变后方能抵达的异域
来源：世界观.md

## 四、叙事调性
正剧向、有厚重感、有成长但不卖惨。主角靠头脑+金手指双线推进，情感克制，女性角色有自己的立场与命运。
来源：世界观.md

## 五、待确认项（保守推进，不代写）
- 第一章是否需要出现具体的五大圣地名号 / 代表人物 / 王朝具名 / 异族具体形态：待确认（见势力格局卡）
- 第一章是否安排女性角色登场与具体叙事功能：待确认（见人物设定卡）
- 三千大世界之间的具体位阶与门槛细则：资料未覆盖，留待后续资料补全, story_contract.core_conflict=陈渊（携观天镜Lv1窥视的边陲少年）与暗中勾结异族渗透者的圣地外门执事·周砚——后者以合谋三大势力献祭边陲同道换取异族庇护与晋升资粮——围绕矿脉暗局、玉佩观天镜之秘与天道异变前的棋局展开具名对抗；陈渊须在周砚收网前以信息差布局破局，否则同道尽灭、玉佩真相永封。
- Recommendation: none

## Issues

### SYNOPSIS-QUALITY-001 `GENERATION_QUALITY`

- Severity: `high`
- Stage: `brainstorm`
- External blocker: `False`
- Real LLM: `True`
- Fake rerun status: `None`
- Message: 总纲质量门禁未通过。
- Evidence: passed=False, structure_score=60, marketability_score=85, conflict_score=85, character_arc_score=85, writability_score=85, warning_issues[0]=总纲可识别结构转折不足 4 个，当前识别到 3 个。, repair_suggestions[0]=补充会改变主角处境、关系、目标、风险等级或关键信息掌握状态的转折。
- Reproduce: `novel-dev-testing quality-summary --input-json <snapshot.json>`
