"""
US equity market session-state detection.

Bitget's own stock-perp documentation confirms these tokenized-equity
perps trade 24/7 while their underlying reference market (NYSE/NASDAQ)
does not, and that Bitget runs a distinct index/mark-price smoothing
mechanism specifically during underlying-market closure hours. That means
"the underlying market is currently closed" is not incidental context —
it's the condition under which premium widening is structurally expected
rather than anomalous. This module exists so every oracle tick can be
labeled with the session it was taken in, and the dislocation engine
(dislocation.py) can distinguish "elevated premium during CLOSED" (expected,
lower alarm) from "elevated premium during REGULAR hours with the
underlying open and liquid" (more likely a genuine, tradeable dislocation).

No external calendar dependency — holidays are a maintained literal list
below rather than computed (e.g. Good Friday requires an Easter-date
algorithm that's more complexity than a hackathon-scope session detector
needs). Extend HOLIDAYS_BY_YEAR as years roll over; a stale list only ever
fails safe (mislabels a holiday as REGULAR), it never blocks anything.
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo
from app import config

_ET = ZoneInfo(config.US_EQUITY_SESSION["timezone"])

# NYSE/NASDAQ full-day market holidays. Source: exchange-published holiday
# calendars. Half days (e.g. day after Thanksgiving, Christmas Eve some
# years) are intentionally not modeled — worst case they're labeled
# REGULAR for the last couple of hours of an early close, which fails
# safe rather than wrongly suppressing a real session.
HOLIDAYS_BY_YEAR: dict[int, set[str]] = {
    2025: {
        "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18",
        "2025-05-26", "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27",
        "2025-12-25",
    },
    2026: {
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
        "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    },
    2027: {
        "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
        "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
    },
}

_PRE_MARKET_START = time.fromisoformat(config.US_EQUITY_SESSION["pre_market_start"])
_REGULAR_START = time.fromisoformat(config.US_EQUITY_SESSION["regular_start"])
_REGULAR_END = time.fromisoformat(config.US_EQUITY_SESSION["regular_end"])
_AFTER_HOURS_END = time.fromisoformat(config.US_EQUITY_SESSION["after_hours_end"])


def _is_holiday(dt_et: datetime) -> bool:
    return dt_et.strftime("%Y-%m-%d") in HOLIDAYS_BY_YEAR.get(dt_et.year, set())


def us_equity_session_state(as_of: datetime | None = None) -> str:
    """
    Returns one of PRE_MARKET | REGULAR | AFTER_HOURS | CLOSED for US
    equities/indices at `as_of` (defaults to now). Weekends and the
    literal holiday list above both resolve to CLOSED.
    """
    dt = (as_of or datetime.now(tz=ZoneInfo("UTC"))).astimezone(_ET)

    if dt.weekday() >= 5 or _is_holiday(dt):
        return "CLOSED"

    t = dt.time()
    if _PRE_MARKET_START <= t < _REGULAR_START:
        return "PRE_MARKET"
    if _REGULAR_START <= t < _REGULAR_END:
        return "REGULAR"
    if _REGULAR_END <= t < _AFTER_HOURS_END:
        return "AFTER_HOURS"
    return "CLOSED"


def session_state_for_asset(asset_type: str, as_of: datetime | None = None) -> str:
    """
    Crypto trades 24/7 by definition — session state only means something
    for tokenized equities and equity indices (SPY/QQQ), which reference
    an underlying that actually closes.
    """
    if asset_type == "crypto":
        return "CRYPTO_24_7"
    return us_equity_session_state(as_of)
