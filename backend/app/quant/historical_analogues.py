"""
Days 7-8 — Historical Intelligence (spec section 6).
Finds past instances where the leader asset made a comparable move and
records how the follower asset reacted, producing the
(leader_move_pct, follower_move_pct) pairs that
quant/displacement.py::expected_reaction() fits a relationship to.

This is the real implementation behind what was previously a manual
`historical_pairs` argument to AlphaAnalyst.analyze().
"""
import pandas as pd
from sqlalchemy.orm import Session
from app.models import MarketData


def _hourly_returns(db: Session, asset_id: int, as_of=None) -> pd.Series:
    """as_of: only rows with timestamp <= as_of are included — see find_historical_pairs."""
    query = db.query(MarketData).filter(
        MarketData.asset_id == asset_id, MarketData.timeframe == "1h"
    )
    if as_of is not None:
        query = query.filter(MarketData.timestamp <= as_of)
    rows = query.order_by(MarketData.timestamp.asc()).all()
    if len(rows) < 2:
        return pd.Series(dtype=float)
    closes = pd.Series([float(r.close) for r in rows], index=[r.timestamp for r in rows])
    return closes.pct_change().dropna()


def find_historical_pairs(
    db: Session,
    leader_asset_id: int,
    follower_asset_id: int,
    move_threshold_pct: float = 0.02,
    lag_hours: int = 1,
    lookback_limit: int = 500,
    as_of=None,
) -> pd.DataFrame:
    """
    Scans leader's hourly return history for moves exceeding
    move_threshold_pct, and pairs each with the follower's return
    `lag_hours` later. Returns a DataFrame with columns
    ['leader_move_pct', 'follower_move_pct', 'timestamp'] — this is what
    quant/displacement.expected_reaction() consumes directly.

    as_of: temporal-integrity boundary (see agents/relationship.py's
    matching docstring). Both leader and follower return series are
    truncated to timestamp <= as_of before any analogue is built — pass
    the event's timestamp here when fitting the relationship a live
    signal is based on, so the fit can only ever use analogues that had
    actually completed (both the leader move AND the follower's
    lag_hours-later reaction) before the event being explained. Omit
    only for genuinely "what does history show me right now" queries.

    Real analogue search over price history, not a synthetic/pre-seeded
    table — accuracy depends on how much historical market_data has been
    backfilled (aim for 6-12 months per the spec, ingest_market_data.py's
    default 200-candle pull is a starting point, not the full backfill).
    """
    leader_returns = _hourly_returns(db, leader_asset_id, as_of=as_of).tail(lookback_limit)
    follower_returns = _hourly_returns(db, follower_asset_id, as_of=as_of)

    if leader_returns.empty or follower_returns.empty:
        return pd.DataFrame(columns=["leader_move_pct", "follower_move_pct", "timestamp"])

    events = leader_returns[leader_returns.abs() >= move_threshold_pct]

    pairs = []
    for ts, leader_move in events.items():
        target_ts = ts + pd.Timedelta(hours=lag_hours)
        # nearest follower return at/after target_ts within a small tolerance window
        window = follower_returns[
            (follower_returns.index >= target_ts) &
            (follower_returns.index <= target_ts + pd.Timedelta(hours=1))
        ]
        if window.empty:
            continue
        follower_move = float(window.iloc[0])
        pairs.append({
            "leader_move_pct": float(leader_move),
            "follower_move_pct": follower_move,
            "timestamp": ts,
        })

    return pd.DataFrame(pairs)


def analogue_summary(pairs: pd.DataFrame, current_leader_move_pct: float, similarity_band: float = 0.01) -> dict:
    """
    Summary stats for the Opportunity Card's 'historical analogues' block
    (spec section 6): count of similar events, follow-through rate, median
    and average follower move.
    """
    if pairs.empty:
        return {"similar_events": 0, "follow_through_rate": 0.0, "median_move": 0.0, "average_move": 0.0}

    similar = pairs[
        (pairs["leader_move_pct"] - current_leader_move_pct).abs() <= similarity_band
    ]
    if similar.empty:
        similar = pairs  # fall back to full sample if nothing within band

    same_direction = similar[
        (similar["follower_move_pct"] > 0) == (current_leader_move_pct > 0)
    ]
    follow_through_rate = round(len(same_direction) / len(similar) * 100, 1) if len(similar) else 0.0

    return {
        "similar_events": int(len(similar)),
        "follow_through_rate": follow_through_rate,
        "median_move": round(float(similar["follower_move_pct"].median()) * 100, 2),
        "average_move": round(float(similar["follower_move_pct"].mean()) * 100, 2),
    }
