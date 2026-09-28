"""
Displacement engine — the heart of Oracle X (spec section 3).
Given a leading asset's move and a lagging asset's historical conditional
reaction, computes the "underreaction gap" that becomes the alpha signal.
"""
import numpy as np
import pandas as pd


def expected_reaction(
    leader_move_pct: float,
    historical_pairs: pd.DataFrame,
) -> tuple[float, float]:
    """
    historical_pairs: DataFrame with columns ['leader_move_pct', 'follower_move_pct']
    from past analogous events. Fits a simple linear relationship
    (follower ~ beta * leader) and returns (expected_follower_move_pct, r_squared).
    Deliberately simple/interpretable over a black-box model — this needs to
    be explainable in the Opportunity Card, not just accurate.
    """
    if len(historical_pairs) < 5:
        return 0.0, 0.0

    x = historical_pairs["leader_move_pct"].values
    y = historical_pairs["follower_move_pct"].values
    beta, alpha = np.polyfit(x, y, 1)

    expected = beta * leader_move_pct + alpha

    y_pred = beta * x + alpha
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return float(expected), float(r_squared)


def displacement_gap(expected_move_pct: float, current_move_pct: float) -> float:
    """The 'estimated edge' — how far the follower asset is from its expected move."""
    return round(expected_move_pct - current_move_pct, 4)


def displacement_zscore(gap: float, historical_gaps: pd.Series) -> float:
    """
    How unusual is this displacement gap relative to history? Used to avoid
    treating normal noise as a signal (part of Risk Guardian's volatility check
    and the Alpha Score's displacement factor).
    """
    if len(historical_gaps) < 10:
        return 0.0
    mean, std = historical_gaps.mean(), historical_gaps.std()
    if std == 0:
        return 0.0
    return float((gap - mean) / std)
