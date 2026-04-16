import pytest
from novel_dev.schemas.outline import (
    SynopsisData,
    VolumePlan,
    VolumeBeat,
    VolumeScoreResult,
    CharacterArc,
    PlotMilestone,
)
from novel_dev.schemas.context import BeatPlan


def test_synopsis_data_creation():
    data = SynopsisData(
        title="Test Novel",
        logline="A test logline",
        core_conflict="Man vs machine",
        estimated_volumes=3,
        estimated_total_chapters=90,
        estimated_total_words=270000,
    )
    assert data.title == "Test Novel"
    assert data.estimated_total_words == 270000


def test_volume_plan_creation():
    beat = BeatPlan(summary="Opening", target_mood="tense")
    vb = VolumeBeat(
        chapter_id="ch_1",
        chapter_number=1,
        title="Prologue",
        summary="Intro",
        target_word_count=3000,
        target_mood="dark",
        beats=[beat],
    )
    plan = VolumePlan(
        volume_id="vol_1",
        volume_number=1,
        title="Volume One",
        summary="First volume",
        total_chapters=1,
        estimated_total_words=3000,
        chapters=[vb],
    )
    assert plan.volume_id == "vol_1"
    assert plan.chapters[0].chapter_id == "ch_1"
    assert plan.chapters[0].beats[0].summary == "Opening"


def test_volume_score_result_creation():
    result = VolumeScoreResult(
        overall=88,
        outline_fidelity=90,
        character_plot_alignment=85,
        hook_distribution=80,
        foreshadowing_management=88,
        chapter_hooks=90,
        page_turning=87,
        summary_feedback="Solid plan",
    )
    assert result.overall == 88
