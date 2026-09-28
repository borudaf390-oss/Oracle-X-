"""
Playbook translator: LockedRelationshipContract -> a GetAgent Playbook
package on disk (README.md, manifest.yaml, backtest.yaml, src/main.py,
src/strategy.py).

SCHEMA PROVENANCE — this version is built against the REAL, retrieved
package-schema.md reference (@bitget-ai/getagent-skill@0.6.4) and the full
contents of four official examples (btc-ema-cross-demo,
crypto-spot-momentum-trader, selection-basket-demo, us-stock-selection-basket),
not reconstruction from fragments. What's now CONFIRMED and changed from
earlier versions of this file:

  - manifest.yaml's real shape: name (regex ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$),
    display_name(+_i18n for en/zh/zh-tw/es/ja/vi), description(+_i18n),
    long_description (300-400 English words, NO numeric periods/thresholds/
    formulas), market_type (spot|contract), trading_symbols, decision_mode,
    backtest_support, runtime_profile, follow_trade_supported, execution_mode,
    strategy_config (a FLAT dict of actual current param values) mirrored by
    user_config_schema. The earlier `strategy_config.symbol_roles.<SYM>.
    verified_metadata` nesting was WRONG — no confirmed example nests like that.
  - backtest.yaml (only for backtest_support: full): venue{name,account_type,
    oms_type,starting_balances}, strategy{module,class,config_class,config},
    execution{start,end}, instrument{id,kind,raw_symbol,base_currency,
    quote_currency,price_precision,size_precision,price_increment,
    size_increment,lot_size,maker_fee,taker_fee,bar_type}. bar_type format
    confirmed: "{SYMBOL}.{VENUE}-{N}-{UNIT}-LAST-EXTERNAL".
  - README.md is REQUIRED (an earlier version of this translator didn't
    generate one at all): UTF-8, >=200 chars, bilingual headings (策略/Strategy,
    开仓/Entry, 平仓/Exit, 风险/Risk).
  - main.py and strategy.py are NEARLY INDEPENDENT, not wired together the way
    an earlier version assumed: strategy.py's NautilusTrader class is
    referenced BY NAME in backtest.yaml's `strategy:` block and instantiated
    internally by the managed backtest.run() engine — main.py's historical
    path never imports strategy.py, it just fetches OHLCV via getagent.data
    and calls backtest.run(). main.py's LIVE path is a SEPARATE, hand-rolled
    reimplementation using getagent.data/getagent.trade directly and does NOT
    instantiate the Nautilus Strategy class at all.
  - Position sizing, a correction to an earlier "fix": the backtest path uses
    a FIXED LITERAL trade_size string in backtest.yaml (e.g. "0.01"), not
    something computed at runtime from portfolio equity — contract.py now
    precomputes this once at export time from a live reference price AND
    the follower's real size_precision/min_trade_num (resolved from Bitget's
    contracts endpoint, not hardcoded placeholders — confirmed field names
    via Bitget's own published example plus two independent third-party SDK
    definitions). The LIVE path sizes via the documented
    trade.helpers.compute_qty(market="contract", budget_amount=margin_budget,
    leverage=leverage) instead — a third, separate mechanism.

CAVEAT NOT YET RESOLVED — trade_size economic semantics: the fixed quantity
is sized correctly at EXPORT-TIME price only. If the backtest window's
starting price differs from today's price, the same fixed quantity
represents a different fraction of starting balance at the start of the
backtest than proposed_position_pct claims. Whether GetAgent's backtest
model expects and accounts for this, or whether it's a real distortion,
has not been verified against the sandbox — don't interpret a resulting
backtest as a clean "N% of equity" risk analog without checking this.

GAP LEFT DELIBERATELY OPEN — TP/SL: package-schema.md requires TP/SL prices
to go through resolve_contract_tpsl()/contract_rules().price_step, never
manual rounding. Oracle X's locked contract carries stop_distance_pct but
NEITHER generated file uses it — this first bridge validates relationship-
trigger translation and backtest compatibility only; Oracle X's Risk Gate
stop distance is not yet represented in the managed strategy. Left as an
explicit gap rather than inventing an untested TP/SL call.

STILL NOT CONFIRMED (flagged inline where relevant):
  - Multi-instrument relationship strategies: every retrieved example trades
    exactly ONE instrument. Oracle X needs bars for BOTH leader and follower.
    Extending backtest.run()'s ohlcv_data dict to two keys is a reasonable
    extrapolation from its confirmed single-key usage, not something any
    example demonstrates.
  - TP/SL: package-schema.md requires resolve_contract_tpsl()/
    contract_rules().price_step for TP/SL prices. Oracle X's contract carries
    stop_distance_pct but it is NOT wired into either generated file yet —
    flagged as a known gap rather than guessed.
  - i18n: this translator does NOT attempt machine translation for zh/zh-tw/
    es/ja/vi — every locale is filled with the English text plus an inline
    TODO, since a wrong translation in a real submission is worse than an
    honest placeholder.
  - venue.name / instrument precision fields: confirmed examples use
    "BINANCE" and "BITGET" inconsistently for similar instruments, and this
    translator's price/size precision values are placeholders copied from the
    BTC perp example's shape, not fetched from Bitget's actual instrument
    rules for the specific follower symbol — fetch via
    trade.helpers.contract_rules() or Bitget's public contracts endpoint
    before trusting these.
"""
import os
import textwrap
from datetime import datetime, timedelta
import yaml
from app.playbook.contract import LockedRelationshipContract

_LOCALES = ["en", "zh", "zh-tw", "es", "ja", "vi"]


def _slug(contract: LockedRelationshipContract) -> str:
    return f"oracle-x-{contract.leader_symbol.lower()}-{contract.follower_symbol.lower()}-{contract.source_signal_id}"


def _i18n_placeholder(en_text: str) -> dict:
    """TODO real translations before publishing — every locale gets the English
    text so the manifest is schema-valid without pretending to have verified
    translations."""
    return {locale: en_text for locale in _LOCALES}


def _long_description_text(contract: LockedRelationshipContract) -> str:
    """
    300-400 English words, NO numeric periods/thresholds/formulas (a hard
    manifest rule) — deliberately qualitative/narrative. All actual numbers
    (correlation, lag, thresholds) live in strategy_config instead.
    """
    return textwrap.dedent("""\
        This Playbook is a cross-market relationship strategy discovered by Oracle X,
        a research system that looks for cases where one asset's price move has not
        yet been matched by a related asset's typically-expected reaction. The thesis
        is that certain pairs of instruments move together with a consistent timing
        relationship, and when the leading instrument moves but the following
        instrument has not yet caught up to its historically expected response, that
        gap represents a temporary information-diffusion lag rather than a change in
        the underlying relationship.

        The strategy watches a leading instrument for a confirmed directional move.
        Once that move is established, it checks whether the following instrument has
        already caught up to the reaction that similar historical moves would suggest.
        If the following instrument still lags behind the expected reaction by a
        meaningful margin, and the direction of the historical relationship is
        supported by the data used to discover it, the strategy treats the gap as an
        actionable opportunity in the direction the following instrument would need to
        move to close it.

        Entry is a one-shot decision per run: once the locked relationship's trigger
        conditions are met, the strategy takes a single position in the following
        instrument in the confirmed direction and does not add to it. This is
        deliberately conservative rather than a repeating pattern-scanning system,
        since the relationship being tested was discovered from a specific historical
        analysis rather than rediscovered fresh on every bar the backtest evaluates.

        Exit for the backtest path closes remaining exposure at the end of the
        evaluation window; live execution defers to the platform's managed trade
        lifecycle and risk boundaries. This package does not attempt to independently
        rediscover the relationship during the backtest window itself — it tests a
        specific, already-identified hypothesis against new data, a meaningfully more
        conservative claim than a strategy that searches for its own pattern over the
        same window it is being evaluated on.

        This strategy underperforms when the historical relationship between the two
        instruments breaks down, when broad market conditions overwhelm the
        idiosyncratic relationship the strategy depends on, or when both instruments
        move together immediately with no measurable lag left to exploit. Past
        behavior of this relationship is not a guarantee of its future persistence,
        and live execution is subject to slippage, fees, and venue-specific liquidity
        conditions that a historical replay cannot fully capture.
        """)


def _readme_md(contract: LockedRelationshipContract) -> str:
    direction_word = contract.direction.lower()
    return textwrap.dedent(f"""\
        # Oracle X: {contract.leader_symbol} to {contract.follower_symbol} Relationship

        A cross-market relationship strategy discovered by Oracle X's research engine,
        translated into a GetAgent Playbook for official backtesting and follow-trade
        validation.

        ## 策略 / Strategy

        This Playbook tests a specific, already-discovered relationship between two
        instruments: {contract.leader_symbol} historically leads {contract.follower_symbol}
        by a measured delay. When the leading instrument moves and the following
        instrument has not yet caught up to its historically expected reaction, the
        strategy treats that gap as a signal.

        The relationship was discovered by Oracle X's own research pipeline using only
        data available before the triggering event (no lookahead), and is locked for
        this package rather than rediscovered during the backtest itself.

        ## 开仓 / Entry

        The strategy enters a single {direction_word} position in {contract.follower_symbol}
        when the leading instrument's move and the follower's displacement both clear
        their locked thresholds. This is a one-shot decision per run, not a repeating
        pattern scan.

        ## 平仓 / Exit

        The backtest path closes all positions at the end of the evaluation window.
        Live execution defers to the platform's managed trade lifecycle.

        ## 风险 / Risk

        This strategy depends on a specific historical relationship persisting out of
        sample. If the relationship breaks down, or if both instruments move together
        with no measurable lag, the strategy will not find an edge to trade. Live
        execution is subject to slippage, fees, and liquidity conditions a historical
        replay cannot fully capture. Past relationship behavior is not a guarantee of
        future persistence.

        Two things this first version does NOT yet represent, flagged explicitly
        rather than silently assumed: the backtest's fixed position size is computed
        from a single reference price at export time, so its relationship to the
        target position-size percentage across the whole backtest window has not been
        independently verified; and this package does not yet attach a stop-loss,
        even though Oracle X's own risk approval for this signal included one. Treat
        this first run as a validation of relationship-trigger translation and
        backtest compatibility, not as a complete representation of Oracle X's risk
        model.

        ## Provenance

        Generated from Oracle X signal #{contract.source_signal_id}, discovered as of
        {contract.discovered_as_of}. Produced by an automated translator
        (app/playbook/translator.py in the Oracle X repository) and not yet validated
        against GetAgent's sandbox — review before publishing.
        """)


def _manifest_dict(contract: LockedRelationshipContract, slug: str) -> dict:
    en_description = (
        f"Cross-market relationship strategy: {contract.leader_symbol} leads "
        f"{contract.follower_symbol}, discovered by Oracle X's research engine."
    )
    en_display_name = f"Oracle X {contract.leader_symbol}-{contract.follower_symbol} Relationship"
    margin_budget_default = str(round(contract.backtest_starting_balance_usdt * contract.proposed_position_pct, 2))

    return {
        "name": slug,
        "display_name": en_display_name,
        "display_name_i18n": _i18n_placeholder(en_display_name),
        "version": "1.0.0",
        "description": en_description,
        "description_i18n": _i18n_placeholder(en_description),
        "long_description": _long_description_text(contract),
        "market_type": "contract",
        "trading_symbols": [contract.leader_symbol, contract.follower_symbol],
        "tags": ["oracle-x", "cross-market", "relationship", "displacement", "deterministic"],
        "decision_mode": "deterministic",
        "backtest_support": "full",
        "runtime_profile": "deterministic",
        "execution_mode": "follow_trade",
        "follow_trade_supported": True,
        "strategy_config": {
            "trading_symbols": [contract.leader_symbol, contract.follower_symbol],
            "leverage": 1,
            "margin_budget": margin_budget_default,
            "lag_hours": contract.lag_hours,
            "leader_move_trigger_pct": contract.leader_move_pct_at_signal,
            "displacement_trigger_pct": contract.displacement_pct_at_signal,
            "expected_follower_move_pct": contract.expected_follower_move_pct,
        },
        "user_config_schema": {
            "trading_symbols": {
                "type": "array",
                "item_type": "string",
                "default": [contract.leader_symbol, contract.follower_symbol],
                "options": [contract.leader_symbol, contract.follower_symbol],
                "min_items": 2,
                "max_items": 2,
                "label": "Leader/follower symbols (locked relationship, order matters)",
            },
            "leverage": {"type": "integer", "default": 1, "min": 1, "max": 10, "label": "Leverage"},
            "margin_budget": {
                "type": "string",
                "default": margin_budget_default,
                "pattern": "^[0-9]+(\\.[0-9]+)?$",
                "label": "Margin budget USDT",
            },
        },
    }


def _backtest_dict(contract: LockedRelationshipContract) -> dict:
    end_dt = datetime.fromisoformat(contract.discovered_as_of)
    start_dt = end_dt - timedelta(days=contract.backtest_total_days)

    return {
        "venue": {
            # BITGET, matching Oracle X's actual data source — confirmed
            # examples use BINANCE and BITGET inconsistently for similar
            # instruments, so this isn't a fully settled convention.
            "name": "BITGET",
            "account_type": "MARGIN",
            "oms_type": "NETTING",
            "starting_balances": [
                {"amount": contract.backtest_starting_balance_usdt, "currency": "USDT"}
            ],
        },
        "strategy": {
            "module": "strategy",
            "class": "OracleXRelationshipStrategy",
            "config_class": "OracleXRelationshipConfig",
            "config": {
                "order_id_tag": f"oracle-x-{contract.source_signal_id}",
                "trade_size": contract.backtest_trade_size,
                "lag_hours": contract.lag_hours,
                "leader_move_trigger_pct": contract.leader_move_pct_at_signal,
                "displacement_trigger_pct": contract.displacement_pct_at_signal,
                "expected_follower_move_pct": contract.expected_follower_move_pct,
            },
        },
        "execution": {
            "start": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        # Only the FOLLOWER instrument is declared — the one actually traded.
        # Whether/how the LEADER needs its own declaration for a
        # two-instrument relationship strategy is NOT confirmed by any
        # retrieved example (all four are single-instrument).
        "instrument": {
            "id": f"{contract.follower_symbol}.BITGET",
            "kind": "perpetual",
            "raw_symbol": contract.follower_symbol,
            "base_currency": contract.follower_symbol.replace("USDT", ""),
            "quote_currency": "USDT",
            "settlement_currency": "USDT",
            # Real Bitget contract rules (contract.py resolved these from a
            # live /contracts call) — no longer hardcoded placeholders.
            "price_precision": contract.follower_price_precision,
            "size_precision": contract.follower_size_precision,
            "price_increment": contract.follower_price_increment,
            "size_increment": contract.follower_size_increment,
            "lot_size": contract.follower_size_increment,
            "maker_fee": contract.follower_maker_fee,
            "taker_fee": contract.follower_taker_fee,
            "bar_type": f"{contract.follower_symbol}.BITGET-1-HOUR-LAST-EXTERNAL",
        },
    }


def _strategy_py(contract: LockedRelationshipContract) -> str:
    """
    Used ONLY by the managed backtest engine (referenced by class name in
    backtest.yaml's `strategy:` block) — confirmed NOT imported by main.py's
    live path, which reimplements the same logic independently. Reverted
    trade_size back to a fixed literal (contract.backtest_trade_size,
    precomputed once at export time from a live price) after finding that no
    confirmed example computes position size dynamically from portfolio
    equity at runtime — an earlier version of this file did that, which was
    itself a wrong "fix" of the original bug, not a correct one.
    """
    return textwrap.dedent(f'''\
        """
        NautilusTrader Strategy implementing Oracle X's LOCKED relationship
        hypothesis: {contract.leader_symbol} leads {contract.follower_symbol}
        by ~{contract.lag_hours}h (correlation {contract.correlation:.2f} as of
        {contract.discovered_as_of}).

        Referenced by name in backtest.yaml's strategy.class — instantiated by
        the managed backtest engine, not imported directly by main.py (whose
        live path is a separate, independent implementation).

        trade_size below is a FIXED LITERAL quantity precomputed once at
        export time (see app/playbook/contract.py) from a live reference
        price, matching the confirmed pattern in every official example —
        NOT computed dynamically from portfolio equity at runtime.

        Deliberately does NOT recompute correlation/lag from the backtest's
        own price history — that would silently reopen the temporal-leakage
        bug Oracle X's AS_OF refactor closed. Tests the fixed,
        already-discovered hypothesis instead. Oracle premium confirmation
        and stop-loss are NOT implemented here — the former needs a live
        index/mark feed this strategy doesn't have wired in, the latter
        needs resolve_contract_tpsl()/contract_rules().price_step per
        package-schema.md, not manual rounding.
        """
        from decimal import Decimal
        from typing import Optional
        from nautilus_trader.config import StrategyConfig
        from nautilus_trader.model.data import Bar, BarType
        from nautilus_trader.model.enums import OrderSide, TimeInForce
        from nautilus_trader.model.identifiers import InstrumentId
        from nautilus_trader.model.instruments import Instrument
        from nautilus_trader.model.objects import Quantity
        from nautilus_trader.trading.strategy import Strategy


        class OracleXRelationshipConfig(StrategyConfig):
            leader_instrument_id: Optional[InstrumentId] = None
            follower_instrument_id: Optional[InstrumentId] = None
            leader_bar_type: Optional[BarType] = None
            follower_bar_type: Optional[BarType] = None
            # Fixed literal quantity — see module docstring. NOT a percentage.
            trade_size: str = "{contract.backtest_trade_size}"
            lag_hours: int = {contract.lag_hours}
            direction: str = "{contract.direction}"
            expected_follower_move_pct: float = {contract.expected_follower_move_pct}
            displacement_trigger_pct: float = {contract.displacement_pct_at_signal}
            leader_move_trigger_pct: float = {contract.leader_move_pct_at_signal}


        class OracleXRelationshipStrategy(Strategy):
            def __init__(self, config: OracleXRelationshipConfig) -> None:
                super().__init__(config)
                self.cfg = config
                self._leader_closes: list[float] = []
                self._follower_closes: list[float] = []
                self._leader_instrument: Optional[Instrument] = None
                self._follower_instrument: Optional[Instrument] = None
                self._triggered = False  # one-shot: mirrors a single live signal

            def on_start(self) -> None:
                if self.cfg.leader_bar_type is None or self.cfg.follower_bar_type is None:
                    raise RuntimeError("leader_bar_type and follower_bar_type must be set")
                self._leader_instrument = self.cache.instrument(self.cfg.leader_instrument_id)
                self._follower_instrument = self.cache.instrument(self.cfg.follower_instrument_id)
                self.subscribe_bars(self.cfg.leader_bar_type)
                self.subscribe_bars(self.cfg.follower_bar_type)

            def on_bar(self, bar: Bar) -> None:
                if self.cfg.leader_instrument_id is not None and bar.bar_type.instrument_id == self.cfg.leader_instrument_id:
                    self._leader_closes.append(float(bar.close))
                elif self.cfg.follower_instrument_id is not None and bar.bar_type.instrument_id == self.cfg.follower_instrument_id:
                    self._follower_closes.append(float(bar.close))
                self._maybe_trigger()

            def _leader_move_pct(self) -> Optional[float]:
                if len(self._leader_closes) < 2:
                    return None
                prev, curr = self._leader_closes[-2], self._leader_closes[-1]
                return (curr - prev) / prev if prev else None

            def _follower_move_pct(self, lookback: int) -> Optional[float]:
                if len(self._follower_closes) <= lookback:
                    return None
                prev, curr = self._follower_closes[-1 - lookback], self._follower_closes[-1]
                return (curr - prev) / prev if prev else None

            def _maybe_trigger(self) -> None:
                if self._triggered:
                    return
                leader_move = self._leader_move_pct()
                follower_move = self._follower_move_pct(self.cfg.lag_hours)
                if leader_move is None or follower_move is None:
                    return
                displacement = self.cfg.expected_follower_move_pct - follower_move
                if abs(leader_move) < abs(self.cfg.leader_move_trigger_pct):
                    return
                if abs(displacement) < self.cfg.displacement_trigger_pct:
                    return
                self._triggered = True
                self._submit_locked_direction_order()

            def _submit_locked_direction_order(self) -> None:
                instrument = self._follower_instrument
                if instrument is None:
                    return
                side = OrderSide.BUY if self.cfg.direction == "LONG" else OrderSide.SELL
                qty = Quantity(Decimal(self.cfg.trade_size), instrument.size_precision)
                order = self.order_factory.market(
                    instrument_id=instrument.id,
                    order_side=side,
                    quantity=qty,
                    time_in_force=TimeInForce.GTC,
                )
                self.submit_order(order)

            def on_stop(self) -> None:
                if self._follower_instrument is not None:
                    self.cancel_all_orders(self._follower_instrument.id)
                    self.close_all_positions(self._follower_instrument.id)
        ''')


def _main_py(contract: LockedRelationshipContract) -> str:
    direction_lower = contract.direction.lower()
    return textwrap.dedent(f'''\
        """
        Entry point for the {contract.leader_symbol}->{contract.follower_symbol}
        Oracle X relationship Playbook.

        Structure confirmed against official examples (btc-ema-cross-demo,
        crypto-spot-momentum-trader): historical and live paths are SEPARATE
        implementations, not a shared Strategy instance. The historical path
        fetches OHLCV via getagent.data and calls the managed backtest.run()
        engine, which instantiates strategy.py's Nautilus Strategy internally
        via backtest.yaml's `strategy:` block — this file never imports
        strategy.py directly. The live path hand-rolls the same displacement
        check using getagent.data/getagent.trade directly.

        UNCONFIRMED: passing TWO instruments' OHLCV frames in one
        backtest.run(ohlcv_data={{...}}) call (one per leg of this
        relationship) is an extrapolation from the confirmed single-key usage
        in every retrieved example — none of them trade more than one
        instrument. Verify this actually works in GetAgent's sandbox before
        trusting the historical path's results.

        Also not implemented: stop-loss. Oracle X's locked contract carries
        stop_distance_pct ({contract.stop_distance_pct}) but package-schema.md
        specifies TP/SL prices must go through resolve_contract_tpsl()/
        contract_rules().price_step rather than manual rounding, and wiring
        that in has not been done yet — flagged here rather than guessed.
        """
        import math
        from decimal import Decimal
        from typing import Any, Optional

        from getagent import backtest, data, runtime

        LEADER_SYMBOL = "{contract.leader_symbol}"
        FOLLOWER_SYMBOL = "{contract.follower_symbol}"
        DIRECTION = "{direction_lower}"


        def _sanitize(value: Any) -> Any:
            if isinstance(value, float) and not math.isfinite(value):
                return None
            return value


        def _run_historical() -> None:
            cfg = runtime.manifest.get("strategy_config", {{}}) or {{}}
            symbols = cfg.get("trading_symbols") or [LEADER_SYMBOL, FOLLOWER_SYMBOL]
            leader_symbol, follower_symbol = symbols[0], symbols[1]

            leader_bars = data.crypto.futures.kline(
                symbol=leader_symbol, interval="1h", limit=1000, closed_only=True,
            )
            follower_bars = data.crypto.futures.kline(
                symbol=follower_symbol, interval="1h", limit=1000, closed_only=True,
            )
            leader_frame = backtest.prepare_frame(leader_bars, datetime_index="date")
            follower_frame = backtest.prepare_frame(follower_bars, datetime_index="date")

            if leader_frame.empty or follower_frame.empty:
                runtime.emit_signal(
                    action="watch",
                    symbol=follower_symbol,
                    confidence=0.0,
                    metrics={{"leader_rows": len(leader_frame), "follower_rows": len(follower_frame)}},
                    meta={{"reason": "no historical bars returned for one or both legs"}},
                )
                return

            # Two-instrument ohlcv_data dict — see module docstring's
            # UNCONFIRMED note.
            result = backtest.run(
                ohlcv_data={{
                    f"{{leader_symbol}}.BITGET": leader_frame,
                    f"{{follower_symbol}}.BITGET": follower_frame,
                }},
                spec=runtime.backtest_spec,
            )

            chart_path = backtest.generate_chart(result)
            summary = result.summary or {{}}
            try:
                net_pnl = float(summary.get("net_pnl", 0) or 0)
            except (TypeError, ValueError):
                net_pnl = 0.0
            action = DIRECTION if net_pnl > 0 else "watch"

            raw_metrics = {{
                "total_return_pct": result.total_return_pct,
                "net_pnl": net_pnl,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown_pct": result.max_drawdown_pct,
                "win_rate": result.win_rate,
                "total_trades": result.total_trades,
                "profit_factor": result.profit_factor,
                "follower_rows": len(follower_frame),
            }}
            metrics = {{key: _sanitize(val) for key, val in raw_metrics.items()}}

            runtime.emit_signal(
                action=action,
                symbol=follower_symbol,
                confidence=_sanitize(result.win_rate) or 0.0,
                metrics=metrics,
                meta={{
                    "chart_path": chart_path,
                    "locked_relationship": {{
                        "leader": leader_symbol,
                        "follower": follower_symbol,
                        "lag_hours": {contract.lag_hours},
                    }},
                }},
            )


        def _leader_move_pct(closes: list) -> Optional[float]:
            if len(closes) < 2:
                return None
            prev, curr = closes[-2], closes[-1]
            return float(curr - prev) / float(prev) if prev else None


        def _follower_move_pct(closes: list, lookback: int) -> Optional[float]:
            if len(closes) <= lookback:
                return None
            prev, curr = closes[-1 - lookback], closes[-1]
            return float(curr - prev) / float(prev) if prev else None


        def _execute_locked_direction_order(*, symbol: str, margin_budget: str, leverage: int) -> dict:
            from getagent import trade

            current = trade.contract.current_position(symbol=symbol)
            position = trade.helpers.find_contract_position(current, symbol=symbol)
            if position is not None and position.hold_side == DIRECTION:
                return {{"status": "already_positioned", "hold_side": position.hold_side}}
            if position is not None:
                closed = trade.contract.close_position(symbol=symbol, hold_side=position.hold_side)
                if not trade.is_success(closed):
                    raise RuntimeError(f"contract close failed: {{closed}}")

            qty_plan = trade.helpers.compute_qty(
                symbol=symbol, market="contract", budget_amount=margin_budget, leverage=leverage,
            )
            open_position = (
                trade.contract.open_long_market if DIRECTION == "long" else trade.contract.open_short_market
            )
            result = open_position(symbol=symbol, qty=qty_plan.qty, leverage=leverage)
            if not trade.is_success(result):
                raise RuntimeError(f"contract open failed: {{result}}")
            return {{"qty": str(qty_plan.qty), "result": result}}


        def _run_live() -> None:
            cfg = runtime.manifest.get("strategy_config", {{}}) or {{}}
            symbols = cfg.get("trading_symbols") or [LEADER_SYMBOL, FOLLOWER_SYMBOL]
            leader_symbol, follower_symbol = symbols[0], symbols[1]
            lag_hours = int(cfg.get("lag_hours", {contract.lag_hours}) or {contract.lag_hours})
            leader_trigger = float(cfg.get("leader_move_trigger_pct", {contract.leader_move_pct_at_signal}))
            displacement_trigger = float(cfg.get("displacement_trigger_pct", {contract.displacement_pct_at_signal}))
            expected_follower_move = float(cfg.get("expected_follower_move_pct", {contract.expected_follower_move_pct}))
            leverage = int(cfg.get("leverage", 1) or 1)
            margin_budget = str(cfg.get("margin_budget", "{contract.backtest_trade_size}") or "{contract.backtest_trade_size}")

            leader_bars = data.crypto.futures.kline(
                symbol=leader_symbol, interval="1h", limit=max(lag_hours + 5, 20), closed_only=True,
            )
            follower_bars = data.crypto.futures.kline(
                symbol=follower_symbol, interval="1h", limit=max(lag_hours + 5, 20), closed_only=True,
            )
            leader_closes = [
                Decimal(str(row["close"])) for row in data.to_records(leader_bars) if row.get("close") not in (None, "")
            ]
            follower_closes = [
                Decimal(str(row["close"])) for row in data.to_records(follower_bars) if row.get("close") not in (None, "")
            ]

            leader_move = _leader_move_pct(leader_closes)
            follower_move = _follower_move_pct(follower_closes, lag_hours)
            if leader_move is None or follower_move is None:
                runtime.emit_signal(
                    action="hold",
                    symbol=follower_symbol,
                    confidence=0.0,
                    metrics={{"leader_rows": len(leader_closes), "follower_rows": len(follower_closes)}},
                    meta={{"reason": "insufficient closed bars for one or both legs"}},
                )
                return

            displacement = expected_follower_move - float(follower_move)
            triggered = abs(float(leader_move)) >= abs(leader_trigger) and abs(displacement) >= displacement_trigger
            action = DIRECTION if triggered else "hold"

            runtime.emit_signal_or_follow(
                action=action,
                symbol=follower_symbol,
                confidence=0.7 if triggered else 0.0,
                metrics={{
                    "leader_move_pct": float(leader_move),
                    "follower_move_pct": float(follower_move),
                    "displacement_pct": displacement,
                }},
                meta={{"lag_hours": lag_hours, "locked_relationship": {{"leader": leader_symbol, "follower": follower_symbol}}}},
                execute_trade=lambda: _execute_locked_direction_order(
                    symbol=follower_symbol, margin_budget=margin_budget, leverage=leverage,
                ),
            )


        def run() -> None:
            if runtime.is_historical():
                _run_historical()
                return
            if runtime.is_live():
                _run_live()
                return
            raise ValueError(f"unsupported evaluation_mode={{runtime.evaluation_mode!r}}")


        if __name__ == "__main__":
            run()
        ''')


def write_playbook_package(contract: LockedRelationshipContract, output_dir: str) -> str:
    """
    Writes README.md, manifest.yaml, backtest.yaml, src/main.py,
    src/strategy.py under output_dir/playbook/<slug>/ — matching the
    confirmed upload tree exactly (package-schema.md: "Do not upload tests/,
    data/, logs/, output/, venvs" — none of those are written here). Returns
    the package directory path.
    """
    slug = _slug(contract)
    package_dir = os.path.join(output_dir, "playbook", slug)
    src_dir = os.path.join(package_dir, "src")
    os.makedirs(src_dir, exist_ok=True)

    with open(os.path.join(package_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(_readme_md(contract))

    with open(os.path.join(package_dir, "manifest.yaml"), "w") as f:
        yaml.safe_dump(_manifest_dict(contract, slug), f, sort_keys=False, default_flow_style=False, allow_unicode=True)

    with open(os.path.join(package_dir, "backtest.yaml"), "w") as f:
        yaml.safe_dump(_backtest_dict(contract), f, sort_keys=False, default_flow_style=False)

    with open(os.path.join(src_dir, "main.py"), "w") as f:
        f.write(_main_py(contract))

    with open(os.path.join(src_dir, "strategy.py"), "w") as f:
        f.write(_strategy_py(contract))

    return package_dir
