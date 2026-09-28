"""
Alpha Score composer (spec section 5). Combines the six weighted factors
into a single 0-100 score. Weights are read from the `factor_weights` table
(seeded from config.DEFAULT_FACTOR_WEIGHTS), not hardcoded, so the
self-improvement loop (autopsy -> factor update) can actually move them.
"""
from sqlalchemy.orm import Session
from app.models import FactorWeight


def get_live_weights(db: Session) -> dict:
    rows = db.query(FactorWeight).all()
    if not rows:
        from app import config
        return dict(config.DEFAULT_FACTOR_WEIGHTS)
    return {r.factor_name: float(r.weight) for r in rows}


def compose_alpha_score(factors: dict, weights: dict) -> float:
    """
    factors: dict with keys matching factor_weights.factor_name, each a
    0..1 normalized value (displacement z-score should be squashed to 0..1
    before calling this — see quant/displacement.py).
    Returns a 0-100 score.
    """
    total_weight = sum(weights.values()) or 1.0
    score = sum(factors.get(name, 0.0) * weight for name, weight in weights.items())
    return round((score / total_weight) * 100, 2)


def score_band(score: float) -> str:
    if score < 40:
        return "NO_TRADE"
    elif score < 60:
        return "WEAK"
    elif score < 75:
        return "WATCH"
    elif score < 90:
        return "STRONG"
    else:
        return "EXTREME"
