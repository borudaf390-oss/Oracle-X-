"""
Day 11 — Backtesting harness.

Walk-forward validation of the core Oracle X relationship: given a leader
asset's move, does the expected_reaction() fit (trained only on PRIOR
events) predict the follower asset's actual subsequent move?

This is walk-forward by construction — at event i, only pairs from events
strictly before event i are used to fit the relationship, so there's no
lookahead bias in what "would have been predictable at the time."

Satisfies the S2 handbook's Alpha Factory backtest convention (60 days
total, last 30 days marked out-of-sample) even though Oracle X is
submitting under AI Trading Desk — kept because it's the honest way to
show whether the causal-chain thesis actually holds up, not just a
compliance checkbox.

Requires real ingested market_data for both assets — this will produce
zero or near-zero results until ingest_market_data.py has actually been
run for a meaningful window. It does not fabricate a backtest report.

Run: python -m app.jobs.run_backtest --leader NVDA --follower AMD
     python -m app.jobs.run_backtest --all-pairs   (uses config.SECTOR_MAP)
"""
import sys
import uuid
import argparse
import pandas as pd
from datetime import datetime, timedelta, timezone
from app.db import SessionLocal
from app.models import Asset, MarketData, BacktestResult
from app.quant.displacement import expected_reaction, displacement_gap
from app.quant.performance import performance_summary
from app.quant.correlation import lead_lag_hours
from app.jobs.ingest_market_data import actual_coverage_days
from app import config

BACKTEST_WINDOW_DAYS = 60
OUT_OF_SAMPLE_DAYS = 30
MOVE_THRESHOLD_PCT = 0.02
LAG_HOURS = 1
MIN_COVERAGE_FRACTION = 0.9  # refuse to run below 90% of BACKTEST_WINDOW_DAYS of real history


def _hourly_closes(db, asset_id: int) -> pd.Series:
    """Raw close-price series — what lead_lag_hours() expects (it pct_changes internally)."""
    rows = (
        db.query(MarketData)
        .filter(MarketData.asset_id == asset_id, MarketData.timeframe == "1h")
        .order_by(MarketData.timestamp.asc())
        .all()
    )
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series([float(r.close) for r in rows], index=[r.timestamp for r in rows])


def _hourly_returns(db, asset_id: int) -> pd.Series:
    rows = (
        db.query(MarketData)
        .filter(MarketData.asset_id == asset_id, MarketData.timeframe == "1h")
        .order_by(MarketData.timestamp.asc())
        .all()
    )
    if len(rows) < 2:
        return pd.Series(dtype=float)
    closes = pd.Series([float(r.close) for r in rows], index=[r.timestamp for r in rows])
    return closes.pct_change().dropna()


def walk_forward(db, leader: Asset, follower: Asset, run_id: str, lag_hours: int = LAG_HOURS) -> list[BacktestResult]:
    """
    Core walk-forward loop. For each leader move event, fits
    expected_reaction() using only pairs observed strictly before that
    event, predicts the follower's move, then compares to what actually
    happened. Every prediction is genuinely out-of-sample relative to the
    data used to make it, regardless of the in_sample/out_of_sample label
    (which only marks the reporting window per the handbook convention).

    lag_hours should be the pair's actually-discovered propagation delay
    (see run()) rather than an assumed constant — testing every pair at a
    fixed 1h lag validates a different hypothesis than whatever delay the
    live pipeline (run_pipeline.py) discovered and actually traded on for
    that pair.
    """
    leader_returns = _hourly_returns(db, leader.id)
    follower_returns = _hourly_returns(db, follower.id)
    if leader_returns.empty or follower_returns.empty:
        return []

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=BACKTEST_WINDOW_DAYS)
    oos_cutoff = now - timedelta(days=OUT_OF_SAMPLE_DAYS)

    leader_returns = leader_returns[leader_returns.index >= window_start]
    events = leader_returns[leader_returns.abs() >= MOVE_THRESHOLD_PCT].sort_index()

    seen_pairs = []  # accumulates (leader_move_pct, follower_move_pct) from EARLIER events only
    results = []

    for ts, leader_move in events.items():
        # Build historical_pairs strictly from events before ts (walk-forward)
        pairs_df = pd.DataFrame(seen_pairs, columns=["leader_move_pct", "follower_move_pct"])

        target_ts = ts + pd.Timedelta(hours=lag_hours)
        window = follower_returns[
            (follower_returns.index >= target_ts) & (follower_returns.index <= target_ts + pd.Timedelta(hours=1))
        ]
        if window.empty:
            continue
        actual_follower_move = float(window.iloc[0])

        if len(pairs_df) >= 5:
            predicted, r_sq = expected_reaction(float(leader_move), pairs_df)
        else:
            predicted, r_sq = 0.0, 0.0  # not enough prior data yet to predict

        direction_correct = (predicted >= 0) == (actual_follower_move >= 0) if predicted != 0 else False

        results.append(BacktestResult(
            run_id=run_id,
            leader_asset_id=leader.id,
            follower_asset_id=follower.id,
            event_timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
            leader_move_pct=float(leader_move),
            predicted_move_pct=predicted,
            actual_move_pct=actual_follower_move,
            direction_correct=direction_correct,
            in_sample=ts.to_pydatetime().replace(tzinfo=timezone.utc) < oos_cutoff if hasattr(ts, "to_pydatetime") else ts < oos_cutoff,
            r_squared_at_time=r_sq,
        ))

        # NOW add this event to the pool for future predictions
        seen_pairs.append({"leader_move_pct": float(leader_move), "follower_move_pct": actual_follower_move})

    return results


def summarize(results: list[BacktestResult]) -> dict:
    def bucket(rows):
        if not rows:
            return {"count": 0, "hit_rate": None, "mean_abs_error": None, "performance": performance_summary([])}
        rows = sorted(rows, key=lambda r: r.event_timestamp)  # equity curve needs chronological order
        hits = sum(1 for r in rows if r.direction_correct)
        mae = sum(abs(float(r.predicted_move_pct) - float(r.actual_move_pct)) for r in rows) / len(rows)
        return {
            "count": len(rows),
            "hit_rate": round(hits / len(rows) * 100, 1),
            "mean_abs_error_pct": round(mae * 100, 3),
            # Direction hit rate alone can hide a losing strategy (a 70%
            # hit rate with losers bigger than winners still loses money)
            # — this is the trade-economics view alongside it.
            "performance": performance_summary(rows),
        }

    in_sample = [r for r in results if r.in_sample]
    out_sample = [r for r in results if not r.in_sample]
    return {
        "total_events": len(results),
        "in_sample": bucket(in_sample),
        "out_of_sample": bucket(out_sample),
    }


def run(leader_symbol: str, follower_symbol: str):
    db = SessionLocal()
    try:
        leader = db.query(Asset).filter(Asset.symbol == leader_symbol).first()
        follower = db.query(Asset).filter(Asset.symbol == follower_symbol).first()
        if not leader or not follower:
            print(f"asset not found: {leader_symbol} or {follower_symbol} — run seed_assets.py first")
            return

        # Coverage gate (P0 fix): the walk-forward loop below will happily
        # produce a report from whatever data exists, with no signal that
        # "60-day backtest" secretly ran on 12 days because backfill never
        # finished paginating. Refuse outright rather than let a thin
        # result imply the validation the handbook expects.
        required_days = BACKTEST_WINDOW_DAYS * MIN_COVERAGE_FRACTION
        leader_days = actual_coverage_days(db, leader.id)
        follower_days = actual_coverage_days(db, follower.id)
        if leader_days < required_days or follower_days < required_days:
            print(
                f"{leader_symbol}->{follower_symbol}: INSUFFICIENT DATA — "
                f"requested {BACKTEST_WINDOW_DAYS}d, have {leader_symbol}={leader_days}d "
                f"{follower_symbol}={follower_days}d (need >={required_days:.0f}d). "
                f"Run ingest_market_data.py --backfill first; refusing to run a backtest "
                f"that would silently understate its own validation window."
            )
            return

        run_id = str(uuid.uuid4())[:8]

        # Discover this pair's actual propagation lag over the full
        # available history (not just the backtest window — the more
        # history for this estimate the better) rather than assuming a
        # fixed 1h delay. Falls back to LAG_HOURS if the discovered lag
        # doesn't support "leader precedes follower" for this pair.
        leader_full = _hourly_closes(db, leader.id)
        follower_full = _hourly_closes(db, follower.id)
        discovered_lag, discovered_corr = (
            lead_lag_hours(leader_full, follower_full) if not leader_full.empty and not follower_full.empty
            else (0.0, 0.0)
        )
        lag_hours = max(1, round(discovered_lag)) if discovered_lag > 0 else LAG_HOURS
        print(f"{leader_symbol}->{follower_symbol}: using lag_hours={lag_hours} "
              f"(discovered lag={discovered_lag}, corr={discovered_corr:.3f})")

        results = walk_forward(db, leader, follower, run_id, lag_hours=lag_hours)

        if not results:
            print(f"{leader_symbol}->{follower_symbol}: no results — insufficient market_data history. "
                  f"Run ingest_market_data.py --backfill first.")
            return

        db.add_all(results)
        db.commit()

        summary = summarize(results)
        print(f"{leader_symbol}->{follower_symbol} (run {run_id}):")
        print(f"  total events: {summary['total_events']}")
        print(f"  in-sample:     hit_rate={summary['in_sample']['hit_rate']} "
              f"perf={summary['in_sample']['performance']}")
        print(f"  out-of-sample: hit_rate={summary['out_of_sample']['hit_rate']} "
              f"perf={summary['out_of_sample']['performance']}")
    finally:
        db.close()


def run_all_pairs():
    db = SessionLocal()
    try:
        assets = {a.symbol: a for a in db.query(Asset).all()}
    finally:
        db.close()

    for symbol, sector in config.SECTOR_MAP.items():
        peers = [s for s, sec in config.SECTOR_MAP.items() if sec == sector and s != symbol]
        for peer in peers:
            if symbol in assets and peer in assets:
                run(symbol, peer)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--leader")
    parser.add_argument("--follower")
    parser.add_argument("--all-pairs", action="store_true")
    args = parser.parse_args()

    if args.all_pairs:
        run_all_pairs()
    elif args.leader and args.follower:
        run(args.leader, args.follower)
    else:
        print("usage: python -m app.jobs.run_backtest --leader NVDA --follower AMD")
        print("       python -m app.jobs.run_backtest --all-pairs")
        sys.exit(1)
