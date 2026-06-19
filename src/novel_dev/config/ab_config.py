from __future__ import annotations
from typing import Any


DEFAULTS = {
    "sweep_interval_minutes": 5,
    "early_stop_consecutive_loss": 3,
    "early_stop_min_lift": -0.10,
    "timeout_days": 7,
    "monitoring_hours": 24,
    "rollback_drop_threshold": 0.05,
    "default_weights": {"critic": 0.5, "hook": 0.3, "thrill": 0.2},
    "max_weight_drift": 0.2,
    "weight_update_interval": 50,
}


def get_ab_auto_acceptance_config() -> dict[str, Any]:
    try:
        import yaml
        with open("llm_config.yaml") as f:
            data = yaml.safe_load(f) or {}
        overrides = data.get("ab_auto_acceptance", {})
    except Exception:
        overrides = {}
    merged = {**DEFAULTS, **overrides}
    return merged
