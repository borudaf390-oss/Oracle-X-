"""
Day 1-2 setup step: seed `assets` from config.ASSET_UNIVERSE before any
ingestion job can run (market_data/events both FK into assets.id).
Run once: python -m app.jobs.seed_assets
"""
from app.db import SessionLocal
from app.models import Asset
from app import config

ASSET_TYPE_MAP = {**{s: "crypto" for s in config.CRYPTO_ASSETS},
                   **{s: "tokenized_equity" for s in config.TOKENIZED_EQUITY_ASSETS},
                   **{s: "index" for s in config.INDEX_ASSETS}}


def seed():
    db = SessionLocal()
    try:
        existing = {a.symbol for a in db.query(Asset).all()}
        created = 0
        for symbol in config.ASSET_UNIVERSE:
            if symbol in existing:
                continue
            db.add(Asset(
                symbol=symbol,
                asset_type=ASSET_TYPE_MAP.get(symbol, "unknown"),
                sector=config.SECTOR_MAP.get(symbol),
                display_name=symbol,
            ))
            created += 1
        db.commit()
        print(f"seeded {created} new assets ({len(existing)} already present)")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
