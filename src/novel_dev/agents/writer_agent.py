import asyncio
import json
import re
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.schemas.context import ChapterContext, DraftMetadata, BeatPlan
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.llm.models import ChatMessage
from novel_dev.services.embedding_service import EmbeddingService


_BEAT_ANCHOR_STRIP_RE = re.compile(r"<!--/?BEAT:\d+-->")


def _strip_anchors(text: str) -> str:
    return _BEAT_ANCHOR_STRIP_RE.sub("", text).strip()


class WriterAgent:
    def __init__(self, session: AsyncSession, embedding_service: Optional[EmbeddingService] = None):
        self.session = session
        self.chapter_repo = ChapterRepository(session)
        self.state_repo = NovelStateRepository(session)
        self.director = NovelDirector(session)
        self.embedding_service = embedding_service

    async def write(self, novel_id: str, context: ChapterContext, chapter_id: str) -> DraftMetadata:
        state = await self.state_repo.get_state(novel_id)
        if not state:
            raise ValueError(f"Novel state not found for {novel_id}")

        if state.current_phase != Phase.DRAFTING.value:
            raise ValueError(f"Cannot write draft from phase {state.current_phase}")

        checkpoint = dict(state.checkpoint_data or {})
        if not checkpoint.get("chapter_context"):
            raise ValueError("chapter_context missing in checkpoint_data")

        raw_draft = ""
        beat_coverage = []
        embedded_foreshadowings = []
        style_violations = []
        total_beats = len(context.chapter_plan.beats)

        from novel_dev.schemas.context import NarrativeRelay
        relay_history: List[NarrativeRelay] = []
        inner_beats: List[str] = []

        for idx, beat in enumerate(context.chapter_plan.beats):
            is_last = (idx == total_beats - 1)
            last_beat_text = inner_beats[-1] if inner_beats else ""

            beat_text = await self._generate_beat(
                beat, context, relay_history, last_beat_text,
                idx, total_beats, is_last, novel_id,
            )
            inner = _strip_anchors(beat_text)
            if len(inner) < 50:
                inner = await self._rewrite_angle(
                    beat, inner, context,
                    relay_history, last_beat_text,
                    idx, total_beats, is_last,
                )
                beat_text = f"<!--BEAT:{idx}-->\n{inner}\n<!--/BEAT:{idx}-->"

            inner_beats.append(inner)
            raw_draft += beat_text + "\n\n"
            beat_coverage.append({"beat_index": idx, "word_count": len(inner)})

            # Generate narrative relay baton
            try:
                relay = await self._generate_relay(inner, beat)
                relay_history.append(relay)
            except Exception:
                relay_history.append(NarrativeRelay(
                    scene_state=beat.summary,
                    emotional_tone=beat.target_mood,
                    new_info_revealed="",
                    open_threads="",
                    next_beat_hook="",
                ))

            for fs in context.pending_foreshadowings:
                if fs["content"] in inner and fs["id"] not in embedded_foreshadowings:
                    embedded_foreshadowings.append(fs["id"])

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

        metadata = DraftMetadata(
            total_words=len(raw_draft),
            beat_coverage=beat_coverage,
            style_violations=style_violations,
            embedded_foreshadowings=embedded_foreshadowings,
        )

        await self.chapter_repo.update_text(chapter_id, raw_draft=raw_draft.strip())
        if self.embedding_service:
            try:
                asyncio.create_task(self.embedding_service.index_chapter(chapter_id))
            except Exception:
                pass
        await self.chapter_repo.update_status(chapter_id, "drafted")

        checkpoint["draft_metadata"] = metadata.model_dump()
        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.REVIEWING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )

        return metadata

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
    ) -> str:
        system_prompt = self._build_system_prompt(context, is_last)
        context_msg = self._build_context_message(
            beat, context, relay_history, last_beat_text, idx, total, is_last
        )
        retrieval_msg = await self._build_retrieval_message(beat, context, novel_id)

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
    ) -> str:
        """Layer 2: Narrative context. Chapter plan + relays + recent beat text."""
        from novel_dev.schemas.context import NarrativeRelay
        parts = []

        if context.previous_chapter_summary:
            parts.append(f"### 前情回顾\n{context.previous_chapter_summary}")

        plan_lines = [f"本章：{context.chapter_plan.title}（共{total}个节拍）"]
        for i, b in enumerate(context.chapter_plan.beats):
            marker = "→ " if i == idx else "  "
            plan_lines.append(f"{marker}节拍{i+1}: {b.summary}")
        parts.append("### 章节计划\n" + "\n".join(plan_lines))

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

    def _fallback_retrieval(self, beat: BeatPlan, context: ChapterContext) -> str:
        """No EmbeddingService fallback: match by key_entities names."""
        beat_entities = set(beat.key_entities)
        matched = [e for e in context.active_entities if e.name in beat_entities]
        if not matched:
            return ""
        text = "\n".join(f"- [{e.type}] {e.name}: {e.current_state[:300]}" for e in matched)
        return f"### 相关角色\n{text}"

    async def _build_retrieval_message(
        self, beat: BeatPlan, context: ChapterContext, novel_id: str,
    ) -> str:
        """Layer 3: Per-beat semantic retrieval for entities/docs/foreshadowings."""
        if not self.embedding_service:
            return self._fallback_retrieval(beat, context)

        query = f"{beat.summary} {' '.join(beat.key_entities)}"
        parts = []

        try:
            entities = await self.embedding_service.search_similar_entities(
                novel_id=novel_id, query_text=query, limit=3
            )
            if entities:
                entity_text = "\n".join(
                    f"- [{e.doc_type}] {e.title}: {e.content_preview}" for e in entities
                )
                parts.append(f"### 相关角色/物品\n{entity_text}")
        except Exception:
            pass

        try:
            docs = await self.embedding_service.search_similar(
                novel_id=novel_id, query_text=query, limit=2
            )
            if docs:
                doc_text = "\n".join(
                    f"- [{d.doc_type}] {d.title}: {d.content_preview}" for d in docs
                )
                parts.append(f"### 相关设定\n{doc_text}")
        except Exception:
            pass

        beat_entities = set(beat.key_entities)
        relevant_fs = [
            fs for fs in context.pending_foreshadowings
            if beat_entities & set(fs.get("related_entity_names", []))
        ]
        if relevant_fs:
            fs_text = "\n".join(
                f"- {fs['content']}（需自然嵌入，不要点破）" for fs in relevant_fs[:3]
            )
            parts.append(f"### 待嵌入伏笔\n{fs_text}")

        return "\n\n".join(parts) if parts else self._fallback_retrieval(beat, context)

    async def _generate_relay(self, beat_text: str, beat: BeatPlan) -> "NarrativeRelay":
        """Generate narrative state snapshot after a beat is written."""
        from novel_dev.schemas.context import NarrativeRelay
        from novel_dev.agents._llm_helpers import call_and_parse
        prompt = (
            "你是一位叙事分析师。请阅读以下小说节拍正文，提取当前叙事状态。\n"
            "返回严格 JSON：\n"
            '{"scene_state":"...","emotional_tone":"...","new_info_revealed":"...","open_threads":"...","next_beat_hook":"..."}\n\n'
            f"节拍计划: {beat.summary}\n\n"
            f"正文:\n{beat_text[:2000]}\n\n"
            "JSON:"
        )
        return await call_and_parse(
            "WriterAgent", "generate_relay", prompt,
            NarrativeRelay.model_validate_json, max_retries=2,
        )

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
            "- **显示不说**(show don't tell):禁止直接写『他感到愤怒』『她意识到』『他明白了』,"
            "改为用具体动作、生理反应、对话潜台词、环境反衬来呈现情绪和认知。\n"
            "- **对话占比**目标 30%-50%,对话要带潜台词/打断/回避,不要做问答式信息交代。\n"
            "- **句式节奏**:长短句交替,动作场景用短句推进,情绪/景物可用长句铺陈;"
            "避免连续 3 句相同结构(如连续『XX 的 XX,XX 的 XX』)。\n"
            "- **视点一致**:全章保持设定视点(默认紧贴主角),不得中途跳入他人内心。\n"
            "- **开场多样性**:禁止以『清晨/黄昏/夜幕/阳光透过』等套路环境描写起笔,"
            "用动作、对话、具象物件或反常细节切入。\n"
            f"{hook_clause}"
            "- **字数**:按节拍 target_word_count 估算,允许 ±20%。\n"
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
    ) -> str:
        system_prompt = self._build_system_prompt(context, is_last)
        context_msg = self._build_context_message(
            beat, context, relay_history or [], last_beat_text,
            idx, total, is_last,
        )
        user_content = (
            f"{context_msg}\n\n"
            f"### 当前过短文本（需扩写）\n{original_text}\n\n"
            "请在遵守上述约束的前提下扩写，保持与上下文的连贯。只返回扩写后的正文，不添加解释："
        )
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_content),
        ]
        from novel_dev.llm import llm_factory
        client = llm_factory.get("WriterAgent", task="rewrite_beat")
        config = llm_factory._resolve_config("WriterAgent", "rewrite_beat")
        response = await client.acomplete(messages, config)
        return _strip_anchors(response.text).strip()
