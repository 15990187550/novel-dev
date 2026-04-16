import re
from typing import Dict, List


class LibrarianAgent:
    """Prototype rule-based extractor for entities, timeline, and foreshadowings."""

    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        # Naive heuristics for prototype; production will use LLM extraction
        # Capitalized consecutive words assumed as proper nouns
        candidates = re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+', text)
        # Simple classification heuristics for Chinese/English mixed
        characters = []
        items = []
        locations = []
        concepts = []

        for cand in candidates:
            lower = cand.lower()
            if any(x in lower for x in ["sect", "mountain", "city", "valley", "peak"]):
                locations.append(cand)
            elif any(x in lower for x in ["sword", "pill", "jade", "ring", "armor"]):
                items.append(cand)
            else:
                characters.append(cand)

        return {
            "characters": list(set(characters)),
            "items": list(set(items)),
            "locations": list(set(locations)),
            "concepts": list(set(concepts)),
        }

    def extract_time_progress(self, text: str) -> Dict:
        # Placeholder heuristic: look for "three days later" patterns
        return {"detected_time_phrases": re.findall(r'\d+\s+days?\s+later', text, re.IGNORECASE)}

    def extract_foreshadowing_clues(self, text: str) -> List[str]:
        # Look for sentences with question marks or mysterious descriptions
        sentences = re.split(r'[.!?。！？]', text)
        clues = [s.strip() for s in sentences if "?" in s or "mysterious" in s.lower()]
        return clues
