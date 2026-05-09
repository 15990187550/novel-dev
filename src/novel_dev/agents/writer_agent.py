import json
import re
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.context import ChapterContext, DraftMetadata, BeatPlan, BeatSelfCheck
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.llm.models import ChatMessage
from novel_dev.agents._log_helpers import log_agent_detail, preview_text
from novel_dev.services.flow_control_service import FlowControlService
from novel_dev.services.log_service import agent_step, logged_agent_step, log_service
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.services.chapter_structure_guard_service import ChapterStructureGuardService


_BEAT_ANCHOR_STRIP_RE = re.compile(r"<!--/?BEAT:\d+-->")
_BEAT_ANCHOR_RE = re.compile(r"<!--BEAT:(\d+)-->\n(.*?)\n<!--/BEAT:\1-->", re.DOTALL)


def _strip_anchors(text: str) -> str:
    return _BEAT_ANCHOR_STRIP_RE.sub("", text).strip()


class WriterAgent:
    def __init__(
        self,
        session: AsyncSession,
        embedding_service: Optional[EmbeddingService] = None,
        structure_guard: Optional[ChapterStructureGuardService] = None,
    ):
        self.session = session
        self.chapter_repo = ChapterRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.director = NovelDirector(session)
        self.embedding_service = embedding_service
        self.structure_guard = structure_guard or ChapterStructureGuardService()

    @logged_agent_step("WriterAgent", "写作章节草稿", node="draft", task="write")
    async def write(self, novel_id: str, context: ChapterContext, chapter_id: str) -> DraftMetadata:
        log_service.add_log(novel_id, "WriterAgent", f"开始写章节草稿: {context.chapter_plan.title}")
        state = await self.state_repo.get_state(novel_id)
        if not state:
            log_service.add_log(novel_id, "WriterAgent", "小说状态未找到", level="error")
            raise ValueError(f"Novel state not found for {novel_id}")

        if state.current_phase != Phase.DRAFTING.value:
            raise ValueError(f"Cannot write draft from phase {state.current_phase}")

        checkpoint = dict(state.checkpoint_data or {})
        if not checkpoint.get("chapter_context"):
            raise ValueError("chapter_context missing in checkpoint_data")

        progress = checkpoint.get("drafting_progress", {})
        start_idx = progress.get("beat_index", 0)
        rewrite_plan = checkpoint.get("draft_rewrite_plan") or {}
        if rewrite_plan:
            log_service.add_log(
                novel_id,
                "WriterAgent",
                "检测到评审退回重写计划，按问题反馈重新生成草稿",
                event="agent.progress",
                status="started",
                node="draft_rewrite",
                task="write",
                metadata={
                    "rewrite_all": bool(rewrite_plan.get("rewrite_all")),
                    "overall": rewrite_plan.get("overall"),
                    "summary_feedback": rewrite_plan.get("summary_feedback"),
                },
            )

        raw_draft = ""
        beat_coverage = []
        embedded_foreshadowings = []
        total_beats = len(context.chapter_plan.beats)

        from novel_dev.schemas.context import NarrativeRelay
        relay_history: List[NarrativeRelay] = []
        inner_beats: List[str] = []

        if start_idx > 0:
            log_service.add_log(novel_id, "WriterAgent", f"从第 {start_idx + 1} 个节拍恢复写作")
        # Resume from checkpoint if previous run was interrupted
        if start_idx > 0:
            if checkpoint.get("relay_history"):
                relay_history = [
                    NarrativeRelay(**r) for r in checkpoint["relay_history"]
                ]
            ch = await self.chapter_repo.get_by_id(chapter_id)
            if ch and ch.raw_draft:
                raw_draft = ch.raw_draft
                for m in _BEAT_ANCHOR_RE.finditer(raw_draft):
                    bi = int(m.group(1))
                    inner = m.group(2).strip()
                    while len(inner_beats) <= bi:
                        inner_beats.append("")
                    inner_beats[bi] = inner
                for i, inner in enumerate(inner_beats):
                    beat_coverage.append({"beat_index": i, "word_count": len(inner)})
                    for fs in context.pending_foreshadowings:
                        if fs.content in inner and fs.id not in embedded_foreshadowings:
                            embedded_foreshadowings.append(fs.id)

        flow_control = FlowControlService(self.session)
        for idx, beat in enumerate(context.chapter_plan.beats):
            if idx < start_idx:
                continue
            await flow_control.raise_if_cancelled(novel_id)
            is_last = (idx == total_beats - 1)
            last_beat_text = inner_beats[-1] if inner_beats else ""
            beat_context = self._beat_context(context, idx)
            log_agent_detail(
                novel_id,
                "WriterAgent",
                f"节拍 {idx + 1}/{total_beats} 写作输入已准备",
                node="draft_beat_input",
                task="write",
                status="started",
                metadata={
                    "beat_index": idx,
                    "total_beats": total_beats,
                    "summary_preview": preview_text(beat.summary),
                    "target_mood": beat.target_mood,
                    "target_word_count": self._beat_target_word_count(context, total_beats, beat),
                    "last_beat_chars": len(last_beat_text),
                    "relay_count": len(relay_history),
                    "rewrite_plan_present": bool(rewrite_plan),
                    "related_entities": [e.name for e in beat_context.entities] if beat_context else [],
                    "related_documents": [doc.title for doc in beat_context.relevant_documents] if beat_context else [],
                    "foreshadowings": [fs.content for fs in beat_context.foreshadowings] if beat_context else [],
                    "guardrails": beat_context.guardrails if beat_context else [],
                },
            )

            beat_text = await self._generate_beat(
                beat, context, relay_history, last_beat_text,
                idx, total_beats, is_last, novel_id, rewrite_plan,
            )
            inner = _strip_anchors(beat_text)
            if len(inner) < 50:
                log_service.add_log(novel_id, "WriterAgent", f"第 {idx + 1} 个节拍过短({len(inner)}字)，重写")
                inner = await self._rewrite_angle(
                    beat,
                    inner,
                    context,
                    relay_history,
                    last_beat_text,
                    idx,
                    total_beats,
                    is_last,
                    None,
                    novel_id,
                    rewrite_plan,
                )
                beat_text = f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"

            self_check = self._self_check_beat(inner, beat, context, idx)
            log_agent_detail(
                novel_id,
                "WriterAgent",
                f"节拍 {idx + 1} 自检完成：{'需重写' if self_check.needs_rewrite else '通过'}",
                node="draft_self_check",
                task="write",
                status="failed" if self_check.needs_rewrite else "succeeded",
                level="warning" if self_check.needs_rewrite else "info",
                metadata={
                    "beat_index": idx,
                    "generated_chars": len(inner),
                    "needs_rewrite": self_check.needs_rewrite,
                    "missing_entities": self_check.missing_entities,
                    "missing_foreshadowings": self_check.missing_foreshadowings,
                    "contradictions": self_check.contradictions,
                },
            )
            if self_check.needs_rewrite:
                log_service.add_log(
                    novel_id,
                    "WriterAgent",
                    f"第 {idx + 1} 个节拍自检未通过，重写: 缺实体 {len(self_check.missing_entities)}，缺伏笔 {len(self_check.missing_foreshadowings)}，冲突 {len(self_check.contradictions)}",
                    level="warning",
                )
                inner = await self._rewrite_angle(
                    beat,
                    inner,
                    context,
                    relay_history,
                    last_beat_text,
                    idx,
                    total_beats,
                    is_last,
                    self_check,
                    novel_id,
                    rewrite_plan,
                )
                beat_text = f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"

            inner, beat_text = await self._guard_writer_beat(
                novel_id=novel_id,
                context=context,
                beat=beat,
                inner=inner,
                relay_history=relay_history,
                last_beat_text=last_beat_text,
                idx=idx,
                total_beats=total_beats,
                is_last=is_last,
                rewrite_plan=rewrite_plan,
                checkpoint=checkpoint,
                state=state,
                chapter_id=chapter_id,
            )

            inner_beats.append(inner)
            raw_draft += beat_text + "\n\n"
            beat_coverage.append({"beat_index": idx, "word_count": len(inner)})

            try:
                next_beat = context.chapter_plan.beats[idx + 1] if idx + 1 < total_beats else None
                relay = await self._generate_relay(inner, beat, context, idx, next_beat, novel_id)
                relay_history.append(relay)
            except Exception as exc:
                log_agent_detail(
                    novel_id,
                    "WriterAgent",
                    "叙事接力生成失败，使用节拍摘要 fallback",
                    node="generate_relay",
                    task="generate_relay",
                    status="failed",
                    level="warning",
                    metadata={
                        "beat_index": idx,
                        "error": f"{type(exc).__name__}: {exc}",
                        "fallback": {
                            "scene_state": beat.summary,
                            "emotional_tone": beat.target_mood,
                        },
                    },
                )
                relay_history.append(NarrativeRelay(
                    scene_state=beat.summary,
                    emotional_tone=beat.target_mood,
                    new_info_revealed="",
                    open_threads="",
                    next_beat_hook="",
                ))

            for fs in context.pending_foreshadowings:
                if fs.content in inner and fs.id not in embedded_foreshadowings:
                    embedded_foreshadowings.append(fs.id)

            log_agent_detail(
                novel_id,
                "WriterAgent",
                f"节拍 {idx + 1}/{total_beats} 完成：{len(inner)} 字",
                node="draft_beat_result",
                task="write",
                metadata={
                    "beat_index": idx,
                    "total_beats": total_beats,
                    "generated_chars": len(inner),
                    "preview": preview_text(inner, 300),
                    "embedded_foreshadowings": list(embedded_foreshadowings),
                    "relay_count": len(relay_history),
                },
            )
            checkpoint["drafting_progress"] = {
                "beat_index": idx + 1,
                "total_beats": total_beats,
                "current_word_count": len(raw_draft),
            }
            checkpoint["relay_history"] = [r.model_dump() for r in relay_history]
            await self.state_repo.save_checkpoint(
                novel_id,
                current_phase=Phase.DRAFTING.value,
                checkpoint_data=checkpoint,
                current_volume_id=state.current_volume_id,
                current_chapter_id=state.current_chapter_id,
            )
            await self.chapter_repo.update_text(chapter_id, raw_draft=raw_draft.strip())
            await flow_control.raise_if_cancelled(novel_id)

        clean_text = _strip_anchors(raw_draft)
        total_words = len(clean_text.replace(" ", "").replace("\n", "").replace("\t", "").replace("\r", ""))
        log_agent_detail(
            novel_id,
            "WriterAgent",
            f"草稿完成：总字数 {total_words}，嵌入伏笔 {len(embedded_foreshadowings)} 条",
            node="draft_result",
            task="write",
            metadata={
                "chapter_id": chapter_id,
                "total_words": total_words,
                "beat_coverage": beat_coverage,
                "embedded_foreshadowings": embedded_foreshadowings,
            },
        )
        metadata = DraftMetadata(
            total_words=total_words,
            beat_coverage=beat_coverage,
            style_violations=[],
            embedded_foreshadowings=embedded_foreshadowings,
        )

        if self.embedding_service:
            try:
                await self.embedding_service.index_chapter(chapter_id)
            except Exception as exc:
                log_service.add_log(novel_id, "WriterAgent", f"章节索引失败: {exc}", level="warning")
        await self.chapter_repo.update_status(chapter_id, "drafted")

        checkpoint["draft_metadata"] = metadata.model_dump()
        checkpoint.pop("draft_rewrite_plan", None)
        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.REVIEWING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )
        log_service.add_log(novel_id, "WriterAgent", "进入 reviewing 阶段")

        return metadata

    async def write_standalone(
        self,
        novel_id: str,
        context: ChapterContext,
        chapter_id: str,
        rewrite_plan: dict | None = None,
    ) -> tuple[DraftMetadata, dict]:
        log_service.add_log(novel_id, "WriterAgent", f"开始独立重写章节草稿: {context.chapter_plan.title}")
        rewrite_plan = rewrite_plan or {}
        raw_draft = ""
        beat_coverage = []
        embedded_foreshadowings = []
        total_beats = len(context.chapter_plan.beats)

        from novel_dev.schemas.context import NarrativeRelay
        relay_history: List[NarrativeRelay] = []
        inner_beats: List[str] = []
        flow_control = FlowControlService(self.session)

        for idx, beat in enumerate(context.chapter_plan.beats):
            await flow_control.raise_if_cancelled(novel_id)
            is_last = (idx == total_beats - 1)
            last_beat_text = inner_beats[-1] if inner_beats else ""
            log_service.add_log(novel_id, "WriterAgent", f"独立重写第 {idx + 1}/{total_beats} 个节拍: {beat.summary[:50]}...")

            beat_text = await self._generate_beat(
                beat, context, relay_history, last_beat_text,
                idx, total_beats, is_last, novel_id, rewrite_plan,
            )
            inner = _strip_anchors(beat_text)
            if len(inner) < 50:
                inner = await self._rewrite_angle(
                    beat,
                    inner,
                    context,
                    relay_history,
                    last_beat_text,
                    idx,
                    total_beats,
                    is_last,
                    None,
                    novel_id,
                    rewrite_plan,
                )
                beat_text = f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"

            self_check = self._self_check_beat(inner, beat, context, idx)
            if self_check.needs_rewrite:
                log_service.add_log(
                    novel_id,
                    "WriterAgent",
                    f"独立重写第 {idx + 1} 个节拍自检未通过，重写",
                    level="warning",
                )
                inner = await self._rewrite_angle(
                    beat,
                    inner,
                    context,
                    relay_history,
                    last_beat_text,
                    idx,
                    total_beats,
                    is_last,
                    self_check,
                    novel_id,
                    rewrite_plan,
                )
                beat_text = f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"

            inner, beat_text = await self._guard_writer_beat(
                novel_id=novel_id,
                context=context,
                beat=beat,
                inner=inner,
                relay_history=relay_history,
                last_beat_text=last_beat_text,
                idx=idx,
                total_beats=total_beats,
                is_last=is_last,
                rewrite_plan=rewrite_plan,
                checkpoint={},
                state=None,
                chapter_id=chapter_id,
            )

            inner_beats.append(inner)
            raw_draft += beat_text + "\n\n"
            beat_coverage.append({"beat_index": idx, "word_count": len(inner)})

            try:
                next_beat = context.chapter_plan.beats[idx + 1] if idx + 1 < total_beats else None
                relay = await self._generate_relay(inner, beat, context, idx, next_beat, novel_id)
                relay_history.append(relay)
            except Exception as exc:
                log_service.add_log(novel_id, "WriterAgent", f"独立重写叙事接力生成失败: {exc}", level="warning")
                relay_history.append(NarrativeRelay(
                    scene_state=beat.summary,
                    emotional_tone=beat.target_mood,
                    new_info_revealed="",
                    open_threads="",
                    next_beat_hook="",
                ))

            for fs in context.pending_foreshadowings:
                if fs.content in inner and fs.id not in embedded_foreshadowings:
                    embedded_foreshadowings.append(fs.id)

        clean_text = _strip_anchors(raw_draft)
        total_words = len(clean_text.replace(" ", "").replace("\n", "").replace("\t", "").replace("\r", ""))
        metadata = DraftMetadata(
            total_words=total_words,
            beat_coverage=beat_coverage,
            style_violations=[],
            embedded_foreshadowings=embedded_foreshadowings,
        )
        await self.chapter_repo.update_text(chapter_id, raw_draft=raw_draft.strip())
        if self.embedding_service:
            try:
                await self.embedding_service.index_chapter(chapter_id)
            except Exception as exc:
                log_service.add_log(novel_id, "WriterAgent", f"独立重写章节索引失败: {exc}", level="warning")
        await self.chapter_repo.update_status(chapter_id, "drafted")
        return metadata, {
            "chapter_context": context.model_dump(),
            "draft_metadata": metadata.model_dump(),
            "relay_history": [r.model_dump() for r in relay_history],
        }

    async def _generate_beat(
        self,
        beat: BeatPlan,
        context: ChapterContext,
        relay_history: list,
        last_beat_text: str,
        idx: int = 0,
        total: int = 1,
        is_last: bool = False,
        novel_id: str = "",
        rewrite_plan: dict | None = None,
    ) -> str:
        system_prompt = self._build_system_prompt(context, is_last)
        context_msg = self._build_context_message(
            beat, context, relay_history, last_beat_text, idx, total, is_last, rewrite_plan
        )
        retrieval_msg = await self._build_retrieval_message(beat, context, novel_id, idx)

        user_content = context_msg
        if retrieval_msg:
            user_content += "\n\n" + retrieval_msg
        user_content += "\n\n请直接输出本节拍正文："

        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_content),
        ]

        from novel_dev.llm import llm_factory
        client = llm_factory.get("WriterAgent", task="generate_beat")
        config = llm_factory._resolve_config("WriterAgent", "generate_beat")
        async with agent_step(
            novel_id,
            "WriterAgent",
            f"生成第 {idx + 1}/{total} 个节拍正文",
            node="generate_beat",
            task="generate_beat",
            metadata={"beat_index": idx, "total_beats": total},
        ):
            response = await client.acomplete(messages, config)
        inner = _strip_anchors(response.text)
        return f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"

    def _build_system_prompt(self, context: ChapterContext, is_last: bool) -> str:
        """Layer 1: Rules. Goes in system message for highest LLM priority."""
        parts = [
            "你是一位追求沉浸感与可读性的中文小说家。按以下约束生成正文。只返回正文，不添加解释。",
            self._build_style_guide_block(context),
            self._build_writing_rules_block(is_last),
        ]
        return "\n\n".join(p for p in parts if p)

    def _build_context_message(
        self, beat: BeatPlan, context: ChapterContext,
        relay_history: list, last_beat_text: str,
        idx: int, total: int, is_last: bool,
        rewrite_plan: dict | None = None,
    ) -> str:
        """Layer 2: Narrative context. Chapter plan + relays + recent beat text."""
        from novel_dev.schemas.context import NarrativeRelay
        parts = []

        if context.previous_chapter_summary:
            parts.append(f"### 前情回顾\n{context.previous_chapter_summary}")

        if context.worldview_summary:
            parts.append("### 世界观约束\n已加载到章节上下文；正文必须遵守检索到的设定与 guardrails，不要自行改写核心设定。")

        if context.location_context:
            location_lines = []
            if context.location_context.current:
                location_lines.append(f"当前地点: {context.location_context.current}")
            if context.location_context.parent:
                location_lines.append(f"上级区域: {context.location_context.parent}")
            if context.location_context.narrative:
                location_lines.append(f"场景镜头: {context.location_context.narrative}")
            if location_lines:
                parts.append("### 当前场景\n" + "\n".join(location_lines))

        if context.timeline_events:
            timeline_text = "\n".join(
                f"- tick {event.get('tick')}: {event.get('narrative')}"
                for event in context.timeline_events[:8]
            )
            parts.append(f"### 近期时间线\n{timeline_text}")

        beat_context = self._beat_context(context, idx)
        target_words = self._beat_target_word_count(context, total, beat)

        if beat_context and beat_context.guardrails:
            guardrail_text = "\n".join(f"- {item}" for item in beat_context.guardrails[:8])
            parts.append(f"### 当前节拍不可违背事实\n{guardrail_text}")
        elif context.guardrails:
            guardrail_text = "\n".join(f"- {item}" for item in context.guardrails[:12])
            parts.append(f"### 不可违背事实\n{guardrail_text}")

        if beat_context and beat_context.entities:
            entity_text = "\n".join(
                f"- [{entity.type}] {entity.name}: {entity.current_state[:300]}"
                for entity in beat_context.entities[:8]
            )
            parts.append(f"### 当前节拍相关实体\n{entity_text}")
        elif context.active_entities or context.related_entities:
            entity_items = context.active_entities + [
                e for e in context.related_entities
                if e.entity_id not in {active.entity_id for active in context.active_entities}
            ]
            entity_text = "\n".join(
                f"- [{entity.type}] {entity.name}: {entity.current_state[:300]}"
                for entity in entity_items[:10]
            )
            if entity_text:
                parts.append(f"### 本章相关实体\n{entity_text}")

        if beat_context and beat_context.relevant_documents:
            doc_text = "\n".join(
                f"- [{doc.doc_type}] {doc.title}: {doc.content_preview}"
                for doc in beat_context.relevant_documents[:3]
            )
            parts.append(f"### 当前节拍相关设定\n{doc_text}")
        elif context.relevant_documents:
            doc_text = "\n".join(
                f"- [{doc.doc_type}] {doc.title}: {doc.content_preview}"
                for doc in context.relevant_documents[:5]
            )
            parts.append(f"### 相关设定资料\n{doc_text}")

        if context.similar_chapters:
            chapter_text = "\n".join(
                f"- {doc.title}: {doc.content_preview}"
                for doc in context.similar_chapters[:3]
            )
            parts.append(f"### 相似章节风格参考\n{chapter_text}")

        if beat_context and beat_context.foreshadowings:
            fs_text = "\n".join(self._format_foreshadowing(fs) for fs in beat_context.foreshadowings[:5])
            parts.append(f"### 当前节拍伏笔安排\n{fs_text}")

        plan_lines = [f"本章：{context.chapter_plan.title}（共{total}个节拍）"]
        for i, b in enumerate(context.chapter_plan.beats):
            marker = "→ " if i == idx else "  "
            if i < idx:
                role = "已完成承接"
            elif i == idx:
                role = "当前必须完成"
            else:
                role = "后续边界，禁止提前发生"
            plan_lines.append(f"{marker}节拍{i+1}（{role}）: {b.summary}")
        parts.append("### 章节计划\n" + "\n".join(plan_lines))
        if idx + 1 < total:
            parts.append(
                "### 节拍边界硬约束\n"
                "后续节拍只是边界参考，用来知道当前节拍在哪里停止。"
                "禁止提前写后续节拍的核心事件、揭示、战斗、奇遇、昏迷、追兵到达或章末钩子；"
                "当前节拍结尾只能留下通向下一节拍的轻微预兆或动作，不得让下一节拍事件实际发生。"
            )
        parts.append(f"### 当前节拍目标字数\n约 {target_words} 字，允许 ±20%，不要明显缩水或灌水。")

        rewrite_focus = self._rewrite_focus_for_beat(rewrite_plan or {}, idx)
        if rewrite_focus:
            parts.append("### 本轮重写重点\n" + rewrite_focus)

        if relay_history:
            relay_text = "\n".join(
                f"[节拍{i+1}] {r.scene_state} | {r.emotional_tone} | 钩子: {r.next_beat_hook}"
                for i, r in enumerate(relay_history)
            )
            parts.append(f"### 已完成节拍状态\n{relay_text}")

        if last_beat_text:
            parts.append(f"### 紧邻上文（承接风格与情感）\n{last_beat_text}")

        position = f"（第{idx+1}/{total}个节拍{'|章末节拍' if is_last else ''}）"
        parts.append(f"### 当前节拍{position}\n{beat.model_dump_json()}")

        return "\n\n".join(parts)

    @staticmethod
    def _beat_target_word_count(context: ChapterContext, total: int, beat: BeatPlan | None = None) -> int:
        if beat and beat.target_word_count:
            return max(1, beat.target_word_count)
        total_beats = max(1, total)
        target = context.chapter_plan.target_word_count or 0
        return max(1, round(target / total_beats)) if target else 800

    @staticmethod
    def _rewrite_focus_for_beat(rewrite_plan: dict, beat_idx: int) -> str:
        if not rewrite_plan:
            return ""
        beat_issues = rewrite_plan.get("beat_issues") or []
        current = None
        if isinstance(beat_issues, list):
            current = next((item for item in beat_issues if item.get("beat_index") == beat_idx), None)
        elif isinstance(beat_issues, dict):
            current = beat_issues.get(beat_idx) or beat_issues.get(str(beat_idx))
        issues = (current or {}).get("issues") or []
        lines = []
        if rewrite_plan.get("summary_feedback"):
            lines.append(f"- 整体反馈: {rewrite_plan.get('summary_feedback')}")
        for issue in (rewrite_plan.get("global_issues") or [])[:3]:
            if not isinstance(issue, dict):
                continue
            dim = issue.get("dim") or "global"
            problem = issue.get("problem") or ""
            suggestion = issue.get("suggestion") or ""
            lines.append(f"- [全局/{dim}] {problem} -> {suggestion}")
        for issue in issues[:6]:
            if not isinstance(issue, dict):
                continue
            dim = issue.get("dim") or "issue"
            problem = issue.get("problem") or ""
            suggestion = issue.get("suggestion") or ""
            lines.append(f"- [{dim}] {problem} -> {suggestion}")
        return "\n".join(line for line in lines if line.strip())

    def _fallback_retrieval(self, beat: BeatPlan, context: ChapterContext, beat_idx: int | None = None) -> str:
        if beat_idx is not None:
            beat_context = self._beat_context(context, beat_idx)
            if beat_context:
                parts = []
                if beat_context.entities:
                    entity_text = "\n".join(
                        f"- [{entity.type}] {entity.name}: {entity.current_state[:300]}"
                        for entity in beat_context.entities[:6]
                    )
                    parts.append(f"### 当前节拍相关实体\n{entity_text}")
                if beat_context.relevant_documents:
                    doc_text = "\n".join(
                        f"- [{doc.doc_type}] {doc.title}: {doc.content_preview}"
                        for doc in beat_context.relevant_documents[:3]
                    )
                    parts.append(f"### 当前节拍相关设定\n{doc_text}")
                if beat_context.foreshadowings:
                    fs_text = "\n".join(
                        self._format_foreshadowing(fs) for fs in beat_context.foreshadowings[:3]
                    )
                    parts.append(f"### 待处理伏笔\n{fs_text}")
                if parts:
                    return "\n\n".join(parts)

        beat_entities = set(beat.key_entities)
        matched = [e for e in context.active_entities if e.name in beat_entities]
        if not matched:
            return ""
        text = "\n".join(f"- [{e.type}] {e.name}: {e.current_state[:300]}" for e in matched)
        return f"### 相关角色\n{text}"

    async def _build_retrieval_message(
        self, beat: BeatPlan, context: ChapterContext, novel_id: str, beat_idx: int,
    ) -> str:
        """Prefer ContextAgent-prepared beat context; only query on missing context."""
        beat_context = self._beat_context(context, beat_idx)
        needs_entity_fallback = not beat_context or not beat_context.entities
        needs_doc_fallback = not beat_context or not beat_context.relevant_documents
        needs_fs_fallback = not beat_context or not beat_context.foreshadowings

        if not self.embedding_service:
            return self._fallback_retrieval(beat, context, beat_idx)

        if not (needs_entity_fallback or needs_doc_fallback or needs_fs_fallback):
            return ""

        query = f"{beat.summary} {' '.join(beat.key_entities)}"
        parts = []

        if needs_entity_fallback:
            try:
                entities = await self.embedding_service.search_similar_entities(
                    novel_id=novel_id, query_text=query, limit=3
                )
                if entities:
                    entity_text = "\n".join(
                        f"- [{e.doc_type}] {e.title}: {e.content_preview}" for e in entities
                    )
                    parts.append(f"### 兜底角色/物品检索\n{entity_text}")
            except Exception as exc:
                log_service.add_log(novel_id, "WriterAgent", f"实体检索失败: {exc}", level="warning")

        if needs_doc_fallback:
            try:
                docs = await self.embedding_service.search_similar(
                    novel_id=novel_id, query_text=query, limit=2
                )
                if docs:
                    doc_text = "\n".join(
                        f"- [{d.doc_type}] {d.title}: {d.content_preview}" for d in docs
                    )
                    parts.append(f"### 兜底设定检索\n{doc_text}")
            except Exception as exc:
                log_service.add_log(novel_id, "WriterAgent", f"文档检索失败: {exc}", level="warning")

        if needs_fs_fallback:
            fallback_fs = [
                fs for fs in context.pending_foreshadowings
                if fs.target_beat_index == beat_idx
            ]
            if fallback_fs:
                fs_text = "\n".join(
                    self._format_foreshadowing(fs) for fs in fallback_fs[:3]
                )
                parts.append(f"### 兜底伏笔安排\n{fs_text}")

        return "\n\n".join(parts) if parts else self._fallback_retrieval(beat, context, beat_idx)

    def _format_foreshadowing(self, fs) -> str:
        parts = [f"- [{fs.role_in_chapter}] {fs.content}"]
        if fs.target_beat_index is not None:
            parts.append(f"目标节拍: {fs.target_beat_index + 1}")
        if fs.surface_hint:
            parts.append(f"露出方式: {fs.surface_hint}")
        if fs.payoff_requirement:
            parts.append(f"回收要求: {fs.payoff_requirement}")
        return "；".join(parts)

    def _beat_context(self, context: ChapterContext, beat_idx: int):
        if beat_idx < len(context.beat_contexts):
            return context.beat_contexts[beat_idx]
        return None

    async def _guard_writer_beat(
        self,
        *,
        novel_id: str,
        context: ChapterContext,
        beat: BeatPlan,
        inner: str,
        relay_history: list,
        last_beat_text: str,
        idx: int,
        total_beats: int,
        is_last: bool,
        rewrite_plan: dict | None,
        checkpoint: dict,
        state,
        chapter_id: str,
    ) -> tuple[str, str]:
        result = await self.structure_guard.check_writer_beat(
            novel_id=novel_id,
            chapter_plan=context.chapter_plan,
            beat_index=idx,
            beat=beat,
            generated_text=inner,
            previous_text=last_beat_text,
        )
        if result.passed:
            return inner, f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"

        evidence = result.evidence(beat_index=idx, mode="writer")
        checkpoint.setdefault("writer_guard_failures", []).append(evidence)
        checkpoint["chapter_structure_guard"] = evidence
        focus = result.suggested_rewrite_focus or "；".join(result.issues) or "严格停留在当前节拍计划内"
        log_agent_detail(
            novel_id,
            "WriterAgent",
            f"节拍 {idx + 1} 结构守卫未通过，按问题重写一次",
            node="writer_structure_guard",
            task="write",
            status="failed",
            level="warning",
            metadata=evidence,
        )
        guard_rewrite_plan = dict(rewrite_plan or {})
        prior_feedback = str(guard_rewrite_plan.get("summary_feedback") or "").strip()
        guard_feedback = f"结构守卫反馈: {focus}"
        guard_rewrite_plan["summary_feedback"] = (
            f"{prior_feedback}\n{guard_feedback}".strip() if prior_feedback else guard_feedback
        )
        guard_rewrite_plan["structure_guard_focus"] = focus
        rewritten = await self._rewrite_angle(
            beat,
            inner,
            context,
            relay_history,
            last_beat_text,
            idx,
            total_beats,
            is_last,
            None,
            novel_id,
            guard_rewrite_plan,
        )
        retry = await self.structure_guard.check_writer_beat(
            novel_id=novel_id,
            chapter_plan=context.chapter_plan,
            beat_index=idx,
            beat=beat,
            generated_text=rewritten,
            previous_text=last_beat_text,
        )
        if retry.passed:
            return rewritten, f"<!--BEAT:{idx}-->\n{rewritten}\n<!--/BEAT:{idx}-->"

        retry_evidence = retry.evidence(beat_index=idx, mode="writer_retry")
        checkpoint.setdefault("writer_guard_failures", []).append(retry_evidence)
        checkpoint["chapter_structure_guard"] = retry_evidence
        log_agent_detail(
            novel_id,
            "WriterAgent",
            f"节拍 {idx + 1} 结构守卫重写后仍未通过，停止章节生成",
            node="writer_structure_guard",
            task="write",
            status="failed",
            level="error",
            metadata=retry_evidence,
        )
        if state is not None:
            await self.state_repo.save_checkpoint(
                novel_id,
                current_phase=Phase.DRAFTING.value,
                checkpoint_data=checkpoint,
                current_volume_id=state.current_volume_id,
                current_chapter_id=state.current_chapter_id,
            )
        error = RuntimeError("Writer beat structure guard failed")
        setattr(error, "chapter_structure_guard", retry_evidence)
        setattr(error, "writer_guard_failures", list(checkpoint.get("writer_guard_failures") or []))
        setattr(error, "failed_phase", Phase.DRAFTING.value)
        raise error

    def _self_check_beat(self, inner: str, beat: BeatPlan, context: ChapterContext, beat_idx: int) -> BeatSelfCheck:
        beat_context = self._beat_context(context, beat_idx)
        missing_entities = []
        missing_foreshadowings = []
        contradictions = []

        if beat_context:
            normalized = self._normalize_for_check(inner)
            for entity in beat_context.entities:
                if not self._entity_represented(entity, normalized, beat):
                    missing_entities.append(entity.name)
            for fs in beat_context.foreshadowings:
                if (
                    fs.role_in_chapter == "embed"
                    and fs.target_beat_index == beat_idx
                    and fs.content
                    and fs.content in beat.foreshadowings_to_embed
                    and not self._foreshadowing_represented(fs, normalized)
                ):
                    missing_foreshadowings.append(fs.content)

        contradictions.extend(self._future_beat_leakage(inner, context, beat_idx))

        needs_rewrite = bool(missing_entities or missing_foreshadowings or contradictions)
        return BeatSelfCheck(
            missing_entities=missing_entities,
            missing_foreshadowings=missing_foreshadowings,
            contradictions=contradictions,
            needs_rewrite=needs_rewrite,
        )

    @staticmethod
    def _normalize_for_check(text: str) -> str:
        return re.sub(r"\s+", "", text or "")

    @classmethod
    def _future_beat_leakage(cls, inner: str, context: ChapterContext, beat_idx: int) -> list[str]:
        normalized_text = cls._normalize_for_check(inner)
        if not normalized_text:
            return []
        current_terms = cls._beat_boundary_terms(context.chapter_plan.beats[beat_idx].summary)
        issues = []
        for future_idx, future_beat in enumerate(context.chapter_plan.beats[beat_idx + 1:], start=beat_idx + 1):
            future_terms = [
                term for term in cls._beat_boundary_terms(future_beat.summary)
                if term not in current_terms
            ]
            matched = [term for term in future_terms if term in normalized_text]
            if cls._is_future_beat_leakage(matched, future_terms):
                preview = "、".join(matched[:5])
                issues.append(f"疑似提前写入后续节拍{future_idx + 1}核心事件: {preview}")
                break
        return issues

    @classmethod
    def _is_future_beat_leakage(cls, matched_terms: list[str], future_terms: list[str]) -> bool:
        if not matched_terms:
            return False
        distinctive_matches = [
            term for term in matched_terms
            if len(term) >= 3 or term in cls._HIGH_SIGNAL_BEAT_TERMS
        ]
        return len(distinctive_matches) >= 3 or (
            len(distinctive_matches) >= 2 and len(matched_terms) >= 4
        )

    _BEAT_TERM_STOPWORDS = {
        "一个", "一种", "一下", "一些", "大量", "无法", "不能", "开始", "继续", "进行",
        "当前", "后续", "节拍", "情绪", "描写", "铺垫", "核心", "事件", "瞬间",
    }
    _HIGH_SIGNAL_BEAT_TERMS = {
        "古经", "识海", "残念", "灵光", "昏迷", "流光", "追兵", "秘籍", "系统",
        "玉佩", "血脉", "入魔", "突破", "飞剑", "雷劫",
    }

    @classmethod
    def _beat_boundary_terms(cls, text: str) -> set[str]:
        normalized = cls._normalize_for_check(text)
        terms: set[str] = set()
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]{2,}", normalized):
            if token in cls._BEAT_TERM_STOPWORDS:
                continue
            terms.add(token)
            for size in (2, 3, 4):
                for start in range(0, len(token) - size + 1):
                    chunk = token[start:start + size]
                    if chunk not in cls._BEAT_TERM_STOPWORDS:
                        terms.add(chunk)
        return terms

    @classmethod
    def _entity_represented(cls, entity, normalized_text: str, beat: BeatPlan) -> bool:
        names = [entity.name, *(getattr(entity, "aliases", []) or [])]
        if any(name and cls._normalize_for_check(name) in normalized_text for name in names):
            return True
        is_planned_entity = entity.name in beat.key_entities or (entity.name and entity.name in beat.summary)
        if not is_planned_entity:
            return True
        return len(normalized_text) >= 35 and cls._has_contextual_reference(normalized_text)

    @staticmethod
    def _has_contextual_reference(normalized_text: str) -> bool:
        references = (
            "他", "她", "其", "此人", "这人", "那人", "那位", "这位",
            "少年", "少女", "青年", "男子", "女子", "老人", "师兄", "师姐", "师弟", "师妹",
        )
        return any(ref in normalized_text for ref in references)

    @classmethod
    def _foreshadowing_represented(cls, fs, normalized_text: str) -> bool:
        content = cls._normalize_for_check(fs.content)
        if content and content in normalized_text:
            return True
        surface_hint = cls._normalize_for_check(getattr(fs, "surface_hint", "") or "")
        if surface_hint and (surface_hint in normalized_text or cls._text_overlap(surface_hint, normalized_text) >= 0.55):
            return True
        return bool(content) and cls._text_overlap(content, normalized_text) >= 0.55

    @staticmethod
    def _text_overlap(needle: str, haystack: str) -> float:
        needle_chars = {
            ch for ch in needle
            if not ch.isspace() and ch not in "，。！？；：、,.!?;:（）()[]【】“”\"'"
        }
        if not needle_chars:
            return 0.0
        haystack_chars = set(haystack)
        return len(needle_chars & haystack_chars) / len(needle_chars)

    async def _generate_relay(
        self,
        beat_text: str,
        beat: BeatPlan,
        context: ChapterContext,
        beat_idx: int,
        next_beat: BeatPlan | None,
        novel_id: str = "",
    ) -> "NarrativeRelay":
        """Generate narrative state snapshot after a beat is written."""
        from novel_dev.schemas.context import NarrativeRelay
        from novel_dev.agents._llm_helpers import call_and_parse_model

        beat_context = self._beat_context(context, beat_idx)
        guardrails = beat_context.guardrails if beat_context else []
        foreshadowings = beat_context.foreshadowings if beat_context else []
        log_agent_detail(
            novel_id,
            "WriterAgent",
            f"叙事接力输入已准备：正文 {len(beat_text)} 字，约束 {len(guardrails)} 条，伏笔 {len(foreshadowings)} 条",
            node="generate_relay",
            task="generate_relay",
            status="started",
            metadata={
                "beat_index": beat_idx,
                "beat_summary_preview": preview_text(beat.summary),
                "next_beat_summary_preview": preview_text(next_beat.summary if next_beat else ""),
                "beat_text_chars": len(beat_text),
                "beat_text_preview": preview_text(beat_text, 300),
                "guardrails": guardrails,
                "foreshadowings": [fs.model_dump() for fs in foreshadowings[:3]],
            },
        )
        prompt = (
            "你是一位小说导演场记。请根据节拍目标、正文、约束和下一节拍目标，"
            "提取稳定叙事接力信息。不要把正文中疑似跑偏或违背约束的内容当成既定事实。\n"
            "返回严格 JSON：\n"
            '{"scene_state":"...","emotional_tone":"...","new_info_revealed":"...","open_threads":"...","next_beat_hook":"..."}\n\n'
            f"当前节拍目标: {beat.summary}\n"
            f"当前节拍情绪: {beat.target_mood}\n"
            f"下一节拍目标: {next_beat.summary if next_beat else '无，当前为章末'}\n"
            f"不可违背事实: {json.dumps(guardrails[:6], ensure_ascii=False)}\n"
            f"本节拍伏笔安排: {json.dumps([fs.model_dump() for fs in foreshadowings[:3]], ensure_ascii=False)}\n\n"
            f"正文:\n{beat_text[:3000]}\n\n"
            "要求：\n"
            "- scene_state 只记录能安全传递到下一节拍的稳定状态。\n"
            "- open_threads 记录尚未解决的问题、伏笔或冲突。\n"
            "- next_beat_hook 要服务下一节拍目标，不要凭空发明新主线。\n"
            "JSON:"
        )
        relay = await call_and_parse_model(
            "WriterAgent", "generate_relay", prompt,
            NarrativeRelay, max_retries=2, novel_id=novel_id,
        )
        log_agent_detail(
            novel_id,
            "WriterAgent",
            "叙事接力已生成",
            node="generate_relay",
            task="generate_relay",
            metadata={
                "beat_index": beat_idx,
                "scene_state_preview": preview_text(relay.scene_state),
                "emotional_tone": relay.emotional_tone,
                "new_info_preview": preview_text(relay.new_info_revealed),
                "open_threads_preview": preview_text(relay.open_threads),
                "next_beat_hook_preview": preview_text(relay.next_beat_hook),
            },
        )
        return relay

    def _build_style_guide_block(self, context: ChapterContext) -> str:
        """把 style_profile 单独置顶,避免 LLM 在长 JSON 中忽略它。"""
        sp = context.style_profile or {}
        if not sp:
            return ""
        try:
            sp_text = json.dumps(sp, ensure_ascii=False, indent=2)
        except Exception:
            sp_text = str(sp)
        return (
            "### 作品风格硬约束(必须遵守)\n"
            f"{sp_text}\n"
        )

    def _build_writing_rules_block(self, is_last: bool) -> str:
        hook_clause = (
            "- **章末钩子**:这是本章最后一个节拍,结尾必须给出明确悬念/反转/赌注升级/情绪爆点,"
            "禁止平淡收束,禁止用说教式总结结尾。\n"
        ) if is_last else (
            "- **节拍内钩子**:结尾留一个能把读者推到下一个节拍的动作、疑问或冲突,不要写完整收束。\n"
        )
        return (
            "### 写作硬约束\n"
            "- **禁用词表**(避免 AI 腔):于是、总之、综上所述、综合来看、总的来说、"
            "这一切、一切的一切、无比、仿佛(非比喻不用)、似乎(非推测不用)、显然、无疑、"
            "油然而生、涌上心头、心头一震、深深地/静静地/默默地(避免叠用)。\n"
            "- **语言纯度**:禁止输出英文、拼音、网络缩写和 UI 术语原文(如 snooze/APP/OK),"
            "除非章节计划明确要求角色说外语；前世概念也必须转写成自然中文表达。\n"
            "- **显示不说**(show don't tell):禁止直接写『他感到愤怒』『她意识到』『他明白了』,"
            "改为用具体动作、生理反应、对话潜台词、环境反衬来呈现情绪和认知。\n"
            "- **低 AI 味默认准则**:优先遵守 style_profile；style_profile 未明确要求华丽、轻松或吐槽时,"
            "默认写得克制、具体、生活化。控制比喻密度,同一节拍不要连续用 3 个以上『像/仿佛/似乎』解释感受;"
            "减少『意识深处、存在、光点、温热感、沉入、古经』等抽象玄幻词连环复读。\n"
            "- **奇遇/异象写法**:避免奇观堆叠和模板化传承演出。不要把视觉、听觉、触觉、痛觉平均铺满;"
            "选择最有辨识度的 1-2 个画面,落到身体反应、行动阻碍、具体后果和下一步因果钩子。\n"
            "- **现代吐槽**:只有 style_profile 明确允许轻松吐槽/反差喜剧时才放大现代梗;"
            "否则现代记忆只作短促念头,必须贴合角色处境,不得削弱当前场景压迫感。\n"
            "- **对话占比**目标 30%-50%,对话要带潜台词/打断/回避,不要做问答式信息交代。\n"
            "- **句式节奏**:长短句交替,动作场景用短句推进,情绪/景物可用长句铺陈;"
            "避免连续 3 句相同结构(如连续『XX 的 XX,XX 的 XX』)。\n"
            "- **视点一致**:全章保持设定视点(默认紧贴主角),不得中途跳入他人内心。\n"
            "- **开场多样性**:禁止以『清晨/黄昏/夜幕/阳光透过』等套路环境描写起笔,"
            "用动作、对话、具象物件或反常细节切入。\n"
            f"{hook_clause}"
            "- **字数**:按用户消息中的当前节拍目标字数写作,允许 ±20%。\n"
            "- **伏笔**:pending_foreshadowings 中标注 role_in_chapter=embed 的条目,"
            "请自然嵌入文本(不要点破,不要写成注解)。\n"
        )

    async def _rewrite_angle(
        self,
        beat: BeatPlan,
        original_text: str,
        context: ChapterContext,
        relay_history: list = None,
        last_beat_text: str = "",
        idx: int = 0,
        total: int = 1,
        is_last: bool = False,
        self_check: BeatSelfCheck | None = None,
        novel_id: str = "",
        rewrite_plan: dict | None = None,
    ) -> str:
        system_prompt = self._build_system_prompt(context, is_last)
        context_msg = self._build_context_message(
            beat, context, relay_history or [], last_beat_text,
            idx, total, is_last, rewrite_plan,
        )
        fix_block = ""
        if self_check and self_check.needs_rewrite:
            issues = []
            if self_check.missing_entities:
                issues.append("缺少关键实体: " + "、".join(self_check.missing_entities))
            if self_check.missing_foreshadowings:
                issues.append("缺少伏笔: " + "、".join(self_check.missing_foreshadowings))
            if self_check.contradictions:
                issues.append("疑似违背约束: " + "；".join(self_check.contradictions))
            fix_block = "### 本次重写必须修复的问题\n" + "\n".join(f"- {issue}" for issue in issues) + "\n\n"
        structure_guard_focus = str((rewrite_plan or {}).get("structure_guard_focus") or "").strip()
        if structure_guard_focus:
            fix_block += (
                "### 结构守卫硬性修复\n"
                f"- 必须修复: {structure_guard_focus}\n"
                "- 删除计划外的具体地点、人物背景、物件来历、台词、线索和因果；不要换一种说法继续保留。\n"
                "- 允许保留氛围、身体反应、动作承接和模糊悬念，但不得把模糊指向写成具体目的地或新设定。\n"
                "- 当前 beat 摘要没有明确写出的专名和事实，不要新增。\n\n"
            )
        user_content = (
            f"{context_msg}\n\n"
            f"{fix_block}"
            f"### 当前文本\n{original_text}\n\n"
            "请在遵守上述约束的前提下重写，优先补足缺失信息并消除冲突。"
            "如果本次是结构守卫重写，宁可删减具体化发挥，也不要新增计划外剧情。"
            "只返回重写后的正文，不添加解释："
        )
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_content),
        ]
        from novel_dev.llm import llm_factory
        client = llm_factory.get("WriterAgent", task="rewrite_beat")
        config = llm_factory._resolve_config("WriterAgent", "rewrite_beat")
        async with agent_step(
            novel_id,
            "WriterAgent",
            f"重写第 {idx + 1}/{total} 个节拍",
            node="rewrite_beat",
            task="rewrite_beat",
            metadata={"beat_index": idx, "total_beats": total},
        ):
            response = await client.acomplete(messages, config)
        return _strip_anchors(response.text).strip()
