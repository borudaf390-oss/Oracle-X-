"""
Oracle tick ingestion — the data feed behind the dislocation engine
(app/oracle/dislocation.py).

Polls Bitget's ticker endpoint (via BitgetClient.get_ticker(), which hits
/api/v2/mix/market/ticker — confirmed to return lastPr/indexPrice/
markPrice/fundingRate in one call) far more frequently than the hourly
OHLCV candle job, since premium/dislocation math needs tighter granularity
than candles provide. Every tick is stored with its computed premium_pct,
mark_basis_pct, and session_state already attached, so downstream
consumers (routes_oracle.py, agents/alpha.py) never need to recompute them
from raw prices.

Run once manually: python -m app.jobs.ingest_oracle_ticks
Run continuously:  python -m app.jobs.ingest_oracle_ticks --loop
"""
import sys
import time
from datetime import datetime, timezone
from app.db import SessionLocal
from app.models import Asset, OracleTick
from app.data.bitget_client import BitgetClient
from app.jobs.ingest_market_data import resolve_and_cache_symbol
from app.oracle.session import session_state_for_asset
from app.oracle.dislocation import premium_pct, mark_basis_pct


def _parse_ticker_payload(raw: dict) -> dict | None:
    """Bitget's ticker response wraps a single-element list in `data`."""
    rows = raw.get("data", [])
    if not rows:
        return None
    row = rows[0]
    try:
        return {
            "last_price": float(row["lastPr"]),
            "index_price": float(row["indexPrice"]) if row.get("indexPrice") else None,
            "mark_price": float(row["markPrice"]) if row.get("markPrice") else None,
            "funding_rate": float(row["fundingRate"]) if row.get("fundingRate") else None,
        }
    except (KeyError, TypeError, ValueError):
        return None


def ingest_asset_tick(db, client: BitgetClient, asset: Asset, bitget_symbol: str) -> bool:
    try:
        raw = client.get_ticker(bitget_symbol)
    except Exception as exc:
        print(f"  [oracle skip] {asset.symbol}: {exc}")
        return False

    parsed = _parse_ticker_payload(raw)
    if parsed is None:
        print(f"  [oracle skip] {asset.symbol}: unparsable ticker payload")
        return False

    premium = premium_pct(parsed["last_price"], parsed["index_price"]) if parsed["index_price"] else None
    basis = mark_basis_pct(parsed["mark_price"], parsed["index_price"]) if parsed["index_price"] and parsed["mark_price"] else None

    tick = OracleTick(
        asset_id=asset.id,
        timestamp=datetime.now(timezone.utc),
        last_price=parsed["last_price"],
        index_price=parsed["index_price"],
        mark_price=parsed["mark_price"],
        funding_rate=parsed["funding_rate"],
        premium_pct=premium,
        mark_basis_pct=basis,
        session_state=session_state_for_asset(asset.asset_type),
    )
    db.add(tick)
    db.commit()
    return True


def run_once():
    db = SessionLocal()
    client = BitgetClient()
    symbol_cache = {}
    try:
        assets = db.query(Asset).all()
        ok = 0
        for asset in assets:
            bitget_symbol = resolve_and_cache_symbol(client, asset, symbol_cache)
            if not bitget_symbol:
                continue
            if ingest_asset_tick(db, client, asset, bitget_symbol):
                ok += 1
        print(f"oracle ticks: {ok}/{len(assets)} assets recorded")
    finally:
        db.close()


if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True:
            run_once()
            time.sleep(120)
    else:
        run_once()
