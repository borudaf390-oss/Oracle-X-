"""
Signal Contract — the boundary between Oracle X's research engine and
anything that translates its output into an external format (currently:
the GetAgent Playbook translator in translator.py).

This exists specifically so a downstream consumer NEVER re-derives the
relationship itself from raw history. That would reopen exactly the
temporal-leakage class of bug the AS_OF refactor (see agents/relationship.py,
quant/historical_analogues.py) closed — a Playbook strategy.py that
recomputes correlation/lag against unrestricted historical data at
whatever moment the backtest engine happens to evaluate it is not
meaningfully different from the original leaky RelationshipHunter.

So the contract is a LOCKED, frozen snapshot: the relationship (leader,
follower, lag, correlation) Oracle X discovered as of a specific
timestamp, plus the deterministic trigger/risk thresholds that
justified the signal. A translator or strategy consuming this contract
tests that fixed hypothesis against new data — it does not get to
rediscover the hypothesis itself. Walk-forward re-discovery during
backtesting is a legitimate, more sophisticated thing to eventually
build, but deliberately not this first bridge (see translator.py's
docstring).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models import Signal, Event, Asset
from app.jobs.ingest_market_data import resolve_and_cache_symbol
from app.jobs.run_pipeline import PER_TRADE_DEFAULTS
from app.data.bitget_client import BitgetClient
from app import config

CONTRACT_VERSION = "1.0"


@dataclass
class LockedRelationshipContract:
    """Everything a translator needs, and nothing it needs to look up itself."""
    contract_version: str
    generated_at: str
    source_signal_id: int
    discovered_as_of: str  # ISO timestamp — the event.timestamp this relationship was fit against
    leader_symbol: str      # Bitget-resolved perp symbol, e.g. "NVDAUSDT"
    follower_symbol: str    # Bitget-resolved perp symbol, e.g. "AMDUSDT"
    lag_hours: int
    correlation: float
    causal_direction_supported: bool
    direction: str  # "LONG" | "SHORT"
    leader_move_pct_at_signal: float
    expected_follower_move_pct: float
    observed_follower_move_pct_at_signal: float
    displacement_pct_at_signal: float
    oracle_premium_zscore_at_signal: float | None
    oracle_regime_at_signal: str | None
    oracle_session_state_at_signal: str | None
    alpha_score: float
    model_confidence: float | None
    data_confidence: float | None
    sample_size: int | None
    risk_limits: dict
    proposed_position_pct: float
    stop_distance_pct: float
    backtest_total_days: int
    backtest_oos_days: int
    narrative: str | None
    # Precomputed for backtest.yaml's fixed literal trade_size (confirmed
    # pattern from official examples — NOT computed dynamically from
    # portfolio equity inside strategy.py, which was an earlier incorrect
    # assumption). See build_locked_relationship_contract()'s docstring.
    backtest_starting_balance_usdt: float
    backtest_trade_size: str
    follower_reference_price: float
    # Real Bitget instrument rules for the follower contract — confirmed
    # field names (pricePlace/priceEndStep/volumePlace/sizeMultiplier/
    # minTradeNum/makerFeeRate/takerFeeRate) via Bitget's own published
    # example response plus two independent third-party SDK type
    # definitions, not just one source. An earlier version of this
    # contract left these as hardcoded placeholders copied from an
    # unrelated BTC example — a real, dangerous gap given
    # instrument.size_precision directly controls the generated
    # strategy's order quantity.
    follower_price_precision: int
    follower_size_precision: int
    follower_price_increment: str
    follower_size_increment: str
    follower_min_trade_num: float
    follower_maker_fee: str
    follower_taker_fee: str


_KNOWN_QUOTE_COINS = ("USDT", "USDC")


def _resolve_instrument_metadata(client: BitgetClient, symbol: str) -> dict:
    """
    Looks up symbol's real contract rules from Bitget's v2 mix/market/contracts
    response. Field names (pricePlace, priceEndStep, volumePlace,
    sizeMultiplier, minTradeNum, makerFeeRate, takerFeeRate) confirmed via
    Bitget's own published example response plus two independent
    third-party SDK type definitions — not verified against a live call in
    this codebase's own test suite, but corroborated across multiple
    independent sources rather than a single one.

    price_increment is derived as priceEndStep * 10^-pricePlace (Bitget
    expresses the increment step in units of the smallest price place, not
    as a standalone decimal) — this derivation itself is inferred from how
    the fields relate conceptually, not independently confirmed against a
    live response either.

    Raises if the symbol isn't found — fails loudly rather than silently
    falling back to guessed precision, since wrong precision here directly
    controls the generated strategy's order quantity.
    """
    data = client.get_contracts()  # class-level cached (see bitget_client.py) — cheap to call again here
    contracts = data.get("data", [])
    for c in contracts:
        if c.get("symbol", "").upper() == symbol.upper():
            price_place = int(c.get("pricePlace", 2))
            price_end_step = float(c.get("priceEndStep", 1))
            return {
                "price_precision": price_place,
                "size_precision": int(c.get("volumePlace", 3)),
                "price_increment": str(price_end_step * (10 ** -price_place)),
                "size_increment": str(c.get("sizeMultiplier", "0.001")),
                "min_trade_num": float(c.get("minTradeNum", 0.0) or 0.0),
                "maker_fee": str(c.get("makerFeeRate", "0.0002")),
                "taker_fee": str(c.get("takerFeeRate", "0.0006")),
            }
    raise ValueError(f"no contract metadata found for {symbol} in Bitget's contract list")


def build_locked_relationship_contract(db: Session, signal_id: int) -> LockedRelationshipContract:
    """
    Builds a frozen contract from an existing Signal. Refuses signals that
    haven't cleared the deterministic Risk Gate — translating a BLOCKed or
    still-PENDING signal into an external strategy artifact would bypass
    the entire point of having a risk gate in the first place.
    """
    signal = db.query(Signal).get(signal_id)
    if signal is None:
        raise ValueError(f"no signal with id={signal_id}")
    if signal.risk_status != "PASS":
        raise ValueError(
            f"signal {signal_id} has risk_status={signal.risk_status!r}, not PASS — "
            f"refusing to export a signal that hasn't cleared the deterministic Risk Gate"
        )

    event = db.query(Event).get(signal.triggering_event_id)
    follower_asset = db.query(Asset).get(signal.asset_id)
    leader_asset = db.query(Asset).get(event.asset_id) if event else None
    if not event or not follower_asset or not leader_asset:
        raise ValueError(f"signal {signal_id} is missing its event/asset linkage — cannot export")

    reason = signal.reason_json or {}
    oracle = reason.get("oracle") or {}
    confidence_breakdown = reason.get("confidence_breakdown") or {}

    # Resolve to the actual live Bitget perp symbols (e.g. "NVDA" -> "NVDAUSDT"),
    # the same resolver ingest_market_data.py uses — not a naive string
    # concatenation, since that's exactly the kind of unverified assumption
    # the competitor evidence (RWA-spot symbols returning empty on GetAgent's
    # replay platform) showed can silently produce an unbacktestable strategy.
    client = BitgetClient()
    symbol_cache: dict = {}
    leader_symbol = resolve_and_cache_symbol(client, leader_asset, symbol_cache)
    follower_symbol = resolve_and_cache_symbol(client, follower_asset, symbol_cache)
    if not leader_symbol or not follower_symbol:
        raise ValueError(
            f"could not resolve a live Bitget perp symbol for "
            f"{leader_asset.symbol}/{follower_asset.symbol} — cannot export a "
            f"strategy against a symbol Bitget doesn't currently list"
        )

    # Precompute a fixed literal trade_size for backtest.yaml's strategy.config
    # block — CONFIRMED to be the real pattern (a fixed decimal-string
    # quantity like "0.01" or "10", set declaratively) after retrieving
    # actual official examples; an earlier version of this contract instead
    # tried to compute position size dynamically inside strategy.py from
    # portfolio equity at runtime, which doesn't match how any confirmed
    # example works. notional = starting_balance * proposed_position_pct,
    # qty = notional / reference_price — computed ONCE here, at export
    # time, using a live price, not re-derived inside the strategy.
    #
    # IMPORTANT CAVEAT (flagged, not resolved): this produces a quantity
    # sized correctly at EXPORT-TIME price only. If the backtest window's
    # starting price differs meaningfully from today's price, the same
    # fixed quantity represents a different fraction of the starting
    # balance at the start of the backtest than proposed_position_pct
    # claims. Whether GetAgent's backtest semantics expect (and account
    # for) this, or whether it's a real economic distortion, has not been
    # verified against the sandbox. Do not interpret a resulting backtest
    # as a clean "N% of equity" risk analog without checking this first.
    starting_balance_usdt = 100_000.0  # matches the confirmed examples' starting_balances convention
    ticker = client.get_ticker(follower_symbol)
    rows = ticker.get("data", [])
    if not rows:
        raise ValueError(f"could not fetch a live ticker for {follower_symbol} — cannot size the backtest trade_size")
    follower_reference_price = float(rows[0]["lastPr"])
    if follower_reference_price <= 0:
        raise ValueError(f"invalid reference price for {follower_symbol}: {follower_reference_price}")

    instrument_meta = _resolve_instrument_metadata(client, follower_symbol)

    position_pct = PER_TRADE_DEFAULTS["proposed_position_pct"]
    notional = starting_balance_usdt * position_pct
    raw_qty = notional / follower_reference_price
    # Rounded to the follower's REAL size_precision (not a hardcoded 3dp
    # guess), and floored up to min_trade_num if the computed size would
    # otherwise be unfillable — an order below the exchange minimum isn't a
    # smaller position, it's a rejected order.
    rounded_qty = round(raw_qty, instrument_meta["size_precision"])
    min_qty = instrument_meta["min_trade_num"]
    if min_qty and rounded_qty < min_qty:
        rounded_qty = min_qty
    backtest_trade_size = str(rounded_qty)

    return LockedRelationshipContract(
        contract_version=CONTRACT_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(),
        source_signal_id=signal.id,
        discovered_as_of=event.timestamp.isoformat(),
        leader_symbol=leader_symbol,
        follower_symbol=follower_symbol,
        lag_hours=int(reason.get("reaction_window_hours", 1)),
        correlation=float(reason.get("correlation", 0.0)),
        causal_direction_supported=bool(reason.get("lag_supports_causal_direction", False)),
        direction=signal.direction,
        leader_move_pct_at_signal=float(reason.get("leader_move_pct", 0.0)),
        expected_follower_move_pct=float(signal.expected_move_pct or 0.0),
        observed_follower_move_pct_at_signal=float(signal.current_move_pct or 0.0),
        displacement_pct_at_signal=float(signal.displacement_pct or 0.0),
        oracle_premium_zscore_at_signal=oracle.get("premium_zscore"),
        oracle_regime_at_signal=oracle.get("regime"),
        oracle_session_state_at_signal=oracle.get("session_state"),
        alpha_score=float(signal.alpha_score),
        model_confidence=float(confidence_breakdown.get("model_confidence")) if confidence_breakdown.get("model_confidence") is not None else None,
        data_confidence=float(confidence_breakdown.get("data_confidence")) if confidence_breakdown.get("data_confidence") is not None else None,
        sample_size=confidence_breakdown.get("sample_size"),
        risk_limits=dict(config.RISK_LIMITS),
        proposed_position_pct=position_pct,
        stop_distance_pct=PER_TRADE_DEFAULTS["stop_distance_pct"],
        backtest_total_days=60,
        backtest_oos_days=30,
        narrative=signal.narrative,
        backtest_starting_balance_usdt=starting_balance_usdt,
        backtest_trade_size=backtest_trade_size,
        follower_reference_price=follower_reference_price,
        follower_price_precision=instrument_meta["price_precision"],
        follower_size_precision=instrument_meta["size_precision"],
        follower_price_increment=instrument_meta["price_increment"],
        follower_size_increment=instrument_meta["size_increment"],
        follower_min_trade_num=instrument_meta["min_trade_num"],
        follower_maker_fee=instrument_meta["maker_fee"],
        follower_taker_fee=instrument_meta["taker_fee"],
    )
