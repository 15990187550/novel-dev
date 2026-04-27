import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.models import KnowledgeDomain, KnowledgeDomainUsage


class KnowledgeDomainRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        novel_id: str,
        name: str,
        domain_type: str = "global_story",
        scope_status: str = "unbound",
        activation_mode: str = "auto",
        activation_keywords: list[str] | None = None,
        rules: dict[str, Any] | None = None,
        source_doc_ids: list[str] | None = None,
        suggested_scopes: list[dict[str, Any]] | None = None,
        confirmed_scopes: list[dict[str, Any]] | None = None,
        confidence: str = "low",
        is_active: bool = True,
    ) -> KnowledgeDomain:
        domain = KnowledgeDomain(
            id=f"domain_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            name=name,
            domain_type=domain_type,
            scope_status=scope_status,
            activation_mode=activation_mode,
            activation_keywords=activation_keywords or [],
            rules=rules or {},
            source_doc_ids=source_doc_ids or [],
            suggested_scopes=suggested_scopes or [],
            confirmed_scopes=confirmed_scopes or [],
            confidence=confidence,
            is_active=is_active,
        )
        self.session.add(domain)
        await self.session.flush()
        return domain

    async def get_by_id(self, domain_id: str) -> Optional[KnowledgeDomain]:
        result = await self.session.execute(select(KnowledgeDomain).where(KnowledgeDomain.id == domain_id))
        return result.scalar_one_or_none()

    async def list_by_novel(self, novel_id: str, *, include_disabled: bool = False) -> list[KnowledgeDomain]:
        stmt = select(KnowledgeDomain).where(KnowledgeDomain.novel_id == novel_id)
        if not include_disabled:
            stmt = stmt.where(KnowledgeDomain.is_active.is_(True))
        stmt = stmt.order_by(KnowledgeDomain.updated_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, domain: KnowledgeDomain, **fields: Any) -> KnowledgeDomain:
        for key, value in fields.items():
            setattr(domain, key, value)
        await self.session.flush()
        return domain

    async def record_usage(
        self,
        *,
        novel_id: str,
        domain_id: str,
        scope_type: str,
        scope_ref: str,
        matched_keywords: list[str] | None = None,
        usage_reason: str = "",
    ) -> KnowledgeDomainUsage:
        usage = KnowledgeDomainUsage(
            id=f"du_{uuid.uuid4().hex[:8]}",
            novel_id=novel_id,
            domain_id=domain_id,
            scope_type=scope_type,
            scope_ref=scope_ref,
            matched_keywords=matched_keywords or [],
            usage_reason=usage_reason,
        )
        self.session.add(usage)
        await self.session.flush()
        return usage
