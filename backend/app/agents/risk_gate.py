"""
Agent 5b — Risk Gate (the enforcement layer of Risk Guardian).

This is deliberately NOT an LLM call. This is the structural boundary
discussed after reviewing NightDesk's S1 win: the block has to be a code
path a signal cannot get around, not an agent's opinion sitting in a
chain that a bug could route past.

Contract: no code anywhere in this project should call
bitget_client.place_order() or mark a signal tradeable without first
calling RiskGate.evaluate() and checking passed == True. This is the
single choke point.
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import Signal, MarketData, RiskGateLog
from app import config
from app.quant import evidence


class RiskGate:
    def __init__(self, db: Session):
        self.db = db
        self.limits = config.RISK_LIMITS

    def _recent_atr_pct(self, asset_id: int, window: int = 14) -> float | None:
        """
        Real ATR%, not the average-intrabar-range approximation this used
        to compute. True Range accounts for gaps between candles (the
        distance from the previous close to the current high/low), which
        the old `(high - low) / close` calculation ignored entirely —
        that formula is closer to a normalized-range indicator than ATR.

        Pulls window+1 candles (oldest first) so every True Range value
        has a previous close to compare against, computes a simple
        rolling average of True Range over `window` periods, then
        expresses it as a percentage of the most recent close.

        Returns None — not 0.0 — when there isn't enough history to
        compute a real ATR. 0.0 would silently read as "zero volatility,"
        which is a PASS for the volatility check; the honest answer when
        data is missing is "unknown," which evaluate() below treats as a
        BLOCK, not a free pass.
        """
        rows = (
            self.db.query(MarketData)
            .filter(MarketData.asset_id == asset_id, MarketData.timeframe == "1h")
            .order_by(MarketData.timestamp.desc())
            .limit(window + 1)
            .all()
        )
        if len(rows) < 2:
            return None

        rows = list(reversed(rows))  # oldest -> newest, so prev_close aligns correctly
        true_ranges = []
        prev_close = float(rows[0].close)
        for r in rows[1:]:
            high, low, close = float(r.high), float(r.low), float(r.close)
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
            prev_close = close

        if not true_ranges:
            return None

        atr = sum(true_ranges) / len(true_ranges)
        latest_close = float(rows[-1].close)
        return atr / latest_close if latest_close > 0 else None

    def _recent_liquidity_usd(self, asset_id: int, hours: int = 24) -> float:
        rows = (
            self.db.query(MarketData)
            .filter(MarketData.asset_id == asset_id, MarketData.timeframe == "1h")
            .order_by(MarketData.timestamp.desc())
            .limit(hours)
            .all()
        )
        return sum(float(r.volume) * float(r.close) for r in rows)

    @staticmethod
    def _check(value, comparator, limit, unknown_reason: str | None = None) -> dict:
        """
        Builds one risk_gate_log check entry with an explicit PASS/FAIL/
        UNKNOWN status rather than a bare boolean. unknown_reason is only
        ever hit for checks whose input CAN legitimately be missing
        (portfolio snapshots, ATR history) — the fail-closed fix: UNKNOWN
        gets pass=False, same as FAIL, instead of the old behavior where a
        missing value silently defaulted to 0.0 and read as a clean PASS.
        """
        if unknown_reason is not None and value is None:
            return {"pass": False, "status": "UNKNOWN", "value": None, "limit": limit, "reason": unknown_reason}
        ok = comparator(value, limit)
        return {"pass": ok, "status": "PASS" if ok else "FAIL", "value": value, "limit": limit}

    def evaluate(self, signal: Signal, portfolio_daily_pnl_pct: float | None, portfolio_drawdown_pct: float | None,
                 proposed_position_pct: float, stop_distance_pct: float) -> dict:
        """
        Runs every deterministic check from RISK_LIMITS. Returns
        {"passed": bool, "checks": {...}} and logs the full breakdown to
        risk_gate_log regardless of outcome (pass AND block both get logged
        — the demo point is showing the gate actually rejects things).

        portfolio_daily_pnl_pct/portfolio_drawdown_pct are None when
        track_portfolio.py has no snapshot data yet — see _check()'s
        docstring for why that BLOCKs rather than passing.
        """
        checks = {}

        checks["daily_loss_stop"] = self._check(
            portfolio_daily_pnl_pct, lambda v, l: v > l, -self.limits["daily_loss_stop_pct"],
            unknown_reason="no portfolio snapshot ~24h old yet — daily P&L is unknown, not zero",
        )
        checks["max_drawdown"] = self._check(
            portfolio_drawdown_pct, lambda v, l: v < l, self.limits["max_drawdown_halt_pct"],
            unknown_reason="no portfolio snapshots in the lookback window — drawdown is unknown, not zero",
        )
        checks["position_size"] = self._check(
            proposed_position_pct, lambda v, l: v <= l, self.limits["max_position_pct_of_capital"]
        )
        checks["stop_distance"] = self._check(
            stop_distance_pct, lambda v, l: v >= l, self.limits["min_stop_distance_pct"]
        )

        atr_pct = self._recent_atr_pct(signal.asset_id)
        checks["volatility"] = self._check(
            atr_pct, lambda v, l: v <= l, self.limits["max_volatility_atr_pct"],
            unknown_reason="insufficient candle history for ATR — volatility is unknown, not zero",
        )

        liquidity = self._recent_liquidity_usd(signal.asset_id)
        checks["liquidity"] = self._check(
            liquidity, lambda v, l: v >= l, self.limits["min_liquidity_usd_24h"]
        )

        passed = all(c["pass"] for c in checks.values())

        signal.risk_status = "PASS" if passed else "BLOCK"
        signal.risk_reason = None if passed else "; ".join(
            f"{name} ({c['status']})" for name, c in checks.items() if not c["pass"]
        )
        # Append this signal's Risk Gate outcome to its Signal Evidence
        # Graph (app/quant/evidence.py) rather than leaving the risk
        # decision as a sibling field the frontend has to know to look for
        # separately from the causal chain that led to it.
        signal.reason_json = evidence.append_step(signal.reason_json, evidence.risk_step(passed, checks))

        log = RiskGateLog(signal_id=signal.id, passed=passed, checks_json=checks)
        self.db.add(log)
        self.db.commit()

        return {"passed": passed, "checks": checks}
