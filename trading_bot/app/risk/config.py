"""Builds a RiskLimits from the app's real configuration sources: the
existing .env-backed Settings (Stage 1) plus config/risk_limits.yaml
(Stage 4). Kept separate from app/risk/limits.py and app/risk/engine.py so
those stay import-free of app.config -- this is the only file in app/risk
that touches the wider app.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from app.config import Settings
from app.risk.limits import RiskLimits

DEFAULT_RISK_LIMITS_YAML = Path("config/risk_limits.yaml")


def load_risk_limits(settings: Settings, yaml_path: Path = DEFAULT_RISK_LIMITS_YAML) -> RiskLimits:
    yaml_values: dict = {}
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_values = yaml.safe_load(f) or {}

    return RiskLimits(
        max_position_pct=settings.max_position_pct,
        max_daily_loss_pct=settings.max_daily_loss_pct,
        max_weekly_loss_pct=settings.max_weekly_loss_pct,
        max_drawdown_pct=settings.max_drawdown_pct,
        allow_leverage=settings.allow_leverage,
        max_leverage=settings.max_leverage,
        max_correlation=yaml_values.get("max_correlation", RiskLimits.max_correlation),
        max_correlated_group_pct=yaml_values.get(
            "max_correlated_group_pct", RiskLimits.max_correlated_group_pct
        ),
        max_add_to_loser_pct=yaml_values.get(
            "max_add_to_loser_pct", RiskLimits.max_add_to_loser_pct
        ),
    )
