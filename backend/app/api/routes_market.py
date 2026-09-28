from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Asset, MarketData, RelationshipEdge
from app.quant.regime import classify_regime
import pandas as pd

router = APIRouter(prefix="/market", tags=["market"])


def _series(db: Session, asset_id: int, timeframe: str = "1h") -> pd.Series:
    rows = (
        db.query(MarketData)
        .filter(MarketData.asset_id == asset_id, MarketData.timeframe == timeframe)
        .order_by(MarketData.timestamp.asc())
        .all()
    )
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series([float(r.close) for r in rows], index=[r.timestamp for r in rows])


@router.get("/live")
def live_market(db: Session = Depends(get_db)):
    assets = db.query(Asset).all()
    out = []
    for a in assets:
        series = _series(db, a.id)
        if len(series) < 2:
            continue
        change_pct = float(series.iloc[-1] / series.iloc[-2] - 1)
        out.append({
            "symbol": a.symbol,
            "asset_type": a.asset_type,
            "sector": a.sector,
            "price": float(series.iloc[-1]),
            "change_pct": change_pct,
        })
    return out


@router.get("/regime")
def regime(db: Session = Depends(get_db)):
    btc = db.query(Asset).filter(Asset.symbol == "BTC").first()
    qqq = db.query(Asset).filter(Asset.symbol == "QQQ").first()
    if not btc or not qqq:
        return {"regime": "NEUTRAL", "score": 0.0}
    return classify_regime(_series(db, btc.id), _series(db, qqq.id))


@router.get("/map")
def market_map(db: Session = Depends(get_db)):
    """Node/edge data for the force-directed propagation graph."""
    assets = db.query(Asset).all()
    edges = db.query(RelationshipEdge).order_by(RelationshipEdge.computed_at.desc()).limit(200).all()
    nodes = []
    for a in assets:
        series = _series(db, a.id)
        change_pct = float(series.iloc[-1] / series.iloc[-2] - 1) if len(series) > 1 else 0.0
        nodes.append({"id": a.id, "symbol": a.symbol, "sector": a.sector, "change_pct": change_pct})
    edge_list = [
        {
            "source": e.asset_a_id,
            "target": e.asset_b_id,
            "correlation": float(e.correlation) if e.correlation is not None else 0.0,
            "lead_lag_hours": float(e.lead_lag_hours) if e.lead_lag_hours is not None else 0.0,
        }
        for e in edges
    ]
    return {"nodes": nodes, "edges": edge_list}
