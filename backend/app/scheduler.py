"""
Runs every job automatically in the background, on repeating intervals,
starting the moment the FastAPI app boots. Every run — success or failure
— is recorded to the `job_status` table, readable via GET /jobs/status,
so "is anything actually happening" has a real answer instead of needing
Railway log access. POST /jobs/trigger/{job_name} runs a job immediately,
for testing without waiting on its interval.
"""
import asyncio
import traceback
from datetime import datetime, timezone
from app.db import SessionLocal, engine
from app.models import JobStatus
from app import config

JOB_REGISTRY = {}  # populated by start_background_jobs(), used by manual trigger endpoint

# Arbitrary but fixed 32-bit key identifying "the Oracle X scheduler lock" —
# any int works as long as it's consistent across every process, since
# Postgres advisory locks are keyed by this number alone, not by name.
_SCHEDULER_LOCK_KEY = 823746512
_lock_connection = None  # kept open for the process lifetime; holds the session-level lock


def _acquire_scheduler_lock() -> bool:
    """
    Session-level Postgres advisory lock so at most one process runs the
    background jobs, no matter how many API replicas/workers are live —
    the rest just serve HTTP traffic. The lock is tied to this raw
    connection and is held until the connection closes (i.e. for the
    life of this process), so it's released automatically on crash or
    redeploy without needing explicit cleanup.

    Fails OPEN (returns True) if the lock attempt itself errors — e.g. the
    DB isn't reachable yet at boot — because in a single-replica hackathon
    deployment it's worse to silently run zero copies of every job than to
    risk a brief double-run during a bad startup.
    """
    global _lock_connection
    if not config.SCHEDULER_USE_ADVISORY_LOCK:
        return True
    try:
        conn = engine.raw_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT pg_try_advisory_lock(%s)", (_SCHEDULER_LOCK_KEY,))
        acquired = bool(cursor.fetchone()[0])
        cursor.close()
        if acquired:
            _lock_connection = conn  # do not close — holding it open holds the lock
            return True
        conn.close()
        return False
    except Exception:
        print("[scheduler] advisory lock attempt failed, defaulting to leader:")
        traceback.print_exc()
        return True


def _record_status(name: str, success: bool, error: str = None, result: str = None):
    db = SessionLocal()
    try:
        row = db.query(JobStatus).get(name)
        now = datetime.now(timezone.utc)
        if not row:
            row = JobStatus(job_name=name, run_count=0)
            db.add(row)
        row.last_run_at = now
        if success:
            row.last_success_at = now
            row.last_error = None
            row.last_result = result
        else:
            row.last_error = error
        row.run_count = (row.run_count or 0) + 1
        db.commit()
    except Exception:
        # Status tracking itself must never break the actual job
        traceback.print_exc()
    finally:
        db.close()


async def _safe_run(name: str, func):
    try:
        result = await asyncio.to_thread(func)
        _record_status(name, success=True, result=str(result) if result else None)
        print(f"[scheduler] {name} completed")
    except Exception as exc:
        _record_status(name, success=False, error=f"{exc}")
        print(f"[scheduler] {name} failed:")
        traceback.print_exc()


async def _run_periodically(name: str, func, interval_seconds: int, run_immediately: bool = True):
    if run_immediately:
        await _safe_run(name, func)
    while True:
        await asyncio.sleep(interval_seconds)
        await _safe_run(name, func)


def start_background_jobs():
    from app.jobs.seed_assets import seed
    from app.jobs.ingest_market_data import run_once as ingest_market_once
    from app.jobs.ingest_events import run_once as ingest_events_once
    from app.jobs.run_pipeline import run_once as pipeline_once
    from app.jobs.track_portfolio import run_once as portfolio_once
    from app.jobs.ingest_oracle_ticks import run_once as oracle_ticks_once

    JOB_REGISTRY.update({
        "seed_assets": seed,
        "ingest_market_data": ingest_market_once,
        "ingest_events": ingest_events_once,
        "run_pipeline": pipeline_once,
        "track_portfolio": portfolio_once,
        "ingest_oracle_ticks": oracle_ticks_once,
    })

    # Manual /jobs/trigger/{job_name} calls always work from any replica —
    # only the *periodic* loops are gated on winning the lock, so a
    # non-leader replica can still be told to run something immediately.
    if not _acquire_scheduler_lock():
        print("[scheduler] another process already holds the scheduler lock — "
              "this replica will serve API traffic only, no periodic jobs.")
        return

    asyncio.create_task(_safe_run("seed_assets", seed))
    asyncio.create_task(_run_periodically("ingest_market_data", ingest_market_once, 3600))
    # 6h x ~18 assets = ~72 requests/day, under NewsAPI's 100/day free cap
    # with headroom for manual triggers via POST /jobs/trigger/ingest_events.
    # (Was 15min — that burned the whole daily quota in ~90 minutes.)
    asyncio.create_task(_run_periodically("ingest_events", ingest_events_once, 21600))
    asyncio.create_task(_run_periodically("run_pipeline", pipeline_once, 600))
    asyncio.create_task(_run_periodically("track_portfolio", portfolio_once, 1800))
    # Oracle ticks (last/index/mark/funding) need much tighter granularity
    # than hourly OHLCV candles to be useful for premium/dislocation math.
    asyncio.create_task(_run_periodically("ingest_oracle_ticks", oracle_ticks_once, 120))

    print("[scheduler] background jobs started (this process is scheduler leader): "
          "seed_assets (once), ingest_market_data (hourly), ingest_events (6h), "
          "run_pipeline (10min), track_portfolio (30min), ingest_oracle_ticks (2min)")
