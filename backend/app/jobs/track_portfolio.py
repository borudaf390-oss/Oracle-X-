"""
Gap fix — replaces the hardcoded PLACEHOLDER_PORTFOLIO_STATE in
jobs/run_pipeline.py with real account data.

Per the S2 handbook: use a dedicated Agentic sub-account (isolated funds,
OAuth, no manual API key) or Bitget's Demo/paper-trading environment during
the hackathon — both work fine here, since this reads from the standard
signed account endpoints either way.

Run once manually: python -m app.jobs.track_portfolio
Run continuously:  python -m app.jobs.track_portfolio --loop
"""
import sys
import time
from datetime import datetime, timedelta, timezone
from app.db import SessionLocal
from app.models import PortfolioSnapshot
from app.data.bitget_client import BitgetClient


def take_snapshot(db, client: BitgetClient) -> PortfolioSnapshot:
    """
    Pulls real account overview and persists a snapshot. Response shape
    should be confirmed against a live call (Bitget's account response
    nests fields under productType-specific keys) — the .get() chain below
    is defensive but the exact field names need verifying against real
    output during Day 3-4 testing, not assumed from docs alone.
    """
    raw = client.get_account_overview()
    accounts = raw.get("data", [])
    account = accounts[0] if accounts else {}

    equity = float(account.get("usdtEquity") or account.get("equity") or 0)
    available = float(account.get("available") or 0)
    unrealized = float(account.get("unrealizedPL") or 0)

    snapshot = PortfolioSnapshot(
        equity=equity, available=available, unrealized_pnl=unrealized, raw_json=raw,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def compute_daily_pnl_pct(db) -> float | None:
    """
    Equity now vs. equity ~24h ago, as a percentage. Returns None — not
    0.0 — when there isn't a snapshot from ~24h ago to compare against.
    0.0 would read as "flat, no loss today," which is a PASS on the
    daily-loss-stop risk check; the honest answer when there's no
    baseline yet is "unknown," which RiskGate now treats as a BLOCK.
    """
    now = (
        db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.timestamp.desc()).first()
    )
    if not now:
        return None
    cutoff = now.timestamp - timedelta(hours=24)
    day_ago = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.timestamp <= cutoff)
        .order_by(PortfolioSnapshot.timestamp.desc())
        .first()
    )
    if not day_ago or float(day_ago.equity) == 0:
        return None
    return float(now.equity) / float(day_ago.equity) - 1


def compute_drawdown_pct(db, lookback_days: int = 30) -> float | None:
    """Current equity vs. the running peak equity over the lookback window.
    Returns None (not 0.0) when there's no snapshot data at all — see
    compute_daily_pnl_pct's docstring for why that distinction matters."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.timestamp >= cutoff)
        .order_by(PortfolioSnapshot.timestamp.asc())
        .all()
    )
    if not snapshots:
        return None
    peak = max(float(s.equity) for s in snapshots)
    current = float(snapshots[-1].equity)
    if peak == 0:
        return None
    return max(0.0, (peak - current) / peak)


def get_live_portfolio_state(db) -> dict:
    """
    Drop-in replacement for jobs/run_pipeline.py's
    PLACEHOLDER_PORTFOLIO_STATE. proposed_position_pct and
    stop_distance_pct still need to come from the specific signal being
    evaluated (they're per-trade, not portfolio-level) — this only supplies
    the two portfolio-level numbers the Risk Gate needs.
    """
    return {
        "daily_pnl_pct": compute_daily_pnl_pct(db),
        "drawdown_pct": compute_drawdown_pct(db),
    }


def run_once():
    db = SessionLocal()
    client = BitgetClient()
    try:
        snap = take_snapshot(db, client)
        state = get_live_portfolio_state(db)
        daily_pnl_str = f"{state['daily_pnl_pct']:.4f}" if state["daily_pnl_pct"] is not None else "unknown"
        drawdown_str = f"{state['drawdown_pct']:.4f}" if state["drawdown_pct"] is not None else "unknown"
        print(f"snapshot: equity={snap.equity} daily_pnl={daily_pnl_str} drawdown={drawdown_str}")
    finally:
        db.close()


if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True:
            run_once()
            time.sleep(1800)  # every 30 min
    else:
        run_once()
