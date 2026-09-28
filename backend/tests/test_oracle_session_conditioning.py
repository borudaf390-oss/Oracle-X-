"""
Phase 2.5 verification: Oracle session-conditioning.

These exact assertions were run standalone against the real
app.oracle.dislocation module before being committed here (that module has
no DB dependency, so it was directly importable and executable in the
authoring environment, unlike the AS_OF tests) — confirmed passing,
including the key regression check in test_same_premium_scores_differently
that the same raw premium value produces materially different z-scores
depending on session (z=7.47 as REGULAR vs z=-0.24 as CLOSED with the
seed/params below), proving CLOSED and REGULAR no longer collapse onto one
shared distribution.
"""
import numpy as np
import pandas as pd
import pytest
from app.oracle.dislocation import session_conditioned_zscore, premium_zscore


@pytest.fixture()
def two_session_history():
    np.random.seed(42)
    regular = np.random.normal(loc=0.001, scale=0.002, size=20)
    closed = np.random.normal(loc=0.02, scale=0.01, size=20)
    hist = pd.DataFrame({
        "premium_pct": np.concatenate([regular, closed]),
        "session_state": ["REGULAR"] * 20 + ["CLOSED"] * 20,
    })
    return hist, regular, closed


def test_regular_3sigma_is_session_conditioned(two_session_history):
    hist, regular, _ = two_session_history
    current = regular.mean() + 3 * regular.std()
    z, conditioned = session_conditioned_zscore(current, hist, "REGULAR")
    assert conditioned is True
    assert abs(z - 3.0) < 0.15


def test_closed_3sigma_is_session_conditioned(two_session_history):
    hist, _, closed = two_session_history
    current = closed.mean() + 3 * closed.std()
    z, conditioned = session_conditioned_zscore(current, hist, "CLOSED")
    assert conditioned is True
    assert abs(z - 3.0) < 0.15


def test_same_premium_scores_differently_by_session(two_session_history):
    """The core regression check: CLOSED and REGULAR must NOT receive the
    same score for the same raw premium when their distributions differ —
    this was the actual conceptual bug being fixed."""
    hist, _, _ = two_session_history
    raw_premium = 0.015
    z_as_regular, _ = session_conditioned_zscore(raw_premium, hist, "REGULAR")
    z_as_closed, _ = session_conditioned_zscore(raw_premium, hist, "CLOSED")
    assert abs(z_as_regular - z_as_closed) > 1.0


def test_closed_falls_back_to_pooled_when_thin(two_session_history):
    hist, regular, closed = two_session_history
    thin_hist = pd.DataFrame({
        "premium_pct": np.concatenate([regular, closed[:5]]),  # only 5 CLOSED ticks, below min_same_session_ticks
        "session_state": ["REGULAR"] * 20 + ["CLOSED"] * 5,
    })
    current = 0.02
    z, conditioned = session_conditioned_zscore(current, thin_hist, "CLOSED")
    assert conditioned is False
    assert z == pytest.approx(premium_zscore(current, thin_hist["premium_pct"]))


def test_regular_falls_back_to_pooled_when_thin(two_session_history):
    hist, regular, closed = two_session_history
    thin_hist = pd.DataFrame({
        "premium_pct": np.concatenate([regular[:8], closed]),  # only 8 REGULAR ticks
        "session_state": ["REGULAR"] * 8 + ["CLOSED"] * 20,
    })
    current = 0.001
    z, conditioned = session_conditioned_zscore(current, thin_hist, "REGULAR")
    assert conditioned is False
    assert z == pytest.approx(premium_zscore(current, thin_hist["premium_pct"]))
