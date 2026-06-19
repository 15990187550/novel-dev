from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents._default_prompts import DEFAULT_PROMPTS
from novel_dev.config import settings
from novel_dev.repositories.prompt_version_repo import PromptVersionRepository

logger = logging.getLogger(__name__)


class PromptRegistry:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = PromptVersionRepository(session)

    async def get_active(self, agent_name: str) -> str:
        pv = await self.repo.get_active(agent_name)
        if pv:
            return pv.content
        if getattr(settings, "phase3_cold_start_allow_hardcoded_fallback", True):
            logger.warning(
                "prompt_registry_cold_start_fallback",
                extra={"agent_name": agent_name},
            )
            return DEFAULT_PROMPTS.get(agent_name, "")
        raise RuntimeError(
            f"No active prompt for {agent_name} and cold_start fallback disabled"
        )

    async def get_by_version(self, agent_name: str, version: str) -> str:
        pv = await self.repo.get_by_version(agent_name, version)
        if not pv:
            raise ValueError(f"Version {version} not found for {agent_name}")
        return pv.content

    async def list_versions(self, agent_name: str) -> list[dict]:
        versions = await self.repo.list_versions(agent_name)
        return [
            {
                "id": v.id,
                "agent_name": v.agent_name,
                "version": v.version,
                "content": v.content,
                "is_active": v.is_active,
                "created_at": v.created_at.isoformat(),
                "created_by": v.created_by,
                "sample_count": v.sample_count,
                "parent_version": v.parent_version,
                "ab_test_id": v.ab_test_id,
            }
            for v in versions
        ]

    async def create_version(
        self, agent_name: str, version: str, content: str,
        is_active: bool = False, created_by: str = "user",
        parent_version: Optional[str] = None,
        ab_test_id: Optional[str] = None,
    ) -> dict:
        existing = await self.repo.get_by_version(agent_name, version)
        if existing:
            raise ValueError(f"Version {version} already exists for {agent_name}")
        pv = await self.repo.create(
            agent_name=agent_name, version=version, content=content,
            is_active=is_active, created_by=created_by,
            parent_version=parent_version, ab_test_id=ab_test_id,
        )
        if is_active:
            await self.repo.set_active(agent_name, version)
        logger.info("prompt_version_created", extra={
            "agent_name": agent_name, "version": version, "created_by": created_by,
        })
        return {"id": pv.id, "version": version, "agent_name": agent_name}

    async def set_active(self, agent_name: str, version: str) -> None:
        await self.repo.set_active(agent_name, version)
        logger.info("prompt_version_applied", extra={
            "agent_name": agent_name, "version": version,
        })

    async def rollback(self, agent_name: str, to_version: str) -> None:
        await self.set_active(agent_name, to_version)

    async def delete_version(self, agent_name: str, version: str) -> None:
        await self.repo.delete(agent_name, version)

    async def bootstrap_defaults(self) -> None:
        for agent_name, content in DEFAULT_PROMPTS.items():
            existing = await self.repo.get_active(agent_name)
            if existing:
                continue
            await self.repo.create(
                agent_name=agent_name, version="v1.0",
                content=content, is_active=True, created_by="system",
            )
        logger.info("prompt_registry_bootstrap", extra={"count": len(DEFAULT_PROMPTS)})

    async def increment_sample_count(self, agent_name: str, version: str) -> None:
        await self.repo.increment_sample_count(agent_name, version)
        # Phase 5: trigger ABAcceptanceDecider if this version is part of a running experiment
        try:
            from sqlalchemy import select
            from novel_dev.db.models import ABTest
            result = await self.session.execute(
                select(ABTest).where(
                    ABTest.agent_name == agent_name,
                    ABTest.status == "running",
                )
            )
            for ab in result.scalars().all():
                if version not in (ab.baseline_version, ab.challenger_version):
                    continue
                from novel_dev.services.ab_acceptance_decider import ABAcceptanceDecider
                decider = ABAcceptanceDecider(self.session)
                await decider.evaluate(experiment_id=ab.id, sample_scores=await self._gather_scores(ab))
        except Exception:
            import logging
            logging.getLogger(__name__).exception("ab_decider_invoke_failed")

    async def _gather_scores(self, ab):
        """Gather per-version sample scores for decider evaluation.

        Simplified: uses PromptVersion.last_score (if set) as the score; falls back
        to a synthetic default. In production this should pull from chapter_quality_repo.
        """
        from sqlalchemy import select
        from novel_dev.db.models import PromptVersion
        result = await self.session.execute(
            select(PromptVersion).where(PromptVersion.ab_test_id == ab.id)
        )
        pvs = list(result.scalars().all())
        out = {}
        for pv in pvs:
            score = pv.last_score if pv.last_score is not None else 80.0
            out[pv.version] = {
                "critic_scores": [score] * pv.sample_count if pv.sample_count > 0 else [score],
                "hook_achieved": [True] * max(pv.sample_count, 1),
                "thrill_verified": [True] * max(pv.sample_count, 1),
            }
        return out

    async def get_active_version_name(self, agent_name: str) -> str:
        pv = await self.repo.get_active(agent_name)
        return pv.version if pv else "v1.0"

    async def get_active_for_chapter(self, agent_name: str, chapter_id: str) -> str:
        from novel_dev.services.ab_test_runner import ABTestRunner
        runner = ABTestRunner(self.session)
        version = await runner.pick_version(agent_name, chapter_id)
        if version:
            return await self.get_by_version(agent_name, version)
        return await self.get_active(agent_name)
