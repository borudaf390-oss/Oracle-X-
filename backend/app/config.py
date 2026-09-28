import os

# --- Core services ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://oracle_x:oracle_x@localhost:5432/oracle_x")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# --- CORS ---
# Comma-separated list of allowed origins, e.g.
# "https://oracle-x.vercel.app,https://oracle-x-staging.vercel.app".
# Falls back to "*" only when nothing is set (local dev), so a deploy that
# forgets to set this is loud (open CORS) rather than silently broken —
# but ALLOWED_ORIGINS must be set for any real deployment.
_allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = (
    ["*"] if _allowed_origins_raw.strip() == "*"
    else [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]
)

# --- Scheduler leader election ---
# Guards against N API replicas each starting their own copy of every
# background job. Uses a Postgres advisory lock (see scheduler.py) so only
# one process actually runs jobs regardless of how many workers/replicas
# are live; the others just serve API traffic. Set to "false" only for
# local debugging where you explicitly want the lock skipped.
SCHEDULER_USE_ADVISORY_LOCK = os.getenv("SCHEDULER_USE_ADVISORY_LOCK", "true").lower() != "false"

# --- Bitget ---
BITGET_API_KEY = os.getenv("BITGET_API_KEY", "")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET", "")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE", "")
BITGET_BASE_URL = os.getenv("BITGET_BASE_URL", "https://api.bitget.com")

# --- News source (event ingestion, Days 5-6) ---
# NewsAPI.org used as the default source: broad coverage, simple REST API,
# free tier sufficient for a hackathon build. Swap for a finance-specific
# feed (e.g. Benzinga, Alpha Vantage news) if rate limits become an issue.
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
NEWSAPI_BASE_URL = os.getenv("NEWSAPI_BASE_URL", "https://newsapi.org/v2")

# --- Qwen (hackathon-provided endpoint per S2 handbook) ---
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")  # set as BITGET_QWEN_API_KEY per handbook, mapped here
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://hackathon.bitgetops.com/v1")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen3.8-max")

# --- Asset universe (crypto majors + tokenized US equities + indices) ---
CRYPTO_ASSETS = ["BTC", "ETH", "SOL"]
TOKENIZED_EQUITY_ASSETS = [
    "NVDA", "TSLA", "AMD", "MU", "AAPL", "MSFT", "AMZN", "GOOGL",
    "META", "NFLX", "COIN", "PLTR", "MSTR",
]
INDEX_ASSETS = ["SPY", "QQQ"]
ASSET_UNIVERSE = CRYPTO_ASSETS + TOKENIZED_EQUITY_ASSETS + INDEX_ASSETS

# --- Sector map (for Relationship Hunter / propagation paths) ---
SECTOR_MAP = {
    "NVDA": "semiconductors", "AMD": "semiconductors", "MU": "semiconductors",
    "TSLA": "auto_tech", "AAPL": "big_tech", "MSFT": "big_tech",
    "AMZN": "big_tech", "GOOGL": "big_tech", "META": "big_tech", "NFLX": "media_tech",
    "COIN": "crypto_equity", "MSTR": "crypto_equity", "PLTR": "software",
    "BTC": "crypto", "ETH": "crypto", "SOL": "crypto",
    "SPY": "index", "QQQ": "index",
}

# --- Cross-stock relationship discovery thresholds ---
RELATIONSHIP_THRESHOLDS = {
    # Below this |correlation|, a candidate is dropped unless Qwen itself
    # flagged it as affected — filters noise from scanning the full asset
    # universe rather than just same-sector peers.
    "min_abs_correlation": 0.15,
    # How many ranked candidates find_propagation_candidates() returns;
    # AlphaAnalyst.analyze() is only ever called on the top few of these.
    "max_candidates": 8,
}

# --- Risk Gate hard thresholds (deterministic — see app/agents/risk_gate.py) ---
RISK_LIMITS = {
    "max_position_pct_of_capital": 0.05,   # 5% max per signal
    "daily_loss_stop_pct": 0.03,           # halt new signals past 3% daily drawdown
    "max_drawdown_halt_pct": 0.10,         # hard halt at 10% drawdown
    "min_liquidity_usd_24h": 5_000_000,    # floor for tradeable liquidity
    "max_volatility_atr_pct": 0.08,        # block if ATR% exceeds this
    "min_stop_distance_pct": 0.005,        # stop can't be closer than 0.5%
}

# --- Bitget execution link (for AI Trading Desk track: AI presents analysis,
# human executes on Bitget directly — no autonomous order placement) ---
def bitget_execution_url(symbol: str, asset_type: str = "tokenized_equity") -> str:
    """
    Deep link to Bitget's trading page for a symbol. URL pattern below is
    the standard USDT-M futures page convention — verify against the live
    site during testing, since Bitget may use a distinct route for
    tokenized-equity perps specifically (not confirmed in the S2 handbook).
    """
    pair = f"{symbol}USDT"
    return f"https://www.bitget.com/futures/usdt/{pair}"


# --- Alpha Score factor weights (seeded; live values come from factor_weights table) ---
DEFAULT_FACTOR_WEIGHTS = {
    "cross_market_displacement": 0.30,
    "momentum": 0.20,
    "volume_abnormality": 0.15,
    "event_strength": 0.15,
    "historical_conditional_probability": 0.10,
    "market_regime": 0.10,
    # Token (last_price) vs Bitget's own index price dislocation — see
    # app/oracle/dislocation.py. compose_alpha_score() normalizes by the
    # sum of all live weights, so this doesn't need the others rebalanced.
    "oracle_regime": 0.10,
}

# --- Confidence decomposition thresholds (app/quant/confidence.py) ---
CONFIDENCE_THRESHOLDS = {
    # Sample size at/above which r_squared is trusted at face value; below
    # this, model_confidence shrinks proportionally (a relationship
    # measured on 3 events can show a great r_squared by chance).
    "min_robust_sample": 30,
    # Minutes since the candidate asset's last 1h candle before
    # data_confidence starts penalizing staleness. Set above the hourly
    # ingestion cadence itself so a normal ~5-15min scheduler lag doesn't
    # look like a data problem.
    "max_fresh_staleness_minutes": 90,
}
# --- Oracle / dislocation engine thresholds ---
ORACLE_THRESHOLDS = {
    "elevated_premium_zscore": 1.5,   # |z| above this -> ELEVATED
    "dislocated_premium_zscore": 2.5,  # |z| above this -> DISLOCATED
    "min_ticks_for_stats": 20,         # need at least this many ticks before z-scores mean anything
    "min_same_session_ticks": 10,      # min same-session ticks before session_conditioned_zscore() uses them instead of the pooled fallback
    "rolling_window": 200,             # ticks used for mean/std baseline
}

# US equity regular session, in US/Eastern — used by app/oracle/session.py.
# Pre/after-market windows are the widest Bitget-relevant convention
# (4:00am-9:30am / 4:00pm-8:00pm ET); tighten later if Bitget's own
# "trading session" definition (see their stock-futures docs) turns out
# narrower once confirmed against live behavior.
US_EQUITY_SESSION = {
    "pre_market_start": "04:00",
    "regular_start": "09:30",
    "regular_end": "16:00",
    "after_hours_end": "20:00",
    "timezone": "America/New_York",
}
