from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from novel_dev.config.ab_judge_config import JudgeConfig
from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage
from novel_dev.repositories.judge_prompt_version_repo import JudgePromptVersionRepository
from novel_dev.repositories.judge_call_log_repo import JudgeCallLogRepository


class JudgeParseError(Exception):
    pass


class NoActiveVersionError(Exception):
    pass


@dataclass
class JudgeResult:
    scores: dict[str, float]          # {"口吻": 7.5, "叙事连贯": 8.0, "风格调性": 6.5}
    rationale: str
    tie_breaker: float               # mean(3 dims),0-10
    call_log_id: str
    model: str
    prompt_version_id: str


class JudgeAgent:
    REQUIRED_DIMS = ("口吻", "叙事连贯", "风格调性")
    DIM_MIN, DIM_MAX = 0.0, 10.0

    def __init__(self, session: AsyncSession, config: JudgeConfig):
        self.session = session
        self.config = config
        self.pv_repo = JudgePromptVersionRepository(session)
        self.call_log_repo = JudgeCallLogRepository(session)

    async def judge_sample(
        self,
        chapter_text: str,
        version_id: Optional[str] = None,
        decision_id: Optional[str] = None,
        experiment_id: Optional[str] = None,
    ) -> JudgeResult:
        if not isinstance(chapter_text, str) or not chapter_text.strip():
            raise ValueError("chapter_text must be a non-empty string")

        # 1. 解析 prompt version
        if version_id is not None:
            pv = await self.pv_repo.get_by_id(version_id)
            if pv is None:
                raise NoActiveVersionError(f"version_id {version_id} not found")
        else:
            pv = await self.pv_repo.get_active()
            if pv is None:
                raise NoActiveVersionError("no active judge_prompt_versions row")

        # 2. 构造 prompt
        prompt = self._render_prompt(pv.prompt_text, chapter_text)

        # 3. 调 LLM
        client = llm_factory.get("JudgeAgent", task="judge_score")
        # 注:Phase 5 模式里 config 是第二个位置参数
        from novel_dev.llm.models import TaskConfig  # 延迟导入避免循环
        llm_config = TaskConfig(model=self.config.model_default, temperature=0.2)
        start = time.monotonic()
        response = await client.acomplete([ChatMessage(role="user", content=prompt)], llm_config)
        latency_ms = int((time.monotonic() - start) * 1000)

        # 4. 解析
        raw_text = self._extract_response_text(response)
        data = self._parse_response(raw_text)

        # 5. 截断理由
        rationale = str(data.get("理由", ""))[: self.config.max_rationale_chars]

        # 6. 计算 tie_breaker
        scores = {dim: float(data[dim]) for dim in self.REQUIRED_DIMS}
        tie_breaker = sum(scores.values()) / len(scores)

        # 7. 写 call log
        input_tokens = len(prompt) // 4  # 粗略估算
        output_tokens = len(raw_text) // 4
        cost_usd = self._estimate_cost(input_tokens, output_tokens)
        log = await self.call_log_repo.log(
            decision_id=decision_id,
            experiment_id=experiment_id,
            prompt_version_id=pv.id,
            model=self.config.model_default,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )

        return JudgeResult(
            scores=scores,
            rationale=rationale,
            tie_breaker=tie_breaker,
            call_log_id=log.id,
            model=self.config.model_default,
            prompt_version_id=pv.id,
        )

    def _render_prompt(self, template: str, chapter_text: str) -> str:
        try:
            return template.format(chapter_text=chapter_text)
        except KeyError:
            # 模板里没有 {chapter_text} 占位符时,降级到字符串拼接
            return template + "\n\n## 待评审章节\n" + chapter_text

    @staticmethod
    def _extract_response_text(response) -> str:
        """兼容 LLMResponse(.text) 和 ChatMessage(.content)。"""
        text = getattr(response, "text", None)
        if text is not None:
            return text
        content = getattr(response, "content", None)
        if content is not None:
            return content
        return str(response)

    def _parse_response(self, content: str) -> dict:
        raw = self._strip_markdown_fences(content)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = self._extract_first_json_block(raw)
            if data is None:
                raise JudgeParseError(f"无法解析 judge 输出: {content[:200]}")

        for dim in self.REQUIRED_DIMS:
            if dim not in data or not isinstance(data[dim], (int, float)):
                raise JudgeParseError(f"缺失或非数值维度: {dim}")
            if not (self.DIM_MIN <= float(data[dim]) <= self.DIM_MAX):
                raise JudgeParseError(f"维度超界: {dim}={data[dim]}")
        return data

    @staticmethod
    def _strip_markdown_fences(content: str) -> str:
        s = content.strip()
        if s.startswith("```"):
            # remove first fence line
            lines = s.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            return "\n".join(lines).strip()
        return s

    @staticmethod
    def _extract_first_json_block(content: str) -> Optional[dict]:
        m = re.search(r"\{[^{}]*\"口吻\"[^{}]*\}", content, re.DOTALL)
        if m is None:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
        """Sonnet 级模型粗略估算(input $3/1M, output $15/1M)。"""
        return (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000