from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Event, Asset

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/recent")
def recent_news(limit: int = 30, db: Session = Depends(get_db)):
    """
    Financial news feed — raw events ingested by Sentinel and structured
    by Interpreter. This is literally the Agent 1/Agent 2 output from the
    architecture, surfaced as a readable feed rather than only living
    inside the signal pipeline.
    """
    rows = db.query(Event).order_by(Event.timestamp.desc()).limit(limit).all()
    out = []
    for e in rows:
        asset = db.query(Asset).get(e.asset_id) if e.asset_id else None
        out.append({
            "id": e.id,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            "asset": asset.symbol if asset else None,
            "event_type": e.event_type,
            "headline": e.headline,
            "source": e.raw_source,
            "sentiment": e.sentiment,
            "magnitude": float(e.magnitude) if e.magnitude is not None else None,
            "interpreted": e.sentiment is not None,  # False = Sentinel caught it, Interpreter hasn't run yet
        })
    return out
