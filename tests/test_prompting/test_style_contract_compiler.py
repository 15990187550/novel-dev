from novel_dev.prompting.style_contract import StyleContractCompiler


def test_style_contract_compiler_turns_style_profile_into_layered_contract():
    profile = {
        "style_guide": "克制、具体，少用抽象玄幻大词。",
        "narrative_rules": ["先写当场动作，再显出信息差。"],
        "character_rules": ["人物嘴硬，情绪不要直接说明。"],
        "language_rules": ["句子短一些，保留生活化物件。"],
        "rhythm_rules": ["结尾留一个低声量余波。"],
        "anti_ai_rules": ["压低比喻密度，不要段尾升华。"],
        "self_check": ["检查是否把心理解释改成动作。"],
    }

    contract = StyleContractCompiler.compile(profile)
    rendered = contract.render_prompt_block()

    assert "### 写法合同" in rendered
    assert "#### 叙事规则" in rendered
    assert "先写当场动作" in rendered
    assert "#### 角色表达" in rendered
    assert "人物嘴硬" in rendered
    assert "#### 语言质感" in rendered
    assert "生活化物件" in rendered
    assert "#### 节奏控制" in rendered
    assert "低声量余波" in rendered
    assert "#### 反AI风险" in rendered
    assert "压低比喻密度" in rendered
    assert "#### 输出前自检" in rendered
    assert "检查是否把心理解释改成动作" in rendered
    assert "{" not in rendered
    assert "}" not in rendered


def test_style_contract_compiler_preserves_empty_profile_as_noop():
    contract = StyleContractCompiler.compile({})

    assert not contract.has_content
    assert contract.render_prompt_block() == ""


def test_style_contract_compiler_keeps_narrative_rules_under_narrative_section_without_style_guide():
    contract = StyleContractCompiler.compile({
        "narrative_rules": ["先写当场动作，再显出信息差。"],
    })

    rendered = contract.render_prompt_block()

    assert "#### 总体风格" not in rendered
    assert "#### 叙事规则" in rendered
    assert "先写当场动作" in rendered


def test_style_contract_compiler_extracts_real_style_config_fields():
    profile = {
        "style_config": {
            "dialogue_style": {"rules": ["对白短，留半句未说完。"]},
            "narration_voice": {"summary": "紧贴主角可感知的信息。"},
            "information_reveal": {"keep": ["先给可见后果，再解释设定。"]},
            "sentence_patterns": {"rules": ["动作段用短句推进。"]},
            "pacing": "moderate",
            "tone": "克制、具体",
            "writing_rules": ["情绪落到动作和物件。"],
            "style_boundary": ["不要段尾升华。"],
        }
    }

    contract = StyleContractCompiler.compile(profile)
    rendered = contract.render_prompt_block()

    assert "紧贴主角可感知的信息" in rendered
    assert "对白短" in rendered
    assert "先给可见后果" in rendered
    assert "动作段用短句推进" in rendered
    assert "节奏取向: moderate" in rendered
    assert "整体气质: 克制、具体" in rendered
    assert "情绪落到动作和物件" in rendered
    assert "不要段尾升华" in rendered
