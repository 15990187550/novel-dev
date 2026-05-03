import json
from typing import List
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.review import ScoreResult
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.agents._log_helpers import log_agent_detail, preview_text
from novel_dev.services.log_service import logged_agent_step, log_service


class BeatScoreIssue(BaseModel):
    dim: str
    problem: str
    suggestion: str


class BeatScorePayload(BaseModel):
    beat_index: int
    scores: dict[str, int] = Field(default_factory=dict)
    issues: List[BeatScoreIssue] = Field(default_factory=list)


class CriticAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)

    @logged_agent_step("CriticAgent", "评审章节", node="review", task="review")
    async def review(self, novel_id: str, chapter_id: str) -> ScoreResult:
        log_service.add_log(novel_id, "CriticAgent", f"开始评审章节: {chapter_id}")
        state = await self.state_repo.get_state(novel_id)
        if not state:
            log_service.add_log(novel_id, "CriticAgent", "小说状态未找到", level="error")
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.REVIEWING.value:
            log_service.add_log(novel_id, "CriticAgent", f"当前阶段 {state.current_phase} 不允许评审", level="error")
            raise ValueError(f"Cannot review from phase {state.current_phase}")

        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")

        checkpoint = dict(state.checkpoint_data or {})
        context_data = checkpoint.get("chapter_context")
        if not context_data:
            raise ValueError("chapter_context missing in checkpoint_data")

        score_result = await self._generate_score(ch.raw_draft or "", context_data, novel_id)
        log_agent_detail(
            novel_id,
            "CriticAgent",
            f"章节评分完成：overall={score_result.overall}",
            node="critic_score",
            task="score_chapter",
            metadata={
                "chapter_id": chapter_id,
                "draft_chars": len(ch.raw_draft or ""),
                "beat_count": len(context_data.get("chapter_plan", {}).get("beats", [])),
                "overall": score_result.overall,
                "dimensions": {d.name: {"score": d.score, "comment": d.comment} for d in score_result.dimensions},
                "summary_feedback": score_result.summary_feedback,
                "per_dim_issues": [issue.model_dump() for issue in score_result.per_dim_issues[:12]],
            },
        )
        beat_scores = await self._generate_beat_scores(context_data, novel_id)
        log_agent_detail(
            novel_id,
            "CriticAgent",
            f"节拍评分完成：{len(beat_scores)} 个节拍",
            node="critic_beat_scores",
            task="score_beats",
            metadata={"chapter_id": chapter_id, "beat_scores": beat_scores[:12]},
        )

        await self.chapter_repo.update_scores(
            chapter_id,
            overall=score_result.overall,
            breakdown={d.name: {"score": d.score, "comment": d.comment} for d in score_result.dimensions},
            feedback={"summary": score_result.summary_feedback},
        )

        checkpoint["beat_scores"] = beat_scores
        checkpoint["critique_feedback"] = {
            "overall": score_result.overall,
            "summary": score_result.summary_feedback,
            "breakdown": {
                d.name: {"score": d.score, "comment": d.comment}
                for d in score_result.dimensions
            },
        }
        checkpoint["per_dim_issues"] = [issue.model_dump() for issue in score_result.per_dim_issues]

        overall = score_result.overall
        dimensions = {d.name: d.score for d in score_result.dimensions}

        red_line_failed = dimensions.get("consistency", 100) < 30 or dimensions.get("humanity", 100) < 40

        if overall < 70 or red_line_failed:
            attempt = checkpoint.get("draft_attempt_count", 0) + 1
            log_agent_detail(
                novel_id,
                "CriticAgent",
                f"评分不达标，退回 drafting：overall={overall}，尝试 {attempt}/3",
                node="critic_decision",
                task="review",
                status="failed",
                level="warning",
                metadata={
                    "chapter_id": chapter_id,
                    "overall": overall,
                    "red_line_failed": red_line_failed,
                    "dimensions": dimensions,
                    "attempt": attempt,
                    "target_phase": Phase.DRAFTING.value,
                    "reason": preview_text(score_result.summary_feedback, 300),
                },
            )
            if attempt >= 3:
                log_service.add_log(novel_id, "CriticAgent", "已达最大重写次数", level="error")
                raise RuntimeError("Max draft attempts exceeded")
            checkpoint["draft_attempt_count"] = attempt
            checkpoint["drafting_progress"] = {
                "beat_index": 0,
                "total_beats": len(context_data.get("chapter_plan", {}).get("beats", [])),
                "current_word_count": 0,
            }
            checkpoint.pop("relay_history", None)
            checkpoint["draft_rewrite_plan"] = self._build_draft_rewrite_plan(
                score_result,
                beat_scores,
                beat_count=len(context_data.get("chapter_plan", {}).get("beats", [])),
                rewrite_all=True,
            )
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.DRAFTING,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )
        else:
            checkpoint.pop("draft_attempt_count", None)
            # 进入新一轮编辑时重置 editor 尝试计数,确保本章 polish 循环独立
            checkpoint.pop("edit_attempt_count", None)
            log_agent_detail(
                novel_id,
                "CriticAgent",
                "评分通过，进入 editing 阶段",
                node="critic_decision",
                task="review",
                metadata={
                    "chapter_id": chapter_id,
                    "overall": overall,
                    "dimensions": dimensions,
                    "target_phase": Phase.EDITING.value,
                },
            )
            await self.director.save_checkpoint(
                novel_id,
                phase=Phase.EDITING,
                checkpoint_data=checkpoint,
                volume_id=state.current_volume_id,
                chapter_id=state.current_chapter_id,
            )

        return score_result

    def _build_draft_rewrite_plan(
        self,
        score_result: ScoreResult,
        beat_scores: List[dict],
        *,
        beat_count: int | None = None,
        rewrite_all: bool = False,
    ) -> dict:
        total_beats = max(beat_count or 0, len(beat_scores))
        beat_issues = [{"beat_index": idx, "issues": []} for idx in range(total_beats)]
        global_issues = []

        for issue in score_result.per_dim_issues:
            payload = issue.model_dump()
            beat_idx = payload.get("beat_idx")
            if isinstance(beat_idx, int) and 0 <= beat_idx < total_beats:
                beat_issues[beat_idx]["issues"].append(payload)
            else:
                global_issues.append(payload)

        for item in beat_scores:
            beat_idx = item.get("beat_index")
            if not isinstance(beat_idx, int) or not (0 <= beat_idx < total_beats):
                continue
            scores = item.get("scores") or {}
            issues = item.get("issues") or []
            for issue in issues:
                beat_issues[beat_idx]["issues"].append(issue)
            low_dims = [dim for dim, score in scores.items() if isinstance(score, (int, float)) and score < 70]
            for dim in low_dims:
                if not any(issue.get("dim") == dim for issue in beat_issues[beat_idx]["issues"] if isinstance(issue, dict)):
                    beat_issues[beat_idx]["issues"].append({
                        "dim": dim,
                        "problem": f"{dim} 评分低于 70",
                        "suggestion": "重写本节拍，优先补强该维度对应的冲突、细节或读感问题。",
                    })

        return {
            "rewrite_all": rewrite_all,
            "overall": score_result.overall,
            "summary_feedback": score_result.summary_feedback,
            "global_issues": global_issues,
            "beat_issues": beat_issues,
        }

    async def _generate_score(self, raw_draft: str, context_data: dict, novel_id: str = "") -> ScoreResult:
        log_agent_detail(
            novel_id,
            "CriticAgent",
            "章节评分输入已准备",
            node="critic_score_input",
            task="score_chapter",
            status="started",
            metadata={
                "draft_chars": len(raw_draft or ""),
                "draft_preview": preview_text(raw_draft, 300),
                "beat_count": len(context_data.get("chapter_plan", {}).get("beats", [])),
                "active_entity_count": len(context_data.get("active_entities", [])),
                "foreshadowing_count": len(context_data.get("pending_foreshadowings", [])),
            },
        )
        # Trim context to only what Critic needs, avoiding retrieval bloat
        trimmed_context = {
            "chapter_plan": context_data.get("chapter_plan", {}),
            "style_profile": context_data.get("style_profile", {}),
            "worldview_summary": context_data.get("worldview_summary", ""),
            "previous_chapter_summary": context_data.get("previous_chapter_summary", ""),
            "active_entities": [
                {"name": e.get("name"), "type": e.get("type"), "current_state": e.get("current_state", "")[:200]}
                for e in context_data.get("active_entities", [])
            ],
            "pending_foreshadowings": context_data.get("pending_foreshadowings", []),
        }
        prompt = (
            "你是一位严格的小说评审编辑。请根据以下章节草稿和章节上下文,"
            "按 rubric 给 6 个维度打分(0-100),并输出**可操作的具体问题**,"
            "以便 Editor 定点修改。返回严格符合 ScoreResult Schema 的 JSON。"
            "dimensions 数组必须包含全部 6 个维度。\n\n"
            "## 评分 Rubric(每个维度 4 档)\n"
            "### plot_tension(情节张力)\n"
            "- 85-100: 有明确冲突升级、赌注递进,场景间存在因果推动,章末钩子强\n"
            "- 70-84: 冲突存在但张力不稳,部分段落节奏拖沓\n"
            "- 50-69: 冲突模糊或重复同一量级冲突,无明显升级\n"
            "- <50: 无冲突/流水账/情节停滞\n\n"
            "### characterization(人物塑造)\n"
            "- 85-100: 行为与动机自洽,有独特语言/行为标记,可看到内在选择\n"
            "- 70-84: 行为基本合理,但缺少区分度,或动机交代略薄\n"
            "- 50-69: 行为偏符号化,靠旁白解释情感\n"
            "- <50: 工具人/OOC/与设定矛盾\n\n"
            "### readability(可读性)\n"
            "- 85-100: 句式多变,场景/对话/心理节奏合理,无冗余\n"
            "- 70-84: 可读但有长句堆砌、重复用词、比喻密度略高\n"
            "- 50-69: 大量书面语/AI 腔,段落结构雷同,比喻密度失控,抽象玄幻词连环复读,"
            "感官平均用力,或出现未授权英文/拼音/网络缩写/UI 术语原文\n"
            "- <50: 生硬、难以连读\n\n"
            "### consistency(设定一致性)\n"
            "- 85-100: 与 worldview/entities/前章完全一致\n"
            "- 70-84: 有小瑕疵但不影响主线\n"
            "- 50-69: 存在 1-2 处明显冲突(称谓、能力、关系)\n"
            "- <50: 与核心设定严重矛盾\n\n"
            "### humanity(人味/沉浸感)\n"
            "- 85-100: 对话自然、有潜台词,内心戏节制,能『显示不说』\n"
            "- 70-84: 偶有 AI 腔词汇、过度解释情感、现代吐槽突兀或奇观描写偏模板\n"
            "- 50-69: 明显 AI 腔、总结式心理描写、对话扁平、模板化奇遇/入体/传承演出,"
            "人物被抽象光影和设定说明淹没\n"
            "- <50: 通篇 AI 味、读起来像设定说明\n\n"
            "### hook_strength(章末钩子强度,仅评价最后一个 beat)\n"
            "- 85-100: 结尾有强悬念/反转/赌注升级/情绪爆点,能拉读者进下一章\n"
            "- 70-84: 有收束但钩子偏弱,下一步走向过于可预测\n"
            "- 50-69: 章末平淡收束或用总结句收尾\n"
            "- <50: 章末无悬念、信息倾倒式结尾、或本章未呼应已埋伏笔\n\n"
            "## 输出要求(非常重要)\n"
            "1. per_dim_issues:**每一个低于 75 分的维度**必须至少给 1 个具体问题,"
            "格式为 {dim, beat_idx, problem, suggestion}。problem 要写具体(例:"
            "『第 2 段对话中,A 的语气与其『沉默寡言』设定矛盾』),禁止抽象标签(『对话不自然』)。\n"
            "2. hook_strength 低于 75 时,per_dim_issues 中必须指定 beat_idx=最后一个 beat 的索引,"
            "problem 写清楚章末为什么不够勾人,suggestion 给出可执行的改写方向。\n"
            "3. beat_idx 指向 chapter_plan.beats 的索引,跨 beat 的整章问题填 null。\n"
            "4. suggestion 要给可直接执行的改写方向(例:『改为 A 用一个动作代替解释』)。\n"
            "5. 语言红线:禁止英文、拼音、网络缩写和 UI 术语原文(如 snooze/APP/OK)。"
            "如果草稿出现这类词,readability 必须低于 75,并在 per_dim_issues 写出原词和中文化改写建议。\n"
            "6. AI 味问题必须具体定位:连续比喻、抽象玄幻词、感官平均用力、模板化奇遇、现代吐槽突兀。"
            "suggestion 必须给可执行动作,例如『删减连续三处像字比喻,只保留最有辨识度的一处』。\n"
            "7. summary_feedback 300 字内,总结三条最影响读感的问题。\n\n"
            f"### 章节上下文\n{json.dumps(trimmed_context, ensure_ascii=False)}\n\n"
            f"### 草稿\n{raw_draft}\n\n"
            "请评分:"
        )
        return await call_and_parse_model(
            "CriticAgent", "score_chapter", prompt, ScoreResult, novel_id=novel_id
        )

    async def review_standalone(
        self,
        novel_id: str,
        chapter_id: str,
        context_data: dict,
    ) -> tuple[ScoreResult, dict]:
        log_service.add_log(novel_id, "CriticAgent", f"开始独立评审章节: {chapter_id}")
        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")
        score_result = await self._generate_score(ch.raw_draft or "", context_data, novel_id)
        beat_scores = await self._generate_beat_scores(context_data, novel_id)
        await self.chapter_repo.update_scores(
            chapter_id,
            overall=score_result.overall,
            breakdown={d.name: {"score": d.score, "comment": d.comment} for d in score_result.dimensions},
            feedback={"summary": score_result.summary_feedback},
        )
        checkpoint = {
            "chapter_context": context_data,
            "beat_scores": beat_scores,
            "critique_feedback": {
                "overall": score_result.overall,
                "summary": score_result.summary_feedback,
                "breakdown": {
                    d.name: {"score": d.score, "comment": d.comment}
                    for d in score_result.dimensions
                },
            },
            "per_dim_issues": [issue.model_dump() for issue in score_result.per_dim_issues],
        }
        return score_result, checkpoint

    async def _generate_beat_scores(self, context_data: dict, novel_id: str = "") -> List[dict]:
        log_service.add_log(novel_id, "CriticAgent", "开始生成节拍评分")
        beats = context_data.get("chapter_plan", {}).get("beats", [])
        if not beats:
            return []
        # Only pass what beat-level scoring needs (avoid retrieval bloat)
        trimmed = {
            "chapter_plan": context_data.get("chapter_plan", {}),
            "style_profile": context_data.get("style_profile", {}),
            "worldview_summary": context_data.get("worldview_summary", ""),
            "previous_chapter_summary": context_data.get("previous_chapter_summary", ""),
            "active_entities": [
                {"name": e.get("name"), "type": e.get("type"), "current_state": e.get("current_state", "")[:200]}
                for e in context_data.get("active_entities", [])
            ],
            "pending_foreshadowings": context_data.get("pending_foreshadowings", []),
        }
        prompt = (
            "你是一位小说评审专家。请根据以下节拍列表和章节上下文,"
            "为**每一个节拍**给出 plot_tension 和 humanity 评分(0-100)及具体问题清单。\n\n"
            "## 评分 rubric(节拍级)\n"
            "- plot_tension >=85: 本节拍有明确推进(冲突/揭示/决定),并引出下一步不确定性\n"
            "- plot_tension 70-84: 有推进但缺少不确定性或节拍过长稀释张力\n"
            "- plot_tension <70: 无推进/重复前文/场景铺陈过多无事件\n"
            "- humanity >=85: 对话/动作自然,情感通过细节呈现,无 AI 腔\n"
            "- humanity 70-84: 有少量 AI 腔、心理直述、比喻过密或现代吐槽突兀,瑕疵不影响读感\n"
            "- humanity <70: 书面语堆砌、总结式情感、对话扁平、抽象玄幻词复读、奇观堆叠或模板化奇遇\n\n"
            "## 输出格式\n"
            "JSON 数组,每元素:\n"
            '{"beat_index": 0, "scores": {"plot_tension": 75, "humanity": 75}, '
            '"issues": [{"dim": "humanity", "problem": "第2句用『油然而生』直述情感", '
            '"suggestion": "改为 A 手指掐进掌心这类动作细节"}]}\n'
            "要求:\n"
            "- scores 低于 75 的维度必须在 issues 中至少给 1 条具体问题(problem 写具体,不要抽象标签)\n"
            "- suggestion 必须可直接执行(具体动作/替换方向)\n"
            "- 节拍全部达标时 issues 可为空数组\n"
            f"\n章节上下文:\n{json.dumps(trimmed, ensure_ascii=False)}\n\n"
            "请评分:"
        )
        result = await call_and_parse_model(
            "CriticAgent", "score_beats", prompt, list[BeatScorePayload], novel_id=novel_id
        )
        return [item.model_dump() for item in result]
