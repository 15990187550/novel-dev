import pytest
from novel_dev.config.ab_judge_config import get_ab_judge_config, JudgeConfig


def test_returns_default_when_no_yaml():
    cfg = get_ab_judge_config()
    assert isinstance(cfg, JudgeConfig)
    assert cfg.enabled is True
    assert cfg.tie_threshold_pct == 1.0
    assert cfg.model_default == "claude-sonnet-4-6"
    assert cfg.max_cost_per_decision_usd == 0.05
    assert cfg.max_cost_per_experiment_usd == 0.50
    assert cfg.max_latency_ms == 10000
    assert cfg.max_rationale_chars == 200
    assert cfg.clear_cut_threshold_pct == 5.0
    assert cfg.min_samples == 30
    assert cfg.calibration_window_days == 14


def test_yaml_overrides_take_effect(tmp_path, monkeypatch):
    yaml_path = tmp_path / "llm_config.yaml"
    yaml_path.write_text("""
ab_acceptance:
  judge:
    enabled: false
    model_default: claude-opus-4-7
    max_cost_per_decision_usd: 0.10
    meta_eval:
      min_samples: 50
""")
    monkeypatch.chdir(tmp_path)
    cfg = get_ab_judge_config()
    assert cfg.enabled is False
    assert cfg.model_default == "claude-opus-4-7"
    assert cfg.max_cost_per_decision_usd == 0.10
    assert cfg.min_samples == 50
    # 其他字段保留默认
    assert cfg.tie_threshold_pct == 1.0
