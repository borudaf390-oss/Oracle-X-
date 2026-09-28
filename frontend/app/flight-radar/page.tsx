"use client";

import { useEffect, useMemo, useState } from "react";
import { api, Signal } from "@/lib/api";
import { signalsToFlights, deriveFactors, FactorWeights, DEFAULT_WEIGHTS, EXCHANGE_HUBS } from "@/lib/globe";
import GlobeCanvas from "@/components/GlobeCanvas";

const FACTOR_LABELS: { key: keyof FactorWeights; label: string }[] = [
  { key: "alpha", label: "Alpha Score" },
  { key: "confidence", label: "Model Confidence" },
  { key: "displacement", label: "Displacement" },
  { key: "move", label: "Current Move" },
];

type DirectionFilter = "ALL" | "LONG" | "SHORT";
type RiskFilter = "ALL" | "PASS" | "BLOCK";

export default function FlightRadarPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [weights, setWeights] = useState<FactorWeights>(DEFAULT_WEIGHTS);
  const [direction, setDirection] = useState<DirectionFilter>("ALL");
  const [risk, setRisk] = useState<RiskFilter>("ALL");

  useEffect(() => {
    let mounted = true;
    api
      .signals()
      .then((s) => mounted && setSignals(s))
      .catch(() => {})
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, []);

  const filtered = useMemo(() => {
    return signals.filter((s) => {
      if (direction !== "ALL" && s.direction !== direction) return false;
      if (risk !== "ALL" && s.risk_status !== risk) return false;
      return true;
    });
  }, [signals, direction, risk]);

  const flights = useMemo(() => signalsToFlights(filtered, weights), [filtered, weights]);
  const ranked = useMemo(() => [...flights].sort((a, b) => b.norm - a.norm), [flights]);

  const axisLeaders = useMemo(() => {
    if (filtered.length === 0) return [];
    return FACTOR_LABELS.map(({ key, label }) => {
      let best = filtered[0];
      let bestVal = -1;
      filtered.forEach((s) => {
        const v = deriveFactors(s)[key];
        if (v > bestVal) {
          bestVal = v;
          best = s;
        }
      });
      return { label, ticker: best.asset, value: bestVal };
    });
  }, [filtered]);

  return (
    <div className="flow-layout">
      <div className="flow-map" style={{ position: "relative" }}>
        {flights.length > 0 ? (
          <GlobeCanvas flights={flights} />
        ) : (
          <div style={{ display: "flex", height: "100%", alignItems: "center", justifyContent: "center", fontSize: 13, color: "var(--text-muted)" }}>
            {loading ? "Loading…" : "No signals match this filter"}
          </div>
        )}
      </div>

      <div className="flow-side" style={{ overflowY: "auto" }}>
        <div className="panel-head"><span>Flight Radar</span></div>

        <div style={{ padding: "16px 20px 0" }}>
          <div className="why-label">Direction</div>
          <div className="chip-row" style={{ padding: "10px 0 4px", borderBottom: "none" }}>
            {(["ALL", "LONG", "SHORT"] as DirectionFilter[]).map((d) => (
              <button key={d} onClick={() => setDirection(d)} className={`filter-chip ${direction === d ? "active" : ""}`}>
                {d === "ALL" ? "All" : d}
              </button>
            ))}
          </div>

          <div className="why-label" style={{ marginTop: 10 }}>Risk gate</div>
          <div className="chip-row" style={{ padding: "10px 0 4px", borderBottom: "none" }}>
            {(["ALL", "PASS", "BLOCK"] as RiskFilter[]).map((r) => (
              <button key={r} onClick={() => setRisk(r)} className={`filter-chip ${risk === r ? "active" : ""}`}>
                {r === "ALL" ? "All" : r === "PASS" ? "Passed" : "Blocked"}
              </button>
            ))}
          </div>
        </div>

        <div style={{ padding: "14px 20px", borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <span className="why-label" style={{ margin: 0 }}>Factor weights</span>
            <button onClick={() => setWeights(DEFAULT_WEIGHTS)} style={{ fontSize: 10.5, color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer" }}>
              reset
            </button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {FACTOR_LABELS.map(({ key, label }) => (
              <div key={key}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: "var(--text-secondary)" }}>
                  <span>{label}</span>
                  <span className="mono up" style={{ fontWeight: 700 }}>{weights[key].toFixed(2)}</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={weights[key]}
                  onChange={(e) => setWeights((w) => ({ ...w, [key]: parseFloat(e.target.value) }))}
                  style={{ width: "100%", marginTop: 4 }}
                />
              </div>
            ))}
          </div>
        </div>

        <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)" }}>
          <div className="why-label" style={{ marginBottom: 8 }}>Axis leaders</div>
          <div className="mono" style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 11 }}>
            {axisLeaders.map((a) => (
              <div key={a.label} style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--text-secondary)" }}>{a.label}</span>
                <span className="up">{a.ticker} · {a.value.toFixed(2)}</span>
              </div>
            ))}
            {axisLeaders.length === 0 && <span style={{ color: "var(--text-muted)" }}>No signals yet</span>}
          </div>
        </div>

        <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)" }}>
          <div className="why-label" style={{ marginBottom: 8 }}>Top ranked</div>
          <div className="mono" style={{ display: "flex", flexDirection: "column", gap: 5, fontSize: 11 }}>
            {ranked.slice(0, 6).map((f, i) => (
              <div key={f.id} style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--text-secondary)" }}>{i + 1}. <span style={{ color: "var(--text-primary)" }}>{f.label}</span></span>
                <span className="up" style={{ fontWeight: 700 }}>{f.norm.toFixed(2)}</span>
              </div>
            ))}
            {ranked.length === 0 && <span style={{ color: "var(--text-muted)" }}>—</span>}
          </div>
        </div>

        <div className="mono" style={{ padding: "14px 20px", display: "flex", flexDirection: "column", gap: 5, fontSize: 11, color: "var(--text-secondary)" }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}><span>Active signals</span><span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{flights.length}</span></div>
          <div style={{ display: "flex", justifyContent: "space-between" }}><span>Exchanges connected</span><span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{EXCHANGE_HUBS.length}</span></div>
        </div>
      </div>
    </div>
  );
}
