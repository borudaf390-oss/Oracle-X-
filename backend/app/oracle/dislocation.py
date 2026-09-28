"""
Dislocation engine — the actual "Oracle" in Oracle X.

Bitget publishes lastPr (last traded price), indexPrice, markPrice and
fundingRate for every perp on a single ticker call (confirmed against
Bitget's v2 mix/market/ticker and symbol-price docs). Mark price is itself
computed by Bitget as a clamped function of index price
(`clamp(indexPrice + orderbook-basis MA, indexPrice*0.97, indexPrice*1.03)`).
So the "dislocation" this module measures is genuine and requires no
external reference-market data feed:

    premium_pct = last_price / index_price - 1

For tokenized-equity perps specifically, Bitget documents a distinct
index/mark smoothing mechanism used during underlying-market closure
hours — meaning a widening premium while session_state == CLOSED is a
structurally expected phenomenon, not noise. See session.py.

Every function here operates on plain pandas Series/DataFrames (same
convention as quant/correlation.py etc.) so this stays independently
testable and swappable, the same way the rest of the quant engine is.
"""
import numpy as np
import pandas as pd
from app import config

_THRESH = config.ORACLE_THRESHOLDS


def premium_pct(last_price: float, index_price: float) -> float | None:
    if not index_price:
        return None
    return round(last_price / index_price - 1, 5)


def mark_basis_pct(mark_price: float, index_price: float) -> float | None:
    if not index_price or mark_price is None:
        return None
    return round(mark_price / index_price - 1, 5)


def premium_zscore(current_premium: float, historical_premiums: pd.Series) -> float:
    """
    How unusual is the current premium relative to this asset's own recent
    history? Mirrors quant/displacement.py::displacement_zscore's approach
    deliberately — same statistical language across the whole Alpha Score,
    not a bespoke metric just for the Oracle factor.

    This is the UNCONDITIONED baseline (pools every session state
    together) — session_conditioned_zscore() below is what oracle_state()
    actually uses when it can; this stays as its documented fallback and
    as a simpler building block other code can call directly.
    """
    hist = historical_premiums.dropna()
    if len(hist) < _THRESH["min_ticks_for_stats"]:
        return 0.0
    mean, std = hist.mean(), hist.std()
    if std == 0 or np.isnan(std):
        return 0.0
    return float((current_premium - mean) / std)


def session_conditioned_zscore(current_premium: float, historical: pd.DataFrame, current_session: str | None,
                                min_same_session_ticks: int = None) -> tuple[float, bool]:
    """
    Returns (zscore, was_session_conditioned).

    Bitget documents a distinct index/mark smoothing mechanism specifically
    during underlying-market closure hours for stock perps — meaning a
    CLOSED-session premium is drawn from a structurally different
    distribution than a REGULAR-session one. Pooling every session into
    one mean/std (premium_zscore's behavior) makes a routine CLOSED-hours
    premium look artificially extreme relative to whichever session
    dominates the pooled sample, or vice versa — exactly the conceptual
    gap flagged in review: "3σ during CLOSED" was scoring identically to
    "3σ during REGULAR" despite the code's own docs explaining why those
    should mean different things.

    Uses only same-session historical ticks for the baseline when there's
    enough of them (min_same_session_ticks); a 2-minute poll cadence means
    a same-session bucket (e.g. "REGULAR" only occurs ~6.5h/weekday) fills
    slower than the pooled sample, so this falls back to the unconditioned
    premium_zscore() while that bucket is still thin — that's a more
    honest state ("not yet session-adjusted") than either blocking the
    Oracle factor entirely or pretending a thin same-session sample is a
    reliable baseline.
    """
    if min_same_session_ticks is None:
        min_same_session_ticks = _THRESH["min_same_session_ticks"]
    if current_session and "session_state" in historical.columns:
        same_session = historical.loc[historical["session_state"] == current_session, "premium_pct"].dropna()
        if len(same_session) >= min_same_session_ticks:
            mean, std = same_session.mean(), same_session.std()
            if std and not np.isnan(std):
                return float((current_premium - mean) / std), True
    return premium_zscore(current_premium, historical["premium_pct"] if "premium_pct" in historical.columns else historical), False


def premium_percentile(current_premium: float, historical_premiums: pd.Series) -> float:
    """Where does the current premium fall in its own recent distribution, 0-100."""
    hist = historical_premiums.dropna()
    if hist.empty:
        return 50.0
    return round(float((hist < current_premium).mean() * 100), 1)


def premium_duration_minutes(ticks: pd.DataFrame) -> float:
    """
    How long (in real elapsed minutes) has the premium held the same sign
    (persistently positive or persistently negative) up through the most
    recent tick? `ticks` must have 'premium_pct' and 'timestamp' columns,
    ordered oldest -> newest. A one-off spike that flips sign next tick
    should score very differently from a premium that's held for an hour —
    this is what lets the Opportunity Card say "Duration: 47 min" rather
    than just a snapshot.

    Uses actual tick timestamps rather than an assumed polling interval —
    ingest_oracle_ticks.py's real cadence isn't guaranteed to be exactly
    the scheduler's nominal 2 minutes (retries, per-asset request latency
    across ~18 assets, scheduler jitter), so counting ticks and multiplying
    by an assumed interval could silently misstate duration. Real elapsed
    time between the oldest and newest tick in the current same-sign run
    is correct regardless of actual polling cadence.
    """
    valid = ticks.dropna(subset=["premium_pct", "timestamp"])
    if valid.empty:
        return 0.0
    current_sign = np.sign(valid["premium_pct"].iloc[-1])
    if current_sign == 0:
        return 0.0

    latest_ts = valid["timestamp"].iloc[-1]
    earliest_same_sign_ts = latest_ts
    for _, row in valid[::-1].iterrows():
        if np.sign(row["premium_pct"]) != current_sign:
            break
        earliest_same_sign_ts = row["timestamp"]

    delta = latest_ts - earliest_same_sign_ts
    return round(delta.total_seconds() / 60, 1)


def premium_velocity(ticks: pd.DataFrame, window_minutes: float = 10.0) -> float:
    """
    Rate of change of the premium over the trailing window_minutes, in
    pct-points per 5 minutes. `ticks` must have 'premium_pct' and
    'timestamp' columns. Finds the tick at/before (latest - window_minutes)
    by actual elapsed time rather than assuming a fixed tick cadence and
    counting back a fixed number of rows — see premium_duration_minutes'
    docstring for why that assumption is unsafe.
    """
    valid = ticks.dropna(subset=["premium_pct", "timestamp"])
    if len(valid) < 2:
        return 0.0
    latest_ts = valid["timestamp"].iloc[-1]
    latest_premium = valid["premium_pct"].iloc[-1]
    cutoff = latest_ts - pd.Timedelta(minutes=window_minutes)

    past = valid[valid["timestamp"] <= cutoff]
    if past.empty:
        return 0.0  # not enough history to cover the full window yet
    reference_row = past.iloc[-1]  # latest tick at/before the cutoff
    elapsed_minutes = (latest_ts - reference_row["timestamp"]).total_seconds() / 60
    if elapsed_minutes <= 0:
        return 0.0

    delta = float(latest_premium - reference_row["premium_pct"])
    return round(delta / elapsed_minutes * 5, 5)


def funding_zscore(current_funding: float, historical_funding: pd.Series) -> float:
    hist = historical_funding.dropna()
    if len(hist) < _THRESH["min_ticks_for_stats"]:
        return 0.0
    mean, std = hist.mean(), hist.std()
    if std == 0 or np.isnan(std):
        return 0.0
    return float((current_funding - mean) / std)


def classify_dislocation(zscore: float) -> str:
    az = abs(zscore)
    if az >= _THRESH["dislocated_premium_zscore"]:
        return "DISLOCATED"
    if az >= _THRESH["elevated_premium_zscore"]:
        return "ELEVATED"
    return "NORMAL"


def oracle_regime_factor(premium_zscore: float, funding_zscore: float = 0.0) -> float:
    """
    Squash both the premium z-score and the funding-rate z-score into a
    single 0..1 factor for compose_alpha_score(), taking whichever is more
    extreme. funding_zscore() was previously computed and displayed on the
    Oracle panel but never actually influenced this factor at all — an
    unusually extreme funding rate (the market paying an unusual premium to
    stay crowded long or short) is a distinct kind of market-structure
    signal from price/index premium dislocation, and either one being
    unusual is evidence the Oracle layer should surface, not premium alone.

    Uses max rather than an average so one strongly extreme signal isn't
    diluted by the other being unremarkable. This is a considered design
    choice for combining two already-comparable (both /3-clipped) signals,
    not a formula confirmed against any external reference — same
    min(|z|/3, 1) scaling quant/displacement.py uses for its own z-score,
    applied to both inputs before combining them.
    """
    premium_component = min(max(abs(premium_zscore) / 3, 0.0), 1.0)
    funding_component = min(max(abs(funding_zscore) / 3, 0.0), 1.0)
    return float(max(premium_component, funding_component))


def oracle_state(current_tick: dict, historical: pd.DataFrame) -> dict:
    """
    Full snapshot for one asset's Opportunity Card Oracle panel and for
    the Alpha Analyst's oracle_regime factor. `current_tick` is the latest
    row as a dict (last_price, index_price, mark_price, funding_rate,
    session_state, timestamp); `historical` is prior oracle_ticks rows
    (oldest -> newest, premium_pct/funding_rate/timestamp columns already
    populated) used as the baseline for z-score/percentile/duration/velocity.
    """
    premium = current_tick.get("premium_pct")
    if premium is None:
        return {"status": "NO_DATA"}

    session_state = current_tick.get("session_state")
    if not historical.empty:
        z, session_conditioned = session_conditioned_zscore(premium, historical, session_state)
    else:
        z, session_conditioned = 0.0, False
    # Timestamp is carried through (not just premium_pct) so
    # premium_duration_minutes/premium_velocity can use real elapsed time
    # rather than assuming a fixed polling interval — see those functions'
    # docstrings for why that assumption was unsafe.
    current_row = {"premium_pct": premium, "timestamp": current_tick.get("timestamp")}
    combined = pd.concat(
        [historical[["premium_pct", "timestamp"]], pd.DataFrame([current_row])],
        ignore_index=True,
    ) if not historical.empty else pd.DataFrame([current_row])

    funding_z = round(
        funding_zscore(current_tick.get("funding_rate", 0.0) or 0.0, historical["funding_rate"]), 3
    ) if not historical.empty and "funding_rate" in historical else 0.0

    return {
        "status": "OK",
        "last_price": current_tick.get("last_price"),
        "index_price": current_tick.get("index_price"),
        "mark_price": current_tick.get("mark_price"),
        "funding_rate": current_tick.get("funding_rate"),
        "premium_pct": premium,
        "premium_zscore": round(z, 3),
        "premium_percentile": premium_percentile(premium, historical["premium_pct"]) if not historical.empty else 50.0,
        "premium_duration_minutes": premium_duration_minutes(combined),
        "premium_velocity": premium_velocity(combined),
        "funding_zscore": funding_z,
        "session_state": current_tick.get("session_state"),
        "session_conditioned": session_conditioned,
        "regime": classify_dislocation(z),
        "oracle_regime_factor": oracle_regime_factor(z, funding_z),
    }
