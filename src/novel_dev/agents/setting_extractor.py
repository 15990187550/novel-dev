import asyncio
from typing import List, Union

from pydantic import BaseModel, Field, field_validator

from novel_dev.agents._llm_helpers import call_and_parse_model
from novel_dev.services.log_service import logged_agent_step, log_service


MAX_SINGLE_EXTRACT_CHARS = 8000
MAX_PARALLEL_EXTRACT_CHUNKS = 2


class CharacterProfile(BaseModel):
    name: str
    identity: str = ""
    personality: str = ""
    goal: str = ""
    appearance: str = ""
    background: str = ""
    ability: str = ""
    realm: str = ""
    relationships: str = ""
    resources: str = ""
    secrets: str = ""
    conflict: str = ""
    arc: str = ""
    notes: str = ""


class ImportantItem(BaseModel):
    name: str
    description: str = ""
    significance: str = ""


class FactionInfo(BaseModel):
    name: str = ""
    description: str = ""
    relationship_with_protagonist: str = ""


class LocationInfo(BaseModel):
    name: str = ""
    description: str = ""
    region: str = ""


def _stringify_structured_value(value):
    if isinstance(value, dict):
        parts = []
        for key, val in value.items():
            if isinstance(val, dict):
                sub = ", ".join(f"{k}={sub_v}" for k, sub_v in val.items())
                parts.append(f"{key}: {sub}")
            else:
                parts.append(f"{key}: {val}")
        return "\n".join(parts)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(_stringify_structured_value(item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return value


def _split_name_and_description(text: str) -> tuple[str, str]:
    stripped = (text or "").strip().lstrip("-*•")
    if not stripped:
        return "", ""
    for separator in ("：", ":"):
        if separator in stripped:
            name, desc = stripped.split(separator, 1)
            return name.strip(), desc.strip()
    return stripped, ""


def _coerce_faction_list(value) -> list[FactionInfo]:
    if value in (None, "", []):
        return []
    if isinstance(value, dict):
        if "name" in value:
            return [FactionInfo.model_validate(value)]
        return [
            FactionInfo(name=str(key).strip(), description=_stringify_structured_value(item).strip())
            for key, item in value.items()
            if str(key).strip()
        ]
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, FactionInfo):
                result.append(item)
                continue
            if isinstance(item, dict):
                result.append(FactionInfo.model_validate(item))
                continue
            name, desc = _split_name_and_description(str(item))
            if name:
                result.append(FactionInfo(name=name, description=desc))
        return result

    result = []
    for line in str(value).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rel = ""
        if "与主角关系:" in stripped:
            prefix, suffix = stripped.split("与主角关系:", 1)
            stripped = prefix.rstrip("（）() ").rstrip()
            rel = suffix.rstrip("）)").strip()
        name, desc = _split_name_and_description(stripped)
        if name:
            result.append(
                FactionInfo(name=name, description=desc, relationship_with_protagonist=rel)
            )
    return result


def _coerce_location_list(value) -> list[LocationInfo]:
    if value in (None, "", []):
        return []
    if isinstance(value, dict):
        if "name" in value:
            return [LocationInfo.model_validate(value)]
        return [
            LocationInfo(name=str(key).strip(), description=_stringify_structured_value(item).strip())
            for key, item in value.items()
            if str(key).strip()
        ]
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, LocationInfo):
                result.append(item)
                continue
            if isinstance(item, dict):
                result.append(LocationInfo.model_validate(item))
                continue
            name, desc = _split_name_and_description(str(item))
            if name:
                result.append(LocationInfo(name=name, description=desc))
        return result

    result = []
    for line in str(value).splitlines():
        name, desc = _split_name_and_description(line)
        if name:
            result.append(LocationInfo(name=name, description=desc))
    return result


def _merge_text(current: str, incoming: str) -> str:
    current = (current or "").strip()
    incoming = (incoming or "").strip()
    if not incoming:
        return current
    if not current:
        return incoming
    if incoming in current:
        return current
    if current in incoming:
        return incoming
    return f"{current}\n{incoming}"


def _merge_named_models(items: list[BaseModel], model_cls: type[BaseModel]) -> list[BaseModel]:
    merged: dict[str, BaseModel] = {}
    for item in items:
        if not getattr(item, "name", "").strip():
            continue
        key = item.name.strip()
        if key not in merged:
            merged[key] = item
            continue
        current = merged[key]
        payload = current.model_dump()
        incoming = item.model_dump()
        for field, incoming_value in incoming.items():
            if field == "name":
                continue
            payload[field] = _merge_text(str(payload.get(field, "")), str(incoming_value or ""))
        merged[key] = model_cls.model_validate(payload)
    return list(merged.values())


def _split_text_into_chunks(text: str, max_chars: int = MAX_SINGLE_EXTRACT_CHARS) -> list[str]:
    stripped = (text or "").strip()
    if len(stripped) <= max_chars:
        return [stripped]

    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0
    for line in stripped.splitlines():
        extra = len(line) + 1
        if current_lines and current_len + extra > max_chars:
            chunks.append("\n".join(current_lines).strip())
            current_lines = []
            current_len = 0
        current_lines.append(line)
        current_len += extra
    if current_lines:
        chunks.append("\n".join(current_lines).strip())
    return [chunk for chunk in chunks if chunk]


class ExtractedSetting(BaseModel):
    worldview: Union[str, dict, list] = ""
    power_system: Union[str, dict, list] = ""
    factions: list[FactionInfo] = Field(default_factory=list)
    locations: list[LocationInfo] = Field(default_factory=list)
    character_profiles: List[CharacterProfile] = Field(default_factory=list)
    important_items: List[ImportantItem] = Field(default_factory=list)
    plot_synopsis: Union[str, dict, list] = ""

    @field_validator("worldview", "power_system", "plot_synopsis", mode="before")
    @classmethod
    def _coerce_text_fields(cls, v):
        return _stringify_structured_value(v)

    @field_validator("factions", mode="before")
    @classmethod
    def _coerce_factions(cls, v):
        return _coerce_faction_list(v)

    @field_validator("locations", mode="before")
    @classmethod
    def _coerce_locations(cls, v):
        return _coerce_location_list(v)


class SettingExtractorAgent:
    def _build_prompt(self, text: str) -> str:
        return (
            "你是一位小说设定提取专家。请从以下设定文档中提取结构化信息，"
            "返回严格符合 ExtractedSetting Schema 的 JSON。只提取文档明确写出或强烈暗示的信息，不要自行补完剧情。\n"
            "1. worldview: 世界观概述，保持精炼，抓核心层级、规则、机制\n"
            "2. power_system: 修炼/力量体系，保持精炼，抓核心境界、规则、压制关系\n"
            "3. factions: 势力列表，每项含 name, description, relationship_with_protagonist\n"
            "4. locations: 地点列表，每项含 name, description, region\n"
            "5. character_profiles: 人物列表，每个人物尽量完整填写：\n"
            "   - name: 姓名/称号\n"
            "   - identity: 身份、定位、阵营、叙事功能\n"
            "   - personality: 性格、行为方式、价值观、情绪底色\n"
            "   - goal: 显性目标、长期追求、当前动机\n"
            "   - appearance: 外貌、气质、辨识特征\n"
            "   - background: 出身、前史、重要经历\n"
            "   - ability: 能力、功法、权柄、特长\n"
            "   - realm: 境界、实力层级、修为状态\n"
            "   - relationships: 与主角/其他人物/势力的关系\n"
            "   - resources: 拥有的资源、传承、法宝、身份优势\n"
            "   - secrets: 隐秘身份、未公开目的、伏笔信息\n"
            "   - conflict: 核心矛盾、阻碍、敌对关系\n"
            "   - arc: 人物成长/转变方向\n"
            "   - notes: 其他无法归类但对正文写作有用的信息\n"
            "6. important_items: 重要物品列表（每件含 name, description, significance）\n"
            "7. plot_synopsis: 剧情梗概，保持精炼\n\n"
            "要求：\n"
            "- factions 和 locations 必须返回数组，不要把整张表原样塞进一个长字符串。\n"
            "- 对长文档优先抽取最关键、最可复用的信息，避免逐字复述原文。\n"
            "- 人物字段不要只写一句泛泛概括；同一人物在文档中出现多次时要整合信息。\n"
            "- 没有依据的字段留空字符串，不要编造。\n"
            "- relationships 要优先记录人物之间的具体关系和立场。\n"
            "- ability/realm/resources/secrets/conflict/arc 只要文档有线索就提取。\n\n"
            f"文档内容：\n\n{text}"
        )

    async def _extract_chunk(
        self,
        text: str,
        novel_id: str = "",
        *,
        chunk_index: int = 1,
        total_chunks: int = 1,
    ) -> ExtractedSetting:
        if novel_id and total_chunks > 1:
            log_service.add_log(
                novel_id,
                "SettingExtractorAgent",
                f"开始提取设定分段 {chunk_index}/{total_chunks}，长度: {len(text)} 字",
                event="agent.progress",
                status="started",
                node="setting_extract_chunk",
                task="extract_setting",
                metadata={"chunk_index": chunk_index, "total_chunks": total_chunks, "chars": len(text)},
            )
        prompt = self._build_prompt(text)
        result = await call_and_parse_model(
            "SettingExtractorAgent",
            "extract_setting",
            prompt,
            ExtractedSetting,
            max_retries=3,
            novel_id=novel_id,
        )
        if novel_id and total_chunks > 1:
            log_service.add_log(
                novel_id,
                "SettingExtractorAgent",
                f"设定分段 {chunk_index}/{total_chunks} 提取完成",
                event="agent.progress",
                status="succeeded",
                node="setting_extract_chunk",
                task="extract_setting",
                metadata={
                    "chunk_index": chunk_index,
                    "total_chunks": total_chunks,
                    "chars": len(text),
                    "factions": len(result.factions),
                    "locations": len(result.locations),
                    "characters": len(result.character_profiles),
                    "items": len(result.important_items),
                },
            )
        return result

    def _merge_results(self, parts: list[ExtractedSetting]) -> ExtractedSetting:
        worldview = ""
        power_system = ""
        plot_synopsis = ""
        factions: list[FactionInfo] = []
        locations: list[LocationInfo] = []
        characters: list[CharacterProfile] = []
        items: list[ImportantItem] = []

        for part in parts:
            worldview = _merge_text(worldview, str(part.worldview or ""))
            power_system = _merge_text(power_system, str(part.power_system or ""))
            plot_synopsis = _merge_text(plot_synopsis, str(part.plot_synopsis or ""))
            factions.extend(part.factions)
            locations.extend(part.locations)
            characters.extend(part.character_profiles)
            items.extend(part.important_items)

        return ExtractedSetting(
            worldview=worldview,
            power_system=power_system,
            factions=_merge_named_models(factions, FactionInfo),
            locations=_merge_named_models(locations, LocationInfo),
            character_profiles=_merge_named_models(characters, CharacterProfile),
            important_items=_merge_named_models(items, ImportantItem),
            plot_synopsis=plot_synopsis,
        )

    @logged_agent_step("SettingExtractorAgent", "提取设定", node="setting_extract", task="extract_setting")
    async def extract(self, text: str, novel_id: str = "") -> ExtractedSetting:
        if novel_id:
            log_service.add_log(
                novel_id,
                "SettingExtractorAgent",
                f"开始提取设定，文本长度: {len(text)} 字",
            )

        chunks = _split_text_into_chunks(text, max_chars=MAX_SINGLE_EXTRACT_CHARS)
        if novel_id and len(chunks) > 1:
            log_service.add_log(
                novel_id,
                "SettingExtractorAgent",
                f"长文档分段提取: {len(chunks)} 段，并发 {min(MAX_PARALLEL_EXTRACT_CHUNKS, len(chunks))} 路",
                event="agent.progress",
                status="started",
                node="setting_extract_split",
                task="extract_setting",
                metadata={
                    "total_chunks": len(chunks),
                    "max_chunk_chars": MAX_SINGLE_EXTRACT_CHARS,
                    "parallelism": min(MAX_PARALLEL_EXTRACT_CHUNKS, len(chunks)),
                    "chunk_lengths": [len(chunk) for chunk in chunks],
                },
            )

        if len(chunks) == 1:
            extracted_parts = [await self._extract_chunk(chunks[0], novel_id)]
        else:
            semaphore = asyncio.Semaphore(MAX_PARALLEL_EXTRACT_CHUNKS)

            async def extract_limited(index: int, chunk: str) -> ExtractedSetting:
                async with semaphore:
                    return await self._extract_chunk(
                        chunk,
                        novel_id,
                        chunk_index=index + 1,
                        total_chunks=len(chunks),
                    )

            extracted_parts = await asyncio.gather(
                *(extract_limited(index, chunk) for index, chunk in enumerate(chunks))
            )

        result = extracted_parts[0] if len(extracted_parts) == 1 else self._merge_results(extracted_parts)
        if novel_id:
            log_service.add_log(
                novel_id,
                "SettingExtractorAgent",
                "设定提取完成: "
                f"势力 {len(result.factions)} 个, 地点 {len(result.locations)} 个, "
                f"人物 {len(result.character_profiles)} 个, 物品 {len(result.important_items)} 个",
            )
        return result
