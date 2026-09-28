// Exchange hub coordinates used by the Flight Radar globe, and helpers that
// derive a deterministic hub pair + factor scores from a real Signal coming
// back from the pipeline (GET /signals). No hub/factor metadata exists in
// the backend today, so this is an explicit, documented approximation —
// swap `hubsForAsset` for a real `signal.exchange` field once the backend
// exposes one.

export type ExchangeHub = { name: string; city: string; lat: number; lon: number; code: string };

export const EXCHANGE_HUBS: ExchangeHub[] = [
  { name: "NYSE / NASDAQ", city: "New York", lat: 40.7128, lon: -74.006, code: "NYC" },
  { name: "LSE", city: "London", lat: 51.5074, lon: -0.1278, code: "LON" },
  { name: "TSE", city: "Tokyo", lat: 35.6762, lon: 139.6503, code: "TYO" },
  { name: "XETRA", city: "Frankfurt", lat: 50.1109, lon: 8.6821, code: "FRA" },
  { name: "HKEX", city: "Hong Kong", lat: 22.3193, lon: 114.1694, code: "HKG" },
  { name: "SGX", city: "Singapore", lat: 1.3521, lon: 103.8198, code: "SIN" },
  { name: "ASX", city: "Sydney", lat: -33.8688, lon: 151.2093, code: "SYD" },
  { name: "TSX", city: "Toronto", lat: 43.6532, lon: -79.3832, code: "TOR" },
];

// Small deterministic string hash so the same asset always maps to the same
// hub pair across renders/reloads (not random per-mount).
function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h << 5) - h + s.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h);
}

export function hubsForAsset(asset: string): { from: number; to: number } {
  const h = hashString(asset);
  const from = h % EXCHANGE_HUBS.length;
  let to = (h >> 3) % EXCHANGE_HUBS.length;
  if (to === from) to = (to + 1) % EXCHANGE_HUBS.length;
  return { from, to };
}

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

// Derives 0..1 "factor" readings from fields that already exist on Signal,
// so the Flight Radar's weighting/ranking is computed from real pipeline
// output rather than fabricated numbers.
export type SignalFactors = { alpha: number; confidence: number; displacement: number; move: number };

export type FactorWeights = { alpha: number; confidence: number; displacement: number; move: number };

export const DEFAULT_WEIGHTS: FactorWeights = { alpha: 0.4, confidence: 0.25, displacement: 0.2, move: 0.15 };

export function scoreSignal(factors: SignalFactors, weights: FactorWeights): number {
  return (
    factors.alpha * weights.alpha +
    factors.confidence * weights.confidence +
    factors.displacement * weights.displacement +
    factors.move * weights.move
  );
}

function fmtPct(v: number | null | undefined) {
  if (v === null || v === undefined) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

export type FlowSignal = {
  id: number;
  asset: string;
  direction: "LONG" | "SHORT";
  alpha_score: number;
  confidence: number;
  displacement_pct: number | null;
  current_move_pct: number | null;
};

// Turns real Signal[] into GlobeCanvas-ready flight data, scored/normalized
// by the given factor weights. Kept independent of GlobeCanvas's own types
// so callers can filter/sort before rendering.
export function signalsToFlights(signals: FlowSignal[], weights: FactorWeights = DEFAULT_WEIGHTS) {
  const scored = signals.map((s) => {
    const factors = deriveFactors(s);
    const score = scoreSignal(factors, weights);
    const { from, to } = hubsForAsset(s.asset);
    return { signal: s, factors, score, from, to };
  });
  const maxScore = Math.max(...scored.map((s) => s.score), 0.0001);
  return scored.map(({ signal, score, from, to }) => ({
    id: signal.id,
    label: signal.asset,
    direction: signal.direction,
    changeLabel: fmtPct(signal.current_move_pct),
    from,
    to,
    norm: score / maxScore,
    score,
  }));
}

export function deriveFactors(s: {
  alpha_score: number;
  confidence: number;
  displacement_pct: number | null;
  current_move_pct: number | null;
}): SignalFactors {
  return {
    alpha: clamp01(s.alpha_score / 100),
    confidence: clamp01(s.confidence),
    displacement: clamp01(Math.abs(s.displacement_pct ?? 0) * 8),
    move: clamp01(Math.abs(s.current_move_pct ?? 0) * 8),
  };
}
