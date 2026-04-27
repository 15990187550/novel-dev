import json
import re
from typing import Literal

from pydantic import BaseModel

from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.services.log_service import logged_agent_step, log_service


class EntityClassificationLLMResult(BaseModel):
    category: Literal["人物", "势力", "功法", "法宝神兵", "天材地宝", "其他"]
    group_name: str = ""
    confidence: float
    reason: str


class EntityClassificationBatchItem(BaseModel):
    index: int
    category: Literal["人物", "势力", "功法", "法宝神兵", "天材地宝", "其他"]
    group_name: str = ""
    confidence: float
    reason: str


class EntityClassificationBatchResult(BaseModel):
    items: list[EntityClassificationBatchItem]


class EntityClassifierAgent:
    @logged_agent_step("EntityClassifierAgent", "分类实体", node="entity_classify", task="classify_entity")
    async def classify(
        self,
        *,
        entity_type: str,
        entity_name: str,
        latest_state: dict,
        relationships: list,
        novel_id: str = "",
    ) -> EntityClassificationLLMResult:
        if novel_id:
            log_service.add_log(novel_id, "EntityClassifierAgent", f"开始分类实体: {entity_name}")

        safe_name = entity_name.replace("{", "{{").replace("}", "}}")[:200]
        safe_type = (entity_type or "other").replace("{", "{{").replace("}", "}}")[:50]
        state_preview = re.sub(r"[{}]", "", str(latest_state or {}))[:3000]
        relationships_preview = re.sub(r"[{}]", "", str(relationships or []))[:1500]
        prompt = (
            "你是一位小说实体分类专家。请根据实体类型、名称、最新状态和关系，"
            "判断实体的一级分类与二级分类，并返回严格符合 EntityClassificationLLMResult Schema 的 JSON。\n\n"
            "一级分类只能是：人物、势力、功法、法宝神兵、天材地宝、其他。\n"
            "二级分类 group_name 要求：\n"
            "- 必须是该一级分类下可读的中文分组名，尽量简短。\n"
            "- 如果无法可靠判断，返回空字符串。\n"
            "- 不要返回“未分组”“其他”“默认分组”这类占位词。\n\n"
            "判断偏好：\n"
            "- entity_type=character 优先判断为人物，除非上下文明确不是人/角色。\n"
            "- entity_type=faction 优先判断为势力。\n"
            "- entity_type=item 需要结合名称与描述区分为功法、法宝神兵、天材地宝或其他。\n"
            "- “经、诀、法、术、神通、剑诀、心法”等通常偏功法。\n"
            "- “剑、刀、镜、印、钟、鼎、塔、棺、佩、珠、轮、图、旗、戟、枪、炉、令、幡”等通常偏法宝神兵。\n"
            "- “丹、药、果、草、花、液、髓、血、骨、晶、石”等若是资源/材料通常偏天材地宝。\n\n"
            f"实体类型：{safe_type}\n"
            f"实体名称：{safe_name}\n"
            f"最新状态：\n{state_preview}\n\n"
            f"关系信息：\n{relationships_preview}"
        )
        result = await call_and_parse_model(
            "EntityClassifierAgent",
            "classify_entity",
            prompt,
            EntityClassificationLLMResult,
            max_retries=3,
            novel_id=novel_id,
        )
        if novel_id:
            log_service.add_log(
                novel_id,
                "EntityClassifierAgent",
                f"实体分类结果: {result.category} / {result.group_name or '-'} (置信度 {result.confidence:.2f})",
            )
        return result

    @logged_agent_step("EntityClassifierAgent", "批量分类实体", node="entity_classify_batch", task="classify_entities_batch")
    async def classify_batch(
        self,
        *,
        entities: list[dict],
        novel_id: str = "",
    ) -> EntityClassificationBatchResult:
        if novel_id:
            log_service.add_log(novel_id, "EntityClassifierAgent", f"开始批量分类实体: {len(entities)} 个")

        safe_entities = []
        for index, entity in enumerate(entities):
            latest_state = entity.get("latest_state") or {}
            relationships = entity.get("relationships") or []
            safe_entities.append({
                "index": index,
                "entity_type": str(entity.get("entity_type") or "other")[:50],
                "entity_name": str(entity.get("entity_name") or "")[:200],
                "latest_state": str(latest_state)[:1800],
                "relationships": str(relationships)[:600],
                "local_category": entity.get("local_category"),
                "local_group_name": entity.get("local_group_name"),
            })

        payload = json.dumps(safe_entities, ensure_ascii=False)
        prompt = (
            "你是一位小说实体分类专家。请一次性分类多个实体，并返回严格符合 "
            "EntityClassificationBatchResult Schema 的 JSON。\n\n"
            "一级分类只能是：人物、势力、功法、法宝神兵、天材地宝、其他。\n"
            "二级分类 group_name 要求：必须是可读的中文分组名，尽量简短；无法可靠判断则返回空字符串；"
            "不要返回“未分组”“其他”“默认分组”这类占位词。\n\n"
            "判断偏好：\n"
            "- entity_type=character 优先判断为人物。\n"
            "- entity_type=faction 优先判断为势力。\n"
            "- entity_type=location 通常判断为其他 / 地点。\n"
            "- entity_type=item 需要结合名称与描述区分为功法、法宝神兵、天材地宝或其他。\n"
            "- 本地预分类 local_category/local_group_name 仅作为参考；如果上下文更明确，可以修正。\n\n"
            "返回要求：\n"
            "- items 数量必须与输入实体数量一致。\n"
            "- 每个结果必须带输入中的 index，不能漏项，不能新增无关项。\n\n"
            f"实体列表 JSON：\n{payload}"
        )
        result = await call_and_parse_model(
            "EntityClassifierAgent",
            "classify_entities_batch",
            prompt,
            EntityClassificationBatchResult,
            max_retries=3,
            novel_id=novel_id,
        )
        if novel_id:
            log_service.add_log(
                novel_id,
                "EntityClassifierAgent",
                f"批量实体分类完成: {len(result.items)}/{len(entities)} 个",
            )
        return result
