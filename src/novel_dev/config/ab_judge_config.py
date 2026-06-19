from __future__ import annotations
from dataclasses import dataclass
from typing import Any


DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "tie_threshold_pct": 1.0,
    "model_default": "claude-sonnet-4-6",
    "max_cost_per_decision_usd": 0.05,
    "max_cost_per_experiment_usd": 0.50,
    "max_latency_ms": 10000,
    "max_rationale_chars": 200,
    "clear_cut_threshold_pct": 5.0,
    "min_samples": 30,
    "calibration_window_days": 14,
}


@dataclass(frozen=True)
class JudgeConfig:
    enabled: bool = True
    tie_threshold_pct: float = 1.0
    model_default: str = "claude-sonnet-4-6"
    max_cost_per_decision_usd: float = 0.05
    max_cost_per_experiment_usd: float = 0.50
    max_latency_ms: int = 10000
    max_rationale_chars: int = 200
    clear_cut_threshold_pct: float = 5.0
    min_samples: int = 30
    calibration_window_days: int = 14

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JudgeConfig":
        return cls(
            enabled=bool(data.get("enabled", DEFAULTS["enabled"])),
            tie_threshold_pct=float(data.get("tie_threshold_pct", DEFAULTS["tie_threshold_pct"])),
            model_default=str(data.get("model_default", DEFAULTS["model_default"])),
            max_cost_per_decision_usd=float(data.get("max_cost_per_decision_usd", DEFAULTS["max_cost_per_decision_usd"])),
            max_cost_per_experiment_usd=float(data.get("max_cost_per_experiment_usd", DEFAULTS["max_cost_per_experiment_usd"])),
            max_latency_ms=int(data.get("max_latency_ms", DEFAULTS["max_latency_ms"])),
            max_rationale_chars=int(data.get("max_rationale_chars", DEFAULTS["max_rationale_chars"])),
            clear_cut_threshold_pct=float(data.get("clear_cut_threshold_pct", DEFAULTS["clear_cut_threshold_pct"])),
            min_samples=int(data.get("min_samples", DEFAULTS["min_samples"])),
            calibration_window_days=int(data.get("calibration_window_days", DEFAULTS["calibration_window_days"])),
        )


def get_ab_judge_config() -> JudgeConfig:
    """从 llm_config.yaml 读取 ab_acceptance.judge 配置,缺省回退到 DEFAULTS。"""
    try:
        import yaml
        with open("llm_config.yaml") as f:
            data = yaml.safe_load(f) or {}
        judge_section = (
            data.get("ab_acceptance", {}).get("judge", {})
        )
        # merge meta_eval 子段
        meta_eval = judge_section.pop("meta_eval", {}) if "meta_eval" in judge_section else {}
        merged = {**DEFAULTS, **judge_section, **meta_eval}
    except Exception:
        merged = DEFAULTS.copy()
    return JudgeConfig.from_dict(merged)
