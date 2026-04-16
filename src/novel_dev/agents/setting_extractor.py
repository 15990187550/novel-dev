import re
from typing import List, Optional
from pydantic import BaseModel


class CharacterProfile(BaseModel):
    name: str
    identity: str = ""
    personality: str = ""
    goal: str = ""


class ImportantItem(BaseModel):
    name: str
    description: str = ""
    significance: str = ""


class ExtractedSetting(BaseModel):
    worldview: str = ""
    power_system: str = ""
    factions: str = ""
    character_profiles: List[CharacterProfile] = []
    important_items: List[ImportantItem] = []
    plot_synopsis: str = ""


class SettingExtractorAgent:
    async def extract(self, text: str) -> ExtractedSetting:
        # Naive regex-based extraction for prototype
        worldview = self._extract_section(text, ["世界观", "worldview", "世界"])
        power_system = self._extract_section(text, ["修炼体系", "power system", "境界", " cultivation"])
        factions = self._extract_section(text, ["势力", "factions", "宗门", "门派"])
        plot_synopsis = self._extract_section(text, ["剧情", "plot", "大纲", "synopsis"])

        characters = self._extract_characters(text)
        items = self._extract_items(text)

        return ExtractedSetting(
            worldview=worldview,
            power_system=power_system,
            factions=factions,
            character_profiles=characters,
            important_items=items,
            plot_synopsis=plot_synopsis,
        )

    def _extract_section(self, text: str, headers: List[str]) -> str:
        for header in headers:
            pattern = re.compile(rf"{re.escape(header)}[：:\s]+([^\n]+)", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                return match.group(1).strip()
        return ""

    def _extract_characters(self, text: str) -> List[CharacterProfile]:
        chars = []
        # Match lines like: 主角林风，青云宗外门弟子，性格坚韧隐忍，目标为父报仇。
        pattern = re.compile(r"(?:主角|人物)[：:\s]*(\S+?)[，,、]\s*(.+?)(?=\n|。|$)")
        for name, rest in pattern.findall(text):
            chars.append(CharacterProfile(name=name, identity=rest))
        return chars

    def _extract_items(self, text: str) -> List[ImportantItem]:
        items = []
        pattern = re.compile(r"重要物品[：:]\s*(\S+?)[，,、]\s*(.+?)(?=\n|。|$)")
        for name, rest in pattern.findall(text):
            items.append(ImportantItem(name=name, description=rest))
        return items
