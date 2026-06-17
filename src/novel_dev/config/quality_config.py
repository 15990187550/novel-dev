"""Centralized loader for quality thresholds and issue-code hints.

Fail loud on missing required keys — better to crash at startup than
silently use stale defaults during a generation run.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "llm_config.yaml"

_REQUIRED_THRESHOLD_KEYS = (
    "publishable_final_review_score",
    "critical_dimension_min_score",
    "judge_consistency",
    "recommendation",
)


class ConfigError(Exception):
    pass


@lru_cache(maxsize=1)
def get_llm_config() -> dict[str, Any]:
    return _load_yaml()


@lru_cache(maxsize=1)
def get_quality_config() -> dict[str, Any]:
    config = _load_yaml()
    quality = config.get("quality_thresholds", {})
    for key in _REQUIRED_THRESHOLD_KEYS:
        if key not in quality:
            raise ConfigError(
                f"Missing required key quality_thresholds.{key} in llm_config.yaml"
            )
    return quality


@lru_cache(maxsize=1)
def get_issue_code_hints() -> dict[str, Any]:
    config = _load_yaml()
    return config.get("issue_code_hints", {})


def get_phase3_config() -> dict:
    cfg = get_llm_config()
    if "phase3" not in cfg:
        raise KeyError("Missing required section: phase3")
    return cfg["phase3"]


def get_phase4_config() -> dict:
    cfg = get_llm_config()
    if "phase4" not in cfg:
        raise KeyError("Missing required section: phase4")
    return cfg["phase4"]


def _load_yaml() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        raise ConfigError(f"llm_config.yaml not found at {_CONFIG_PATH}")
    with _CONFIG_PATH.open() as f:
        return yaml.safe_load(f) or {}