# Backtesting

The actual walk-forward backtest engine lives at
`backend/app/jobs/run_backtest.py`, alongside the other ingestion/pipeline
jobs (it needs the same DB models and quant modules they use). This
directory is kept as a scaffold placeholder per the original repo
structure, rather than duplicating imports across two locations.

Run it from `backend/`:

```bash
python -m app.jobs.run_backtest --leader NVDA --follower AMD
python -m app.jobs.run_backtest --all-pairs
```

Results are written to the `backtest_results` table and readable via
`GET /backtest/runs` and `GET /backtest/runs/{run_id}`.

## Methodology

Walk-forward validation of the leader→follower displacement relationship
(`quant/displacement.py::expected_reaction`). At each historical event, the
prediction is fit using only pairs from *earlier* events — no lookahead.
Results are additionally labeled `in_sample` / `out_of_sample` using a
60-day-total / last-30-days-out-of-sample split, matching the S2 handbook's
Alpha Factory backtest convention (kept for honesty about whether the core
thesis holds, even though Oracle X submits under AI Trading Desk).

**This will produce zero or near-zero results until real market data has
been backfilled** — it reads only real ingested `market_data`, never
synthetic or pre-seeded numbers. Run `ingest_market_data.py --backfill`
first.
