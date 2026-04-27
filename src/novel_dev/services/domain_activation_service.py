from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents._llm_helpers import coerce_to_str_list
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.knowledge_domain_repo import KnowledgeDomainRepository
from novel_dev.schemas.outline import SynopsisData
from novel_dev.services.log_service import log_service
from novel_dev.services.narrative_constraint_service import ActiveConstraintContext, NarrativeConstraintBuilder


class DomainActivationService:
    ACTIVATION_THRESHOLD = 60
    CANDIDATE_THRESHOLD = 30
    CONSTRAINT_SOURCE_DOC_TYPES = ("worldview", "setting", "concept", "synopsis")

    def __init__(self, session: AsyncSession):
        self.session = session
        self.domain_repo = KnowledgeDomainRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.fallback_builder = NarrativeConstraintBuilder()

    async def build_context(
        self,
        *,
        novel_id: str,
        synopsis: SynopsisData,
        volume_number: int,
        source_text: str = "",
        world_snapshot: dict[str, Any] | None = None,
        feedback: str = "",
    ) -> ActiveConstraintContext:
        if not source_text:
            source_text = await self._load_source_text(novel_id)
        fallback = self.fallback_builder.build_for_volume(
            synopsis=synopsis,
            volume_number=volume_number,
            source_text=source_text,
            world_snapshot=world_snapshot,
        )
        domains = await self.domain_repo.list_by_novel(novel_id)
        if not domains:
            log_service.add_log(
                novel_id,
                "DomainActivationService",
                f"第 {volume_number} 卷未配置规则域，使用文档启发式约束",
                event="agent.progress",
                status="fallback",
                node="domain_activation",
                task="activate_domains",
                metadata={"volume_number": volume_number},
            )
            return fallback

        scope_ref = f"vol_{volume_number}"
        current_outline = next((item for item in synopsis.volume_outlines or [] if item.volume_number == volume_number), None)
        query_text = "\n".join([
            synopsis.title,
            synopsis.logline,
            synopsis.core_conflict,
            current_outline.model_dump_json() if current_outline else "",
            feedback or "",
        ])

        active = []
        candidates = []
        for domain in domains:
            score, matched, reason = self._score_domain(domain, scope_ref, query_text)
            item = {"domain": domain, "score": score, "matched": matched, "reason": reason}
            if score >= self.ACTIVATION_THRESHOLD:
                active.append(item)
            elif score >= self.CANDIDATE_THRESHOLD:
                candidates.append(item)

        context = self._merge_context(
            fallback=fallback,
            active=active,
            candidates=candidates,
            volume_number=volume_number,
        )
        context.executable_constraints = self.fallback_builder._build_executable_constraints(
            context=context,
            query_text=query_text,
            current_outline=current_outline,
        )
        for item in active:
            await self.domain_repo.record_usage(
                novel_id=novel_id,
                domain_id=item["domain"].id,
                scope_type="volume",
                scope_ref=scope_ref,
                matched_keywords=item["matched"],
                usage_reason=item["reason"],
            )

        log_service.add_log(
            novel_id,
            "DomainActivationService",
            f"第 {volume_number} 卷激活规则域: {', '.join(context.active_domains) if context.active_domains else '无'}",
            event="agent.progress",
            status="succeeded",
            node="domain_activation",
            task="activate_domains",
            metadata={
                "volume_number": volume_number,
                "active_domains": [
                    {
                        "domain_id": item["domain"].id,
                        "name": item["domain"].name,
                        "score": item["score"],
                        "matched_keywords": item["matched"],
                        "reason": item["reason"],
                    }
                    for item in active
                ],
                "candidate_domains": [
                    {
                        "domain_id": item["domain"].id,
                        "name": item["domain"].name,
                        "score": item["score"],
                        "matched_keywords": item["matched"],
                    }
                    for item in candidates
                ],
            },
        )
        return context

    async def _load_source_text(self, novel_id: str) -> str:
        docs = []
        for doc_type in self.CONSTRAINT_SOURCE_DOC_TYPES:
            docs.extend(await self.doc_repo.get_current_by_type(novel_id, doc_type))
        return "\n\n".join(f"[{doc.doc_type}] {doc.title}\n{doc.content}" for doc in docs)[:10000]

    def _score_domain(self, domain, scope_ref: str, query_text: str) -> tuple[int, list[str], str]:
        if not domain.is_active or domain.activation_mode == "disabled":
            return 0, [], "disabled"
        if domain.activation_mode == "manual" and not self._scope_matches(domain.confirmed_scopes or [], scope_ref):
            return 0, [], "manual_not_confirmed"

        matched = self._match_keywords(domain.activation_keywords or [], query_text)
        score = 0
        reasons = []
        if domain.activation_mode == "always":
            score += 70
            reasons.append("always")
        if self._scope_matches(domain.confirmed_scopes or [], scope_ref):
            score += 100
            reasons.append("confirmed_scope")
        if self._scope_matches(domain.suggested_scopes or [], scope_ref):
            score += 80
            reasons.append("suggested_scope")
        if matched:
            score += min(60, len(matched) * 20)
            reasons.append("keyword_match:" + ",".join(matched))
        return score, matched, ";".join(reasons) or "no_match"

    def _scope_matches(self, scopes: list[dict[str, Any]], scope_ref: str) -> bool:
        return any(item.get("scope_type") == "volume" and item.get("scope_ref") == scope_ref for item in scopes)

    def _match_keywords(self, keywords: list[str], text: str) -> list[str]:
        matched = []
        for keyword in keywords:
            value = str(keyword or "").strip()
            if value and value in text and value not in matched:
                matched.append(value)
        return matched[:10]

    def _merge_context(
        self,
        *,
        fallback: ActiveConstraintContext,
        active: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        volume_number: int,
    ) -> ActiveConstraintContext:
        context = ActiveConstraintContext(
            volume_number=volume_number,
            active_domains=[],
            current_scope=list(fallback.current_scope),
            allowed_conflicts=list(fallback.allowed_conflicts),
            foreshadow_only=list(fallback.foreshadow_only),
            forbidden_now=list(fallback.forbidden_now),
            continuity_rules=list(fallback.continuity_rules),
            power_ladder=list(fallback.power_ladder),
            knowledge_boundaries=list(fallback.knowledge_boundaries),
            open_questions=list(fallback.open_questions),
            source_snippets=list(fallback.source_snippets),
            executable_constraints=list(fallback.executable_constraints),
        )
        for item in active:
            domain = item["domain"]
            rules = domain.rules or {}
            context.active_domains.append(f"{domain.name}({item['reason']})")
            context.current_scope.extend(coerce_to_str_list(rules.get("scope_boundaries")))
            context.allowed_conflicts.extend(coerce_to_str_list(rules.get("accessible_conflicts")))
            context.foreshadow_only.extend(coerce_to_str_list(rules.get("foreshadow_only")))
            context.forbidden_now.extend(coerce_to_str_list(rules.get("forbidden_now")))
            context.continuity_rules.extend(coerce_to_str_list(rules.get("continuity_rules")))
            context.power_ladder.extend(coerce_to_str_list(rules.get("power_ladder")))
            context.knowledge_boundaries.extend(coerce_to_str_list(rules.get("knowledge_boundaries")))
            context.open_questions.extend(coerce_to_str_list(rules.get("open_questions")))
            context.source_snippets.append(
                f"{domain.name}: 命中 {', '.join(item['matched']) or '作用域'}; 置信度 {domain.confidence}"
            )
        for item in candidates:
            domain = item["domain"]
            context.source_snippets.append(
                f"候选规则域 {domain.name}: 命中 {', '.join(item['matched'])}; 未达到完整激活阈值，按知识缺口保守处理。"
            )
            context.foreshadow_only.append(f"{domain.name} 相关未确认内容只能作为伏笔或待确认线索。")
        return self._dedupe_context(context)

    def _dedupe_context(self, context: ActiveConstraintContext) -> ActiveConstraintContext:
        for field in (
            "active_domains",
            "current_scope",
            "allowed_conflicts",
            "foreshadow_only",
            "forbidden_now",
            "continuity_rules",
            "power_ladder",
            "knowledge_boundaries",
            "open_questions",
            "source_snippets",
        ):
            values = []
            seen = set()
            for value in getattr(context, field):
                text = str(value).strip()
                if text and text not in seen:
                    values.append(text)
                    seen.add(text)
            setattr(context, field, values)
        constraints = []
        seen_constraints = set()
        for constraint in context.executable_constraints:
            key = (constraint.constraint_type, constraint.title, tuple(constraint.terms), constraint.instruction)
            if key in seen_constraints:
                continue
            constraints.append(constraint)
            seen_constraints.add(key)
        context.executable_constraints = constraints
        return context
