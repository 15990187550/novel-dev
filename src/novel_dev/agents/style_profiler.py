import math
from collections import Counter
from typing import List
from pydantic import BaseModel


class StyleConfig(BaseModel):
    sentence_patterns: dict = {}
    dialogue_style: dict = {}
    rhetoric_devices: dict = {}
    pacing: str = ""
    vocabulary_preferences: List[str] = []
    perspective: str = ""
    tone: str = ""
    evolution_notes: str = ""


class StyleProfile(BaseModel):
    style_guide: str
    style_config: StyleConfig


class StyleProfilerAgent:
    CHUNK_SIZE = 3000
    MIN_SAMPLES = 8
    MAX_SAMPLES = 24
    SAMPLE_RATIO = 0.5

    def _chunk_text(self, text: str, chunk_size: int = CHUNK_SIZE) -> List[str]:
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    def _sample_chunks(self, chunks: List[str]) -> List[str]:
        total = len(chunks)
        if total == 0:
            return []
        target = max(self.MIN_SAMPLES, min(self.MAX_SAMPLES, math.ceil(total * self.SAMPLE_RATIO)))
        target = min(target, total)

        if total <= target:
            return chunks

        step = total / target
        sampled = []
        for i in range(target):
            idx = min(int(i * step), total - 1)
            sampled.append(chunks[idx])
        return sampled

    async def profile(self, text: str) -> StyleProfile:
        chunks = self._chunk_text(text)
        sampled = self._sample_chunks(chunks)

        # Prototype: simple heuristic analysis without LLM
        config = StyleConfig(
            sentence_patterns={"avg_length": self._avg_sentence_length(text)},
            dialogue_style={"direct_speech_ratio": self._dialogue_ratio(text)},
            rhetoric_devices={},
            pacing="fast" if len(sampled) > 10 else "moderate",
            vocabulary_preferences=self._extract_vocabulary(text),
            perspective="limited" if "他" in text or "她" in text else "omniscient",
            tone="intense" if "杀" in text or "血" in text or "剑" in text else "neutral",
            evolution_notes="",
        )

        guide = (
            f"Overall: {config.pacing} pacing, "
            f"{config.perspective} perspective, "
            f"{config.tone} tone. "
            f"Samples analyzed: {len(sampled)} chunks."
        )

        return StyleProfile(style_guide=guide, style_config=config)

    def _avg_sentence_length(self, text: str) -> float:
        sentences = [s.strip() for s in text.replace("。", ".").replace("！", "!").replace("？", "?").split(".") if s.strip()]
        if not sentences:
            return 0.0
        return sum(len(s) for s in sentences) / len(sentences)

    def _dialogue_ratio(self, text: str) -> float:
        quotes = text.count('"') + text.count("'") + text.count("“") + text.count("”")
        return round(quotes / max(len(text), 1), 3)

    def _extract_vocabulary(self, text: str) -> List[str]:
        # Simple high-frequency bigrams
        words = list(text)
        bigrams = [words[i] + words[i + 1] for i in range(len(words) - 1)]
        freq = Counter(bigrams)
        return [bg for bg, _ in freq.most_common(5)]
