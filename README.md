# Oracle X — AI Cross-Market Alpha Engine

Bitget AI Base Camp · Hackathon S2 entry.

> Detect when an asset's observed reaction lags the reaction implied by its historical relationship to a related asset (cross-market *displacement*), confirm or disconfirm it with Bitget's own index/mark/funding state (the *Oracle* layer), have Qwen explain the evidence, and let a deterministic Risk Gate — not an AI — decide whether a human should see it as actionable.

**Positioning:** *AI Trading Desk* (AI presents, human executes on Bitget) bridging into *Alpha Factory* (a locked, deterministic strategy exported to GetAgent Playbook for official backtest verification). Explicitly **not** an autonomous trading agent or an exchange.

## Design principles

1. **Qwen reasons, code decides.** Qwen never produces position size, stop, price, or permission.
2. **Temporal integrity.** Relationship discovery may only see data ≤ the event's timestamp (AS_OF).
3. **Fail closed.** Unknown risk inputs block; they never default to "safe".
4. **Locked hypotheses.** Anything exported externally tests a fixed, already-discovered relationship — never re-discovers it from the window it's evaluated on.
5. **State uncertainty explicitly.** Unverified assumptions are written into docstrings/READMEs, not filled with plausible-looking code.

## Architecture (high level)

```
NewsAPI + Bitget REST  →  Ingestion (scheduler, leader-locked)
                              ↓
                         Postgres (~15 tables)
                              ↓
  Agent pipeline (Interpreter → Relationship Hunter[AS_OF] → Alpha Analyst
                  → Risk Analyst(Qwen, advisory) → RISK GATE(deterministic) → Narrator)
                              ↓
              FastAPI  ←→  Next.js frontend
                              ↓
              Playbook bridge (LockedContract → translator → GetAgent package)
```

**Deployment target:** Railway (API) + Vercel (frontend) + Postgres. Scheduler runs inside the API process, guarded by a Postgres advisory lock.

## Repo layout

```
backend/
├── app/
│   ├── agents/          sentinel · interpreter · relationship · alpha ·
│   │                    risk_analyst · risk_gate · narrator
│   ├── quant/           correlation · displacement · momentum · regime ·
│   │                    scoring · historical_analogues · confidence ·
│   │                    performance · evidence
│   ├── oracle/          session · dislocation · query
│   ├── data/            bitget_client · news_client · qwen_client
│   ├── playbook/        contract · translator
│   ├── api/             routes_signals · market · oracle · simulate ·
│   │                    backtest · news · jobs
│   ├── jobs/            ingest_* · run_pipeline · run_backtest ·
│   │                    export_playbook · seed_assets · track_portfolio
│   ├── models.py        SQLAlchemy ORM
│   ├── db.py            engine/session
│   ├── config.py        env vars, asset universe, risk limits
│   ├── scheduler.py     advisory-lock leader election
│   └── main.py          FastAPI entrypoint
├── db/schema.sql
├── tests/
├── tools/diff_playbook_scaffold.py
└── requirements.txt
frontend/                Next.js (App Router) + Tailwind + three.js globe
backtesting/             notes
```

## What is built

### Backend
- Bitget client: candles with `endTime` cursor pagination, ticker (last/index/mark/funding), contracts with 5-min class-level cache, HMAC signing. `place_order()` raises `NotImplementedError`.
- NewsAPI + Qwen clients with retries, schema validation, neutral fallback on extraction failure.
- Ingestion: market data (1h candles, 90d), oracle ticks (2 min), events (6h) with `published_at` provenance.
- Relationship Hunter: full-universe scan, AS_OF-bounded, ranked by |corr| with causal-direction penalty.
- Alpha Analyst: 7 weighted factors, confidence decomposed (model / data / composite), Evidence Chain.
- Risk Gate: deterministic PASS / FAIL / UNKNOWN; unknown ⇒ BLOCK. Real True-Range ATR. Logs every check.
- Oracle layer: session-conditioned premium z-score, funding z-score, duration/velocity from real tick timestamps, regime factor.
- Playbook bridge: `LockedRelationshipContract` (refuses non-PASS), translator against real GetAgent schema, fixed `trade_size` from instrument rules.
- API: `/signals`, `/market`, `/oracle`, `/simulate`, `/backtest`, `/news`, `/jobs`. No authentication yet.
- Tests: session-conditioning and contract-cache executed in sandbox; temporal-integrity and relationship-dedup need sqlalchemy locally.

### Frontend
- Dashboard, signals (OpportunityCard with Evidence Chain + Oracle panel), market-map, simulation, news, flight-radar globe, playbooks.
- API client already defines `oracleSummary`, `backtestRuns`, `jobStatus` — pages for backtest / oracle / ops still to be wired.

## Honest status

Nothing in this repo has been run end-to-end against a real Postgres, Bitget, NewsAPI, or Qwen in the build sandbox. Frontend has never been compiled there. The first real boot is still required.

| Claim | Status |
|---|---|
| Lead/lag sign correct | ✅ verified on synthetic data |
| Session-conditioned z-score | ✅ verified (5 cases) |
| Contract cache TTL / failure-preservation | ✅ verified with mocked HTTP |
| Duration/velocity use real timestamps | ✅ verified |
| Funding influences Oracle factor | ✅ verified |
| Translator schema-shaped | ✅ verified on mock contract |
| AS_OF temporal integrity | 🟡 test written; DB test not run |
| Full pipeline end-to-end | ⬜ never run |
| Frontend compiles | ⬜ never built |
| GetAgent accepts package | ⏳ untested |
| Any performance / edge claim | ⬜ none can be made yet |

## Setup

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Set env: DATABASE_URL, BITGET_API_KEY, BITGET_API_SECRET, BITGET_PASSPHRASE,
#          NEWS_API_KEY, QWEN_API_KEY, ALLOWED_ORIGINS
# Init DB from db/schema.sql, then:
uvicorn app.main:app --reload --port 8000

# Tests (requires sqlalchemy + Postgres or appropriate mocks)
pytest tests/ -v

# Frontend
cd frontend
npm install
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

### Playbook export (Gate A — do this next)

```bash
# From backend, against a live DB that has at least one PASS signal:
python -m app.jobs.export_playbook --signal-id <id> --output-dir ./playbook_out
# Then run GetAgent's validate.py on that exact directory and share the raw output.
```

## What is not built yet (priority order)

**Gate A (you):** real Postgres boot + pytest; one real Playbook export → validate.py.

**Phase 4 (no external deps):** leader-move alignment, failed Qwen extraction as first-class state, Qwen provenance, backtest page, oracle page, ops/health panel, README/playbooks credibility (done in this pass).

**Phase 5:** walk-forward lag discovery, cost-aware backtest, train/validate/test split, Risk Gate v2.

**Phase 6 (after Gate A):** Playbook TP/SL + oracle confirmation in exported strategy, export UI, automation.

**Phase 7:** dynamic universe, auth, migrations, demo flow, polish.

## Explicit non-goals

Autonomous order placement, exchange/ledger infrastructure, token settlement, Kafka/microservices, replacing BitgetClient with MCP until stock-perp historical coverage is proven, and any change to research logic solely to make GetAgent's backtest look better.
