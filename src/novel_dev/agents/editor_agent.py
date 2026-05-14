import hashlib
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
        checkpoint.pop("editor_guard_warnings", None)
        checkpoint.pop("editor_guard_resolved", None)
        checkpoint.pop("chapter_structure_guard", None)
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
        repair_tasks = checkpoint.get("repair_tasks") or []
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
        self._merge_final_polish_issues(checkpoint, issues_by_beat, whole_chapter_issues)
        continuity_issues, force_continuity_rewrite = self._continuity_rewrite_issues(checkpoint)
        whole_chapter_issues.extend(continuity_issues)

        last_idx = len(beats) - 1
        polished_beats = []
        repair_task_outcomes: dict[tuple, dict[str, int]] = {}
        flow_control = FlowControlService(self.session)
        for idx, beat_text in enumerate(beats):
            await flow_control.raise_if_cancelled(novel_id)
            score_entry = beat_scores[idx] if idx < len(beat_scores) else {}
            scores = score_entry.get("scores", {})
            beat_level_issues = score_entry.get("issues", []) or []
            chapter_issues = issues_by_beat.get(idx, [])
            beat_repair_tasks = self._repair_tasks_for_beat(repair_tasks, idx)
            self._record_repair_tasks_selected(repair_task_outcomes, beat_repair_tasks)
            all_issues = (
                chapter_issues
                + beat_level_issues
                + [self._repair_task_to_issue(task) for task in beat_repair_tasks]
            )

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
                polished = self._clean_text_integrity_fragments(polished)
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
            polished = self._clean_text_integrity_fragments(polished)
            if beat_repair_tasks and polished != beat_text:
                completed = True
                self._record_repair_tasks_changed(repair_task_outcomes, beat_repair_tasks)
                checkpoint.setdefault("repair_history", []).append(
                    self._build_repair_history_entry(
                        idx,
                        beat_repair_tasks,
                        beat_text,
                        polished,
                        completed=completed,
                        attempt=checkpoint.get("edit_attempt_count"),
                    )
                )
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
        checkpoint.pop("final_polish_issues", None)
        checkpoint["repair_tasks"] = self._unfinished_repair_tasks(repair_tasks, repair_task_outcomes)

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
        checkpoint.pop("editor_guard_warnings", None)
        checkpoint.pop("editor_guard_resolved", None)
        checkpoint.pop("chapter_structure_guard", None)
        ch = await self.chapter_repo.get_by_id(chapter_id)
        if not ch:
            raise ValueError(f"Chapter not found: {chapter_id}")

        beat_scores = checkpoint.get("beat_scores", [])
        per_dim_issues = checkpoint.get("per_dim_issues", [])
        critique = checkpoint.get("critique_feedback", {}) or {}
        chapter_context = checkpoint.get("chapter_context", {})
        repair_tasks = checkpoint.get("repair_tasks") or []
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
        self._merge_final_polish_issues(checkpoint, issues_by_beat, whole_chapter_issues)
        continuity_issues, force_continuity_rewrite = self._continuity_rewrite_issues(checkpoint)
        whole_chapter_issues.extend(continuity_issues)

        last_idx = len(beats) - 1
        polished_beats = []
        repair_task_outcomes: dict[tuple, dict[str, int]] = {}
        flow_control = FlowControlService(self.session)
        for idx, beat_text in enumerate(beats):
            await flow_control.raise_if_cancelled(novel_id)
            score_entry = beat_scores[idx] if idx < len(beat_scores) else {}
            scores = score_entry.get("scores", {})
            beat_level_issues = score_entry.get("issues", []) or []
            chapter_issues = issues_by_beat.get(idx, [])
            beat_repair_tasks = self._repair_tasks_for_beat(repair_tasks, idx)
            self._record_repair_tasks_selected(repair_task_outcomes, beat_repair_tasks)
            all_issues = (
                chapter_issues
                + beat_level_issues
                + [self._repair_task_to_issue(task) for task in beat_repair_tasks]
            )
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
                polished = self._clean_text_integrity_fragments(polished)
            else:
                polished = beat_text
            polished = self._clean_text_integrity_fragments(polished)
            if beat_repair_tasks and polished != beat_text:
                completed = True
                self._record_repair_tasks_changed(repair_task_outcomes, beat_repair_tasks)
                checkpoint.setdefault("repair_history", []).append(
                    self._build_repair_history_entry(
                        idx,
                        beat_repair_tasks,
                        beat_text,
                        polished,
                        completed=completed,
                        attempt=checkpoint.get("edit_attempt_count"),
                    )
                )
            polished_beats.append(polished)
            await flow_control.raise_if_cancelled(novel_id)

        polished_text = "\n\n".join(polished_beats)
        await self.chapter_repo.update_text(chapter_id, polished_text=polished_text)
        if self.embedding_service:
            try:
                await self.embedding_service.index_chapter(chapter_id)
            except Exception as exc:
                log_service.add_log(novel_id, "EditorAgent", f"独立精修章节索引失败: {exc}", level="warning")
        await self.chapter_repo.update_status(chapter_id, "edited")
        checkpoint.pop("final_polish_issues", None)
        checkpoint["repair_tasks"] = self._unfinished_repair_tasks(repair_tasks, repair_task_outcomes)
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
                checkpoint.setdefault("editor_guard_resolved", []).append(evidence)
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
            checkpoint.setdefault("editor_guard_warnings", []).append(evidence)
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
        checkpoint.setdefault("editor_guard_warnings", []).append(evidence)
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
            "suggestion": f"{focus}；回到当前节拍已有事实，用动作、停顿、视线或身体反应增强读感。",
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
            issue_lines.append(self._format_issue_for_prompt(it))
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
            "只返回改写后的正文，以正文形式呈现。\n",
            "## 改写方向\n"
            "1. 局部修补模式:优先修改与问题直接相关的句群,保持原事件集合、人物集合、地点集合和信息释放顺序。\n"
            "2. 读感推进:让当场目标、可见阻力、角色策略/态度变化和具体停点更清楚。\n"
            "3. 对话层次:关键信息通过试探、保留、误判或代价逐步浮出,让角色关系在说话方式里变化。\n"
            "4. 章末牵引:使用已有物件、风险、情绪余波和已埋伏笔强化停点,让读者感到当场后果和下一步疑问。\n"
            "   写法顺序为:先点住本段已经出现的具体物/伤/话/选择,再写人物必须承受的代价或迟疑,最后落在一个未完成动作或已知风险的逼近感。\n"
            "5. 自然中文表达:英文、拼音、网络缩写和 UI 术语原文转写为贴合角色处境的中文说法。\n"
            "6. 情绪呈现:把直述心理改成动作、对话潜台词、身体反应或环境反衬,让读者自己感到人物变化。\n"
            "7. 低 AI 味修整:处理比喻过密、抽象玄幻词连环复读、感官平均用力、奇观堆叠、模板化入体/传承演出。\n"
            "8. 异象/奇遇段落:保留最有辨识度的画面,把抽象光影落到身体反应、行动阻碍或具体后果。\n"
            "9. 现代吐槽:只有风格约束明确允许时才放大;通常改成短促、贴处境的内心念头。\n"
            "10. 字数节奏:保持与原段相近的字数(±20%),优先补顺断句、压缩重复解释、保留有效冲突。\n",
            "## 事实边界\n"
            "1. 使用计划和原段已经给出的事实强化表达,保留事件先后顺序和人物已完成动作。\n"
            "2. 使用已有悬念增强章末钩子:放大当前风险、未完成选择、情绪余波或已埋伏笔。\n"
            "3. 有限留白:当计划内信息不足以制造新反转时,用停顿、视线、动作未完成或既有风险的措辞强化。\n"
            "4. 正文只升级已有事实:新线索、新证据、新物件、新威胁、新动机、黑影、追兵、身份背景、额外线索和额外台词"
            "交给章节计划或后续节拍;本段用已给目标、阻力、选择和代价增强读感。\n",
            "5. 若问题建议里出现新增反转、陌生人物、额外物件或后续危险示例,请只吸收其读感目标,并改用原文/计划已经出现的素材完成同等效果。\n",
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

    @classmethod
    def _format_issue_for_prompt(cls, issue: dict) -> str:
        dim = issue.get("dim")
        problem = issue.get("problem")
        suggestion = cls._bounded_suggestion_for_issue(issue)
        return f"- [{dim}] 问题: {problem}\n  建议: {suggestion}"

    @staticmethod
    def _repair_tasks_for_beat(tasks: list[dict], beat_index: int) -> list[dict]:
        if not isinstance(tasks, list):
            return []
        selected = []
        for task in tasks:
            if not EditorAgent._is_valid_repair_task(task):
                continue
            task_beat_index = task.get("beat_index")
            if task_beat_index is None or task_beat_index == beat_index:
                selected.append(task)
        return selected

    @staticmethod
    def _is_valid_repair_task(task) -> bool:
        if not isinstance(task, dict):
            return False
        task_type = str(task.get("task_type") or "").strip()
        issue_codes = EditorAgent._repair_task_issue_codes(task)
        return bool(task_type and issue_codes)

    @staticmethod
    def _repair_task_issue_codes(task: dict) -> list[str]:
        raw_codes = task.get("issue_codes")
        if isinstance(raw_codes, list):
            return [str(code).strip() for code in raw_codes if str(code).strip()]
        if raw_codes is None:
            return []
        code = str(raw_codes).strip()
        return [code] if code else []

    @staticmethod
    def _repair_task_key(task: dict) -> tuple:
        task_id = task.get("task_id")
        if task_id:
            return ("task_id", str(task_id))
        return (
            "task",
            str(task.get("task_type") or ""),
            task.get("beat_index"),
            tuple(EditorAgent._repair_task_issue_codes(task)),
            str(task.get("scope") or ""),
            str(task.get("chapter_id") or ""),
            tuple(EditorAgent._normalized_repair_field_items(task.get("constraints"))),
            tuple(EditorAgent._normalized_repair_field_items(task.get("success_criteria"))),
        )

    @staticmethod
    def _normalized_repair_field_items(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        return [text] if text else []

    @classmethod
    def _record_repair_tasks_selected(cls, outcomes: dict, tasks: list[dict]) -> None:
        for task in tasks:
            key = cls._repair_task_key(task)
            entry = outcomes.setdefault(key, {"selected": 0, "changed": 0})
            entry["selected"] += 1

    @classmethod
    def _record_repair_tasks_changed(cls, outcomes: dict, tasks: list[dict]) -> None:
        for task in tasks:
            key = cls._repair_task_key(task)
            entry = outcomes.setdefault(key, {"selected": 0, "changed": 0})
            entry["changed"] += 1

    @classmethod
    def _unfinished_repair_tasks(cls, tasks: list[dict], outcomes: dict) -> list:
        if not isinstance(tasks, list):
            return []
        unfinished = []
        for task in tasks:
            if not cls._is_valid_repair_task(task):
                continue
            outcome = outcomes.get(cls._repair_task_key(task))
            if not outcome or outcome["selected"] == 0 or outcome["changed"] < outcome["selected"]:
                unfinished.append(task)
        return unfinished

    @staticmethod
    def _build_repair_task_prompt(source_text: str, task: dict, chapter_context: dict) -> str:
        import json

        task_type = task.get("task_type") or "repair_task"
        issue_codes = EditorAgent._stringify_repair_field(task.get("issue_codes"))
        constraints = EditorAgent._stringify_repair_field(task.get("constraints"))
        success_criteria = EditorAgent._stringify_repair_field(task.get("success_criteria"))

        chapter_plan = {}
        if isinstance(chapter_context, dict):
            chapter_plan = chapter_context.get("chapter_plan") or {}
        title = chapter_plan.get("title") if isinstance(chapter_plan, dict) else None
        plan_text = json.dumps(chapter_plan, ensure_ascii=False, indent=2) if chapter_plan else ""

        return "\n".join([
            "你是一位小说编辑，请根据质量修复任务改写原文。",
            f"任务类型: {task_type}",
            f"问题码: {issue_codes or '无'}",
            f"约束: {constraints or '无'}",
            f"成功标准: {success_criteria or '无'}",
            f"章节标题: {title or '未提供'}",
            f"章节计划: {plan_text or '未提供'}",
            "硬性约束: 严禁新增章节计划外的人物、物件、线索、威胁、地点或事件；只能用原文和章节计划已经给出的事实完成修复。",
            f"原文:\n{source_text}",
            "改写:",
        ])

    @staticmethod
    def _stringify_repair_field(value) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return "；".join(str(item) for item in value)
        return str(value)

    @classmethod
    def _repair_task_to_issue(cls, task: dict) -> dict:
        task_type = task.get("task_type") or "repair_task"
        issue_codes = cls._stringify_repair_field(task.get("issue_codes"))
        constraints = cls._stringify_repair_field(task.get("constraints"))
        success_criteria = cls._stringify_repair_field(task.get("success_criteria"))
        schema_fields = []
        for field in ("task_id", "chapter_id", "scope", "allowed_materials"):
            value = cls._stringify_repair_field(task.get(field))
            if value:
                schema_fields.append(f"{field}：{value}")
        description = (
            task.get("problem")
            or task.get("description")
            or task.get("summary")
            or task_type
        )
        problem_parts = [str(description)]
        if issue_codes:
            problem_parts.append(f"问题码：{issue_codes}")
        if constraints:
            problem_parts.append(f"约束：{constraints}")
        if schema_fields:
            problem_parts.extend(schema_fields)
        return {
            "dim": task_type,
            "problem": "质量修复任务：" + "；".join(problem_parts),
            "suggestion": success_criteria or "按质量修复任务完成定点修复。",
        }

    @classmethod
    def _build_repair_history_entry(
        cls,
        beat_index: int,
        tasks: list[dict],
        source_text: str,
        polished_text: str,
        *,
        completed: bool,
        attempt: int | None = None,
    ) -> dict:
        task_types = [str(task.get("task_type") or "repair_task") for task in tasks]
        issue_codes = []
        task_ids = []
        task_keys = []
        for task in tasks:
            issue_codes.extend(cls._repair_task_issue_codes(task))
            if task.get("task_id"):
                task_ids.append(str(task.get("task_id")))
            task_keys.append(repr(cls._repair_task_key(task)))
        return {
            "beat_index": beat_index,
            "task_types": task_types,
            "issue_codes": issue_codes,
            "task_ids": task_ids,
            "task_keys": task_keys,
            "completed": completed,
            "status": "completed" if completed else "attempted",
            "attempt": attempt,
            "source_preview": preview_text(source_text, 120),
            "polished_preview": preview_text(polished_text, 120),
            "source_hash": cls._short_text_hash(source_text),
            "polished_hash": cls._short_text_hash(polished_text),
            "source_chars": len(source_text),
            "polished_chars": len(polished_text),
        }

    @staticmethod
    def _short_text_hash(text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _bounded_suggestion_for_issue(issue: dict) -> str:
        suggestion = str(issue.get("suggestion") or "").strip()
        dim = str(issue.get("dim") or "")
        risky_markers = (
            "新反转", "新的反转", "加入新", "新增", "黑影", "追兵", "有人正朝",
            "密信被", "信纸在融化", "禁地深处亮起", "额外", "陌生人", "新人物",
            "新线索", "新证据", "新物件", "新威胁", "例如：", "比如：",
        )
        if dim == "hook_strength" or any(marker in suggestion for marker in risky_markers):
            base = suggestion
            if base:
                base += "。"
            return (
                f"{base}执行时只使用原文和章节计划已出现的物件、伤势、选择、风险或伏笔; "
                "通过当场后果、人物迟疑、身体反应、未完成动作和已知风险逼近来强化钩子。"
            )
        if dim in {"editing_boundary", "consistency", "quality_gate", "required_payoff"}:
            base = suggestion or "回到当前节拍已有事实完成修补。"
            return (
                f"{base} 改动范围收束在表达、节奏和读者感知,事件、人物、物件、线索和台词沿用已有材料。"
            )
        return suggestion

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
                "suggestion": item.get("suggestion") or "按长期设定重写冲突段落，沿用已有事实并恢复设定一致性。",
            })
        if not issues and plan.get("summary"):
            issues.append({
                "dim": "continuity",
                "problem": str(plan.get("summary")),
                "suggestion": "按长期设定修复正文中的硬冲突。",
            })
        return issues, bool(plan.get("rewrite_all") and issues)

    @staticmethod
    def _merge_final_polish_issues(
        checkpoint: dict,
        issues_by_beat: dict[int, list],
        whole_chapter_issues: list,
    ) -> None:
        plan = checkpoint.get("final_polish_issues")
        if not isinstance(plan, dict):
            return
        for item in plan.get("beat_issues") or []:
            if not isinstance(item, dict):
                continue
            beat_idx = item.get("beat_index")
            if not isinstance(beat_idx, int):
                continue
            issues = [issue for issue in item.get("issues") or [] if isinstance(issue, dict)]
            if issues:
                issues_by_beat.setdefault(beat_idx, []).extend(issues)
        for issue in plan.get("global_issues") or []:
            if isinstance(issue, dict):
                whole_chapter_issues.append(issue)
        for blocking in plan.get("quality_gate_blocking_items") or []:
            if not isinstance(blocking, dict):
                continue
            detail = blocking.get("detail")
            detail_lines = detail if isinstance(detail, list) else []
            suggestion = "删去重复承接、补齐节拍转场，并用当前节拍已有事实补足动作因果。"
            if blocking.get("code") == "text_integrity":
                suggestion = "修复残句、孤立标点或截断段落，保持完整句读和动作承接。"
            if detail_lines:
                suggestion = "；".join(str(item) for item in detail_lines[:3])
            whole_chapter_issues.append({
                "dim": blocking.get("code") or "quality_gate",
                "problem": blocking.get("message") or "成稿质量门禁触发阻断项。",
                "suggestion": suggestion,
            })
        for warning in plan.get("quality_gate_warnings") or []:
            if not isinstance(warning, dict):
                continue
            detail = warning.get("detail") if isinstance(warning.get("detail"), dict) else {}
            missing = detail.get("missing") if isinstance(detail.get("missing"), list) else []
            whole_chapter_issues.append({
                "dim": warning.get("code") or "quality_gate",
                "problem": warning.get("message") or "成稿质量门禁仍有告警。",
                "suggestion": "围绕当前节拍已有事实补足读者需要看见的兑现、余波和停点。"
                + (f" 重点兑现: {'；'.join(str(item) for item in missing[:3])}" if missing else ""),
            })

    @staticmethod
    def _clean_isolated_punctuation_paragraphs(text: str) -> str:
        paragraphs = text.split("\n\n")
        cleaned = [
            paragraph
            for paragraph in paragraphs
            if not re.fullmatch(r"\s*[。！？!?.,，、；;：:]+\s*", paragraph)
        ]
        return "\n\n".join(cleaned).strip()

    @classmethod
    def _clean_text_integrity_fragments(cls, text: str) -> str:
        cleaned = cls._clean_isolated_punctuation_paragraphs(text)
        paragraphs = [
            cls._repair_truncated_paragraph(paragraph)
            for paragraph in cleaned.split("\n\n")
        ]
        return "\n\n".join(paragraphs).strip()

    @staticmethod
    def _repair_truncated_paragraph(paragraph: str) -> str:
        stripped = paragraph.strip()
        replacements = (
            (r"，照[。.!]$", "，照出一片昏黄。"),
            (r"，还是[。.!]$", "，还是保全自身。"),
            (r"站不[。.!]$", "站不起来。"),
        )
        for pattern, replacement in replacements:
            if re.search(pattern, stripped):
                return re.sub(pattern, replacement, paragraph.rstrip()).strip()
        return paragraph
