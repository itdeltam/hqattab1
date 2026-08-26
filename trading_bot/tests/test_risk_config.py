from pathlib import Path

import pytest

from app.config import Settings
from app.risk.config import load_risk_limits


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        max_position_pct=0.12,
        max_daily_loss_pct=0.03,
        max_weekly_loss_pct=0.06,
        max_drawdown_pct=0.20,
        allow_leverage=True,
        max_leverage=1.5,
    )


def test_loads_env_backed_fields_from_settings(settings, tmp_path):
    limits = load_risk_limits(settings, yaml_path=tmp_path / "nonexistent.yaml")

    assert limits.max_position_pct == 0.12
    assert limits.max_daily_loss_pct == 0.03
    assert limits.max_weekly_loss_pct == 0.06
    assert limits.max_drawdown_pct == 0.20
    assert limits.allow_leverage is True
    assert limits.max_leverage == 1.5


def test_missing_yaml_file_falls_back_to_defaults(settings, tmp_path):
    limits = load_risk_limits(settings, yaml_path=tmp_path / "nonexistent.yaml")

    assert limits.max_correlation == 0.70
    assert limits.max_correlated_group_pct == 0.25
    assert limits.max_add_to_loser_pct == 0.05


def test_yaml_values_override_defaults(settings, tmp_path):
    yaml_path = tmp_path / "risk_limits.yaml"
    yaml_path.write_text(
        "max_correlation: 0.85\nmax_correlated_group_pct: 0.30\nmax_add_to_loser_pct: 0.08\n"
    )

    limits = load_risk_limits(settings, yaml_path=yaml_path)

    assert limits.max_correlation == 0.85
    assert limits.max_correlated_group_pct == 0.30
    assert limits.max_add_to_loser_pct == 0.08


def test_empty_yaml_file_falls_back_to_defaults(settings, tmp_path):
    yaml_path = tmp_path / "risk_limits.yaml"
    yaml_path.write_text("")

    limits = load_risk_limits(settings, yaml_path=yaml_path)

    assert limits.max_correlation == 0.70


def test_real_config_risk_limits_yaml_loads_cleanly(settings):
    real_path = Path("config/risk_limits.yaml")
    limits = load_risk_limits(settings, yaml_path=real_path)

    assert 0 < limits.max_correlation <= 1
    assert 0 < limits.max_correlated_group_pct <= 1
    assert 0 < limits.max_add_to_loser_pct <= 1
