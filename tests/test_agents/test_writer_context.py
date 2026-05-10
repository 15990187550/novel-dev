import pytest
from novel_dev.agents.writer_agent import WriterAgent
from novel_dev.schemas.context import (
    ChapterContext, ChapterPlan, BeatPlan, LocationContext,
    EntityState, NarrativeRelay, ForeshadowingContext, BeatContext,
    BeatWritingCard,
)


def _make_context(**overrides):
    defaults = dict(
        chapter_plan=ChapterPlan(
            chapter_number=1, title="Test", target_word_count=2000,
            beats=[BeatPlan(summary="开场", target_mood="压抑")],
        ),
        style_profile={"style_guide": "简洁有力"},
        worldview_summary="测试世界观",
        active_entities=[],
        location_context=LocationContext(current="默认"),
        timeline_events=[],
        pending_foreshadowings=[],
        beat_contexts=[],
    )
    defaults.update(overrides)
    return ChapterContext(**defaults)


class TestBuildSystemPrompt:
    def test_contains_style_and_rules(self):
        ctx = _make_context()
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_system_prompt(ctx, is_last=False)
        assert "简洁有力" in result
        assert "写作方向" in result
        assert "读者读感" in result
        assert "自然中文表达" in result

    def test_prompt_contains_low_ai_flavor_style_controls(self):
        ctx = _make_context(style_profile={})
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_system_prompt(ctx, is_last=False)
        assert "比喻服务画面和情绪" in result
        assert "抽象玄幻概念" in result
        assert "最有辨识度" in result
        assert "现代吐槽" in result
        assert "style_profile" in result

    def test_no_worldview_or_entities(self):
        ctx = _make_context(worldview_summary="这是一段很长的世界观描述" * 100)
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_system_prompt(ctx, is_last=False)
        assert "世界观描述" not in result

    def test_last_beat_has_hook_clause(self):
        ctx = _make_context()
        agent = WriterAgent.__new__(WriterAgent)
        result_last = agent._build_system_prompt(ctx, is_last=True)
        result_mid = agent._build_system_prompt(ctx, is_last=False)
        assert "章末钩子" in result_last
        assert "章末钩子" not in result_mid


class TestBuildContextMessage:
    def test_includes_chapter_plan(self):
        ctx = _make_context()
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[0], ctx, [], "", 0, 1, False
        )
        assert "Test" in result
        assert "开场" in result
        assert "当前节拍目标字数" in result
        assert "硬范围" in result

    def test_marks_future_beats_as_boundaries_not_content_to_write_now(self):
        ctx = _make_context(
            chapter_plan=ChapterPlan(
                chapter_number=1,
                title="Test",
                target_word_count=2000,
                beats=[
                    BeatPlan(summary="清晨山村，陆照入山采药，铺垫凡俗生活", target_mood="平静"),
                    BeatPlan(summary="发现泛黄古经，触碰瞬间识海剧震，大量残念碎片涌入", target_mood="惊变"),
                ],
            )
        )
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[0], ctx, [], "", 0, 2, False
        )
        assert "后续节拍作为停点参考" in result
        assert "当前节拍停在" in result
        assert "节拍2（后续停点参考）" in result
        assert "禁止提前写" not in result
        assert "禁止提前发生" not in result

    def test_includes_rewrite_plan_for_current_beat(self):
        ctx = _make_context(
            chapter_plan=ChapterPlan(
                chapter_number=1,
                title="Test",
                target_word_count=2000,
                beats=[
                    BeatPlan(summary="开场", target_mood="压抑"),
                    BeatPlan(summary="冲突", target_mood="紧张"),
                ],
            )
        )
        rewrite_plan = {
            "beat_issues": {
                1: {
                    "issues": [
                        {"dim": "plot_tension", "problem": "冲突不足", "suggestion": "增加追兵逼近"}
                    ]
                }
            }
        }
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[1], ctx, [], "", 1, 2, False, rewrite_plan
        )
        assert "本轮重写重点" in result
        assert "冲突不足" in result
        assert "增加追兵逼近" in result

    def test_rewrite_focus_includes_global_issues_without_other_beat_issues(self):
        rewrite_plan = {
            "summary_feedback": "整体需要更紧",
            "global_issues": [
                {"dim": "plot_tension", "problem": "全章冲突不足", "suggestion": "提高主线压力"}
            ],
            "beat_issues": [
                {"beat_index": 0, "issues": [{"dim": "humanity", "problem": "第一节拍生硬", "suggestion": "补动作"}]},
                {"beat_index": 1, "issues": [{"dim": "readability", "problem": "第二节拍绕", "suggestion": "缩短句子"}]},
            ],
        }
        result = WriterAgent._rewrite_focus_for_beat(rewrite_plan, 0)
        assert "全章冲突不足" in result
        assert "第一节拍生硬" in result
        assert "第二节拍绕" not in result

    def test_beat_target_word_count_prefers_beat_specific_target(self):
        beat = BeatPlan(summary="开场", target_mood="压抑", target_word_count=1200)
        ctx = _make_context(
            chapter_plan=ChapterPlan(chapter_number=1, title="Test", target_word_count=2000, beats=[beat])
        )
        assert WriterAgent._beat_target_word_count(ctx, 1, beat) == 1200

    @pytest.mark.asyncio
    async def test_enforce_beat_word_budget_rewrites_overlong_beat(self):
        beat = BeatPlan(summary="林照发现残页，必须藏起证据。", target_mood="紧张", target_word_count=100)
        ctx = _make_context(
            chapter_plan=ChapterPlan(chapter_number=1, title="Test", target_word_count=100, beats=[beat])
        )
        agent = WriterAgent.__new__(WriterAgent)

        async def fake_rewrite_angle(*args, **kwargs):
            return "林照发现残页，压住心口震动，选择先藏证据再离开。"

        agent._rewrite_angle = fake_rewrite_angle
        inner, beat_text = await agent._enforce_beat_word_budget(
            beat=beat,
            inner="长" * 180,
            context=ctx,
            relay_history=[],
            last_beat_text="",
            idx=0,
            total_beats=1,
            is_last=True,
            novel_id="n_budget",
            rewrite_plan={},
        )

        assert "选择先藏证据" in inner
        assert "<!--BEAT:0-->" in beat_text

    def test_includes_relay_history(self):
        ctx = _make_context()
        relay = NarrativeRelay(
            scene_state="秦风在山洞中",
            emotional_tone="紧张",
            new_info_revealed="发现密道",
            open_threads="密道通向哪里",
            next_beat_hook="火把快灭了",
        )
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[0], ctx, [relay], "", 1, 3, False
        )
        assert "秦风在山洞中" in result
        assert "火把快灭了" in result

    def test_includes_last_beat_text(self):
        ctx = _make_context()
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[0], ctx, [], "上一段正文内容", 1, 3, False
        )
        assert "上一段正文内容" in result

    def test_no_full_context_dump(self):
        ctx = _make_context(worldview_summary="很长的世界观" * 200)
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._build_context_message(
            ctx.chapter_plan.beats[0], ctx, [], "", 0, 1, False
        )
        assert len(result) < 5000
        assert "### 世界观约束" in result


class TestFallbackRetrieval:
    def test_matches_by_key_entities(self):
        ctx = _make_context(active_entities=[
            EntityState(entity_id="e1", name="秦风", type="character", current_state="武功高强的剑客"),
            EntityState(entity_id="e2", name="玉佩", type="item", current_state="古老的传家之宝"),
        ])
        beat = BeatPlan(summary="秦风拿起玉佩", target_mood="压抑", key_entities=["秦风"])
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._fallback_retrieval(beat, ctx)
        assert "秦风" in result
        assert "玉佩" not in result

    def test_empty_when_no_match(self):
        ctx = _make_context(active_entities=[
            EntityState(entity_id="e1", name="秦风", type="character", current_state="剑客"),
        ])
        beat = BeatPlan(summary="开场", target_mood="压抑", key_entities=["柳月"])
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._fallback_retrieval(beat, ctx)
        assert result == ""

    def test_uses_beat_context_when_index_provided(self):
        beat = BeatPlan(summary="开场", target_mood="压抑", key_entities=["秦风"])
        ctx = _make_context(
            chapter_plan=ChapterPlan(chapter_number=1, title="Test", target_word_count=2000, beats=[beat]),
            beat_contexts=[
                BeatContext(
                    beat_index=0,
                    beat=beat,
                    entities=[EntityState(entity_id="e1", name="秦风", type="character", current_state="受伤但清醒")],
                )
            ],
        )
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._fallback_retrieval(beat, ctx, 0)
        assert "当前节拍相关实体" in result
        assert "秦风" in result


class TestSchemaCompatibility:
    def test_chapter_context_roundtrip_with_beat_contexts(self):
        beat = BeatPlan(summary="开场", target_mood="压抑", key_entities=["秦风"], foreshadowings_to_embed=["玉佩发热"])
        context = _make_context(
            chapter_plan=ChapterPlan(chapter_number=1, title="Test", target_word_count=2000, beats=[beat]),
            pending_foreshadowings=[
                ForeshadowingContext(
                    id="fs1",
                    content="玉佩发热",
                    role_in_chapter="embed",
                    related_entity_names=["秦风"],
                    target_beat_index=0,
                )
            ],
            beat_contexts=[
                BeatContext(
                    beat_index=0,
                    beat=beat,
                    entities=[EntityState(entity_id="e1", name="秦风", type="character", current_state="受伤")],
                    foreshadowings=[
                        ForeshadowingContext(
                            id="fs1",
                            content="玉佩发热",
                            role_in_chapter="embed",
                            related_entity_names=["秦风"],
                            target_beat_index=0,
                        )
                    ],
                    guardrails=["不要无铺垫切换地点。"],
                )
            ],
        )
        roundtrip = ChapterContext(**context.model_dump())
        assert roundtrip.beat_contexts[0].entities[0].name == "秦风"
        assert roundtrip.pending_foreshadowings[0].id == "fs1"


class TestSelfCheck:
    def test_self_check_marks_missing_required_entity_when_no_reference_exists(self):
        beat = BeatPlan(summary="开场", target_mood="压抑", key_entities=["秦风"], foreshadowings_to_embed=["玉佩发热"])
        ctx = _make_context(
            chapter_plan=ChapterPlan(chapter_number=1, title="Test", target_word_count=2000, beats=[beat]),
            beat_contexts=[
                BeatContext(
                    beat_index=0,
                    beat=beat,
                    entities=[EntityState(entity_id="e1", name="秦风", type="character", current_state="受伤")],
                    foreshadowings=[
                        ForeshadowingContext(
                            id="fs1",
                            content="玉佩发热",
                            role_in_chapter="embed",
                            related_entity_names=["秦风"],
                            target_beat_index=0,
                        )
                    ],
                )
            ],
        )
        agent = WriterAgent.__new__(WriterAgent)
        text = "山风贴着石壁慢慢往前卷，洞口的天色被云层压得极低，滴水声在黑暗里反复回荡。这样的静默持续了很久，直到远处传来碎石滚落的轻响。"
        result = agent._self_check_beat(text, beat, ctx, 0)
        assert result.needs_rewrite is True
        assert "秦风" in result.missing_entities
        assert "玉佩发热" in result.missing_foreshadowings

    def test_self_check_allows_alias_and_natural_foreshadowing_surface(self):
        beat = BeatPlan(summary="秦风察觉玉佩异动", target_mood="压抑", key_entities=["秦风"], foreshadowings_to_embed=["玉佩发热"])
        ctx = _make_context(
            chapter_plan=ChapterPlan(chapter_number=1, title="Test", target_word_count=2000, beats=[beat]),
            beat_contexts=[
                BeatContext(
                    beat_index=0,
                    beat=beat,
                    entities=[EntityState(entity_id="e1", name="秦风", type="character", current_state="受伤", aliases=["秦师兄"])],
                    foreshadowings=[
                        ForeshadowingContext(
                            id="fs1",
                            content="玉佩发热",
                            role_in_chapter="embed",
                            related_entity_names=["秦风"],
                            target_beat_index=0,
                            surface_hint="掌心玉佩温热",
                        )
                    ],
                )
            ],
        )
        agent = WriterAgent.__new__(WriterAgent)
        text = "秦师兄扶着石壁停下脚步，掌心玉佩忽然温热了一瞬。他没有声张，只把指节慢慢收紧，继续听着洞外的风声。"
        result = agent._self_check_beat(text, beat, ctx, 0)
        assert result.needs_rewrite is False

    def test_self_check_allows_pronoun_reference_in_normal_length_text(self):
        beat = BeatPlan(summary="秦风穿过山洞", target_mood="压抑", key_entities=["秦风"])
        ctx = _make_context(
            chapter_plan=ChapterPlan(chapter_number=1, title="Test", target_word_count=2000, beats=[beat]),
            beat_contexts=[
                BeatContext(
                    beat_index=0,
                    beat=beat,
                    entities=[EntityState(entity_id="e1", name="秦风", type="character", current_state="受伤")],
                )
            ],
        )
        agent = WriterAgent.__new__(WriterAgent)
        text = "他扶着石壁慢慢往前走，胸口还在发闷，耳边只有风声和滴水声。这样的静默持续了很久，直到他停在洞口前，抬头看向外面的天色。"
        result = agent._self_check_beat(text, beat, ctx, 0)
        assert result.needs_rewrite is False

    def test_self_check_marks_short_missing_entity_text(self):
        beat = BeatPlan(summary="开场", target_mood="压抑", key_entities=["秦风"])
        ctx = _make_context(
            chapter_plan=ChapterPlan(chapter_number=1, title="Test", target_word_count=2000, beats=[beat]),
            beat_contexts=[
                BeatContext(
                    beat_index=0,
                    beat=beat,
                    entities=[EntityState(entity_id="e1", name="秦风", type="character", current_state="受伤")],
                )
            ],
        )
        agent = WriterAgent.__new__(WriterAgent)
        result = agent._self_check_beat("风很冷。", beat, ctx, 0)
        assert result.needs_rewrite is True
        assert "秦风" in result.missing_entities

    def test_self_check_marks_future_beat_event_leakage(self):
        beat0 = BeatPlan(summary="清晨山村，陆照入山采药，铺垫凡俗生活", target_mood="平静")
        beat1 = BeatPlan(summary="发现泛黄古经，触碰瞬间识海剧震，大量残念碎片涌入", target_mood="惊变")
        ctx = _make_context(
            chapter_plan=ChapterPlan(
                chapter_number=1,
                title="道经初现",
                target_word_count=2000,
                beats=[beat0, beat1],
            )
        )
        agent = WriterAgent.__new__(WriterAgent)
        text = "陆照扒开藤蔓，竟发现一本泛黄古经。手指刚触到书页，识海剧震，残念碎片潮水般涌入。"
        result = agent._self_check_beat(text, beat0, ctx, 0)
        assert result.needs_rewrite is True
        assert any("后续节拍" in item for item in result.contradictions)

    def test_self_check_marks_missing_last_beat_payoff_and_hook(self):
        beat = BeatPlan(
            summary="林照击倒监视者后搜查遗物发现密函，新的危险信号逼近。",
            target_mood="压迫",
            key_entities=["林照", "监视者"],
        )
        ctx = _make_context(
            chapter_plan=ChapterPlan(chapter_number=1, title="试炼惊变", target_word_count=1800, beats=[beat]),
            writing_cards=[
                BeatWritingCard(
                    beat_index=0,
                    objective="林照处理倒下的监视者。",
                    required_entities=["林照", "监视者"],
                    required_payoffs=["林照搜查遗物发现密函", "新的危险信号逼近"],
                    ending_hook="密函指向宗门内应，新的危险信号逼近。",
                    reader_takeaway="读者应明确知道林照拿到第一条线索，同时更大的危险正在靠近。",
                )
            ],
        )
        agent = WriterAgent.__new__(WriterAgent)

        result = agent._self_check_beat("林照盯着倒下的监视者，慢慢收回手。夜风从试炼林里吹过，他没有再多停留。", beat, ctx, 0)

        assert result.needs_rewrite is True
        assert any("未兑现" in item for item in result.contradictions)

    def test_self_check_allows_last_beat_payoff_and_hook_when_present(self):
        beat = BeatPlan(
            summary="林照击倒监视者后搜查遗物发现密函，新的危险信号逼近。",
            target_mood="压迫",
            key_entities=["林照", "监视者"],
        )
        ctx = _make_context(
            chapter_plan=ChapterPlan(chapter_number=1, title="试炼惊变", target_word_count=1800, beats=[beat]),
            writing_cards=[
                BeatWritingCard(
                    beat_index=0,
                    objective="林照处理倒下的监视者。",
                    required_entities=["林照", "监视者"],
                    required_payoffs=["林照搜查遗物发现密函", "新的危险信号逼近"],
                    ending_hook="密函指向宗门内应，新的危险信号逼近。",
                    reader_takeaway="读者应明确知道林照拿到第一条线索，同时更大的危险正在靠近。",
                )
            ],
        )
        agent = WriterAgent.__new__(WriterAgent)

        result = agent._self_check_beat("林照蹲下搜查监视者遗物，从衣襟暗袋里摸出一封密函。密函末尾的内应暗记让他后背发冷，林外随即传来第二声短哨，新的危险信号已经逼近。", beat, ctx, 0)

        assert result.needs_rewrite is False
