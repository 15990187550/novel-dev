import re
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.repositories.novel_state_repo import NovelStateRepository
from novel_dev.repositories.chapter_repo import ChapterRepository
from novel_dev.agents.director import NovelDirector, Phase
from novel_dev.llm.models import ChatMessage
from novel_dev.agents._log_helpers import log_agent_detail, preview_text
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.services.flow_control_service import FlowControlService
from novel_dev.services.log_service import agent_step, logged_agent_step, log_service
from novel_dev.services.chapter_structure_guard_service import ChapterStructureGuardService


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
    def __init__(
        self,
        session: AsyncSession,
        embedding_service: Optional[EmbeddingService] = None,
        structure_guard: Optional[ChapterStructureGuardService] = None,
    ):
        self.session = session
        self.state_repo = NovelStateRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.director = NovelDirector(session)
        self.embedding_service = embedding_service
        self.structure_guard = structure_guard or ChapterStructureGuardService()

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
        log_agent_detail(
            novel_id,
            "EditorAgent",
            f"精修输入已准备：第 {checkpoint['edit_attempt_count']} 次尝试",
            node="edit_input",
            task="polish",
            status="started",
            metadata={
                "chapter_id": chapter_id,
                "attempt": checkpoint["edit_attempt_count"],
                "raw_chars": len(ch.raw_draft or ""),
                "beat_score_count": len(checkpoint.get("beat_scores", [])),
                "per_dim_issue_count": len(checkpoint.get("per_dim_issues", [])),
                "overall": (checkpoint.get("critique_feedback") or {}).get("overall"),
            },
        )
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
        continuity_issues, force_continuity_rewrite = self._continuity_rewrite_issues(checkpoint)
        whole_chapter_issues.extend(continuity_issues)

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
                    "suggestion": "改写章末,只能用当前节拍已存在的事实给出明确悬念、反转、赌注升级、情绪爆点或呼应已埋伏笔",
                }]

            needs_rewrite = any(s < 70 for s in scores.values()) or bool(all_issues) or is_forced_last or force_continuity_rewrite
            if needs_rewrite:
                log_agent_detail(
                    novel_id,
                    "EditorAgent",
                    f"节拍 {idx + 1} 需要改写",
                    node="polish_beat_decision",
                    task="polish",
                    status="started",
                    metadata={
                        "beat_index": idx,
                        "source_chars": len(beat_text),
                        "scores": scores,
                        "low_dimensions": [dim for dim, score in scores.items() if score < 70],
                        "issues": all_issues[:12],
                        "whole_chapter_issues": whole_chapter_issues[:6],
                        "forced_last_beat": is_forced_last,
                    },
                )
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
                polished = await self._guard_editor_beat(
                    novel_id=novel_id,
                    chapter_context=chapter_context,
                    beat_index=idx,
                    source_text=beat_text,
                    polished_text=polished,
                    checkpoint=checkpoint,
                    retry_factory=lambda evidence, idx=idx, beat_text=beat_text, scores=scores: self._retry_rewrite_beat_after_guard(
                        source_text=beat_text,
                        scores=scores,
                        guard_evidence=evidence,
                        whole_chapter_issues=whole_chapter_issues,
                        chapter_context=chapter_context,
                    ),
                )
                log_agent_detail(
                    novel_id,
                    "EditorAgent",
                    f"节拍 {idx + 1} 改写完成：{len(beat_text)}→{len(polished)} 字",
                    node="polish_beat_result",
                    task="polish",
                    metadata={
                        "beat_index": idx,
                        "source_chars": len(beat_text),
                        "polished_chars": len(polished),
                        "preview": preview_text(polished, 300),
                    },
                )
            else:
                log_agent_detail(
                    novel_id,
                    "EditorAgent",
                    f"节拍 {idx + 1} 无需改写",
                    node="polish_beat_decision",
                    task="polish",
                    metadata={
                        "beat_index": idx,
                        "source_chars": len(beat_text),
                        "scores": scores,
                        "issue_count": len(all_issues),
                    },
                )
                polished = beat_text
            polished_beats.append(polished)
            await flow_control.raise_if_cancelled(novel_id)

        polished_text = "\n\n".join(polished_beats)
        await self.chapter_repo.update_text(chapter_id, polished_text=polished_text)
        log_agent_detail(
            novel_id,
            "EditorAgent",
            f"精修完成：总字数 {len(polished_text)}",
            node="edit_result",
            task="polish",
            metadata={
                "chapter_id": chapter_id,
                "raw_chars": len(raw_draft),
                "polished_chars": len(polished_text),
                "beat_count": len(beats),
            },
        )
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
        continuity_issues, force_continuity_rewrite = self._continuity_rewrite_issues(checkpoint)
        whole_chapter_issues.extend(continuity_issues)

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
                    "suggestion": "改写章末,只能用当前节拍已存在的事实给出明确悬念、反转、赌注升级、情绪爆点或呼应已埋伏笔",
                }]
            needs_rewrite = any(s < 70 for s in scores.values()) or bool(all_issues) or is_forced_last or force_continuity_rewrite
            if needs_rewrite:
                polished = await self._rewrite_beat(
                    beat_text, scores, all_issues, whole_chapter_issues, chapter_context,
                )
                polished = await self._guard_editor_beat(
                    novel_id=novel_id,
                    chapter_context=chapter_context,
                    beat_index=idx,
                    source_text=beat_text,
                    polished_text=polished,
                    checkpoint=checkpoint,
                    retry_factory=lambda evidence, idx=idx, beat_text=beat_text, scores=scores: self._retry_rewrite_beat_after_guard(
                        source_text=beat_text,
                        scores=scores,
                        guard_evidence=evidence,
                        whole_chapter_issues=whole_chapter_issues,
                        chapter_context=chapter_context,
                    ),
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

    async def _guard_editor_beat(
        self,
        *,
        novel_id: str,
        chapter_context: dict,
        beat_index: int,
        source_text: str,
        polished_text: str,
        checkpoint: dict,
        retry_factory=None,
    ) -> str:
        chapter_plan = chapter_context.get("chapter_plan") if isinstance(chapter_context, dict) else chapter_context
        result = await self.structure_guard.check_editor_beat(
            novel_id=novel_id,
            chapter_plan=chapter_plan or {},
            beat_index=beat_index,
            source_text=source_text,
            polished_text=polished_text,
        )
        if result.passed:
            return polished_text

        evidence = result.evidence(beat_index=beat_index, mode="editor")
        evidence["source_chars"] = len(source_text)
        evidence["polished_chars"] = len(polished_text)
        checkpoint.setdefault("editor_guard_warnings", []).append(evidence)
        checkpoint["chapter_structure_guard"] = evidence
        log_agent_detail(
            novel_id,
            "EditorAgent",
            f"节拍 {beat_index + 1} 润色触发结构守卫，回退原文",
            node="editor_structure_guard",
            task="polish",
            status="failed",
            level="warning",
            metadata=evidence,
        )
        if retry_factory is not None:
            retry_text = await retry_factory(evidence)
            retry_result = await self.structure_guard.check_editor_beat(
                novel_id=novel_id,
                chapter_plan=chapter_plan or {},
                beat_index=beat_index,
                source_text=source_text,
                polished_text=retry_text,
            )
            if retry_result.passed:
                log_agent_detail(
                    novel_id,
                    "EditorAgent",
                    f"节拍 {beat_index + 1} 润色越界后受限重试通过",
                    node="editor_structure_guard_retry",
                    task="polish",
                    status="succeeded",
                    metadata={
                        "beat_index": beat_index,
                        "source_chars": len(source_text),
                        "retry_chars": len(retry_text),
                        "original_guard_issues": evidence.get("issues") or [],
                    },
                )
                return retry_text
            retry_evidence = retry_result.evidence(beat_index=beat_index, mode="editor_retry")
            retry_evidence["source_chars"] = len(source_text)
            retry_evidence["polished_chars"] = len(retry_text)
            checkpoint.setdefault("editor_guard_warnings", []).append(retry_evidence)
            log_agent_detail(
                novel_id,
                "EditorAgent",
                f"节拍 {beat_index + 1} 润色受限重试仍越界，回退原文",
                node="editor_structure_guard_retry",
                task="polish",
                status="failed",
                level="warning",
                metadata=retry_evidence,
            )
        return source_text

    async def _retry_rewrite_beat_after_guard(
        self,
        *,
        source_text: str,
        scores: dict,
        guard_evidence: dict,
        whole_chapter_issues: list,
        chapter_context: dict,
    ) -> str:
        issues = guard_evidence.get("issues") or []
        focus = guard_evidence.get("suggested_rewrite_focus") or "回到原文和章节计划已有事实，保留表达优化。"
        guard_issue = {
            "dim": "consistency",
            "problem": "上一版润色引入了计划外事实或改变了节拍边界：" + "；".join(str(item) for item in issues[:4]),
            "suggestion": f"{focus}；正文只使用原文、章节计划和已给事实，保留句子顺滑、动作清晰和情绪层次。",
        }
        return await self._rewrite_beat(
            source_text,
            scores,
            [guard_issue],
            whole_chapter_issues,
            chapter_context,
        )

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
            "你是一位小说编辑。请在保留叙事事实和原对话意图的前提下,针对以下问题定点改写本段。"
            "只返回改写后的正文,不要添加任何解释、标签或编号。\n",
            "## 改写方向\n"
            "1. 增强读感:让句子更顺,让动作、对话和物件承担信息,让读者能自然跟住情绪和因果。\n"
            "2. 自然中文表达:英文、拼音、网络缩写和 UI 术语原文转写为贴合角色处境的中文说法。\n"
            "3. 情绪呈现:把直述心理改成动作、对话潜台词、身体反应或环境反衬,让读者自己感到人物变化。\n"
            "4. 低 AI 味修整:处理比喻过密、抽象玄幻词连环复读、感官平均用力、奇观堆叠、模板化入体/传承演出。\n"
            "5. 异象/奇遇段落:保留最有辨识度的画面,把抽象光影落到身体反应、行动阻碍或具体后果。\n"
            "6. 现代吐槽:只有风格约束明确允许时才放大;通常改成短促、贴处境的内心念头。\n"
            "7. 字数节奏:保持与原段相近的字数(±20%),优先补顺断句、压缩重复解释、保留有效冲突。\n",
            "## 事实边界\n"
            "1. 使用计划和原段已经给出的事实强化表达,保留事件先后顺序和人物已完成动作。\n"
            "2. 使用已有悬念增强章末钩子:放大当前风险、未完成选择、情绪余波或已埋伏笔。\n"
            "3. 有限留白:当计划内信息不足以制造新反转时,用停顿、视线、动作未完成或既有风险的措辞强化,不发明新事件。\n"
            "4. 正文只升级已有事实:新线索、新证据、新物件、新威胁、新动机和额外台词交给章节计划或后续节拍,"
            "需要新线索时写入后续建议,本段用已给目标、阻力、选择和代价增强读感。\n",
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

    @staticmethod
    def _continuity_rewrite_issues(checkpoint: dict) -> tuple[list[dict], bool]:
        plan = checkpoint.get("continuity_rewrite_plan")
        if not isinstance(plan, dict):
            return [], False
        raw_issues = plan.get("global_issues") or []
        if not isinstance(raw_issues, list):
            raw_issues = []
        issues = []
        for item in raw_issues:
            if not isinstance(item, dict):
                continue
            dim = item.get("dim") or "continuity"
            if dim == "continuity":
                dim = "连续性"
            issues.append({
                "dim": dim,
                "problem": item.get("problem") or "正文与长期设定存在连续性冲突。",
                "suggestion": item.get("suggestion") or "按长期设定重写冲突段落，不新增覆盖旧设定的事实。",
            })
        if not issues and plan.get("summary"):
            issues.append({
                "dim": "continuity",
                "problem": str(plan.get("summary")),
                "suggestion": "按长期设定修复正文中的硬冲突。",
            })
        return issues, bool(plan.get("rewrite_all") and issues)
