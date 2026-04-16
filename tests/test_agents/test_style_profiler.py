import pytest

from novel_dev.agents.style_profiler import StyleProfilerAgent


def test_chunk_sampling():
    agent = StyleProfilerAgent()
    text = "a" * 9000  # 3 blocks
    chunks = agent._chunk_text(text, chunk_size=3000)
    assert len(chunks) == 3

    sampled = agent._sample_chunks(chunks)
    # 3 blocks -> sample all (min 8 not reached, but 50% rounds up)
    assert len(sampled) == 3


def test_large_text_sampling():
    agent = StyleProfilerAgent()
    text = "a" * (50 * 3000)  # 50 blocks
    chunks = agent._chunk_text(text, chunk_size=3000)
    sampled = agent._sample_chunks(chunks)
    assert len(sampled) == 24  # capped at 24


@pytest.mark.asyncio
async def test_profile_from_text():
    agent = StyleProfilerAgent()
    text = "林风握紧了剑。剑光一闪，敌人倒下。"
    profile = await agent.profile(text)
    assert profile.style_guide != ""
    assert profile.style_config.perspective != ""
