import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.agents._llm_helpers import coerce_to_str_list, coerce_to_text
from novel_dev.repositories.knowledge_domain_repo import KnowledgeDomainRepository
from novel_dev.schemas.knowledge_domain import DEFAULT_DOMAIN_RULES, KnowledgeDomainCreate, KnowledgeDomainUpdate
from novel_dev.schemas.outline import SynopsisData
from novel_dev.services.log_service import log_service


class KnowledgeDomainService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = KnowledgeDomainRepository(session)

    async def create_domain(self, novel_id: str, payload: KnowledgeDomainCreate):
        rules = self._normalize_rules(payload.rules)
        keywords = payload.activation_keywords or self._derive_keywords(payload.name, rules)
        return await self.repo.create(
            novel_id=novel_id,
            name=payload.name,
            domain_type=payload.domain_type or "source_work",
            scope_status="unbound",
            activation_mode=payload.activation_mode or "auto",
            activation_keywords=keywords,
            rules=rules,
            source_doc_ids=payload.source_doc_ids,
            confidence=payload.confidence or "low",
        )

    async def update_domain(self, novel_id: str, domain_id: str, payload: KnowledgeDomainUpdate):
        domain = await self.repo.get_by_id(domain_id)
        if not domain or domain.novel_id != novel_id:
            raise ValueError("Knowledge domain not found")
        updates = payload.model_dump(exclude_unset=True)
        if "rules" in updates:
            updates["rules"] = self._normalize_rules(updates["rules"])
        if "activation_keywords" in updates and updates["activation_keywords"] is not None:
            updates["activation_keywords"] = coerce_to_str_list(updates["activation_keywords"])
        return await self.repo.update(domain, **updates)

    async def confirm_scope(self, novel_id: str, domain_id: str, scope_type: str, scope_refs: list[str]):
        domain = await self.repo.get_by_id(domain_id)
        if not domain or domain.novel_id != novel_id:
            raise ValueError("Knowledge domain not found")
        existing = list(domain.confirmed_scopes or [])
        seen = {(item.get("scope_type"), item.get("scope_ref")) for item in existing}
        for scope_ref in scope_refs:
            key = (scope_type, scope_ref)
            if key not in seen:
                existing.append({"scope_type": scope_type, "scope_ref": scope_ref})
                seen.add(key)
        return await self.repo.update(domain, confirmed_scopes=existing, scope_status="confirmed")

    async def suggest_scopes_from_synopsis(self, novel_id: str, synopsis: SynopsisData) -> list[dict[str, Any]]:
        domains = await self.repo.list_by_novel(novel_id)
        suggestions: list[dict[str, Any]] = []
        for domain in domains:
            if domain.activation_mode == "disabled" or not domain.is_active:
                continue
            if domain.activation_mode == "manual":
                continue
            domain_suggestions = list(domain.suggested_scopes or [])
            seen = {(item.get("scope_type"), item.get("scope_ref")) for item in domain_suggestions}
            for outline in synopsis.volume_outlines or []:
                text = outline.model_dump_json()
                matched = self._match_keywords(domain.activation_keywords or [], text)
                if not matched:
                    continue
                scope_ref = f"vol_{outline.volume_number}"
                key = ("volume", scope_ref)
                if key not in seen:
                    domain_suggestions.append({
                        "scope_type": "volume",
                        "scope_ref": scope_ref,
                        "matched_keywords": matched,
                        "confidence": min(0.95, 0.45 + len(matched) * 0.15),
                    })
                    seen.add(key)
                suggestions.append({
                    "domain_id": domain.id,
                    "domain_name": domain.name,
                    "scope_type": "volume",
                    "scope_ref": scope_ref,
                    "matched_keywords": matched,
                })
            if domain_suggestions != (domain.suggested_scopes or []):
                status = "confirmed" if domain.confirmed_scopes else "suggested"
                await self.repo.update(domain, suggested_scopes=domain_suggestions, scope_status=status)

        if suggestions:
            log_service.add_log(
                novel_id,
                "KnowledgeDomainService",
                f"已生成 {len(suggestions)} 条规则域作用域建议",
                event="agent.progress",
                status="succeeded",
                node="domain_scope_suggestion",
                task="suggest_domain_scopes",
                metadata={"suggestions": suggestions[:20]},
            )
        return suggestions

    def create_domain_draft_from_document(
        self,
        *,
        name: str,
        doc_id: str,
        content: str,
        domain_type: str = "source_work",
        activation_mode: str = "auto",
    ) -> KnowledgeDomainCreate:
        rules = self._extract_rules_heuristically(content)
        keywords = self._derive_keywords(name, rules, content)
        return KnowledgeDomainCreate(
            name=name,
            domain_type=domain_type,
            activation_mode=activation_mode,
            activation_keywords=keywords,
            rules=rules,
            source_doc_ids=[doc_id],
            confidence="low",
        )

    def _normalize_rules(self, rules: dict[str, Any] | None) -> dict[str, Any]:
        normalized = {key: list(value) for key, value in DEFAULT_DOMAIN_RULES.items()}
        for key, value in (rules or {}).items():
            if key in normalized:
                normalized[key] = coerce_to_str_list(value)
            else:
                normalized[str(key)] = value
        return normalized

    def _derive_keywords(self, name: str, rules: dict[str, Any], content: str = "") -> list[str]:
        candidates = [coerce_to_text(name).strip()]
        for value in rules.values():
            if isinstance(value, list):
                candidates.extend(str(item) for item in value[:8])
        candidates.extend(re.findall(r"《([^》]{2,20})》", content))
        candidates.extend(re.findall(r"([\u4e00-\u9fff]{2,12})(?:世界|体系|原著|规则|设定)", content[:3000]))

        keywords = []
        seen = set()
        for candidate in candidates:
            text = coerce_to_text(candidate).strip(" ：:，,。；;、[]()（）")
            if not text or len(text) < 2 or text in seen:
                continue
            keywords.append(text)
            seen.add(text)
            if len(keywords) >= 12:
                break
        return keywords

    def _extract_rules_heuristically(self, content: str) -> dict[str, Any]:
        text = coerce_to_text(content)
        rules = self._normalize_rules({})
        line_map = {
            "power_ladder": ("境界", "等级", "层级", "修炼"),
            "accessible_conflicts": ("允许", "可触达", "可用冲突", "当前可"),
            "foreshadow_only": ("伏笔", "只能伏笔", "远景", "暂不展开"),
            "forbidden_now": ("禁止", "不能", "不得", "不可", "不要"),
            "continuity_rules": ("连续", "承接", "规则", "必须"),
            "knowledge_boundaries": ("未知", "待确认", "缺口", "不确定"),
        }
        for raw_line in text.splitlines():
            line = raw_line.strip(" -\t")
            if len(line) < 4:
                continue
            for key, markers in line_map.items():
                if any(marker in line for marker in markers):
                    rules[key].append(line[:180])
                    break
        return rules

    def _match_keywords(self, keywords: list[str], text: str) -> list[str]:
        matched = []
        for keyword in keywords:
            value = coerce_to_text(keyword).strip()
            if value and value in text and value not in matched:
                matched.append(value)
        return matched[:10]
