import re
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.llm.models import ChatMessage
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.services.flow_control_service import FlowControlService
from novel_dev.services.log_service import agent_step, logged_agent_step, log_service


BEAT_ANCHOR_RE = re.compile(r"<!--BEAT:(\d+)-->(.*?)<!--/BEAT:\1-->", re.DOTALL)


def split_beats(raw_draft: str) -> Tuple[List[str], bool]:
    """按 Writer 的锚点切 beat;无锚点时回退到 \\n\\n 切分。
    返回 (beats, anchored)。"""
    if not raw_draft:
        return [], False
    matches = BEAT_ANCHOR_RE.findall(raw_draft)
    if matches:
        return [m[1].strip() for m in matches], True
    return raw_draft.split("\n\n"), False


class EditorAgent:
    def __init__(self, session: AsyncSession, embedding_service: Optional[EmbeddingService] = None):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)
        self.embedding_service = embedding_service

    @logged_agent_step("EditorAgent", "精修章节", node="edit", task="polish")
    async def polish(self, novel_id: str, chapter_id: str):
        log_service.add_log(novel_id, "EditorAgent", f"开始精修章节: {chapter_id}")
        state = await self.state_repo.get_state(novel_id)
        if not state:
            log_service.add_log(novel_id, "EditorAgent", "小说状态未找到", level="error")
            raise ValueError(f"Novel state not found for {novel_id}")
        if state.current_phase != Phase.EDITING.value:
            log_service.add_log(novel_id, "EditorAgent", f"当前阶段 {state.current_phase} 不允许编辑", level="error")
            raise ValueError(f"Cannot edit from phase {state.current_phase}")

        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            log_service.add_log(novel_id, "EditorAgent", f"章节未找到: {chapter_id}", level="error")
            raise ValueError(f"Chapter not found: {chapter_id}")

        checkpoint = dict(state.checkpoint_data or {})
        checkpoint["edit_attempt_count"] = checkpoint.get("edit_attempt_count", 0) + 1
        log_service.add_log(novel_id, "EditorAgent", f"第 {checkpoint['edit_attempt_count']} 次精修尝试")
        beat_scores = checkpoint.get("beat_scores", [])
        per_dim_issues = checkpoint.get("per_dim_issues", [])
        critique = checkpoint.get("critique_feedback", {}) or {}
        chapter_context = checkpoint.get("chapter_context", {})
        raw_draft = ch.raw_draft or ""
        beats, _ = split_beats(raw_draft)

        # 章末钩子弱 -> 强制改最后一个 beat,即便它本身 beat-level 分数不低
        hook_score = None
        breakdown = critique.get("breakdown") or {}
        if isinstance(breakdown, dict):
            hook_entry = breakdown.get("hook_strength") or {}
            if isinstance(hook_entry, dict):
                hook_score = hook_entry.get("score")
        force_last_beat_rewrite = (
            hook_score is not None
            and isinstance(hook_score, (int, float))
            and hook_score < 70
            and len(beats) > 0
        )

        # 按 beat_idx 聚合问题,避免 Editor 不知道改什么
        issues_by_beat: dict[int, list] = {}
        whole_chapter_issues: list = []
        for issue in per_dim_issues:
            bi = issue.get("beat_idx")
            if bi is None:
                whole_chapter_issues.append(issue)
            else:
                issues_by_beat.setdefault(bi, []).append(issue)

        last_idx = len(beats) - 1
        polished_beats = []
        flow_control = FlowControlService(self.session)
        for idx, beat_text in enumerate(beats):
            await flow_control.raise_if_cancelled(novel_id)
            score_entry = beat_scores[idx] if idx < len(beat_scores) else {}
            scores = score_entry.get("scores", {})
            beat_level_issues = score_entry.get("issues", []) or []
            chapter_issues = issues_by_beat.get(idx, [])
            all_issues = chapter_issues + beat_level_issues

            # 章末钩子弱时强制改最后一个 beat,并注入一条章末改写指引
            is_forced_last = force_last_beat_rewrite and idx == last_idx
            if is_forced_last and not any(it.get("dim") == "hook_strength" for it in all_issues):
                all_issues = all_issues + [{
                    "dim": "hook_strength",
                    "beat_idx": last_idx,
                    "problem": f"章末钩子评分 {hook_score} 低于 70,结尾未能让读者想读下一章",
                    "suggestion": "改写章末,给出以下任一要素:明确悬念、反转、赌注升级、情绪爆点或呼应已埋伏笔",
                }]

            needs_rewrite = any(s < 70 for s in scores.values()) or bool(all_issues) or is_forced_last
            if needs_rewrite:
                log_service.add_log(novel_id, "EditorAgent", f"改写第 {idx + 1} 个节拍 ({len(beat_text)} 字)")
                async with agent_step(
                    novel_id,
                    "EditorAgent",
                    f"改写第 {idx + 1} 个节拍",
                    node="polish_beat",
                    task="polish_beat",
                    metadata={"beat_index": idx, "source_words": len(beat_text)},
                ):
                    polished = await self._rewrite_beat(
                        beat_text, scores, all_issues, whole_chapter_issues, chapter_context,
                    )
                log_service.add_log(novel_id, "EditorAgent", f"第 {idx + 1} 个节拍改写完成 ({len(polished)} 字)")
            else:
                log_service.add_log(novel_id, "EditorAgent", f"第 {idx + 1} 个节拍无需改写")
                polished = beat_text
            polished_beats.append(polished)
            await flow_control.raise_if_cancelled(novel_id)

        polished_text = "\n\n".join(polished_beats)
        await self.chapter_repo.update_text(chapter_id, polished_text=polished_text)
        log_service.add_log(novel_id, "EditorAgent", f"精修完成，总字数: {len(polished_text)}")
        if self.embedding_service:
            try:
                await self.embedding_service.index_chapter(chapter_id)
            except Exception as exc:
                log_service.add_log(novel_id, "EditorAgent", f"章节索引失败: {exc}", level="warning")
        await self.chapter_repo.update_status(chapter_id, "edited")

        await self.director.save_checkpoint(
            novel_id,
            phase=Phase.FAST_REVIEWING,
            checkpoint_data=checkpoint,
            volume_id=state.current_volume_id,
            chapter_id=state.current_chapter_id,
        )
        log_service.add_log(novel_id, "EditorAgent", "进入 fast_reviewing 阶段")

    async def polish_standalone(self, novel_id: str, chapter_id: str, checkpoint: dict) -> str:
        log_service.add_log(novel_id, "EditorAgent", f"开始独立精修章节: {chapter_id}")
        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")

        beat_scores = checkpoint.get("beat_scores", [])
        per_dim_issues = checkpoint.get("per_dim_issues", [])
        critique = checkpoint.get("critique_feedback", {}) or {}
        chapter_context = checkpoint.get("chapter_context", {})
        raw_draft = ch.raw_draft or ""
        beats, _ = split_beats(raw_draft)

        hook_score = None
        breakdown = critique.get("breakdown") or {}
        if isinstance(breakdown, dict):
            hook_entry = breakdown.get("hook_strength") or {}
            if isinstance(hook_entry, dict):
                hook_score = hook_entry.get("score")
        force_last_beat_rewrite = (
            hook_score is not None
            and isinstance(hook_score, (int, float))
            and hook_score < 70
            and len(beats) > 0
        )

        issues_by_beat: dict[int, list] = {}
        whole_chapter_issues: list = []
        for issue in per_dim_issues:
            bi = issue.get("beat_idx")
            if bi is None:
                whole_chapter_issues.append(issue)
            else:
                issues_by_beat.setdefault(bi, []).append(issue)

        last_idx = len(beats) - 1
        polished_beats = []
        flow_control = FlowControlService(self.session)
        for idx, beat_text in enumerate(beats):
            await flow_control.raise_if_cancelled(novel_id)
            score_entry = beat_scores[idx] if idx < len(beat_scores) else {}
            scores = score_entry.get("scores", {})
            beat_level_issues = score_entry.get("issues", []) or []
            chapter_issues = issues_by_beat.get(idx, [])
            all_issues = chapter_issues + beat_level_issues
            is_forced_last = force_last_beat_rewrite and idx == last_idx
            if is_forced_last and not any(it.get("dim") == "hook_strength" for it in all_issues):
                all_issues = all_issues + [{
                    "dim": "hook_strength",
                    "beat_idx": last_idx,
                    "problem": f"章末钩子评分 {hook_score} 低于 70,结尾未能让读者想读下一章",
                    "suggestion": "改写章末,给出明确悬念、反转、赌注升级、情绪爆点或呼应已埋伏笔",
                }]
            needs_rewrite = any(s < 70 for s in scores.values()) or bool(all_issues) or is_forced_last
            if needs_rewrite:
                polished = await self._rewrite_beat(
                    beat_text, scores, all_issues, whole_chapter_issues, chapter_context,
                )
            else:
                polished = beat_text
            polished_beats.append(polished)

        polished_text = "\n\n".join(polished_beats)
        await self.chapter_repo.update_text(chapter_id, polished_text=polished_text)
        if self.embedding_service:
            try:
                await self.embedding_service.index_chapter(chapter_id)
            except Exception as exc:
                log_service.add_log(novel_id, "EditorAgent", f"独立精修章节索引失败: {exc}", level="warning")
        await self.chapter_repo.update_status(chapter_id, "edited")
        return polished_text

    async def _rewrite_beat(
        self,
        text: str,
        scores: dict,
        issues: list,
        whole_chapter_issues: list,
        chapter_context: dict,
    ) -> str:
        low_dims = [k for k, v in scores.items() if v < 70]
        issue_lines = []
        for it in issues:
            issue_lines.append(
                f"- [{it.get('dim')}] 问题: {it.get('problem')}\n  建议: {it.get('suggestion')}"
            )
        whole_lines = []
        for it in whole_chapter_issues[:3]:
            whole_lines.append(
                f"- [{it.get('dim')}] 整章共性: {it.get('problem')} -> {it.get('suggestion')}"
            )

        style_profile = chapter_context.get("style_profile", {})
        style_block = ""
        if style_profile:
            import json
            style_block = f"### 作品风格约束\n{json.dumps(style_profile, ensure_ascii=False, indent=2)}\n\n"

        chapter_plan = chapter_context.get("chapter_plan", {})
        plan_block = ""
        if chapter_plan:
            import json
            plan_block = f"### 章节计划\n{json.dumps(chapter_plan, ensure_ascii=False)}\n\n"

        prompt_parts = [
            "你是一位小说编辑。请在『保留原情节与原对话意图』的前提下,针对以下问题定点改写本段,"
            "只返回改写后的正文,不要添加任何解释、标签或编号。\n",
            "## 改写准则(必须遵守)\n"
            "1. 禁用 AI 腔词汇:于是/总之/综上所述/这一切/无比/仿佛/似乎(非必要时)/油然而生/涌上心头。\n"
            "2. 显示不说(show don't tell):用动作/对话/细节替代『他感到 X』『她想到 Y』这类直述。\n"
            "3. 删除冗余总结段,避免复读前文已交代的信息。\n"
            "4. 禁止输出英文、拼音、网络缩写和 UI 术语原文(如 snooze/APP/OK),"
            "把前世或现代概念转写成自然中文表达。\n"
            "5. 保持与原段相近的字数(±20%),不要大幅缩水或灌水。\n",
            style_block,
            plan_block,
        ]
        if low_dims:
            prompt_parts.append(f"## 低分维度\n{', '.join(low_dims)}\n")
        if issue_lines:
            prompt_parts.append("## 本段具体问题(必须逐条解决)\n" + "\n".join(issue_lines) + "\n")
        if whole_lines:
            prompt_parts.append("## 整章通病(写本段时顺带注意)\n" + "\n".join(whole_lines) + "\n")
        prompt_parts.append(f"## 原文\n{text}\n\n改写:")

        prompt = "\n".join(p for p in prompt_parts if p)
        from novel_dev.llm import llm_factory
        client = llm_factory.get("EditorAgent", task="polish_beat")
        response = await client.acomplete([ChatMessage(role="user", content=prompt)])
        return response.text.strip()
