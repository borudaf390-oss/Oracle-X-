"use client";

import { useEffect, useMemo, useState } from "react";
import { api, OracleState, OracleHistory } from "@/lib/api";

function fmt(v: number | null | undefined, digits = 2, suffix = "") {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}${suffix}`;
}

function regimeClass(r?: string) {
  if (r === "DISLOCATED") return "fail";
  if (r === "ELEVATED") return "pending";
  return "pass";
}

/** Tiny inline sparkline from premium_pct series (no chart lib). */
function Sparkline({ values }: { values: (number | null)[] }) {
  const pts = values.filter((v): v is number => v != null && !Number.isNaN(v));
  if (pts.length < 2) {
    return <span style={{ fontSize: 11, color: "var(--text-muted)" }}>no history</span>;
  }
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const span = max - min || 1;
  const w = 120;
  const h = 28;
  const path = pts
    .map((v, i) => {
      const x = (i / (pts.length - 1)) * w;
      const y = h - ((v - min) / span) * (h - 2) - 1;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const last = pts[pts.length - 1];
  const color = last >= 0 ? "var(--signal)" : "var(--short)";
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block" }}>
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

export default function OraclePage() {
  const [rows, setRows] = useState<OracleState[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [history, setHistory] = useState<OracleHistory | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .oracleSummary()
      .then((data) => {
        setRows(data);
        if (data.length) setSelected(data[0].symbol ?? null);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selected) {
      setHistory(null);
      return;
    }
    api
      .oracleHistory(selected, 90)
      .then(setHistory)
      .catch(() => setHistory(null));
  }, [selected]);

  const selectedRow = useMemo(
    () => rows.find((r) => r.symbol === selected) ?? null,
    [rows, selected]
  );

  const dislocated = rows.filter((r) => r.regime === "DISLOCATED").length;
  const elevated = rows.filter((r) => r.regime === "ELEVATED").length;

  return (
    <>
      <div className="toolbar">
        <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 640, lineHeight: 1.5 }}>
          Bitget-native dislocation layer — premium vs index, mark basis, funding z-score, and
          session-conditioned extremity. Sorted by |premium z|. No external reference feed required.
        </p>
      </div>

      <div className="stats" style={{ marginBottom: 14 }}>
        <div className="stat">
          <div className="l">Assets tracked</div>
          <div className="v mono tabular">{rows.length}</div>
        </div>
        <div className="stat accent-glow">
          <div className="l">Dislocated</div>
          <div className="v mono tabular accent">{dislocated}</div>
        </div>
        <div className="stat">
          <div className="l">Elevated</div>
          <div className="v mono tabular">{elevated}</div>
        </div>
        <div className="stat">
          <div className="l">Normal</div>
          <div className="v mono tabular">{Math.max(0, rows.length - dislocated - elevated)}</div>
        </div>
      </div>

      {loading ? (
        <p style={{ fontSize: 13, color: "var(--text-muted)" }}>Loading…</p>
      ) : rows.length === 0 ? (
        <div className="panel" style={{ padding: 32, textAlign: "center" }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>No oracle ticks yet</div>
          <p style={{ fontSize: 12.5, color: "var(--text-secondary)", maxWidth: 420, margin: "0 auto" }}>
            The <code className="mono" style={{ fontSize: 11.5 }}>ingest_oracle_ticks</code> job
            (every 2 min) populates this view from Bitget last/index/mark/funding.
          </p>
        </div>
      ) : (
        <div className="playbook-layout">
          <div className="playbook-list">
            <div className="panel-head">
              <span>Dislocation leaderboard</span>
              <span style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 400 }}>by |z|</span>
            </div>
            <div className="playbook-list-body">
              {rows.map((r) => (
                <button
                  key={r.symbol}
                  className={`playbook-row ${r.symbol === selected ? "active" : ""}`}
                  onClick={() => setSelected(r.symbol ?? null)}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{r.symbol}</div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                        {r.session_state ?? "—"}
                        {r.session_conditioned ? " · session-adj" : ""}
                      </div>
                    </div>
                    <span className={`risk-badge ${regimeClass(r.regime)}`}>{r.regime ?? "—"}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 9, fontSize: 11 }} className="mono">
                    <span style={{ color: "var(--text-secondary)" }}>
                      z {fmt(r.premium_zscore, 2)} · prem {fmt(r.premium_pct != null ? r.premium_pct * 100 : null, 3, "%")}
                    </span>
                    <span style={{ color: "var(--text-muted)" }}>
                      fund z {fmt(r.funding_zscore, 2)}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="playbook-detail">
            {!selectedRow ? (
              <p style={{ fontSize: 13, color: "var(--text-muted)" }}>Select a symbol</p>
            ) : (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
                  <div>
                    <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>{selectedRow.symbol}</h2>
                    <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                      {selectedRow.session_state ?? "—"}
                      {selectedRow.session_conditioned ? " · z is session-conditioned" : " · pooled z"}
                    </div>
                  </div>
                  <span className={`risk-badge ${regimeClass(selectedRow.regime)}`}>{selectedRow.regime}</span>
                </div>

                <div className="grid2 mono" style={{ marginTop: 16 }}>
                  <div>
                    <div className="l">PREMIUM</div>
                    <div className={`v ${(selectedRow.premium_pct ?? 0) >= 0 ? "up" : "down"}`}>
                      {fmt(selectedRow.premium_pct != null ? selectedRow.premium_pct * 100 : null, 3, "%")}
                    </div>
                  </div>
                  <div>
                    <div className="l">PREMIUM Z</div>
                    <div className="v">{fmt(selectedRow.premium_zscore, 2)}</div>
                  </div>
                  <div>
                    <div className="l">PERCENTILE</div>
                    <div className="v">{fmt(selectedRow.premium_percentile, 1)}</div>
                  </div>
                  <div>
                    <div className="l">DURATION</div>
                    <div className="v">{fmt(selectedRow.premium_duration_minutes, 1, "m")}</div>
                  </div>
                  <div>
                    <div className="l">VELOCITY</div>
                    <div className="v">{fmt(selectedRow.premium_velocity, 4)}</div>
                  </div>
                  <div>
                    <div className="l">FUNDING Z</div>
                    <div className="v">{fmt(selectedRow.funding_zscore, 2)}</div>
                  </div>
                  <div>
                    <div className="l">FUNDING RATE</div>
                    <div className="v">{fmt(selectedRow.funding_rate != null ? selectedRow.funding_rate * 100 : null, 4, "%")}</div>
                  </div>
                  <div>
                    <div className="l">ORACLE FACTOR</div>
                    <div className="v">{fmt(selectedRow.oracle_regime_factor, 2)}</div>
                  </div>
                </div>

                <div style={{ marginTop: 18 }}>
                  <div className="why-label">Premium history</div>
                  <div style={{ marginTop: 8, padding: "10px 12px", background: "rgba(0,0,0,0.25)", borderRadius: 10 }}>
                    <Sparkline values={(history?.points ?? []).map((p) => p.premium_pct)} />
                    <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 6 }} className="mono">
                      {(history?.points?.length ?? 0)} ticks
                    </div>
                  </div>
                </div>

                <div className="grid2 mono" style={{ marginTop: 16 }}>
                  <div>
                    <div className="l">LAST</div>
                    <div className="v">{fmt(selectedRow.last_price, 4)}</div>
                  </div>
                  <div>
                    <div className="l">INDEX</div>
                    <div className="v">{fmt(selectedRow.index_price, 4)}</div>
                  </div>
                  <div>
                    <div className="l">MARK</div>
                    <div className="v">{fmt(selectedRow.mark_price, 4)}</div>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
