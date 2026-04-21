from unittest.mock import AsyncMock, patch

import pytest

from novel_dev.agents.style_profiler import StyleProfilerAgent, StyleProfile
from novel_dev.llm.models import LLMResponse


@pytest.mark.asyncio
async def test_profile_success():
    profile = StyleProfile(
        style_guide="轻松吐槽包裹热血推进，旁白贴近主角意识",
        style_config={
            "sentence_patterns": {"avg_length": 22, "paragraph_length": "2-4 sentences", "complexity": "moderate"},
            "dialogue_style": {"direct_speech_ratio": 0.3, "dialogue_tag_style": "简洁标签"},
            "narration_voice": {"distance": "close_limited", "commentary_source": "主角内心"},
            "humor_strategy": {"frequency": "medium", "source": "现代思维反差", "restraint": "危机和抒情处收敛"},
            "information_reveal": {"method": "行动中渐进揭露", "suspense_density": "medium"},
            "scene_preferences": {"combat": "拆招和心理判断并重", "daily": "对白推动关系"},
            "rhetoric_devices": ["反差幽默", "反讽"],
            "pacing": "fast",
            "vocabulary_preferences": ["剑", "血", "杀"],
            "perspective": "limited",
            "tone": "诙谐但有热血底色",
            "writing_rules": ["旁白贴近主角即时判断", "紧张场景减少吐槽"],
            "style_boundary": ["不要把幽默写成密集网络梗", "不要一次性倾倒设定"],
            "evolution_notes": "日常段幽默更密，主线危机时转为紧凑。",
        },
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=profile.model_dump_json())

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = StyleProfilerAgent()
        result = await agent.profile("测试文本")

    assert result.style_guide != ""
    assert result.style_config.perspective == "limited"
    assert result.style_config.tone == "诙谐但有热血底色"
    assert result.style_config.narration_voice["distance"] == "close_limited"
    assert result.style_config.writing_rules
    assert result.style_config.style_boundary


@pytest.mark.asyncio
async def test_profile_prompt_asks_for_actionable_style_constraints():
    profile = StyleProfile(
        style_guide="克制紧凑",
        style_config={
            "pacing": "moderate",
            "perspective": "limited",
            "tone": "克制",
            "writing_rules": ["每段保留明确推进点"],
            "style_boundary": ["不要总结剧情"],
        },
    )
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(text=profile.model_dump_json())

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = StyleProfilerAgent()
        await agent.profile("测试文本")

    prompt = mock_client.acomplete.call_args.args[0][0].content
    assert "只提取'写法与风格'" in prompt
    assert "writing_rules" in prompt
    assert "style_boundary" in prompt
    assert "不要总结剧情" in prompt


@pytest.mark.asyncio
async def test_profile_coerces_text_and_string_list_fields():
    mock_client = AsyncMock()
    mock_client.acomplete.return_value = LLMResponse(
        text='''{
  "style_guide": {"核心": "冷峻压迫", "节奏": "紧绷"},
  "style_config": {
    "sentence_patterns": {"avg_length": 25, "complexity": "moderate"},
    "dialogue_style": {"direct_speech_ratio": 0.3},
    "narration_voice": {"distance": "close"},
    "humor_strategy": {"frequency": "low"},
    "information_reveal": {"method": "渐进"},
    "scene_preferences": {"combat": "短句拆招"},
    "rhetoric_devices": {"主要": "比喻", "次要": "排比"},
    "pacing": ["fast", "with pauses"],
    "vocabulary_preferences": {"高频": "剑", "意象": "血"},
    "perspective": {"main": "limited"},
    "tone": ["intense", "dark"],
    "writing_rules": {"规则1": "短句推进", "规则2": "少解释"},
    "style_boundary": {"边界1": "不要堆设定"},
    "evolution_notes": {"前期": "克制", "后期": "更疯狂"}
  }
}'''
    )

    with patch("novel_dev.agents._llm_helpers.llm_factory") as mock_factory:
        mock_factory.get.return_value = mock_client
        agent = StyleProfilerAgent()
        result = await agent.profile("测试文本")

    assert "核心: 冷峻压迫" in result.style_guide
    assert result.style_config.rhetoric_devices == ["主要: 比喻", "次要: 排比"]
    assert result.style_config.vocabulary_preferences == ["高频: 剑", "意象: 血"]
    assert result.style_config.writing_rules == ["规则1: 短句推进", "规则2: 少解释"]
    assert result.style_config.style_boundary == ["边界1: 不要堆设定"]
    assert result.style_config.pacing == "fast\nwith pauses"
    assert result.style_config.perspective == "main: limited"
    assert result.style_config.tone == "intense\ndark"
    assert "前期: 克制" in result.style_config.evolution_notes
