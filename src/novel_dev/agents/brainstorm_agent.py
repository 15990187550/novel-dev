import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.outline import SynopsisData, SynopsisScoreResult
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.services.log_service import log_service


class BrainstormAgent:
    # self-review 阈值:overall 达标且关键维度(具体度、对抗具体度、转折数量)达底线
    OVERALL_THRESHOLD = 75
    KEY_DIM_THRESHOLDS = {
        "logline_specificity": 75,
        "conflict_concreteness": 75,
        "structural_turns": 70,
    }
    MAX_REVISE_ATTEMPTS = 3

    def __init__(self, session: AsyncSession):
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.director = NovelDirector(session)

    async def brainstorm(self, novel_id: str) -> SynopsisData:
        log_service.add_log(novel_id, "BrainstormAgent", "开始生成小说大纲")
        docs = await self.doc_repo.get_by_type(novel_id, "worldview")
        docs += await self.doc_repo.get_by_type(novel_id, "setting")
        docs += await self.doc_repo.get_by_type(novel_id, "concept")

        if not docs:
            log_service.add_log(novel_id, "BrainstormAgent", "未找到设定文档", level="error")
            raise ValueError("No source documents found for brainstorming")

        combined = "\n\n".join(f"[{d.doc_type}]\n{d.content}" for d in docs)
        log_service.add_log(novel_id, "BrainstormAgent", f"读取 {len(docs)} 份设定文档，开始生成 synopsis")
        synopsis_data = await self._generate_and_refine(combined, novel_id)
        synopsis_text = self._format_synopsis_text(synopsis_data)

        doc = await self.doc_repo.create(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type="synopsis",
            title=synopsis_data.title,
            content=synopsis_text,
        )

        checkpoint = {}
        state = await self.state_repo.get_state(novel_id)
        if state and state.checkpoint_data:
            checkpoint = dict(state.checkpoint_data)

        checkpoint["synopsis_data"] = synopsis_data.model_dump()
        checkpoint["synopsis_doc_id"] = doc.id

        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.VOLUME_PLANNING,
            checkpoint_data=checkpoint,
            volume_id=None,
            chapter_id=None,
        )
        log_service.add_log(novel_id, "BrainstormAgent", f"大纲生成完成，标题: {synopsis_data.title}，进入 volume_planning 阶段")

        return synopsis_data

    async def _generate_and_refine(self, combined_text: str, novel_id: str) -> SynopsisData:
        synopsis = await self._generate_synopsis(combined_text, novel_id)
        for attempt in range(self.MAX_REVISE_ATTEMPTS):
            score = await self._score_synopsis(synopsis, novel_id)
            log_service.add_log(novel_id, "BrainstormAgent", f"第 {attempt + 1} 次评分: overall={score.overall}")
            if self._is_acceptable(score):
                log_service.add_log(novel_id, "BrainstormAgent", f"评分通过，overall={score.overall}")
                return synopsis
            log_service.add_log(novel_id, "BrainstormAgent", f"评分未通过，开始第 {attempt + 1} 次修订")
            synopsis = await self._revise_synopsis(synopsis, score, combined_text, novel_id)
        log_service.add_log(novel_id, "BrainstormAgent", f"已达最大修订次数 {self.MAX_REVISE_ATTEMPTS}，返回最后一版", level="warning")
        return synopsis

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
        source_text = combined_text[:12000]
        prompt = (
            "你是一位资深商业小说大纲生成专家,面向网文连载读者。"
            "根据用户提供的设定文档,生成一份可供后续分卷、分章、分节拍继续展开的大纲。"
            "返回严格符合指定 JSON Schema 的数据。\n\n"
            "## 结构要求(在里程碑与人物弧中体现)\n"
            "1. 采用三幕式或更复杂结构,整部故事至少含 4 个能改变主角处境的转折点,"
            "每一幕至少 1 个,转折尽量由角色选择驱动(而非纯外力)。\n"
            "2. 节奏:里程碑分布上,平均每 3 章左右有 1 个小高潮,每卷有 1 个卷级高潮。\n"
            "3. 伏笔:character_arcs 与 milestones 合计给出 ≥4 个可回收的悬念点,"
            "每个悬念尽量在 1 卷内给出回收线索。\n"
            "4. 钩子:整部故事结尾带开放性钩子,能引出下一卷或续作的核心悬念。\n"
            "5. 人物弧光:主要角色 key_turning_points ≥3 个,且包含一次内在转变"
            "(信念/价值观/关系的重要变化)。\n\n"
            "## Schema 写法规范\n"
            "- logline:写成『角色 + 欲望 + 阻力 + 赌注』的一句话,避免把 logline 写成 setting 说明。\n"
            "- core_conflict:写具体的对抗关系(例『主角 vs 宗门长老会关于传承之争』),"
            "避免抽象标签(如『正邪对立』『人性与命运』)。\n"
            "- milestones.climax_event:写一个可被后续章节直接展开的具体事件,不要只写情绪。\n\n"
            f"{source_text}"
        )
        result = await call_and_parse_model(
            "BrainstormAgent", "generate_synopsis", prompt, SynopsisData, novel_id=novel_id
        )
        log_service.add_log(novel_id, "BrainstormAgent", f" synopsis 生成完成: {result.title}")
        return result

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
        if source_text:
            lines.append("")
            lines.append("## 参考资料")
            lines.append(source_text)
        return "\n".join(lines)

    def format_synopsis_text(self, data: SynopsisData, source_text: str = "") -> str:
        return self._format_synopsis_text(data, source_text)
