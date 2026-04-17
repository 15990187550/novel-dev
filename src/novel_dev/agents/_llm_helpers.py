import asyncio
from typing import Callable, TypeVar

from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage
from pydantic import ValidationError
import json

T = TypeVar("T")


async def call_and_parse(
    agent_name: str,
    task: str,
    prompt: str,
    parser: Callable[[str], T],
    max_retries: int = 3,
) -> T:
    client = llm_factory.get(agent_name, task=task)
    last_error = None
    for attempt in range(max_retries):
        try:
            response = await client.acomplete([ChatMessage(role="user", content=prompt)])
            return parser(response.text)
        except (ValidationError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
    raise RuntimeError(
        f"LLM parse failed after {max_retries} retries for {agent_name}/{task}: {last_error}"
    ) from last_error
