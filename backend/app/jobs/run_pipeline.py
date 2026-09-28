"""
Day 9 — Pipeline orchestrator.
Wires Sentinel -> Interpreter -> Relationship Hunter -> Alpha Analyst ->
Risk Analyst + Risk Gate -> Narrator into one real, callable pipeline.
This is the job that actually turns a fresh event into a finished,
explainable, risk-gated Signal row — everything upstream (ingestion jobs)
feeds this; everything downstream (API, frontend) reads its output.

Run once manually: python -m app.jobs.run_pipeline
Run continuously:  python -m app.jobs.run_pipeline --loop
"""
import sys
import time
from datetime import datetime, timezone
from app.db import SessionLocal
from app.models import Event, Asset
from app.agents.sentinel import Sentinel
from app.agents.interpreter import Interpreter
from app.agents.relationship import RelationshipHunter
from app.agents.alpha import AlphaAnalyst
from app.agents.risk_analyst import RiskAnalyst
from app.agents.risk_gate import RiskGate
from app.agents.narrator import Narrator
from app.quant.historical_analogues import find_historical_pairs
from app.jobs.track_portfolio import get_live_portfolio_state

# Per-trade values still need to come from the specific signal/position
# sizing logic, not the portfolio tracker — these two remain here as the
# per-trade defaults until position-sizing logic is built out.
PER_TRADE_DEFAULTS = {
    "proposed_position_pct": 0.02,
    "stop_distance_pct": 0.018,
}


def process_event(db, event: Event) -> list:
    """
    Runs one already-interpreted event through the full agent chain.
    Returns created Signal rows.

    as_of = event.timestamp is the temporal-integrity boundary (see
    agents/relationship.py and agents/alpha.py's matching docstrings in
    detail): relationship DISCOVERY (find_propagation_candidates,
    find_historical_pairs) must only see data that existed at/before the
    event, or the "historical relationship" it fits could quietly include
    market moves that happened after the event it's supposedly explaining.
    analyst.analyze() deliberately does NOT get this same as_of — it needs
    live, current data to measure how the market has actually reacted
    SINCE the event, which is the whole point of current_move_pct.
    """
    hunter = RelationshipHunter(db)
    analyst = AlphaAnalyst(db)
    risk_analyst = RiskAnalyst(db)
    risk_gate = RiskGate(db)
    narrator = Narrator(db)

    as_of = event.timestamp
    candidates = hunter.find_propagation_candidates(event, as_of=as_of)
    if not candidates:
        return []

    signals = []
    for candidate in candidates[:3]:  # top 3 strongest-correlated candidates per event
        # Use the actually-discovered propagation lag (RelationshipHunter's
        # lead_lag_hours, now correctly signed — see quant/correlation.py)
        # instead of hardcoding 1 hour everywhere. causal_direction_supported
        # (computed by relationship.py) is False when the empirical data
        # doesn't actually support "leader precedes candidate" for this
        # pair — flagged in reason_json rather than silently treated as if
        # the causal direction were confirmed.
        raw_lag = candidate.get("lead_lag_hours", 1) or 1
        lag_hours = max(1, round(abs(raw_lag)))

        pairs = find_historical_pairs(
            db, event.asset_id, candidate["asset_id"], lag_hours=lag_hours, as_of=as_of
        )
        signal = analyst.analyze(event, candidate, pairs, lag_hours=lag_hours)

        # Advisory qualitative opinion — logged, does not gate
        try:
            opinion = risk_analyst.assess(signal)
            reason = dict(signal.reason_json or {})
            # Strip nested provenance from the opinion blob for the advisory
            # field, and hoist it under the unified qwen_provenance key (B5).
            prov = opinion.pop("qwen_provenance", None)
            reason["risk_analyst_opinion"] = opinion
            if prov:
                qwen_prov = dict(reason.get("qwen_provenance") or {})
                qwen_prov["risk_analyst"] = prov
                reason["qwen_provenance"] = qwen_prov
            signal.reason_json = reason
            db.commit()
        except Exception as exc:
            print(f"    [risk_analyst skipped] {exc}")

        # The actual gate — deterministic, this is what sets risk_status
        portfolio_state = get_live_portfolio_state(db)
        risk_gate.evaluate(
            signal,
            portfolio_daily_pnl_pct=portfolio_state["daily_pnl_pct"],
            portfolio_drawdown_pct=portfolio_state["drawdown_pct"],
            proposed_position_pct=PER_TRADE_DEFAULTS["proposed_position_pct"],
            stop_distance_pct=PER_TRADE_DEFAULTS["stop_distance_pct"],
        )

        try:
            narrator.narrate(signal)
        except Exception as exc:
            print(f"    [narrator skipped] {exc}")

        signals.append(signal)
        print(f"    -> signal {signal.id} {candidate['symbol']} {signal.direction} "
              f"alpha={signal.alpha_score} risk={signal.risk_status}")

    return signals


def run_once():
    db = SessionLocal()
    sentinel = Sentinel(db)
    interpreter = Interpreter(db)
    try:
        pending = sentinel.fetch_pending_for_interpretation(limit=20)
        if pending:
            print(f"interpreting {len(pending)} pending events...")
            interpreter.interpret_batch(pending)


        # B4: failed extractions are interpreted but not actionable — mark
        # them processed so they don't occupy the pending window forever.
        failed = (
            db.query(Event)
            .filter(
                Event.extraction_failed.is_(True),
                Event.pipeline_processed_at.is_(None),
            )
            .limit(50)
            .all()
        )
        for fe in failed:
            fe.pipeline_processed_at = datetime.now(timezone.utc)
        if failed:
            db.commit()
            print(f"marked {len(failed)} failed-extraction events as processed (no signals)")

        # process recently interpreted events that don't have signals yet.
        # pipeline_processed_at IS NULL is the actual "doesn't have signals
        # yet" filter — the previous version's comment claimed this but the
        # query never enforced it, so the same 20 most-recent events could
        # regenerate signals on every single 10-minute cycle indefinitely.
        recent = (
            db.query(Event)
            .filter(
                Event.sentiment.isnot(None),
                Event.asset_id.isnot(None),
                Event.pipeline_processed_at.is_(None),
                Event.extraction_failed.is_(False),  # B4: skip failed extractions
            )
            .order_by(Event.timestamp.desc())
            .limit(20)
            .all()
        )
        total_signals = 0
        for event in recent:
            asset = db.query(Asset).get(event.asset_id)
            print(f"processing event {event.id} ({asset.symbol if asset else '?'}): {event.headline[:60]}")
            try:
                signals = process_event(db, event)
                total_signals += len(signals)
                # Only mark processed on success — an exception leaves it
                # NULL so a transient failure (Qwen timeout, DB hiccup) gets
                # retried next cycle instead of silently vanishing forever.
                event.pipeline_processed_at = datetime.now(timezone.utc)
                db.commit()
            except Exception as exc:
                db.rollback()
                print(f"    [event {event.id} FAILED, will retry next cycle] {exc}")
        print(f"pipeline run complete: {total_signals} signals produced")
    finally:
        db.close()


if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True:
            run_once()
            time.sleep(600)  # every 10 min
    else:
        run_once()
