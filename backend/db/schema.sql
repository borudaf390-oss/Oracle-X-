-- Oracle X core schema
-- Cross-market alpha engine: assets, market data, events, relationships, signals, outcomes

CREATE TABLE IF NOT EXISTS assets (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(20) UNIQUE NOT NULL,
    asset_type      VARCHAR(20) NOT NULL,   -- 'crypto' | 'tokenized_equity' | 'index'
    sector          VARCHAR(50),
    display_name    VARCHAR(100),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_data (
    id              BIGSERIAL PRIMARY KEY,
    asset_id        INTEGER NOT NULL REFERENCES assets(id),
    timeframe       VARCHAR(5) NOT NULL,    -- '1m','5m','15m','1h','4h','1d'
    timestamp       TIMESTAMPTZ NOT NULL,
    open            NUMERIC(20,8) NOT NULL,
    high            NUMERIC(20,8) NOT NULL,
    low             NUMERIC(20,8) NOT NULL,
    close           NUMERIC(20,8) NOT NULL,
    volume          NUMERIC(24,8) NOT NULL,
    UNIQUE (asset_id, timeframe, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_market_data_lookup ON market_data (asset_id, timeframe, timestamp DESC);

CREATE TABLE IF NOT EXISTS events (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    asset_id        INTEGER REFERENCES assets(id),
    event_type      VARCHAR(50) NOT NULL,   -- 'earnings','product','macro','crypto_news','sec_filing'
    headline        TEXT NOT NULL,
    raw_source      TEXT,
    sentiment       VARCHAR(10),            -- 'bullish','bearish','neutral'
    magnitude       NUMERIC(4,3),           -- 0..1, Qwen-assigned strength
    horizon_hours   INTEGER,                -- expected impact window
    affected_assets INTEGER[],              -- asset ids Qwen flagged as downstream
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_time ON events (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_asset ON events (asset_id);
-- Duplicate-signal fix: run_pipeline.py previously re-selected the same
-- "20 most recent interpreted events" every cycle with nothing marking an
-- event as already handled, so a single event could regenerate signals
-- indefinitely. This column is that marker.
ALTER TABLE events ADD COLUMN IF NOT EXISTS pipeline_processed_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_events_unprocessed ON events (pipeline_processed_at) WHERE pipeline_processed_at IS NULL;
-- Temporal provenance (Phase 2): `timestamp` now equals published_at when
-- available, rather than always meaning "when Oracle X downloaded this."
-- Kept separately from `timestamp` so the distinction stays auditable.
ALTER TABLE events ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
ALTER TABLE events ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMPTZ;
ALTER TABLE events ADD COLUMN IF NOT EXISTS source_url TEXT;

CREATE TABLE IF NOT EXISTS relationships (
    id              SERIAL PRIMARY KEY,
    asset_a_id      INTEGER NOT NULL REFERENCES assets(id),
    asset_b_id      INTEGER NOT NULL REFERENCES assets(id),
    correlation     NUMERIC(5,4),
    lead_lag_hours  NUMERIC(6,2),           -- positive = A leads B
    period_start    TIMESTAMPTZ,
    period_end      TIMESTAMPTZ,
    computed_at     TIMESTAMPTZ DEFAULT now(),
    UNIQUE (asset_a_id, asset_b_id, period_start, period_end)
);
-- The UNIQUE constraint above only catches exact-duplicate snapshots
-- (identical period_start/period_end), which varies per call since it's
-- derived from whatever data was available at call time — it doesn't by
-- itself prevent unbounded growth from repeated processing of the same
-- pair. app/agents/relationship.py now dedups at the application level by
-- recency (skip writing if a snapshot for this pair exists within the
-- last hour); this index supports that lookup.
CREATE INDEX IF NOT EXISTS idx_relationships_pair_recency ON relationships (asset_a_id, asset_b_id, computed_at DESC);

CREATE TABLE IF NOT EXISTS signals (
    id                  BIGSERIAL PRIMARY KEY,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT now(),
    asset_id            INTEGER NOT NULL REFERENCES assets(id),
    triggering_event_id BIGINT REFERENCES events(id),
    direction           VARCHAR(5) NOT NULL,    -- 'LONG' | 'SHORT'
    alpha_score         NUMERIC(5,2) NOT NULL,  -- 0-100
    confidence          NUMERIC(5,2) NOT NULL,  -- 0-100, headline UI number (see below)
    model_confidence    NUMERIC(5,2),           -- statistical reliability of the leader/follower relationship alone
    data_confidence     NUMERIC(5,2),           -- freshness/completeness of the market data behind this signal
    sample_size         INTEGER,                -- number of historical analogues the relationship is based on
    expected_move_pct   NUMERIC(8,4),
    current_move_pct    NUMERIC(8,4),
    displacement_pct    NUMERIC(8,4),
    reason_json         JSONB,                  -- structured causal chain + factor breakdown
    narrative           TEXT,                   -- Qwen-generated explanation
    risk_status         VARCHAR(10) DEFAULT 'PENDING',  -- 'PASS' | 'BLOCK' | 'PENDING'
    risk_reason         TEXT,
    status               VARCHAR(15) DEFAULT 'OPEN'      -- 'OPEN' | 'SIMULATED' | 'CLOSED'
);
-- `confidence` used to be computed as min(alpha_score, r_squared*100 +
-- alpha_score*0.3) — i.e. capped BY alpha_score, which meant it could
-- never carry information independent of the opportunity score it was
-- supposed to qualify. It's now composite_confidence(model_confidence,
-- data_confidence) — see app/quant/confidence.py — and the two inputs are
-- stored alongside it so the UI can show the breakdown, not just the
-- blend. ADD COLUMN IF NOT EXISTS keeps this idempotent for databases
-- that already have a `signals` table from before this fields existed.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS model_confidence NUMERIC(5,2);
ALTER TABLE signals ADD COLUMN IF NOT EXISTS data_confidence NUMERIC(5,2);
ALTER TABLE signals ADD COLUMN IF NOT EXISTS sample_size INTEGER;
CREATE INDEX IF NOT EXISTS idx_signals_time ON signals (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_signals_asset ON signals (asset_id);

CREATE TABLE IF NOT EXISTS simulations (
    id              BIGSERIAL PRIMARY KEY,
    signal_id       BIGINT NOT NULL REFERENCES signals(id),
    entry_price     NUMERIC(20,8),
    stop_price      NUMERIC(20,8),
    target_price    NUMERIC(20,8),
    risk_amount     NUMERIC(20,8),
    reward_amount   NUMERIC(20,8),
    risk_reward     NUMERIC(6,3),
    historical_win_rate NUMERIC(5,2),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS outcomes (
    id                  BIGSERIAL PRIMARY KEY,
    signal_id           BIGINT NOT NULL REFERENCES signals(id) UNIQUE,
    actual_return_pct   NUMERIC(8,4),
    prediction_error_pct NUMERIC(8,4),
    result_summary       TEXT,
    correct_factors      TEXT[],
    missed_factors        TEXT[],
    closed_at            TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS factor_weights (
    id              SERIAL PRIMARY KEY,
    factor_name     VARCHAR(50) UNIQUE NOT NULL,  -- e.g. 'cross_market_displacement','momentum','volume_abnormality'
    weight          NUMERIC(5,4) NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT now(),
    update_reason   TEXT
);

CREATE TABLE IF NOT EXISTS factor_performance (
    factor_name        VARCHAR(50) PRIMARY KEY REFERENCES factor_weights(factor_name),
    correct_count      INTEGER NOT NULL DEFAULT 0,
    missed_count       INTEGER NOT NULL DEFAULT 0,
    last_promoted_at   TIMESTAMPTZ,
    last_promotion_note TEXT
);
-- Adaptive Signal Calibration (replaces per-outcome live weight nudging):
-- observations accumulate here first; app/api/routes_simulate.py only
-- promotes them into factor_weights.weight once a factor has at least
-- MIN_SAMPLE_FOR_PROMOTION observations, so a single outcome can no
-- longer swing a live weight the way the previous implementation could.

CREATE TABLE IF NOT EXISTS risk_gate_log (
    id              BIGSERIAL PRIMARY KEY,
    signal_id       BIGINT REFERENCES signals(id),
    passed          BOOLEAN NOT NULL,
    checks_json     JSONB NOT NULL,     -- {"position_size": {"pass": true, "value":..., "limit":...}, ...}
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_risk_gate_log_signal ON risk_gate_log (signal_id);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    equity          NUMERIC(24,8) NOT NULL,     -- total account equity (USDT)
    available       NUMERIC(24,8),
    unrealized_pnl  NUMERIC(24,8),
    raw_json        JSONB                       -- full account response, for audit
);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_time ON portfolio_snapshots (timestamp DESC);

CREATE TABLE IF NOT EXISTS delivery_log (
    id              BIGSERIAL PRIMARY KEY,
    signal_id       BIGINT NOT NULL REFERENCES signals(id),
    event_type      VARCHAR(20) NOT NULL,   -- 'delivered' | 'execution_clicked'
    channel         VARCHAR(20) DEFAULT 'dashboard',
    metadata_json   JSONB,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_delivery_log_signal ON delivery_log (signal_id);
CREATE INDEX IF NOT EXISTS idx_delivery_log_time ON delivery_log (created_at DESC);

CREATE TABLE IF NOT EXISTS backtest_results (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              VARCHAR(40) NOT NULL,   -- groups rows from one backtest run
    leader_asset_id     INTEGER NOT NULL REFERENCES assets(id),
    follower_asset_id   INTEGER NOT NULL REFERENCES assets(id),
    event_timestamp     TIMESTAMPTZ NOT NULL,
    leader_move_pct     NUMERIC(8,4) NOT NULL,
    predicted_move_pct  NUMERIC(8,4) NOT NULL,
    actual_move_pct     NUMERIC(8,4) NOT NULL,
    direction_correct   BOOLEAN NOT NULL,
    in_sample           BOOLEAN NOT NULL,       -- false = out-of-sample window
    r_squared_at_time   NUMERIC(5,4),           -- fit quality of the relationship used
    created_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_backtest_run ON backtest_results (run_id);

CREATE TABLE IF NOT EXISTS job_status (
    job_name        VARCHAR(50) PRIMARY KEY,
    last_run_at     TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_error      TEXT,
    last_result     TEXT,
    run_count       INTEGER DEFAULT 0
);

-- seed default factor weights (Alpha Score composition from spec)
INSERT INTO factor_weights (factor_name, weight, update_reason) VALUES
    ('cross_market_displacement', 0.30, 'initial seed'),
    ('momentum', 0.20, 'initial seed'),
    ('volume_abnormality', 0.15, 'initial seed'),
    ('event_strength', 0.15, 'initial seed'),
    ('historical_conditional_probability', 0.10, 'initial seed'),
    ('market_regime', 0.10, 'initial seed'),
    ('oracle_regime', 0.10, 'initial seed — token/index premium dislocation')
ON CONFLICT (factor_name) DO NOTHING;
-- compose_alpha_score() normalizes by the sum of live weights, so adding
-- oracle_regime here doesn't require rebalancing the others by hand.

-- Oracle ticks: high-frequency last/index/mark/funding snapshots feeding
-- the dislocation engine (app/oracle/dislocation.py). Populated by
-- app/jobs/ingest_oracle_ticks.py, polled every 2 minutes — much tighter
-- than the hourly OHLCV candles in market_data, since premium/dislocation
-- math needs finer granularity than candle data provides.
CREATE TABLE IF NOT EXISTS oracle_ticks (
    id              BIGSERIAL PRIMARY KEY,
    asset_id        INTEGER NOT NULL REFERENCES assets(id),
    timestamp       TIMESTAMPTZ NOT NULL,
    last_price      NUMERIC(20,8) NOT NULL,
    index_price     NUMERIC(20,8),
    mark_price      NUMERIC(20,8),
    funding_rate    NUMERIC(10,8),
    premium_pct     NUMERIC(8,5),   -- (last_price / index_price) - 1
    mark_basis_pct  NUMERIC(8,5),   -- (mark_price / index_price) - 1
    session_state   VARCHAR(15),    -- PRE_MARKET | REGULAR | AFTER_HOURS | CLOSED | CRYPTO_24_7
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_oracle_ticks_asset_time ON oracle_ticks (asset_id, timestamp DESC);

-- Failed Qwen extraction is a first-class state (B4)
ALTER TABLE events ADD COLUMN IF NOT EXISTS extraction_failed BOOLEAN NOT NULL DEFAULT FALSE;
