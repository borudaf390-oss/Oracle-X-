from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import BacktestResult, Asset
from app.jobs.ingest_market_data import actual_coverage_days
from app.jobs.run_backtest import BACKTEST_WINDOW_DAYS
from app.quant.performance import performance_summary

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.get("/runs")
def list_runs(db: Session = Depends(get_db)):
    """
    Distinct run_ids with their leader/follower pair, event count, and the
    actual current data coverage behind each pair — so the frontend can
    show "60-day backtest (currently only 41d of history available)"
    instead of implying a validation depth the data doesn't back up.
    """
    rows = db.query(BacktestResult).all()
    runs: dict = {}
    for r in rows:
        key = r.run_id
        if key not in runs:
            leader = db.query(Asset).get(r.leader_asset_id)
            follower = db.query(Asset).get(r.follower_asset_id)
            leader_days = actual_coverage_days(db, r.leader_asset_id) if leader else 0
            follower_days = actual_coverage_days(db, r.follower_asset_id) if follower else 0
            runs[key] = {
                "run_id": key,
                "leader": leader.symbol if leader else None,
                "follower": follower.symbol if follower else None,
                "event_count": 0,
                "hits": 0,
                "requested_window_days": BACKTEST_WINDOW_DAYS,
                "leader_coverage_days": leader_days,
                "follower_coverage_days": follower_days,
                "coverage_status": (
                    "VALID" if min(leader_days, follower_days) >= BACKTEST_WINDOW_DAYS * 0.9
                    else "INSUFFICIENT"
                ),
            }
        runs[key]["event_count"] += 1
        if r.direction_correct:
            runs[key]["hits"] += 1

    out = []
    for run in runs.values():
        run["hit_rate"] = round(run["hits"] / run["event_count"] * 100, 1) if run["event_count"] else None
        out.append(run)
    return out


@router.get("/runs/{run_id}")
def run_detail(run_id: str, db: Session = Depends(get_db)):
    rows = db.query(BacktestResult).filter(BacktestResult.run_id == run_id).order_by(BacktestResult.event_timestamp).all()
    events = [
        {
            "event_timestamp": r.event_timestamp.isoformat(),
            "leader_move_pct": float(r.leader_move_pct),
            "predicted_move_pct": float(r.predicted_move_pct),
            "actual_move_pct": float(r.actual_move_pct),
            "direction_correct": r.direction_correct,
            "in_sample": r.in_sample,
            "r_squared_at_time": float(r.r_squared_at_time) if r.r_squared_at_time is not None else None,
        }
        for r in rows
    ]
    # Trade-economics on top of raw direction hits — see quant/performance.py
    # for why hit_rate alone isn't a sufficient view (a 70% hit-rate system
    # can still lose money if losers outsize winners).
    return {
        "events": events,
        "performance": {
            "overall": performance_summary(rows),
            "in_sample": performance_summary([r for r in rows if r.in_sample]),
            "out_of_sample": performance_summary([r for r in rows if not r.in_sample]),
        },
    }
