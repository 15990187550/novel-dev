from __future__ import annotations

import re
from hashlib import sha1
from collections import defaultdict
from typing import ClassVar, Literal

from novel_dev.schemas.quality import QualityIssue, RepairTask


TaskType = Literal[
    "prose_polish",
    "cohesion_repair",
    "hook_repair",
    "character_repair",
    "scene_pressure_repair",
    "integrity_repair",
    "continuity_repair",
]
TaskScope = Literal["chapter", "beat", "paragraph"]


class RepairPlanner:
    """Build deterministic repair tasks from standardized quality issues."""

    PLANNABLE_REPAIRABILITY: ClassVar[set[str]] = {"auto", "guided"}
    ISSUE_TASK_TYPES: ClassVar[dict[str, TaskType]] = {
        "beat_cohesion": "cohesion_repair",
        "plan_boundary_violation": "cohesion_repair",
        "text_integrity": "integrity_repair",
        "ai_flavor": "prose_polish",
        "language_style": "prose_polish",
        "word_count_drift": "prose_polish",
        "final_review_score": "prose_polish",
        "critical_dimension_score": "scene_pressure_repair",
        "required_payoff": "hook_repair",
        "hook_strength": "hook_repair",
        "plot_tension": "scene_pressure_repair",
        "humanity": "character_repair",
        "characterization": "character_repair",
        "continuity_audit": "continuity_repair",
        "consistency": "continuity_repair",
        "dead_entity_acted": "continuity_repair",
        "canonical_identity_drift": "continuity_repair",
        "story_contract_terms_missing": "continuity_repair",
    }
    TASK_TYPE_ORDER: ClassVar[dict[TaskType, int]] = {
        "cohesion_repair": 0,
        "integrity_repair": 1,
        "prose_polish": 2,
        "scene_pressure_repair": 3,
        "hook_repair": 4,
        "character_repair": 5,
        "continuity_repair": 6,
    }
    TASK_GUIDANCE: ClassVar[dict[TaskType, tuple[list[str], list[str]]]] = {
        "cohesion_repair": (
            [
                "只修复段落/beat 衔接、转场、重复文本和边界越界问题，不新增重大剧情事实。",
                "不得改变本章既定事件顺序、视角和已确认信息。",
            ],
            [
                "相邻 beat 之间因果承接和转场清晰，读者能理解行动如何推进。",
                "重复或近似重复的 beat 文本已合并、删除或改写为有效推进。",
                "文本回到当前 beat 允许范围内，没有提前泄露或跨越计划边界。",
            ],
        ),
        "integrity_repair": (
            [
                "只修复文本完整性问题，包括断句、重复、残缺标记和明显格式破损。",
                "不得借修复完整性之名扩写新情节或改写人物动机。",
            ],
            [
                "文本连续可读，没有残句、乱码、重复粘贴或未闭合结构。",
                "修复后中文叙述保持原有语义和章节信息不丢失。",
            ],
        ),
        "prose_polish": (
            [
                "保留原有剧情事实、人物选择和信息揭示顺序，只调整表达质量。",
                "不得引入新的设定、角色关系或尚未出现的线索。",
            ],
            [
                "语言更自然具体，减少 AI 腔、模板句和空泛评价。",
                "字数、节奏和文风回到本章目标要求，中文表达顺畅。",
            ],
        ),
        "hook_repair": (
            [
                "只强化钩子、悬念或必要回收，不改变既定主线结论。",
                "不得提前完全揭示后续章节的关键答案。",
            ],
            [
                "章节结尾或关键节点形成明确阅读牵引。",
                "应回收的伏笔得到可见处理，未回收项有清晰延后理由。",
            ],
        ),
        "character_repair": (
            [
                "围绕既有人物设定修复行为、语气和动机，不重写人物核心性格。",
                "不得让角色做出缺乏铺垫的重大立场反转。",
            ],
            [
                "人物语言、行动和内心反应与既有画像一致。",
                "关键选择具备可追踪动机，读者能理解角色为什么这样做。",
            ],
        ),
        "scene_pressure_repair": (
            [
                "围绕当前场景已有冲突、阻碍、代价和人物关系修复张力，不另起一条新危机。",
                "不得新增计划外敌人、道具、线索、场所或外部事件来制造压力。",
            ],
            [
                "读者能在当前行动中看见阻力、代价或关系压力，而不是只读到作者概括。",
                "场景推进保留原有事实顺序，但压力感和下一步选择更清楚。",
            ],
        ),
        "continuity_repair": (
            [
                "以已归档世界状态、时间线和前文事实为准修复冲突。",
                "不得为了局部顺畅覆盖或否定已生效的连续性事实。",
            ],
            [
                "时间、地点、人物状态和道具状态与前后文一致。",
                "所有被指出的连续性冲突都有明确修正，不产生新的矛盾。",
            ],
        ),
    }

    @classmethod
    def plan(cls, chapter_id: str, issues: list[QualityIssue]) -> list[RepairTask]:
        grouped: dict[tuple[TaskType, TaskScope, int | None], list[QualityIssue]] = defaultdict(list)
        for issue in issues:
            if issue.repairability not in cls.PLANNABLE_REPAIRABILITY:
                continue
            task_type = cls._task_type_for_issue(issue)
            if task_type is None:
                continue
            task_scope = cls._task_scope(issue.scope)
            grouped[(task_type, task_scope, issue.beat_index)].append(issue)

        tasks: list[RepairTask] = []
        for task_type, scope, beat_index in sorted(grouped, key=cls._group_sort_key):
            group_issues = grouped[(task_type, scope, beat_index)]
            issue_codes = sorted({issue.code for issue in group_issues})
            constraints, success_criteria = cls._task_guidance(task_type, group_issues)
            tasks.append(
                RepairTask(
                    task_id=cls._task_id(chapter_id, task_type, scope, beat_index, issue_codes),
                    chapter_id=chapter_id,
                    issue_codes=issue_codes,
                    task_type=task_type,
                    scope=scope,
                    beat_index=beat_index,
                    problem=cls._task_problem(group_issues),
                    evidence=cls._task_evidence(group_issues),
                    suggestion=cls._task_suggestion(group_issues),
                    constraints=list(constraints),
                    success_criteria=list(success_criteria),
                )
            )
        return tasks

    @classmethod
    def _task_type_for_issue(cls, issue: QualityIssue) -> TaskType | None:
        if issue.code == "critical_dimension_score":
            dimension = cls._dimension_from_issue(issue)
            if dimension == "hook_strength":
                return "hook_repair"
            if dimension == "humanity":
                return "character_repair"
            if dimension == "plot_tension":
                return "scene_pressure_repair"
        return cls.ISSUE_TASK_TYPES.get(issue.code)

    @staticmethod
    def _dimension_from_issue(issue: QualityIssue) -> str:
        haystack = "\n".join([*issue.evidence, issue.suggestion])
        for marker in ("hook_strength", "humanity", "plot_tension"):
            if marker in haystack:
                return marker
        return ""

    @classmethod
    def _task_guidance(
        cls,
        task_type: TaskType,
        issues: list[QualityIssue],
    ) -> tuple[list[str], list[str]]:
        base_constraints, base_success_criteria = cls.TASK_GUIDANCE[task_type]
        constraints = list(base_constraints)
        success_criteria = list(base_success_criteria)
        evidence = cls._task_evidence(issues)
        if evidence:
            constraints.append("修复依据: " + "；".join(evidence[:6]))
        suggestions = [issue.suggestion.strip() for issue in issues if issue.suggestion.strip()]
        if suggestions:
            success_criteria.append("评审建议: " + "；".join(dict.fromkeys(suggestions)))
        return constraints, success_criteria

    @staticmethod
    def _task_problem(issues: list[QualityIssue]) -> str:
        for issue in issues:
            for evidence in issue.evidence:
                cleaned = evidence.strip()
                if cleaned:
                    return cleaned
        return ""

    @staticmethod
    def _task_evidence(issues: list[QualityIssue]) -> list[str]:
        seen = set()
        result = []
        for issue in issues:
            for evidence in issue.evidence:
                cleaned = evidence.strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    result.append(cleaned)
        return result[:6]

    @staticmethod
    def _task_suggestion(issues: list[QualityIssue]) -> str:
        suggestions = []
        for issue in issues:
            cleaned = issue.suggestion.strip()
            if cleaned and cleaned not in suggestions:
                suggestions.append(cleaned)
        return "；".join(suggestions)

    @staticmethod
    def _task_scope(scope: str) -> TaskScope:
        if scope in {"chapter", "beat", "paragraph"}:
            return scope
        return "chapter"

    @classmethod
    def _group_sort_key(cls, group: tuple[TaskType, TaskScope, int | None]) -> tuple[int, str, int, str]:
        task_type, scope, beat_index = group
        beat_sort = beat_index if beat_index is not None else -1
        return (cls.TASK_TYPE_ORDER[task_type], scope, beat_sort, task_type)

    @classmethod
    def _task_id(
        cls,
        chapter_id: str,
        task_type: TaskType,
        scope: TaskScope,
        beat_index: int | None,
        issue_codes: list[str],
    ) -> str:
        chapter_slug = cls._slug(chapter_id)
        beat_slug = f"beat-{beat_index}" if beat_index is not None else "all"
        code_slug = "-".join(issue_codes)
        return f"repair-{chapter_slug}-{task_type}-{scope}-{beat_slug}-{code_slug}"

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        digest = sha1(value.encode("utf-8")).hexdigest()[:8]
        return f"{slug or 'chapter'}-{digest}"
