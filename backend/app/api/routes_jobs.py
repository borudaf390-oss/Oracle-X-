from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from datetime import datetime, timezone, timedelta
from app.db import get_db, engine
from app.models import JobStatus, MarketData, OracleTick, Event, Signal, Asset
from app.scheduler import JOB_REGISTRY, _safe_run, _SCHEDULER_LOCK_KEY
from app import config
import asyncio

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/status")
def job_status(db: Session = Depends(get_db)):
    rows = db.query(JobStatus).all()
    return [
        {
            "job_name": r.job_name,
            "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
            "last_success_at": r.last_success_at.isoformat() if r.last_success_at else None,
            "last_error": r.last_error,
            "run_count": r.run_count,
            "healthy": r.last_error is None,
        }
        for r in rows
    ]


@router.get("/health")
def ops_health(db: Session = Depends(get_db)):
    """
    Ops / health panel payload: scheduler leader hint, per-job status,
    data freshness (latest market candle, oracle tick, event), signal counts.
    """
    rows = db.query(JobStatus).all()
    jobs = [
        {
            "job_name": r.job_name,
            "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
            "last_success_at": r.last_success_at.isoformat() if r.last_success_at else None,
            "last_error": r.last_error,
            "run_count": r.run_count or 0,
            "healthy": r.last_error is None,
        }
        for r in rows
    ]

    # Scheduler leader: best-effort — try to see if *this* process holds the lock.
    is_leader = None
    if not config.SCHEDULER_USE_ADVISORY_LOCK:
        is_leader = True
    else:
        try:
            with engine.connect() as conn:
                # pg_try_advisory_lock would steal the lock; use pg_advisory_lock
                # inspection via pg_locks instead.
                result = conn.execute(
                    text(
                        "SELECT EXISTS ("
                        "  SELECT 1 FROM pg_locks"
                        "  WHERE locktype = 'advisory'"
                        "    AND classid = 0"
                        "    AND objid = :key"
                        "    AND granted = true"
                        ")"
                    ),
                    {"key": _SCHEDULER_LOCK_KEY},
                )
                is_leader = bool(result.scalar())
        except Exception:
            is_leader = None

    now = datetime.now(timezone.utc)

    def _age_seconds(ts):
        if ts is None:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0, int((now - ts).total_seconds()))

    latest_candle = db.query(func.max(MarketData.timestamp)).scalar()
    latest_tick = db.query(func.max(OracleTick.timestamp)).scalar()
    latest_event = db.query(func.max(Event.timestamp)).scalar()
    asset_count = db.query(func.count(Asset.id)).scalar() or 0
    open_signals = (
        db.query(func.count(Signal.id))
        .filter(Signal.status.in_(["OPEN", "SIMULATED"]))
        .scalar()
        or 0
    )
    pass_signals = (
        db.query(func.count(Signal.id)).filter(Signal.risk_status == "PASS").scalar() or 0
    )
    block_signals = (
        db.query(func.count(Signal.id)).filter(Signal.risk_status == "BLOCK").scalar() or 0
    )

    return {
        "scheduler": {
            "advisory_lock_enabled": config.SCHEDULER_USE_ADVISORY_LOCK,
            "lock_held": is_leader,
            "registered_jobs": sorted(JOB_REGISTRY.keys()),
        },
        "jobs": jobs,
        "freshness": {
            "latest_market_candle_at": latest_candle.isoformat() if latest_candle else None,
            "latest_market_candle_age_s": _age_seconds(latest_candle),
            "latest_oracle_tick_at": latest_tick.isoformat() if latest_tick else None,
            "latest_oracle_tick_age_s": _age_seconds(latest_tick),
            "latest_event_at": latest_event.isoformat() if latest_event else None,
            "latest_event_age_s": _age_seconds(latest_event),
        },
        "counts": {
            "assets": asset_count,
            "open_signals": open_signals,
            "pass_signals": pass_signals,
            "block_signals": block_signals,
        },
        "server_time": now.isoformat(),
    }


@router.post("/trigger/{job_name}")
async def trigger_job(job_name: str):
    """Runs a job immediately instead of waiting for its scheduled interval."""
    if job_name not in JOB_REGISTRY:
        raise HTTPException(
            404, f"unknown job: {job_name}. Known jobs: {list(JOB_REGISTRY.keys())}"
        )
    asyncio.create_task(_safe_run(job_name, JOB_REGISTRY[job_name]))
    return {"triggered": job_name}
