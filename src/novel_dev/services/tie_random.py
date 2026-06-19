from __future__ import annotations
import hashlib
from typing import Sequence


def tie_random_pick(experiment_id: str, candidates: Sequence[str]) -> str:
    """基于 experiment_id 哈希的 deterministic 随机选择。

    用于 judge 失败时 tie 决策的回退路径。同一 experiment_id 总是返回同一 candidate,
    便于调试和复现。
    """
    if not candidates:
        raise ValueError("candidates must be non-empty")
    seed = int(hashlib.sha256(experiment_id.encode()).hexdigest()[:8], 16)
    return candidates[seed % len(candidates)]
