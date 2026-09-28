"""Shared oracle_ticks -> DataFrame loader, used by routes_oracle.py and agents/alpha.py."""
import pandas as pd
from sqlalchemy.orm import Session
from app.models import OracleTick
from app import config

_LOOKBACK_TICKS = config.ORACLE_THRESHOLDS["rolling_window"]


def ticks_df(db: Session, asset_id: int, limit: int = _LOOKBACK_TICKS, as_of=None) -> pd.DataFrame:
    """as_of: only ticks with timestamp <= as_of — see AlphaAnalyst.analyze()'s docstring."""
    query = db.query(OracleTick).filter(OracleTick.asset_id == asset_id)
    if as_of is not None:
        query = query.filter(OracleTick.timestamp <= as_of)
    rows = query.order_by(OracleTick.timestamp.desc()).limit(limit).all()
    rows = list(reversed(rows))  # oldest -> newest
    if not rows:
        return pd.DataFrame(columns=["premium_pct", "funding_rate"])
    return pd.DataFrame([
        {
            "timestamp": r.timestamp,
            "last_price": float(r.last_price) if r.last_price is not None else None,
            "index_price": float(r.index_price) if r.index_price is not None else None,
            "mark_price": float(r.mark_price) if r.mark_price is not None else None,
            "funding_rate": float(r.funding_rate) if r.funding_rate is not None else None,
            "premium_pct": float(r.premium_pct) if r.premium_pct is not None else None,
            "session_state": r.session_state,
        }
        for r in rows
    ])
