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