from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from scipy import stats
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import ABTest, ChapterQualityMetric
from novel_dev.repositories.ab_test_repo import ABTestRepository
from novel_dev.repositories.prompt_version_repo import PromptVersionRepository

logger = logging.getLogger(__name__)


@dataclass
class ABTestResult:
    test_id: str
    status: str
    baseline_mean: Optional[float]
    challenger_mean: Optional[float]
    p_value: Optional[float]
    baseline_n: int
    challenger_n: int
    winner: Optional[str]


class ABTestRunner:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ABTestRepository(session)

    async def start(
        self,
        agent_name: str,
        baseline_version: str,
        challenger_version: str,
        max_samples: int = 10,
        min_samples: int = 3,
        alpha: float = 0.05,
        scope_filter: Optional[dict] = None,
    ) -> ABTest:
        running = await self.repo.list_running(agent_name=agent_name)
        if running:
            raise ValueError(
                f"Agent {agent_name} already has a running A/B test ({running[0].id})"
            )
        if baseline_version == challenger_version:
            raise ValueError("Baseline and challenger versions must differ")
        prompt_repo = PromptVersionRepository(self.session)
        baseline = await prompt_repo.get_by_version(agent_name, baseline_version)
        challenger = await prompt_repo.get_by_version(agent_name, challenger_version)
        missing = [
            version
            for version, prompt_version in (
                (baseline_version, baseline),
                (challenger_version, challenger),
            )
            if prompt_version is None
        ]
        if missing:
            raise ValueError(
                f"Prompt version(s) not found for {agent_name}: {', '.join(missing)}"
            )
        ab = await self.repo.create(
            agent_name=agent_name,
            baseline_version=baseline_version,
            challenger_version=challenger_version,
            config={
                "max_samples": max_samples,
                "min_samples": min_samples,
                "alpha": alpha,
                "scope_filter": scope_filter or {},
            },
        )
        baseline.ab_test_id = ab.id
        challenger.ab_test_id = ab.id
        baseline.experiment_state = "running"
        challenger.experiment_state = "running"
        await self.session.flush()
        logger.info("ab_test_started", extra={
            "test_id": ab.id, "agent_name": agent_name,
            "baseline_version": baseline_version,
            "challenger_version": challenger_version,
        })
        return ab

    async def stop(self, test_id: str) -> ABTest:
        await self.repo.mark_aborted(test_id)
        logger.info("ab_test_stopped", extra={"test_id": test_id})
        return await self.repo.get(test_id)

    async def list_running(self) -> list[ABTest]:
        return await self.repo.list_running()

    async def list_all(self) -> list[ABTest]:
        return await self.repo.list_all()

    async def pick_version(self, agent_name: str, chapter_id: str) -> Optional[str]:
        running = await self.repo.list_running(agent_name=agent_name)
        if not running:
            return None
        ab = running[0]
        h = int(hashlib.md5(f"{ab.id}:{chapter_id}".encode()).hexdigest(), 16)
        return ab.baseline_version if h % 2 == 0 else ab.challenger_version

    async def results(self, test_id: str) -> ABTestResult:
        ab = await self.repo.get(test_id)
        if not ab:
            raise ValueError(f"A/B test {test_id} not found")
        result = await self.session.execute(
            select(ChapterQualityMetric).where(
                ChapterQualityMetric.phase == ab.agent_name,
            )
        )
        metrics = list(result.scalars().all())
        baseline_scores = [
            m.overall_score for m in metrics
            if m.prompt_version == ab.baseline_version and m.overall_score is not None
        ]
        challenger_scores = [
            m.overall_score for m in metrics
            if m.prompt_version == ab.challenger_version and m.overall_score is not None
        ]
        baseline_n = len(baseline_scores)
        challenger_n = len(challenger_scores)
        max_samples = ab.config.get("max_samples", 10)
        min_samples = ab.config.get("min_samples", 3)
        alpha = ab.config.get("alpha", 0.05)
        if baseline_n < min_samples or challenger_n < min_samples:
            return ABTestResult(
                test_id=test_id, status="pending",
                baseline_mean=sum(baseline_scores) / baseline_n if baseline_n else None,
                challenger_mean=sum(challenger_scores) / challenger_n if challenger_n else None,
                p_value=None, baseline_n=baseline_n, challenger_n=challenger_n,
                winner=None,
            )
        baseline_mean = sum(baseline_scores) / baseline_n
        challenger_mean = sum(challenger_scores) / challenger_n
        t_stat, p_value = stats.ttest_ind(baseline_scores, challenger_scores, equal_var=False)
        if baseline_n + challenger_n >= max_samples * 2:
            winner = "challenger" if p_value < alpha and challenger_mean > baseline_mean else "baseline"
            await self.repo.mark_completed(test_id, winner=winner, ended_at=datetime.utcnow())
        else:
            winner = "challenger" if p_value < alpha and challenger_mean > baseline_mean else None
        return ABTestResult(
            test_id=test_id,
            status="completed" if baseline_n + challenger_n >= max_samples * 2 else "running",
            baseline_mean=baseline_mean, challenger_mean=challenger_mean,
            p_value=p_value, baseline_n=baseline_n, challenger_n=challenger_n,
            winner=winner,
        )

    async def declare_winner(self, test_id: str, winner: str) -> None:
        ab = await self.repo.get(test_id)
        if not ab:
            raise ValueError(f"A/B test {test_id} not found")
        if winner not in ("baseline", "challenger"):
            raise ValueError(f"Invalid winner: {winner}")
        chosen_version = ab.baseline_version if winner == "baseline" else ab.challenger_version
        from novel_dev.services.prompt_registry import PromptRegistry
        reg = PromptRegistry(self.session)
        await reg.set_active(ab.agent_name, chosen_version)
        await self.repo.mark_completed(test_id, winner=winner, ended_at=datetime.utcnow())
        logger.info("ab_test_winner_declared", extra={
            "test_id": test_id, "winner": winner, "chosen_version": chosen_version,
        })
