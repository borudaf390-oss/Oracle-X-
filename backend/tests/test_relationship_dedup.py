"""
Phase 2.5 verification: relationship-edge dedup (agents/relationship.py's
_recent_edge_exists / _EDGE_DEDUP_MINUTES).

Verifies the distinction the user asked to make explicit: repeated calls
to find_propagation_candidates() for the same pair should keep computing
and returning a live correlation/lag every time (never suppress the
calculation), but should only WRITE a new relationships row when the
existing one has aged out of the dedup window.

NOT executed in the environment these were authored in — sqlalchemy isn't
available there (see tests/test_temporal_integrity.py's docstring for the
same caveat). Hand-traced carefully; run locally with
`pytest tests/ -v` before relying on it.
"""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import numpy as np
from app.models import Asset, MarketData, RelationshipEdge
from app.agents.relationship import RelationshipHunter, _EDGE_DEDUP_MINUTES

HOURS = 80
BASE_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _seed_correlated_pair(db):
    leader = Asset(symbol="LEADER", asset_type="crypto", sector=None)
    follower = Asset(symbol="FOLLOWER", asset_type="crypto", sector=None)
    db.add_all([leader, follower])
    db.commit()
    db.refresh(leader)
    db.refresh(follower)

    steps = np.sin(np.arange(HOURS) * 0.7) + 0.3 * np.cos(np.arange(HOURS) * 0.13)
    leader_prices = 100 + np.cumsum(steps)
    # FOLLOWER tracks LEADER closely so this pair clears the correlation
    # threshold on its own merits (no need for the qwen_flagged bypass
    # used in the temporal-integrity tests).
    follower_prices = 50 + np.cumsum(steps) * 0.8

    for h in range(HOURS):
        ts = BASE_TS + timedelta(hours=h)
        db.add(MarketData(asset_id=leader.id, timeframe="1h", timestamp=ts,
                           open=leader_prices[h], high=leader_prices[h], low=leader_prices[h],
                           close=leader_prices[h], volume=1000.0))
        db.add(MarketData(asset_id=follower.id, timeframe="1h", timestamp=ts,
                           open=follower_prices[h], high=follower_prices[h], low=follower_prices[h],
                           close=follower_prices[h], volume=1000.0))
    db.commit()
    return leader, follower


def _edge_count(db, leader_id, follower_id) -> int:
    return (
        db.query(RelationshipEdge)
        .filter(RelationshipEdge.asset_a_id == leader_id, RelationshipEdge.asset_b_id == follower_id)
        .count()
    )


def test_repeated_calls_within_window_write_only_once(db_session):
    db = db_session
    leader, follower = _seed_correlated_pair(db)
    as_of = BASE_TS + timedelta(hours=HOURS - 1)
    event = SimpleNamespace(asset_id=leader.id, timestamp=as_of, affected_assets=None)
    hunter = RelationshipHunter(db)

    first = hunter.find_propagation_candidates(event, as_of=as_of)
    assert any(c["symbol"] == "FOLLOWER" for c in first), "pair should clear the correlation threshold on its own"
    assert _edge_count(db, leader.id, follower.id) == 1

    # Immediately call again — the live calculation must still happen
    # (this asserts on its presence in the returned list, not just on the
    # row count), but no new row should be written since the existing one
    # is well within _EDGE_DEDUP_MINUTES.
    second = hunter.find_propagation_candidates(event, as_of=as_of)
    assert any(c["symbol"] == "FOLLOWER" for c in second), "calculation must still run even when the write is skipped"
    assert _edge_count(db, leader.id, follower.id) == 1, "dedup should have skipped the second write"


def test_new_snapshot_written_after_dedup_window_expires(db_session):
    db = db_session
    leader, follower = _seed_correlated_pair(db)
    as_of = BASE_TS + timedelta(hours=HOURS - 1)
    event = SimpleNamespace(asset_id=leader.id, timestamp=as_of, affected_assets=None)
    hunter = RelationshipHunter(db)

    hunter.find_propagation_candidates(event, as_of=as_of)
    assert _edge_count(db, leader.id, follower.id) == 1

    # Age the existing edge past the dedup window by directly backdating
    # its computed_at, rather than waiting _EDGE_DEDUP_MINUTES of real
    # wall-clock time.
    edge = db.query(RelationshipEdge).filter(
        RelationshipEdge.asset_a_id == leader.id, RelationshipEdge.asset_b_id == follower.id
    ).one()
    edge.computed_at = datetime.now(timezone.utc) - timedelta(minutes=_EDGE_DEDUP_MINUTES + 5)
    db.commit()

    hunter.find_propagation_candidates(event, as_of=as_of)
    assert _edge_count(db, leader.id, follower.id) == 2, "a new snapshot should be written once the old one has aged out"
