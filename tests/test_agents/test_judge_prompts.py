from novel_dev.agents.judge_prompts import render_judge_prompt_v1, JUDGE_PROMPT_V1


def test_renders_with_chapter_text():
    rendered = render_judge_prompt_v1("这是章节内容...")
    assert "这是章节内容..." in rendered
    assert "人物口吻" in rendered
    assert "叙事连贯" in rendered
    assert "风格调性" in rendered
    assert "口吻" in rendered  # JSON key
    assert "理由" in rendered  # rationale key


def test_v1_template_has_strict_json_output_instruction():
    assert "严格 JSON" in JUDGE_PROMPT_V1 or "strict JSON" in JUDGE_PROMPT_V1
    assert "JSON 之外" in JUDGE_PROMPT_V1 or "outside JSON" in JUDGE_PROMPT_V1


def test_dimension_rubric_present():
    rendered = render_judge_prompt_v1("x")
    for keyword in ["9-10", "7-8", "5-6", "<5"]:
        assert keyword in rendered, f"rubric {keyword} missing"
