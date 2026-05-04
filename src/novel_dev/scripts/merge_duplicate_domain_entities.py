import argparse
import asyncio
import json
import logging
import re
import sys
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.db.engine import async_session_maker
from novel_dev.db.models import Entity, EntityRelationship, EntityVersion
from novel_dev.repositories.entity_repo import EntityRepository

logger = logging.getLogger(__name__)

ALIAS_SEPARATORS_PATTERN = r"[/／|｜、;；]+"
BRACKET_CONTENT_PATTERN = r"（(.*?)）|\((.*?)\)|【(.*?)】|\[(.*?)\]"
LIST_SEPARATOR_PATTERN = r"[/／|｜、;；,，]"


def normalize_entity_name(value: str) -> str:
    return EntityRepository.normalize_name(value or "")


def entity_name_variants(name: str, aliases: list[Any] | None = None) -> set[str]:
    raw_values = [name or ""]
    raw_values.extend(str(alias) for alias in (aliases or []) if alias)

    candidates: set[str] = set()
    for raw in raw_values:
        raw = raw.strip()
        if not raw:
            continue
        candidates.add(raw)
        for match in re.finditer(BRACKET_CONTENT_PATTERN, raw):
            candidates.update(part for part in match.groups() if part)
        candidates.update(part for part in re.split(ALIAS_SEPARATORS_PATTERN, raw) if part)

    return {
        normalized
        for candidate in candidates
        if (normalized := normalize_entity_name(candidate))
    }


def find_duplicate_groups(
    rows: list[dict[str, Any]],
    *,
    include_ambiguous: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scoped_rows: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        scoped_rows[(row.get("novel_id"), row.get("domain_key"), row.get("type"))].append(row)

    groups: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for scope, scope_rows in scoped_rows.items():
        if len(scope_rows) < 2:
            continue

        variants_by_id = {
            row["id"]: entity_name_variants(row.get("name") or "", _state_aliases(row.get("state")))
            for row in scope_rows
        }
        row_by_id = {row["id"]: row for row in scope_rows}
        standalone_variants = {
            next(iter(variants)): row["id"]
            for row in scope_rows
            if len((variants := variants_by_id[row["id"]])) == 1
        }

        ambiguous_ids: set[str] = set()
        if not include_ambiguous:
            for row in scope_rows:
                row_variants = variants_by_id[row["id"]]
                ambiguous_reason = _ambiguous_name_reason(row, row_variants, standalone_variants)
                if ambiguous_reason:
                    ambiguous_ids.add(row["id"])
                    skipped.append(
                        {
                            "entity_id": row["id"],
                            "name": row.get("name"),
                            "scope": _scope_payload(scope),
                            "variants": sorted(row_variants),
                            "reason": ambiguous_reason,
                        }
                    )

        graph: dict[str, set[str]] = defaultdict(set)
        ids = [row["id"] for row in scope_rows if row["id"] not in ambiguous_ids]
        for index, left_id in enumerate(ids):
            for right_id in ids[index + 1 :]:
                shared = variants_by_id[left_id] & variants_by_id[right_id]
                shared = {variant for variant in shared if variant in standalone_variants}
                if not shared:
                    continue
                graph[left_id].add(right_id)
                graph[right_id].add(left_id)

        visited: set[str] = set()
        for entity_id in ids:
            if entity_id in visited or not graph.get(entity_id):
                continue
            component: list[str] = []
            queue: deque[str] = deque([entity_id])
            visited.add(entity_id)
            while queue:
                current = queue.popleft()
                component.append(current)
                for neighbor in graph[current]:
                    if neighbor in visited:
                        continue
                    visited.add(neighbor)
                    queue.append(neighbor)

            if len(component) < 2:
                continue
            keep_id = _choose_canonical_id([row_by_id[item] for item in component], variants_by_id)
            drop_ids = sorted([item for item in component if item != keep_id], key=lambda item: row_by_id[item].get("name") or "")
            shared_variants = sorted(
                variant
                for variant in set().union(*(variants_by_id[item] for item in component))
                if sum(1 for item in component if variant in variants_by_id[item]) >= 2
            )
            groups.append(
                {
                    "keep_id": keep_id,
                    "keep_name": row_by_id[keep_id].get("name"),
                    "drop_ids": drop_ids,
                    "drop_names": [row_by_id[item].get("name") for item in drop_ids],
                    "shared_variants": shared_variants,
                    "scope": _scope_payload(scope),
                    "reason": "same_scope_name_variant_overlap",
                }
            )

    groups.sort(key=lambda group: (str(group["scope"]), group["keep_name"] or "", group["keep_id"]))
    return groups, skipped


class DuplicateEntityMergeService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        create_backups: bool = True,
        include_ambiguous: bool = False,
    ):
        self.session = session
        self.create_backups = create_backups
        self.include_ambiguous = include_ambiguous

    async def scan(
        self,
        *,
        novel_id: str | None = None,
        domain_id: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        rows = await self._load_entity_rows(novel_id=novel_id, domain_id=domain_id)
        groups, skipped = find_duplicate_groups(rows, include_ambiguous=self.include_ambiguous)
        if limit is not None:
            groups = groups[:limit]
        return {
            "dry_run": True,
            "candidate_groups": groups,
            "candidate_group_count": len(groups),
            "candidate_drop_count": sum(len(group["drop_ids"]) for group in groups),
            "skipped": skipped,
            "skipped_count": len(skipped),
        }

    async def apply(
        self,
        *,
        novel_id: str | None = None,
        domain_id: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        scan_result = await self.scan(novel_id=novel_id, domain_id=domain_id, limit=limit)
        apply_result = await self.apply_groups(scan_result["candidate_groups"])
        return {
            **scan_result,
            "dry_run": False,
            **apply_result,
        }

    async def apply_groups(self, groups: list[dict[str, Any]]) -> dict[str, Any]:
        backup_tables = await self._create_backup_tables() if self.create_backups and groups else {}
        result = {
            "backup_tables": backup_tables,
            "merged_groups": 0,
            "merged_entities": 0,
            "source_updates": 0,
            "target_updates": 0,
            "self_relationships_inactivated": 0,
            "duplicate_relationships_inactivated": 0,
            "errors": [],
        }
        for group in groups:
            try:
                item_result = await self._merge_group(group)
            except Exception as exc:
                result["errors"].append(
                    {
                        "group": group,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            result["merged_groups"] += 1
            for key in (
                "merged_entities",
                "source_updates",
                "target_updates",
                "self_relationships_inactivated",
                "duplicate_relationships_inactivated",
            ):
                result[key] += item_result[key]
        await self.session.flush()
        return result

    async def _load_entity_rows(
        self,
        *,
        novel_id: str | None,
        domain_id: str | None,
    ) -> list[dict[str, Any]]:
        stmt = select(Entity)
        if novel_id:
            stmt = stmt.where(Entity.novel_id == novel_id)
        entities = list((await self.session.execute(stmt.order_by(Entity.name.asc(), Entity.id.asc()))).scalars().all())

        rows: list[dict[str, Any]] = []
        for entity in entities:
            latest = await self._latest_version(entity.id)
            state = latest.state if latest and isinstance(latest.state, dict) else {}
            domain_key = _domain_key(entity.search_document or "", state)
            if domain_id and domain_key != f"_knowledge_domain_id:{domain_id}":
                continue
            rows.append(
                {
                    "id": entity.id,
                    "name": entity.name,
                    "type": entity.type,
                    "novel_id": entity.novel_id,
                    "domain_key": domain_key,
                    "state": state,
                    "relationship_count": await self._relationship_count(entity.id),
                }
            )
        return rows

    async def _latest_version(self, entity_id: str) -> EntityVersion | None:
        result = await self.session.execute(
            select(EntityVersion)
            .where(EntityVersion.entity_id == entity_id)
            .order_by(EntityVersion.version.desc())
        )
        return result.scalars().first()

    async def _relationship_count(self, entity_id: str) -> int:
        result = await self.session.execute(
            select(EntityRelationship).where(
                EntityRelationship.is_active.is_(True),
                (EntityRelationship.source_id == entity_id) | (EntityRelationship.target_id == entity_id),
            )
        )
        return len(result.scalars().all())

    async def _merge_group(self, group: dict[str, Any]) -> dict[str, int]:
        keep = await self.session.get(Entity, group["keep_id"])
        if keep is None:
            raise ValueError(f"keep entity not found: {group['keep_id']}")
        drops = [await self.session.get(Entity, drop_id) for drop_id in group["drop_ids"]]
        drop_entities = [entity for entity in drops if entity is not None]
        if not drop_entities:
            return self._empty_merge_result()

        keep_latest = await self._latest_version(keep.id)
        keep_state = dict(keep_latest.state if keep_latest and isinstance(keep_latest.state, dict) else {})
        merged_state = dict(keep_state)
        merged_records = list(merged_state.get("_merged_duplicate_entities") or [])
        aliases = _merge_aliases(
            _state_aliases(merged_state),
            [keep.name],
            group.get("shared_variants") or [],
        )

        for drop in drop_entities:
            drop_latest = await self._latest_version(drop.id)
            drop_state = dict(drop_latest.state if drop_latest and isinstance(drop_latest.state, dict) else {})
            aliases = _merge_aliases(aliases, [drop.name], _state_aliases(drop_state), entity_name_variants(drop.name, _state_aliases(drop_state)))
            merged_state = _merge_entity_states(merged_state, drop_state)
            merged_records.append(
                {
                    "entity_id": drop.id,
                    "name": drop.name,
                    "version": drop.current_version,
                    "state": drop_state,
                }
            )

        merged_state["aliases"] = [alias for alias in aliases if alias and normalize_entity_name(alias) != normalize_entity_name(keep.name)]
        merged_state["_merged_duplicate_entities"] = merged_records
        next_version = (keep.current_version or 0) + 1
        self.session.add(
            EntityVersion(
                entity_id=keep.id,
                version=next_version,
                state=merged_state,
                diff_summary={
                    "source": "merge_duplicate_domain_entities",
                    "merged_entity_ids": [entity.id for entity in drop_entities],
                    "merged_entity_names": [entity.name for entity in drop_entities],
                    "reason": group.get("reason"),
                    "shared_variants": group.get("shared_variants") or [],
                },
            )
        )
        keep.current_version = next_version
        keep.search_document = _merge_text(keep.search_document, *[entity.search_document for entity in drop_entities])

        result = self._empty_merge_result()
        drop_ids = [entity.id for entity in drop_entities]
        for relationship in await self._relationships_by_source(drop_ids):
            old_source_id = relationship.source_id
            relationship.source_id = keep.id
            relationship.meta = _append_merge_meta(relationship.meta, "source_entity_merged", {"old_source_id": old_source_id, "new_source_id": keep.id})
            result["source_updates"] += 1
        for relationship in await self._relationships_by_target(drop_ids):
            old_target_id = relationship.target_id
            relationship.target_id = keep.id
            relationship.meta = _append_merge_meta(relationship.meta, "target_entity_merged", {"old_target_id": old_target_id, "new_target_id": keep.id})
            result["target_updates"] += 1

        result["self_relationships_inactivated"] += await self._inactivate_self_relationships(keep.id)
        result["duplicate_relationships_inactivated"] += await self._collapse_duplicate_relationships(keep.novel_id)

        await self.session.execute(delete(EntityVersion).where(EntityVersion.entity_id.in_(drop_ids)))
        await self.session.execute(delete(Entity).where(Entity.id.in_(drop_ids)))
        result["merged_entities"] = len(drop_ids)
        await self.session.flush()
        return result

    async def _relationships_by_source(self, source_ids: list[str]) -> list[EntityRelationship]:
        result = await self.session.execute(select(EntityRelationship).where(EntityRelationship.source_id.in_(source_ids)))
        return list(result.scalars().all())

    async def _relationships_by_target(self, target_ids: list[str]) -> list[EntityRelationship]:
        result = await self.session.execute(select(EntityRelationship).where(EntityRelationship.target_id.in_(target_ids)))
        return list(result.scalars().all())

    async def _inactivate_self_relationships(self, entity_id: str) -> int:
        result = await self.session.execute(
            select(EntityRelationship).where(
                EntityRelationship.source_id == entity_id,
                EntityRelationship.target_id == entity_id,
                EntityRelationship.is_active.is_(True),
            )
        )
        count = 0
        for relationship in result.scalars().all():
            relationship.is_active = False
            relationship.meta = _append_merge_meta(
                relationship.meta,
                "self_relationship_after_entity_merge",
                {"entity_id": entity_id},
            )
            count += 1
        return count

    async def _collapse_duplicate_relationships(self, novel_id: str | None) -> int:
        stmt = select(EntityRelationship).where(EntityRelationship.is_active.is_(True))
        if novel_id is not None:
            stmt = stmt.where(EntityRelationship.novel_id == novel_id)
        rows = list((await self.session.execute(stmt.order_by(EntityRelationship.id.asc()))).scalars().all())
        grouped: dict[tuple[Any, str, str, str], list[EntityRelationship]] = defaultdict(list)
        for row in rows:
            grouped[(row.novel_id, row.source_id, row.target_id, row.relation_type)].append(row)

        count = 0
        for relationships in grouped.values():
            if len(relationships) < 2:
                continue
            winner = relationships[0]
            merged_meta = dict(winner.meta or {})
            merged_meta.setdefault("merged_duplicate_relationships", [])
            for duplicate in relationships[1:]:
                merged_meta["merged_duplicate_relationships"].append(
                    {
                        "relationship_id": duplicate.id,
                        "source_id": duplicate.source_id,
                        "target_id": duplicate.target_id,
                        "relation_type": duplicate.relation_type,
                        "meta": duplicate.meta,
                    }
                )
                duplicate.is_active = False
                duplicate.meta = _append_merge_meta(
                    duplicate.meta,
                    "duplicate_relationship_after_entity_merge",
                    {"merged_into_relationship_id": winner.id},
                )
                count += 1
            winner.meta = merged_meta
        return count

    async def _create_backup_tables(self) -> dict[str, str]:
        suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        tables = {
            "entities": f"entity_merge_entities_backup_{suffix}",
            "entity_versions": f"entity_merge_versions_backup_{suffix}",
            "entity_relationships": f"entity_merge_relationships_backup_{suffix}",
        }
        for source, backup in tables.items():
            await self.session.execute(text(f'CREATE TABLE "{backup}" AS SELECT * FROM {source}'))
        return tables

    @staticmethod
    def _empty_merge_result() -> dict[str, int]:
        return {
            "merged_entities": 0,
            "source_updates": 0,
            "target_updates": 0,
            "self_relationships_inactivated": 0,
            "duplicate_relationships_inactivated": 0,
        }


def _state_aliases(state: Any) -> list[Any]:
    if not isinstance(state, dict):
        return []
    aliases = state.get("aliases")
    if isinstance(aliases, list):
        return aliases
    return []


def _domain_key(search_document: str, state: dict[str, Any]) -> str | None:
    domain_id = state.get("_knowledge_domain_id") if isinstance(state, dict) else None
    if domain_id:
        return f"_knowledge_domain_id:{domain_id}"
    domain_name = state.get("_knowledge_domain_name") if isinstance(state, dict) else None
    if domain_name:
        return f"_knowledge_domain_name:{domain_name}"
    return EntityRepository._search_document_domain_key(search_document or "")


def _ambiguous_name_reason(
    row: dict[str, Any],
    variants: set[str],
    standalone_variants: dict[str, str],
) -> str | None:
    name = row.get("name") or ""
    if len(variants) < 2:
        return None

    if re.search(LIST_SEPARATOR_PATTERN, name):
        standalone_hit_count = sum(1 for variant in variants if variant in standalone_variants)
        if row.get("type") != "character" and standalone_hit_count >= 1:
            return "ambiguous_branch_or_aggregate_name"
        if standalone_hit_count >= 2:
            return "ambiguous_aggregate_name"
        if row.get("type") == "character" and re.search(r"(一族|族群|家族|宗门|门派|联盟|帝国|王朝|组织)", name):
            return "ambiguous_character_group_name"

    bracket_parts = _bracket_parts(name)
    if bracket_parts:
        bracket_variants = {
            normalized
            for part in bracket_parts
            if (normalized := normalize_entity_name(part))
        }
        if bracket_variants and not any(variant in standalone_variants for variant in bracket_variants):
            return "ambiguous_shared_descriptor"
        if any(_is_generic_bracket_descriptor(part, row.get("type")) for part in bracket_parts):
            return "ambiguous_descriptor_qualified_name"
    return None


def _bracket_parts(name: str) -> list[str]:
    parts: list[str] = []
    for match in re.finditer(BRACKET_CONTENT_PATTERN, name or ""):
        parts.extend(part.strip() for part in match.groups() if part and part.strip())
    return parts


def _is_generic_bracket_descriptor(part: str, entity_type: str | None) -> bool:
    text_value = part.strip()
    if not text_value:
        return False
    if re.fullmatch(r"第.*", text_value):
        return True
    if text_value in {"种族", "新", "旧", "投影", "主角", "分身", "化身", "小型", "中型", "大型"}:
        return True
    if entity_type in {"item", "location", "faction"} and re.search(r"(阶段|形态|版本|分部|分支)", text_value):
        return True
    return False


def _choose_canonical_id(rows: list[dict[str, Any]], variants_by_id: dict[str, set[str]]) -> str:
    def rank(row: dict[str, Any]) -> tuple[int, int, int, str]:
        name = row.get("name") or ""
        normalized = normalize_entity_name(name)
        plain_match = int(len(variants_by_id[row["id"]]) == 1 and normalized in variants_by_id[row["id"]])
        no_punctuation = int(not re.search(rf"{LIST_SEPARATOR_PATTERN}|[（(【\[]", name))
        relationship_count = int(row.get("relationship_count") or 0)
        return (plain_match, no_punctuation, relationship_count, -len(name))

    return sorted(rows, key=lambda row: (rank(row), row["id"]), reverse=True)[0]["id"]


def _scope_payload(scope: tuple[Any, Any, Any]) -> dict[str, Any]:
    return {"novel_id": scope[0], "domain_key": scope[1], "type": scope[2]}


def _merge_aliases(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        items = value if isinstance(value, (list, tuple, set)) else [value]
        for item in items:
            if item is None:
                continue
            text_value = str(item).strip()
            if not text_value:
                continue
            candidate_values = [text_value]
            outside_brackets = re.sub(BRACKET_CONTENT_PATTERN, "", text_value).strip()
            if outside_brackets:
                candidate_values.append(outside_brackets)
            for match in re.finditer(BRACKET_CONTENT_PATTERN, text_value):
                candidate_values.extend(part for part in match.groups() if part)
            candidate_values.extend(part for part in re.split(ALIAS_SEPARATORS_PATTERN, text_value) if part)
            for candidate in candidate_values:
                candidate = candidate.strip()
                normalized = normalize_entity_name(candidate)
                if not candidate or not normalized or candidate in seen:
                    continue
                seen.add(candidate)
                result.append(candidate)
    return result


def _merge_entity_states(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in incoming.items():
        if key in {"aliases", "_merged_duplicate_entities"} or value in (None, "", [], {}):
            continue
        existing = result.get(key)
        if existing in (None, "", [], {}):
            result[key] = value
        elif isinstance(existing, list) and isinstance(value, list):
            result[key] = _merge_aliases(existing, value)
        elif isinstance(existing, dict) and isinstance(value, dict):
            result[key] = {**existing, **value}
        elif isinstance(existing, str) and isinstance(value, str) and value not in existing:
            result[key] = _merge_text(existing, value)
    return result


def _merge_text(*values: Any) -> str | None:
    parts: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        if value not in parts:
            parts.append(value)
    return "\n".join(parts) if parts else None


def _append_merge_meta(meta: Any, reason: str, payload: dict[str, Any]) -> dict[str, Any]:
    merged = dict(meta) if isinstance(meta, dict) else {}
    merged["merge_reason"] = reason
    merged.update(payload)
    return merged


async def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Merge historical duplicate entities inside the same novel/domain/type scope")
    parser.add_argument("--novel-id", help="Limit to one novel")
    parser.add_argument("--domain-id", help="Limit to one knowledge domain id")
    parser.add_argument("--apply", action="store_true", help="Write merges. Default is dry-run only.")
    parser.add_argument("--include-ambiguous", action="store_true", help="Also merge list-like aggregate names")
    parser.add_argument("--limit", type=int, help="Maximum candidate groups to merge/report")
    parser.add_argument("--no-backup", action="store_true", help="Skip backup table creation when applying")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    async with async_session_maker() as session:
        service = DuplicateEntityMergeService(
            session,
            create_backups=not args.no_backup,
            include_ambiguous=args.include_ambiguous,
        )
        if args.apply:
            result = await service.apply(novel_id=args.novel_id, domain_id=args.domain_id, limit=args.limit)
            if result["errors"]:
                await session.rollback()
            else:
                await session.commit()
        else:
            result = await service.scan(novel_id=args.novel_id, domain_id=args.domain_id, limit=args.limit)
            await session.rollback()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
