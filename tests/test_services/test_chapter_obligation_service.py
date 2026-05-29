from novel_dev.schemas.context import BeatPlan, BeatWritingCard, ChapterContext, ChapterPlan, LocationContext
from novel_dev.services.chapter_obligation_service import ChapterObligationService


def test_chapter_obligation_service_builds_contract_from_existing_context_assets():
    context = ChapterContext(
        chapter_plan=ChapterPlan(
            chapter_number=2,
            title="压力转向",
            target_word_count=1200,
            beats=[
                BeatPlan(summary="主角带着旧钥匙进入封存房间。", key_entities=["主角", "旧钥匙"]),
            ],
            beat_boundary_cards=[
                {
                    "beat_index": 0,
                    "must_cover": ["旧钥匙必须造成可见后果"],
                    "forbidden_materials": ["不得提前揭示房间主人身份"],
                }
            ],
        ),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="封存房间"),
        timeline_events=[],
        pending_foreshadowings=[],
        story_contract={"must_carry_forward": ["旧钥匙"]},
        writing_cards=[
            BeatWritingCard(
                beat_index=0,
                objective="主角确认旧钥匙不是普通钥匙",
                required_entities=["主角", "旧钥匙"],
                required_facts=["旧钥匙仍在主角手里"],
                required_payoffs=["旧钥匙必须触发一次当场变化"],
                forbidden_future_events=["房间主人真实身份留到后续章节"],
            )
        ],
    )

    contract = ChapterObligationService.build_from_context(context)

    assert "主角确认旧钥匙不是普通钥匙" in contract["must_hit_now"]
    assert "旧钥匙必须触发一次当场变化" in contract["must_hit_now"]
    assert "旧钥匙必须造成可见后果" in contract["must_hit_now"]
    assert "旧钥匙仍在主角手里" in contract["must_preserve"]
    assert "旧钥匙" in contract["must_preserve"]
    assert "房间主人真实身份留到后续章节" in contract["forbidden_crossings"]
    assert "不得提前揭示房间主人身份" in contract["forbidden_crossings"]


def test_chapter_obligation_prompt_block_uses_contract_language_not_fixed_plot_formula():
    block = ChapterObligationService.render_prompt_block(
        {
            "must_hit_now": ["让当前线索产生可见后果"],
            "must_preserve": ["关键物件仍由主角持有"],
            "can_defer": ["长期答案可以延后"],
            "forbidden_crossings": ["不得提前确认后续真相"],
        }
    )

    assert "### 章节义务合同" in block
    assert "本章必须让读者看见" in block
    assert "必须出现新风险" not in block
    assert "必须短对话" not in block


def test_chapter_obligation_filters_abstract_meta_hook_from_must_hit_now():
    context = ChapterContext(
        chapter_plan=ChapterPlan(
            chapter_number=3,
            title="抽象章末",
            target_word_count=1200,
            beats=[
                BeatPlan(
                    summary="主角握住残页离开功法阁；与“外门困境”直接相关的未解变化压到章末，逼得主角下一步继续处理。",
                    target_mood="压迫",
                    key_entities=["主角", "残页", "功法阁"],
                )
            ],
        ),
        style_profile={},
        worldview_summary="",
        active_entities=[],
        location_context=LocationContext(current="功法阁"),
        timeline_events=[],
        pending_foreshadowings=[],
        writing_cards=[
            BeatWritingCard(
                beat_index=0,
                objective="主角离开功法阁",
                ending_hook="与“外门困境”直接相关的未解变化压到章末，逼得主角下一步继续处理",
                required_payoffs=["与“外门困境”直接相关的未解变化压到章末，逼得主角下一步继续处理"],
                ending_driver_candidates=["残页在主角手里出现可感知变化"],
            )
        ],
    )

    contract = ChapterObligationService.build_from_context(context)
    block = ChapterObligationService.render_prompt_block(contract)

    assert "残页在主角手里出现可感知变化" in block
    assert "外门困境" not in block
    assert "下一步继续处理" not in block
