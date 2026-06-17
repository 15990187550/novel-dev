import pytest


def test_phase4_config_loads(monkeypatch):
    from novel_dev.config.quality_config import get_phase4_config
    cfg = get_phase4_config()
    assert "rcs" in cfg
    assert cfg["rcs"]["trigger_window_chapters"] == 5
    assert "web_novel" in cfg
    assert "writer" in cfg
    assert cfg["writer"]["default_drafting_mode"] == "beat_by_beat"


def test_phase4_config_missing_raises(monkeypatch):
    def bad():
        return {}
    monkeypatch.setattr("novel_dev.config.quality_config.get_llm_config", bad)
    from novel_dev.config.quality_config import get_phase4_config
    with pytest.raises(KeyError):
        get_phase4_config()