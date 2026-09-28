from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Asset
from app.oracle.dislocation import oracle_state
from app.oracle.query import ticks_df as _ticks_df

router = APIRouter(prefix="/oracle", tags=["oracle"])


@router.get("/{symbol}")
def get_oracle_state(symbol: str, db: Session = Depends(get_db)):
    """
    Current dislocation state for one asset: premium vs Bitget's index
    price, its z-score/percentile/duration/velocity against this asset's
    own recent history, funding-rate skew, and the underlying market's
    session state. Powers the Opportunity Card's Oracle panel.
    """
    asset = db.query(Asset).filter(Asset.symbol == symbol.upper()).first()
    if not asset:
        raise HTTPException(404, f"asset not found: {symbol}")

    df = _ticks_df(db, asset.id)
    if df.empty:
        return {"symbol": asset.symbol, "status": "NO_DATA"}

    current = df.iloc[-1].to_dict()
    historical = df.iloc[:-1]
    state = oracle_state(current, historical)
    state["symbol"] = asset.symbol
    return state


@router.get("")
def oracle_summary(db: Session = Depends(get_db)):
    """All assets' latest oracle regime — powers a market-wide dislocation overview."""
    assets = db.query(Asset).all()
    out = []
    for asset in assets:
        df = _ticks_df(db, asset.id)
        if df.empty:
            continue
        current = df.iloc[-1].to_dict()
        historical = df.iloc[:-1]
        state = oracle_state(current, historical)
        state["symbol"] = asset.symbol
        out.append(state)
    out.sort(key=lambda s: abs(s.get("premium_zscore", 0.0)), reverse=True)
    return out


@router.get("/history/{symbol}")
def oracle_history(symbol: str, limit: int = 60, db: Session = Depends(get_db)):
    """
    Recent premium / funding / session points for sparkline charts on the
    Oracle page. Newest last. Caps at 200 points.
    """
    limit = max(1, min(limit, 200))
    asset = db.query(Asset).filter(Asset.symbol == symbol.upper()).first()
    if not asset:
        raise HTTPException(404, f"asset not found: {symbol}")

    df = _ticks_df(db, asset.id, limit=limit)
    if df.empty:
        return {"symbol": asset.symbol, "points": []}

    points = []
    for _, row in df.iterrows():
        ts = row.get("timestamp")
        points.append({
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "premium_pct": float(row["premium_pct"]) if row.get("premium_pct") is not None else None,
            "funding_rate": float(row["funding_rate"]) if row.get("funding_rate") is not None else None,
            "last_price": float(row["last_price"]) if row.get("last_price") is not None else None,
            "session_state": row.get("session_state"),
        })
    return {"symbol": asset.symbol, "points": points}
