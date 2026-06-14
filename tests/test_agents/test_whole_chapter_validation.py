import pytest
from novel_dev.schemas.context import ChapterContext, ChapterPlan
from novel_dev.schemas.quality import BeatBoundaryCard
from novel_dev.services.beat_coverage_validator import BeatCoverageValidator


@pytest.fixture
def sample_plan():
    return ChapterPlan(
        chapter_number=1,
        target_word_count=3000,
        beats=[],
        beat_boundary_cards=[
            BeatBoundaryCard(beat_index=0, must_cover=["陆照", "玉佩"], forbidden_materials=["追兵"]),
            BeatBoundaryCard(beat_index=1, must_cover=["药库"], forbidden_materials=[]),
        ],
    )


@pytest.mark.asyncio
async def test_perfect_chapter_no_issues(async_session, sample_plan):
    validator = BeatCoverageValidator(async_session, use_llm=False)
    text = "陆照握紧玉佩，悄悄潜入药库。"
    results = await validator.validate(sample_plan.beat_boundary_cards, text)
    assert all(r.severity == "ok" for r in results)


@pytest.mark.asyncio
async def test_missing_beat_warns(async_session, sample_plan):
    validator = BeatCoverageValidator(async_session, use_llm=False)
    text = "陆照握紧玉佩。"  # 缺药库
    results = await validator.validate(sample_plan.beat_boundary_cards, text)
    assert any(r.severity == "warn" for r in results)


@pytest.mark.asyncio
async def test_forbidden_material_blocks(async_session, sample_plan):
    validator = BeatCoverageValidator(async_session, use_llm=False)
    text = "陆照握紧玉佩，追兵已经逼近。"  # beat 0 forbidden
    results = await validator.validate(sample_plan.beat_boundary_cards, text)
    assert any(r.severity == "block" for r in results)
