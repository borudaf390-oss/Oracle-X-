"""
Momentum + volume abnormality factors feeding the Alpha Score.
"""
import numpy as np
import pandas as pd


def momentum_score(close: pd.Series, short_window: int = 4, long_window: int = 24) -> float:
    """
    Simple dual-window momentum: short-term ROC relative to long-term ROC,
    normalized to roughly -1..1 via tanh for use as an Alpha Score input.
    """
    if len(close) < long_window + 1:
        return 0.0
    short_roc = (close.iloc[-1] / close.iloc[-short_window] - 1) if len(close) > short_window else 0.0
    long_roc = (close.iloc[-1] / close.iloc[-long_window] - 1) if len(close) > long_window else 0.0
    raw = short_roc - long_roc
    return float(np.tanh(raw * 10))  # squashed to -1..1


def volume_abnormality(volume: pd.Series, window: int = 30) -> float:
    """
    Current volume vs rolling mean, expressed as a z-score, squashed to 0..1
    for the Alpha Score's volume_abnormality factor (only spikes matter, so
    we clip negative z-scores to 0).
    """
    if len(volume) < window + 1:
        return 0.0
    rolling_mean = volume.iloc[-window - 1:-1].mean()
    rolling_std = volume.iloc[-window - 1:-1].std()
    if rolling_std == 0 or np.isnan(rolling_std):
        return 0.0
    z = (volume.iloc[-1] - rolling_mean) / rolling_std
    return float(min(max(z, 0) / 4, 1.0))  # 4-sigma spike -> 1.0
