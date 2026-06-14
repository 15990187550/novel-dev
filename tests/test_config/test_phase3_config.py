import pytest


def test_phase3_config_loads():
    from novel_dev.config.quality_config import get_phase3_config
    cfg = get_phase3_config()
    assert "root_cause_analyzer" in cfg
    assert cfg["ab_test"]["default_max_samples"] == 10
    assert cfg["prompt_registry"]["bootstrap_default"] is True


def test_phase3_config_missing_raises(monkeypatch):
    def bad():
        return {}
    monkeypatch.setattr("novel_dev.config.quality_config.get_llm_config", bad)
    from novel_dev.config.quality_config import get_phase3_config
    with pytest.raises(KeyError):
        get_phase3_config()
