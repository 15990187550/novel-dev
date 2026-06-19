JUDGE_PROMPT_V1 = """你是一位严格的网文质量评审,负责给单章打分。本章属于对比实验的一部分,
请独立于其他信息评估。

## 待评审章节
{chapter_text}

## 评分维度(0-10 分,允许小数)

1. **人物口吻**:角色对话和内心独白是否符合其既定性格、当前处境和关系网。
   - 9-10:口吻完全契合,角色感强
   - 7-8:基本一致,偶有可商榷处
   - 5-6:有 1-2 处明显偏差
   - <5:多处角色感崩塌

2. **叙事连贯**:时间线、空间、事件因果是否清晰,有无逻辑跳跃或重复。
   - 9-10:流畅自然
   - 7-8:可读,有 1 处小跳跃
   - 5-6:需要读者脑补才能跟上
   - <5:明显断裂

3. **风格调性**:与本作品已确立的语言风格、用词偏好、修辞习惯是否一致。
   - 9-10:风格统一
   - 7-8:基本统一,有 1-2 处可商榷
   - 5-6:出现风格漂移
   - <5:风格断裂

## 输出格式(严格 JSON,无任何额外文字)
{{"口吻": 7.5, "叙事连贯": 8.0, "风格调性": 6.5, "理由": "≤200 字简评"}}

不要在 JSON 之外输出任何内容。"""


def render_judge_prompt_v1(chapter_text: str) -> str:
    """用给定章节文本渲染 v1 模板。chapter_text 必须是字符串(不能为空)。"""
    if not isinstance(chapter_text, str) or not chapter_text.strip():
        raise ValueError("chapter_text must be a non-empty string")
    return JUDGE_PROMPT_V1.format(chapter_text=chapter_text)
