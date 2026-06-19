from novel_dev.config.ab_config import get_ab_auto_acceptance_config


def test_default_config_has_required_keys():
    cfg = get_ab_auto_acceptance_config()
    assert cfg["sweep_interval_minutes"] == 5
    assert cfg["early_stop_consecutive_loss"] == 3
    assert cfg["early_stop_min_lift"] == -0.10
    assert cfg["timeout_days"] == 7
    assert cfg["monitoring_hours"] == 24
    assert cfg["rollback_drop_threshold"] == 0.05
    assert cfg["default_weights"]["critic"] == 0.5