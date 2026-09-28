"""
Days 3-4 — Market engine ingestion (revised).

Two fixes from the S2 handbook review:
1. Symbol resolution now uses BitgetClient.resolve_symbol() against the
   real contract list instead of guessing a `{SYMBOL}USDT` convention.
2. Backfill is now paginated to cover ~90 days of hourly candles (buffer
   above the handbook's 60-day-total / 30-day-out-of-sample backtest
   requirement for Alpha Factory), not just a single 200-candle pull.

Run once manually: python -m app.jobs.ingest_market_data
Run continuously:  python -m app.jobs.ingest_market_data --loop
Full backfill:     python -m app.jobs.ingest_market_data --backfill
"""
import sys
import time
from datetime import datetime, timedelta, timezone
from app.db import SessionLocal
from app.models import Asset, MarketData
from app.data.bitget_client import BitgetClient
from app import config

GRANULARITY_MAP = {"1h": "1H", "4h": "4H", "1d": "1D", "15m": "15m", "5m": "5m", "1m": "1m"}
BACKFILL_DAYS = 90  # buffer above the 60-day backtest minimum
CANDLES_PER_REQUEST = 200  # Bitget's per-request cap


def resolve_and_cache_symbol(client: BitgetClient, asset: Asset, cache: dict):
    if asset.symbol in cache:
        return cache[asset.symbol]
    resolved = client.resolve_symbol(asset.symbol)
    if not resolved:
        print(f"  [not listed] {asset.symbol} — no matching Bitget contract, skipping")
    cache[asset.symbol] = resolved
    return resolved


def _insert_candles(db, asset: Asset, timeframe: str, candles: list) -> int:
    inserted = 0
    for c in candles:
        ts = datetime.fromtimestamp(int(c[0]) / 1000, tz=timezone.utc)
        exists = (
            db.query(MarketData)
            .filter(MarketData.asset_id == asset.id, MarketData.timeframe == timeframe,
                     MarketData.timestamp == ts)
            .first()
        )
        if exists:
            continue
        db.add(MarketData(
            asset_id=asset.id, timeframe=timeframe, timestamp=ts,
            open=c[1], high=c[2], low=c[3], close=c[4], volume=c[5],
        ))
        inserted += 1
    return inserted


def ingest_asset(db, client: BitgetClient, asset: Asset, bitget_symbol: str, timeframe: str = "1h"):
    granularity = GRANULARITY_MAP[timeframe]
    try:
        raw = client.get_candles(bitget_symbol, granularity=granularity, limit=CANDLES_PER_REQUEST)
    except Exception as exc:
        print(f"  [skip] {asset.symbol}: {exc}")
        return 0
    inserted = _insert_candles(db, asset, timeframe, raw.get("data", []))
    db.commit()
    return inserted


def backfill_asset(db, client: BitgetClient, asset: Asset, bitget_symbol: str, timeframe: str = "1h",
                    max_pages: int = 60) -> dict:
    """
    Walks backward through get_history_candles() using an endTime cursor,
    CANDLES_PER_REQUEST at a time, until either BACKFILL_DAYS is covered,
    the exchange returns no more data, or max_pages is hit (safety valve —
    60 pages * 200 candles = 12,000 hourly candles = ~500 days, comfortably
    above the 90-day target).

    Returns a coverage report rather than a bare candle count, so callers
    (and run_backtest.py) can refuse to trust a backtest built on less
    history than it claims:
        {"inserted": int, "requested_days": float, "available_days": float,
         "coverage_pct": float, "observations": int, "status": "VALID"|"INSUFFICIENT"}
    """
    granularity = GRANULARITY_MAP[timeframe]
    cutoff = datetime.now(timezone.utc) - timedelta(days=BACKFILL_DAYS)

    inserted_total = 0
    end_cursor_ms = None
    oldest_seen = None
    seen_timestamps = set()

    for _ in range(max_pages):
        try:
            raw = client.get_history_candles(
                bitget_symbol, granularity=granularity, limit=CANDLES_PER_REQUEST,
                end_time_ms=end_cursor_ms,
            )
        except Exception as exc:
            print(f"  [backfill skip] {asset.symbol}: {exc}")
            break

        candles = raw.get("data", [])
        if not candles:
            break  # exchange has no more history for this symbol

        inserted_total += _insert_candles(db, asset, timeframe, candles)
        db.commit()

        page_timestamps = {int(c[0]) for c in candles}
        if page_timestamps <= seen_timestamps:
            break  # cursor stopped advancing — avoid looping on the same page forever
        seen_timestamps |= page_timestamps

        page_oldest_ms = min(page_timestamps)
        page_oldest = datetime.fromtimestamp(page_oldest_ms / 1000, tz=timezone.utc)
        oldest_seen = page_oldest if oldest_seen is None else min(oldest_seen, page_oldest)

        if page_oldest <= cutoff:
            break  # reached target depth

        # Bitget's endTime is exclusive-ish in practice for paging backward —
        # step one interval before the oldest candle we just saw so the next
        # page doesn't re-request the same window.
        interval_ms = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
                        "15m": 900_000, "5m": 300_000, "1m": 60_000}[timeframe]
        end_cursor_ms = page_oldest_ms - interval_ms

    available_days = (datetime.now(timezone.utc) - oldest_seen).days if oldest_seen else 0
    coverage_pct = round(min(available_days / BACKFILL_DAYS, 1.0) * 100, 1) if BACKFILL_DAYS else 0.0
    status = "VALID" if available_days >= BACKFILL_DAYS * 0.9 else "INSUFFICIENT"

    report = {
        "inserted": inserted_total,
        "requested_days": BACKFILL_DAYS,
        "available_days": available_days,
        "coverage_pct": coverage_pct,
        "observations": len(seen_timestamps),
        "status": status,
    }
    print(f"  [backfill] {asset.symbol}: requested={BACKFILL_DAYS}d available={available_days}d "
          f"({coverage_pct}%) observations={len(seen_timestamps)} status={status}")
    return report


def actual_coverage_days(db, asset_id: int, timeframe: str = "1h") -> float:
    """
    What run_backtest.py checks before trusting its own output: how much
    real history actually exists for this asset in market_data, computed
    from the data itself rather than assumed from a backfill job having
    run "successfully" (which previously said nothing about how deep it
    actually reached).
    """
    from app.models import MarketData
    oldest = (
        db.query(MarketData)
        .filter(MarketData.asset_id == asset_id, MarketData.timeframe == timeframe)
        .order_by(MarketData.timestamp.asc())
        .first()
    )
    if not oldest:
        return 0.0
    return (datetime.now(timezone.utc) - oldest.timestamp.replace(tzinfo=timezone.utc)).days


def run_once(timeframe: str = "1h"):
    db = SessionLocal()
    client = BitgetClient()
    symbol_cache = {}
    try:
        assets = db.query(Asset).all()
        total = 0
        for asset in assets:
            bitget_symbol = resolve_and_cache_symbol(client, asset, symbol_cache)
            if not bitget_symbol:
                continue
            n = ingest_asset(db, client, asset, bitget_symbol, timeframe)
            total += n
            print(f"  {asset.symbol} ({bitget_symbol}): +{n} candles")
        print(f"ingest complete: {total} new candles across {len(assets)} assets")
    finally:
        db.close()


def run_backfill(timeframe: str = "1h") -> dict:
    """
    Returns {symbol: coverage_report} for every asset, so a caller (or
    run_backtest.py, before trusting a backtest) can check whether the
    claimed 60/90-day window was actually reached rather than assuming it
    was because the job ran without error.
    """
    db = SessionLocal()
    client = BitgetClient()
    symbol_cache = {}
    reports = {}
    try:
        assets = db.query(Asset).all()
        total = 0
        insufficient = []
        for asset in assets:
            bitget_symbol = resolve_and_cache_symbol(client, asset, symbol_cache)
            if not bitget_symbol:
                continue
            report = backfill_asset(db, client, asset, bitget_symbol, timeframe)
            reports[asset.symbol] = report
            total += report["inserted"]
            if report["status"] == "INSUFFICIENT":
                insufficient.append(asset.symbol)
        print(f"backfill complete: {total} candles across {len(assets)} assets "
              f"(~{BACKFILL_DAYS}d target)")
        if insufficient:
            print(f"  [insufficient coverage] {', '.join(insufficient)} — "
                  f"backtests involving these pairs will be refused until more history exists")
    finally:
        db.close()
    return reports


if __name__ == "__main__":
    if "--backfill" in sys.argv:
        run_backfill()
    elif "--loop" in sys.argv:
        while True:
            run_once()
            time.sleep(3600)
    else:
        run_once()
