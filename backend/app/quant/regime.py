"""
Market regime classifier — feeds the dashboard's regime badge and the
Alpha Score's market_regime factor. Uses BTC + QQQ as risk-appetite proxies
(crypto and tech-equity beta are the two fastest risk-on/off signals
available without a full macro data feed).
"""
import numpy as np
import pandas as pd


def classify_regime(btc_close: pd.Series, qqq_close: pd.Series, window: int = 24) -> dict:
    """
    Returns {"regime": "RISK_ON"|"RISK_OFF"|"NEUTRAL", "score": -1..1,
    "btc_trend": float, "qqq_trend": float}.
    """
    if len(btc_close) < window + 1 or len(qqq_close) < window + 1:
        return {"regime": "NEUTRAL", "score": 0.0, "btc_trend": 0.0, "qqq_trend": 0.0}

    btc_trend = float(btc_close.iloc[-1] / btc_close.iloc[-window] - 1)
    qqq_trend = float(qqq_close.iloc[-1] / qqq_close.iloc[-window] - 1)

    score = float(np.tanh((btc_trend + qqq_trend) * 5))

    if score > 0.15:
        regime = "RISK_ON"
    elif score < -0.15:
        regime = "RISK_OFF"
    else:
        regime = "NEUTRAL"

    return {"regime": regime, "score": score, "btc_trend": btc_trend, "qqq_trend": qqq_trend}


def regime_factor_for_alpha(regime: dict) -> float:
    """Maps regime score to a 0..1 factor input for the Alpha Score."""
    return float((regime["score"] + 1) / 2)
