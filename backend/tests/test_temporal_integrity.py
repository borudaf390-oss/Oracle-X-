"""
Temporal-integrity regression tests.

These exist because of a confirmed bug: RelationshipHunter and
find_historical_pairs previously queried an asset's ENTIRE available
price history with no upper timestamp bound, so a relationship "explaining"
an event could be fit using market data that arrived after that event —
undermining the whole "information propagation" premise the product rests
on. app/agents/relationship.py and app/quant/historical_analogues.py now
accept an `as_of` parameter that bounds every query to
`timestamp <= as_of`.

The test strategy: build a baseline dataset with NO real relationship
between two assets, get a result at some cutoff timestamp T. Then insert
"poisoned" future rows (timestamps > T) deliberately engineered to have an
obvious, strong relationship with the leader — the kind of thing that
would jump out immediately if it leaked into a past calculation. Assert:

  1. Querying with as_of=T gives back the EXACT same result whether the
     poisoned future rows exist in the DB or not (proves the boundary
     actually excludes them).
  2. Querying the SAME poisoned dataset with as_of=None (unbounded, the
     old default) gives a MEANINGFULLY DIFFERENT result (proves the
     poisoned data would actually have corrupted the result if it leaked
     in — i.e. assertion 1 isn't vacuously true because the poison had no
     effect anyway).

Run with: cd backend && pytest tests/ -v
Requires sqlalchemy + pytest installed (see requirements.txt) — these
were written and hand-verified against a standalone pandas reproduction
of the same scenario, but have NOT been executed in-repo in the
environment these were authored in (no sqlalchemy/pytest available
there); run them locally before relying on them.
"""
import math
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import numpy as np
import pandas as pd
from app.models import Asset, MarketData
from app.agents.relationship import RelationshipHunter
from app.quant.historical_analogues import find_historical_pairs

HOURS = 100
CUTOFF_HOUR = 60
BASE_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _seed_assets(db):
    leader = Asset(symbol="LEADER", asset_type="crypto", sector=None)
    follower = Asset(symbol="FOLLOWER", asset_type="crypto", sector=None)
    db.add_all([leader, follower])
    db.commit()
    db.refresh(leader)
    db.refresh(follower)
    return leader, follower


def _insert_candles(db, asset_id: int, prices: dict):
    """prices: {hour_offset: close_price}"""
    for hour, price in prices.items():
        ts = BASE_TS + timedelta(hours=hour)
        db.add(MarketData(
            asset_id=asset_id, timeframe="1h", timestamp=ts,
            open=price, high=price, low=price, close=price, volume=1000.0,
        ))
    db.commit()


def _leader_prices() -> dict:
    steps = np.sin(np.arange(HOURS) * 0.7) + 0.3 * np.cos(np.arange(HOURS) * 0.13)
    prices = 100 + np.cumsum(steps)
    return {h: float(p) for h, p in enumerate(prices)}


def _follower_baseline_prices() -> dict:
    """Hours 0..CUTOFF_HOUR, deliberately unrelated pattern to the leader."""
    steps = np.cos(np.arange(CUTOFF_HOUR + 1) * 1.9) * 0.05
    prices = 50 + np.cumsum(steps)
    return {h: float(p) for h, p in enumerate(prices)}


def _follower_poison_prices(leader_prices: dict) -> dict:
    """Hours CUTOFF_HOUR+1..HOURS-1, engineered to closely track the leader —
    an obvious, strong relationship that must NOT be visible to an as_of=CUTOFF query."""
    return {
        h: leader_prices[h] + 0.001 * (h - CUTOFF_HOUR)
        for h in range(CUTOFF_HOUR + 1, HOURS)
    }


def test_relationship_hunter_ignores_future_data(db_session):
    db = db_session
    leader, follower = _seed_assets(db)
    leader_prices = _leader_prices()
    _insert_candles(db, leader.id, leader_prices)
    _insert_candles(db, follower.id, _follower_baseline_prices())

    as_of = BASE_TS + timedelta(hours=CUTOFF_HOUR)
    # affected_assets bypasses the min_abs_correlation filter (0.15) that
    # find_propagation_candidates() applies — this test's baseline
    # relationship is deliberately near-zero, so without this the
    # candidate wouldn't be returned at all and there'd be nothing to
    # compare. Qwen-flagging is also realistic: it's exactly the
    # mechanism the real pipeline uses to keep a candidate in view even
    # when raw correlation alone wouldn't surface it.
    event = SimpleNamespace(asset_id=leader.id, timestamp=as_of, affected_assets=[follower.id])

    hunter = RelationshipHunter(db)
    baseline = hunter.find_propagation_candidates(event, as_of=as_of)
    baseline_follower = next(c for c in baseline if c["symbol"] == "FOLLOWER")

    # Now poison the future — rows strictly after the cutoff, strongly related to the leader.
    _insert_candles(db, follower.id, _follower_poison_prices(leader_prices))

    bounded = hunter.find_propagation_candidates(event, as_of=as_of)
    bounded_follower = next(c for c in bounded if c["symbol"] == "FOLLOWER")

    assert math.isclose(bounded_follower["correlation"], baseline_follower["correlation"], abs_tol=1e-9), (
        "as_of-bounded correlation changed after inserting FUTURE rows — temporal leakage regression"
    )
    assert bounded_follower["lead_lag_hours"] == baseline_follower["lead_lag_hours"]

    # Sanity check: the poison must actually be capable of changing the
    # result when the boundary is removed, or the assertions above would
    # be true for the trivial reason that the poison did nothing at all.
    # find_propagation_candidates() itself always falls back to
    # source_event.timestamp when as_of is omitted (a deliberate
    # fail-safe default — there's no legitimate reason to ever want it
    # fully unbounded in production), so this checks the underlying
    # _price_series() truncation directly instead, which does support a
    # genuinely unbounded query.
    from app.quant.correlation import rolling_correlation
    leader_unbounded = hunter._price_series(leader.id, as_of=None)
    follower_unbounded = hunter._price_series(follower.id, as_of=None)
    unbounded_corr_series = rolling_correlation(leader_unbounded, follower_unbounded).dropna()
    unbounded_corr = float(unbounded_corr_series.iloc[-1])
    assert abs(unbounded_corr - baseline_follower["correlation"]) > 0.3, (
        "poisoned future data had no effect on the unbounded query — "
        "this test's synthetic data isn't actually exercising the leakage path"
    )


def test_find_historical_pairs_ignores_future_data(db_session):
    db = db_session
    leader, follower = _seed_assets(db)
    leader_prices = _leader_prices()
    _insert_candles(db, leader.id, leader_prices)
    _insert_candles(db, follower.id, _follower_baseline_prices())

    as_of = BASE_TS + timedelta(hours=CUTOFF_HOUR)

    baseline_pairs = find_historical_pairs(
        db, leader.id, follower.id, move_threshold_pct=0.01, lag_hours=1, as_of=as_of
    )

    _insert_candles(db, follower.id, _follower_poison_prices(leader_prices))

    bounded_pairs = find_historical_pairs(
        db, leader.id, follower.id, move_threshold_pct=0.01, lag_hours=1, as_of=as_of
    )

    pd.testing.assert_frame_equal(
        baseline_pairs.reset_index(drop=True), bounded_pairs.reset_index(drop=True)
    )

    unbounded_pairs = find_historical_pairs(
        db, leader.id, follower.id, move_threshold_pct=0.01, lag_hours=1, as_of=None
    )
    assert len(unbounded_pairs) != len(baseline_pairs) or not unbounded_pairs.equals(baseline_pairs), (
        "poisoned future data had no effect on the unbounded query — "
        "this test's synthetic data isn't actually exercising the leakage path"
    )
