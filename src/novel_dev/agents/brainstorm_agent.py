import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.outline import SynopsisData, SynopsisScoreResult, SynopsisVolumeOutline
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.services.narrative_constraint_service import NarrativeConstraintBuilder
from novel_dev.services.knowledge_domain_service import KnowledgeDomainService
from novel_dev.services.log_service import logged_agent_step, log_service
from novel_dev.services.story_quality_service import StoryQualityService
from novel_dev.services.genre_template_service import GenreTemplateService


class BrainstormAgent:
    # self-review 阈值:overall 达标且关键维度(具体度、对抗具体度、转折数量)达底线
    OVERALL_THRESHOLD = 75
    KEY_DIM_THRESHOLDS = {
        "logline_specificity": 75,
        "conflict_concreteness": 75,
        "structural_turns": 70,
    }
    MAX_REVISE_ATTEMPTS = 3
    VOLUME_OUTLINE_BATCH_SIZE = 6

    def __init__(self, session: AsyncSession):
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.director = NovelDirector(session)
        self.constraint_builder = NarrativeConstraintBuilder()
        self.knowledge_domain_service = KnowledgeDomainService(session)

    def _log_progress(
        self,
        novel_id: str,
        message: str,
        *,
        node: str,
        task: str,
        status: str,
        level: str = "info",
        metadata: dict | None = None,
    ) -> None:
        log_service.add_log(
            novel_id,
            "BrainstormAgent",
            message,
            level=level,
            event="agent.progress",
            status=status,
            node=node,
            task=task,
            metadata=metadata,
        )

    @logged_agent_step("BrainstormAgent", "生成小说大纲", node="brainstorm", task="brainstorm")
    async def brainstorm(self, novel_id: str) -> SynopsisData:
        self._log_progress(
            novel_id,
            "开始生成小说大纲",
            node="brainstorm",
            task="brainstorm",
            status="started",
        )
        self._log_progress(
            novel_id,
            "读取设定资料",
            node="source_documents",
            task="load_sources",
            status="started",
        )
        docs = await self.doc_repo.get_current_by_type(novel_id, "worldview")
        docs += await self.doc_repo.get_current_by_type(novel_id, "setting")
        docs += await self.doc_repo.get_current_by_type(novel_id, "concept")

        if not docs:
            self._log_progress(
                novel_id,
                "未找到设定文档",
                node="source_documents",
                task="load_sources",
                status="failed",
                level="error",
            )
            raise ValueError("No source documents found for brainstorming")

        combined = "\n\n".join(f"[{d.doc_type}]\n{d.content}" for d in docs)
        self._log_progress(
            novel_id,
            f"已读取 {len(docs)} 份设定文档，开始生成 synopsis",
            node="source_documents",
            task="load_sources",
            status="succeeded",
            metadata={"document_count": len(docs), "source_chars": len(combined)},
        )
        synopsis_data = await self._generate_and_refine(combined, novel_id)
        synopsis_text = self._format_synopsis_text(synopsis_data)

        self._log_progress(
            novel_id,
            "保存总纲文档",
            node="document_save",
            task="save_synopsis",
            status="started",
            metadata={"title": synopsis_data.title},
        )
        doc = await self.doc_repo.create(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type="synopsis",
            title=synopsis_data.title,
            content=synopsis_text,
        )
        self._log_progress(
            novel_id,
            f"总纲文档已保存: {doc.id}",
            node="document_save",
            task="save_synopsis",
            status="succeeded",
            metadata={"doc_id": doc.id, "content_chars": len(synopsis_text)},
        )

        checkpoint = {}
        state = await self.state_repo.get_state(novel_id)
        if state and state.checkpoint_data:
            checkpoint = dict(state.checkpoint_data)

        checkpoint["synopsis_data"] = synopsis_data.model_dump()
        checkpoint["synopsis_doc_id"] = doc.id

        self._log_progress(
            novel_id,
            "写入总纲 checkpoint 并推进到卷规划",
            node="checkpoint",
            task="save_checkpoint",
            status="started",
            metadata={"phase": Phase.VOLUME_PLANNING.value},
        )
        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.VOLUME_PLANNING,
            checkpoint_data=checkpoint,
            volume_id=None,
            chapter_id=None,
        )
        self._log_progress(
            novel_id,
            f"大纲生成完成，标题: {synopsis_data.title}，进入 volume_planning 阶段",
            node="checkpoint",
            task="save_checkpoint",
            status="succeeded",
            metadata={
                "phase": Phase.VOLUME_PLANNING.value,
                "estimated_volumes": synopsis_data.estimated_volumes,
                "estimated_total_chapters": synopsis_data.estimated_total_chapters,
                "volume_outlines": len(synopsis_data.volume_outlines),
            },
        )

        return synopsis_data

    async def _generate_and_refine(self, combined_text: str, novel_id: str) -> SynopsisData:
        self._log_progress(
            novel_id,
            "生成总纲草稿",
            node="synopsis_draft",
            task="generate_synopsis",
            status="started",
            metadata={"source_chars": len(combined_text)},
        )
        synopsis = await self._generate_synopsis(combined_text, novel_id)
        self._log_progress(
            novel_id,
            f"总纲草稿生成完成: {synopsis.title}",
            node="synopsis_draft",
            task="generate_synopsis",
            status="succeeded",
            metadata={
                "estimated_volumes": synopsis.estimated_volumes,
                "estimated_total_chapters": synopsis.estimated_total_chapters,
                "volume_outlines": len(synopsis.volume_outlines),
            },
        )
        for attempt in range(self.MAX_REVISE_ATTEMPTS):
            self._log_progress(
                novel_id,
                f"开始第 {attempt + 1} 次总纲评分",
                node="synopsis_review",
                task="score_synopsis",
                status="started",
                metadata={"attempt": attempt + 1, "max_attempts": self.MAX_REVISE_ATTEMPTS},
            )
            score = await self._score_synopsis(synopsis, novel_id)
            self._log_progress(
                novel_id,
                f"第 {attempt + 1} 次评分完成: overall={score.overall}",
                node="synopsis_review",
                task="score_synopsis",
                status="succeeded",
                metadata={
                    "attempt": attempt + 1,
                    "overall": score.overall,
                    "logline_specificity": score.logline_specificity,
                    "conflict_concreteness": score.conflict_concreteness,
                    "character_arc_depth": score.character_arc_depth,
                    "structural_turns": score.structural_turns,
                    "hook_strength": score.hook_strength,
                },
            )
            if self._is_acceptable(score):
                self._log_progress(
                    novel_id,
                    f"总纲评分通过，overall={score.overall}",
                    node="synopsis_review",
                    task="score_synopsis",
                    status="accepted",
                    metadata={"attempt": attempt + 1, "overall": score.overall},
                )
                return self._with_review_status(
                    synopsis,
                    score=score,
                    status="accepted",
                    reason="总纲评分通过。",
                    attempt=attempt + 1,
                )
            self._log_progress(
                novel_id,
                f"评分未通过，开始第 {attempt + 1} 次修订",
                node="synopsis_revision",
                task="revise_synopsis",
                status="started",
                metadata={"attempt": attempt + 1, "overall": score.overall},
            )
            synopsis = await self._revise_synopsis(synopsis, score, combined_text, novel_id)
            self._log_progress(
                novel_id,
                f"第 {attempt + 1} 次总纲修订完成: {synopsis.title}",
                node="synopsis_revision",
                task="revise_synopsis",
                status="succeeded",
                metadata={
                    "attempt": attempt + 1,
                    "estimated_volumes": synopsis.estimated_volumes,
                    "volume_outlines": len(synopsis.volume_outlines),
                },
            )
        self._log_progress(
            novel_id,
            f"已达最大修订次数 {self.MAX_REVISE_ATTEMPTS}，返回最后一版",
            node="synopsis_review",
            task="score_synopsis",
            status="max_attempts_reached",
            level="warning",
            metadata={"max_attempts": self.MAX_REVISE_ATTEMPTS},
        )
        final_score = await self._score_synopsis(synopsis, novel_id)
        return self._with_review_status(
            synopsis,
            score=final_score,
            status="max_attempts_reached",
            reason="已达最大自动修订次数，请在大纲工作台人工调整。",
            attempt=self.MAX_REVISE_ATTEMPTS,
        )

    def _with_review_status(
        self,
        synopsis: SynopsisData,
        *,
        score: SynopsisScoreResult,
        status: str,
        reason: str,
        attempt: int,
    ) -> SynopsisData:
        quality_report = StoryQualityService.evaluate_synopsis(synopsis)
        return synopsis.model_copy(update={
            "review_status": {
                "status": status,
                "reason": reason,
                "attempt": attempt,
                "score": score.model_dump(),
                "synopsis_quality_report": quality_report.model_dump(),
                "optimization_suggestion": self._build_score_feedback(score),
            }
        })

    def _is_acceptable(self, score: SynopsisScoreResult) -> bool:
        if score.overall < self.OVERALL_THRESHOLD:
            return False
        for dim, floor in self.KEY_DIM_THRESHOLDS.items():
            if getattr(score, dim, 100) < floor:
                return False
        return True

    def _build_score_feedback(self, score: SynopsisScoreResult) -> str:
        lines = []
        if score.overall < self.OVERALL_THRESHOLD:
            lines.append(f"overall={score.overall} 低于下限 {self.OVERALL_THRESHOLD}")
        for dim, floor in self.KEY_DIM_THRESHOLDS.items():
            val = getattr(score, dim, 100)
            if val < floor:
                lines.append(f"{dim}={val} 低于下限 {floor}")
        if score.summary_feedback:
            lines.append(f"评审意见: {score.summary_feedback}")
        return "\n".join(lines)

    async def _score_synopsis(self, synopsis: SynopsisData, novel_id: str) -> SynopsisScoreResult:
        prompt = (
            "你是一位严格的小说大纲评审。请按 rubric 给下面的 SynopsisData 多维度打分,"
            "返回严格符合 SynopsisScoreResult Schema 的 JSON。\n\n"
            "## Rubric\n"
            "- logline_specificity >=75: logline 同时包含角色、欲望、阻力、赌注\n"
            "- logline_specificity <75: logline 偏向设定描述或情绪标签,缺具体对抗\n"
            "- conflict_concreteness >=75: core_conflict 为具体对抗关系(谁 vs 谁,为了什么)\n"
            "- conflict_concreteness <75: core_conflict 是抽象标签(如『正邪对立』)\n"
            "- character_arc_depth >=75: 主要角色 key_turning_points>=3 且含内在转变\n"
            "- structural_turns >=70: milestones 中可识别出至少 4 个改变处境的转折\n"
            "- hook_strength >=75: milestones 结尾能引出续作的开放性悬念\n\n"
            "## 输出\n"
            "严格 JSON,summary_feedback 300 字内,指明最需要改的 2-3 点。\n\n"
            f"### SynopsisData\n{synopsis.model_dump_json()}\n\n请打分:"
        )
        return await call_and_parse_model(
            "BrainstormAgent", "score_synopsis", prompt, SynopsisScoreResult, novel_id=novel_id
        )

    async def _revise_synopsis(
        self,
        synopsis: SynopsisData,
        score: SynopsisScoreResult,
        combined_text: str,
        novel_id: str,
    ) -> SynopsisData:
        feedback = self._build_score_feedback(score)
        prompt = (
            "你是一位小说大纲修订专家。请根据以下评审反馈对 SynopsisData 进行定点修订,"
            "返回严格符合 SynopsisData Schema 的 JSON。保留原设定的核心方向,只针对"
            "未达标维度做结构/写法层面的改进,但不要偏离核心设定、人物基础关系与主要矛盾。\n\n"
            "## 修订重点映射\n"
            "- logline_specificity 低:把 logline 改写为『角色+欲望+阻力+赌注』一句话\n"
            "- conflict_concreteness 低:把 core_conflict 写成具体对抗关系,指名对手\n"
            "- character_arc_depth 低:为主要角色补齐 ≥3 个 key_turning_points,并含一次内在转变\n"
            "- structural_turns 低:在 milestones 里补齐可识别的转折点描述\n"
            "- hook_strength 低:在最后一个 milestone 的 climax_event 后加开放性悬念\n\n"
            f"### 原 SynopsisData\n{synopsis.model_dump_json()}\n\n"
            f"### 评审反馈\n{feedback}\n\n"
            f"### 参考原设定(仅供对齐世界观,不要逐字照抄)\n{combined_text[:4000]}\n\n"
            "请输出修订后的 SynopsisData JSON:"
        )
        return await call_and_parse_model(
            "BrainstormAgent", "revise_synopsis", prompt, SynopsisData, novel_id=novel_id
        )

    async def _generate_synopsis(self, combined_text: str, novel_id: str) -> SynopsisData:
        self._log_progress(
            novel_id,
            "采用两阶段生成总纲: 先生成顶层总纲,再分批生成卷级概要",
            node="synopsis_generation_plan",
            task="generate_synopsis",
            status="started",
            metadata={"batch_size": self.VOLUME_OUTLINE_BATCH_SIZE, "source_chars": len(combined_text)},
        )
        top_level = await self._generate_top_level_synopsis(combined_text, novel_id)
        self._log_progress(
            novel_id,
            f"开始分批生成 {top_level.estimated_volumes} 个卷级概要",
            node="synopsis_volume_outlines",
            task="generate_synopsis_volume_outlines",
            status="started",
            metadata={
                "estimated_volumes": top_level.estimated_volumes,
                "estimated_total_chapters": top_level.estimated_total_chapters,
                "batch_size": self.VOLUME_OUTLINE_BATCH_SIZE,
            },
        )
        volume_outlines = await self._generate_volume_outlines(combined_text, top_level, novel_id)
        result = top_level.model_copy(update={"volume_outlines": volume_outlines})
        await self.knowledge_domain_service.suggest_scopes_from_synopsis(novel_id, result)
        self._log_progress(
            novel_id,
            f"synopsis 生成完成: {result.title}",
            node="synopsis_draft",
            task="generate_synopsis",
            status="llm_result_ready",
            metadata={
                "themes": len(result.themes),
                "character_arcs": len(result.character_arcs),
                "milestones": len(result.milestones),
                "volume_outlines": len(result.volume_outlines),
            },
        )
        self._log_progress(
            novel_id,
            "两阶段总纲生成完成,已组装顶层总纲与卷级概要",
            node="synopsis_generation_plan",
            task="generate_synopsis",
            status="succeeded",
            metadata={
                "estimated_volumes": result.estimated_volumes,
                "volume_outlines": len(result.volume_outlines),
            },
        )
        return result

    async def _build_genre_prompt_block(self, novel_id: str, task_name: str) -> str:
        if not novel_id:
            return ""
        genre_template = await GenreTemplateService(self.session).resolve(
            novel_id,
            "BrainstormAgent",
            task_name,
        )
        genre_block = genre_template.render_prompt_block(
            "source_rules",
            "setting_rules",
            "structure_rules",
            "quality_rules",
            "forbidden_rules",
        )
        if not genre_block:
            genre_block = "使用通用类型约束。"
        return f"## 类型模板约束\n{genre_block}\n\n"

    async def _generate_top_level_synopsis(self, combined_text: str, novel_id: str) -> SynopsisData:
        self._log_progress(
            novel_id,
            "开始生成顶层总纲",
            node="synopsis_top_level",
            task="generate_synopsis_top_level",
            status="started",
            metadata={"source_chars": len(combined_text)},
        )
        source_text = combined_text[:12000]
        genre_prompt_block = await self._build_genre_prompt_block(
            novel_id,
            "generate_synopsis_top_level",
        )
        prompt = (
            "你是一位资深商业小说大纲生成专家,面向网文连载读者。"
            "根据用户提供的设定文档,先生成顶层总纲。卷级概要会在下一步分批生成,"
            "本步骤不要展开每一卷。"
            "返回严格符合指定 JSON Schema 的数据。\n\n"
            "## 结构要求(在里程碑与人物弧中体现)\n"
            "1. 采用三幕式或更复杂结构,整部故事至少含 4 个能改变主角处境的转折点,"
            "每一幕至少 1 个,转折尽量由角色选择驱动(而非纯外力)。\n"
            "2. 节奏:里程碑分布上,平均每 3 章左右有 1 个小高潮,每卷有 1 个卷级高潮。\n"
            "3. 伏笔:character_arcs 与 milestones 合计给出 ≥4 个可回收的悬念点,"
            "每个悬念尽量在 1 卷内给出回收线索。\n"
            "4. 钩子:整部故事结尾带开放性钩子,能引出下一卷或续作的核心悬念。\n"
            "5. 人物弧光:主要角色 key_turning_points ≥3 个,且包含一次内在转变"
            "(信念/价值观/关系的重要变化)。\n"
            "6. 本步骤 volume_outlines 必须返回空数组 [],不要写任何卷级概要、章节列表或 beats。\n\n"
            "## Schema 写法规范\n"
            "- logline:写成『角色 + 欲望 + 阻力 + 赌注』的一句话,避免把 logline 写成 setting 说明。\n"
            "- core_conflict:写成来自导入资料的具体对抗关系,例如『角色/阵营A vs 角色/阵营B 围绕核心目标的冲突』,"
            "避免抽象标签(如『理念冲突』『命运考验』),也不要引入资料外的势力、地点或事件。\n"
            "- milestones.climax_event:写一个可被后续章节直接展开的具体事件,不要只写情绪。\n\n"
            f"{genre_prompt_block}"
            "## 输出字段约束(必须严格遵守)\n"
            "只允许以下顶层字段,禁止输出任何额外字段:\n"
            '{"title","logline","core_conflict","themes","character_arcs","milestones",'
            '"estimated_volumes","estimated_total_chapters","estimated_total_words",'
            '"volume_outlines","entity_highlights","relationship_highlights"}\n'
            "- title: 字符串\n"
            "- logline: 字符串\n"
            "- core_conflict: 字符串\n"
            "- themes: 字符串数组,控制在 3-6 个\n"
            "- character_arcs: 数组,每项只包含 name / arc_summary / key_turning_points 三个字段\n"
            "- milestones: 数组,每项只包含 act / summary / climax_event 三个字段\n"
            "- estimated_volumes: 整数\n"
            "- estimated_total_chapters: 整数\n"
            "- estimated_total_words: 整数\n"
            "- volume_outlines: 本步骤必须是空数组 [],卷级概要由下一步分批生成\n"
            "- entity_highlights: 对象,可选键包括 characters / factions / locations / items,值均为字符串数组\n"
            "- relationship_highlights: 字符串数组,每项描述一个关键关系推进\n"
            "不要输出 worldview_summary、three_act_structure、volume_hooks、suspense_plants、chapters、beats 等任何额外结构。\n"
            "不要输出 Markdown、代码块、解释文字或字段注释,只返回单个 JSON 对象。\n\n"
            f"{source_text}"
        )
        result = await call_and_parse_model(
            "BrainstormAgent", "generate_synopsis_top_level", prompt, SynopsisData, novel_id=novel_id
        )
        self._log_progress(
            novel_id,
            f"顶层总纲生成完成: {result.title}",
            node="synopsis_draft",
            task="generate_synopsis_top_level",
            status="succeeded",
            metadata={
                "themes": len(result.themes),
                "character_arcs": len(result.character_arcs),
                "milestones": len(result.milestones),
                "estimated_volumes": result.estimated_volumes,
                "estimated_total_chapters": result.estimated_total_chapters,
            },
        )
        return result.model_copy(update={"volume_outlines": []})

    async def _generate_volume_outlines(
        self,
        combined_text: str,
        synopsis: SynopsisData,
        novel_id: str,
    ) -> list[SynopsisVolumeOutline]:
        total = max(0, int(synopsis.estimated_volumes or 0))
        if total <= 0:
            return []

        source_text = combined_text[:6000]
        outlines: list[SynopsisVolumeOutline] = []
        for start in range(1, total + 1, self.VOLUME_OUTLINE_BATCH_SIZE):
            end = min(total, start + self.VOLUME_OUTLINE_BATCH_SIZE - 1)
            self._log_progress(
                novel_id,
                f"生成卷级概要 {start}-{end}/{total}",
                node="synopsis_volume_outlines",
                task="generate_synopsis_volume_outlines_batch",
                status="started",
                metadata={"start": start, "end": end, "estimated_volumes": total},
            )
            try:
                constraints = self.constraint_builder.build_for_volume_batch(
                    synopsis=synopsis,
                    start=start,
                    end=end,
                    source_text=source_text,
                )
                self._log_progress(
                    novel_id,
                    f"已构建卷级概要约束包 {start}-{end}/{total}",
                    node="synopsis_volume_constraints",
                    task="build_active_constraint_context",
                    status="succeeded",
                    metadata={"start": start, "end": end, "estimated_volumes": total},
                )
                batch = await self._generate_volume_outline_batch(
                    source_text=source_text,
                    synopsis=synopsis,
                    constraints=constraints,
                    start=start,
                    end=end,
                    novel_id=novel_id,
                )
            except Exception as exc:
                self._log_progress(
                    novel_id,
                    f"卷级概要 {start}-{end}/{total} 生成失败: {exc}",
                    node="synopsis_volume_outlines",
                    task="generate_synopsis_volume_outlines_batch",
                    status="failed",
                    level="error",
                    metadata={
                        "start": start,
                        "end": end,
                        "estimated_volumes": total,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                raise
            outlines.extend(batch)
            self._log_progress(
                novel_id,
                f"卷级概要 {start}-{end}/{total} 生成完成",
                node="synopsis_volume_outlines",
                task="generate_synopsis_volume_outlines_batch",
                status="succeeded",
                metadata={"start": start, "end": end, "received": len(batch), "total_received": len(outlines)},
            )

        normalized_by_number: dict[int, SynopsisVolumeOutline] = {}
        for outline in outlines:
            if 1 <= outline.volume_number <= total:
                normalized_by_number[outline.volume_number] = outline
        missing_numbers = [number for number in range(1, total + 1) if number not in normalized_by_number]
        if missing_numbers:
            self._log_progress(
                novel_id,
                f"卷级概要缺失 {len(missing_numbers)} 项,使用占位概要补齐",
                node="synopsis_volume_outlines",
                task="generate_synopsis_volume_outlines",
                status="completed_with_placeholders",
                level="warning",
                metadata={"missing_volume_numbers": missing_numbers, "estimated_volumes": total},
            )
        result = [
            normalized_by_number.get(number) or self._build_placeholder_volume_outline(number, synopsis)
            for number in range(1, total + 1)
        ]
        self._log_progress(
            novel_id,
            f"卷级概要生成完成: {len(result)}/{total}",
            node="synopsis_volume_outlines",
            task="generate_synopsis_volume_outlines",
            status="succeeded",
            metadata={"estimated_volumes": total, "volume_outlines": len(result)},
        )
        return result

    async def _generate_volume_outline_batch(
        self,
        *,
        source_text: str,
        synopsis: SynopsisData,
        constraints: str,
        start: int,
        end: int,
        novel_id: str,
    ) -> list[SynopsisVolumeOutline]:
        genre_prompt_block = await self._build_genre_prompt_block(
            novel_id,
            "generate_volume_outlines_batch",
        )
        prompt = (
            "你是一位长篇网文分卷策划。请基于顶层总纲,只生成指定范围内的卷级概要数组。"
            "这些概要是后续完整卷纲的方向契约,不是章节表。\n\n"
            f"{genre_prompt_block}"
            "## 输出要求\n"
            f"- 只生成第 {start} 卷到第 {end} 卷,必须正好 {end - start + 1} 项。\n"
            "- 每项必须包含 volume_number/title/summary/narrative_role/main_goal/main_conflict/"
            "start_state/end_state/climax/hook_to_next/key_entities/relationship_shifts/"
            "foreshadowing_setup/foreshadowing_payoff/target_chapter_range。\n"
            "- volume_number 必须连续且落在指定范围内。\n"
            "- summary 控制在 80-150 字,不要写 chapters 或 beats。\n"
            "- target_chapter_range 使用类似 '1-50' 的范围,并和总章数规模大致匹配。\n"
            "- 每一卷必须遵守对应的 ActiveConstraintContext:只能写当前阶段可触达冲突;"
            "高阶概念只能作为伏笔/残痕/传闻/代理人间接出现;缺少设定依据时保守降级,不要硬编。\n"
            "- 只返回 JSON 数组,不要解释、Markdown 或额外字段。\n\n"
            f"### 顶层总纲\n{synopsis.model_copy(update={'volume_outlines': []}).model_dump_json()}\n\n"
            f"{constraints}\n\n"
            f"### 参考设定\n{source_text or '无'}"
        )
        return await call_and_parse_model(
            "BrainstormAgent",
            "generate_synopsis_volume_outlines_batch",
            prompt,
            list[SynopsisVolumeOutline],
            novel_id=novel_id,
        )

    def _build_placeholder_volume_outline(
        self,
        volume_number: int,
        synopsis: SynopsisData,
    ) -> SynopsisVolumeOutline:
        chapters_per_volume = max(1, round((synopsis.estimated_total_chapters or 0) / max(1, synopsis.estimated_volumes)))
        start_chapter = (volume_number - 1) * chapters_per_volume + 1
        end_chapter = volume_number * chapters_per_volume
        return SynopsisVolumeOutline(
            volume_number=volume_number,
            title=f"第{volume_number}卷",
            summary=f"围绕《{synopsis.title}》主线推进第 {volume_number} 卷核心阶段,承接总纲冲突并为后续卷留下转折空间。",
            narrative_role="承接顶层总纲的阶段性推进",
            main_goal=synopsis.logline,
            main_conflict=synopsis.core_conflict,
            start_state="承接上一阶段局势",
            end_state="完成本阶段转折并引出后续矛盾",
            climax="本卷核心冲突集中爆发",
            hook_to_next="新的更高层矛盾显现",
            key_entities=[],
            relationship_shifts=[],
            foreshadowing_setup=[],
            foreshadowing_payoff=[],
            target_chapter_range=f"{start_chapter}-{end_chapter}",
        )

    def _format_synopsis_text(self, data: SynopsisData, source_text: str = "") -> str:
        lines = [
            f"# {data.title}",
            "",
            "## 一句话梗概",
            data.logline,
            "",
            "## 核心冲突",
            data.core_conflict,
            "",
            "## 人物弧光",
        ]
        for arc in data.character_arcs:
            lines.append(f"### {arc.name}")
            lines.append(arc.arc_summary)
            for pt in arc.key_turning_points:
                lines.append(f"- {pt}")
        lines.append("")
        lines.append("## 剧情里程碑")
        for ms in data.milestones:
            lines.append(f"### {ms.act}")
            lines.append(ms.summary)
            if ms.climax_event:
                lines.append(f"高潮：{ms.climax_event}")
        if data.volume_outlines:
            lines.append("")
            lines.append("## 卷级总览")
            for volume in data.volume_outlines:
                lines.append(f"### 第 {volume.volume_number} 卷：{volume.title}")
                lines.append(volume.summary)
                if volume.main_goal:
                    lines.append(f"- 卷目标：{volume.main_goal}")
                if volume.main_conflict:
                    lines.append(f"- 核心冲突：{volume.main_conflict}")
                if volume.climax:
                    lines.append(f"- 卷高潮：{volume.climax}")
                if volume.hook_to_next:
                    lines.append(f"- 卷末钩子：{volume.hook_to_next}")
        if source_text:
            lines.append("")
            lines.append("## 参考资料")
            lines.append(source_text)
        return "\n".join(lines)

    def format_synopsis_text(self, data: SynopsisData, source_text: str = "") -> str:
        return self._format_synopsis_text(data, source_text)
