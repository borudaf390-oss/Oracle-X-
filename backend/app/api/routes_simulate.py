from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Signal, Simulation, Outcome, MarketData, FactorWeight, FactorPerformance

router = APIRouter(tags=["simulation"])

# Adaptive Signal Calibration thresholds. A factor's live weight is only
# ever touched once it has this many accumulated correct/missed
# observations — below that, _record_factor_observations() keeps counting
# but _promote_candidate_weights() leaves factor_weights.weight alone.
MIN_SAMPLE_FOR_PROMOTION = 20
PROMOTION_LEARNING_RATE = 0.05  # max |weight delta| applied per promotion


@router.post("/signals/{signal_id}/simulate")
def simulate(signal_id: int, db: Session = Depends(get_db)):
    signal = db.query(Signal).get(signal_id)
    if not signal:
        raise HTTPException(404, "signal not found")
    if signal.risk_status != "PASS":
        raise HTTPException(400, f"cannot simulate a signal with risk_status={signal.risk_status}")

    latest = (
        db.query(MarketData)
        .filter(MarketData.asset_id == signal.asset_id, MarketData.timeframe == "1h")
        .order_by(MarketData.timestamp.desc())
        .first()
    )
    if not latest:
        raise HTTPException(400, "no market data for this asset")

    entry = float(latest.close)
    expected_move = float(signal.expected_move_pct or 0)
    stop_pct = 0.018  # placeholder default stop distance; tune via risk_gate min_stop_distance
    if signal.direction == "LONG":
        stop = entry * (1 - stop_pct)
        target = entry * (1 + abs(expected_move))
    else:
        stop = entry * (1 + stop_pct)
        target = entry * (1 - abs(expected_move))

    risk_amount = abs(entry - stop)
    reward_amount = abs(target - entry)
    rr = round(reward_amount / risk_amount, 3) if risk_amount > 0 else 0.0

    sim = Simulation(
        signal_id=signal.id,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        risk_amount=risk_amount,
        reward_amount=reward_amount,
        risk_reward=rr,
        historical_win_rate=None,  # filled once historical analogue engine is wired (Days 7-8)
    )
    db.add(sim)
    signal.status = "SIMULATED"
    db.commit()
    db.refresh(sim)

    return {
        "entry": entry, "stop": stop, "target": target,
        "risk_amount": risk_amount, "reward_amount": reward_amount,
        "risk_reward": rr,
    }


class CloseOutcomeRequest(BaseModel):
    actual_return_pct: float
    result_summary: str = ""
    correct_factors: list[str] = []
    missed_factors: list[str] = []


@router.post("/outcomes/{signal_id}/close")
def close_outcome(signal_id: int, body: CloseOutcomeRequest, db: Session = Depends(get_db)):
    signal = db.query(Signal).get(signal_id)
    if not signal:
        raise HTTPException(404, "signal not found")

    predicted = float(signal.expected_move_pct or 0)
    error = round(abs(predicted - body.actual_return_pct), 4)

    outcome = Outcome(
        signal_id=signal.id,
        actual_return_pct=body.actual_return_pct,
        prediction_error_pct=error,
        result_summary=body.result_summary,
        correct_factors=body.correct_factors,
        missed_factors=body.missed_factors,
    )
    db.add(outcome)
    signal.status = "CLOSED"
    db.commit()

    _record_factor_observations(db, outcome)
    promoted = _promote_candidate_weights(db)

    return {"prediction_error_pct": error, "factors_promoted": promoted}


def _record_factor_observations(db: Session, outcome: Outcome):
    """
    Adaptive Signal Calibration, step 1: accumulate correct/missed
    attribution counts per factor. Deliberately does NOT touch
    FactorWeight.weight — see _promote_candidate_weights for the gated
    step that does, once enough evidence has accumulated.
    """
    for name in (outcome.correct_factors or []) + (outcome.missed_factors or []):
        if db.query(FactorWeight).filter(FactorWeight.factor_name == name).first() is None:
            continue  # ignore factor names that don't correspond to a live weight
        row = db.query(FactorPerformance).get(name)
        if row is None:
            row = FactorPerformance(factor_name=name, correct_count=0, missed_count=0)
            db.add(row)
        if name in (outcome.correct_factors or []):
            row.correct_count += 1
        if name in (outcome.missed_factors or []):
            row.missed_count += 1
    db.commit()


def _promote_candidate_weights(db: Session) -> list[str]:
    """
    Adaptive Signal Calibration, step 2: promote accumulated observations
    into live factor_weights — but ONLY for factors with at least
    MIN_SAMPLE_FOR_PROMOTION total observations. This is what stops a
    single outcome from swinging a live weight (the previous
    implementation moved weights by a fixed step on every single close,
    regardless of sample size).

    This is a sample-size gate, not full out-of-sample validation — a
    genuine held-out evaluation split would need infrastructure this
    hackathon build doesn't have yet (a separate validation population of
    signals never used to inform the promotion decision). Documented here
    rather than silently presented as more rigorous than it is.

    Counters reset after promotion so the next promotion reflects new
    evidence rather than the same observations compounding indefinitely.
    """
    weights = {w.factor_name: w for w in db.query(FactorWeight).all()}
    promoted = []

    for perf in db.query(FactorPerformance).all():
        total = perf.correct_count + perf.missed_count
        if total < MIN_SAMPLE_FOR_PROMOTION or perf.factor_name not in weights:
            continue

        accuracy = perf.correct_count / total
        delta = PROMOTION_LEARNING_RATE * (accuracy - 0.5) * 2  # maps 0..1 accuracy to -rate..+rate

        w = weights[perf.factor_name]
        w.weight = round(max(0.01, float(w.weight) + delta), 4)
        w.update_reason = (
            f"promoted: {total} obs, {accuracy * 100:.0f}% correct-attribution rate, "
            f"delta={delta:+.4f}"
        )
        perf.last_promoted_at = datetime.utcnow()
        perf.last_promotion_note = w.update_reason
        perf.correct_count = 0
        perf.missed_count = 0
        promoted.append(perf.factor_name)

    if promoted:
        total_weight = sum(float(w.weight) for w in weights.values()) or 1.0
        for w in weights.values():
            w.weight = round(float(w.weight) / total_weight, 4)
        db.commit()

    return promoted
