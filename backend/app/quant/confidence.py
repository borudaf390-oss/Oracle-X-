"""
Confidence decomposition.

The old `confidence` field was computed as
`min(alpha_score, r_squared*100 + alpha_score*0.3)` — i.e. it was
mathematically incapable of exceeding alpha_score, and alpha_score is
"strength of the opportunity," a completely different question from
"how much should you trust this number." That conflation is what this
module removes:

    alpha_score      -> strength of the opportunity (agents/alpha.py, unchanged)
    model_confidence -> statistical reliability of the leader/follower
                         relationship this signal is built on, independent
                         of how good the opportunity looks
    data_confidence  -> freshness/completeness of the market data behind it,
                         independent of both of the above
    confidence       -> a single headline number for the UI, but now an
                         honest function of the two measures above
"""
from datetime import datetime, timezone
from app import config

_THRESH = config.CONFIDENCE_THRESHOLDS


def sample_size_adequacy(sample_size: int) -> float:
    """
    0..1 — how much to trust r_squared given how few historical analogues
    it's based on. A relationship measured on 3 events can show a great
    r_squared by chance; this shrinks confidence in that r_squared until
    the sample is large enough (min_robust_sample) to take at face value.
    """
    min_sample = _THRESH["min_robust_sample"]
    if min_sample <= 0:
        return 1.0
    return min(1.0, max(0, sample_size) / min_sample)


def model_confidence(r_squared: float, sample_size: int) -> float:
    """0..100. Statistical reliability of the relationship alone."""
    r2 = max(0.0, min(1.0, r_squared or 0.0))
    return round(r2 * 100 * sample_size_adequacy(sample_size), 2)


def staleness_minutes(last_data_timestamp: datetime | None) -> float:
    if last_data_timestamp is None:
        return float("inf")
    ts = last_data_timestamp if last_data_timestamp.tzinfo else last_data_timestamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 60


def data_confidence(last_data_timestamp: datetime | None, backfill_coverage_pct: float | None,
                     oracle_available: bool) -> float:
    """
    0..100. Freshness + historical-coverage completeness of the data behind
    this signal — a perfectly-correlated relationship computed on stale or
    thin data shouldn't read as trustworthy just because the relationship
    itself looks good.
    """
    staleness = staleness_minutes(last_data_timestamp)
    max_staleness = _THRESH["max_fresh_staleness_minutes"]
    freshness_score = 0.0 if staleness == float("inf") else max(0.0, min(1.0, 1 - staleness / max_staleness))
    coverage_score = min(1.0, max(0.0, backfill_coverage_pct or 0.0) / 100)
    # Oracle ticks are a bonus signal (premium/dislocation), not a
    # prerequisite — their absence (e.g. feed still warming up) shouldn't
    # tank data_confidence the way stale candles or thin backfill should.
    oracle_score = 1.0 if oracle_available else 0.6
    blended = freshness_score * 0.5 + coverage_score * 0.35 + oracle_score * 0.15
    return round(blended * 100, 2)


def composite_confidence(model_conf: float, data_conf: float) -> float:
    """
    Headline confidence shown in the UI. Geometric mean rather than a
    plain average, so a signal can't read as confident overall by being
    strong on just one axis alone (e.g. pristine data behind a
    relationship with r_squared near zero) — both need to hold up.
    """
    return round((max(model_conf, 0.0) * max(data_conf, 0.0)) ** 0.5, 2)
