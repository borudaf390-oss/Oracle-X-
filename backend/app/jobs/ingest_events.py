"""
Days 5-6 — Event intelligence ingestion.
For each asset in the universe: pull recent headlines, dedupe against
already-ingested events (by headline text), run Sentinel to persist raw
events, then Interpreter to structure them via Qwen.

Run once manually: python -m app.jobs.ingest_events
Run continuously:  python -m app.jobs.ingest_events --loop
"""
import sys
import time
from datetime import datetime
from app.db import SessionLocal
from app.models import Asset, Event
from app.data.news_client import NewsClient
from app.agents.sentinel import Sentinel
from app.agents.interpreter import Interpreter
from app import config


def _parse_published_at(raw: str | None):
    """
    NewsAPI's publishedAt is ISO 8601 UTC, typically with a 'Z' suffix
    (e.g. '2026-09-20T09:02:00Z'). Python 3.11's datetime.fromisoformat
    handles 'Z' natively; this still guards against a missing/malformed
    value falling through to Sentinel's own now()-fallback rather than
    raising and dropping the whole article.
    """
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def run_once():
    db = SessionLocal()
    news = NewsClient()
    sentinel = Sentinel(db)
    interpreter = Interpreter(db)
    try:
        assets = db.query(Asset).all()
        new_events = []
        for asset in assets:
            try:
                if asset.asset_type == "crypto":
                    articles = news.crypto_headlines(asset.symbol)
                else:
                    articles = news.headlines_for(asset.symbol)
            except Exception as exc:
                print(f"  [skip] {asset.symbol}: {exc}")
                continue

            for a in articles:
                already = (
                    db.query(Event)
                    .filter(Event.headline == a["headline"], Event.asset_id == asset.id)
                    .first()
                )
                if already:
                    continue
                event_type = "earnings" if "earnings" in a["headline"].lower() else (
                    "crypto_news" if asset.asset_type == "crypto" else "product"
                )
                event = sentinel.ingest_raw_headline(
                    asset_symbol=asset.symbol,
                    headline=a["headline"],
                    source=a["source"],
                    event_type=event_type,
                    published_at=_parse_published_at(a.get("published_at")),
                    source_url=a.get("url"),
                )
                new_events.append(event)
            print(f"  {asset.symbol}: {len(articles)} headlines checked")

        print(f"ingested {len(new_events)} new raw events, interpreting via Qwen...")
        pending = sentinel.fetch_pending_for_interpretation(limit=50)
        interpreted = interpreter.interpret_batch(pending)
        print(f"interpreted {len(interpreted)} events")
    finally:
        db.close()


if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True:
            run_once()
            time.sleep(900)  # every 15 min
    else:
        run_once()
