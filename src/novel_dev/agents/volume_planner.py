import json
import math
import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, model_validator

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


class VolumeChapterSkeleton(BaseModel):
    chapter_number: int
    title: str
    summary: str

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if "title" not in normalized and "chapter_title" in normalized:
            normalized["title"] = normalized["chapter_title"]
        if "summary" not in normalized:
            for legacy_key in ("description", "chapter_summary", "content"):
                if legacy_key in normalized:
                    normalized["summary"] = normalized[legacy_key]
                    break
        return normalized


class VolumePlanBlueprint(BaseModel):
    volume_id: str
    volume_number: int
    title: str
    summary: str
    total_chapters: int
    estimated_total_words: int
    chapters: list[VolumeChapterSkeleton] = Field(default_factory=list)
    entity_highlights: dict[str, list[str]] = Field(default_factory=dict)
    relationship_highlights: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        volume_number = normalized.get("volume_number") or normalized.get("number") or 1
        if "volume_number" not in normalized:
            normalized["volume_number"] = volume_number
        if "volume_id" not in normalized:
            normalized["volume_id"] = normalized.get("id") or normalized.get("volume_ref") or f"vol_{volume_number}"
        if "title" not in normalized:
            normalized["title"] = normalized.get("volume_title") or normalized.get("name") or f"第{volume_number}卷"
        if "summary" not in normalized:
            normalized["summary"] = normalized.get("volume_summary") or normalized.get("description") or ""
        if "estimated_total_words" not in normalized:
            normalized["estimated_total_words"] = (
                normalized.get("total_words") or normalized.get("word_count") or normalized.get("estimated_words") or 3000
            )
        if "total_chapters" not in normalized:
            normalized["total_chapters"] = normalized.get("chapter_count") or len(normalized.get("chapters") or [])
        return normalized


class VolumePlannerAgent:
    MAX_AUTOREVISE_CHAPTERS = 18

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
        plan_context = self._build_plan_context(synopsis, world_snapshot)

        attempt = checkpoint.get("volume_plan_attempt_count", 0)
        skip_full_revise = len(volume_plan.chapters) > self.MAX_AUTOREVISE_CHAPTERS
        while True:
            score = await self._generate_score(volume_plan, novel_id)
            log_service.add_log(novel_id, "VolumePlannerAgent", f"第 {attempt + 1} 次评分: overall={score.overall}")
            if self._is_acceptable(score):
                log_service.add_log(novel_id, "VolumePlannerAgent", f"评分通过，overall={score.overall}")
                break
            if skip_full_revise:
                log_service.add_log(
                    novel_id,
                    "VolumePlannerAgent",
                    "大卷纲已跳过自动整卷修订，请在工作台继续细化章节。",
                    level="warning",
                )
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
            volume_plan = await self._revise_volume_plan(volume_plan, self._build_revise_feedback(score), plan_context, novel_id)

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
    CHAPTER_BATCH_SIZE = 8

    def _suggest_volume_chapter_range(self, synopsis: SynopsisData) -> tuple[int, int]:
        estimated_volumes = max(1, synopsis.estimated_volumes or 1)
        estimated_total_chapters = max(1, synopsis.estimated_total_chapters or 1)
        rough_chapters_per_volume = math.ceil(estimated_total_chapters / estimated_volumes)

        if rough_chapters_per_volume <= 6:
            lower = max(3, rough_chapters_per_volume)
            upper = max(lower, min(6, rough_chapters_per_volume + 1))
            return lower, upper
        if rough_chapters_per_volume <= 18:
            lower = max(6, rough_chapters_per_volume - 2)
            upper = min(20, rough_chapters_per_volume + 2)
            return lower, max(lower, upper)
        return 20, 36

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

    def _build_plan_context(self, synopsis: SynopsisData, world_snapshot: Optional[dict]) -> str:
        synopsis_text = synopsis.model_dump_json()[:12000]
        if not world_snapshot:
            return f"### 大纲数据\n{synopsis_text}"
        return (
            f"### 大纲数据\n{synopsis_text}\n\n"
            "### 前卷世界状态快照\n"
            f"活跃人物:\n{world_snapshot.get('entities', '无')}\n"
            f"未回收伏笔:\n{world_snapshot.get('foreshadowings', '无')}\n"
            f"已推进时间线:\n{world_snapshot.get('timeline', '无')}"
        )

    def _build_score_plan_snapshot(self, plan: VolumePlan) -> str:
        snapshot = {
            "volume_id": plan.volume_id,
            "volume_number": plan.volume_number,
            "title": plan.title,
            "summary": plan.summary,
            "total_chapters": plan.total_chapters,
            "estimated_total_words": plan.estimated_total_words,
            "chapters": [],
        }
        for chapter in plan.chapters:
            hook = chapter.beats[-1].summary if chapter.beats else ""
            snapshot["chapters"].append({
                "chapter_number": chapter.chapter_number,
                "title": chapter.title,
                "summary": chapter.summary,
                "hook": hook,
                "foreshadowings_to_embed": chapter.foreshadowings_to_embed,
                "foreshadowings_to_recover": chapter.foreshadowings_to_recover,
            })
        return json.dumps(snapshot, ensure_ascii=False)

    async def _generate_volume_plan(
        self, synopsis: SynopsisData, volume_number: int, world_snapshot: Optional[dict] = None, novel_id: str = ""
    ) -> VolumePlan:
        log_service.add_log(novel_id, "VolumePlannerAgent", "开始生成卷纲")
        MAX_CHARS = 12000
        truncated_synopsis = synopsis.model_dump_json()[:MAX_CHARS]
        chapter_range = self._suggest_volume_chapter_range(synopsis)

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
            "## 输出规模限制\n"
            f"1. total_chapters 必须控制在 {chapter_range[0]}-{chapter_range[1]} 章之间。\n"
            "2. 这是单卷可执行规划,不要试图一次覆盖整部小说的全部章节。\n"
            "3. 每章 summary 控制在 40-80 字,每个 beat 控制在 18-40 字。\n"
            "4. beats 保持 2-3 个即可,优先保证完整 JSON 和章节因果链。\n\n"
            f"大纲数据:\n{truncated_synopsis}\n\n"
            f"当前卷号:{volume_number}"
            f"{world_block}"
        )
        blueprint = await call_and_parse_model(
            "VolumePlannerAgent", "generate_volume_plan", prompt, VolumePlanBlueprint, max_retries=3, novel_id=novel_id
        )
        detailed_chapters = await self._expand_volume_plan_batches(
            blueprint,
            synopsis,
            world_snapshot=world_snapshot,
            novel_id=novel_id,
        )
        result = VolumePlan(
            volume_id=blueprint.volume_id,
            volume_number=blueprint.volume_number,
            title=blueprint.title,
            summary=blueprint.summary,
            total_chapters=len(detailed_chapters),
            estimated_total_words=blueprint.estimated_total_words,
            chapters=detailed_chapters,
            entity_highlights=blueprint.entity_highlights,
            relationship_highlights=blueprint.relationship_highlights,
        )
        log_service.add_log(novel_id, "VolumePlannerAgent", f"卷纲生成完成: {result.title}")
        return result

    async def _expand_volume_plan_batches(
        self,
        blueprint: VolumePlanBlueprint,
        synopsis: SynopsisData,
        *,
        world_snapshot: Optional[dict],
        novel_id: str,
    ) -> list[VolumeBeat]:
        chapters: list[VolumeBeat] = []
        skeletons = blueprint.chapters
        for start in range(0, len(skeletons), self.CHAPTER_BATCH_SIZE):
            batch = skeletons[start:start + self.CHAPTER_BATCH_SIZE]
            start_no = batch[0].chapter_number
            end_no = batch[-1].chapter_number
            log_service.add_log(novel_id, "VolumePlannerAgent", f"扩展章节细节: 第 {start_no}-{end_no} 章")
            prompt = self._build_volume_plan_batch_prompt(
                blueprint,
                synopsis,
                batch,
                world_snapshot=world_snapshot,
            )
            batch_result = await call_and_parse_model(
                "VolumePlannerAgent",
                "expand_volume_plan_batch",
                prompt,
                list[VolumeBeat],
                max_retries=3,
                novel_id=novel_id,
            )
            chapters.extend(batch_result)
        return chapters

    def _build_volume_plan_batch_prompt(
        self,
        blueprint: VolumePlanBlueprint,
        synopsis: SynopsisData,
        batch: list[VolumeChapterSkeleton],
        *,
        world_snapshot: Optional[dict],
    ) -> str:
        batch_payload = [
            {
                "chapter_number": chapter.chapter_number,
                "title": chapter.title,
                "summary": chapter.summary,
            }
            for chapter in batch
        ]
        world_block = ""
        if world_snapshot:
            world_block = (
                "\n\n### 前卷世界状态快照\n"
                f"活跃人物:\n{world_snapshot.get('entities', '无')}\n"
                f"未回收伏笔:\n{world_snapshot.get('foreshadowings', '无')}\n"
                f"已推进时间线:\n{world_snapshot.get('timeline', '无')}\n"
            )
        return (
            "你是一位小说分卷规划专家。请根据给定的卷纲骨架，补全一批章节的详细 VolumeBeat 数组。"
            "只返回合法 JSON 数组，每一项必须符合 VolumeBeat Schema。\n"
            "要求:\n"
            "1. 只扩展本批章节，不要返回其他章节。\n"
            "2. 每章保留 chapter_number/title/summary 主线含义一致。\n"
            "3. chapter_id 使用 ch_<chapter_number>。\n"
            "4. target_word_count 给出合理整数；target_mood 用简短英文或中文短语。\n"
            "5. 每章 2-3 个 beats，每个 beat 只写 summary 和 target_mood，必要时补 key_entities / foreshadowings_to_embed。\n"
            "6. 章节之间必须形成因果推进，最后一个 beat 要有章末钩子。\n"
            "7. 不要输出 Markdown，不要解释。\n\n"
            f"### 整卷骨架\n{blueprint.model_dump_json()[:8000]}\n\n"
            f"### 整体大纲\n{synopsis.model_dump_json()[:8000]}\n\n"
            f"### 本批待扩展章节\n{json.dumps(batch_payload, ensure_ascii=False)}"
            f"{world_block}"
        )

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
            "返回严格符合 VolumeScoreResult Schema 的 JSON。\n\n"
            "## Rubric\n"
            "- outline_fidelity >=75: 与 synopsis 主线、卷目标、章节推进一致，不偏题。\n"
            "- character_plot_alignment >=75: 角色目标、动机、行动与章节冲突推进一致。\n"
            "- hook_distribution >=75: 平均每 2-3 章有小高潮/悬念点，卷内有卷级高潮。\n"
            "- foreshadowing_management >=75: 埋设与回收有呼应，不是孤立点缀。\n"
            "- chapter_hooks >=75: 多数章节结尾有明确钩子。\n"
            "- page_turning >=70: 读者会自然想继续读下一章。\n"
            "## 输出\n"
            "严格 JSON，summary_feedback 控制在 300 字内，指出最需要改的 2-3 点。"
            f"\n\n### VolumePlan\n{self._build_score_plan_snapshot(plan)}"
        )
        result = await call_and_parse_model(
            "VolumePlannerAgent", "score_volume_plan", prompt, VolumeScoreResult, max_retries=3, novel_id=novel_id
        )
        log_service.add_log(novel_id, "VolumePlannerAgent", f"评分完成: overall={result.overall}")
        return result

    async def _revise_volume_plan(self, plan: VolumePlan, feedback: str, plan_context: str = "", novel_id: str = "") -> VolumePlan:
        log_service.add_log(novel_id, "VolumePlannerAgent", "开始修订卷纲")
        prompt = (
            "你是一个小说分卷规划专家。请根据以下 VolumePlan、原始规划上下文与评审反馈进行修正，"
            "返回严格符合 VolumePlan Schema 的 JSON。"
            f"\n\n### 当前 VolumePlan\n{plan.model_dump_json()}"
            f"\n\n### 原始规划上下文\n{plan_context}"
            f"\n\n### 反馈\n{feedback}"
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
