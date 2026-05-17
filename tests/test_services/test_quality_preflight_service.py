from novel_dev.schemas.context import BeatPlan, ChapterPlan
from novel_dev.schemas.outline import VolumePlan
from novel_dev.services.quality_preflight_service import QualityPreflightService


def test_preflight_blocks_repeated_generic_constraints_before_drafting():
    generic = "陆照必须在继续行动与保全自身之间做出选择，阻力当场升级，失败代价是失去关键线索并暴露处境，结尾留下新的危险信号。"
    plan = ChapterPlan(
        chapter_number=1,
        title="模板章",
        target_word_count=1800,
        beats=[
            BeatPlan(summary=f"陆照通过入门考核；{generic}", target_mood="紧张", key_entities=["陆照"]),
            BeatPlan(summary=f"陆照被分到杂役处；{generic}", target_mood="压迫", key_entities=["陆照"]),
        ],
    )

    report = QualityPreflightService.evaluate_chapter_plan(plan)

    assert report.status == "block"
    assert report.passed is False
    assert any(issue.code == "repeated_generic_repair_constraint" for issue in report.blocking_issues)


def test_preflight_blocks_forbidden_setting_alias_from_story_contract():
    plan = ChapterPlan(
        chapter_number=3,
        title="身份误写",
        target_word_count=1600,
        beats=[
            BeatPlan(
                summary="林照在药库被迫隐藏玉佩，却被人称作魔门圣子，结尾发现追兵逼近。",
                target_mood="紧张",
                key_entities=["林照"],
            )
        ],
    )

    report = QualityPreflightService.evaluate_chapter_plan(
        plan,
        story_contract={"forbidden_aliases": ["魔门圣子"], "must_carry_forward": ["玉佩"]},
    )

    assert report.status == "block"
    assert any(issue.code == "forbidden_story_contract_term" for issue in report.blocking_issues)
    assert "魔门圣子" in report.forbidden_terms


def test_preflight_blocks_choice_without_failure_stake():
    plan = ChapterPlan(
        chapter_number=2,
        title="无代价选择",
        target_word_count=1600,
        beats=[
            BeatPlan(
                summary="林照为查药库线索潜入内库，却被执事拦下；他必须在追问和沉默之间选择，结尾发现追兵逼近。",
                target_mood="紧张",
                key_entities=["林照"],
            )
        ],
    )

    report = QualityPreflightService.evaluate_chapter_plan(plan)

    assert report.status == "block"
    assert any("失败代价" in issue.message for issue in report.blocking_issues)


def test_preflight_blocks_empty_volume_plan():
    plan = VolumePlan(
        volume_id="vol_empty",
        volume_number=1,
        title="空卷",
        summary="空卷纲",
        total_chapters=0,
        estimated_total_words=0,
        chapters=[],
    )

    summary = QualityPreflightService.summarize_volume_plan(plan)

    assert summary["status"] == "block"
    assert summary["passed"] is False
    assert summary["blocking_issues"][0]["code"] == "missing_volume_chapters"
    assert summary["blocking_issues"][0]["dimension"] == "writability"
    assert summary["blocking_issues"][0]["severity"] == "block"


def test_preflight_warns_abstract_readability_and_exports_contract():
    plan = ChapterPlan(
        chapter_number=1,
        title="入门",
        target_word_count=1200,
        beats=[
            BeatPlan(summary="陆照醒来了解世界。", target_mood="平静", key_entities=["陆照"]),
            BeatPlan(summary="陆照继续成长。", target_mood="平静", key_entities=["陆照"]),
        ],
    )

    report = QualityPreflightService.evaluate_chapter_plan(plan)

    assert report.status == "block"
    assert any(issue.dimension == "readability" for issue in report.warning_issues)
    assert any("可见动作" in item for item in report.readability_contract)
    assert report.causal_links


def test_preflight_builds_dynamic_contract_from_entities_and_story_contract():
    plan = ChapterPlan(
        chapter_number=2,
        title="旧案",
        target_word_count=1800,
        beats=[
            BeatPlan(
                summary="林照为查明玉佩线索潜入祠堂，却被守祠人拦下；他必须在追问和隐忍之间选择，结尾发现追兵逼近。",
                target_mood="压抑",
                key_entities=["林照"],
            )
        ],
    )

    contract = QualityPreflightService.build_chapter_contract(
        plan,
        story_contract={"protagonist_goal": "查明家族覆灭真相", "must_carry_forward": ["玉佩"]},
        active_entities=[
            {
                "name": "林照",
                "memory_snapshot": {"canonical_profile": {"identity_role": "青云宗外门弟子"}},
            }
        ],
    )

    assert any("主角长期目标" in item for item in contract["canonical_constraints"])
    assert any("林照 固定身份" in item for item in contract["canonical_constraints"])
    assert any("玉佩" in item for item in contract["continuity_requirements"])
