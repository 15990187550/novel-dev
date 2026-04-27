import pytest
from novel_dev.schemas.outline import (
    SynopsisData,
    VolumePlan,
    VolumeBeat,
    VolumeScoreResult,
    CharacterArc,
    PlotMilestone,
    SynopsisVolumeOutline,
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
    assert data.volume_outlines == []


def test_synopsis_volume_outline_accepts_contract_aliases():
    outline = SynopsisVolumeOutline.model_validate({
        "number": 2,
        "volume_title": "破局卷",
        "description": "主角从被动逃亡转为主动布局。",
        "goal": "夺回主动权",
        "conflict": "主角 vs 追猎者",
        "climax_event": "反杀追猎首领",
        "hook": "幕后真凶露面",
        "key_entities": "主角",
        "relationship_shifts": {"师徒": "从猜疑到托付"},
    })

    assert outline.volume_number == 2
    assert outline.title == "破局卷"
    assert outline.main_goal == "夺回主动权"
    assert outline.main_conflict == "主角 vs 追猎者"
    assert outline.climax == "反杀追猎首领"
    assert outline.hook_to_next == "幕后真凶露面"
    assert outline.key_entities == ["主角"]
    assert outline.relationship_shifts == ["师徒: 从猜疑到托付"]


def test_synopsis_data_backfills_incomplete_volume_outlines():
    data = SynopsisData.model_validate({
        "title": "道照诸天",
        "logline": "陆照争夺超脱路径。",
        "core_conflict": "陆照 vs 轮回空间",
        "estimated_volumes": 2,
        "estimated_total_chapters": 60,
        "estimated_total_words": 180000,
        "volume_outlines": [
            {"main_goal": "夺回第一枚道印", "main_conflict": "陆照 vs 轮回使者"},
            "道庭介入，陆照被迫离开旧地。",
        ],
    })

    assert data.volume_outlines[0].volume_number == 1
    assert data.volume_outlines[0].title == "夺回第一枚道印"
    assert data.volume_outlines[0].summary == "夺回第一枚道印"
    assert data.volume_outlines[1].volume_number == 2
    assert data.volume_outlines[1].title == "道庭介入，陆照被迫离开旧地"
    assert data.volume_outlines[1].summary == "道庭介入，陆照被迫离开旧地。"


def test_synopsis_volume_outline_backfills_missing_title_from_summary():
    outline = SynopsisVolumeOutline.model_validate({
        "volume_number": 1,
        "summary": "陆照踏入修行世界并卷入传承争夺。",
        "main_goal": "获得道经认可",
        "main_conflict": "陆照 vs 追杀者",
        "target_chapter_range": "1-50",
    })

    assert outline.title == "陆照踏入修行世界并卷入传承争夺"
    assert outline.summary == "陆照踏入修行世界并卷入传承争夺。"


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


def test_volume_plan_accepts_legacy_llm_field_names():
    plan = VolumePlan.model_validate(
        {
            "volume_number": 1,
            "volume_title": "第一卷 道经初鸣",
            "description": "陆照起步，发现道经异动。",
            "total_words": 36000,
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "藏经阁异响",
                    "description": "陆照夜入藏经阁。",
                    "planned_foreshadowings": ["道经印记"],
                    "beats": [
                        {
                            "beat_number": 1,
                            "description": "陆照察觉藏经阁异动。",
                        }
                    ],
                }
            ],
        }
    )

    assert plan.volume_id == "vol_1"
    assert plan.title == "第一卷 道经初鸣"
    assert plan.summary == "陆照起步，发现道经异动。"
    assert plan.estimated_total_words == 36000
    assert plan.total_chapters == 1
    assert plan.chapters[0].chapter_id == "ch_1"
    assert plan.chapters[0].target_word_count == 3000
    assert plan.chapters[0].target_mood == "tense"
    assert plan.chapters[0].foreshadowings_to_recover == ["道经印记"]
    assert plan.chapters[0].beats[0].summary == "陆照察觉藏经阁异动。"
    assert plan.chapters[0].beats[0].target_mood == "tense"
