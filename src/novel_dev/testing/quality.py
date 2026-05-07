from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


Severity = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class QualityFinding:
    code: str
    severity: Severity
    message: str


def _has_items(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return len(value) > 0
    return value is not None


def validate_settings(settings: dict[str, Any]) -> list[QualityFinding]:
    checks = [
        ("worldview", "SETTINGS_MISSING_WORLDVIEW", "Settings must include worldview."),
        (
            "characters",
            "SETTINGS_MISSING_CHARACTERS",
            "Settings must include at least one character.",
        ),
        (
            "factions",
            "SETTINGS_MISSING_FACTIONS",
            "Settings must include at least one faction or force.",
        ),
        ("locations", "SETTINGS_MISSING_LOCATIONS", "Settings must include at least one location."),
        (
            "rules",
            "SETTINGS_MISSING_RULES",
            "Settings must include at least one rule or power-system constraint.",
        ),
        (
            "core_conflicts",
            "SETTINGS_MISSING_CORE_CONFLICTS",
            "Settings must include at least one core conflict.",
        ),
    ]
    findings: list[QualityFinding] = []
    for key, code, message in checks:
        if not _has_items(settings.get(key)):
            findings.append(QualityFinding(code=code, severity="high", message=message))
    return findings


def validate_outline(outline: dict[str, Any]) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    required = [
        ("main_line", "OUTLINE_MISSING_MAIN_LINE", "Outline must include a main line."),
        ("conflicts", "OUTLINE_MISSING_CONFLICTS", "Outline must include conflicts."),
        (
            "character_motivations",
            "OUTLINE_MISSING_MOTIVATIONS",
            "Outline must include character motivations.",
        ),
        ("chapters", "OUTLINE_MISSING_CHAPTERS", "Outline must include executable chapters."),
    ]
    for key, code, message in required:
        if not _has_items(outline.get(key)):
            findings.append(QualityFinding(code=code, severity="high", message=message))

    for index, chapter in enumerate(outline.get("chapters") or [], start=1):
        beats = chapter.get("beats") if isinstance(chapter, dict) else None
        if not _has_items(beats):
            findings.append(
                QualityFinding(
                    code="OUTLINE_CHAPTER_MISSING_BEATS",
                    severity="high",
                    message=f"Chapter {index} must include at least one beat.",
                )
            )
    return findings


def validate_chapter(
    text: str,
    required_beats: list[str],
    minimum_chars: int,
) -> list[QualityFinding]:
    compact = "".join(text.split())
    findings: list[QualityFinding] = []
    if len(compact) < minimum_chars:
        findings.append(
            QualityFinding(
                code="CHAPTER_TOO_SHORT",
                severity="high",
                message=(
                    f"Chapter has {len(compact)} non-space characters, "
                    f"below minimum {minimum_chars}."
                ),
            )
        )
    for beat in required_beats:
        if beat and beat not in text:
            findings.append(
                QualityFinding(
                    code="CHAPTER_MISSING_BEAT",
                    severity="high",
                    message=f"Chapter does not cover required beat: {beat}",
                )
            )
    return findings


def validate_cross_stage_consistency(
    allowed_terms: set[str],
    generated_text: str,
    watched_terms: set[str],
) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    for term in sorted(watched_terms):
        if term in generated_text and term not in allowed_terms:
            findings.append(
                QualityFinding(
                    code="CROSS_STAGE_UNDEFINED_TERM",
                    severity="high",
                    message=f"Generated text references undefined term: {term}",
                )
            )
    return findings
