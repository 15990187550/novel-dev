def test_writer_prompt_has_few_shot_example():
    from novel_dev.agents._default_prompts import WRITER_PROMPT
    assert "Few-shot" in WRITER_PROMPT or "差" in WRITER_PROMPT or "示例" in WRITER_PROMPT


def test_critic_prompt_has_high_low_score_examples():
    from novel_dev.agents._default_prompts import CRITIC_PROMPT
    # 应有高分/低分示例
    assert ("90" in CRITIC_PROMPT or "high" in CRITIC_PROMPT.lower())


def test_editor_prompt_has_before_after_example():
    from novel_dev.agents._default_prompts import EDITOR_PROMPT
    assert "修前" in EDITOR_PROMPT or "改前" in EDITOR_PROMPT or "before" in EDITOR_PROMPT.lower()


def test_rolling_synopsis_prompt_defined():
    from novel_dev.agents._default_prompts import ROLLING_SYNOPSIS_PROMPT
    assert "前情" in ROLLING_SYNOPSIS_PROMPT or "prev" in ROLLING_SYNOPSIS_PROMPT.lower()


def test_entity_change_importance_prompt_defined():
    from novel_dev.agents._default_prompts import ENTITY_CHANGE_IMPORTANCE_PROMPT
    assert "important" in ENTITY_CHANGE_IMPORTANCE_PROMPT.lower()


def test_imagery_extraction_prompt_defined():
    from novel_dev.agents._default_prompts import IMAGERY_EXTRACTION_PROMPT
    assert "意象" in IMAGERY_EXTRACTION_PROMPT or "imagery" in IMAGERY_EXTRACTION_PROMPT.lower()


def test_cross_chapter_drift_prompt_defined():
    from novel_dev.agents._default_prompts import CROSS_CHAPTER_DRIFT_DETECTION_PROMPT
    assert "drift" in CROSS_CHAPTER_DRIFT_DETECTION_PROMPT.lower() or "漂移" in CROSS_CHAPTER_DRIFT_DETECTION_PROMPT