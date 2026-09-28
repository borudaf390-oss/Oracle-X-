"""
Agent 3 — Relationship Hunter (spec section 12).
Looks for: correlations, lead/lag, sector relationships, crypto/equity
relationships, abnormal divergence. Writes to `relationships` and returns
candidate propagation paths for the Alpha Analyst to score.
"""
import pandas as pd
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models import Asset, MarketData, RelationshipEdge, Event
from app.quant.correlation import rolling_correlation, lead_lag_hours
from app import config

_THRESH = config.RELATIONSHIP_THRESHOLDS
# Don't write a new relationship-edge snapshot for the same asset pair more
# often than this — find_propagation_candidates() runs on every event, and
# with no dedup, repeated processing of the same pair (which happens
# constantly given the small universe) wrote a new row every single time
# with no uniqueness constraint, growing the table unboundedly for no
# analytical benefit (the correlation over a ~30h rolling window barely
# moves within an hour anyway).
_EDGE_DEDUP_MINUTES = 60


class RelationshipHunter:
    def __init__(self, db: Session):
        self.db = db

    def _price_series(self, asset_id: int, timeframe: str = "1h", as_of=None) -> pd.Series:
        """
        as_of: when given, only returns candles with timestamp <= as_of.
        This is the enforcement point for the temporal-integrity fix — every
        relationship/correlation/lead-lag calculation must be computable
        using only data that existed at the time being analyzed, not the
        full history up to whenever the job happens to run. Omitting as_of
        (the old, leaky default) uses everything available, which is only
        correct for genuinely "what does the relationship look like right
        now" queries — never for explaining a specific past event.
        """
        query = self.db.query(MarketData).filter(
            MarketData.asset_id == asset_id, MarketData.timeframe == timeframe
        )
        if as_of is not None:
            query = query.filter(MarketData.timestamp <= as_of)
        rows = query.order_by(MarketData.timestamp.asc()).all()
        if not rows:
            return pd.Series(dtype=float)
        return pd.Series(
            [float(r.close) for r in rows], index=[r.timestamp for r in rows]
        )

    def _recent_edge_exists(self, asset_a_id: int, asset_b_id: int) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_EDGE_DEDUP_MINUTES)
        return self.db.query(RelationshipEdge).filter(
            RelationshipEdge.asset_a_id == asset_a_id,
            RelationshipEdge.asset_b_id == asset_b_id,
            RelationshipEdge.computed_at >= cutoff,
        ).first() is not None

    def find_propagation_candidates(self, source_event: Event, as_of=None) -> list[dict]:
        """
        Given a triggering event on one asset, ranks EVERY other seeded
        asset (not just same-sector peers) by correlation and lead/lag
        with the source asset.

        as_of: defaults to source_event.timestamp when not given explicitly
        — this is the temporal-integrity fix. Every price series this
        function touches (source and every candidate) is truncated to
        timestamp <= as_of before any correlation or lead/lag is computed,
        so the discovered relationship reflects only what was knowable at
        the time of the event, not data that arrived afterward. Without
        this, an event processed hours after it fired could have its
        "historical relationship" quietly built using market moves that
        happened AFTER the event — which would make the causal story look
        more precise than it actually was in real time.

        This replaces the previous same-sector-plus-SPY/QQQ restriction,
        which structurally could never surface a genuine cross-sector
        relationship (e.g. a crypto move spilling into risk-appetite
        equities, or a semiconductor event reaching a "software" or
        "crypto_equity"-labeled name the sector map doesn't connect it
        to) — exactly the kind of relationship that isn't yet obvious and
        is most worth surfacing. The seeded universe is small (~18
        symbols per config.ASSET_UNIVERSE), so scanning all of it is
        cheap; this stops being true at a much larger universe, at which
        point a candidate pre-filter (sector + a correlation cache) would
        be needed again.

        Ranking score combines |correlation| with two adjustments:
        - downweighted (not dropped) when the discovered lead/lag doesn't
          actually support "source leads candidate" for this pair — see
          quant/correlation.py's now-corrected sign convention. A small
          universe means we don't want to fully discard a candidate just
          because the timing direction is unclear this time.
        - boosted for a Qwen-flagged cross-sector call, since Qwen may
          have picked up a genuine connection (e.g. a supply-chain or
          competitive relationship) that raw price correlation alone
          hasn't caught up to yet.
        """
        source_asset = self.db.query(Asset).filter(Asset.id == source_event.asset_id).first()
        if not source_asset:
            return []
        as_of = as_of or source_event.timestamp

        qwen_flagged_symbols = set()
        if source_event.affected_assets:
            flagged = self.db.query(Asset).filter(Asset.id.in_(source_event.affected_assets)).all()
            qwen_flagged_symbols = {a.symbol for a in flagged}

        source_series = self._price_series(source_asset.id, as_of=as_of)
        if source_series.empty:
            return []

        source_sector = config.SECTOR_MAP.get(source_asset.symbol)
        all_candidates = self.db.query(Asset).filter(Asset.id != source_asset.id).all()

        results = []
        for candidate in all_candidates:
            candidate_series = self._price_series(candidate.id, as_of=as_of)
            if candidate_series.empty:
                continue

            corr_series = rolling_correlation(source_series, candidate_series)
            latest_corr = float(corr_series.dropna().iloc[-1]) if not corr_series.dropna().empty else 0.0

            is_qwen_flagged = candidate.symbol in qwen_flagged_symbols
            if abs(latest_corr) < _THRESH["min_abs_correlation"] and not is_qwen_flagged:
                continue  # too weak to be worth scoring or showing

            lag, lag_corr = lead_lag_hours(source_series, candidate_series)
            same_sector = source_sector is not None and config.SECTOR_MAP.get(candidate.symbol) == source_sector
            # Positive lag = source leads candidate (see quant/correlation.py's
            # corrected, verified sign convention) — the causal direction
            # this whole propagation-candidate search assumes.
            causal_direction_supported = lag > 0

            score = abs(latest_corr)
            if not causal_direction_supported:
                score *= 0.5
            if is_qwen_flagged and not same_sector:
                score *= 1.25  # a novel connection the sector map alone wouldn't find

            results.append({
                "asset_id": candidate.id,
                "symbol": candidate.symbol,
                "sector": config.SECTOR_MAP.get(candidate.symbol),
                "same_sector": same_sector,
                "qwen_flagged": is_qwen_flagged,
                "correlation": latest_corr,
                "lead_lag_hours": lag,
                "lead_lag_corr": lag_corr,
                "causal_direction_supported": causal_direction_supported,
                "as_of": as_of,
                "_score": score,
            })

            # Dedup: skip the DB write (not the calculation above, which
            # the caller still needs live) if a snapshot for this pair was
            # already written recently — see _EDGE_DEDUP_MINUTES.
            if not self._recent_edge_exists(source_asset.id, candidate.id):
                self.db.add(RelationshipEdge(
                    asset_a_id=source_asset.id,
                    asset_b_id=candidate.id,
                    correlation=latest_corr,
                    lead_lag_hours=lag,
                    period_start=source_series.index.min(),
                    period_end=source_series.index.max(),
                ))
        self.db.commit()

        results.sort(key=lambda r: r["_score"], reverse=True)
        for r in results:
            del r["_score"]
        return results[: _THRESH["max_candidates"]]
