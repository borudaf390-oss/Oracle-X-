"""
Agent 1 — Sentinel (spec section 12).
Job: find events. News, earnings, macro, crypto, announcements.
Writes raw events to the `events` table (pre-Interpreter — sentiment/
magnitude/affected_assets are filled in by Agent 2, not here).
"""
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import Event, Asset


class Sentinel:
    def __init__(self, db: Session):
        self.db = db

    def ingest_raw_headline(self, asset_symbol: str, headline: str, source: str, event_type: str,
                             timestamp: datetime = None, published_at: datetime = None,
                             source_url: str = None) -> Event:
        """
        Persist a raw, unstructured event. Source feed integration (news API,
        RSS, Bitget announcements, etc.) plugs in here — this method is the
        single entry point everything upstream should call.

        published_at: when the source says this actually happened/was
        published — becomes `timestamp` (what AS_OF and every downstream
        relationship calculation anchors to) when given, since "when we
        happened to download it" is a materially different, less accurate
        anchor for a system whose core claim is about information
        propagation timing. Falls back to `timestamp` (explicit override,
        e.g. for backfilling a known event time) or now() only when neither
        is available.
        """
        asset = self.db.query(Asset).filter(Asset.symbol == asset_symbol).first()
        now = datetime.utcnow()
        event = Event(
            timestamp=published_at or timestamp or now,
            asset_id=asset.id if asset else None,
            event_type=event_type,
            headline=headline,
            raw_source=source,
            published_at=published_at,
            ingested_at=now,
            source_url=source_url,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def fetch_pending_for_interpretation(self, limit: int = 20):
        """Events ingested but not yet processed by the Interpreter (sentiment is null)."""
        return (
            self.db.query(Event)
            .filter(Event.sentiment.is_(None))
            .order_by(Event.timestamp.desc())
            .limit(limit)
            .all()
        )
