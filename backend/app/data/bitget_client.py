"""
Bitget REST client — market data (OHLCV, ticker) and, where applicable,
tokenized-equity perp endpoints. Signing logic follows Bitget's standard
HMAC-SHA256 request signing (timestamp + method + path + body).

This is a real client skeleton, not a mock: fill in BITGET_API_KEY/SECRET/
PASSPHRASE via env vars and the request signing will work against the live
API. Endpoints below match Bitget's v2 mix/spot market data routes; confirm
exact paths for tokenized-equity perps in the hackathon handbook, since that
product surface is newer than the standard USDT-perp docs.
"""
import base64
import hashlib
import hmac
import time
import json
import requests
from app import config


class BitgetClient:
    # Class-level (shared across instances) cache for get_contracts() —
    # see that method's docstring for why. A plain class attribute is
    # fine here since this process is single-threaded per job; if jobs
    # ever run concurrently in threads, this would need a lock.
    _contracts_cache: dict = {}
    _CONTRACTS_CACHE_TTL_SECONDS = 300  # 5 minutes — contract listings change rarely

    def __init__(self):
        self.base_url = config.BITGET_BASE_URL
        self.api_key = config.BITGET_API_KEY
        self.api_secret = config.BITGET_API_SECRET
        self.passphrase = config.BITGET_API_PASSPHRASE

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        message = f"{timestamp}{method.upper()}{path}{body}"
        mac = hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _headers(self, method: str, path: str, body: str = "") -> dict:
        ts = str(int(time.time() * 1000))
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": self._sign(ts, method, path, body),
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

    def get_candles(self, symbol: str, granularity: str = "1H", limit: int = 200,
                     end_time_ms: int | None = None):
        """
        Public endpoint — no signing required. Returns recent OHLCV candles.
        end_time_ms (Unix ms), when passed, returns candles ending at/before
        that timestamp — confirmed against Bitget's v2 docs (startTime/
        endTime are both Unix-ms params on this endpoint). Note this
        endpoint only covers recent history per granularity's documented
        window (e.g. ~83 days for 1H); for real backfill beyond that, use
        get_history_candles() below instead.
        """
        path = "/api/v2/mix/market/candles"
        params = {
            "symbol": symbol,
            "granularity": granularity,
            "limit": limit,
            "productType": "USDT-FUTURES",
        }
        if end_time_ms is not None:
            params["endTime"] = str(end_time_ms)
        resp = requests.get(f"{self.base_url}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_history_candles(self, symbol: str, granularity: str = "1H", limit: int = 200,
                             end_time_ms: int | None = None):
        """
        Dedicated history endpoint for real backfill — the plain
        get_candles() endpoint above is windowed to a fixed recent lookback
        per granularity and doesn't reach far enough back for a genuine
        60-90 day backfill. This is the endpoint ingest_market_data.py's
        backfill_asset() should page backward through via end_time_ms,
        moving the cursor to the oldest returned candle's timestamp minus
        one interval on each call until either BACKFILL_DAYS is covered or
        the exchange returns no more data.
        """
        path = "/api/v2/mix/market/history-candles"
        params = {
            "symbol": symbol,
            "granularity": granularity,
            "limit": limit,
            "productType": "USDT-FUTURES",
        }
        if end_time_ms is not None:
            params["endTime"] = str(end_time_ms)
        resp = requests.get(f"{self.base_url}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_ticker(self, symbol: str):
        path = "/api/v2/mix/market/ticker"
        params = {"symbol": symbol, "productType": "USDT-FUTURES"}
        resp = requests.get(f"{self.base_url}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_contracts(self, product_type: str = "USDT-FUTURES", force_refresh: bool = False):
        """
        Real instrument list from Bitget — used to resolve actual tradeable
        symbols instead of guessing a naming convention. Per the S2 handbook,
        Bitget's market data covers Crypto and US stock futures (spot on the
        roadmap); this endpoint is how we find out what's actually listed
        rather than assuming a `{SYMBOL}USDT` pattern.

        Cached at the class level (shared across every BitgetClient
        instance) for _CONTRACTS_CACHE_TTL_SECONDS. Without this,
        ingest_oracle_ticks.py's 2-minute poll loop across ~18 assets was
        issuing 18 identical full-contract-list requests per cycle — the
        contract list is the same for every asset within a run, and
        rarely changes at all, so there was nothing being learned by
        re-fetching it per-asset. force_refresh bypasses the cache for
        callers that specifically need up-to-the-second listing state.
        """
        cached = self._contracts_cache.get(product_type)
        if cached and not force_refresh:
            fetched_at, data = cached
            if (time.time() - fetched_at) < self._CONTRACTS_CACHE_TTL_SECONDS:
                return data
        path = "/api/v2/mix/market/contracts"
        params = {"productType": product_type}
        resp = requests.get(f"{self.base_url}{path}", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        self._contracts_cache[product_type] = (time.time(), data)
        return data

    def resolve_symbol(self, base_symbol: str, product_type: str = "USDT-FUTURES") -> str | None:
        """
        Looks up base_symbol (e.g. 'NVDA', 'BTC') against the real contract
        list and returns the exact tradeable symbol Bitget uses, or None if
        not listed. Caches nothing yet — fine for hackathon call volume;
        add an in-memory cache if ingestion jobs start hitting rate limits.
        """
        data = self.get_contracts(product_type)
        contracts = data.get("data", [])
        for c in contracts:
            symbol = c.get("symbol", "")
            base_coin = c.get("baseCoin", "")
            if base_coin.upper() == base_symbol.upper() or symbol.upper().startswith(base_symbol.upper()):
                return symbol
        return None

    def get_account_overview(self, product_type: str = "USDT-FUTURES"):
        """
        Real, signed account state — equity, available balance, unrealized
        PnL. This is what jobs/track_portfolio.py reads to compute the
        daily-loss-stop and max-drawdown inputs Risk Gate needs; replaces
        the hardcoded placeholder portfolio state from the pipeline.
        Requires BITGET_API_KEY/SECRET/PASSPHRASE — recommended per the S2
        handbook to use a dedicated Agentic sub-account (isolated funds) or
        Bitget's Demo/paper-trading environment during the hackathon.
        """
        path = "/api/v2/mix/account/accounts"
        params = {"productType": product_type}
        query = f"?productType={product_type}"
        headers = self._headers("GET", path + query)
        resp = requests.get(f"{self.base_url}{path}", params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_positions(self, product_type: str = "USDT-FUTURES"):
        """Real open positions — feeds proposed_position_pct / concentration checks in Risk Gate."""
        path = "/api/v2/mix/position/all-position"
        params = {"productType": product_type}
        query = f"?productType={product_type}"
        headers = self._headers("GET", path + query)
        resp = requests.get(f"{self.base_url}{path}", params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_tokenized_equity_price(self, symbol: str):
        """
        Superseded by resolve_symbol() + get_candles()/get_ticker() using the
        resolved symbol — kept as a named entry point in case the S2 handbook
        adds a distinct tokenized-equity route later (spot tokenized equities
        are listed as 'on the roadmap' per the handbook, not live yet).
        """
        resolved = self.resolve_symbol(symbol)
        if not resolved:
            raise ValueError(f"{symbol} not found in Bitget's live contract list")
        return self.get_ticker(resolved)

    def place_order(self, symbol: str, side: str, size: float, order_type: str = "market"):
        """
        Signed, authenticated order placement. Left unimplemented on purpose
        until Risk Gate (app/agents/risk_gate.py) is wired in front of it —
        no code path should be able to call this without a PASS from the gate.
        """
        raise NotImplementedError(
            "Wire this only through app/agents/risk_gate.py — do not call "
            "place_order directly from any agent or route."
        )
