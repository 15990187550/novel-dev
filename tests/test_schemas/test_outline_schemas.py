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


def test_default_lists():
    arc = CharacterArc(name="Hero", arc_summary="Grows")
    assert arc.key_turning_points == []

    milestone = PlotMilestone(act="Act 1", summary="Setup")
    assert milestone.climax_event is None

    data = SynopsisData(
        title="T",
        logline="L",
        core_conflict="C",
        estimated_volumes=1,
        estimated_total_chapters=1,
        estimated_total_words=1000,
    )
    assert data.themes == []
    assert data.character_arcs == []
    assert data.milestones == []


def test_synopsis_data_accepts_legacy_llm_field_names():
    data = SynopsisData.model_validate(
        {
            "title": "道照诸天",
            "logline": "陆照欲证彼岸，却被末劫与旧敌逼上绝路。",
            "core_conflict": "陆照 vs 玄天道庭，争夺末劫前最后的彼岸道统",
            "themes": ["求道", "因果"],
            "character_arcs": [
                {
                    "character": "陆照",
                    "arc": "从只信自身机缘，到愿为诸天众生承担因果。",
                    "turning_points": ["得授道经", "轮回失我", "末劫守道"],
                }
            ],
            "milestones": [
                {
                    "name": "得授道经",
                    "description": "陆照入局，初次看见彼岸之争的残酷。",
                    "chapter_range": "1-30",
                    "climax_event": "祖师遗蜕开眼，点名陆照承接道统",
                }
            ],
            "estimated_volumes": 10,
            "estimated_total_chapters": 1300,
            "estimated_total_words": 3900000,
        }
    )

    assert data.character_arcs[0].name == "陆照"
    assert data.character_arcs[0].arc_summary == "从只信自身机缘，到愿为诸天众生承担因果。"
    assert data.character_arcs[0].key_turning_points == ["得授道经", "轮回失我", "末劫守道"]
    assert data.milestones[0].act == "得授道经"
    assert data.milestones[0].summary == "陆照入局，初次看见彼岸之争的残酷。"
    assert data.milestones[0].climax_event == "祖师遗蜕开眼，点名陆照承接道统"


def test_volume_score_result_bounds():
    with pytest.raises(ValueError):
        VolumeScoreResult(overall=-1, outline_fidelity=0, character_plot_alignment=0, hook_distribution=0, foreshadowing_management=0, chapter_hooks=0, page_turning=0, summary_feedback="bad")

    with pytest.raises(ValueError):
        VolumeScoreResult(overall=101, outline_fidelity=0, character_plot_alignment=0, hook_distribution=0, foreshadowing_management=0, chapter_hooks=0, page_turning=0, summary_feedback="bad")
