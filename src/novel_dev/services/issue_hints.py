# src/novel_dev/services/issue_hints.py
"""Map aggregated issue codes to actionable root-cause hints.

In phase 1 the hints are static text from llm_config.yaml. Phase 3 may
replace this with an LLM-driven root-cause analyzer; the interface here
is designed to be drop-in replaceable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from novel_dev.config.quality_config import get_issue_code_hints


@dataclass
class IssueHint:
    code: str
    severity: str
    threshold: int
    hint: str
    occurrences: int
    matches: bool


class IssueHintsService:
    def __init__(self, hints_config: Optional[dict] = None):
        self.hints = hints_config if hints_config is not None else get_issue_code_hints()

    def matched_hints(self, code_counts: Iterable[tuple[str, int]]) -> list[IssueHint]:
        out: list[IssueHint] = []
        for code, count in code_counts:
            cfg = self.hints.get(code)
            if not cfg:
                out.append(IssueHint(
                    code=code, severity="unknown", threshold=0,
                    hint="", occurrences=count, matches=False,
                ))
                continue
            threshold = int(cfg.get("threshold", 1))
            out.append(IssueHint(
                code=code,
                severity=cfg.get("severity", "warn"),
                threshold=threshold,
                hint=cfg.get("hint", ""),
                occurrences=count,
                matches=count >= threshold,
            ))
        return out
