"""Post-write beat coverage validator with LLM-as-judge and deterministic fallback."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

from novel_dev.agents._llm_helpers import call_and_parse
from novel_dev.llm import llm_factory
from novel_dev.schemas.quality import BeatBoundaryCard

logger = logging.getLogger(__name__)


@dataclass
class BeatCoverageResult:
    beat_index: int
    covered: bool
    deviation: str | None
    severity: Literal["ok", "warn", "block"]

    def to_issue_code(self) -> str | None:
        if self.severity == "ok":
            return None
        if self.severity == "block":
            return "BEAT_BOUNDARY_VIOLATION"
        return "EVENT_ORDER_DRIFT"


class BeatCoverageValidator:
    def __init__(self, session, llm_client=None, use_llm: bool = True):
        self.session = session
        self.llm = llm_client
        self.use_llm = use_llm

    async def validate(
        self,
        beat_cards: list[BeatBoundaryCard],
        draft_text: str,
    ) -> list[BeatCoverageResult]:
        if not beat_cards and not self.use_llm:
            return [
                BeatCoverageResult(
                    beat_index=-1,
                    covered=True,
                    deviation="no_cards_no_llm",
                    severity="ok",
                )
            ]
        if self.use_llm:
            try:
                return await self._llm_judge(beat_cards, draft_text)
            except Exception as exc:
                logger.warning(
                    "Beat coverage LLM judge failed, falling back",
                    extra={"fallback": "deterministic", "reason": repr(exc)},
                )
        return self._deterministic_check(beat_cards, draft_text)

    async def _llm_judge(
        self,
        beat_cards: list[BeatBoundaryCard],
        draft_text: str,
    ) -> list[BeatCoverageResult]:
        prompt = self._build_judge_prompt(beat_cards, draft_text)

        def parser(text: str) -> list[BeatCoverageResult]:
            payload = json.loads(text)
            if not isinstance(payload, list):
                raise ValueError("expected JSON array")
            return [
                BeatCoverageResult(
                    beat_index=int(item.get("beat_index", card.beat_index)),
                    covered=bool(item.get("covered", False)),
                    deviation=item.get("deviation") or None,
                    severity=item.get("severity", "warn"),
                )
                for item, card in zip(payload, beat_cards)
            ]

        client = self.llm or llm_factory.get("BeatCoverageValidator", task="beat_coverage_check")
        results = await call_and_parse(
            agent_name="BeatCoverageValidator",
            task="beat_coverage_check",
            prompt=prompt,
            parser=parser,
            max_retries=2,
            client=client,
        )
        return results

    def _build_judge_prompt(
        self,
        beat_cards: list[BeatBoundaryCard],
        draft_text: str,
    ) -> str:
        cards_json = "[\n" + ",\n".join(
            json.dumps({
                "beat_index": card.beat_index,
                "must_cover": card.must_cover or [],
                "forbidden_materials": card.forbidden_materials or [],
            }, ensure_ascii=False)
            for card in beat_cards
        ) + "\n]"
        return (
            "你是一位小说节拍覆盖检查员。下面给出每拍的 'must_cover'（必须覆盖）和 "
            "'forbidden_materials'（严格禁止）。请对照整章正文，逐拍判断：\n"
            "1. covered: 该拍 must_cover 是否基本被覆盖（≥60% 关键词出现或语义等价）。\n"
            "2. deviation: 未覆盖时简要说明偏差。\n"
            "3. severity: ok / warn / block。forbidden 命中必须 block；must_cover 大面积缺失 block；小面积缺失 warn。\n\n"
            f"### 节拍卡\n{cards_json}\n\n"
            f"### 正文\n{draft_text}\n\n"
            "只返回 JSON 数组，每个元素为 {beat_index, covered, deviation, severity}。不要 markdown 代码块。"
        )

    def _deterministic_check(
        self,
        beat_cards: list[BeatBoundaryCard],
        draft_text: str,
    ) -> list[BeatCoverageResult]:
        results: list[BeatCoverageResult] = []
        for card in beat_cards:
            must_cover = card.must_cover or []
            forbidden = card.forbidden_materials or []
            matched = sum(1 for term in must_cover if term and term in draft_text)
            has_forbidden = any(term and term in draft_text for term in forbidden)
            if has_forbidden:
                results.append(
                    BeatCoverageResult(
                        beat_index=card.beat_index,
                        covered=False,
                        deviation=f"forbidden material matched: {forbidden}",
                        severity="block",
                    )
                )
                continue
            covered = not must_cover or (matched / len(must_cover) >= 0.6)
            if covered:
                results.append(
                    BeatCoverageResult(
                        beat_index=card.beat_index,
                        covered=True,
                        deviation=None,
                        severity="ok",
                    )
                )
            else:
                results.append(
                    BeatCoverageResult(
                        beat_index=card.beat_index,
                        covered=False,
                        deviation=f"must_cover matched {matched}/{len(must_cover)}",
                        severity="warn",
                    )
                )
        return results
