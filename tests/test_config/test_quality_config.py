import pytest
from novel_dev.config.quality_config import (
    get_quality_config,
    get_issue_code_hints,
    ConfigError,
)


def test_quality_config_loads_thresholds(tmp_path, monkeypatch):
    yaml_path = tmp_path / "llm_config.yaml"
    yaml_path.write_text("""
quality_thresholds:
  publishable_final_review_score: 82
  critical_dimension_min_score: 75
  judge_consistency:
    stable_max_cv: 0.05
    moderate_max_cv: 0.10
  recommendation:
    block_threshold: 60
    minor_repair_min_score: 78
    minor_repair_min_critical: 72
    major_repair_min_score: 70
    stop_after_attempts: 3
    pattern_issue_threshold: 3
""")
    monkeypatch.setattr("novel_dev.config.quality_config._CONFIG_PATH", yaml_path)
    get_quality_config.cache_clear()
    cfg = get_quality_config()
    assert cfg["publishable_final_review_score"] == 82
    assert cfg["recommendation"]["stop_after_attempts"] == 3


def test_quality_config_fails_loud_on_missing_key(tmp_path, monkeypatch):
    yaml_path = tmp_path / "llm_config.yaml"
    yaml_path.write_text("quality_thresholds:\n  publishable_final_review_score: 82\n")
    monkeypatch.setattr("novel_dev.config.quality_config._CONFIG_PATH", yaml_path)
    get_quality_config.cache_clear()
    with pytest.raises(ConfigError, match="critical_dimension_min_score"):
        get_quality_config()


def test_quality_config_includes_max_auto_rewrites():
    cfg = get_quality_config()
    assert "max_auto_rewrites" in cfg["recommendation"]
    assert isinstance(cfg["recommendation"]["max_auto_rewrites"], int)


def test_issue_code_hints_returns_empty_dict_when_absent(tmp_path, monkeypatch):
    yaml_path = tmp_path / "llm_config.yaml"
    yaml_path.write_text("quality_thresholds: {}\n")
    monkeypatch.setattr("novel_dev.config.quality_config._CONFIG_PATH", yaml_path)
    get_issue_code_hints.cache_clear()
    assert get_issue_code_hints() == {}