"""
Trade-economics metrics for run_backtest.py.

The backtester previously reported only hit_rate and mean_abs_error — a
system can have a 70% hit rate and still lose money if its average loser
is bigger than its average winner, so hit rate alone can't tell you
whether the strategy is actually worth trading. These functions compute
the metrics that answer that question instead.

Each "trade" here is one backtest event where a direction was actually
predicted (predicted_move_pct != 0): its return is
sign(predicted) * actual_move_pct — i.e. the raw return you'd have made
taking a naive unit position in the predicted direction. This does not
model position sizing, fees, slippage, or spread, so treat these as
directional-edge diagnostics, not a claim about live P&L.

MAE/MFE (max adverse/favorable excursion during the holding period) are
deliberately NOT computed here: the backtest only has a single 1h close
at the target timestamp, not the intrabar price path between entry and
exit, so a genuine MAE/MFE isn't calculable from this data without
fetching finer-grained candles for every event window. Reporting it
anyway from a single-point return would be exactly the kind of implied
precision the historical-coverage fix elsewhere in this pass was meant to
eliminate — better to state the limitation than fabricate the number.
"""
import math


def trade_returns(results: list) -> list[float]:
    """One realized-direction return per event where a direction was actually predicted."""
    out = []
    for r in results:
        predicted = float(r.predicted_move_pct)
        if predicted == 0.0:
            continue  # no position would have been taken — not a trade
        direction = 1.0 if predicted > 0 else -1.0
        out.append(direction * float(r.actual_move_pct))
    return out


def performance_summary(results: list) -> dict:
    returns = trade_returns(results)
    n = len(returns)
    if n == 0:
        return {
            "trades": 0, "win_rate": None, "expectancy_pct": None,
            "profit_factor": None, "sharpe": None, "sortino": None,
            "max_drawdown_pct": None, "avg_win_pct": None, "avg_loss_pct": None,
        }

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]

    mean_return = sum(returns) / n
    variance = sum((r - mean_return) ** 2 for r in returns) / n
    std_dev = math.sqrt(variance)
    sharpe = (mean_return / std_dev) if std_dev > 0 else None

    downside = [min(r, 0.0) for r in returns]
    downside_variance = sum(d ** 2 for d in downside) / n
    downside_std = math.sqrt(downside_variance)
    sortino = (mean_return / downside_std) if downside_std > 0 else None

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else None)

    # Max drawdown on the equity curve formed by compounding these returns
    # in event order (results are expected pre-sorted by event_timestamp).
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= (1 + r)
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, drawdown)

    return {
        "trades": n,
        "win_rate": round(len(wins) / n * 100, 1),
        "expectancy_pct": round(mean_return * 100, 3),
        "profit_factor": round(profit_factor, 3) if isinstance(profit_factor, float) and profit_factor != float("inf") else profit_factor,
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "sortino": round(sortino, 3) if sortino is not None else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "avg_win_pct": round(sum(wins) / len(wins) * 100, 3) if wins else None,
        "avg_loss_pct": round(sum(losses) / len(losses) * 100, 3) if losses else None,
    }
