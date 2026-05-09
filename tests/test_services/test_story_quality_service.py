from novel_dev.schemas.context import BeatPlan, ChapterPlan
from novel_dev.schemas.outline import CharacterArc, PlotMilestone, SynopsisData, VolumeBeat
from novel_dev.services.story_quality_service import StoryQualityService
from novel_dev.agents.setting_workbench_agent import SettingBatchChangeDraft, SettingBatchDraft
from novel_dev.services.setting_workbench_service import SettingWorkbenchService


def test_setting_quality_blocks_missing_executable_story_foundations():
    report = StoryQualityService.evaluate_setting_payload(
        {
            "worldview": "天玄大陆，宗门林立。",
            "character_profiles": [{"name": "陆照"}],
            "power_system": "",
            "plot_synopsis": "",
        }
    )

    assert report.passed is False
    assert "power_system" in report.missing_sections
    assert any("核心冲突" in issue for issue in report.weaknesses)
    assert any("主角目标" in suggestion for suggestion in report.repair_suggestions)


def test_synopsis_quality_blocks_abstract_conflict_and_missing_volume_promise():
    synopsis = SynopsisData(
        title="天玄纪",
        logline="少年在乱世中成长。",
        core_conflict="正邪对立",
        themes=["成长"],
        character_arcs=[CharacterArc(name="陆照", arc_summary="成长", key_turning_points=["入门"])],
        milestones=[PlotMilestone(act="一", summary="修炼", climax_event="突破")],
        estimated_volumes=1,
        estimated_total_chapters=3,
        estimated_total_words=9000,
        volume_outlines=[],
    )

    report = StoryQualityService.evaluate_synopsis(synopsis)

    assert report.passed is False
    assert report.conflict_score < 75
    assert report.writability_score < 75
    assert any("具体对抗" in issue for issue in report.blocking_issues)


def test_chapter_writability_requires_conflict_choice_and_hook():
    chapter = VolumeBeat(
        chapter_id="ch_1",
        chapter_number=1,
        title="第一章",
        summary="陆照醒来，了解世界。",
        target_word_count=3000,
        target_mood="平静",
        key_entities=["陆照"],
        beats=[
            BeatPlan(summary="陆照醒来，了解世界。", target_mood="平静", key_entities=["陆照"]),
        ],
    )

    report = StoryQualityService.evaluate_chapter_writability(chapter)

    assert report.passed is False
    assert report.weak_beats == [0]
    assert any("阻力" in issue or "选择" in issue for issue in report.blocking_issues)


def test_build_writing_cards_from_executable_chapter_plan():
    plan = ChapterPlan(
        chapter_number=1,
        title="第一章",
        target_word_count=2000,
        beats=[
            BeatPlan(
                summary="陆照为救妹妹潜入药库，却被执事发现；他必须在交出玉佩和暴露身世之间选择，结尾听见追兵逼近。",
                target_mood="紧张",
                key_entities=["陆照", "执事"],
                foreshadowings_to_embed=["玉佩发热"],
            ),
            BeatPlan(
                summary="陆照利用玉佩残光脱身，但发现妹妹病情恶化，决定参加宗门试炼换药。",
                target_mood="压迫",
                key_entities=["陆照"],
            ),
        ],
    )

    cards = StoryQualityService.build_writing_cards(plan)

    assert len(cards) == 2
    assert cards[0].beat_index == 0
    assert "陆照" in cards[0].required_entities
    assert cards[0].conflict
    assert cards[0].ending_hook
    assert "陆照利用玉佩残光脱身" in cards[0].forbidden_future_events
    assert cards[0].target_word_count == 1000


def test_setting_workbench_builds_quality_report_from_generated_draft():
    draft = SettingBatchDraft(
        summary="生成基础设定",
        changes=[
            SettingBatchChangeDraft(
                target_type="setting_card",
                operation="create",
                after_snapshot={
                    "doc_type": "worldview",
                    "title": "世界观",
                    "content": "天玄大陆，宗门林立。",
                },
            )
        ],
    )

    report = SettingWorkbenchService._evaluate_generated_setting_quality(draft)

    assert report.passed is False
    assert "power_system" in report.missing_sections
    assert any("核心冲突" in issue for issue in report.weaknesses)
