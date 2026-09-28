"""
Agent 2 — Interpreter (spec section 12).
Turns a raw event into structured data using Qwen, then writes the
structured fields back onto the event row.
"""
from sqlalchemy.orm import Session
from app.models import Event, Asset
from app.data.qwen_client import QwenClient


class Interpreter:
    def __init__(self, db: Session, qwen: QwenClient = None):
        self.db = db
        self.qwen = qwen or QwenClient()

    def interpret(self, event: Event) -> Event:
        structured = self.qwen.extract_event(event.headline, event.raw_source or "")

        event.sentiment = structured.get("sentiment")
        event.magnitude = structured.get("magnitude")
        event.horizon_hours = structured.get("horizon_hours")
        event.extraction_failed = bool(structured.get("extraction_failed", False))

        affected_symbols = structured.get("affected_assets", [])
        affected_ids = [
            a.id for a in self.db.query(Asset).filter(Asset.symbol.in_(affected_symbols)).all()
        ]
        event.affected_assets = affected_ids

        # Backfill asset_id from Qwen if Sentinel didn't have it
        if event.asset_id is None and structured.get("asset"):
            asset = self.db.query(Asset).filter(Asset.symbol == structured["asset"]).first()
            if asset:
                event.asset_id = asset.id

        self.db.commit()
        self.db.refresh(event)
        return event

    def interpret_batch(self, events: list[Event]) -> list[Event]:
        return [self.interpret(e) for e in events]
