import math
import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.outline import (
    VolumePlan,
    VolumeBeat,
    VolumeScoreResult,
    SynopsisData,
)
from novel_dev.schemas.context import BeatPlan
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.entity_repo import EntityRepository
from novel_dev.repositories.version_repo import EntityVersionRepository
from novel_dev.repositories.timeline_repo import TimelineRepository
from novel_dev.repositories.foreshadowing_repo import ForeshadowingRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.services.log_service import log_service


class VolumePlannerAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.entity_repo = EntityRepository(session)
        self.version_repo = EntityVersionRepository(session)
        self.timeline_repo = TimelineRepository(session)
        self.foreshadowing_repo = ForeshadowingRepository(session)
        self.director = NovelDirector(session)

    async def plan(self, novel_id: str, volume_number: Optional[int] = None) -> VolumePlan:
        log_service.add_log(novel_id, "VolumePlannerAgent", "开始生成分卷规划")
        state = await self.state_repo.get_state(novel_id)
        if not state:
            log_service.add_log(novel_id, "VolumePlannerAgent", "小说状态未找到", level="error")
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.VOLUME_PLANNING.value:
            log_service.add_log(novel_id, "VolumePlannerAgent", f"当前阶段 {state.current_phase} 不允许规划分卷", level="error")
            raise ValueError(f"Cannot plan volume from phase {state.current_phase}")

        checkpoint = dict(state.checkpoint_data or {})
        synopsis_data = checkpoint.get("synopsis_data")
        if not synopsis_data:
            raise ValueError("synopsis_data missing in checkpoint_data")

        synopsis = SynopsisData.model_validate(synopsis_data)

        if volume_number is None:
            volume_number = self._infer_volume_number(checkpoint, state)
        log_service.add_log(novel_id, "VolumePlannerAgent", f"规划第 {volume_number} 卷")

        world_snapshot = await self._load_world_snapshot(novel_id) if volume_number > 1 else None
        volume_plan = await self._generate_volume_plan(synopsis, volume_number, world_snapshot, novel_id)

        attempt = checkpoint.get("volume_plan_attempt_count", 0)
        while True:
            score = await self._generate_score(volume_plan, novel_id)
            log_service.add_log(novel_id, "VolumePlannerAgent", f"第 {attempt + 1} 次评分: overall={score.overall}")
            if self._is_acceptable(score):
                log_service.add_log(novel_id, "VolumePlannerAgent", f"评分通过，overall={score.overall}")
                break
            attempt += 1
            checkpoint["volume_plan_attempt_count"] = attempt
            log_service.add_log(novel_id, "VolumePlannerAgent", f"评分未通过，开始第 {attempt} 次修订")
            if attempt >= 3:
                log_service.add_log(novel_id, "VolumePlannerAgent", "已达最大修订次数", level="error")
                await self.director.save_checkpoint(
                    novel_id,
                    phase=Phase.VOLUME_PLANNING,
                    checkpoint_data=checkpoint,
                    volume_id=state.current_volume_id,
                    chapter_id=state.current_chapter_id,
                )
                raise RuntimeError("Max volume plan attempts exceeded")
            volume_plan = await self._revise_volume_plan(volume_plan, self._build_revise_feedback(score), novel_id)

        checkpoint["current_volume_plan"] = volume_plan.model_dump()
        checkpoint["current_chapter_plan"] = self._extract_chapter_plan(volume_plan.chapters[0])
        checkpoint["volume_plan_attempt_count"] = 0
        log_service.add_log(novel_id, "VolumePlannerAgent", f"分卷规划完成: {volume_plan.title}，共 {len(volume_plan.chapters)} 章")

        await self.doc_repo.create(
            doc_id=f"doc_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            doc_type="volume_plan",
            title=f"{volume_plan.title}",
            content=volume_plan.model_dump_json(),
        )

        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.CONTEXT_PREPARATION,
            checkpoint_data=checkpoint,
            volume_id=volume_plan.volume_id,
            chapter_id=volume_plan.chapters[0].chapter_id,
        )
        log_service.add_log(novel_id, "VolumePlannerAgent", "进入 context_preparation 阶段")

        return volume_plan

    # Overall 只要及格,但关键维度(爽点分布、人物与情节契合)必须达标,否则是"虚高"。
    OVERALL_THRESHOLD = 75
    KEY_DIM_THRESHOLDS = {
        "hook_distribution": 75,
        "character_plot_alignment": 75,
        "page_turning": 70,
    }

    def _is_acceptable(self, score) -> bool:
        if score.overall < self.OVERALL_THRESHOLD:
            return False
        for dim, floor in self.KEY_DIM_THRESHOLDS.items():
            if getattr(score, dim, 100) < floor:
                return False
        return True

    def _build_revise_feedback(self, score) -> str:
        failing = []
        for dim, floor in self.KEY_DIM_THRESHOLDS.items():
            val = getattr(score, dim, 100)
            if val < floor:
                failing.append(f"{dim}={val}(下限 {floor})")
        lines = [f"overall={score.overall}(下限 {self.OVERALL_THRESHOLD})"] if score.overall < self.OVERALL_THRESHOLD else []
        if failing:
            lines.append("关键维度未达标: " + ", ".join(failing))
        if score.summary_feedback:
            lines.append(f"评审意见: {score.summary_feedback}")
        lines.append(
            "请针对以上未达标维度逐项修正:"
            "爽点分布不足就增加每 2-3 章的小高潮与钩子;"
            "人物与情节契合低说明角色目标/动机与情节推进脱节,需补强动机逻辑;"
            "页面翻动欲低意味着章末钩子不够,需在每章结尾加入悬念/反转/赌注升级。"
        )
        return "\n".join(lines)

    def _infer_volume_number(self, checkpoint: dict, state) -> int:
        if state.current_volume_id and state.current_volume_id.startswith("vol_"):
            try:
                return int(state.current_volume_id.replace("vol_", ""))
            except ValueError:
                pass
        return 1

    async def _generate_volume_plan(
        self, synopsis: SynopsisData, volume_number: int, world_snapshot: Optional[dict] = None, novel_id: str = ""
    ) -> VolumePlan:
        log_service.add_log(novel_id, "VolumePlannerAgent", "开始生成卷纲")
        MAX_CHARS = 12000
        truncated_synopsis = synopsis.model_dump_json()[:MAX_CHARS]

        world_block = ""
        if world_snapshot:
            world_block = (
                "\n\n### 前卷世界状态快照(本卷规划必须与以下事实一致,不得与之矛盾)\n"
                f"活跃人物:\n{world_snapshot.get('entities', '无')}\n"
                f"未回收伏笔(本卷内应考虑回收部分):\n{world_snapshot.get('foreshadowings', '无')}\n"
                f"已推进时间线:\n{world_snapshot.get('timeline', '无')}\n"
            )

        prompt = (
            "你是一位小说分卷规划专家。请根据以下大纲数据,"
            "生成一个完整的分卷规划 VolumePlan,返回严格符合 VolumePlan Schema 的 JSON。\n"
            "## 结构要求\n"
            "1. 每章给出有意义的标题和摘要,不用『第X章』这类占位符。\n"
            "2. 每章拆分为 2-4 个节拍(beats),每个节拍用『谁做什么导致什么后果』的形式描述,"
            "让后续 Writer 能据此展开。\n"
            "3. 章节之间保持因果连贯,平均每 2-3 章安排 1 个能改变处境的冲突点/悬念点。\n"
            "4. 每章最后一个 beat 安排悬念、反转、情绪爆点或赌注升级之一,作为章末钩子,"
            "避免平淡收束。\n"
            "5. 本卷整体规划出 1 个卷级高潮和 1 个卷末钩子,为下一卷铺垫。\n"
            "6. foreshadowings_to_embed 与 foreshadowings_to_recover 在章节之间要形成呼应,"
            "埋下的伏笔在合理章节内给出回收线索。\n"
            "7. 估算字数合理。\n\n"
            f"大纲数据:\n{truncated_synopsis}\n\n"
            f"当前卷号:{volume_number}"
            f"{world_block}"
        )
        result = await call_and_parse_model(
            "VolumePlannerAgent", "generate_volume_plan", prompt, VolumePlan, max_retries=3, novel_id=novel_id
        )
        log_service.add_log(novel_id, "VolumePlannerAgent", f"卷纲生成完成: {result.title}")
        return result

    async def _load_world_snapshot(self, novel_id: str) -> dict:
        """为跨卷延续加载世界状态快照:活跃实体、未回收伏笔、近期时间线。"""
        try:
            entities = await self.entity_repo.list_by_novel(novel_id)
            entity_lines = []
            for e in entities[:30]:
                latest = await self.version_repo.get_latest(e.id)
                state_str = str(latest.state) if latest else ""
                entity_lines.append(f"- [{e.type}] {e.name}: {state_str[:200]}")
            entities_text = "\n".join(entity_lines) if entity_lines else "无"

            fs_list = await self.foreshadowing_repo.list_active(novel_id=novel_id)
            fs_lines = [f"- {fs.content}" for fs in fs_list[:30]]
            fs_text = "\n".join(fs_lines) if fs_lines else "无"

            tick = await self.timeline_repo.get_current_tick() or 0
            events = await self.timeline_repo.get_around_tick(tick, radius=5, novel_id=novel_id)
            tl_lines = [f"- tick={e.tick}: {e.narrative}" for e in events[:15]]
            tl_text = "\n".join(tl_lines) if tl_lines else "无"

            return {"entities": entities_text, "foreshadowings": fs_text, "timeline": tl_text}
        except Exception as exc:
            log_service.add_log(novel_id, "VolumePlannerAgent", f"世界快照加载失败: {exc}", level="warning")
            return {}

    async def _generate_score(self, plan: VolumePlan, novel_id: str = "") -> VolumeScoreResult:
        log_service.add_log(novel_id, "VolumePlannerAgent", "开始评分卷纲")
        prompt = (
            "你是一个小说分卷规划评审专家。请根据以下 VolumePlan JSON 进行多维度评分，"
            "返回严格符合 VolumeScoreResult Schema 的 JSON。"
            f"\n\n{plan.model_dump_json()}"
        )
        result = await call_and_parse_model(
            "VolumePlannerAgent", "score_volume_plan", prompt, VolumeScoreResult, max_retries=3, novel_id=novel_id
        )
        log_service.add_log(novel_id, "VolumePlannerAgent", f"评分完成: overall={result.overall}")
        return result

    async def _revise_volume_plan(self, plan: VolumePlan, feedback: str, novel_id: str = "") -> VolumePlan:
        log_service.add_log(novel_id, "VolumePlannerAgent", "开始修订卷纲")
        prompt = (
            "你是一个小说分卷规划专家。请根据以下 VolumePlan 和评审反馈进行修正，"
            "返回严格符合 VolumePlan Schema 的 JSON。"
            f"\n\nVolumePlan:\n{plan.model_dump_json()}"
            f"\n\n反馈：{feedback}"
        )
        result = await call_and_parse_model(
            "VolumePlannerAgent", "revise_volume_plan", prompt, VolumePlan, max_retries=3, novel_id=novel_id
        )
        log_service.add_log(novel_id, "VolumePlannerAgent", "卷纲修订完成")
        return result

    def _extract_chapter_plan(self, volume_beat: VolumeBeat) -> dict:
        """Extract chapter plan from VolumeBeat without mutating input."""
        chapter_plan = volume_beat.model_dump()
        beats = [b.model_dump() for b in volume_beat.beats]
        if volume_beat.foreshadowings_to_embed and beats:
            if not beats[0].get("foreshadowings_to_embed"):
                beats[0]["foreshadowings_to_embed"] = list(volume_beat.foreshadowings_to_embed)
        chapter_plan["beats"] = beats
        return chapter_plan
