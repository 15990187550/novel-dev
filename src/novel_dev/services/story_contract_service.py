from __future__ import annotations

import re
from typing import Any


class StoryContractService:
    """Build lightweight cross-stage story contracts from existing checkpoints."""

    SALIENT_TERMS = (
        "父亲",
        "母亲",
        "兄长",
        "妹妹",
        "遗物",
        "信物",
        "线索",
        "真相",
        "证据",
        "旧案",
        "秘密",
        "承诺",
        "目标",
    )

    @classmethod
    def build_from_snapshot(cls, snapshot: dict[str, Any]) -> dict[str, Any]:
        checkpoint = cls._checkpoint(snapshot)
        synopsis = checkpoint.get("synopsis_data") if isinstance(checkpoint.get("synopsis_data"), dict) else {}
        changes = cls._setting_changes(snapshot)

        first_chapter_goal = cls._first_chapter_goal(changes)
        protagonist_goal = cls._protagonist_goal(changes, synopsis)
        current_stage_goal = cls._current_stage_goal(synopsis, checkpoint)
        core_conflict = cls._coerce_text(
            synopsis.get("core_conflict")
            or cls._setting_card_content(changes, doc_type="core_conflict")
            or cls._setting_card_content(changes, doc_type="plot")
        )
        key_clues = sorted(cls._salient_terms(" ".join([first_chapter_goal, current_stage_goal, core_conflict])))

        return {
            "protagonist_goal": protagonist_goal,
            "current_stage_goal": current_stage_goal,
            "first_chapter_goal": first_chapter_goal,
            "core_conflict": core_conflict,
            "key_clues": key_clues,
            "antagonistic_pressure": cls._antagonistic_pressure(core_conflict, changes),
            "must_carry_forward": key_clues[:8],
            "source_status": cls._source_status(snapshot),
        }

    @classmethod
    def evaluate_cross_stage_quality(
        cls,
        snapshot: dict[str, Any],
        contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        checkpoint = cls._checkpoint(snapshot)
        contract = contract or cls.build_from_snapshot(snapshot)
        warnings: list[dict[str, Any]] = []

        first_goal = cls._coerce_text(contract.get("first_chapter_goal"))
        first_volume_summary = cls._first_volume_chapter_summary(checkpoint)
        if first_goal and first_volume_summary:
            setting_terms = cls._salient_terms(first_goal)
            volume_terms = cls._salient_terms(first_volume_summary)
            shared = setting_terms & volume_terms
            if setting_terms and volume_terms and not shared:
                warnings.append({
                    "code": "first_chapter_goal_drift",
                    "source_stage": "volume_plan",
                    "message": "第一章设定启动事件与卷纲首章摘要承接较弱。",
                    "evidence": f"setting_terms={sorted(setting_terms)}; volume_terms={sorted(volume_terms)}",
                    "recommendation": "让卷纲首章摘要继承设定中的启动物件、地点或主角目标。",
                })

        for warning in checkpoint.get("editor_guard_warnings") or []:
            if not isinstance(warning, dict):
                continue
            if warning.get("introduced_plan_external_fact") or warning.get("issues"):
                evidence = "; ".join(cls._coerce_text(item) for item in warning.get("issues") or [])
                warnings.append({
                    "code": "editor_plan_external_fact",
                    "source_stage": "editing",
                    "message": "编辑阶段出现计划外新增事实风险。",
                    "evidence": evidence or cls._coerce_text(warning),
                    "recommendation": cls._coerce_text(warning.get("suggested_rewrite_focus"))
                    or "把新增线索沉淀为后续计划建议，正文回到已给事实。",
                })

        blocking_issues = [
            item for item in warnings
            if item.get("severity") in {"high", "critical"} or item.get("blocking") is True
        ]
        return {
            "passed": not blocking_issues,
            "warnings": warnings,
            "blocking_issues": blocking_issues,
            "contract_fields_present": sorted(
                key for key, value in (contract or {}).items()
                if key != "source_status" and value not in (None, "", [], {})
            ),
        }

    @classmethod
    def _checkpoint(cls, snapshot: dict[str, Any]) -> dict[str, Any]:
        checkpoint = snapshot.get("checkpoint") or snapshot.get("checkpoint_data") or {}
        return checkpoint if isinstance(checkpoint, dict) else {}

    @classmethod
    def _setting_changes(cls, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        direct = snapshot.get("setting_review_changes")
        if isinstance(direct, list):
            return [item for item in direct if isinstance(item, dict)]
        batch = snapshot.get("setting_review_batch") or snapshot.get("setting_batch") or {}
        if isinstance(batch, dict):
            changes = batch.get("changes") or (batch.get("input_snapshot") or {}).get("changes")
            if isinstance(changes, list):
                return [item for item in changes if isinstance(item, dict)]
        return []

    @classmethod
    def _first_chapter_goal(cls, changes: list[dict[str, Any]]) -> str:
        for change in changes:
            after = change.get("after_snapshot") if isinstance(change.get("after_snapshot"), dict) else {}
            text = " ".join(cls._coerce_text(after.get(key)) for key in ("title", "content", "summary"))
            if "第一章" in text or "首章" in text:
                return cls._coerce_text(after.get("content") or after.get("summary") or text)
        return ""

    @classmethod
    def _protagonist_goal(cls, changes: list[dict[str, Any]], synopsis: dict[str, Any]) -> str:
        for change in changes:
            after = change.get("after_snapshot") if isinstance(change.get("after_snapshot"), dict) else {}
            text = cls._coerce_text(after.get("current_state") or after.get("content") or "")
            if after.get("type") == "character" and "目标" in text:
                match = re.search(r"目标是([^。；;\n]+)", text)
                if match:
                    return match.group(1).strip()
                return text[:80]
        for outline in synopsis.get("volume_outlines") or []:
            if isinstance(outline, dict) and outline.get("main_goal"):
                return cls._coerce_text(outline.get("main_goal"))
        return cls._coerce_text(synopsis.get("logline") or synopsis.get("core_conflict"))

    @classmethod
    def _current_stage_goal(cls, synopsis: dict[str, Any], checkpoint: dict[str, Any]) -> str:
        current_volume = checkpoint.get("current_volume_id") or checkpoint.get("current_volume_number") or 1
        for outline in synopsis.get("volume_outlines") or []:
            if not isinstance(outline, dict):
                continue
            if outline.get("volume_number") in (current_volume, 1, "1", None):
                return cls._coerce_text(outline.get("main_goal") or outline.get("summary"))
        return ""

    @classmethod
    def _setting_card_content(cls, changes: list[dict[str, Any]], *, doc_type: str) -> str:
        for change in changes:
            after = change.get("after_snapshot") if isinstance(change.get("after_snapshot"), dict) else {}
            if after.get("doc_type") == doc_type:
                return cls._coerce_text(after.get("content") or after.get("summary"))
        return ""

    @classmethod
    def _first_volume_chapter_summary(cls, checkpoint: dict[str, Any]) -> str:
        plan = checkpoint.get("current_volume_plan") if isinstance(checkpoint.get("current_volume_plan"), dict) else {}
        chapters = plan.get("chapters") or []
        if not chapters:
            return ""
        first = chapters[0]
        if hasattr(first, "model_dump"):
            first = first.model_dump()
        return cls._coerce_text((first or {}).get("summary") if isinstance(first, dict) else first)

    @classmethod
    def _antagonistic_pressure(cls, core_conflict: str, changes: list[dict[str, Any]]) -> str:
        if "vs" in core_conflict:
            return core_conflict.split("vs", 1)[1].strip()
        if "对抗" in core_conflict:
            return core_conflict.split("对抗", 1)[1].strip(" 。")
        for change in changes:
            after = change.get("after_snapshot") if isinstance(change.get("after_snapshot"), dict) else {}
            if after.get("type") == "organization":
                return cls._coerce_text(after.get("name") or after.get("current_state"))
        return ""

    @classmethod
    def _source_status(cls, snapshot: dict[str, Any]) -> dict[str, Any]:
        batch = snapshot.get("setting_review_batch") if isinstance(snapshot.get("setting_review_batch"), dict) else {}
        return {
            "setting_review_batch_status": batch.get("status"),
            "setting_change_count": len(cls._setting_changes(snapshot)),
        }

    @classmethod
    def _salient_terms(cls, text: str) -> set[str]:
        source = cls._coerce_text(text)
        terms = {term for term in cls.SALIENT_TERMS if term in source}
        for token in re.findall(r"[\u4e00-\u9fff]{2,8}", source):
            if token.endswith(("真相", "线索", "证据", "信物", "遗物", "秘密", "目标", "承诺")):
                terms.add(token)
        return terms

    @staticmethod
    def _coerce_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()
