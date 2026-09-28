"""
Correlation + lead/lag engine. Feeds the `relationships` table and the
Relationship Hunter agent. Real pandas/numpy math — no stubs.
"""
import numpy as np
import pandas as pd


def rolling_correlation(series_a: pd.Series, series_b: pd.Series, window: int = 30) -> pd.Series:
    """Rolling Pearson correlation of two return series, aligned on timestamp index."""
    returns_a = series_a.pct_change()
    returns_b = series_b.pct_change()
    return returns_a.rolling(window).corr(returns_b)


def lead_lag_hours(series_a: pd.Series, series_b: pd.Series, max_lag: int = 24) -> tuple[float, float]:
    """
    Cross-correlation at multiple lags to find how many hours A leads B
    (positive = A leads B by that many hours, negative = B leads A).
    Series must be hourly-indexed price series (not yet differenced —
    this function takes the pct_change itself, same as rolling_correlation).

    Sign convention, confirmed by direct simulation rather than assumed
    (see PR/commit notes): pandas' `series.shift(k)` sets
    `shifted[t] = series[t-k]`. So for a lag k, we correlate
    `returns_a[t]` against `returns_b[t-k]`. If A truly leads B by n
    periods (B's move at t mirrors A's move at t-n), the maximizing k in
    that raw correlation is k=-n, NOT k=+n — verified with a synthetic
    series where B[t] = A[t-2] + noise, which peaks at k=-2. The loop
    below negates the raw result so the function's *return value* matches
    its documented, intuitive contract (positive = A leads B) rather than
    forcing every caller to remember to flip the sign themselves.
    """
    returns_a = series_a.pct_change().dropna()
    returns_b = series_b.pct_change().dropna()

    best_lag: int = 0
    best_corr: float | None = None
    for lag in range(-max_lag, max_lag + 1):
        shifted_b = returns_b.shift(lag)
        aligned = pd.concat([returns_a, shifted_b], axis=1).dropna()
        if len(aligned) < 10:
            continue
        corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
        if corr is None or pd.isna(corr):
            continue
        if best_corr is None or abs(corr) > abs(best_corr):
            best_lag, best_corr = lag, float(corr)
    # Negate: see docstring — the raw loop finds k such that
    # corr(a[t], b[t-k]) is maximal, which means "B leads A by k" when
    # k>0, the opposite of this function's documented positive-lag meaning.
    return float(-best_lag), float(best_corr) if best_corr is not None else 0.0


def correlation_shift(series_a: pd.Series, series_b: pd.Series, event_timestamp, window_hours: int = 48):
    """
    Before/after correlation shift around an event (spec section 9,
    'What Changed?'). Returns (corr_before, corr_after, delta).
    """
    before_mask = (series_a.index >= event_timestamp - pd.Timedelta(hours=window_hours)) & (
        series_a.index < event_timestamp
    )
    after_mask = (series_a.index >= event_timestamp) & (
        series_a.index < event_timestamp + pd.Timedelta(hours=window_hours)
    )

    corr_before = series_a[before_mask].pct_change().corr(series_b[before_mask].pct_change())
    corr_after = series_a[after_mask].pct_change().corr(series_b[after_mask].pct_change())
    corr_before = float(corr_before) if corr_before is not None else 0.0
    corr_after = float(corr_after) if corr_after is not None else 0.0
    return corr_before, corr_after, corr_after - corr_before
