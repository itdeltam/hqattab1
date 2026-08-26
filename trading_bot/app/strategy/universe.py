"""The Stage 2 research notebook's recommended v1 universe (see
research/stage2_strategy_math_spec.ipynb, section 1): a fixed basket of
liquid, diversified US sector/asset-class ETFs, not individual equities --
diversification by construction, no single-name risk, deep liquidity and
clean corporate actions, and a trivial defensive leg via SHY (which also
doubles as StrategyParams.defensive_asset).
"""
from __future__ import annotations

DEFAULT_UNIVERSE: tuple[str, ...] = (
    # 11 SPDR sector ETFs
    "XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    # Broad market
    "SPY", "QQQ", "IWM",
    # International
    "EFA", "EEM",
    # Bonds / rates -- SHY is also the strategy's defensive fallback asset
    "TLT", "IEF", "SHY",
    # Alternatives
    "GLD", "DBC", "VNQ",
)
