from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Signal, Asset, DeliveryLog
from app import config

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
def list_signals(status: str = None, db: Session = Depends(get_db)):
    q = db.query(Signal).order_by(Signal.timestamp.desc())
    if status:
        q = q.filter(Signal.status == status)
    signals = q.limit(50).all()
    return [_serialize(s, db) for s in signals]


@router.get("/{signal_id}")
def get_signal(signal_id: int, db: Session = Depends(get_db)):
    signal = db.query(Signal).get(signal_id)
    if not signal:
        raise HTTPException(404, "signal not found")
    return _serialize(signal, db)


@router.get("/{signal_id}/why")
def why(signal_id: int, db: Session = Depends(get_db)):
    from app.agents.narrator import Narrator
    signal = db.query(Signal).get(signal_id)
    if not signal:
        raise HTTPException(404, "signal not found")
    return {"explanation": Narrator(db).what_changed(signal)}


class DeliveryEvent(BaseModel):
    event_type: str  # "delivered" | "execution_clicked"
    channel: str = "dashboard"


@router.post("/{signal_id}/deliver")
def log_delivery(signal_id: int, body: DeliveryEvent, db: Session = Depends(get_db)):
    """
    Records that a signal's information was shown to the user, or that they
    clicked through to execute on Bitget. This is the audit trail for the
    AI Trading Desk track's "AI presents, human decides" boundary — every
    piece of information delivered, and every click toward execution, is
    logged here rather than assumed.
    """
    signal = db.query(Signal).get(signal_id)
    if not signal:
        raise HTTPException(404, "signal not found")
    if body.event_type not in ("delivered", "execution_clicked"):
        raise HTTPException(400, "event_type must be 'delivered' or 'execution_clicked'")

    log = DeliveryLog(signal_id=signal_id, event_type=body.event_type, channel=body.channel)
    db.add(log)
    db.commit()
    return {"logged": True}


def _serialize(s: Signal, db: Session) -> dict:
    asset = db.query(Asset).get(s.asset_id)
    reason = s.reason_json or {}
    risk_opinion = reason.get("risk_analyst_opinion")

    return {
        "id": s.id,
        "asset": asset.symbol if asset else None,
        "direction": s.direction,
        "alpha_score": float(s.alpha_score),
        "confidence": float(s.confidence),
        "model_confidence": float(s.model_confidence) if s.model_confidence is not None else None,
        "data_confidence": float(s.data_confidence) if s.data_confidence is not None else None,
        "sample_size": s.sample_size,
        "expected_move_pct": float(s.expected_move_pct) if s.expected_move_pct is not None else None,
        "current_move_pct": float(s.current_move_pct) if s.current_move_pct is not None else None,
        "displacement_pct": float(s.displacement_pct) if s.displacement_pct is not None else None,
        "risk_status": s.risk_status,
        "risk_reason": s.risk_reason,
        "narrative": s.narrative,
        "reason": s.reason_json,
        # Surfaced separately (they also live inside reason_json) so the
        # frontend doesn't need to know reason_json's internal shape.
        "oracle": reason.get("oracle"),
        "evidence_chain": reason.get("evidence_chain", []),
        "status": s.status,
        "timestamp": s.timestamp.isoformat() if s.timestamp else None,
        "execution_url": config.bitget_execution_url(asset.symbol, asset.asset_type) if asset else None,
        # Explicit, attributed agent reasoning — surfaced separately from
        # the raw reason_json blob so the frontend can show *which* Qwen
        # agent produced each piece of reasoning, not just the text.
        "agent_reasoning": {
            "narrator": {
                "agent": "Qwen — Narrator",
                "text": s.narrative,
                "provenance": (reason.get("qwen_provenance") or {}).get("narrator"),
            } if s.narrative else None,
            "risk_analyst": {
                "agent": "Qwen — Risk Analyst",
                "recommendation": risk_opinion.get("recommendation") if risk_opinion else None,
                "reasoning": risk_opinion.get("reasoning") if risk_opinion else None,
                "provenance": (reason.get("qwen_provenance") or {}).get("risk_analyst"),
            } if risk_opinion else None,
        },
        "qwen_provenance": reason.get("qwen_provenance"),
    }
