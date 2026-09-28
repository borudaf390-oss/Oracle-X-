const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export type MarketTick = {
  symbol: string;
  asset_type: string;
  sector: string | null;
  price: number;
  change_pct: number;
};

export type Regime = {
  regime: "RISK_ON" | "RISK_OFF" | "NEUTRAL";
  score: number;
  btc_trend?: number;
  qqq_trend?: number;
};

export type QwenProvenance = {
  purpose?: string;
  model?: string;
  prompt_version?: string | null;
  input_hash?: string | null;
  output_hash?: string | null;
  latency_ms?: number | null;
  validation_ok?: boolean;
  attempts?: number;
  error?: string | null;
};

export type AgentReasoning = {
  narrator: { agent: string; text: string; provenance?: QwenProvenance | null } | null;
  risk_analyst: {
    agent: string;
    recommendation: string | null;
    reasoning: string | null;
    provenance?: QwenProvenance | null;
  } | null;
};

export type OracleState = {
  status: "OK" | "NO_DATA";
  symbol?: string;
  last_price?: number | null;
  index_price?: number | null;
  mark_price?: number | null;
  funding_rate?: number | null;
  premium_pct?: number | null;
  premium_zscore?: number;
  premium_percentile?: number;
  premium_duration_minutes?: number;
  premium_velocity?: number;
  funding_zscore?: number;
  session_state?: "PRE_MARKET" | "REGULAR" | "AFTER_HOURS" | "CLOSED" | "CRYPTO_24_7" | null;
  session_conditioned?: boolean;
  regime?: "NORMAL" | "ELEVATED" | "DISLOCATED";
  oracle_regime_factor?: number;
};

export type EvidenceStep = {
  step: "event" | "relationship" | "expected_reaction" | "current_reaction" |
        "displacement" | "oracle" | "risk" | "narrative";
  label: string;
  data: Record<string, any>;
};

export type Signal = {
  id: number;
  asset: string;
  direction: "LONG" | "SHORT";
  alpha_score: number;
  confidence: number;
  model_confidence: number | null;
  data_confidence: number | null;
  sample_size: number | null;
  expected_move_pct: number | null;
  current_move_pct: number | null;
  displacement_pct: number | null;
  risk_status: "PASS" | "BLOCK" | "PENDING";
  risk_reason: string | null;
  narrative: string | null;
  reason: Record<string, any> | null;
  oracle: OracleState | null;
  evidence_chain: EvidenceStep[];
  status: string;
  timestamp: string;
  execution_url: string | null;
  agent_reasoning: AgentReasoning;
  qwen_provenance?: Record<string, QwenProvenance> | null;
};

export type MarketMapData = {
  nodes: { id: number; symbol: string; sector: string | null; change_pct: number }[];
  edges: { source: number; target: number; correlation: number; lead_lag_hours: number }[];
};

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export type SimulationResult = {
  entry: number;
  stop: number;
  target: number;
  risk_amount: number;
  reward_amount: number;
  risk_reward: number;
};

export type NewsItem = {
  id: number;
  timestamp: string;
  asset: string | null;
  event_type: string;
  headline: string;
  source: string | null;
  sentiment: "bullish" | "bearish" | "neutral" | null;
  magnitude: number | null;
  interpreted: boolean;
};

export type JobStatusItem = {
  job_name: string;
  last_run_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  run_count: number;
  healthy: boolean;
};

export type PerformanceSummary = {
  trades: number;
  win_rate: number | null;
  expectancy_pct: number | null;
  profit_factor: number | null;
  sharpe: number | null;
  sortino: number | null;
  max_drawdown_pct: number | null;
  avg_win_pct: number | null;
  avg_loss_pct: number | null;
};

export type BacktestRun = {
  run_id: string;
  leader: string | null;
  follower: string | null;
  event_count: number;
  hit_rate: number | null;
  requested_window_days: number;
  leader_coverage_days: number;
  follower_coverage_days: number;
  coverage_status: "VALID" | "INSUFFICIENT";
};

export type BacktestEvent = {
  event_timestamp: string;
  leader_move_pct: number;
  predicted_move_pct: number;
  actual_move_pct: number;
  direction_correct: boolean;
  in_sample: boolean;
  r_squared_at_time: number | null;
};

export type BacktestRunDetail = {
  events: BacktestEvent[];
  performance: {
    overall: PerformanceSummary;
    in_sample: PerformanceSummary;
    out_of_sample: PerformanceSummary;
  };
};


export type OracleHistoryPoint = {
  timestamp: string;
  premium_pct: number | null;
  funding_rate: number | null;
  last_price: number | null;
  session_state: string | null;
};

export type OracleHistory = {
  symbol: string;
  points: OracleHistoryPoint[];
};

export type OpsHealth = {
  scheduler: {
    advisory_lock_enabled: boolean;
    lock_held: boolean | null;
    registered_jobs: string[];
  };
  jobs: JobStatusItem[];
  freshness: {
    latest_market_candle_at: string | null;
    latest_market_candle_age_s: number | null;
    latest_oracle_tick_at: string | null;
    latest_oracle_tick_age_s: number | null;
    latest_event_at: string | null;
    latest_event_age_s: number | null;
  };
  counts: {
    assets: number;
    open_signals: number;
    pass_signals: number;
    block_signals: number;
  };
  server_time: string;
};

export const api = {
  liveMarket: () => get<MarketTick[]>("/market/live"),
  regime: () => get<Regime>("/market/regime"),
  marketMap: () => get<MarketMapData>("/market/map"),
  signals: (status?: string) => get<Signal[]>(`/signals${status ? `?status=${status}` : ""}`),
  signal: (id: number) => get<Signal>(`/signals/${id}`),
  why: (id: number) => get<{ explanation: string }>(`/signals/${id}/why`),
  simulate: (id: number) => post<SimulationResult>(`/signals/${id}/simulate`),
  logDelivery: (id: number, eventType: "delivered" | "execution_clicked") =>
    post<{ logged: boolean }>(`/signals/${id}/deliver`, { event_type: eventType }),
  closeOutcome: (
    id: number,
    body: { actual_return_pct: number; result_summary?: string; correct_factors?: string[]; missed_factors?: string[] }
  ) => post<{ prediction_error_pct: number }>(`/outcomes/${id}/close`, body),
  news: (limit = 30) => get<NewsItem[]>(`/news/recent?limit=${limit}`),
  jobStatus: () => get<JobStatusItem[]>("/jobs/status"),
  triggerJob: (name: string) => post<{ triggered: string }>(`/jobs/trigger/${name}`),
  oracleState: (symbol: string) => get<OracleState>(`/oracle/${symbol}`),
  oracleSummary: () => get<OracleState[]>("/oracle"),
  backtestRuns: () => get<BacktestRun[]>("/backtest/runs"),
  backtestRunDetail: (runId: string) => get<BacktestRunDetail>(`/backtest/runs/${runId}`),
  oracleHistory: (symbol: string, limit = 60) =>
    get<OracleHistory>(`/oracle/history/${encodeURIComponent(symbol)}?limit=${limit}`),
  opsHealth: () => get<OpsHealth>("/jobs/health"),
};

