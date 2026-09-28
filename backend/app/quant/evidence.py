"""
Signal Evidence Graph.

reason_json previously held all the numbers a signal was built from, but
as a flat bag of fields with no explicit ordering or narrative structure —
a consumer (frontend, Narrator) had to already know which fields to pull
out and in what order to tell the "why was this surfaced" story. This
module builds that story as an explicit ordered list instead:

    EVENT -> RELATIONSHIP -> EXPECTED REACTION -> CURRENT REACTION ->
    DISPLACEMENT -> ORACLE -> RISK -> NARRATIVE

The first six steps are built in agents/alpha.py at signal-creation time
(everything it already computed); RiskGate.evaluate() and
Narrator.narrate() each append their own step afterward, once those
stages actually run — so a signal that hasn't been risk-checked yet has a
chain missing that step rather than a fabricated placeholder.

Every step is {"step": name, "label": human-readable one-liner, "data": {...}}
so the frontend can render `label` directly without re-deriving it, while
`data` keeps the raw numbers for anything that wants them.
"""
from datetime import datetime, timezone


def event_step(source_event, leader_symbol: str, leader_move_pct: float) -> dict:
    direction_word = "up" if leader_move_pct >= 0 else "down"
    return {
        "step": "event",
        "label": f"{leader_symbol} {direction_word} {abs(leader_move_pct) * 100:.2f}% — {source_event.headline[:100]}",
        "data": {
            "leader_symbol": leader_symbol,
            "leader_move_pct": leader_move_pct,
            "event_type": source_event.event_type,
            "sentiment": source_event.sentiment,
            "magnitude": float(source_event.magnitude) if source_event.magnitude is not None else None,
            "timestamp": source_event.timestamp.isoformat() if source_event.timestamp else None,
        },
    }


def relationship_step(leader_symbol: str, candidate: dict, lag_hours: int,
                       lag_supports_causal_direction: bool) -> dict:
    corr = candidate["correlation"]
    raw_lag = candidate["lead_lag_hours"]
    if raw_lag > 0:
        timing = f"{leader_symbol} leads {candidate['symbol']} by ~{raw_lag:.0f}h"
    elif raw_lag < 0:
        timing = f"{candidate['symbol']} actually leads {leader_symbol} by ~{abs(raw_lag):.0f}h (unexpected direction)"
    else:
        timing = f"{leader_symbol} and {candidate['symbol']} move together with no clear lead/lag"

    qualifiers = []
    if candidate.get("same_sector"):
        qualifiers.append("same sector")
    if candidate.get("qwen_flagged"):
        qualifiers.append("Qwen-flagged")
    qualifier_str = f" ({', '.join(qualifiers)})" if qualifiers else ""

    return {
        "step": "relationship",
        "label": f"{timing}, correlation {corr:+.2f}{qualifier_str}",
        "data": {
            "correlation": corr,
            "lead_lag_hours": raw_lag,
            "reaction_window_hours": lag_hours,
            "causal_direction_supported": lag_supports_causal_direction,
            "same_sector": candidate.get("same_sector"),
            "qwen_flagged": candidate.get("qwen_flagged"),
        },
    }


def expected_reaction_step(follower_symbol: str, expected_move_pct: float, r_squared: float,
                            sample_size: int) -> dict:
    return {
        "step": "expected_reaction",
        "label": f"Historically, {follower_symbol} moves {expected_move_pct * 100:+.2f}% in this "
                 f"situation (r²={r_squared:.2f}, n={sample_size})",
        "data": {
            "expected_move_pct": expected_move_pct,
            "r_squared": r_squared,
            "sample_size": sample_size,
        },
    }


def current_reaction_step(follower_symbol: str, current_move_pct: float, lag_hours: int) -> dict:
    return {
        "step": "current_reaction",
        "label": f"{follower_symbol} has actually moved {current_move_pct * 100:+.2f}% "
                 f"over the last {lag_hours}h",
        "data": {"current_move_pct": current_move_pct, "window_hours": lag_hours},
    }


def displacement_step(follower_symbol: str, gap: float, direction: str) -> dict:
    return {
        "step": "displacement",
        "label": f"Displacement: {gap * 100:+.2f}% not yet reflected in {follower_symbol} "
                 f"({direction} opportunity)",
        "data": {"displacement_pct": gap, "direction": direction},
    }


def oracle_step(oracle_snapshot: dict, symbol: str) -> dict | None:
    if not oracle_snapshot or oracle_snapshot.get("status") != "OK":
        return None
    return {
        "step": "oracle",
        "label": f"{symbol} trading at {oracle_snapshot['premium_pct'] * 100:+.2f}% vs index "
                 f"({oracle_snapshot['regime']}, underlying {oracle_snapshot.get('session_state')})",
        "data": oracle_snapshot,
    }


def risk_step(passed: bool, checks: dict) -> dict:
    if passed:
        label = "Risk Gate: PASS — all checks cleared"
    else:
        # Distinguish an UNKNOWN input (missing portfolio/ATR data — see
        # RiskGate._check's fail-closed design) from an actual threshold
        # breach (FAIL), since they mean different things to a trader
        # deciding whether to act on this signal anyway.
        failed = [
            f"{name} ({c.get('status', 'FAIL')})"
            for name, c in checks.items() if not c["pass"]
        ]
        label = f"Risk Gate: BLOCK — {', '.join(failed)}"
    return {
        "step": "risk",
        "label": label,
        "data": {"passed": passed, "checks": checks},
    }


def narrative_step(narrative_text: str) -> dict:
    return {
        "step": "narrative",
        "label": narrative_text,
        "data": {"generated_at": datetime.now(timezone.utc).isoformat()},
    }


def append_step(reason_json: dict, step: dict | None) -> dict:
    """Appends one step to an existing evidence_chain (creating it if absent), returns the updated reason_json."""
    if step is None:
        return reason_json
    reason_json = dict(reason_json or {})
    chain = list(reason_json.get("evidence_chain", []))
    chain.append(step)
    reason_json["evidence_chain"] = chain
    return reason_json
