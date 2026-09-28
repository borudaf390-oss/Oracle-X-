"""
Agent 4 — Alpha Analyst (spec section 12).
Combines quantitative features into an Alpha Score and creates the Signal
row. Does NOT decide whether the signal is allowed to trade — that's
Risk Guardian's job (risk_analyst.py + risk_gate.py), run after this.
"""
import pandas as pd
from sqlalchemy.orm import Session
from app.models import Asset, MarketData, Event, Signal
from app.quant.displacement import expected_reaction, displacement_gap, displacement_zscore
from app.quant.momentum import momentum_score, volume_abnormality
from app.quant.regime import classify_regime, regime_factor_for_alpha
from app.quant.scoring import get_live_weights, compose_alpha_score, score_band
from app.quant.historical_analogues import analogue_summary
from app.quant.confidence import model_confidence, data_confidence, composite_confidence
from app.quant import evidence
from app.jobs.ingest_market_data import actual_coverage_days, BACKFILL_DAYS
from app.oracle.query import ticks_df
from app.oracle.dislocation import oracle_state


class AlphaAnalyst:
    def __init__(self, db: Session):
        self.db = db

    def _series(self, asset_id: int, field: str, timeframe: str = "1h", as_of=None) -> pd.Series:
        """as_of: only rows with timestamp <= as_of — see analyze()'s docstring for when this matters."""
        query = self.db.query(MarketData).filter(
            MarketData.asset_id == asset_id, MarketData.timeframe == timeframe
        )
        if as_of is not None:
            query = query.filter(MarketData.timestamp <= as_of)
        rows = query.order_by(MarketData.timestamp.asc()).all()
        if not rows:
            return pd.Series(dtype=float)
        values = [float(getattr(r, field)) for r in rows]
        return pd.Series(values, index=[r.timestamp for r in rows])

    def analyze(self, source_event: Event, candidate: dict, historical_pairs: pd.DataFrame,
                lag_hours: int = 1, as_of=None) -> Signal:
        """
        candidate: one entry from RelationshipHunter.find_propagation_candidates()
        historical_pairs: past (leader_move_pct, follower_move_pct) analogues
        for this asset pair, used by displacement.expected_reaction() — must
        already be built with the same lag_hours AND the same temporal
        boundary as this call (run_pipeline.py passes as_of=event.timestamp
        to find_historical_pairs()) or the fitted relationship won't match
        what current_move_pct below is actually measuring.
        lag_hours: the empirically-discovered propagation delay for this pair
        (RelationshipHunter's lead_lag_hours). current_move_pct is measured
        over this window rather than a hardcoded single bar — checking only
        the most recent 1h bar understates/overstates how much of the
        reaction has developed when the real propagation delay is longer.

        as_of: NOT the same boundary as historical_pairs' — a deliberate,
        documented distinction, not an inconsistency:
          - Relationship DISCOVERY (RelationshipHunter, find_historical_pairs)
            must be bounded to <= event.timestamp, because it's answering
            "what was this relationship knowable to be, before the event."
            Letting it see data from after the event is exactly the
            temporal leakage this refactor removes.
          - Observation of CURRENT state (this method's candidate_close,
            leader_close, regime inputs, oracle snapshot) is answering "how
            has the market actually moved since the event" — that
            necessarily needs data AFTER the event, up to whenever this is
            being processed. Bounding it to event.timestamp would make
            current_move_pct always read as zero.
        run_pipeline.py leaves `as_of` as None (unbounded — use live,
        current data) for normal live signal generation. This parameter
        exists so the same code can be replayed deterministically as of any
        past timestamp (e.g. for testing or auditing a specific historical
        signal) by passing that timestamp here explicitly.
        """
        candidate_close = self._series(candidate["asset_id"], "close", as_of=as_of)
        candidate_volume = self._series(candidate["asset_id"], "volume", as_of=as_of)

        current_move_pct = float(
            candidate_close.iloc[-1] / candidate_close.iloc[-1 - lag_hours] - 1
        ) if len(candidate_close) > lag_hours else 0.0

        # B3 — leader_move alignment:
        # Prefer the move of the bar that contains (or immediately follows)
        # the event timestamp, not the latest live 1h bar. Using the live
        # bar made the Evidence Chain imply the event caused a move that
        # may have happened hours later for unrelated reasons.
        # Fallback chain:
        #   1. bar at/after event.timestamp (first close >= event time)
        #   2. last bar strictly before event (if no post-event bar yet)
        #   3. latest bar (legacy) only if series has no usable timestamps
        leader_close = self._series(source_event.asset_id, "close", as_of=as_of)
        leader_move_pct = 0.0
        event_ts = getattr(source_event, "timestamp", None)
        if len(leader_close) > 1 and event_ts is not None:
            try:
                # Normalize to tz-aware comparable index
                idx = leader_close.index
                # Find first bar at or after the event
                post = leader_close[idx >= event_ts]
                if len(post) >= 1:
                    # Use the first post-event bar vs the bar immediately before it
                    i = leader_close.index.get_loc(post.index[0])
                    if isinstance(i, slice):
                        i = i.start
                    if i is not None and i > 0:
                        leader_move_pct = float(leader_close.iloc[i] / leader_close.iloc[i - 1] - 1)
                    elif i == 0 and len(leader_close) > 1:
                        leader_move_pct = float(leader_close.iloc[0] / leader_close.iloc[1] - 1)  # degenerate
                else:
                    # No post-event bar yet — use last pre-event bar vs prior
                    pre = leader_close[idx < event_ts]
                    if len(pre) > 1:
                        leader_move_pct = float(pre.iloc[-1] / pre.iloc[-2] - 1)
                    elif len(leader_close) > 1:
                        leader_move_pct = float(leader_close.iloc[-1] / leader_close.iloc[-2] - 1)
            except Exception:
                leader_move_pct = float(
                    leader_close.iloc[-1] / leader_close.iloc[-2] - 1
                ) if len(leader_close) > 1 else 0.0
        elif len(leader_close) > 1:
            leader_move_pct = float(leader_close.iloc[-1] / leader_close.iloc[-2] - 1)

        expected_move_pct, r_squared = expected_reaction(leader_move_pct, historical_pairs)
        gap = displacement_gap(expected_move_pct, current_move_pct)

        historical_gaps = (
            historical_pairs["follower_move_pct"] - historical_pairs["leader_move_pct"]
            if not historical_pairs.empty else pd.Series(dtype=float)
        )
        z = displacement_zscore(gap, historical_gaps)
        displacement_factor = min(max(abs(z) / 3, 0.0), 1.0)  # squash to 0..1

        mom = (momentum_score(candidate_close) + 1) / 2  # 0..1
        vol_abnormality = volume_abnormality(candidate_volume)

        btc_close = self._series(
            self.db.query(Asset).filter(Asset.symbol == "BTC").first().id, "close", as_of=as_of
        )
        qqq_close = self._series(
            self.db.query(Asset).filter(Asset.symbol == "QQQ").first().id, "close", as_of=as_of
        )
        regime = classify_regime(btc_close, qqq_close)
        regime_factor = regime_factor_for_alpha(regime)

        # Oracle factor: token(last_price) vs Bitget's own index_price
        # dislocation for the candidate asset (app/oracle/dislocation.py).
        # Degrades to a neutral 0.0 factor + explicit NO_DATA status when
        # oracle_ticks hasn't accumulated enough history yet, rather than
        # erroring the whole analyze() call over a still-warming-up feed.
        oracle_df = ticks_df(self.db, candidate["asset_id"], as_of=as_of)
        if not oracle_df.empty:
            oracle_current = oracle_df.iloc[-1].to_dict()
            oracle_snapshot = oracle_state(oracle_current, oracle_df.iloc[:-1])
        else:
            oracle_snapshot = {"status": "NO_DATA"}
        oracle_factor = float(oracle_snapshot.get("oracle_regime_factor", 0.0))

        factors = {
            "cross_market_displacement": displacement_factor,
            "momentum": mom,
            "volume_abnormality": vol_abnormality,
            "event_strength": float(source_event.magnitude or 0.0),
            "historical_conditional_probability": r_squared,
            "market_regime": regime_factor,
            "oracle_regime": oracle_factor,
        }
        weights = get_live_weights(self.db)
        alpha_score = compose_alpha_score(factors, weights)

        # Confidence decomposition (app/quant/confidence.py) — deliberately
        # NOT derived from alpha_score. sample_size is how many historical
        # analogues expected_reaction()'s r_squared was fit on; coverage_pct
        # is how much of the target backfill window actually exists for
        # this asset right now (not what a backfill job merely attempted).
        sample_size = int(len(historical_pairs)) if historical_pairs is not None else 0
        last_data_ts = candidate_close.index[-1] if len(candidate_close) else None
        coverage_pct = min(actual_coverage_days(self.db, candidate["asset_id"]) / BACKFILL_DAYS, 1.0) * 100 \
            if BACKFILL_DAYS else 0.0
        oracle_available = oracle_snapshot.get("status") == "OK"

        model_conf = model_confidence(r_squared, sample_size)
        data_conf = data_confidence(last_data_ts, coverage_pct, oracle_available)
        confidence = composite_confidence(model_conf, data_conf)

        direction = "LONG" if gap > 0 else "SHORT"
        analogues = analogue_summary(historical_pairs, leader_move_pct) if not historical_pairs.empty else {
            "similar_events": 0, "follow_through_rate": 0.0, "median_move": 0.0, "average_move": 0.0
        }

        leader_symbol = self.db.query(Asset).get(source_event.asset_id).symbol
        lag_supports_causal_direction = candidate.get("causal_direction_supported", candidate["lead_lag_hours"] > 0)

        # Signal Evidence Graph (app/quant/evidence.py): the explicit,
        # ordered "why was this surfaced" chain. Risk Gate and the
        # Narrator each append their own step later, once those stages
        # actually run on this signal.
        evidence_chain = [
            evidence.event_step(source_event, leader_symbol, leader_move_pct),
            evidence.relationship_step(leader_symbol, candidate, lag_hours, lag_supports_causal_direction),
            evidence.expected_reaction_step(candidate["symbol"], expected_move_pct, r_squared, sample_size),
            evidence.current_reaction_step(candidate["symbol"], current_move_pct, lag_hours),
            evidence.displacement_step(candidate["symbol"], gap, direction),
        ]
        oracle_evidence = evidence.oracle_step(oracle_snapshot, candidate["symbol"])
        if oracle_evidence:
            evidence_chain.append(oracle_evidence)

        signal = Signal(
            asset_id=candidate["asset_id"],
            triggering_event_id=source_event.id,
            direction=direction,
            alpha_score=alpha_score,
            confidence=confidence,
            model_confidence=model_conf,
            data_confidence=data_conf,
            sample_size=sample_size,
            expected_move_pct=expected_move_pct,
            current_move_pct=current_move_pct,
            displacement_pct=gap,
            reason_json={
                "leader_symbol": leader_symbol,
                "leader_move_pct": leader_move_pct,
                "correlation": candidate["correlation"],
                "lead_lag_hours": candidate["lead_lag_hours"],
                "reaction_window_hours": lag_hours,
                "same_sector": candidate.get("same_sector"),
                "qwen_flagged_relationship": candidate.get("qwen_flagged"),
                "lag_supports_causal_direction": lag_supports_causal_direction,
                "factors": factors,
                "weights": weights,
                "band": score_band(alpha_score),
                "historical_analogues": analogues,
                "oracle": oracle_snapshot,
                "confidence_breakdown": {
                    "model_confidence": model_conf,
                    "data_confidence": data_conf,
                    "sample_size": sample_size,
                    "data_coverage_pct": round(coverage_pct, 1),
                },
                "evidence_chain": evidence_chain,
            },
            risk_status="PENDING",
        )
        self.db.add(signal)
        self.db.commit()
        self.db.refresh(signal)
        return signal
